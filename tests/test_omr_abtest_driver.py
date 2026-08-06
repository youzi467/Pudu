# -*- coding: utf-8 -*-
"""P1-2 · T03 编排驱动单测（``tools/omr_abtest_p1_2.py``）。

被测对象是 A/B 实验**唯一有 I/O 的那一层**：建工作区、硬链接语料、调
oemer、调 harness、读 sidecar、断言不变量、写产物。本文件用**三合一替身**
（:class:`FakeHarness`）注入 ``oemer_fn`` / ``eval_fn`` / ``project_fn``，
因此可以**完整跑通 Stage-0~5 而不跑 oemer、不跑 Pudu、不需 GPU**——
这正是设计 §2.1 把「纯函数决策」与「有 I/O 编排」拆开的收益。

覆盖需求（对应 T03 验收口径）
-----------------------------
* **cell 规划**：7 arm × 2 打分 = 14 cell；``pc_off`` 恒排在同 arm 的
  ``pc_on`` 之前（后者依赖前者的 pred 缓存）；``--arms`` 白名单必须含基线。
* **工作区隔离（R5 / SK-6）**：每个 cell 一个目录，pred / 审计报告互不覆盖。
* **同页同 stem（SK-3）**：工作区里的文件名一律沿用原 stem，不加 cell 前缀。
* **缓存命中 / 未命中**：pred 存在**且非空**才算命中；命中跳过 oemer，
  ``--no-cache`` 强制重跑；0 字节残留视为未命中（断点续跑的正确性基础）。
* **降级标记透传（R3 / SK-5）**：metrics sidecar 的 ``degraded=true``
  必须一路透到 ``CellResult.preprocess`` 与 ``DeltaResult`` 的双口径。
* **Stage-3 不变量守护（R6）**：干净 GT 跑 ``--apply-postcorrect``，
  ``applied != 0`` 或报告缺失 ⇒ 整轮 FAIL。
* **透明性断言（R7）**：``pipe_noop`` 与 ``pre_off`` 不等价 ⇒ 阻断性发现。
* **SK-2**：所有 arm 一律带 ``--gt``（``gt_path`` 非空）。
* **SK-4**：打分侧 ``postcorrect_gt`` 恒 False。
* **SK-8**：``preprocess is None`` 的基线 arm 绝不携带 config / metrics。
* **Δ 参照系**：``*__pc_off`` 对照 ``pre_off__pc_off``；``*__pc_on`` 对照
  **同 arm 的** ``*__pc_off``。

运行开销的两个刻意取舍
----------------------
1. **共享只读夹具**：本机沙箱删一个文件约 16 ms，一次 14-cell 全流程会产生
   ~400 个文件（≈7 s 全花在 teardown 上）。因此模块级共享**一份语料**与
   **一次干净跑**（:class:`_SharedCleanRun`），只读断言全部复用；只有需要
   「不同替身行为」的用例才自己跑一遍。
2. **冒烟臂矩阵**：需要跑全流程的用例默认只用
   :data:`SMOKE_ARMS`（基线 + 透明性 + 一个 preset），足以覆盖全部接线路径；
   确实要验 14-cell 矩阵的用例显式传 ``arm_filter=()``。

本测试**不 import cv2 / numpy / scipy**（沿用 P0-2 规则，保证沙箱可收集），
也**不写仓库工作区**——所有产物落 :func:`tempfile.mkdtemp`。
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (HERE, TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _purity_probe import assert_import_is_pure  # noqa: E402

import omr_eval_groundtruth as G  # noqa: E402
import omr_abtest_lib as L  # noqa: E402
import omr_abtest_p1_2 as D  # noqa: E402
from omr_abtest_lib import (  # noqa: E402
    DecisionThresholds,
    BASELINE_ARM_ID, SANITY_ARM_ID, PROBE_ARM_ID, PC_OFF, PC_ON, cell_id_of,
)
from omr_abtest_p1_2 import AbtestDriver, build_config  # noqa: E402

#: 单测把 bootstrap 压到 200 次纯为提速；确定性由固定 seed 保证（SK-9）。
FAST_TH = DecisionThresholds(bootstrap_iters=200)

#: 模拟语料页（3 页足够覆盖「多页配对 + 单页降级 + 单页 fatal」三种形态）。
PAGES = ("p1", "p2", "p3")

#: 需要跑全流程时的默认臂集合：基线 + 透明性 sanity + 一个真 preset。
#: 这三条臂已覆盖驱动的全部分支（直调 / --no-preprocess / --preprocess-preset）。
SMOKE_ARMS = (BASELINE_ARM_ID, SANITY_ARM_ID, "pre_default")

MINIMAL_XML = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<score-partwise version="3.1"><part-list/></score-partwise>')

#: 每页固定分母，让 note_pass_rate 可以心算核对。
NOTES_PER_PAGE = 100
FIELDS_PER_PAGE = 60
BASE_CORRECT = 10  # 基线每页 10/100 => note_pass_rate = 10.00%

#: 模块级共享的只读语料（驱动只读语料、只往 work_root 写，故可安全共享）。
_SHARED_CORPUS = None
_SHARED_TMP = None


def make_corpus(root, pages=PAGES):
    """造一份符合 harness 约定①（``foo.jpg`` + ``foo.gt.musicxml``）的语料。"""
    os.makedirs(root, exist_ok=True)
    for base in pages:
        with open(os.path.join(root, base + ".jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + base.encode("ascii"))
        with open(os.path.join(root, base + ".gt.musicxml"), "w",
                  encoding="utf-8") as f:
            f.write(MINIMAL_XML)
    return root


def setUpModule():
    """建共享语料（只读）。"""
    global _SHARED_CORPUS, _SHARED_TMP
    _SHARED_TMP = tempfile.mkdtemp(prefix="p1_2_shared_")
    _SHARED_CORPUS = make_corpus(os.path.join(_SHARED_TMP, "corpus"))


def tearDownModule():
    """拆共享语料与共享跑（沙箱删文件很贵，集中一次做）。"""
    _SharedCleanRun.dispose()
    if _SHARED_TMP:
        shutil.rmtree(_SHARED_TMP, ignore_errors=True)


# ----------------------------------------------------------------------
# 三合一替身
# ----------------------------------------------------------------------

class FakeHarness(object):
    """``run_oemer`` / ``eval_corpus`` / ``pudu_jianpu_json`` 三合一替身。

    行为**刻意贴近真实 harness 的可观测契约**（写 pred、写 metrics sidecar、
    写后处理审计报告、缺 pred 记 fatal），这样驱动的接线错误才会被测出来，
    而不是被替身的宽容掩盖。

    Attributes:
        oemer_calls: ``run_oemer`` 的逐次调用快照（校验 argv 语义）。
        eval_calls: ``eval_corpus`` 的逐次调用快照。
        project_calls: ``pudu_jianpu_json`` 的逐次调用快照。
    """

    def __init__(self, *, bump_by_cell=None, page_bump=None,
                 degraded_by_arm=None, oemer_fail=(), applied_by_gt=None,
                 project_raise_on=()):
        """
        Args:
            bump_by_cell: ``{cell_id: 每页多对的音符数}``（造 Δ）。
            page_bump: ``{(cell_id, page): 增量}``（造逐页差异，喂符号检验）。
            degraded_by_arm: ``{arm_id: (降级页, ...)}``（造 SK-5 降级）。
            oemer_fail: 这些页的 oemer 直接返回 False（不写 pred ⇒ fatal）。
            applied_by_gt: ``{gt 文件名: appliedCount}``（造 R6 不变量违规）。
            project_raise_on: 这些 gt 文件名上 Pudu 抛异常。
        """
        self.bump_by_cell = dict(bump_by_cell or {})
        self.page_bump = dict(page_bump or {})
        self.degraded_by_arm = dict(degraded_by_arm or {})
        self.oemer_fail = set(oemer_fail)
        self.applied_by_gt = dict(applied_by_gt or {})
        self.project_raise_on = set(project_raise_on)
        self.oemer_calls = []
        self.eval_calls = []
        self.project_calls = []

    # —— Stage-1 替身 ——

    def run_oemer(self, image_path, out_musicxml, gt_path=None,
                  venv_python="", f3_geometric=False, *,
                  preprocess=None, preprocess_config=None,
                  preprocess_metrics=None):
        """替身 ``run_oemer``：签名与 harness 逐参数一致。"""
        base = os.path.splitext(os.path.basename(image_path))[0]
        arm_id = os.path.basename(os.path.dirname(out_musicxml))
        self.oemer_calls.append({
            "image": image_path, "out": out_musicxml, "gt_path": gt_path,
            "f3_geometric": f3_geometric, "preprocess": preprocess,
            "preprocess_config": preprocess_config,
            "preprocess_metrics": preprocess_metrics,
            "base": base, "arm_id": arm_id,
        })
        # SK-8 的驱动侧镜像断言：直调基线绝不携带 config / metrics。
        if preprocess is None and (preprocess_config or preprocess_metrics):
            raise ValueError(
                "SK-8: preprocess=None 时不得传 preprocess_config/metrics")
        if base in self.oemer_fail:
            return False
        os.makedirs(os.path.dirname(out_musicxml), exist_ok=True)
        with open(out_musicxml, "w", encoding="utf-8") as f:
            f.write(MINIMAL_XML)
        if preprocess_metrics:
            degraded = base in set(self.degraded_by_arm.get(arm_id, ()))
            os.makedirs(os.path.dirname(preprocess_metrics), exist_ok=True)
            with open(preprocess_metrics, "w", encoding="utf-8") as f:
                json.dump({
                    "src": image_path,
                    "dst": out_musicxml,
                    "preset": preprocess,
                    "degraded": degraded,
                    "degrade_reason": "cv2_missing" if degraded else "",
                    "deskew_decision": ("applied" if preprocess == "photo"
                                        else "disabled"),
                    "deskew_applied_deg": 0.8 if preprocess == "photo" else 0.0,
                    "ink_ratio_out": 0.11,
                    "total_ms": 123.4,
                }, f)
        return True

    # —— Stage-1/2 替身 ——

    def _correct(self, cell_id, base):
        value = (BASE_CORRECT
                 + int(self.bump_by_cell.get(cell_id, 0))
                 + int(self.page_bump.get((cell_id, base), 0)))
        return max(0, min(NOTES_PER_PAGE, value))

    def eval_corpus(self, corpus_dir, use_oemer=True, f3_geometric=False, *,
                    oemer_opts=None, project_opts=None, reuse_pred=False):
        """替身 ``eval_corpus``：只判「有没有 pred」并造分，不碰 Pudu。"""
        self.eval_calls.append({
            "corpus_dir": corpus_dir, "use_oemer": use_oemer,
            "f3_geometric": f3_geometric, "oemer_opts": oemer_opts,
            "project_opts": project_opts, "reuse_pred": reuse_pred,
        })
        cell_id = os.path.basename(os.path.abspath(corpus_dir))
        gts = sorted(f for f in os.listdir(corpus_dir)
                     if f.endswith(G.GT_SUFFIX))
        per_file = []
        fatal_files = []
        notes_compared = notes_correct = 0
        field_checked = field_failed = 0
        for gt in gts:
            base = gt[: -len(G.GT_SUFFIX)]
            pred = os.path.join(corpus_dir, base + ".pred.musicxml")
            if not (os.path.isfile(pred) and os.path.getsize(pred) > 0):
                fatal_files.append(base)
                per_file.append({"file": base,
                                 "fatal": "pred 缺失（reuse_pred）",
                                 "notes_compared": 0, "notes_correct": 0,
                                 "field_checked": 0, "field_failed": 0})
                continue
            correct = self._correct(cell_id, base)
            failed = 2 if correct <= BASE_CORRECT else 1
            per_file.append({
                "file": base, "fatal": None,
                "notes_compared": NOTES_PER_PAGE, "notes_correct": correct,
                "field_checked": FIELDS_PER_PAGE, "field_failed": failed,
            })
            notes_compared += NOTES_PER_PAGE
            notes_correct += correct
            field_checked += FIELDS_PER_PAGE
            field_failed += failed
            self._maybe_write_pc_report(project_opts, base)

        note_rate = (round(notes_correct * 100.0 / notes_compared, 2)
                     if notes_compared else 0.0)
        field_rate = (round((field_checked - field_failed) * 100.0
                            / field_checked, 2) if field_checked else 0.0)
        summary = {
            "files": len(gts),
            "notes_compared": notes_compared, "notes_correct": notes_correct,
            "field_checked": field_checked, "field_failed": field_failed,
            "note_pass_rate": note_rate, "field_pass_rate": field_rate,
            "category_pass": {"pitch_octave": note_rate,
                              "rhythm": round(note_rate + 1.0, 2)},
            "category_distribution": {
                "event_count": notes_compared,
                "pitch_octave": notes_compared - notes_correct},
            "fatal_files": fatal_files,
        }
        return {"summary": summary, "per_file": per_file}

    def _maybe_write_pc_report(self, project_opts, base):
        """postcorrect 开启且给了模板时，逐页写 P1-1 审计报告。"""
        if project_opts is None:
            return
        template = getattr(project_opts, "postcorrect_report", None)
        if not template or not getattr(project_opts, "postcorrect_pred", False):
            return
        path = template.replace(G.BASE_PLACEHOLDER, base)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"measuresReconciled": 4, "notesTouched": 3,
                       "appliedCount": 3, "flaggedCount": 1,
                       "applied": [{"kind": "key"}, {"kind": "rhythm"},
                                   {"kind": "rhythm"}],
                       "flagged": [{"kind": "tuplet"}]}, f)

    # —— Stage-3 替身 ——

    def pudu_jianpu_json(self, musicxml_path, *, postcorrect=False,
                         postcorrect_report=None):
        """替身 ``pudu_jianpu_json``：只落 P1-1 审计报告。"""
        name = os.path.basename(musicxml_path)
        self.project_calls.append({"musicxml": musicxml_path,
                                   "postcorrect": postcorrect,
                                   "postcorrect_report": postcorrect_report})
        if name in self.project_raise_on:
            raise RuntimeError(f"Pudu.exe 崩了: {name}")
        applied = int(self.applied_by_gt.get(name, 0))
        if postcorrect_report:
            os.makedirs(os.path.dirname(postcorrect_report), exist_ok=True)
            with open(postcorrect_report, "w", encoding="utf-8") as f:
                json.dump({"measuresReconciled": 2, "notesTouched": applied,
                           "appliedCount": applied, "flaggedCount": 0,
                           "applied": [{"kind": "key"}] * applied,
                           "flagged": []}, f)
        return {"ok": True}


# ----------------------------------------------------------------------
# 夹具
# ----------------------------------------------------------------------

def build_driver(work_root, fake, *, arm_filter=SMOKE_ARMS, limit=0,
                 deskew_probe=True, invariant_gt=None, invariant_expected=None,
                 thresholds=FAST_TH, run_id="t03", corpus=None):
    """按替身装配一个驱动（永远 ``with_env=False``，免去哈希 Pudu.exe）。

    替身语料只有 3 页、凑不出真机的 13 份红线清单，因此这里把
    ``invariant_expected`` 与替身 GT 清单**成对**下调为清单实际长度——
    驱动的硬断言要求二者必须同时注入，真实跑那条路径永远量 13 份（QA-1）。
    """
    corpus = corpus or _SHARED_CORPUS
    cfg = build_config(corpus_dir=corpus, work_root=work_root, run_id=run_id,
                       deskew_probe=deskew_probe, arm_filter=arm_filter,
                       thresholds=thresholds, with_env=False)
    if invariant_gt is None:
        invariant_gt = sorted(os.path.join(corpus, f)
                              for f in os.listdir(corpus)
                              if f.endswith(G.GT_SUFFIX))
    invariant_gt = list(invariant_gt)
    if invariant_expected is None:
        invariant_expected = len(invariant_gt)
    return AbtestDriver(cfg, oemer_fn=fake.run_oemer,
                        eval_fn=fake.eval_corpus,
                        project_fn=fake.pudu_jianpu_json,
                        invariant_gt=invariant_gt,
                        invariant_expected=invariant_expected, limit=limit,
                        verbose=False)


class _SharedCleanRun(object):
    """模块级共享的「一次干净全流程跑」，供所有只读断言复用。

    干净 = 无降级、无 fatal、``pipe_noop`` 与基线完全一致、不变量全过。
    只读断言复用它可以把 teardown 的文件删除开销摊薄到一次。
    """

    tmp = None
    driver = None
    fake = None
    summary = None

    @classmethod
    def get(cls):
        if cls.summary is None:
            cls.tmp = tempfile.mkdtemp(prefix="p1_2_clean_")
            cls.fake = FakeHarness()
            cls.driver = build_driver(os.path.join(cls.tmp, "work"), cls.fake,
                                      run_id="clean")
            cls.summary = cls.driver.run()
        return cls.driver, cls.fake, cls.summary

    @classmethod
    def dispose(cls):
        if cls.tmp:
            shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.tmp = cls.driver = cls.fake = cls.summary = None


class DriverTestBase(unittest.TestCase):
    """需要**自己跑一遍**的用例的基类：每个用例一个独立 work_root。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1_2_drv_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.corpus = _SHARED_CORPUS
        self.work_root = os.path.join(self.tmp, "work")

    def make_driver(self, fake=None, **kwargs):
        fake = fake or FakeHarness()
        return build_driver(self.work_root, fake, **kwargs), fake


class SharedRunTestBase(unittest.TestCase):
    """只读断言的基类：复用 :class:`_SharedCleanRun`，不产生任何新文件。"""

    @classmethod
    def setUpClass(cls):
        cls.driver, cls.fake, cls.summary = _SharedCleanRun.get()


# ----------------------------------------------------------------------
# Stage-0：配置与规划（零 I/O，天然廉价）
# ----------------------------------------------------------------------

class TestBuildConfig(unittest.TestCase):
    """``build_config`` 的 arm 组装、探针开关、白名单校验。"""

    def _cfg(self, **kw):
        kw.setdefault("corpus_dir", _SHARED_CORPUS)
        kw.setdefault("work_root", os.path.join(_SHARED_TMP, "cfg"))
        kw.setdefault("run_id", "cfg")
        kw.setdefault("with_env", False)
        return build_config(**kw)

    def test_default_has_seven_arms_and_fourteen_cells(self):
        cfg = self._cfg()
        self.assertEqual(len(cfg.arms), 7, "6 arm + 1 个 U7 探针")
        self.assertEqual(len(cfg.plan_cells()), 14, "7 arm × 2 打分")
        self.assertEqual(cfg.baseline_cell, cell_id_of(BASELINE_ARM_ID, PC_OFF))

    def test_arm_ids_match_design(self):
        """设计 §2.2 钉死的 6 条主臂，一条不能少、一条不能多。"""
        cfg = self._cfg(deskew_probe=False)
        self.assertEqual([a.arm_id for a in cfg.arms],
                         [BASELINE_ARM_ID, SANITY_ARM_ID, "pre_default",
                          "pre_scan", "pre_photo", "pre_low_contrast"])

    def test_probe_arm_carries_probe_config(self):
        """U7：探针 arm 必须挂上 ``omr_abtest_photo_nodeskew.json``。"""
        probe = [a for a in self._cfg().arms if a.arm_id == PROBE_ARM_ID]
        self.assertEqual(len(probe), 1)
        self.assertEqual(probe[0].preprocess, "photo")
        self.assertEqual(probe[0].preprocess_config, D.PROBE_CONFIG)
        self.assertTrue(os.path.isfile(D.PROBE_CONFIG),
                        "探针配置文件必须真实存在，否则该 arm 会静默退化成 photo")

    def test_probe_off_gives_twelve_cells(self):
        cfg = self._cfg(deskew_probe=False)
        self.assertEqual(len(cfg.arms), 6)
        self.assertEqual(len(cfg.plan_cells()), 12, "设计 §2.2 的 12 cell 主矩阵")

    def test_arm_filter_keeps_only_wanted(self):
        cfg = self._cfg(arm_filter=[BASELINE_ARM_ID, "pre_scan"])
        self.assertEqual([a.arm_id for a in cfg.arms],
                         [BASELINE_ARM_ID, "pre_scan"])

    def test_arm_filter_without_baseline_raises(self):
        """没有基线就没有参照系，宁可拒绝跑，也不出无意义的 Δ。"""
        with self.assertRaises(ValueError) as ctx:
            self._cfg(arm_filter=["pre_scan"])
        self.assertIn(BASELINE_ARM_ID, str(ctx.exception))

    def test_arm_filter_all_unknown_raises(self):
        with self.assertRaises(ValueError):
            self._cfg(arm_filter=["nope"])

    def test_default_run_id_is_timestamped(self):
        cfg = self._cfg(run_id=None)
        self.assertTrue(cfg.run_id.startswith("p1_2_"))
        self.assertTrue(cfg.work_root.endswith(cfg.run_id),
                        "产物必须落 work_root/<run_id>，多轮实验才不会互相覆盖")

    def test_with_env_false_leaves_fingerprint_empty(self):
        cfg = self._cfg()
        self.assertEqual(cfg.env.pudu_exe_sha256, "")
        self.assertEqual(cfg.env.git_head, "")

    def test_thresholds_default_matches_u1(self):
        """U1 已拍板：驱动不得偷偷改阈值默认值。"""
        th = self._cfg().thresholds
        self.assertEqual(th.min_note_pass_gain_pp, 1.0)
        self.assertEqual(th.min_field_pass_gain_pp, 1.0)
        self.assertEqual(th.max_category_regress_pp, 1.0)
        self.assertEqual(th.min_improved_pages, 5)
        self.assertEqual(th.max_worsened_pages, 1)
        self.assertTrue(th.require_zero_degraded)
        self.assertEqual(th.postcorrect_min_field_gain_pp, 0.5)
        self.assertEqual(th.bootstrap_seed, 20260801)


class TestPairsAndPlan(DriverTestBase):
    """语料发现与 cell 矩阵展开（只读语料，不跑流程）。"""

    def test_pairs_discovers_all_pages_sorted(self):
        driver, _ = self.make_driver()
        self.assertEqual([b for _i, _g, b in driver.pairs()], list(PAGES))

    def test_pairs_respects_limit(self):
        driver, _ = self.make_driver(limit=2)
        self.assertEqual([b for _i, _g, b in driver.pairs()], ["p1", "p2"])

    def test_pairs_are_cached(self):
        driver, _ = self.make_driver()
        self.assertIs(driver.pairs(), driver.pairs())

    def test_empty_corpus_raises(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        cfg = build_config(corpus_dir=empty, work_root=self.work_root,
                           run_id="t", with_env=False)
        with self.assertRaises(RuntimeError):
            AbtestDriver(cfg, verbose=False).pairs()

    def test_pc_off_precedes_pc_on_within_arm(self):
        """``pc_on`` 复用同 arm 的 pred，顺序反了会读到空缓存。"""
        driver, _ = self.make_driver(arm_filter=())
        ids = [p.cell_id for p in driver.plan()]
        for arm in [a.arm_id for a in driver.config.arms]:
            self.assertLess(ids.index(cell_id_of(arm, PC_OFF)),
                            ids.index(cell_id_of(arm, PC_ON)),
                            f"{arm}: pc_off 必须排在 pc_on 之前")

    def test_needs_oemer_only_for_pc_off(self):
        driver, _ = self.make_driver(arm_filter=())
        for plan in driver.plan():
            self.assertEqual(plan.needs_oemer, not plan.score.postcorrect,
                             f"{plan.cell_id}: 后处理不改 pred，无需重跑 oemer")

    def test_cell_dirs_are_unique(self):
        """SK-6 的规划期前置条件：14 个 cell 目录两两不同。"""
        driver, _ = self.make_driver(arm_filter=())
        dirs = [p.workspace_dir for p in driver.plan()]
        self.assertEqual(len(dirs), len(set(dirs)))

    def test_cache_dir_is_shared_within_arm(self):
        """同 arm 的 pc_off / pc_on 必须指向**同一份** pred 缓存。"""
        driver, _ = self.make_driver(arm_filter=())
        by_cell = {p.cell_id: p.cache_dir for p in driver.plan()}
        for arm in [a.arm_id for a in driver.config.arms]:
            self.assertEqual(by_cell[cell_id_of(arm, PC_OFF)],
                             by_cell[cell_id_of(arm, PC_ON)])

    def test_manifest_records_everything_needed_to_reproduce(self):
        driver, _ = self.make_driver(arm_filter=())
        with open(driver.write_manifest(), "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schema"], L.SCHEMA)
        self.assertEqual(data["pages"], list(PAGES))
        self.assertEqual(len(data["cells"]), 14)
        self.assertEqual(data["baseline_cell"],
                         cell_id_of(BASELINE_ARM_ID, PC_OFF))
        self.assertEqual(data["thresholds"]["bootstrap_seed"], 20260801,
                         "SK-9：seed 必须落 manifest，否则结论不可复现")
        self.assertIn("invariant_gt", data)


# ----------------------------------------------------------------------
# Stage-1：OMR sweep 与 pred 缓存（每个用例只 warm 1 条臂，很便宜）
# ----------------------------------------------------------------------

class TestWarmArm(DriverTestBase):
    """断点续跑的全部秘密：``cache/<arm>/<base>.pred.musicxml`` 存在且非空。"""

    def setUp(self):
        super(TestWarmArm, self).setUp()
        self.driver, self.fake = self.make_driver(arm_filter=())

    def arm(self, arm_id):
        return [a for a in self.driver.config.arms if a.arm_id == arm_id][0]

    def test_cold_run_calls_oemer_for_every_page(self):
        ran = self.driver.warm_arm(self.arm(BASELINE_ARM_ID))
        self.assertEqual(sorted(ran), list(PAGES))
        self.assertTrue(all(ran.values()))
        self.assertEqual(len(self.fake.oemer_calls), len(PAGES))
        for base in PAGES:
            self.assertTrue(os.path.isfile(
                self.driver.pred_path(BASELINE_ARM_ID, base)))

    def test_second_run_hits_cache_and_skips_oemer(self):
        arm = self.arm(BASELINE_ARM_ID)
        self.driver.warm_arm(arm)
        self.fake.oemer_calls = []
        ran = self.driver.warm_arm(arm)
        self.assertEqual(self.fake.oemer_calls, [],
                         "命中缓存必须一次 oemer 都不跑（65 s/页 -> 0 s）")
        self.assertFalse(any(ran.values()))

    def test_force_reruns_despite_cache(self):
        arm = self.arm(BASELINE_ARM_ID)
        self.driver.warm_arm(arm)
        self.fake.oemer_calls = []
        self.driver.warm_arm(arm, force=True)
        self.assertEqual(len(self.fake.oemer_calls), len(PAGES))

    def test_zero_byte_pred_counts_as_miss(self):
        """跑挂留下的 0 字节残骸不能被误判成命中，否则该页永远缺 pred。"""
        arm = self.arm(BASELINE_ARM_ID)
        self.driver.warm_arm(arm)
        with open(self.driver.pred_path(BASELINE_ARM_ID, "p3"), "w",
                  encoding="utf-8"):
            pass
        self.fake.oemer_calls = []
        ran = self.driver.warm_arm(arm)
        self.assertEqual([c["base"] for c in self.fake.oemer_calls], ["p3"])
        self.assertTrue(ran["p3"])

    def test_baseline_arm_never_carries_preprocess_args(self):
        """SK-8：直调 arm 一旦带 config/metrics，harness 会抛 ValueError。"""
        self.driver.warm_arm(self.arm(BASELINE_ARM_ID))
        for call in self.fake.oemer_calls:
            self.assertIsNone(call["preprocess"])
            self.assertIsNone(call["preprocess_config"])
            self.assertIsNone(call["preprocess_metrics"])

    def test_preset_arm_writes_metrics_sidecar(self):
        """SK-5：没有 sidecar 就看不见降级，preset arm 必须逐页落。"""
        self.driver.warm_arm(self.arm("pre_scan"))
        for call in self.fake.oemer_calls:
            self.assertEqual(call["preprocess"], "scan")
            self.assertTrue(call["preprocess_metrics"].endswith(
                call["base"] + ".metrics.json"))
        for base in PAGES:
            self.assertTrue(os.path.isfile(
                self.driver.metrics_path("pre_scan", base)))

    def test_probe_arm_passes_config_override(self):
        self.driver.warm_arm(self.arm(PROBE_ARM_ID))
        self.assertTrue(self.fake.oemer_calls)
        for call in self.fake.oemer_calls:
            self.assertEqual(call["preprocess"], "photo")
            self.assertEqual(call["preprocess_config"], D.PROBE_CONFIG)

    def test_noop_arm_uses_off_not_none(self):
        """``pipe_noop`` 走 omr_pipeline.py --no-preprocess，不是直调。"""
        self.driver.warm_arm(self.arm(SANITY_ARM_ID))
        self.assertTrue(all(c["preprocess"] == "off"
                            for c in self.fake.oemer_calls))

    def test_every_arm_passes_gt(self):
        """SK-2：所有 arm 一律带 ``--gt``，否则调号后处理口径不一致。"""
        for arm in self.driver.config.arms:
            self.driver.warm_arm(arm)
        self.assertEqual(len(self.fake.oemer_calls), 7 * len(PAGES))
        for call in self.fake.oemer_calls:
            self.assertTrue(call["gt_path"])
            self.assertTrue(os.path.isfile(call["gt_path"]))

    def test_f3_geometric_is_off_everywhere(self):
        """F3 已证零效果（plan §8），A/B 必须把它钉死在 False。"""
        for arm in self.driver.config.arms:
            self.driver.warm_arm(arm)
        self.assertTrue(all(c["f3_geometric"] is False
                            for c in self.fake.oemer_calls))

    def test_oemer_failure_is_recorded_not_raised(self):
        """SK-10：单页失败不炸整轮，留给打分阶段记 fatal。"""
        driver, _ = self.make_driver(FakeHarness(oemer_fail=("p2",)),
                                     arm_filter=())
        ran = driver.warm_arm(
            [a for a in driver.config.arms if a.arm_id == BASELINE_ARM_ID][0])
        self.assertFalse(ran["p2"])
        self.assertTrue(ran["p1"])
        self.assertFalse(os.path.isfile(driver.pred_path(BASELINE_ARM_ID,
                                                         "p2")))

    def test_cache_is_per_arm(self):
        """不同 arm 的 pred 必须落不同目录，否则 A/B 直接串味。"""
        self.driver.warm_arm(self.arm(BASELINE_ARM_ID))
        self.driver.warm_arm(self.arm("pre_scan"))
        self.assertNotEqual(self.driver.cache_dir(BASELINE_ARM_ID),
                            self.driver.cache_dir("pre_scan"))
        self.assertTrue(os.path.isfile(self.driver.pred_path("pre_scan", "p1")))


# ----------------------------------------------------------------------
# 工作区隔离
# ----------------------------------------------------------------------

class TestWorkspace(DriverTestBase):
    """R5 / SK-3 / SK-6：cell 之间物理隔离，页内文件名保持同一 stem。"""

    def setUp(self):
        super(TestWorkspace, self).setUp()
        self.driver, self.fake = self.make_driver(
            arm_filter=[BASELINE_ARM_ID, "pre_default"])
        self.plans = {p.cell_id: p for p in self.driver.plan()}

    def test_workspace_contains_image_gt_and_pred(self):
        self.driver.warm_arm(self.driver.config.arms[0])
        ws = self.driver.prepare_workspace(
            self.plans[cell_id_of(BASELINE_ARM_ID, PC_OFF)])
        names = set(os.listdir(ws))
        for base in PAGES:
            self.assertIn(base + ".jpg", names)
            self.assertIn(base + G.GT_SUFFIX, names)
            self.assertIn(base + ".pred.musicxml", names)

    def test_stem_is_preserved_without_cell_prefix(self):
        """SK-3：per-page 配对靠 stem 做主键，改名等于把配对全打散。"""
        self.driver.warm_arm(self.driver.config.arms[0])
        plan = self.plans[cell_id_of(BASELINE_ARM_ID, PC_OFF)]
        ws = self.driver.prepare_workspace(plan)
        for name in os.listdir(ws):
            self.assertFalse(name.startswith(plan.cell_id),
                             f"{name}: 工作区文件名不得带 cell 前缀")
            self.assertTrue(any(name.startswith(b) for b in PAGES),
                            f"{name}: 文件名必须沿用原 stem")

    def test_cells_do_not_share_directories(self):
        """SK-6：两个 arm 的同名 pred 必须内容独立、互不覆盖。"""
        for arm in self.driver.config.arms:
            self.driver.warm_arm(arm)
        ws0 = self.driver.prepare_workspace(
            self.plans[cell_id_of(BASELINE_ARM_ID, PC_OFF)])
        ws1 = self.driver.prepare_workspace(
            self.plans[cell_id_of("pre_default", PC_OFF)])
        self.assertNotEqual(os.path.abspath(ws0), os.path.abspath(ws1))
        a = os.path.join(ws0, "p1.pred.musicxml")
        b = os.path.join(ws1, "p1.pred.musicxml")
        self.assertTrue(os.path.isfile(a) and os.path.isfile(b))
        self.assertFalse(os.path.samefile(a, b),
                         "不同 arm 的 pred 若共用 inode，A/B 结果会互相污染")

    def test_missing_pred_is_not_linked(self):
        """缺 pred 的页留白，交给 harness 记 fatal（绝不静默回退跑 oemer）。"""
        driver, _ = self.make_driver(FakeHarness(oemer_fail=("p2",)),
                                     arm_filter=[BASELINE_ARM_ID])
        driver.warm_arm(driver.config.arms[0])
        ws = driver.prepare_workspace(driver.plan()[0])
        self.assertFalse(os.path.isfile(os.path.join(ws, "p2.pred.musicxml")))
        self.assertTrue(os.path.isfile(os.path.join(ws, "p1.pred.musicxml")))

    def test_prepare_is_idempotent(self):
        self.driver.warm_arm(self.driver.config.arms[0])
        plan = self.plans[cell_id_of(BASELINE_ARM_ID, PC_OFF)]
        first = sorted(os.listdir(self.driver.prepare_workspace(plan)))
        second = sorted(os.listdir(self.driver.prepare_workspace(plan)))
        self.assertEqual(first, second)

    def test_pc_on_reuses_same_arm_pred(self):
        """后处理只作用于投影层：pc_on 不得重跑 oemer，直接吃同 arm 的 pred。"""
        self.driver.warm_arm(self.driver.config.arms[0])
        self.fake.oemer_calls = []
        ws = self.driver.prepare_workspace(
            self.plans[cell_id_of(BASELINE_ARM_ID, PC_ON)])
        self.assertEqual(self.fake.oemer_calls, [])
        self.assertTrue(os.path.isfile(os.path.join(ws, "p1.pred.musicxml")))


# ----------------------------------------------------------------------
# Stage-2：打分接线
# ----------------------------------------------------------------------

class TestScoreCell(DriverTestBase):
    """harness 调用形态：``reuse_pred`` 恒 True、SK-4 恒 False。"""

    def setUp(self):
        super(TestScoreCell, self).setUp()
        self.driver, self.fake = self.make_driver(arm_filter=())
        self.plans = {p.cell_id: p for p in self.driver.plan()}

    def _run_cells(self, arm_id, suffixes=(PC_OFF,)):
        arm = [a for a in self.driver.config.arms if a.arm_id == arm_id][0]
        self.driver.warm_arm(arm)
        for suffix in suffixes:
            self.driver.score_cell(self.plans[cell_id_of(arm_id, suffix)])

    def test_reuse_pred_is_always_true(self):
        self._run_cells(BASELINE_ARM_ID, (PC_OFF, PC_ON))
        self.assertEqual(len(self.fake.eval_calls), 2)
        for call in self.fake.eval_calls:
            self.assertTrue(call["reuse_pred"],
                            "pred 已由 warm_arm 备妥，打分阶段绝不重跑 oemer")

    def test_postcorrect_gt_is_never_enabled(self):
        """🔴 SK-4：gt 侧投影永不加 ``--apply-postcorrect``。"""
        self._run_cells(BASELINE_ARM_ID, (PC_OFF, PC_ON))
        for call in self.fake.eval_calls:
            self.assertFalse(call["project_opts"].postcorrect_gt)

    def test_project_opts_track_score_spec(self):
        self._run_cells(BASELINE_ARM_ID, (PC_OFF, PC_ON))
        off, on = self.fake.eval_calls
        self.assertFalse(off["project_opts"].postcorrect_pred)
        self.assertIsNone(off["project_opts"].postcorrect_report)
        self.assertTrue(on["project_opts"].postcorrect_pred)
        self.assertIn(G.BASE_PLACEHOLDER, on["project_opts"].postcorrect_report)

    def test_report_dir_lives_inside_cell_workspace(self):
        """SK-6：审计报告必须落各自 cell 目录，否则 pc_on 之间互相覆盖。"""
        self._run_cells(BASELINE_ARM_ID, (PC_ON,))
        self._run_cells("pre_scan", (PC_ON,))
        paths = [c["project_opts"].postcorrect_report
                 for c in self.fake.eval_calls]
        self.assertEqual(len(set(paths)), 2)
        self.assertIn(cell_id_of(BASELINE_ARM_ID, PC_ON), paths[0])
        self.assertIn(cell_id_of("pre_scan", PC_ON), paths[1])

    def test_oemer_opts_mirror_arm_spec(self):
        self._run_cells("pre_photo")
        opts = self.fake.eval_calls[-1]["oemer_opts"]
        self.assertEqual(opts.preprocess, "photo")
        self.assertFalse(opts.f3_geometric)
        self.assertIn(G.BASE_PLACEHOLDER, opts.preprocess_metrics)

    def test_baseline_oemer_opts_have_no_metrics_template(self):
        self._run_cells(BASELINE_ARM_ID)
        opts = self.fake.eval_calls[-1]["oemer_opts"]
        self.assertIsNone(opts.preprocess)
        self.assertIsNone(opts.preprocess_metrics)
        self.assertIsNone(opts.preprocess_config)

    def test_harness_report_is_persisted(self):
        arm = self.driver.config.arms[0]
        self.driver.warm_arm(arm)
        plan = self.plans[cell_id_of(arm.arm_id, PC_OFF)]
        result = self.driver.score_cell(plan)
        path = os.path.join(self.driver.cell_dir(plan.cell_id),
                            D.HARNESS_REPORT_NAME)
        self.assertTrue(os.path.isfile(path))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["summary"], result["summary"])


# ----------------------------------------------------------------------
# Stage-3：不变量守护
# ----------------------------------------------------------------------

class TestInvariantGuard(DriverTestBase):
    """🔴 R6：干净 GT 上 ``applied`` 必须恒为 0。"""

    def test_clean_gt_passes(self):
        driver, fake = self.make_driver()
        result = driver.run_invariant()
        self.assertTrue(result.passed)
        self.assertEqual(result.gt_files_checked, len(PAGES))
        self.assertEqual(result.violations, ())
        self.assertTrue(all(c["postcorrect"] for c in fake.project_calls),
                        "Stage-3 的意义就是把后处理开在干净 GT 上做反证")

    def test_nonzero_applied_fails_the_round(self):
        driver, _ = self.make_driver(
            FakeHarness(applied_by_gt={"p3.gt.musicxml": 2}))
        result = driver.run_invariant()
        self.assertFalse(result.passed)
        self.assertEqual(result.applied_per_file["p3.gt.musicxml"], 2)
        self.assertTrue(any("p3.gt.musicxml" in v for v in result.violations))

    def test_pudu_crash_counts_as_violation(self):
        """跑不出报告 = 无法自证清白，同样按违规处理。"""
        driver, _ = self.make_driver(
            FakeHarness(project_raise_on=("p2.gt.musicxml",)))
        result = driver.run_invariant()
        self.assertFalse(result.passed)
        self.assertEqual(result.applied_per_file["p2.gt.musicxml"], -1)

    def test_reports_land_in_invariant_dir(self):
        driver, _ = self.make_driver()
        driver.run_invariant()
        self.assertEqual(sorted(os.listdir(driver.invariant_dir)),
                         sorted(b + ".gt.musicxml.report.json" for b in PAGES))

    def test_real_coverage_is_pages_plus_seven_p1_1_files(self):
        """真实清单：语料页 GT + 7 份 P1-1 语料（真机即 6 + 7 = 13 份）。"""
        driver, _ = self.make_driver()
        driver._invariant_gt = None  # 强制走真实发现逻辑
        files = driver.invariant_gt_files()
        from_corpus = [f for f in files
                       if os.path.dirname(f) == os.path.abspath(self.corpus)]
        self.assertEqual(len(from_corpus), len(PAGES))
        present = [n for n in D.P1_1_CLEAN_GT
                   if os.path.isfile(os.path.join(REPO_ROOT, "data", n))]
        self.assertEqual(len(present), 7,
                         "test_jianpu_postcorrect.cpp 的 7 个 PC_CORPUS_TEST")
        self.assertEqual(len(files), len(PAGES) + len(present))

    def test_report_only_recovers_invariant_from_disk(self):
        """改阈值重跑决策时，不必再启动 Pudu 复跑守护。"""
        driver, fake = self.make_driver()
        driver.run()
        calls = len(fake.project_calls)
        result = driver.report_only()
        self.assertEqual(len(fake.project_calls), calls,
                         "report_only 必须从磁盘复读不变量报告")
        self.assertTrue(result.invariant.passed)
        self.assertEqual(result.invariant.gt_files_checked, len(PAGES))


class TestInvariantCoverageIsImmune(DriverTestBase):
    """🔴 QA-1：Stage-3 红线份数不受 ``--limit`` 影响，也不许被单独调低。"""

    def test_limit_does_not_shrink_the_redline(self):
        """``--limit 1`` 只截打分语料，不变量仍跑满全部干净 GT。"""
        driver, fake = self.make_driver(limit=1)
        self.assertEqual(len(driver.pairs()), 1, "打分语料应被 --limit 截断")
        result = driver.run_invariant()
        self.assertEqual(result.gt_files_checked, len(PAGES),
                         "--limit 撼动了 Stage-3 红线清单")
        self.assertEqual(len(fake.project_calls), len(PAGES))
        self.assertTrue(result.passed)

    def test_real_corpus_path_always_measures_thirteen(self):
        """不注入替身清单时，规范份数恒为 13——``--limit`` 也改不了。"""
        cfg = build_config(corpus_dir=self.corpus, work_root=self.work_root,
                           run_id="real", arm_filter=SMOKE_ARMS,
                           thresholds=FAST_TH, with_env=False)
        for limit in (0, 1, 2):
            with self.subTest(limit=limit):
                real = AbtestDriver(cfg, limit=limit, verbose=False)
                self.assertEqual(real.invariant_expected,
                                 L.INVARIANT_EXPECTED_GT)

    def test_lowering_expected_alone_is_rejected(self):
        """硬断言：不注入替身 GT 清单就想调低份数 ⇒ 直接 ValueError。"""
        cfg = build_config(corpus_dir=self.corpus, work_root=self.work_root,
                           run_id="guard", arm_filter=SMOKE_ARMS,
                           thresholds=FAST_TH, with_env=False)
        with self.assertRaises(ValueError) as ctx:
            AbtestDriver(cfg, invariant_expected=1, verbose=False)
        self.assertIn("invariant_gt", str(ctx.exception))

    def test_cli_exposes_no_coverage_override(self):
        """CLI 不得给出任何调低红线份数的入口（与 SK-4 同一守法）。"""
        with open(D.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        for flag in ("--invariant-expected", "--invariant-gt",
                     "--expected-gt"):
            self.assertNotIn(flag, source, f"CLI 暴露了红线旁路：{flag}")


# ----------------------------------------------------------------------
# Stage-4/5：干净跑的只读断言（共享一次全流程）
# ----------------------------------------------------------------------

class TestCleanRun(SharedRunTestBase):
    """一次干净全流程跑出来的产物、Δ 参照系、聚合口径。"""

    def test_all_artifacts_are_written(self):
        for name in (D.MANIFEST_NAME, D.SUMMARY_NAME, D.REPORT_NAME):
            path = os.path.join(self.driver.run_dir, name)
            self.assertTrue(os.path.isfile(path), f"缺产物: {name}")
            self.assertGreater(os.path.getsize(path), 0)

    def test_summary_json_is_schema_tagged_and_serializable(self):
        with open(os.path.join(self.driver.run_dir, D.SUMMARY_NAME), "r",
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schema"], L.SCHEMA)
        self.assertEqual(len(data["cells"]), len(self.driver.plan()))
        json.dumps(self.summary.to_json())  # 不得抛 TypeError

    def test_markdown_report_states_confidence(self):
        """SK-11：报告必须显式给出置信度，禁止把 directional 说成已验证。"""
        with open(os.path.join(self.driver.run_dir, D.REPORT_NAME), "r",
                  encoding="utf-8") as f:
            md = f.read()
        self.assertIn("confidence", md.lower())

    def test_delta_reference_frames(self):
        """``pc_off`` 对基线，``pc_on`` 对同 arm 的 ``pc_off``（设计 §6.1）。"""
        by_cell = {d.cell_id: d.baseline_cell_id for d in self.summary.deltas}
        baseline = cell_id_of(BASELINE_ARM_ID, PC_OFF)
        self.assertNotIn(baseline, by_cell, "基线自己不产生 Δ")
        for arm in [a.arm_id for a in self.driver.config.arms]:
            if arm != BASELINE_ARM_ID:
                self.assertEqual(by_cell[cell_id_of(arm, PC_OFF)], baseline)
            self.assertEqual(by_cell[cell_id_of(arm, PC_ON)],
                             cell_id_of(arm, PC_OFF),
                             "后处理 Δ 必须同 arm 内比，才能单变量归因")

    def test_every_planned_cell_is_collected(self):
        self.assertEqual([c.cell_id for c in self.summary.cells],
                         [p.cell_id for p in self.driver.plan()])

    def test_oemer_runs_once_per_arm_not_per_cell(self):
        """洞察 1：后处理不改 pred，oemer 只跑 ``len(arms)`` 轮而非 cell 数轮。"""
        self.assertEqual(len(self.fake.oemer_calls),
                         len(self.driver.config.arms) * len(PAGES))

    def test_clean_run_has_no_degraded_or_fatal(self):
        for cell in self.summary.cells:
            self.assertEqual(cell.preprocess.degraded_pages, (),
                             f"{cell.cell_id}: 替身未造降级，不应出现降级页")
            self.assertEqual(cell.fatal_files, ())
            self.assertTrue(cell.comparable)

    def test_transparency_holds_when_identical(self):
        self.assertFalse(any("R7" in f
                             for f in self.summary.decision.blocking_findings))

    def test_invariant_passed(self):
        self.assertTrue(self.summary.invariant.passed)
        self.assertEqual(self.summary.invariant.violations, ())

    def test_postcorrect_reports_are_aggregated(self):
        cells = self.summary.cell_map()
        on = cells[cell_id_of(BASELINE_ARM_ID, PC_ON)]
        off = cells[cell_id_of(BASELINE_ARM_ID, PC_OFF)]
        self.assertEqual(on.postcorrect_stats.applied_total, 3 * len(PAGES))
        self.assertEqual(on.postcorrect_stats.by_kind.get("rhythm"),
                         2 * len(PAGES))
        self.assertEqual(off.postcorrect_stats.applied_total, 0,
                         "pc_off cell 不该有任何审计报告")

    def test_print_verdict_emits_three_key_lines(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            D.print_verdict(self.summary)
        out = buf.getvalue()
        self.assertIn("preprocess_default", out)
        self.assertIn("postcorrect_default", out)
        self.assertIn("confidence", out)


# ----------------------------------------------------------------------
# Stage-4/5：需要特定替身行为的用例（各自跑一遍）
# ----------------------------------------------------------------------

class TestAggregateEdgeCases(DriverTestBase):
    """降级透传、透明性破裂、不变量违规、fatal、缺基线。"""

    def test_note_rate_comes_from_harness_summary(self):
        """SK-1 的驱动侧镜像：聚合值 = harness summary，不重算。"""
        target = cell_id_of("pre_default", PC_OFF)
        driver, _ = self.make_driver(FakeHarness(bump_by_cell={target: 5}))
        summary = driver.run()
        cells = summary.cell_map()
        self.assertAlmostEqual(
            cells[cell_id_of(BASELINE_ARM_ID, PC_OFF)].note_pass_rate, 10.0)
        self.assertAlmostEqual(cells[target].note_pass_rate, 15.0)
        delta = [d for d in summary.deltas if d.cell_id == target][0]
        self.assertAlmostEqual(delta.d_note_pass_pp, 5.0)

    def test_degraded_flag_propagates_to_delta(self):
        """R3 / SK-5：sidecar 的 degraded 必须一路透到双口径 Δ。"""
        driver, _ = self.make_driver(
            FakeHarness(degraded_by_arm={"pre_default": ("p3",)}))
        summary = driver.run()
        cell = summary.cell_map()[cell_id_of("pre_default", PC_OFF)]
        self.assertEqual(cell.preprocess.degraded_pages, ("p3",))
        self.assertTrue(cell.preprocess.any_degraded())
        self.assertEqual(cell.preprocess.degrade_reasons["p3"], "cv2_missing")
        delta = [d for d in summary.deltas
                 if d.cell_id == cell_id_of("pre_default", PC_OFF)][0]
        self.assertTrue(delta.degraded_contaminated)
        self.assertEqual(delta.excluded_pages, ("p3",))
        self.assertIsNotNone(delta.d_note_pass_pp_excl_degraded,
                             "剔除降级页的第二口径必须给出（SK-5）")

    def test_transparency_break_is_blocking(self):
        """R7：``pipe_noop`` 与直调基线不等价 ⇒ 所有 preset Δ 都不可信。"""
        driver, _ = self.make_driver(FakeHarness(
            bump_by_cell={cell_id_of(SANITY_ARM_ID, PC_OFF): 7}))
        summary = driver.run()
        blocking = "\n".join(summary.decision.blocking_findings)
        self.assertIn("R7", blocking)
        self.assertIn("透明性", blocking)

    def test_invariant_violation_reaches_decision(self):
        driver, _ = self.make_driver(
            FakeHarness(applied_by_gt={"p1.gt.musicxml": 1}))
        summary = driver.run()
        self.assertFalse(summary.invariant.passed)
        self.assertEqual(summary.decision.postcorrect_default,
                         L.POSTCORRECT_FAIL)

    def test_fatal_page_makes_cell_incomparable(self):
        """SK-10：缺 pred ⇒ 分母漂移 ⇒ 该 cell 不可比、不参与决策。"""
        driver, _ = self.make_driver(FakeHarness(oemer_fail=("p2",)))
        summary = driver.run()
        for cell in summary.cells:
            self.assertIn("p2", cell.fatal_files)
            self.assertFalse(cell.comparable)
        self.assertTrue(all(not d.comparable for d in summary.deltas))

    def test_missing_baseline_is_blocking(self):
        """基线 cell 收不到结果时，宁可报阻断也不出无参照的 Δ。"""
        driver, _ = self.make_driver()
        driver.config = _replace_config(driver.config,
                                        baseline_cell="ghost__pc_off")
        summary = driver.run()
        self.assertTrue(any("ghost__pc_off" in f
                            for f in summary.decision.blocking_findings))
        self.assertEqual(summary.deltas, ())


def _replace_config(cfg, **overrides):
    """造畸形配置用的 frozen dataclass 复制器（仅单测使用）。"""
    kwargs = {
        "run_id": cfg.run_id, "corpus_dir": cfg.corpus_dir,
        "work_root": cfg.work_root, "arms": cfg.arms, "scores": cfg.scores,
        "baseline_cell": cfg.baseline_cell,
        "reuse_oemer_cache": cfg.reuse_oemer_cache,
        "deskew_probe": cfg.deskew_probe, "thresholds": cfg.thresholds,
        "env": cfg.env,
    }
    kwargs.update(overrides)
    return type(cfg)(**kwargs)


class TestRunModes(DriverTestBase):
    """``run`` / ``rescore`` / ``report`` 三种运行模式的语义差异。"""

    def test_second_run_is_fully_cached(self):
        driver, fake = self.make_driver()
        driver.run()
        fake.oemer_calls = []
        driver.run()
        self.assertEqual(fake.oemer_calls, [],
                         "断点续跑：第二次 run 应当 0 次 oemer")

    def test_rescore_skips_oemer_but_rescores_every_cell(self):
        driver, fake = self.make_driver()
        driver.run()
        fake.oemer_calls = []
        fake.eval_calls = []
        driver.run(skip_oemer=True)
        self.assertEqual(fake.oemer_calls, [])
        self.assertEqual(len(fake.eval_calls), len(driver.plan()))

    def test_report_only_reproduces_same_numbers(self):
        """改阈值秒级复算：同输入必须得到同 Δ（SK-9 确定性）。"""
        driver, fake = self.make_driver()
        first = driver.run()
        fake.eval_calls = []
        second = driver.report_only()
        self.assertEqual(fake.eval_calls, [], "report_only 不得重跑打分")
        self.assertEqual([d.to_dict() for d in first.deltas],
                         [d.to_dict() for d in second.deltas])

    def test_skip_invariant_marks_result_unusable(self):
        driver, fake = self.make_driver()
        summary = driver.run(skip_invariant=True)
        self.assertEqual(fake.project_calls, [])
        self.assertTrue(any("Stage-3" in f
                            for f in summary.decision.blocking_findings))

    def test_force_oemer_ignores_cache(self):
        driver, fake = self.make_driver()
        driver.run()
        fake.oemer_calls = []
        driver.run(force_oemer=True)
        self.assertEqual(len(fake.oemer_calls),
                         len(driver.config.arms) * len(PAGES))

    def test_limit_smoke_run(self):
        """冒烟口径：``--limit 2 --arms pre_off,pre_scan`` 只跑 4 次 oemer。"""
        driver, fake = self.make_driver(
            arm_filter=[BASELINE_ARM_ID, "pre_scan"], limit=2)
        summary = driver.run()
        self.assertEqual(len(fake.oemer_calls), 4)
        self.assertEqual(len(summary.cells), 4)
        self.assertEqual(summary.cells[0].pages_count, 2)


# ----------------------------------------------------------------------
# CLI 与人读输出
# ----------------------------------------------------------------------

class TestCli(DriverTestBase):
    """CLI 只做参数解析与分派，不含任何判断逻辑。"""

    def test_parser_exposes_four_subcommands(self):
        parser = D.build_parser()
        for cmd in ("plan", "run", "rescore", "report"):
            self.assertEqual(parser.parse_args([cmd]).cmd, cmd)

    def test_thresholds_flow_from_cli(self):
        args = D.build_parser().parse_args(
            ["run", "--min-note-pass-gain-pp", "2.5", "--bootstrap-iters", "7"])
        th = D._thresholds_from_args(args)
        self.assertEqual(th.min_note_pass_gain_pp, 2.5)
        self.assertEqual(th.bootstrap_iters, 7)
        self.assertEqual(th.bootstrap_seed, 20260801, "seed 保持 U1 默认")

    def test_plan_subcommand_prints_matrix(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = D.main(["plan", "--corpus", self.corpus,
                         "--work-root", self.work_root, "--run-id", "cli"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn(cell_id_of(BASELINE_ARM_ID, PC_OFF), out)
        self.assertIn(cell_id_of(PROBE_ARM_ID, PC_ON), out)
        self.assertIn("成本估算", out)

    def test_plan_can_write_manifest(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            D.main(["plan", "--corpus", self.corpus, "--work-root",
                    self.work_root, "--run-id", "cli2", "--write-manifest"])
        self.assertTrue(os.path.isfile(os.path.join(
            self.work_root, "cli2", D.MANIFEST_NAME)))

    def test_plan_honours_no_deskew_probe(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            D.main(["plan", "--corpus", self.corpus, "--work-root",
                    self.work_root, "--run-id", "cli3", "--no-deskew-probe"])
        out = buf.getvalue()
        self.assertNotIn(PROBE_ARM_ID, out)

    def test_report_without_run_id_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = D.main(["report", "--corpus", self.corpus,
                         "--work-root", self.work_root])
        self.assertEqual(rc, 1)

    def test_rescore_without_run_id_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = D.main(["rescore", "--corpus", self.corpus,
                         "--work-root", self.work_root])
        self.assertEqual(rc, 1)

    def test_render_plan_shows_runner_and_flag_per_arm(self):
        driver, _ = self.make_driver(arm_filter=())
        text = D.render_plan(driver)
        self.assertIn("on (U7)", text)
        self.assertIn("--preprocess-preset scan", text)
        self.assertIn("--no-preprocess", text)
        self.assertIn("omr_oemer.py", text)


# ----------------------------------------------------------------------
# 小工具与纯净性
# ----------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    """驱动私有小工具的边界行为。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1_2_helper_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_sha256_of_missing_file_is_empty(self):
        self.assertEqual(D._sha256_file(os.path.join(self.tmp, "nope")), "")
        self.assertEqual(D._sha256_file(None), "")

    def test_sha256_is_stable_16_hex(self):
        path = os.path.join(self.tmp, "x.bin")
        with open(path, "wb") as f:
            f.write(b"pudu")
        digest = D._sha256_file(path)
        self.assertEqual(len(digest), 16)
        self.assertEqual(digest, D._sha256_file(path))

    def test_read_json_tolerates_garbage(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(D._read_json(path))
        self.assertIsNone(D._read_json(os.path.join(self.tmp, "absent.json")))

    def test_read_json_rejects_non_dict(self):
        path = os.path.join(self.tmp, "list.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2], f)
        self.assertIsNone(D._read_json(path))

    def test_link_or_copy_creates_parent_dirs(self):
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("hi")
        dst = os.path.join(self.tmp, "a", "b", "c.txt")
        D._link_or_copy(src, dst)
        self.assertTrue(os.path.isfile(dst))
        with open(dst, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "hi")

    def test_link_or_copy_is_idempotent(self):
        src = os.path.join(self.tmp, "s2.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("v1")
        dst = os.path.join(self.tmp, "d2.txt")
        D._link_or_copy(src, dst)
        with open(dst, "w", encoding="utf-8") as f:
            f.write("v2")
        D._link_or_copy(src, dst)  # 已存在则直接返回，不覆盖
        with open(dst, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "v2")

    def test_env_fingerprint_fields_are_strings(self):
        for value in D.build_env_fingerprint().to_dict().values():
            self.assertIsInstance(value, str)


class TestPurity(unittest.TestCase):
    """沙箱可收集性 + U7 探针配置的单变量隔离。"""

    HEAVY = ("cv2", "numpy", "scipy", "pandas", "matplotlib")

    def test_a_heavy_modules_not_loaded_at_import_time(self):
        """增量口径：导入 ``omr_abtest_p1_2`` 前后，新增模块中不得含重型库。

        历史写法断言「当前 sys.modules 里没有 cv2/numpy」，依赖用例执行顺序：
        单独跑能过，全量 ``pytest tests/`` 里被前置用例污染就误报。改成摘缓存
        后重新真导一次、只看**本次导入**的增量，与执行顺序彻底解耦
        （用例名保留 ``a_`` 前缀，不改变既有收集顺序约定）。
        """
        assert_import_is_pure(self, "omr_abtest_p1_2", self.HEAVY)

    def test_no_heavy_imports_in_source(self):
        with open(os.path.join(TOOLS, "omr_abtest_p1_2.py"), "r",
                  encoding="utf-8") as f:
            src = f.read()
        for mod in self.HEAVY:
            self.assertNotIn(f"import {mod}", src, f"驱动层不得 import {mod}")

    def test_no_subprocess_in_driver_source(self):
        """驱动只通过 harness 起子进程，自己不得直接拼 argv（SK-7 的护栏）。"""
        with open(os.path.join(TOOLS, "omr_abtest_p1_2.py"), "r",
                  encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("import subprocess", src)
        self.assertNotIn("os.system", src)

    def test_probe_config_only_differs_by_deskew(self):
        """U7 单变量隔离：探针与 photo preset 的唯一差异是 enable_deskew。"""
        import omr_preprocess as P
        photo, _src_a, _w_a = P.load_config(None, "", "photo")
        probe, _src_b, _w_b = P.load_config(D.PROBE_CONFIG, "", "photo")
        # load_config 返回的是 dataclass（非 dict），需用 vars() 取字段视图。
        photo_d, probe_d = vars(photo), vars(probe)
        diff = {k for k in set(photo_d) | set(probe_d)
                if photo_d.get(k) != probe_d.get(k)}
        self.assertEqual(diff, {"enable_deskew"},
                         "探针必须只动 deskew 一个变量，否则归因不成立")
        self.assertTrue(photo_d["enable_deskew"])
        self.assertFalse(probe_d["enable_deskew"])


class TestCacheVersionInvalidation(unittest.TestCase):
    """缓存版本失效：预处理代码变更后，旧 oemer 缓存必须过期重跑。

    P1-2 Bug C 端到端验证曾因静默复用「预处理变更前」的缓存而失效，
    根因是 oemer 缓存 key 不感知预处理工具版本。以下测试锁定该语义。
    """

    def _write_metrics(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_current_version_readable(self):
        ver = D._current_preproc_tool_version()
        self.assertIsNotNone(ver)
        self.assertTrue(ver.startswith("p0-"))

    def test_mismatched_version_is_stale(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m.metrics.json")
        self._write_metrics(p, {"tool_version": "p0-2.1"})
        self.assertTrue(D._is_metrics_stale(p, "p0-2.2"))

    def test_matching_version_is_not_stale(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m.metrics.json")
        self._write_metrics(p, {"tool_version": "p0-2.2"})
        self.assertFalse(D._is_metrics_stale(p, "p0-2.2"))

    def test_missing_tool_version_field_is_not_stale(self):
        """遗留缓存/测试桩未打版本号 → 沿用旧复用行为，不破坏断点续跑。"""
        d = tempfile.mkdtemp()
        p = os.path.join(d, "m.metrics.json")
        self._write_metrics(p, {"src": "x", "dst": "y"})
        self.assertFalse(D._is_metrics_stale(p, "p0-2.2"))

    def test_missing_or_corrupt_metrics_is_stale(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "none.metrics.json")
        self.assertTrue(D._is_metrics_stale(p, "p0-2.2"))
        corrupt = os.path.join(d, "bad.metrics.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        self.assertTrue(D._is_metrics_stale(corrupt, "p0-2.2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
