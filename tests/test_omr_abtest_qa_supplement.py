# -*- coding: utf-8 -*-
"""谱渡 Pudu · P1-2 · QA 独立补充测试（严过关 / 纯 stdlib）

本文件**不重复**工程师已覆盖的路径，只补三类东西：

1. **回归锁**（``TestStatBoundaryLocks`` / ``TestDecisionDeterminism`` /
   ``TestDegenerateInputs``）——QA 手工敲过、当前行为**正确**的边界，
   写成断言钉死，防后续重构悄悄改坏。重点是"诚实统计"那几条：
   单页 / 单页离群值 **不得**被判 ``significant``、bootstrap 逐位可复现、
   全降级页必须被 C1 一票否决、tie-breaking 与输入顺序无关。

2. **红线覆盖度**（``TestInvariantCoverageRedline``）——🔴 **当前失败**。
   ``evaluate_invariant`` 对空/缩水的报告集合返回 ``passed=True``
   （真空为真），使 C1′ 这道 P1-1 立项红线可被绕过。见类 docstring
   的复现步骤。这些用例是给工程师的**验收标准**，修好即转绿。

3. **契约锁**（``TestPageSetSemantics``）——把"页集合取交集"这一隐式语义
   显式钉住，避免将来有人改成"并集/左连接"而无人察觉。

约束：零第三方依赖（不引 scipy / pandas / numpy），不跑 oemer / Pudu /
子进程，全内存，秒级完成。
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import omr_abtest_lib as L  # noqa: E402
import omr_abtest_p1_2 as D  # noqa: E402
from omr_abtest_lib import (  # noqa: E402
    AbtestSummary, CellResult, DecisionThresholds, ExperimentConfig,
    InvariantResult, PageCounts, PreprocessMetricsSummary,
    bootstrap_ci_by_page, cell_id_of, check_transparency, compute_delta,
    decide_postcorrect, decide_preprocess, evaluate_invariant, make_decision,
    render_markdown, sign_test_p,
    BASELINE_ARM_ID, PC_OFF, PC_ON,
)

#: Stage-3 必须覆盖的干净 GT 份数：6 页 concerto + 7 份 P1-1 = 13。
EXPECTED_CLEAN_GT = 13


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def pages(spec):
    """``{page: (correct, compared)}`` -> ``{page: PageCounts}``。"""
    return {p: PageCounts(notes_compared=c_all, notes_correct=c_ok,
                          field_checked=10, field_failed=0)
            for p, (c_ok, c_all) in spec.items()}


def cell(cell_id, arm_id, *, postcorrect=False, note=0.0, field=0.0,
         page_spec=None, cats=None, fatal=(), degraded=()):
    page_spec = page_spec or {}
    pg = pages(page_spec)
    return CellResult(
        cell_id=cell_id, arm_id=arm_id, postcorrect=postcorrect,
        note_pass_rate=note, field_pass_rate=field,
        notes_compared=sum(v.notes_compared for v in pg.values()),
        notes_correct=sum(v.notes_correct for v in pg.values()),
        field_checked=10 * len(pg), field_failed=0,
        category_distribution=dict(cats or {}),
        per_page=pg, fatal_files=tuple(fatal),
        preprocess=PreprocessMetricsSummary(pages_total=len(pg),
                                            degraded_pages=tuple(degraded)))


SIX_LOW = {f"p{i}": (5, 10) for i in range(6)}
SIX_HIGH = {f"p{i}": (7, 10) for i in range(6)}


# ======================================================================
# 1. 统计边界回归锁（"诚实统计"是 SK-11 的落地面，不许退化）
# ======================================================================

class TestStatBoundaryLocks(unittest.TestCase):
    """符号检验 / bootstrap 的边界值锁。"""

    def test_sign_test_exact_table(self):
        """精确二项对表（设计 §6.2），逐值钉死。"""
        table = {
            (0, 0): 1.0, (1, 0): 1.0, (0, 1): 1.0,
            (6, 0): 0.03125, (5, 1): 0.21875, (4, 2): 0.6875, (3, 3): 1.0,
            (2, 0): 0.5, (3, 0): 0.25, (4, 0): 0.125, (5, 0): 0.0625,
        }
        for (imp, wor), want in sorted(table.items()):
            with self.subTest(improved=imp, worsened=wor):
                self.assertAlmostEqual(sign_test_p(imp, wor), want, places=10)

    def test_sign_test_is_symmetric(self):
        """双侧检验：交换 improved/worsened 不改 p。"""
        for imp, wor in ((6, 0), (5, 1), (4, 2), (7, 3), (1, 9)):
            with self.subTest(pair=(imp, wor)):
                self.assertEqual(sign_test_p(imp, wor), sign_test_p(wor, imp))

    def test_sign_test_never_exceeds_one(self):
        """p 恒落在 (0, 1]，任何 n 都不得溢出。"""
        for imp in range(0, 12):
            for wor in range(0, 12):
                p = sign_test_p(imp, wor)
                self.assertGreater(p, 0.0)
                self.assertLessEqual(p, 1.0)

    def test_sign_test_clamps_negative_input(self):
        """负数入参被夹到 0，不得算出负 n 或抛异常。"""
        self.assertEqual(sign_test_p(-3, 5), sign_test_p(0, 5))
        self.assertEqual(sign_test_p(-1, -1), 1.0)

    def test_six_pages_minimum_reachable_p(self):
        """🔴 6 页语料下 p 的下确界 = 0.03125 > 0 —— 只有 6:0 全胜够格叫显著。"""
        best = min(sign_test_p(i, 6 - i) for i in range(7))
        self.assertAlmostEqual(best, 0.03125, places=10)
        self.assertGreater(best, 0.0)

    def test_bootstrap_is_bit_reproducible(self):
        """SK-9：固定 seed ⇒ 同输入必得同输出（跨调用、跨顺序）。"""
        a = bootstrap_ci_by_page(pages_pairs(SIX_HIGH), pages_pairs(SIX_LOW))
        b = bootstrap_ci_by_page(pages_pairs(SIX_HIGH), pages_pairs(SIX_LOW))
        self.assertEqual(a, b)

    def test_bootstrap_seed_changes_result_shape_not_crash(self):
        lo1, hi1 = bootstrap_ci_by_page(pages_pairs(SIX_HIGH),
                                        pages_pairs(SIX_LOW), seed=1)
        lo2, hi2 = bootstrap_ci_by_page(pages_pairs(SIX_HIGH),
                                        pages_pairs(SIX_LOW), seed=2)
        self.assertLessEqual(lo1, hi1)
        self.assertLessEqual(lo2, hi2)

    def test_bootstrap_degenerate_inputs(self):
        """空 / 无交集 / iters<=0 / 零音符，一律安全返回 (0,0)，不得除零。"""
        one, oneb = {"p": (7, 10)}, {"p": (5, 10)}
        self.assertEqual(bootstrap_ci_by_page({}, {}), (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page({"a": (1, 2)}, {"b": (1, 2)}),
                         (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page(one, oneb, iters=0), (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page(one, oneb, iters=-5), (0.0, 0.0))
        self.assertEqual(bootstrap_ci_by_page({"p": (0, 0)}, {"p": (0, 0)},
                                              iters=50), (0.0, 0.0))

    def test_bootstrap_single_page_ci_is_degenerate(self):
        """单页重抽样只能抽到自己 ⇒ CI 退化为点，必须靠 p 值把关显著性。"""
        ci = bootstrap_ci_by_page({"p": (7, 10)}, {"p": (5, 10)}, iters=500)
        self.assertEqual(ci[0], ci[1])


def pages_pairs(spec):
    """``{page: (correct, compared)}`` -> bootstrap 入参形态。"""
    return {p: (c_ok, c_all) for p, (c_ok, c_all) in spec.items()}


# ======================================================================
# 2. 判定确定性 / 保守性回归锁
# ======================================================================

class TestDecisionDeterminism(unittest.TestCase):

    def test_single_page_improvement_is_never_significant(self):
        """🔴 R2：n=1 时 p=1.0，即便 CI 不跨 0 也只能是 directional。"""
        base = cell("pre_off__pc_off", "pre_off", note=50.0,
                    page_spec={"p0": (5, 10)})
        exp = cell("pre_scan__pc_off", "pre_scan", note=70.0,
                   page_spec={"p0": (7, 10)})
        d = compute_delta(exp, base)
        self.assertEqual(d.pages_improved, 1)
        self.assertEqual(d.sign_test_p, 1.0)
        self.assertNotEqual(d.verdict, L.VERDICT_SIGNIFICANT)
        self.assertEqual(d.verdict, L.VERDICT_DIRECTIONAL)

    def test_single_outlier_page_carrying_total_is_not_significant(self):
        """总分被单页离群值撑起（5 页打平 + 1 页暴涨）⇒ 不得判显著。"""
        flat = {f"p{i}": (1, 10) for i in range(5)}
        base = cell("pre_off__pc_off", "pre_off", note=10.0,
                    page_spec={**flat, "p5": (1, 10)})
        exp = cell("pre_scan__pc_off", "pre_scan", note=25.0,
                   page_spec={**flat, "p5": (10, 10)})
        d = compute_delta(exp, base)
        self.assertEqual((d.pages_improved, d.pages_worsened, d.pages_tied),
                         (1, 0, 5))
        self.assertNotEqual(d.verdict, L.VERDICT_SIGNIFICANT)

    def test_majority_worsened_is_regression_even_if_total_up(self):
        """Δnote>0 但多数页变差 ⇒ regression（不因不显著而放过）。"""
        base = cell("pre_off__pc_off", "pre_off", note=50.0,
                    page_spec={"p0": (5, 10), "p1": (5, 10), "p2": (5, 10)})
        exp = cell("pre_scan__pc_off", "pre_scan", note=60.0,
                   page_spec={"p0": (10, 10), "p1": (4, 10), "p2": (4, 10)})
        d = compute_delta(exp, base)
        self.assertGreater(d.d_note_pass_pp, 0.0)
        self.assertEqual(d.verdict, L.VERDICT_REGRESSION)

    def test_decide_preprocess_is_input_order_independent(self):
        """完全打平的两个 preset ⇒ 选优结果不得依赖 deltas 列表顺序。"""
        base = cell("pre_off__pc_off", "pre_off", note=50.0, field=90.0,
                    page_spec=SIX_LOW, cats={"pitch": 40, "event_count": 5})
        a = cell("pre_scan__pc_off", "pre_scan", note=70.0, field=95.0,
                 page_spec=SIX_HIGH, cats={"pitch": 20, "event_count": 4})
        b = cell("pre_photo__pc_off", "pre_photo", note=70.0, field=95.0,
                 page_spec=SIX_HIGH, cats={"pitch": 20, "event_count": 4})
        cells = {c.cell_id: c for c in (base, a, b)}
        ds = [compute_delta(a, base), compute_delta(b, base)]
        fwd, _ = decide_preprocess(ds, cells)
        rev, _ = decide_preprocess(list(reversed(ds)), cells)
        self.assertEqual(fwd, rev)
        self.assertTrue(fwd.startswith("on:"))

    def test_c1_vetoes_when_all_pages_degraded(self):
        """🔴 SK-5/C1：全部页 fail-open 降级 ⇒ 一票否决，且第二口径为 None。"""
        base = cell("pre_off__pc_off", "pre_off", note=50.0, field=90.0,
                    page_spec=SIX_LOW, cats={"pitch": 40, "event_count": 5})
        deg = cell("pre_photo__pc_off", "pre_photo", note=70.0, field=95.0,
                   page_spec=SIX_HIGH, cats={"pitch": 20, "event_count": 4},
                   degraded=tuple(SIX_HIGH))
        d = compute_delta(deg, base)
        self.assertTrue(d.degraded_contaminated)
        self.assertIsNone(d.d_note_pass_pp_excl_degraded)
        verdict, trace = decide_preprocess(
            [d], {base.cell_id: base, deg.cell_id: deg})
        self.assertEqual(verdict, "off")
        self.assertTrue(any("C1" in t for t in trace))

    def test_fatal_cell_is_blocked_and_excluded(self):
        """🔴 SK-10：有 fatal 页的 cell 不可比，必须进 blocking 且不参与决策。"""
        base = cell("pre_off__pc_off", "pre_off", note=50.0, field=90.0,
                    page_spec=SIX_LOW)
        bad = cell("pre_scan__pc_off", "pre_scan", note=90.0, field=99.0,
                   page_spec=SIX_HIGH, fatal=("p3",))
        d = compute_delta(bad, base)
        self.assertFalse(d.comparable)
        dec = make_decision({base.cell_id: base, bad.cell_id: bad}, [d],
                            InvariantResult(passed=True,
                                            gt_files_checked=EXPECTED_CLEAN_GT))
        self.assertEqual(dec.preprocess_default, "off")
        self.assertTrue(any("SK-10" in b for b in dec.blocking_findings))

    def test_transparency_catches_sub_pp_drift(self):
        """R7：透明代理与直调差 1e-4 pp 也必须报破裂（不许放宽容差）。"""
        a = cell("pipe_noop__pc_off", "pipe_noop", note=50.0, field=90.0,
                 page_spec=SIX_LOW)
        b = cell("pre_off__pc_off", "pre_off", note=50.0, field=90.0,
                 page_spec=SIX_LOW)
        self.assertEqual(check_transparency(a, b), [])
        drift = dataclasses.replace(a, note_pass_rate=50.0001)
        self.assertTrue(check_transparency(drift, b))
        self.assertEqual(check_transparency(None, b), [])
        self.assertEqual(check_transparency(a, None), [])


# ======================================================================
# 3. 退化输入不得崩溃（报告是最后一公里，崩了等于整轮白跑）
# ======================================================================

class TestDegenerateInputs(unittest.TestCase):

    def _empty_summary(self):
        cfg = ExperimentConfig(corpus_dir="x", work_root="w", run_id="r")
        inv = InvariantResult(passed=True, gt_files_checked=0)
        return AbtestSummary(config=cfg, cells=(), deltas=(), invariant=inv,
                             decision=make_decision({}, [], inv))

    def test_render_markdown_on_empty_summary(self):
        md = render_markdown(self._empty_summary())
        self.assertIn("P1-2", md)
        self.assertGreater(len(md.splitlines()), 10)

    def test_summary_json_is_serializable(self):
        """tuple / Mapping 必须能过 json.dumps，否则产物写不出来。"""
        txt = json.dumps(self._empty_summary().to_json(), ensure_ascii=False)
        self.assertIn("run_id", txt)

    def test_all_zero_delta_is_neutral(self):
        z1 = CellResult(cell_id="a__pc_off", arm_id="pre_off", postcorrect=False)
        z2 = CellResult(cell_id="b__pc_off", arm_id="pre_scan", postcorrect=False)
        d = compute_delta(z2, z1)
        self.assertEqual(d.d_note_pass_pp, 0.0)
        self.assertEqual(d.sign_test_p, 1.0)
        self.assertEqual(d.ci95_note_pass_pp, (0.0, 0.0))
        self.assertEqual(d.verdict, L.VERDICT_NEUTRAL)

    def test_aggregate_cell_on_empty_report(self):
        c = L.aggregate_cell("c", "pre_off", False, {})
        self.assertEqual(c.note_pass_rate, 0.0)
        self.assertEqual(c.pages_count, 0)
        self.assertTrue(c.comparable)

    def test_decide_preprocess_with_no_candidates(self):
        """矩阵里只剩基线/sanity/探针 ⇒ 判 off 并留痕，不得抛异常。"""
        verdict, trace = decide_preprocess([], {})
        self.assertEqual(verdict, "off")
        self.assertTrue(trace)


# ======================================================================
# 4. 🔴 红线：Stage-3 不变量覆盖度（**当前失败 —— 待工程师修复**）
# ======================================================================

class TestInvariantCoverageRedline(unittest.TestCase):
    """🔴 C1′ 真空为真缺陷（QA-1）。

    **现状**：``evaluate_invariant`` 只看"收到的报告里有没有非 0 applied"，
    不看"该收到多少份"。于是报告集合为空 / 缩水时一律 ``passed=True``，
    ``decide_postcorrect`` 的 C1′ 打出 ✅ 并放行 ``on_for_omr_path``，
    ``blocking_findings`` 为空 —— P1-1 立项红线（干净 GT 上一处都不许改）
    被真空绕过。

    **一条命令即可复现**（非杜撰路径，``--limit`` 是正式 smoke flag）::

        python tools/omr_abtest_p1_2.py run --limit 2

    此时 ``invariant_gt_files()`` 只剩 2 + 7 = 9 份（少了 4 页 concerto GT），
    报告照样写"C1′ 不变量：9 份干净 GT …✅"，与全量跑的绿色输出无法区分。

    **建议修法（任选其一，测试只锁契约不锁实现）**：

    * ``evaluate_invariant(reports, expected=N)``：``len(reports) < N`` 记违规；
    * ``AbtestDriver.invariant_gt_files()`` 不受 ``--limit`` 影响（Stage-3
      是固定 13 份清单，与打分语料子集无关）；且 P1-1 GT 缺文件时把
      ``[warn]`` 升级为 blocking finding；
    * ``decide_postcorrect``：``gt_files_checked <= 0`` 直接返回 off。
    """

    def _good_pair(self):
        rel = sorted(L.POSTCORRECT_RELEVANT)
        off = cell(cell_id_of(BASELINE_ARM_ID, PC_OFF), BASELINE_ARM_ID,
                   note=50.0, field=90.0, page_spec=SIX_LOW,
                   cats={**{c: 10 for c in rel}, "event_count": 5})
        on = cell(cell_id_of(BASELINE_ARM_ID, PC_ON), BASELINE_ARM_ID,
                  postcorrect=True, note=70.0, field=96.0, page_spec=SIX_HIGH,
                  cats={**{c: 4 for c in rel}, "event_count": 5})
        cells = {off.cell_id: off, on.cell_id: on}
        return cells, [compute_delta(on, off)]

    def test_sanity_full_coverage_recommends_on(self):
        """对照组：13 份齐全 + C2′–C5′ 全过 ⇒ 应推荐 on_for_omr_path。"""
        cells, deltas = self._good_pair()
        verdict, _ = decide_postcorrect(
            deltas, cells,
            InvariantResult(passed=True, gt_files_checked=EXPECTED_CLEAN_GT))
        self.assertEqual(verdict, L.POSTCORRECT_DEFAULT_ON)

    def test_zero_coverage_must_not_recommend_on(self):
        """🔴 0 份干净 GT 被验过 ⇒ 绝不能推荐默认开后处理。"""
        cells, deltas = self._good_pair()
        verdict, trace = decide_postcorrect(
            deltas, cells, InvariantResult(passed=True, gt_files_checked=0))
        self.assertNotEqual(
            verdict, L.POSTCORRECT_DEFAULT_ON,
            "C1′ 真空为真：0 份 GT 被验证却放行了 postcorrect 默认开；"
            f"实际返回 {verdict!r}，留痕首条={trace[0]!r}")

    def test_zero_coverage_must_produce_blocking_finding(self):
        """🔴 覆盖为 0 至少要留下阻断性发现，不能安静通过。"""
        cells, deltas = self._good_pair()
        dec = make_decision(cells, deltas,
                            InvariantResult(passed=True, gt_files_checked=0))
        self.assertTrue(
            dec.blocking_findings,
            "不变量覆盖为 0 时 blocking_findings 为空 —— "
            "报告与全量绿跑无法区分")

    def test_shrunken_coverage_must_not_recommend_on(self):
        """🔴 覆盖缩水（9/13，--limit 2 的真实后果）同样不得放行。"""
        cells, deltas = self._good_pair()
        verdict, _ = decide_postcorrect(
            deltas, cells, InvariantResult(passed=True, gt_files_checked=9))
        self.assertNotEqual(
            verdict, L.POSTCORRECT_DEFAULT_ON,
            "覆盖 9/13 仍放行 postcorrect 默认开")

    def test_invariant_gt_list_must_not_shrink_with_limit(self):
        """🔴 Stage-3 是固定 13 份清单，``--limit`` 只截断打分语料，不得截断红线。"""
        tmp = tempfile.mkdtemp(prefix="qa_inv_limit_")
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        cfg = D.build_config(corpus_dir=D.DEFAULT_CORPUS, work_root=tmp,
                             run_id="qa_limit", with_env=False)
        full = len(D.AbtestDriver(cfg, limit=0, verbose=False)
                   .invariant_gt_files())
        self.assertEqual(full, EXPECTED_CLEAN_GT)
        for lim in (1, 2, 3):
            with self.subTest(limit=lim):
                got = len(D.AbtestDriver(cfg, limit=lim, verbose=False)
                          .invariant_gt_files())
                self.assertEqual(
                    got, EXPECTED_CLEAN_GT,
                    f"--limit {lim} 把 Stage-3 红线覆盖从 13 缩到 {got} 份，"
                    f"且报告不会提示")

    def test_missing_p1_1_gt_file_is_surfaced(self):
        """🔴 P1-1 GT 文件缺失只打 [warn] 不够，必须能被判定层看见。"""
        tmp = tempfile.mkdtemp(prefix="qa_inv_missing_")
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        cfg = D.build_config(corpus_dir=D.DEFAULT_CORPUS, work_root=tmp,
                             run_id="qa_missing", with_env=False)
        broken = D.P1_1_CLEAN_GT[:-1] + ("__does_not_exist__.musicxml",)
        with mock.patch.object(D, "P1_1_CLEAN_GT", broken):
            files = D.AbtestDriver(cfg, verbose=False).invariant_gt_files()
        names = [os.path.basename(p) for p in files]
        reports = {n: {"appliedCount": 0, "applied": [], "flagged": []}
                   for n in names}
        res = evaluate_invariant(reports)
        self.assertFalse(
            res.passed,
            f"少了 1 份 P1-1 干净 GT（实收 {res.gt_files_checked}/"
            f"{EXPECTED_CLEAN_GT}）却判 PASS —— 红线被悄悄削弱")


# ======================================================================
# 5. 页集合语义契约锁
# ======================================================================

class TestPageSetSemantics(unittest.TestCase):
    """把"按页配对取交集"钉死，防将来被改成并集/左连接。"""

    def test_paired_stats_use_intersection(self):
        base = cell("b", "pre_off", page_spec={f"p{i}": (5, 10)
                                               for i in range(6)})
        part = cell("c", "pre_scan", page_spec={f"p{i}": (7, 10)
                                                for i in range(4)})
        d = compute_delta(part, base)
        self.assertEqual(d.pages_improved, 4)
        self.assertEqual(d.pages_worsened, 0)
        self.assertEqual(d.pages_tied, 0)

    def test_disjoint_page_sets_yield_no_pairs(self):
        a = cell("a", "pre_off", page_spec={"x": (5, 10)})
        b = cell("b", "pre_scan", page_spec={"y": (7, 10)})
        d = compute_delta(b, a)
        self.assertEqual((d.pages_improved, d.pages_worsened, d.pages_tied),
                         (0, 0, 0))
        self.assertEqual(d.sign_test_p, 1.0)
        self.assertEqual(d.ci95_note_pass_pp, (0.0, 0.0))

    def test_page_key_is_stem_not_path(self):
        """SK-3：页主键是 stem，不含目录 —— 换 cell 工作区不得打散配对。"""
        m = {"src": r"C:\ws\cells\pre_scan__pc_off\page1.jpg", "degraded": False}
        self.assertEqual(L._page_of_metrics(m), "page1")
        self.assertEqual(L._page_of_metrics({"page": "page1"}), "page1")
        self.assertEqual(L._page_of_metrics({}), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
