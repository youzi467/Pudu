# -*- coding: utf-8 -*-
"""谱渡 Pudu · P1-2 · A/B 实验编排驱动（``omr_abtest_p1_2``）。

定位
----
本脚本是 P1-2「预处理 A/B 调参 + 后处理前后对比」**唯一有 I/O 的一层**：
建工作区、硬链接语料、跑 oemer、调 harness、读 sidecar、断言不变量、写产物。
所有**判断**都下沉到纯函数层 :mod:`omr_abtest_lib`，本层不做任何统计与决策。

两阶段流水线（设计核心洞察 1：两个实验成本量级差 60 倍，必须解耦）
------------------------------------------------------------------
::

    Stage-0  规划 & 环境指纹   -> manifest.json
    Stage-1  OMR sweep（贵）   -> 每 arm 每页跑一次 oemer，pred 落 cache/
    Stage-2  投影打分（廉价）  -> 12 个 cell 全部 --reuse-pred，从 cache 复投影
    Stage-3  不变量守护（红线）-> 13 份干净 GT 跑 --apply-postcorrect，断言 applied==0
    Stage-4  聚合 / Δ / 统计   -> abtest_summary.json
    Stage-5  决策 & 渲染       -> abtest_report.md

**与设计时序图的一处实现偏差（有意）**：设计把 oemer 调用画在
``eval_corpus`` 内部。本实现把 Stage-1 的 oemer 调用**上提到驱动层**
（``warm_arm``），Stage-1/Stage-2 的**打分**一律走 ``reuse_pred=True``。
原因：``eval_corpus`` 的 ``reuse_pred`` 是**整个语料级**开关，做不到
「6 页里已缓存 4 页就只补跑 2 页」；而设计 §2.3 明文要求
「每页跑完立刻写 cache，重跑时逐页跳过」的断点续跑。上提之后：

* 断点续跑粒度 = **页**（跑挂了重跑只补缺页，不重跑 45 分钟）；
* Stage-1 与 Stage-2 的打分走**同一条**代码路径，少一套分支；
* argv 完全不变——驱动直接复用 harness 的 :func:`run_oemer`，
  即 T01 单测逐 token 把关过的那一个函数。

红线（设计 §10）
----------------
* **SK-2**：所有 arm 一律带 ``--gt``（由 ``run_oemer(gt_path=...)`` 保证）。
* **SK-3**：同一页在所有 cell 保持**同一个 stem**，否则 per-page 配对失效。
* **SK-4**：gt 侧投影永不加 ``--apply-postcorrect``（harness 内有硬断言）。
* **SK-5**：每个 preset arm 都必须落 metrics sidecar，降级才可观测。
* **SK-6**：cell 之间**物理隔离**，pred/report 不得互相覆盖。
* **SK-9**：唯一随机源在纯函数层，seed 落 manifest。

CLI
---
::

    python tools/omr_abtest_p1_2.py plan     [--corpus DIR] [--limit N]
    python tools/omr_abtest_p1_2.py run      [--corpus DIR] [--limit N] [--arms a,b]
    python tools/omr_abtest_p1_2.py rescore  --run-id ID     # 不跑 oemer，只重投影
    python tools/omr_abtest_p1_2.py report   --run-id ID     # 只重跑决策/渲染（秒级）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import omr_eval_groundtruth as G  # noqa: E402
import omr_abtest_lib as A  # noqa: E402
from omr_abtest_lib import (  # noqa: E402
    ArmSpec, ScoreSpec, CellPlan, CellResult, DecisionThresholds,
    EnvFingerprint, ExperimentConfig, InvariantResult, AbtestSummary,
    BASELINE_ARM_ID, SANITY_ARM_ID, PC_OFF, PC_ON, INVARIANT_EXPECTED_GT,
    aggregate_cell, cell_id_of, check_transparency, compute_delta,
    default_arms, default_scores, evaluate_invariant, make_decision,
)

__all__ = [
    "DEFAULT_CORPUS", "PROBE_CONFIG", "P1_1_CLEAN_GT", "MANIFEST_NAME",
    "SUMMARY_NAME", "REPORT_NAME", "AbtestDriver", "build_config", "main",
]

#: 主语料：6 页 concerto（干净扫描件，与历史 07-20 基线同一批）。
DEFAULT_CORPUS = os.path.join(_REPO_ROOT, "data", "omr_eval", "real",
                              "concerto_pages")
#: 产物根目录。
DEFAULT_WORK_ROOT = os.path.join(_REPO_ROOT, "data", "omr_eval", "_abtest",
                                 "p1_2")
#: K2 探针配置（photo 但 ``enable_deskew=false``，U7）。
PROBE_CONFIG = os.path.join(_TOOLS_DIR, "omr_abtest_photo_nodeskew.json")
#: 预处理配置单一真源（进环境指纹）。
PREPROCESS_CONFIG = os.path.join(_TOOLS_DIR, "omr_preprocess_config.json")

#: P1-1 的干净 GT 语料（``test/test_jianpu_postcorrect.cpp`` 的 7 个
#: ``PC_CORPUS_TEST``，实测 7 份而非设计 §8 笔误的 8/14 份）。
#: 与 6 页 concerto GT 合计 **13 份**，构成 Stage-3 不变量守护的全部覆盖。
P1_1_CLEAN_GT: Tuple[str, ...] = (
    "solo-violin-partita-no-2-in-d-minor-j-s-bach-bwv-1004.musicxml",
    "j-s-bach-cello-suite-n-1-bwv-1007-1-prelude.musicxml",
    "concerto-in-a-minor-a-vivaldi.musicxml",
    "badinerie-for-flute-by-js-bach.musicxml",
    "solo-violin-caprice-no-24-in-a-minor-n-paganini-op-1-no-24.musicxml",
    "canon-in-d-violin-solo.musicxml",
    "summer-third-movement.musicxml",
)

MANIFEST_NAME = "manifest.json"
SUMMARY_NAME = "abtest_summary.json"
REPORT_NAME = "abtest_report.md"
HARNESS_REPORT_NAME = "harness_report.json"

#: metrics sidecar / postcorrect report 的文件名模板（``{base}`` 由 harness 展开）。
METRICS_TEMPLATE = "{base}.metrics.json"
PC_REPORT_TEMPLATE = "{base}.report.json"


# ----------------------------------------------------------------------
# 小工具（纯 I/O，无判断）
# ----------------------------------------------------------------------

def _log(msg: str, enabled: bool = True) -> None:
    if enabled:
        print(msg, flush=True)


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _sha256_file(path: Optional[str]) -> str:
    """文件 sha256（前 16 位）；不存在返回空串。"""
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _link_or_copy(src: str, dst: str) -> str:
    """优先硬链接（零拷贝、零额外磁盘），失败回落复制。

    A/B 要在 14 个 cell 工作区各放一份 6 页 jpg + gt；硬链接可以把
    ~200 MB 的重复占用降到 0。跨卷 / 文件系统不支持时静默回落 copy2。
    """
    if os.path.exists(dst):
        return dst
    _ensure_dir(os.path.dirname(dst))
    try:
        os.link(src, dst)
    except (OSError, AttributeError, NotImplementedError):
        shutil.copy2(src, dst)
    return dst


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    """读 JSON；不存在/不可解析返回 None（调用方据此判违规或跳过）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: str, payload: Any) -> str:
    _ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _git_head() -> str:
    """读 ``.git/HEAD``（不起子进程，沙箱友好）。"""
    head = os.path.join(_REPO_ROOT, ".git", "HEAD")
    try:
        with open(head, "r", encoding="utf-8") as f:
            ref = f.read().strip()
    except OSError:
        return ""
    if not ref.startswith("ref:"):
        return ref[:12]
    target = os.path.join(_REPO_ROOT, ".git", ref.split(" ", 1)[1].strip())
    try:
        with open(target, "r", encoding="utf-8") as f:
            return f.read().strip()[:12]
    except OSError:
        return ""


def _oemer_version(venv_python: str = G.VENV_PYTHON) -> str:
    """从 venv 的 ``site-packages`` 里扫 ``oemer-*.dist-info``（不起子进程）。"""
    scripts_dir = os.path.dirname(venv_python)
    venv_root = os.path.dirname(scripts_dir)
    for rel in (os.path.join("Lib", "site-packages"),
                os.path.join("lib", "site-packages")):
        site = os.path.join(venv_root, rel)
        if not os.path.isdir(site):
            continue
        try:
            entries = os.listdir(site)
        except OSError:
            continue
        for name in sorted(entries):
            low = name.lower()
            if low.startswith("oemer-") and low.endswith(".dist-info"):
                return name[len("oemer-"):-len(".dist-info")]
    return ""


def build_env_fingerprint() -> EnvFingerprint:
    """采集环境指纹（R4：跨机器复核结论的唯一依据）。"""
    return EnvFingerprint(
        pudu_exe_sha256=_sha256_file(G.EXE),
        oemer_version=_oemer_version(),
        preprocess_config_sha256=_sha256_file(PREPROCESS_CONFIG),
        eval_lib_sha256=_sha256_file(os.path.join(_TOOLS_DIR,
                                                  "omr_eval_lib.py")),
        git_head=_git_head(),
    )


def build_config(corpus_dir: str = DEFAULT_CORPUS,
                 work_root: str = DEFAULT_WORK_ROOT,
                 run_id: Optional[str] = None,
                 deskew_probe: bool = True,
                 arm_filter: Sequence[str] = (),
                 thresholds: Optional[DecisionThresholds] = None,
                 with_env: bool = True) -> ExperimentConfig:
    """组装 :class:`ExperimentConfig`（Stage-0）。

    Args:
        corpus_dir: 语料目录。
        work_root: 产物根目录（真正的 run 目录是 ``work_root/<run_id>``）。
        run_id: 不给则用 ``p1_2_<时间戳>``。
        deskew_probe: 是否加 K2 探针 arm（U7 默认 True）。
        arm_filter: 只保留这些 arm_id（冒烟用）；空表示全部。
        thresholds: 决策阈值（U1 默认值）。
        with_env: 是否采集环境指纹（单测里关掉可免去哈希 Pudu.exe）。
    """
    run_id = run_id or time.strftime("p1_2_%Y%m%d_%H%M%S")
    arms = default_arms(deskew_probe=deskew_probe, probe_config=PROBE_CONFIG)
    if arm_filter:
        wanted = list(arm_filter)
        arms = tuple(a for a in arms if a.arm_id in wanted)
        if not arms:
            raise ValueError(f"--arms 过滤后无任何 arm：{wanted}")
        if all(a.arm_id != BASELINE_ARM_ID for a in arms):
            raise ValueError(
                f"--arms 必须包含基线 {BASELINE_ARM_ID}，否则所有 Δ 无参照系")
    return ExperimentConfig(
        run_id=run_id,
        corpus_dir=os.path.abspath(corpus_dir),
        work_root=os.path.abspath(os.path.join(work_root, run_id)),
        arms=arms,
        scores=default_scores(),
        baseline_cell=cell_id_of(BASELINE_ARM_ID, PC_OFF),
        deskew_probe=deskew_probe,
        thresholds=thresholds or DecisionThresholds(),
        env=build_env_fingerprint() if with_env else EnvFingerprint(),
    )


# ----------------------------------------------------------------------
# 驱动
# ----------------------------------------------------------------------

def _current_preproc_tool_version() -> Optional[str]:
    """读取当前 ``omr_preprocess`` 的工具版本，用于 oemer 缓存失效判定。

    ``omr_preprocess`` 顶层只 import 标准库（cv2/numpy 延迟导入），
    故此处 import 安全且廉价。失败返回 ``None``（不强制失效，沿用旧行为）。
    """
    try:
        from omr_preprocess import TOOL_VERSION
        return str(TOOL_VERSION)
    except Exception:
        return None


def _is_metrics_stale(mpath: str, cur_ver: str) -> bool:
    """缓存 metrics 的预处理工具版本与当前代码不一致 → 过期（需重跑 oemer）。

    缺失/损坏 → 过期，强制重跑该页；但若 metrics 根本没有 ``tool_version``
    字段（旧版/测试桩未打版本号的遗留缓存），则视为「不感知版本」，沿用旧
    复用行为（避免破坏断点续跑）。只有当版本号**存在且不同**时才判过期。
    """
    try:
        with open(mpath, "r", encoding="utf-8") as fh:
            m = json.load(fh)
    except Exception:
        return True
    tv = m.get("tool_version")
    if tv is None:
        return False
    return str(tv) != cur_ver


class AbtestDriver:
    """A/B 实验编排器。

    三个外部依赖全部可注入，因此 :mod:`tests.test_omr_abtest_driver`
    可以用替身完整跑通 Stage-0~5，**不跑 oemer、不跑 Pudu、不需 GPU**。

    Attributes:
        config: 实验配置快照。
        oemer_fn: ``run_oemer`` 替身点（Stage-1）。
        eval_fn: ``eval_corpus`` 替身点（Stage-1/2 打分）。
        project_fn: ``pudu_jianpu_json`` 替身点（Stage-3 不变量）。
    """

    def __init__(self,
                 config: ExperimentConfig,
                 *,
                 oemer_fn: Optional[Callable[..., bool]] = None,
                 eval_fn: Optional[Callable[..., Dict[str, Any]]] = None,
                 project_fn: Optional[Callable[..., Dict[str, Any]]] = None,
                 invariant_gt: Optional[Sequence[str]] = None,
                 invariant_expected: Optional[int] = None,
                 limit: int = 0,
                 verbose: bool = True) -> None:
        """
        Args:
            invariant_gt: 覆写 Stage-3 干净 GT 清单（**仅测试替身语料使用**，
                CLI 无入口）。
            invariant_expected: 覆写本轮规范覆盖份数。默认 ``None`` ⇒ 取红线
                全量 :data:`INVARIANT_EXPECTED_GT` (13)。

        Raises:
            ValueError: 未注入 ``invariant_gt`` 却想下调 ``invariant_expected``。
                真实语料路径永远不注入 GT 清单，因此这条硬断言在结构上封死了
                「偷偷把红线份数调低」的口子（QA-1）。
        """
        self.config = config
        self.oemer_fn = oemer_fn or G.run_oemer
        self.eval_fn = eval_fn or G.eval_corpus
        self.project_fn = project_fn or G.pudu_jianpu_json
        self.limit = max(0, int(limit))
        self.verbose = verbose
        self._invariant_gt = (list(invariant_gt)
                              if invariant_gt is not None else None)
        # 🔴 QA-1：规范份数只能与替身 GT 清单**成对**下调。真实跑（不注入
        # invariant_gt）无论如何都按 13 份红线量，--limit 也撼动不了。
        if invariant_expected is not None:
            if self._invariant_gt is None:
                raise ValueError(
                    "invariant_expected 只能与 invariant_gt 一起注入："
                    "真实语料下 Stage-3 红线恒为 "
                    f"{INVARIANT_EXPECTED_GT} 份，不允许单独下调")
            if int(invariant_expected) < 0:
                raise ValueError("invariant_expected 不能为负")
        self.invariant_expected: int = (INVARIANT_EXPECTED_GT
                                        if invariant_expected is None
                                        else int(invariant_expected))
        self._pairs: Optional[List[Tuple[str, str, str]]] = None
        self._blocking: List[str] = []

    # —— 路径 ——

    @property
    def run_dir(self) -> str:
        return self.config.work_root

    @property
    def cells_dir(self) -> str:
        return os.path.join(self.run_dir, "cells")

    @property
    def cache_root(self) -> str:
        return os.path.join(self.run_dir, "cache")

    @property
    def invariant_dir(self) -> str:
        return os.path.join(self.run_dir, "invariant")

    def cache_dir(self, arm_id: str) -> str:
        return os.path.join(self.cache_root, arm_id)

    def metrics_dir(self, arm_id: str) -> str:
        return os.path.join(self.cache_dir(arm_id), "metrics")

    def cell_dir(self, cell_id: str) -> str:
        return os.path.join(self.cells_dir, cell_id)

    def pred_path(self, arm_id: str, base: str) -> str:
        return os.path.join(self.cache_dir(arm_id), base + ".pred.musicxml")

    def metrics_path(self, arm_id: str, base: str) -> str:
        return os.path.join(self.metrics_dir(arm_id), base + ".metrics.json")

    # —— Stage-0 ——

    def pairs(self) -> List[Tuple[str, str, str]]:
        """发现 ``(image, gt, base)`` 三元组（缓存结果，受 ``--limit`` 截断）。

        Raises:
            RuntimeError: 语料目录里一对都没有。
        """
        if self._pairs is None:
            found = G.discover_pairs(self.config.corpus_dir, use_oemer=True)
            found.sort(key=lambda item: item[2])
            if self.limit:
                found = found[:self.limit]
            if not found:
                raise RuntimeError(
                    f"语料 {self.config.corpus_dir} 未发现任何 (image, gt) 对")
            self._pairs = found
        return self._pairs

    def plan(self) -> List[CellPlan]:
        """展开 cell 矩阵（纯规划，不落盘）。"""
        return self.config.plan_cells()

    def write_manifest(self) -> str:
        """写 ``manifest.json``（配置 + 阈值 + 指纹 + 语料清单）。"""
        payload = dict(self.config.to_dict())
        payload["schema"] = A.SCHEMA
        payload["pages"] = [base for _img, _gt, base in self.pairs()]
        payload["cells"] = [p.to_dict() for p in self.plan()]
        payload["invariant_gt"] = [os.path.basename(p)
                                   for p in self.invariant_gt_files()]
        return _write_json(os.path.join(self.run_dir, MANIFEST_NAME), payload)

    # —— Stage-1：OMR sweep（贵、逐页可断点续跑） ——

    def warm_arm(self, arm: ArmSpec, force: bool = False) -> Dict[str, bool]:
        """为一个 arm 补齐 pred 缓存，返回 ``{base: 本轮是否真的跑了 oemer}``。

        缓存命中判据：``cache/<arm>/<base>.pred.musicxml`` 存在**且非空**，
        且（对预处理臂）缓存 metrics 的 ``tool_version`` 与当前预处理代码一致。
        命中即跳过（≈65 s/页 -> 0 s）；这是断点续跑的全部秘密。
        注意：预处理代码（``omr_preprocess.TOOL_VERSION``）变更后，旧缓存视为
        过期必须重跑 oemer，否则会静默复用「增强图处理前」的结果
        （曾导致 P1-2 Bug C 端到端验证失效）。

        Args:
            arm: 实验臂。
            force: 无视缓存强制重跑（``--no-cache``）。
        """
        _ensure_dir(self.cache_dir(arm.arm_id))
        ran: Dict[str, bool] = {}
        use_metrics = arm.preprocess is not None
        if use_metrics:
            _ensure_dir(self.metrics_dir(arm.arm_id))
        cur_proc_ver = _current_preproc_tool_version()
        for image, gt, base in self.pairs():
            pred = self.pred_path(arm.arm_id, base)
            cached = (os.path.isfile(pred) and os.path.getsize(pred) > 0)
            # 预处理臂：若缓存 metrics 的工具版本与当前代码不一致 → 过期，必须重跑
            stale = False
            if cached and use_metrics and cur_proc_ver is not None:
                stale = _is_metrics_stale(
                    self.metrics_path(arm.arm_id, base), cur_proc_ver)
            if cached and not force and self.config.reuse_oemer_cache and not stale:
                _log(f"  [cache] {arm.arm_id}/{base} 命中，跳过 oemer",
                     self.verbose)
                ran[base] = False
                continue
            if stale:
                _log(f"  [cache] {arm.arm_id}/{base} 预处理版本过期，重跑 oemer",
                     self.verbose)
            _log(f"  [oemer] {arm.arm_id}/{base} 识别中…", self.verbose)
            ok = self.oemer_fn(
                image, pred, gt_path=gt,
                f3_geometric=arm.f3_geometric,
                preprocess=arm.preprocess,
                preprocess_config=(arm.preprocess_config
                                   if arm.preprocess is not None else None),
                preprocess_metrics=(self.metrics_path(arm.arm_id, base)
                                    if use_metrics else None))
            ran[base] = bool(ok)
            if not ok:
                _log(f"  [warn] {arm.arm_id}/{base} oemer 失败 —— "
                     f"该页将在打分阶段记为 fatal（SK-10）", self.verbose)
        return ran

    # —— 工作区 ——

    def prepare_workspace(self, plan: CellPlan) -> str:
        """搭 cell 工作区：硬链接 image + gt + cache 里的 pred。

        SK-3：文件名一律沿用原 stem，**不加 cell 前缀**——per-page 配对靠
        stem 做主键，改名等于把 6 页配对全打散。
        SK-6：每个 cell 一个目录，pred / report / note_diffs 互不覆盖。
        """
        ws = _ensure_dir(self.cell_dir(plan.cell_id))
        for image, gt, base in self.pairs():
            _link_or_copy(image, os.path.join(ws, os.path.basename(image)))
            _link_or_copy(gt, os.path.join(ws, os.path.basename(gt)))
            pred = self.pred_path(plan.arm.arm_id, base)
            if os.path.isfile(pred) and os.path.getsize(pred) > 0:
                _link_or_copy(pred, os.path.join(ws, base + ".pred.musicxml"))
        return ws

    # —— Stage-1/2：打分（一律 reuse_pred=True） ——

    def score_cell(self, plan: CellPlan) -> Dict[str, Any]:
        """对一个 cell 调 harness 打分，并把原始报告落盘。

        ``reuse_pred=True`` 恒成立：pred 已由 :meth:`warm_arm` 备妥，
        harness 只负责「Pudu 投影 + 比对」。缺 pred 的页由 harness 记 fatal，
        绝不静默回退去跑 oemer。
        """
        ws = self.prepare_workspace(plan)
        report_dir = os.path.join(ws, "postcorrect_reports")
        oemer_opts = plan.arm.to_oemer_opts(
            preprocess_metrics=(os.path.join(self.metrics_dir(plan.arm.arm_id),
                                             METRICS_TEMPLATE)
                                if plan.arm.preprocess is not None else None))
        project_opts = plan.score.to_project_opts(report_dir)
        _log(f"[score] {plan.cell_id} …", self.verbose)
        result = self.eval_fn(ws, use_oemer=True,
                              oemer_opts=oemer_opts,
                              project_opts=project_opts,
                              reuse_pred=True)
        _write_json(os.path.join(ws, HARNESS_REPORT_NAME), result)
        return result

    # —— Stage-3：不变量守护 ——

    def invariant_gt_files(self) -> List[str]:
        """Stage-3 覆盖的干净 GT 清单：6 页 concerto GT + 7 份 P1-1 语料。

        **不受 ``--limit`` 影响**（QA-1 修复）：Stage-3 是固定 13 份红线清单，
        与打分语料子集（``--limit`` 截断项）无关。任何缩水都视为红线被削弱。
        因此这里**绕过** ``self.pairs()``（后者受 ``--limit`` 截断），直接用全量
        语料发现 concerto GT。
        """
        if self._invariant_gt is not None:
            return list(self._invariant_gt)
        # 直接全量发现 concerto GT，绕过 pairs() 的 --limit 截断（QA-1）。
        files = [gt for _img, gt, _base
                 in G.discover_pairs(self.config.corpus_dir, use_oemer=True)]
        data_dir = os.path.join(_REPO_ROOT, "data")
        for name in P1_1_CLEAN_GT:
            path = os.path.join(data_dir, name)
            if os.path.isfile(path):
                files.append(path)
            else:
                # QA-1：缺文件不只 warn，必须进判定层的阻断性发现，
                # 否则谁挪一下 data/*.musicxml，红线就被静默削弱。
                msg = f"P1-1 干净 GT 缺失，Stage-3 红线缩水：{path}"
                _log(f"[warn] {msg}", self.verbose)
                if msg not in self._blocking:
                    self._blocking.append(msg)
        return files

    def run_invariant(self) -> InvariantResult:
        """🔴 干净 GT 上跑 ``--apply-postcorrect``，断言 ``applied == 0``。

        这是 P1-1 的立项红线（R6）：后处理只许修 OMR 的错，对人工权威
        MusicXML 一处都不许动。任何非零 ``appliedCount`` ⇒ 整轮 FAIL。
        """
        out_dir = _ensure_dir(self.invariant_dir)
        reports: Dict[str, Optional[Dict[str, Any]]] = {}
        for path in self.invariant_gt_files():
            name = os.path.basename(path)
            report_path = os.path.join(out_dir, name + ".report.json")
            try:
                self.project_fn(path, postcorrect=True,
                                postcorrect_report=report_path)
            except Exception as exc:  # noqa: BLE001
                _log(f"  [invariant] {name}: Pudu 失败 -> {exc}", self.verbose)
                reports[name] = None
                continue
            reports[name] = _read_json(report_path)
        result = evaluate_invariant(reports,
                                    expected=self.invariant_expected)
        _log(f"[invariant] {result.gt_files_checked}/{result.expected_gt} "
             f"份干净 GT -> {'PASS' if result.passed else 'FAIL'}",
             self.verbose)
        return result

    # —— Stage-4：聚合 ——

    def collect_cell(self, plan: CellPlan,
                     harness_report: Optional[Dict[str, Any]] = None
                     ) -> CellResult:
        """把一个 cell 的 harness 报告 + sidecar 折叠成 :class:`CellResult`。"""
        ws = self.cell_dir(plan.cell_id)
        if harness_report is None:
            harness_report = _read_json(
                os.path.join(ws, HARNESS_REPORT_NAME)) or {}

        metrics: List[Dict[str, Any]] = []
        if plan.arm.preprocess is not None:
            for _img, _gt, base in self.pairs():
                data = _read_json(self.metrics_path(plan.arm.arm_id, base))
                if data is not None:
                    data.setdefault("page", base)
                    metrics.append(data)

        pc_reports: List[Dict[str, Any]] = []
        if plan.score.postcorrect:
            for _img, _gt, base in self.pairs():
                data = _read_json(os.path.join(ws, "postcorrect_reports",
                                               base + ".report.json"))
                if data is not None:
                    pc_reports.append(data)

        return aggregate_cell(
            cell_id=plan.cell_id,
            arm_id=plan.arm.arm_id,
            postcorrect=plan.score.postcorrect,
            harness_report=harness_report,
            preprocess_metrics=metrics,
            postcorrect_reports=pc_reports,
            raw_report_path=os.path.relpath(
                os.path.join(ws, HARNESS_REPORT_NAME), self.run_dir))

    def aggregate(self, invariant: InvariantResult,
                  reports: Optional[Dict[str, Dict[str, Any]]] = None
                  ) -> AbtestSummary:
        """Stage-4 + Stage-5：聚合 -> Δ -> 决策 -> :class:`AbtestSummary`。

        Δ 的参照系（设计 §6.1）：

        * ``*__pc_off`` cell -> 对照 ``pre_off__pc_off``（预处理效果）；
        * ``*__pc_on``  cell -> 对照**同 arm 的** ``*__pc_off``
          （后处理效果，同一批 pred 上唯一变量就是后处理，归因干净）。
        """
        reports = reports or {}
        plans = self.plan()
        cells: Dict[str, CellResult] = {}
        for plan in plans:
            cells[plan.cell_id] = self.collect_cell(
                plan, reports.get(plan.cell_id))

        baseline_id = self.config.baseline_cell
        baseline = cells.get(baseline_id)
        deltas = []
        if baseline is not None:
            for plan in plans:
                cell = cells[plan.cell_id]
                if plan.score.postcorrect:
                    ref = cells.get(cell_id_of(plan.arm.arm_id, PC_OFF))
                else:
                    ref = baseline
                if ref is None or ref.cell_id == cell.cell_id:
                    continue
                deltas.append(compute_delta(cell, ref, self.config.thresholds))
        else:
            self._blocking.append(
                f"基线 cell {baseline_id} 缺失，全部 Δ 无参照系 ⇒ 无法决策")

        blocking = list(self._blocking)
        blocking.extend(check_transparency(
            cells.get(cell_id_of(SANITY_ARM_ID, PC_OFF)), baseline))

        decision = make_decision(cells, deltas, invariant,
                                 self.config.thresholds,
                                 extra_blocking=blocking,
                                 corpus_label=(
                                     f"{os.path.basename(self.config.corpus_dir)}"
                                     f" {len(self.pairs())}p"))
        return AbtestSummary(
            config=self.config,
            cells=tuple(cells[p.cell_id] for p in plans),
            deltas=tuple(deltas),
            invariant=invariant,
            decision=decision)

    # —— Stage-5：产物 ——

    def write_outputs(self, summary: AbtestSummary) -> Tuple[str, str]:
        """写 ``abtest_summary.json`` + ``abtest_report.md``。"""
        js = _write_json(os.path.join(self.run_dir, SUMMARY_NAME),
                         summary.to_json())
        md_path = os.path.join(self.run_dir, REPORT_NAME)
        _ensure_dir(self.run_dir)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(summary.to_markdown())
        return (js, md_path)

    # —— 全流程 ——

    def run(self, *, skip_oemer: bool = False, force_oemer: bool = False,
            skip_invariant: bool = False) -> AbtestSummary:
        """跑完 Stage-0~5，返回 :class:`AbtestSummary`。

        Args:
            skip_oemer: 跳过 Stage-1 的 oemer（``rescore`` 子命令）。
            force_oemer: 无视缓存强制重跑 oemer（``--no-cache``）。
            skip_invariant: 跳过 Stage-3（**仅供调试**，正式跑绝不允许）。
        """
        _ensure_dir(self.run_dir)
        manifest = self.write_manifest()
        _log(f"[stage-0] manifest -> {manifest}", self.verbose)
        _log(f"[stage-0] {len(self.config.arms)} arm × "
             f"{len(self.config.scores)} 打分 = {len(self.plan())} cell，"
             f"{len(self.pairs())} 页", self.verbose)

        if not skip_oemer:
            _log("[stage-1] OMR sweep（贵、逐页可断点续跑）", self.verbose)
            for arm in self.config.arms:
                self.warm_arm(arm, force=force_oemer)
        else:
            _log("[stage-1] 跳过 oemer，全部复用 cache（rescore 模式）",
                 self.verbose)

        _log("[stage-2] 投影打分（12 cell，全部 --reuse-pred）", self.verbose)
        reports: Dict[str, Dict[str, Any]] = {}
        for plan in self.plan():
            reports[plan.cell_id] = self.score_cell(plan)

        if skip_invariant:
            self._blocking.append(
                "⚠ Stage-3 不变量守护被 --skip-invariant 跳过，"
                "本轮结论**不可用于**任何默认开关决策")
            # QA-1：跳过 ≠ 通过。覆盖为 0 而规范要求 13，coverage_ok 自然为
            # False，判定层会据此判 FAIL——不给「没跑就当过了」留任何余地。
            invariant = InvariantResult(
                passed=False, gt_files_checked=0,
                expected_gt=self.invariant_expected,
                violations=("Stage-3 不变量守护被 --skip-invariant 跳过，"
                            "0 份干净 GT 被验证",))
        else:
            _log("[stage-3] 不变量守护（P1-1 红线）", self.verbose)
            invariant = self.run_invariant()

        _log("[stage-4/5] 聚合 / Δ / 统计 / 决策", self.verbose)
        summary = self.aggregate(invariant, reports)
        js, md = self.write_outputs(summary)
        _log(f"[done] summary -> {js}", self.verbose)
        _log(f"[done] report  -> {md}", self.verbose)
        return summary

    def report_only(self, invariant: Optional[InvariantResult] = None
                    ) -> AbtestSummary:
        """只重跑 Stage-4/5（改阈值后秒级复算，不碰 oemer / Pudu）。"""
        if invariant is None:
            reports: Dict[str, Optional[Dict[str, Any]]] = {}
            if os.path.isdir(self.invariant_dir):
                for name in sorted(os.listdir(self.invariant_dir)):
                    if not name.endswith(".report.json"):
                        continue
                    key = name[: -len(".report.json")]
                    reports[key] = _read_json(
                        os.path.join(self.invariant_dir, name))
            invariant = evaluate_invariant(reports,
                                           expected=self.invariant_expected)
        summary = self.aggregate(invariant)
        self.write_outputs(summary)
        return summary


# ----------------------------------------------------------------------
# 人读输出
# ----------------------------------------------------------------------

def render_plan(driver: AbtestDriver) -> str:
    """``plan`` 子命令的人读输出：cell 矩阵 + 每 arm 的实际调用形态。"""
    cfg = driver.config
    lines: List[str] = []
    add = lines.append
    add(f"run_id      : {cfg.run_id}")
    add(f"corpus      : {cfg.corpus_dir}")
    add(f"work_root   : {cfg.work_root}")
    add(f"baseline    : {cfg.baseline_cell}")
    add(f"deskew probe: {'on (U7)' if cfg.deskew_probe else 'off'}")
    add("")
    pages = [b for _i, _g, b in driver.pairs()]
    add(f"页数 {len(pages)}：{', '.join(pages)}")
    add("")
    add("arm 矩阵（Stage-1 每个 arm 跑一轮 oemer）：")
    add(f"{'arm_id':<20} {'runner':<18} {'preset/flag':<28} 说明")
    for arm in cfg.arms:
        if arm.preprocess is None:
            runner, flag = "omr_oemer.py", "(直调，无预处理 flag)"
        elif arm.preprocess == "off":
            runner, flag = "omr_pipeline.py", "--no-preprocess"
        else:
            runner = "omr_pipeline.py"
            flag = f"--preprocess-preset {arm.preprocess}"
            if arm.preprocess_config:
                flag += " +cfg"
        add(f"{arm.arm_id:<20} {runner:<18} {flag:<28} {arm.label}")
    add("")
    add("cell 矩阵（Stage-2 每个 cell 打一次分）：")
    add(f"{'cell_id':<28} {'postcorrect':<12} {'needs_oemer':<12} workspace")
    for plan in driver.plan():
        add(f"{plan.cell_id:<28} "
            f"{('on' if plan.score.postcorrect else 'off'):<12} "
            f"{str(plan.needs_oemer):<12} "
            f"{os.path.relpath(plan.workspace_dir, cfg.work_root)}")
    add("")
    add(f"Stage-3 不变量守护覆盖 {len(driver.invariant_gt_files())} 份干净 GT："
        f"{len(pages)} 页 concerto GT + "
        f"{len(driver.invariant_gt_files()) - len(pages)} 份 P1-1 语料")
    add("")
    est_pages = len(pages) * len(cfg.arms)
    add(f"成本估算：Stage-1 ≈ {est_pages} 页 × 65 s ≈ "
        f"{est_pages * 65 / 60:.0f} min（缓存命中则为 0）；"
        f"Stage-2 ≈ {len(driver.plan()) * len(pages)} 次投影 × 1 s ≈ "
        f"{len(driver.plan()) * len(pages) / 60:.1f} min")
    return "\n".join(lines) + "\n"


def print_verdict(summary: AbtestSummary) -> None:
    """把最关键的三行结论打到 stdout（CI 直接抓这三行）。"""
    d = summary.decision
    print("")
    print("=" * 70)
    print(f"preprocess_default  = {d.preprocess_default}")
    print(f"postcorrect_default = {d.postcorrect_default}")
    print(f"confidence          = {d.confidence}")
    if d.blocking_findings:
        print("-" * 70)
        for item in d.blocking_findings:
            print(f"🔴 {item}")
    print("=" * 70)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--corpus", default=DEFAULT_CORPUS, help="语料目录")
    parser.add_argument("--work-root", default=DEFAULT_WORK_ROOT,
                        help="产物根目录")
    parser.add_argument("--run-id", default=None, help="运行标识（默认时间戳）")
    parser.add_argument("--limit", type=int, default=0,
                        help="只取前 N 页（冒烟用，0=全部）")
    parser.add_argument("--arms", default="",
                        help="逗号分隔的 arm 白名单（冒烟用，必须含 pre_off）")
    parser.add_argument("--no-deskew-probe", action="store_true",
                        help="关闭 K2 探针 arm（U7 默认开）")
    parser.add_argument("--quiet", action="store_true", help="少打日志")


def _add_thresholds(parser: argparse.ArgumentParser) -> None:
    th = DecisionThresholds()
    parser.add_argument("--min-note-pass-gain-pp", type=float,
                        default=th.min_note_pass_gain_pp)
    parser.add_argument("--min-field-pass-gain-pp", type=float,
                        default=th.min_field_pass_gain_pp)
    parser.add_argument("--max-category-regress-pp", type=float,
                        default=th.max_category_regress_pp)
    parser.add_argument("--min-improved-pages", type=int,
                        default=th.min_improved_pages)
    parser.add_argument("--max-worsened-pages", type=int,
                        default=th.max_worsened_pages)
    parser.add_argument("--bootstrap-iters", type=int,
                        default=th.bootstrap_iters)
    parser.add_argument("--bootstrap-seed", type=int, default=th.bootstrap_seed)


def _thresholds_from_args(args: argparse.Namespace) -> DecisionThresholds:
    base = DecisionThresholds()
    return DecisionThresholds(
        min_note_pass_gain_pp=getattr(args, "min_note_pass_gain_pp",
                                      base.min_note_pass_gain_pp),
        min_field_pass_gain_pp=getattr(args, "min_field_pass_gain_pp",
                                       base.min_field_pass_gain_pp),
        max_category_regress_pp=getattr(args, "max_category_regress_pp",
                                        base.max_category_regress_pp),
        min_improved_pages=getattr(args, "min_improved_pages",
                                   base.min_improved_pages),
        max_worsened_pages=getattr(args, "max_worsened_pages",
                                   base.max_worsened_pages),
        require_zero_degraded=base.require_zero_degraded,
        postcorrect_min_field_gain_pp=base.postcorrect_min_field_gain_pp,
        bootstrap_iters=getattr(args, "bootstrap_iters", base.bootstrap_iters),
        bootstrap_seed=getattr(args, "bootstrap_seed", base.bootstrap_seed),
    )


def _driver_from_args(args: argparse.Namespace,
                      with_env: bool = True) -> AbtestDriver:
    arm_filter = [s.strip() for s in (args.arms or "").split(",") if s.strip()]
    cfg = build_config(corpus_dir=args.corpus,
                       work_root=args.work_root,
                       run_id=args.run_id,
                       deskew_probe=not args.no_deskew_probe,
                       arm_filter=arm_filter,
                       thresholds=_thresholds_from_args(args),
                       with_env=with_env)
    return AbtestDriver(cfg, limit=args.limit, verbose=not args.quiet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omr_abtest_p1_2",
        description="谱渡 Pudu · P1-2 预处理 A/B + 后处理前后对比 编排驱动")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="只打印 cell 矩阵与成本估算，不跑任何东西")
    _add_common(p_plan)
    _add_thresholds(p_plan)
    p_plan.add_argument("--write-manifest", action="store_true",
                        help="顺便把 manifest.json 落盘")

    p_run = sub.add_parser("run", help="跑完整实验（Stage-0~5）")
    _add_common(p_run)
    _add_thresholds(p_run)
    p_run.add_argument("--no-cache", action="store_true",
                       help="无视 pred 缓存，强制重跑 oemer")
    p_run.add_argument("--skip-invariant", action="store_true",
                       help="跳过 Stage-3（仅调试；结论将被标记为不可用）")

    p_rescore = sub.add_parser(
        "rescore", help="不跑 oemer，只从 cache 重投影打分（改了 P1-1 规则后用）")
    _add_common(p_rescore)
    _add_thresholds(p_rescore)
    p_rescore.add_argument("--skip-invariant", action="store_true")

    p_report = sub.add_parser(
        "report", help="只重跑聚合/决策/渲染（改阈值后秒级复算）")
    _add_common(p_report)
    _add_thresholds(p_report)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口。

    Returns:
        int: 0 = 一切正常；2 = 有阻断性发现（不变量破裂 / 透明性破裂）。
    """
    args = build_parser().parse_args(argv)

    if args.cmd == "plan":
        driver = _driver_from_args(args, with_env=False)
        print(render_plan(driver), end="")
        if args.write_manifest:
            print(f"manifest -> {driver.write_manifest()}")
        return 0

    if args.cmd == "report":
        if not args.run_id:
            print("[error] report 子命令必须显式给 --run-id", file=sys.stderr)
            return 1
        driver = _driver_from_args(args)
        summary = driver.report_only()
    elif args.cmd == "rescore":
        if not args.run_id:
            print("[error] rescore 子命令必须显式给 --run-id", file=sys.stderr)
            return 1
        driver = _driver_from_args(args)
        summary = driver.run(skip_oemer=True,
                             skip_invariant=args.skip_invariant)
    else:  # run
        driver = _driver_from_args(args)
        summary = driver.run(force_oemer=args.no_cache,
                             skip_invariant=args.skip_invariant)

    print_verdict(summary)
    if summary.decision.blocking_findings or not summary.invariant.passed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
