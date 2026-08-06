# -*- coding: utf-8 -*-
"""P1-2 · T02 纯函数层单测（``tools/omr_abtest_lib.py``）。

被测对象是 A/B 实验的**决策大脑**：聚合、统计、判据、渲染。因为它零 I/O、
零子进程、零第三方依赖，所以可以**脱离 GPU / oemer / Pudu** 全量单测——
这正是设计 §2.1 把纯函数与编排层拆开的收益。

覆盖需求
--------
* **SK-1**：:func:`aggregate_cell` 只取 harness ``summary``，**绝不重算**
  （测试刻意让 ``summary`` 与 ``per_file`` 对不上，断言取 ``summary``）。
* **SK-9**：:func:`bootstrap_ci_by_page` 是全模块唯一随机源，固定 seed 下
  **逐位可复现**（同参数两次调用结果必须完全相等）。
* **SK-5 / R3**：降级页**双口径** Δ（全量 + 剔除降级页）都进结果。
* **SK-10**：``fatal_files`` 非空的 cell 不可比、不参与决策。
* **SK-4**：:meth:`ScoreSpec.to_project_opts` 恒 ``postcorrect_gt=False``，
  且不提供任何打开它的入参。
* **SK-11**：``directional`` 结论禁止写成"已验证"，
  :func:`render_markdown` 强制输出 ``confidence`` 行。
* **统计对表**：:func:`sign_test_p` 在 n=6 下的精确二项值
  （6:0=0.03125 / 5:1=0.21875 / 4:2=0.6875 / 3:3=1.0）。
* **判据边界**：``decide_preprocess`` 的 C1–C5、``decide_postcorrect`` 的
  C1′–C5′，每条判据都测「刚好通过」与「差一点」两侧。

本测试**不 import cv2 / numpy / scipy**（沿用 P0-2 规则，保证沙箱可收集）。
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (HERE, TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _purity_probe import HEAVY_MODULES, assert_import_is_pure  # noqa: E402

import omr_abtest_lib as L  # noqa: E402
from omr_abtest_lib import (  # noqa: E402
    ArmSpec, ScoreSpec, DecisionThresholds, EnvFingerprint, ExperimentConfig,
    PageCounts, PreprocessMetricsSummary, PostCorrectSummary,
    CellResult, DeltaResult, InvariantResult, Decision, AbtestSummary,
    BASELINE_ARM_ID, SANITY_ARM_ID, PROBE_ARM_ID, PC_OFF, PC_ON,
    VERDICT_SIGNIFICANT, VERDICT_DIRECTIONAL, VERDICT_NEUTRAL,
    VERDICT_REGRESSION,
    POSTCORRECT_DEFAULT_ON, POSTCORRECT_DEFAULT_OFF, POSTCORRECT_FAIL,
    INVARIANT_EXPECTED_GT,
    cell_id_of, preset_of_arm, default_arms, default_scores,
    summarize_preprocess, summarize_postcorrect, aggregate_cell,
    sign_test_p, bootstrap_ci_by_page, classify_verdict, compute_delta,
    evaluate_invariant, check_transparency, diagnose_deskew,
    decide_preprocess, decide_postcorrect, make_decision, render_markdown,
)

# 单测里把 bootstrap 次数压到 200，纯为提速；确定性由固定 seed 保证，
# 与迭代次数无关（SK-9）。凡是断言 CI 具体数值的用例都显式传这个阈值对象。
FAST_TH = DecisionThresholds(bootstrap_iters=200)


# ----------------------------------------------------------------------
# 构造工具
# ----------------------------------------------------------------------

def make_cell(cell_id,
              arm_id="pre_scan",
              postcorrect=False,
              note=0.0,
              field=0.0,
              pages=None,
              category_pass=None,
              category_distribution=None,
              fatal_files=(),
              degraded=(),
              total_ms=0.0,
              applied=0,
              flagged=0):
    """构造 :class:`CellResult`。

    Args:
        pages: ``{page: (notes_correct, notes_compared, field_checked,
            field_failed)}``。
        degraded: 降级页 key 列表（会塞进 ``preprocess.degraded_pages``）。
    """
    pages = pages or {}
    per_page = {}
    per_page_note_pass = {}
    n_ok = n_all = f_all = f_bad = 0
    for key, (ok, total, fc, ff) in pages.items():
        counts = PageCounts(notes_compared=total, notes_correct=ok,
                            field_checked=fc, field_failed=ff)
        per_page[key] = counts
        per_page_note_pass[key] = round(counts.note_pass_rate, 2)
        n_ok += ok
        n_all += total
        f_all += fc
        f_bad += ff
    return CellResult(
        cell_id=cell_id,
        arm_id=arm_id,
        postcorrect=postcorrect,
        note_pass_rate=note,
        field_pass_rate=field,
        notes_compared=n_all,
        notes_correct=n_ok,
        field_checked=f_all,
        field_failed=f_bad,
        category_pass=dict(category_pass or {}),
        category_distribution=dict(category_distribution or {}),
        per_page=per_page,
        per_page_note_pass=per_page_note_pass,
        fatal_files=tuple(fatal_files),
        preprocess=PreprocessMetricsSummary(
            pages_total=len(pages),
            degraded_pages=tuple(degraded),
            degrade_reasons={p: "ink_ratio_out_of_range" for p in degraded},
            total_ms_mean=total_ms,
        ),
        postcorrect_stats=PostCorrectSummary(applied_total=applied,
                                             flagged_total=flagged),
    )


def make_delta(cell_id,
               baseline_cell_id=None,
               d_note=2.0,
               d_field=2.0,
               d_cat_pass=None,
               d_cat_count=None,
               improved=6,
               worsened=0,
               tied=0,
               p=0.03125,
               ci=(0.5, 4.0),
               d_event=0,
               verdict=VERDICT_SIGNIFICANT,
               comparable=True,
               excluded_pages=(),
               d_note_excl=None,
               d_field_excl=None):
    """构造 :class:`DeltaResult`（判据测试直接喂它，不经 bootstrap）。"""
    return DeltaResult(
        cell_id=cell_id,
        baseline_cell_id=baseline_cell_id or cell_id_of(BASELINE_ARM_ID, PC_OFF),
        d_note_pass_pp=d_note,
        d_field_pass_pp=d_field,
        d_category_pass_pp=dict(d_cat_pass or {}),
        d_category_count=dict(d_cat_count or {}),
        d_event_count=d_event,
        pages_improved=improved,
        pages_worsened=worsened,
        pages_tied=tied,
        sign_test_p=p,
        ci95_note_pass_pp=ci,
        verdict=verdict,
        comparable=comparable,
        degraded_contaminated=bool(excluded_pages),
        excluded_pages=tuple(excluded_pages),
        d_note_pass_pp_excl_degraded=d_note_excl,
        d_field_pass_pp_excl_degraded=d_field_excl,
    )


# ======================================================================
# 1. 配置类数据结构
# ======================================================================


class TestArmAndScoreSpec(unittest.TestCase):
    """ArmSpec / ScoreSpec -> harness opts 的折叠语义。"""

    def test_cell_id_and_preset_helpers(self):
        self.assertEqual(cell_id_of("pre_scan", PC_OFF), "pre_scan__pc_off")
        self.assertEqual(cell_id_of("pre_off", PC_ON), "pre_off__pc_on")
        self.assertEqual(preset_of_arm("pre_low_contrast"), "low_contrast")
        self.assertEqual(preset_of_arm("pipe_noop"), "pipe_noop")

    def test_baseline_arm_never_emits_preprocess_flags(self):
        """基线 arm（preprocess=None）必须直调 oemer，且不带任何私有 flag。

        这是 SK-8 的**前置防线**：与其让 harness 抛 ValueError，不如在
        折叠时就把 config/metrics 显式清空，让"基线不产 metrics"成为语义。
        """
        arm = ArmSpec(BASELINE_ARM_ID, None, "some_config.json", False, "base")
        opts = arm.to_oemer_opts(preprocess_metrics="m/{base}.json")
        self.assertIsNone(opts.preprocess)
        self.assertIsNone(opts.preprocess_config)
        self.assertIsNone(opts.preprocess_metrics)
        self.assertFalse(opts.f3_geometric)

    def test_preset_arm_keeps_config_and_metrics(self):
        arm = ArmSpec(PROBE_ARM_ID, "photo", "probe.json", False, "probe")
        opts = arm.to_oemer_opts(preprocess_metrics="m/{base}.metrics.json")
        self.assertEqual(opts.preprocess, "photo")
        self.assertEqual(opts.preprocess_config, "probe.json")
        self.assertEqual(opts.preprocess_metrics, "m/{base}.metrics.json")

    def test_noop_arm_uses_off_sentinel(self):
        arm = ArmSpec(SANITY_ARM_ID, "off", None, False, "noop")
        opts = arm.to_oemer_opts(preprocess_metrics="m/{base}.json")
        self.assertEqual(opts.preprocess, "off")
        # "off" 也是"经 pipeline"，所以 metrics 仍然透传
        self.assertEqual(opts.preprocess_metrics, "m/{base}.json")

    def test_score_spec_suffix(self):
        self.assertEqual(ScoreSpec(postcorrect=False).suffix, PC_OFF)
        self.assertEqual(ScoreSpec(postcorrect=True).suffix, PC_ON)

    def test_score_spec_never_enables_gt_postcorrect(self):
        """🔴 SK-4：gt 侧后处理永不开启，且无入参可以打开它。"""
        for pc in (True, False):
            for report_dir in (None, "", "reports"):
                opts = ScoreSpec(postcorrect=pc).to_project_opts(report_dir)
                self.assertFalse(opts.postcorrect_gt,
                                 f"pc={pc} report_dir={report_dir!r}")

    def test_score_spec_report_path_template(self):
        opts = ScoreSpec(True, True).to_project_opts("reports")
        self.assertEqual(opts.postcorrect_report,
                         os.path.join("reports", "{base}.report.json"))
        self.assertTrue(opts.postcorrect_pred)

        # pc_off 不产报告；emit_report=False 也不产
        self.assertIsNone(
            ScoreSpec(False, True).to_project_opts("reports").postcorrect_report)
        self.assertIsNone(
            ScoreSpec(True, False).to_project_opts("reports").postcorrect_report)
        # 没给目录也不产（避免落到 CWD）
        self.assertIsNone(
            ScoreSpec(True, True).to_project_opts(None).postcorrect_report)


class TestDefaultMatrix(unittest.TestCase):
    """设计 §2.2 的 6（+1 探针）arm × 2 打分维度 = 12（+2）cell。"""

    def test_default_arms_without_probe(self):
        arms = default_arms(deskew_probe=False)
        self.assertEqual([a.arm_id for a in arms],
                         ["pre_off", "pipe_noop", "pre_default", "pre_scan",
                          "pre_photo", "pre_low_contrast"])
        self.assertIsNone(arms[0].preprocess)
        self.assertEqual(arms[1].preprocess, "off")
        self.assertTrue(all(not a.f3_geometric for a in arms),
                        "F3 已证零效果，A/B 一律不开（plan §8）")

    def test_default_arms_with_probe(self):
        """U7：探针默认启用，且必须带覆盖配置才能真正关掉 deskew。"""
        arms = default_arms(deskew_probe=True, probe_config="probe.json")
        self.assertEqual(len(arms), 7)
        probe = arms[-1]
        self.assertEqual(probe.arm_id, PROBE_ARM_ID)
        self.assertEqual(probe.preprocess, "photo")
        self.assertEqual(probe.preprocess_config, "probe.json")

    def test_default_scores(self):
        scores = default_scores()
        self.assertEqual([s.suffix for s in scores], [PC_OFF, PC_ON])
        self.assertFalse(scores[0].emit_report)
        self.assertTrue(scores[1].emit_report)

    def test_plan_cells_order_and_oemer_reuse(self):
        """pc_off 恒排在同 arm 的 pc_on 之前；oemer 只在 pc_off 上跑。"""
        cfg = ExperimentConfig(run_id="r1", corpus_dir="corpus",
                               work_root=os.path.join("out", "r1"),
                               arms=default_arms(deskew_probe=True,
                                                 probe_config="p.json"))
        plans = cfg.plan_cells()
        self.assertEqual(len(plans), 7 * 2)
        self.assertEqual([p.cell_id for p in plans[:4]],
                         ["pre_off__pc_off", "pre_off__pc_on",
                          "pipe_noop__pc_off", "pipe_noop__pc_on"])
        self.assertEqual([p.needs_oemer for p in plans[:4]],
                         [True, False, True, False])
        # oemer 轮次 = arm 数，而不是 cell 数（设计洞察 1）
        self.assertEqual(sum(1 for p in plans if p.needs_oemer), 7)

    def test_plan_cells_directories_are_isolated(self):
        """SK-3：每个 cell 独立工作区；同 arm 的两个 cell 共享 pred 缓存。"""
        cfg = ExperimentConfig(run_id="r1", corpus_dir="c", work_root="w",
                               arms=default_arms(deskew_probe=False))
        plans = {p.cell_id: p for p in cfg.plan_cells()}
        off = plans["pre_scan__pc_off"]
        on = plans["pre_scan__pc_on"]
        self.assertNotEqual(off.workspace_dir, on.workspace_dir)
        self.assertEqual(off.cache_dir, on.cache_dir)
        self.assertEqual(off.workspace_dir,
                         os.path.join("w", "cells", "pre_scan__pc_off"))
        self.assertEqual(off.cache_dir, os.path.join("w", "cache", "pre_scan"))

    def test_config_to_dict_is_json_serializable(self):
        cfg = ExperimentConfig(run_id="r1", corpus_dir="c", work_root="w",
                               env=EnvFingerprint(git_head="abc123"))
        text = json.dumps(cfg.to_dict(), ensure_ascii=False)
        self.assertIn("abc123", text)
        self.assertIn("bootstrap_seed", text)

    def test_locked_default_thresholds_u1(self):
        """U1 已拍板：阈值取设计 §4 默认值，任何改动都要走决策流程。"""
        th = DecisionThresholds()
        self.assertEqual(th.min_note_pass_gain_pp, 1.0)
        self.assertEqual(th.min_field_pass_gain_pp, 1.0)
        self.assertEqual(th.max_category_regress_pp, 1.0)
        self.assertEqual(th.min_improved_pages, 5)
        self.assertEqual(th.max_worsened_pages, 1)
        self.assertTrue(th.require_zero_degraded)
        self.assertEqual(th.postcorrect_min_field_gain_pp, 0.5)
        self.assertEqual(th.bootstrap_iters, 10000)
        self.assertEqual(th.bootstrap_seed, 20260801)


# ======================================================================
# 2. 聚合
# ======================================================================


class TestSummarizePreprocess(unittest.TestCase):
    """C7/C8：sidecar 是"降级"的唯一可观测通道。"""

    def test_empty_input(self):
        s = summarize_preprocess([])
        self.assertEqual(s.pages_total, 0)
        self.assertFalse(s.any_degraded())
        self.assertEqual(s.total_ms_mean, 0.0)

    def test_degraded_pages_are_captured(self):
        metrics = [
            {"page": "p1", "degraded": False, "total_ms": 100.0,
             "deskew_decision": "applied", "deskew_applied_deg": 1.5,
             "ink_ratio_out": 0.08},
            {"page": "p2", "degraded": True,
             "degrade_reason": "ink_ratio_out_of_range", "total_ms": 200.0},
        ]
        s = summarize_preprocess(metrics)
        self.assertTrue(s.any_degraded())
        self.assertEqual(s.degraded_pages, ("p2",))
        self.assertEqual(s.degrade_reasons["p2"], "ink_ratio_out_of_range")
        self.assertEqual(s.deskew_decisions["p1"], "applied")
        self.assertEqual(s.deskew_decisions["p2"], "disabled")
        self.assertAlmostEqual(s.deskew_applied_deg["p1"], 1.5)
        self.assertAlmostEqual(s.ink_ratio_out["p1"], 0.08)
        self.assertNotIn("p2", s.ink_ratio_out)
        self.assertAlmostEqual(s.total_ms_mean, 150.0)
        self.assertEqual(s.pages_total, 2)

    def test_page_key_falls_back_to_src_stem(self):
        s = summarize_preprocess([{"src": os.path.join("a", "b", "p3.jpg"),
                                   "degraded": True}])
        self.assertEqual(s.degraded_pages, ("p3",))

    def test_malformed_entries_do_not_crash(self):
        s = summarize_preprocess([None, 42, {"page": "p1",
                                             "total_ms": "not-a-number",
                                             "deskew_applied_deg": "x"}])
        self.assertEqual(s.deskew_applied_deg["p1"], 0.0)
        self.assertEqual(s.total_ms_mean, 0.0)


class TestSummarizePostcorrect(unittest.TestCase):
    """P1-1 审计报告 schema -> 决策输入。"""

    def test_empty(self):
        s = summarize_postcorrect([])
        self.assertEqual(s.applied_total, 0)
        self.assertEqual(dict(s.by_kind), {})

    def test_aggregate_by_kind(self):
        reports = [
            {"measuresReconciled": 3, "notesTouched": 5, "appliedCount": 2,
             "flaggedCount": 1,
             "applied": [{"kind": "rhythm"}, {"kind": "tuplet"}],
             "flagged": [{"kind": "pitch_octave"}]},
            {"measuresReconciled": 1, "notesTouched": 1, "appliedCount": 1,
             "flaggedCount": 0, "applied": [{"kind": "rhythm"}], "flagged": []},
        ]
        s = summarize_postcorrect(reports)
        self.assertEqual(s.applied_total, 3)
        self.assertEqual(s.flagged_total, 1)
        self.assertEqual(s.measures_reconciled, 4)
        self.assertEqual(s.notes_touched, 6)
        self.assertEqual(dict(s.by_kind), {"rhythm": 2, "tuplet": 1})
        self.assertEqual(dict(s.flagged_by_kind), {"pitch_octave": 1})

    def test_count_falls_back_to_list_length(self):
        s = summarize_postcorrect([{"applied": [{"kind": "key"}, {}]}])
        self.assertEqual(s.applied_total, 2)
        self.assertEqual(dict(s.by_kind), {"key": 1, "unknown": 1})


class TestAggregateCell(unittest.TestCase):
    """🔴 SK-1：只取 harness summary，绝不重算。"""

    HARNESS = {
        "summary": {
            "note_pass_rate": 2.65,
            "field_pass_rate": 61.11,
            "notes_compared": 944,
            "notes_correct": 25,
            "field_checked": 18,
            "field_failed": 7,
            "category_pass": {"rhythm": 40.5, "pitch_degree": 55.0},
            "category_distribution": {"rhythm": 100, "event_count": 12},
            "fatal_files": [],
        },
        "per_file": [
            {"file": "p1", "notes_compared": 100, "notes_correct": 90,
             "field_checked": 3, "field_failed": 0},
            {"file": "p2", "notes_compared": 100, "notes_correct": 80,
             "field_checked": 3, "field_failed": 1},
        ],
    }

    def test_rates_come_from_summary_not_recomputed(self):
        """per_file 加总是 85%，summary 说 2.65% —— 必须听 summary 的。"""
        cell = aggregate_cell("pre_off__pc_off", "pre_off", False, self.HARNESS)
        self.assertAlmostEqual(cell.note_pass_rate, 2.65)
        self.assertAlmostEqual(cell.field_pass_rate, 61.11)
        self.assertEqual(cell.notes_compared, 944)
        self.assertEqual(cell.field_checked, 18)
        self.assertEqual(dict(cell.category_pass),
                         {"rhythm": 40.5, "pitch_degree": 55.0})

    def test_per_page_counts_and_rates(self):
        cell = aggregate_cell("pre_off__pc_off", "pre_off", False, self.HARNESS)
        self.assertEqual(cell.pages_count, 2)
        self.assertAlmostEqual(cell.per_page_note_pass["p1"], 90.0)
        self.assertAlmostEqual(cell.per_page["p2"].field_pass_rate,
                               (3 - 1) / 3 * 100.0)

    def test_fatal_files_make_cell_incomparable(self):
        """SK-10：分母漂移的 cell 不可比。"""
        report = json.loads(json.dumps(self.HARNESS))
        report["summary"]["fatal_files"] = ["p3.jpg"]
        cell = aggregate_cell("pre_photo__pc_off", "pre_photo", False, report)
        self.assertEqual(cell.fatal_files, ("p3.jpg",))
        self.assertFalse(cell.comparable)

    def test_sidecars_are_folded_in(self):
        cell = aggregate_cell(
            "pre_photo__pc_on", "pre_photo", True, self.HARNESS,
            preprocess_metrics=[{"page": "p1", "degraded": True,
                                 "degrade_reason": "clahe_failed"}],
            postcorrect_reports=[{"appliedCount": 4,
                                  "applied": [{"kind": "rhythm"}] * 4}],
            raw_report_path="cells/pre_photo__pc_on/report.json")
        self.assertTrue(cell.preprocess.any_degraded())
        self.assertEqual(cell.postcorrect_stats.applied_total, 4)
        self.assertEqual(cell.raw_report_path,
                         "cells/pre_photo__pc_on/report.json")
        self.assertTrue(cell.postcorrect)

    def test_missing_summary_yields_zeros(self):
        cell = aggregate_cell("x__pc_off", "x", False, {})
        self.assertEqual(cell.note_pass_rate, 0.0)
        self.assertEqual(cell.pages_count, 0)
        self.assertTrue(cell.comparable)


# ======================================================================
# 3. 统计
# ======================================================================


class TestSignTest(unittest.TestCase):
    """精确二项符号检验对表（设计 §6.2）。"""

    def test_n6_exact_table(self):
        """n=6 下的完整对表——只有 6:0 才够格叫"统计显著"。"""
        table = {
            (6, 0): 0.03125,
            (5, 1): 0.21875,
            (4, 2): 0.6875,
            (3, 3): 1.0,
            (2, 4): 0.6875,
            (0, 6): 0.03125,
        }
        for (imp, wor), expect in table.items():
            self.assertAlmostEqual(sign_test_p(imp, wor), expect, places=10,
                                   msg=f"{imp}:{wor}")

    def test_six_zero_is_the_only_significant_split_at_n6(self):
        self.assertLessEqual(sign_test_p(6, 0), L.SIGNIFICANCE_ALPHA)
        self.assertGreater(sign_test_p(5, 1), L.SIGNIFICANCE_ALPHA)

    def test_ties_are_excluded_so_n_shrinks(self):
        """5 页改善 + 1 页打平 = 5:0，n=5 -> p=0.0625，**仍然不显著**。

        这条很关键：打平页不能算作"胜利"，否则会把 5:0 误判成显著。
        """
        self.assertAlmostEqual(sign_test_p(5, 0), 2.0 / 32.0)
        self.assertGreater(sign_test_p(5, 0), L.SIGNIFICANCE_ALPHA)

    def test_degenerate_inputs(self):
        self.assertEqual(sign_test_p(0, 0), 1.0)
        self.assertEqual(sign_test_p(-3, 0), 1.0)
        self.assertLessEqual(sign_test_p(7, 0), 0.015625 + 1e-12)

    def test_p_never_exceeds_one(self):
        for imp in range(0, 8):
            for wor in range(0, 8):
                self.assertLessEqual(sign_test_p(imp, wor), 1.0)
                self.assertGreater(sign_test_p(imp, wor), 0.0)


class TestBootstrap(unittest.TestCase):
    """SK-9：固定 seed -> 逐位可复现；按页而不是按音符抽样。"""

    CELL = {"p1": (15, 100), "p2": (20, 100), "p3": (35, 100),
            "p4": (10, 100), "p5": (25, 100), "p6": (30, 100)}
    BASE = {"p1": (10, 100), "p2": (20, 100), "p3": (30, 100),
            "p4": (8, 100), "p5": (20, 100), "p6": (28, 100)}

    def test_determinism_same_seed(self):
        a = bootstrap_ci_by_page(self.CELL, self.BASE, iters=500, seed=20260801)
        b = bootstrap_ci_by_page(self.CELL, self.BASE, iters=500, seed=20260801)
        self.assertEqual(a, b)

    def test_different_seed_may_differ_but_stays_bounded(self):
        a = bootstrap_ci_by_page(self.CELL, self.BASE, iters=500, seed=1)
        b = bootstrap_ci_by_page(self.CELL, self.BASE, iters=500, seed=2)
        self.assertLessEqual(a[0], a[1])
        self.assertLessEqual(b[0], b[1])
        # 两个 seed 的 CI 都应包住真实 Δ（约 +4.0pp）
        for ci in (a, b):
            self.assertLessEqual(ci[0], 4.5)
            self.assertGreaterEqual(ci[1], 3.0)

    def test_identical_inputs_give_zero_ci(self):
        ci = bootstrap_ci_by_page(self.BASE, self.BASE, iters=200, seed=7)
        self.assertEqual(ci, (0.0, 0.0))

    def test_uniform_gain_ci_excludes_zero(self):
        """每页都赢 -> CI 下界必须 > 0（这是"显著"的必要条件之一）。"""
        cell = {p: (ok + 10, total) for p, (ok, total) in self.BASE.items()}
        lo, hi = bootstrap_ci_by_page(cell, self.BASE, iters=800, seed=20260801)
        self.assertGreater(lo, 0.0)
        self.assertGreaterEqual(hi, lo)

    def test_only_intersecting_pages_participate(self):
        cell = dict(self.CELL)
        cell["p99"] = (100, 100)
        with_extra = bootstrap_ci_by_page(cell, self.BASE, iters=300, seed=5)
        without = bootstrap_ci_by_page(self.CELL, self.BASE, iters=300, seed=5)
        self.assertEqual(with_extra, without)

    def test_degenerate_inputs(self):
        self.assertEqual(bootstrap_ci_by_page({}, {}, iters=100), (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page(self.CELL, self.BASE, iters=0),
                         (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page({"a": (1, 2)}, {"b": (1, 2)},
                                              iters=100), (0.0, 0.0))


class TestClassifyVerdict(unittest.TestCase):
    """四态判定（保守优先）。"""

    TH = DecisionThresholds()

    def test_significant_requires_all_three_conditions(self):
        d = make_delta("c", d_note=3.0, improved=6, worsened=0, p=0.03125,
                       ci=(0.5, 5.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_SIGNIFICANT)

    def test_not_significant_when_ci_crosses_zero(self):
        d = make_delta("c", d_note=3.0, improved=6, worsened=0, p=0.03125,
                       ci=(-0.5, 5.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_DIRECTIONAL)

    def test_not_significant_when_p_above_alpha(self):
        d = make_delta("c", d_note=3.0, improved=5, worsened=0, p=0.0625,
                       ci=(0.5, 5.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_DIRECTIONAL)

    def test_not_significant_when_any_page_worsens(self):
        d = make_delta("c", d_note=3.0, improved=5, worsened=1, p=0.21875,
                       ci=(0.5, 5.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_DIRECTIONAL)

    def test_negative_delta_is_regression(self):
        d = make_delta("c", d_note=-0.5, improved=5, worsened=1, p=0.2,
                       ci=(-3.0, 1.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_REGRESSION)

    def test_positive_delta_but_majority_worse_is_regression(self):
        """总分被单页离群值撑起来 -> 不可信，标红。"""
        d = make_delta("c", d_note=2.0, improved=1, worsened=5, p=0.21875,
                       ci=(-5.0, 8.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_REGRESSION)

    def test_zero_delta_is_neutral(self):
        d = make_delta("c", d_note=0.0, improved=0, worsened=0, p=1.0,
                       ci=(0.0, 0.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_NEUTRAL)

    def test_zero_delta_with_more_worsened_pages_is_regression(self):
        d = make_delta("c", d_note=0.0, improved=1, worsened=3, p=0.6,
                       ci=(-2.0, 2.0))
        self.assertEqual(classify_verdict(d, self.TH), VERDICT_REGRESSION)


# ======================================================================
# 4. compute_delta（含降级双口径）
# ======================================================================


class TestComputeDelta(unittest.TestCase):

    def _baseline(self, **kw):
        return make_cell(
            cell_id_of(BASELINE_ARM_ID, PC_OFF), BASELINE_ARM_ID,
            note=20.0, field=80.0,
            pages={"p1": (10, 100, 10, 2),
                   "p2": (20, 100, 10, 2),
                   "p3": (30, 100, 10, 2)},
            category_pass={"rhythm": 40.0, "pitch_degree": 50.0},
            category_distribution={"rhythm": 100, "event_count": 12},
            **kw)

    def _cell(self, **kw):
        return make_cell(
            "pre_scan__pc_off", "pre_scan",
            note=23.3333, field=86.6667,
            pages={"p1": (15, 100, 10, 1),
                   "p2": (20, 100, 10, 2),
                   "p3": (35, 100, 10, 1)},
            category_pass={"rhythm": 43.0, "pitch_degree": 49.5},
            category_distribution={"rhythm": 90, "event_count": 10},
            **kw)

    def test_basic_deltas(self):
        d = compute_delta(self._cell(), self._baseline(), FAST_TH)
        self.assertAlmostEqual(d.d_note_pass_pp, 3.3333, places=4)
        self.assertAlmostEqual(d.d_field_pass_pp, 6.6667, places=4)
        self.assertAlmostEqual(d.d_category_pass_pp["rhythm"], 3.0)
        self.assertAlmostEqual(d.d_category_pass_pp["pitch_degree"], -0.5)
        self.assertEqual(d.d_category_count["rhythm"], -10)
        self.assertEqual(d.d_event_count, -2)
        self.assertEqual(d.baseline_cell_id, "pre_off__pc_off")

    def test_page_level_pairing(self):
        d = compute_delta(self._cell(), self._baseline(), FAST_TH)
        self.assertEqual((d.pages_improved, d.pages_worsened, d.pages_tied),
                         (2, 0, 1))
        self.assertAlmostEqual(d.sign_test_p, 0.5, places=6)
        self.assertEqual(d.verdict, VERDICT_DIRECTIONAL)

    def test_dual_metric_when_pages_degraded(self):
        """🔴 SK-5：降级页存在时，全量 Δ 与剔除降级页 Δ 都必须出。"""
        d = compute_delta(self._cell(degraded=("p2",)), self._baseline(),
                          FAST_TH)
        self.assertTrue(d.degraded_contaminated)
        self.assertEqual(d.excluded_pages, ("p2",))
        # 剔除 p2 后：cell (15+35)/200=25.0%，baseline (10+30)/200=20.0%
        self.assertAlmostEqual(d.d_note_pass_pp_excl_degraded, 5.0, places=4)
        # field：cell (20-2)/20=90%，baseline (20-4)/20=80%
        self.assertAlmostEqual(d.d_field_pass_pp_excl_degraded, 10.0, places=4)
        # 全量口径不受影响，依然直取 summary
        self.assertAlmostEqual(d.d_note_pass_pp, 3.3333, places=4)
        self.assertTrue(any("降级页" in n for n in d.notes))

    def test_no_second_metric_when_clean(self):
        d = compute_delta(self._cell(), self._baseline(), FAST_TH)
        self.assertFalse(d.degraded_contaminated)
        self.assertIsNone(d.d_note_pass_pp_excl_degraded)
        self.assertIsNone(d.d_field_pass_pp_excl_degraded)
        self.assertEqual(d.excluded_pages, ())

    def test_baseline_degraded_pages_also_excluded(self):
        d = compute_delta(self._cell(), self._baseline(degraded=("p1",)),
                          FAST_TH)
        self.assertEqual(d.excluded_pages, ("p1",))
        self.assertIsNotNone(d.d_note_pass_pp_excl_degraded)

    def test_fatal_cell_marked_incomparable(self):
        """SK-10：有 fatal 页 -> Δ 打上不可比标记 + 说明。"""
        d = compute_delta(self._cell(fatal_files=("p4.jpg",)),
                          self._baseline(), FAST_TH)
        self.assertFalse(d.comparable)
        self.assertTrue(any("SK-10" in n for n in d.notes))

    def test_identical_cells_give_neutral(self):
        base = self._baseline()
        same = make_cell("pipe_noop__pc_off", SANITY_ARM_ID,
                         note=base.note_pass_rate, field=base.field_pass_rate,
                         pages={"p1": (10, 100, 10, 2),
                                "p2": (20, 100, 10, 2),
                                "p3": (30, 100, 10, 2)},
                         category_pass=dict(base.category_pass),
                         category_distribution=dict(base.category_distribution))
        d = compute_delta(same, base, FAST_TH)
        self.assertEqual(d.d_note_pass_pp, 0.0)
        self.assertEqual(d.d_field_pass_pp, 0.0)
        self.assertEqual(d.verdict, VERDICT_NEUTRAL)
        self.assertEqual(d.ci95_note_pass_pp, (0.0, 0.0))
        self.assertEqual(d.pages_tied, 3)

    def test_uniform_win_reaches_significant(self):
        """6 页全胜 + CI 不跨 0 -> significant（唯一能达标的形态）。"""
        pages_base = {f"p{i}": (10 * i, 100, 10, 2) for i in range(1, 7)}
        pages_cell = {f"p{i}": (10 * i + 8, 100, 10, 1) for i in range(1, 7)}
        base = make_cell(cell_id_of(BASELINE_ARM_ID, PC_OFF), BASELINE_ARM_ID,
                         note=35.0, field=80.0, pages=pages_base)
        cell = make_cell("pre_scan__pc_off", "pre_scan",
                         note=43.0, field=90.0, pages=pages_cell)
        d = compute_delta(cell, base, DecisionThresholds(bootstrap_iters=800))
        self.assertEqual(d.pages_improved, 6)
        self.assertEqual(d.pages_worsened, 0)
        self.assertAlmostEqual(d.sign_test_p, 0.03125, places=6)
        self.assertGreater(d.ci95_note_pass_pp[0], 0.0)
        self.assertEqual(d.verdict, VERDICT_SIGNIFICANT)

    def test_to_dict_json_serializable(self):
        d = compute_delta(self._cell(degraded=("p2",)), self._baseline(),
                          FAST_TH)
        text = json.dumps(d.to_dict(), ensure_ascii=False)
        self.assertIn("d_note_pass_pp_excl_degraded", text)


# ======================================================================
# 5. 不变量 / 透明性 / 探针
# ======================================================================


class TestInvariant(unittest.TestCase):
    """🔴 P1-1 立项红线：干净 GT 上 applied 必须为 0。"""

    def test_all_clean_passes(self):
        reports = {f"gt{i}.musicxml": {"appliedCount": 0, "applied": [],
                                       "flaggedCount": 1,
                                       "flagged": [{"kind": "rhythm"}]}
                   for i in range(13)}
        r = evaluate_invariant(reports)
        self.assertTrue(r.passed)
        self.assertEqual(r.gt_files_checked, 13)
        self.assertEqual(r.violations, ())
        self.assertTrue(all(v == 0 for v in r.applied_per_file.values()))

    def test_flagged_is_allowed_applied_is_not(self):
        """flagged（只标记不改）不算违规，applied（真改了）才算。

        本例只关心 applied/flagged 的语义，因此用 ``expected=0`` 关掉覆盖度
        门槛，避免两份样本触发「覆盖不足」噪声——覆盖度语义由
        :meth:`test_shrunken_coverage_is_a_violation` 单独锁。
        """
        r = evaluate_invariant({
            "ok.musicxml": {"appliedCount": 0, "flaggedCount": 9},
            "bad.musicxml": {"appliedCount": 2,
                             "applied": [{"kind": "rhythm"},
                                         {"kind": "tuplet"}]},
        }, expected=0)
        self.assertFalse(r.passed)
        self.assertEqual(len(r.violations), 1)
        self.assertIn("bad.musicxml", r.violations[0])
        self.assertIn("rhythm", r.violations[0])
        self.assertEqual(r.applied_per_file["ok.musicxml"], 0)
        self.assertEqual(r.applied_per_file["bad.musicxml"], 2)

    def test_shrunken_coverage_is_a_violation(self):
        """🔴 QA-1：报告集合缩水（< 13）不许「真空为真」地放行。"""
        reports = {f"gt{i}.musicxml": {"appliedCount": 0}
                   for i in range(INVARIANT_EXPECTED_GT - 1)}
        r = evaluate_invariant(reports)
        self.assertFalse(r.passed)
        self.assertEqual(r.gt_files_checked, INVARIANT_EXPECTED_GT - 1)
        self.assertTrue(any("覆盖不足" in v for v in r.violations),
                        f"缺少覆盖度违规：{r.violations}")

    def test_missing_report_counts_as_violation(self):
        """跑失败 = 无法自证清白 = 违规（不能因为没数据就放过）。"""
        r = evaluate_invariant({"x.musicxml": None})
        self.assertFalse(r.passed)
        self.assertEqual(r.applied_per_file["x.musicxml"], -1)
        self.assertIn("无法验证不变量", r.violations[0])

    def test_applied_count_falls_back_to_list(self):
        r = evaluate_invariant({"y.musicxml": {"applied": [{"kind": "key"}]}})
        self.assertFalse(r.passed)
        self.assertEqual(r.applied_per_file["y.musicxml"], 1)

    def test_empty_input_does_not_pass_vacuously(self):
        """🔴 QA-1：空报告集合必须判 FAIL，而不是「没数据 = 没违规」。"""
        r = evaluate_invariant({})
        self.assertFalse(r.passed)
        self.assertEqual(r.gt_files_checked, 0)
        self.assertTrue(any("覆盖不足 0/" in v for v in r.violations),
                        f"空集合未报覆盖不足：{r.violations}")

    def test_expected_zero_restores_pure_applied_semantics(self):
        """``expected=0`` 是显式的「只查 applied」逃生口，供单元隔离使用。"""
        r = evaluate_invariant({}, expected=0)
        self.assertTrue(r.passed)
        self.assertEqual(r.violations, ())


class TestTransparency(unittest.TestCase):
    """R7：pipe_noop 必须与 pre_off 完全一致。"""

    def _pair(self, **cell_kw):
        base = make_cell(cell_id_of(BASELINE_ARM_ID, PC_OFF), BASELINE_ARM_ID,
                         note=2.65, field=61.11,
                         pages={"p1": (10, 100, 3, 1)},
                         category_distribution={"rhythm": 100})
        defaults = dict(note=2.65, field=61.11,
                        pages={"p1": (10, 100, 3, 1)},
                        category_distribution={"rhythm": 100})
        defaults.update(cell_kw)
        noop = make_cell(cell_id_of(SANITY_ARM_ID, PC_OFF), SANITY_ARM_ID,
                         **defaults)
        return noop, base

    def test_identical_is_transparent(self):
        noop, base = self._pair()
        self.assertEqual(check_transparency(noop, base), [])

    def test_note_rate_drift_is_blocking(self):
        noop, base = self._pair(note=2.70)
        findings = check_transparency(noop, base)
        self.assertEqual(len(findings), 1)
        self.assertIn("note_pass_rate", findings[0])
        self.assertIn("透明性破裂", findings[0])

    def test_denominator_drift_is_blocking(self):
        noop, base = self._pair(pages={"p1": (10, 99, 3, 1)})
        findings = check_transparency(noop, base)
        self.assertTrue(any("notes_compared" in f for f in findings))

    def test_category_distribution_drift_is_blocking(self):
        noop, base = self._pair(category_distribution={"rhythm": 101})
        findings = check_transparency(noop, base)
        self.assertTrue(any("category_distribution" in f for f in findings))

    def test_missing_cell_is_silent(self):
        self.assertEqual(check_transparency(None, None), [])


class TestDeskewProbe(unittest.TestCase):
    """K2 / R1：photo vs photo_nodeskew 单变量归因（U7）。"""

    def _deltas(self, photo_note, probe_note):
        return [
            make_delta("pre_photo__pc_off", d_note=photo_note),
            make_delta(cell_id_of(PROBE_ARM_ID, PC_OFF), d_note=probe_note),
        ]

    def test_deskew_identified_as_harmful(self):
        msg = diagnose_deskew(self._deltas(-2.5, 1.2))
        self.assertIsNotNone(msg)
        self.assertIn("enable_deskew 改回 false", msg)

    def test_both_non_negative_means_no_conflict(self):
        msg = diagnose_deskew(self._deltas(1.0, 1.5))
        self.assertIn("同为非负", msg)

    def test_both_negative_is_inconclusive(self):
        msg = diagnose_deskew(self._deltas(-1.0, -2.0))
        self.assertIn("未构成", msg)

    def test_missing_probe_returns_none(self):
        self.assertIsNone(diagnose_deskew(
            [make_delta("pre_photo__pc_off", d_note=-1.0)]))
        self.assertIsNone(diagnose_deskew([]))


# ======================================================================
# 6. decide_preprocess（C1–C5 边界）
# ======================================================================


class TestDecidePreprocess(unittest.TestCase):
    """设计 §6.3：每条判据测「刚好通过」与「差一点」两侧。"""

    TH = DecisionThresholds()

    def _scenario(self, cell_kw=None, delta_kw=None, arm_id="pre_scan"):
        """构造一个"刚好全过 C1–C5"的候选，再按需扰动。"""
        cid = cell_id_of(arm_id, PC_OFF)
        cell_defaults = dict(arm_id=arm_id, note=25.0, field=85.0,
                             pages={f"p{i}": (10, 100, 3, 0)
                                    for i in range(1, 7)},
                             category_pass={"rhythm": 45.0,
                                            "pitch_degree": 55.0},
                             total_ms=120.0)
        cell_defaults.update(cell_kw or {})
        cells = {cid: make_cell(cid, **cell_defaults)}

        delta_defaults = dict(
            d_note=1.0, d_field=1.0,
            d_cat_pass={"rhythm": 2.0, "pitch_degree": -1.0},
            improved=5, worsened=1, d_event=0, p=0.21875, ci=(-0.5, 5.0),
            verdict=VERDICT_DIRECTIONAL)
        delta_defaults.update(delta_kw or {})
        deltas = [make_delta(cid, **delta_defaults)]
        return deltas, cells

    def _decide(self, **kw):
        deltas, cells = self._scenario(**kw)
        return decide_preprocess(deltas, cells, self.TH)

    # —— 全过 ——
    def test_all_criteria_exactly_at_boundary_passes(self):
        """Δnote=1.0 / Δfield=1.0 / 最差维度=-1.0 / 5 改善 1 恶化 / Δevent=0。"""
        verdict, trace = self._decide()
        self.assertEqual(verdict, "on:scan")
        self.assertTrue(any("推荐默认开 scan" in t for t in trace))
        self.assertTrue(any("preprocess_default=on:scan" in t for t in trace))

    # —— C0 可比性（SK-10）——
    def test_c0_fatal_cell_rejected(self):
        verdict, trace = self._decide(cell_kw={"fatal_files": ("p9.jpg",)})
        self.assertEqual(verdict, "off")
        self.assertTrue(any("C0 可比" in t and "❌" in t for t in trace))

    # —— C1 降级页 ——
    def test_c1_degraded_page_rejects_candidate(self):
        verdict, trace = self._decide(cell_kw={"degraded": ("p2",)})
        self.assertEqual(verdict, "off")
        self.assertTrue(any("C1 降级页=1" in t for t in trace))

    def test_c1_can_be_relaxed_by_threshold(self):
        deltas, cells = self._scenario(cell_kw={"degraded": ("p2",)})
        th = DecisionThresholds(require_zero_degraded=False)
        verdict, _ = decide_preprocess(deltas, cells, th)
        self.assertEqual(verdict, "on:scan")

    # —— C2 主指标增益 ——
    def test_c2_note_gain_just_below_threshold(self):
        verdict, _ = self._decide(delta_kw={"d_note": 0.99})
        self.assertEqual(verdict, "off")

    def test_c2_field_gain_just_below_threshold(self):
        verdict, _ = self._decide(delta_kw={"d_field": 0.99})
        self.assertEqual(verdict, "off")

    # —— C3 维度退化 ——
    def test_c3_category_regression_exactly_at_limit_passes(self):
        verdict, _ = self._decide(
            delta_kw={"d_cat_pass": {"rhythm": 2.0, "tie": -1.0}})
        self.assertEqual(verdict, "on:scan")

    def test_c3_category_regression_beyond_limit_rejected(self):
        verdict, trace = self._decide(
            delta_kw={"d_cat_pass": {"rhythm": 2.0, "tie": -1.01}})
        self.assertEqual(verdict, "off")
        self.assertTrue(any("C3 最差维度 tie" in t for t in trace))

    # —— C4 逐页稳健 ——
    def test_c4_too_few_improved_pages(self):
        verdict, _ = self._decide(delta_kw={"improved": 4, "worsened": 1})
        self.assertEqual(verdict, "off")

    def test_c4_too_many_worsened_pages(self):
        verdict, _ = self._decide(delta_kw={"improved": 5, "worsened": 2})
        self.assertEqual(verdict, "off")

    # —— C5 对齐健康度 ——
    def test_c5_event_count_increase_rejected(self):
        verdict, trace = self._decide(delta_kw={"d_event": 1})
        self.assertEqual(verdict, "off")
        self.assertTrue(any("C5 Δevent_count=+1" in t for t in trace))

    def test_c5_event_count_decrease_is_good(self):
        verdict, _ = self._decide(delta_kw={"d_event": -3})
        self.assertEqual(verdict, "on:scan")

    # —— 候选筛选 ——
    def test_baseline_sanity_and_probe_are_never_candidates(self):
        """基线/sanity/探针都不是"可推荐 preset"。"""
        cells = {}
        deltas = []
        for arm in (BASELINE_ARM_ID, SANITY_ARM_ID, PROBE_ARM_ID):
            cid = cell_id_of(arm, PC_OFF)
            cells[cid] = make_cell(cid, arm_id=arm,
                                   pages={f"p{i}": (10, 100, 3, 0)
                                          for i in range(1, 7)})
            deltas.append(make_delta(cid, d_note=9.0, d_field=9.0,
                                     improved=6, worsened=0))
        verdict, trace = decide_preprocess(deltas, cells, self.TH)
        self.assertEqual(verdict, "off")
        self.assertTrue(any("无候选 preset arm" in t for t in trace))

    def test_pc_on_cells_are_not_preprocess_candidates(self):
        cid = cell_id_of("pre_scan", PC_ON)
        cells = {cid: make_cell(cid, arm_id="pre_scan", postcorrect=True)}
        deltas = [make_delta(cid,
                             baseline_cell_id=cell_id_of("pre_scan", PC_OFF),
                             d_note=9.0, d_field=9.0)]
        verdict, _ = decide_preprocess(deltas, cells, self.TH)
        self.assertEqual(verdict, "off")

    def test_selection_prefers_highest_field_gain(self):
        deltas, cells = [], {}
        for arm, d_field in (("pre_scan", 1.5), ("pre_default", 3.0),
                             ("pre_low_contrast", 2.0)):
            sub_d, sub_c = self._scenario(arm_id=arm,
                                          delta_kw={"d_field": d_field})
            deltas.extend(sub_d)
            cells.update(sub_c)
        verdict, trace = decide_preprocess(deltas, cells, self.TH)
        self.assertEqual(verdict, "on:default")
        self.assertTrue(any("3 个 preset 通过 C1–C5" in t for t in trace))

    def test_selection_tiebreak_by_note_then_latency(self):
        deltas, cells = [], {}
        sub_d, sub_c = self._scenario(arm_id="pre_scan",
                                      delta_kw={"d_field": 2.0, "d_note": 2.0},
                                      cell_kw={"total_ms": 500.0})
        deltas.extend(sub_d)
        cells.update(sub_c)
        sub_d, sub_c = self._scenario(arm_id="pre_default",
                                      delta_kw={"d_field": 2.0, "d_note": 2.0},
                                      cell_kw={"total_ms": 100.0})
        deltas.extend(sub_d)
        cells.update(sub_c)
        verdict, _ = decide_preprocess(deltas, cells, self.TH)
        self.assertEqual(verdict, "on:default", "Δ 平手时应取更快的 preset")

    def test_off_still_reports_best_manual_candidate(self):
        """全不达标也要给"手动使用建议"，不能只丢一句 off。"""
        deltas, cells = self._scenario(delta_kw={"d_note": 0.2, "d_field": 0.3})
        verdict, trace = decide_preprocess(deltas, cells, self.TH)
        self.assertEqual(verdict, "off")
        self.assertTrue(any("手动使用建议" in t for t in trace))
        self.assertTrue(any("维持 opt-in" in t for t in trace))


# ======================================================================
# 7. decide_postcorrect（C1′–C5′ 边界）
# ======================================================================


class TestDecidePostcorrect(unittest.TestCase):
    """设计 §6.4：观测对 = pre_off__pc_on vs pre_off__pc_off。"""

    TH = DecisionThresholds()
    OK_INV = InvariantResult(passed=True, gt_files_checked=13)

    def _scenario(self, delta_kw=None, cell_kw=None):
        target = cell_id_of(BASELINE_ARM_ID, PC_ON)
        base = cell_id_of(BASELINE_ARM_ID, PC_OFF)
        cell_defaults = dict(arm_id=BASELINE_ARM_ID, postcorrect=True,
                             note=3.0, field=72.0, applied=17, flagged=4,
                             pages={f"p{i}": (5, 100, 3, 0)
                                    for i in range(1, 7)})
        cell_defaults.update(cell_kw or {})
        cells = {target: make_cell(target, **cell_defaults),
                 base: make_cell(base, arm_id=BASELINE_ARM_ID, note=2.65,
                                 field=61.11,
                                 pages={f"p{i}": (4, 100, 3, 1)
                                        for i in range(1, 7)})}
        delta_defaults = dict(
            baseline_cell_id=base,
            d_note=0.35, d_field=10.89,
            d_cat_count={"rhythm": -20, "tuplet": -3, "pitch_octave": -1,
                         "pitch_degree": 0, "tie": -2},
            improved=4, worsened=0, tied=2, p=0.125, ci=(-0.2, 1.0),
            verdict=VERDICT_DIRECTIONAL)
        delta_defaults.update(delta_kw or {})
        return [make_delta(target, **delta_defaults)], cells

    def _decide(self, invariant=None, **kw):
        deltas, cells = self._scenario(**kw)
        return decide_postcorrect(deltas, cells, invariant or self.OK_INV,
                                  self.TH)

    def test_all_criteria_pass(self):
        verdict, trace = self._decide()
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_ON)
        self.assertTrue(any("on_for_omr_path" in t for t in trace))
        # U6：必须写清"只在 --from-omr 入口默认开"
        joined = "\n".join(trace)
        self.assertIn("--from-omr", joined)
        self.assertIn("--no-postcorrect", joined)
        self.assertIn("转换入口保持默认关", joined)

    def test_c1_invariant_failure_fails_whole_run(self):
        """🔴 不变量破了 -> 整轮 FAIL，不出任何建议。"""
        bad = InvariantResult(passed=False, gt_files_checked=13,
                              violations=("gt1: applied=2",))
        verdict, trace = self._decide(invariant=bad)
        self.assertEqual(verdict, POSTCORRECT_FAIL)
        self.assertTrue(any("整轮 FAIL" in t for t in trace))
        # FAIL 时不应继续评估 C2′–C5′
        self.assertFalse(any(t.startswith("C2′") for t in trace))

    def test_c2_relevant_categories_must_net_decrease(self):
        verdict, trace = self._decide(
            delta_kw={"d_cat_count": {"rhythm": 0, "tuplet": 0}})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)
        self.assertTrue(any("C2′" in t and "❌" in t for t in trace))

    def test_c2_positive_relevant_sum_rejected(self):
        verdict, _ = self._decide(
            delta_kw={"d_cat_count": {"rhythm": 5, "tuplet": -1}})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)

    def test_c3_unrelated_category_must_not_worsen(self):
        """后处理不该动 tie/chord 这些类别，动了就是副作用。"""
        verdict, trace = self._decide(
            delta_kw={"d_cat_count": {"rhythm": -20, "tie": +2}})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)
        self.assertTrue(any("C3′" in t and "tie" in t for t in trace))

    def test_c3_unrelated_category_decrease_is_fine(self):
        verdict, _ = self._decide(
            delta_kw={"d_cat_count": {"rhythm": -20, "tie": -2}})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_ON)

    def test_c4_note_pass_must_not_regress(self):
        verdict, trace = self._decide(delta_kw={"d_note": -0.01})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)
        self.assertTrue(any("C4′" in t and "❌" in t for t in trace))

    def test_c4_zero_note_delta_is_acceptable(self):
        verdict, _ = self._decide(delta_kw={"d_note": 0.0})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_ON)

    def test_c5_field_gain_boundary(self):
        self.assertEqual(self._decide(delta_kw={"d_field": 0.5})[0],
                         POSTCORRECT_DEFAULT_ON)
        self.assertEqual(self._decide(delta_kw={"d_field": 0.49})[0],
                         POSTCORRECT_DEFAULT_OFF)

    def test_missing_observation_pair_yields_off(self):
        verdict, trace = decide_postcorrect([], {}, self.OK_INV, self.TH)
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)
        self.assertTrue(any("缺少观测对" in t for t in trace))

    def test_fatal_pages_block_decision(self):
        verdict, trace = self._decide(cell_kw={"fatal_files": ("p7.jpg",)})
        self.assertEqual(verdict, POSTCORRECT_DEFAULT_OFF)
        self.assertTrue(any("SK-10" in t for t in trace))

    def test_audit_stats_are_recorded_in_trace(self):
        _, trace = self._decide()
        self.assertTrue(any("applied=17" in t and "flagged=4" in t
                            for t in trace))


# ======================================================================
# 8. make_decision + 渲染
# ======================================================================


def build_summary(significant=False, invariant_ok=True, degraded=False,
                  extra_blocking=()):
    """搭一份端到端的 :class:`AbtestSummary`（供决策/渲染测试复用）。"""
    base_id = cell_id_of(BASELINE_ARM_ID, PC_OFF)
    pc_on_id = cell_id_of(BASELINE_ARM_ID, PC_ON)
    scan_id = cell_id_of("pre_scan", PC_OFF)

    pages = {f"p{i}": (10 * i, 100, 3, 1) for i in range(1, 7)}
    baseline = make_cell(base_id, BASELINE_ARM_ID, note=2.65, field=61.11,
                         pages=pages,
                         category_pass={"rhythm": 40.0},
                         category_distribution={"rhythm": 100,
                                                "event_count": 12})
    scan = make_cell(scan_id, "pre_scan", note=5.0, field=65.0,
                     pages={f"p{i}": (10 * i + 5, 100, 3, 0)
                            for i in range(1, 7)},
                     category_pass={"rhythm": 43.0},
                     category_distribution={"rhythm": 95, "event_count": 10},
                     degraded=("p3",) if degraded else (),
                     total_ms=130.0)
    pc_on = make_cell(pc_on_id, BASELINE_ARM_ID, postcorrect=True,
                      note=3.0, field=72.0, pages=pages,
                      category_pass={"rhythm": 44.0},
                      category_distribution={"rhythm": 80, "event_count": 12},
                      applied=17, flagged=4)

    cells = {base_id: baseline, scan_id: scan, pc_on_id: pc_on}
    deltas = [
        make_delta(scan_id, base_id, d_note=2.35, d_field=3.89,
                   d_cat_pass={"rhythm": 3.0},
                   d_cat_count={"rhythm": -5, "event_count": -2},
                   improved=6, worsened=0, tied=0,
                   p=0.03125 if significant else 0.21875,
                   ci=(0.8, 4.0) if significant else (-0.5, 4.0),
                   d_event=-2,
                   verdict=(VERDICT_SIGNIFICANT if significant
                            else VERDICT_DIRECTIONAL),
                   excluded_pages=("p3",) if degraded else (),
                   d_note_excl=2.80 if degraded else None,
                   d_field_excl=4.20 if degraded else None),
        make_delta(pc_on_id, base_id, d_note=0.35, d_field=10.89,
                   d_cat_pass={"rhythm": 4.0},
                   d_cat_count={"rhythm": -20, "tuplet": -3},
                   improved=4, worsened=0, tied=2, p=0.125, ci=(-0.2, 1.0),
                   d_event=0, verdict=VERDICT_DIRECTIONAL),
    ]
    invariant = InvariantResult(
        passed=invariant_ok, gt_files_checked=13,
        applied_per_file={f"gt{i}": 0 for i in range(13)},
        violations=() if invariant_ok else ("gt1: applied=2 —— 红线被打破",))
    decision = make_decision(cells, deltas, invariant,
                             DecisionThresholds(),
                             extra_blocking=extra_blocking,
                             corpus_label="clean-scan concerto 6p")
    cfg = ExperimentConfig(run_id="p1_2_test", corpus_dir="corpus",
                           work_root="out", env=EnvFingerprint(git_head="deadbeef"))
    return AbtestSummary(config=cfg,
                         cells=tuple(cells[k] for k in sorted(cells)),
                         deltas=tuple(deltas), invariant=invariant,
                         decision=decision)


class TestMakeDecision(unittest.TestCase):

    def test_confidence_directional_carries_sk11_warning(self):
        s = build_summary(significant=False)
        self.assertIn("directional-only", s.decision.confidence)
        self.assertIn("SK-11", s.decision.confidence)
        self.assertIn("clean-scan concerto 6p", s.decision.confidence)
        self.assertIn("n=6 pages", s.decision.confidence)

    def test_confidence_significant_when_any_arm_significant(self):
        s = build_summary(significant=True)
        self.assertIn("significant on at least one arm", s.decision.confidence)

    def test_invariant_failure_propagates_everywhere(self):
        s = build_summary(invariant_ok=False)
        self.assertEqual(s.decision.postcorrect_default, POSTCORRECT_FAIL)
        self.assertTrue(any("红线被打破" in b
                            for b in s.decision.blocking_findings))
        # 不变量破了也不能自称 significant
        self.assertIn("directional-only", s.decision.confidence)

    def test_extra_blocking_findings_are_merged(self):
        s = build_summary(extra_blocking=("R7 透明性破裂：pipe_noop 与 pre_off 不同",))
        self.assertTrue(any("R7" in b for b in s.decision.blocking_findings))

    def test_preprocess_decision_uses_thresholds(self):
        """Δnote=2.35 / Δfield=3.89 / 6:0 改善 / Δevent=-2 -> 推荐 scan。"""
        s = build_summary()
        self.assertEqual(s.decision.preprocess_default, "on:scan")

    def test_degraded_page_blocks_preprocess_recommendation(self):
        s = build_summary(degraded=True)
        self.assertEqual(s.decision.preprocess_default, "off")

    def test_fatal_cell_is_reported_as_blocking(self):
        base_id = cell_id_of(BASELINE_ARM_ID, PC_OFF)
        cells = {base_id: make_cell(base_id, BASELINE_ARM_ID,
                                    fatal_files=("p2.jpg",))}
        d = make_decision(cells, [],
                          InvariantResult(passed=True,
                                          gt_files_checked=INVARIANT_EXPECTED_GT))
        self.assertTrue(any("SK-10" in b for b in d.blocking_findings))

    def test_fatal_blocking_note_lists_pages_as_plain_ascii_csv(self):
        """SK-10 阻断性发现里的页名必须是**排序后的纯 ASCII 逗号分隔**串。

        历史写法内插 ``list(...)`` 的 repr（``['p3.jpg', 'p1.jpg']``），中括号
        与引号既是阅读噪声，也让日志在终端复制/转贴时更容易缺字。改用
        ``_fmt_files`` 后：页名逐字可读、顺序稳定（可 diff、可快照断言）。
        """
        base_id = cell_id_of(BASELINE_ARM_ID, PC_OFF)
        cells = {base_id: make_cell(base_id, BASELINE_ARM_ID,
                                    fatal_files=("p3.jpg", "p1.jpg"))}
        d = make_decision(cells, [],
                          InvariantResult(passed=True,
                                          gt_files_checked=INVARIANT_EXPECTED_GT))
        note = next(b for b in d.blocking_findings if "SK-10" in b)
        # 真实页名逐字出现，且按字典序、以 ", " 分隔
        self.assertIn("p1.jpg, p3.jpg", note)
        self.assertIn(base_id, note)
        # 不再有 list repr 的中括号 / 引号噪声
        for noise in ("[", "]", "'", '"'):
            self.assertNotIn(noise, note,
                             f"SK-10 阻断性发现不应出现 repr 噪声 {noise!r}：{note}")

    def test_fatal_delta_note_lists_pages_as_plain_ascii_csv(self):
        """``compute_delta`` 的 SK-10 说明同样走纯 ASCII 逗号分隔格式。"""
        base_id = cell_id_of(BASELINE_ARM_ID, PC_OFF)
        cell_id = cell_id_of("pre_scan", PC_OFF)
        baseline = make_cell(base_id, BASELINE_ARM_ID)
        cell = make_cell(cell_id, "pre_scan", fatal_files=("p9.jpg", "p4.jpg"))
        d = compute_delta(cell, baseline)
        note = next(n for n in d.notes if "SK-10" in n)
        self.assertIn("p4.jpg, p9.jpg", note)
        for noise in ("[", "]", "'"):
            self.assertNotIn(noise, note,
                             f"SK-10 Δ 说明不应出现 repr 噪声 {noise!r}：{note}")

    def test_fmt_files_renders_empty_set_without_dangling_separator(self):
        """空集合退化成 ``(none)``，避免日志出现悬空分隔符。"""
        self.assertEqual(L._fmt_files(()), "(none)")
        self.assertEqual(L._fmt_files(["b", "a"]), "a, b")


class TestRenderMarkdown(unittest.TestCase):

    def setUp(self):
        self.summary = build_summary()
        self.md = render_markdown(self.summary)

    def test_confidence_section_is_mandatory(self):
        self.assertIn("## 0. 置信度声明（SK-11）", self.md)
        self.assertIn("**confidence**:", self.md)

    def test_forbidden_wording_only_appears_inside_prohibition(self):
        """🔴 SK-11：'已验证' 只允许出现在"禁止这样写"的那句话里。"""
        for line in self.md.splitlines():
            if "已验证" in line or "已证明" in line:
                self.assertIn("禁止", line,
                              f"疑似违规表述：{line}")

    def test_directional_rendered_with_hedged_wording(self):
        self.assertIn("方向性证据（未达显著）", self.md)

    def test_all_sections_present(self):
        for heading in ("## 1. 阻断性发现",
                        "## 2. 环境指纹与阈值",
                        "## 3. cell 矩阵",
                        "## 4. Δ 表",
                        "## 5. 降级页双口径",
                        "## 6. 逐维度 category_pass Δ",
                        "## 7. Stage-3 不变量守护",
                        "## 8. 决策"):
            self.assertIn(heading, self.md)

    def test_env_and_thresholds_are_rendered(self):
        self.assertIn("deadbeef", self.md)
        self.assertIn("thresholds.bootstrap_seed", self.md)
        self.assertIn("20260801", self.md)

    def test_dual_metric_section_when_degraded(self):
        md = render_markdown(build_summary(degraded=True))
        self.assertIn("Δnote 剔除降级页", md)

    def test_dual_metric_section_says_nothing_when_clean(self):
        self.assertIn("无需第二口径", self.md)

    def test_invariant_verdict_rendered(self):
        self.assertIn("PASS ✅", self.md)
        self.assertIn("13 份干净 GT", self.md)
        self.assertIn("FAIL 🔴", render_markdown(build_summary(
            invariant_ok=False)))

    def test_to_markdown_matches_render(self):
        self.assertEqual(self.summary.to_markdown(), self.md)


class TestSummarySerialization(unittest.TestCase):

    def test_to_json_roundtrip(self):
        summary = build_summary()
        payload = summary.to_json()
        text = json.dumps(payload, ensure_ascii=False)
        back = json.loads(text)
        self.assertEqual(back["schema"], L.SCHEMA)
        self.assertEqual(back["run_id"], "p1_2_test")
        self.assertEqual(len(back["cells"]), 3)
        self.assertEqual(len(back["deltas"]), 2)
        self.assertTrue(back["invariant"]["passed"])
        self.assertIn("confidence", back["decision"])

    def test_cell_map(self):
        summary = build_summary()
        cmap = summary.cell_map()
        self.assertIn(cell_id_of(BASELINE_ARM_ID, PC_OFF), cmap)
        self.assertEqual(len(cmap), 3)


class TestPurity(unittest.TestCase):
    """本模块必须保持"纯"：无第三方依赖、无 I/O、无子进程。"""

    def test_no_heavy_third_party_imports(self):
        """增量口径：只追究**导入 omr_abtest_lib 本身**拉进来的重型库。

        全局快照式的 ``assertNotIn(banned, sys.modules)`` 会被同 session 的
        前置用例污染（它们合法地用 cv2/numpy），属于测试隔离缺陷而非产品缺陷。
        """
        assert_import_is_pure(self, "omr_abtest_lib", HEAVY_MODULES)

    def test_no_io_or_subprocess_modules_referenced(self):
        source = open(L.__file__, encoding="utf-8").read()
        for banned in ("import subprocess", "import shutil", "open("):
            self.assertNotIn(banned, source,
                             f"纯函数层不应出现 {banned!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
