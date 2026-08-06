# -*- coding: utf-8 -*-
"""P1-2 · T04 不变量守护 / 透明性 / fatal 排除（库层，纯函数）。

本文件专门钉死设计 §2.4 / §6.3 / §6.4 / §10 的三条**硬红线**，全部在
``omr_abtest_lib`` 的纯函数层直测，**不跑 oemer、不跑 Pudu、不写文件**：

* **Stage-3 不变量断言（R6）**：``evaluate_invariant`` 对 13 份干净 GT 必须
  全过；任一份 ``applied != 0`` 或报告缺失 ⇒ 整轮 FAIL。本文件还用**真实语料
  清单**（6 页 concerto GT + 7 份 P1-1 语料 = 13 份，见
  ``tools/omr_abtest_p1_2.py`` 的 ``DEFAULT_CORPUS`` / ``P1_1_CLEAN_GT``）
  做端到端计数断言，证明守护确实覆盖 13 份。
* **pipe_noop 透明性（R7）**：``check_transparency`` 对 ``pre_off`` 基线必须
  **零差异**；任意一项（note/field 率、分子分母、category 分布）不等价 ⇒
  阻断性发现，并必须流入 ``make_decision`` 的 ``blocking_findings``。
* **fatal 页排除（SK-10）**：``fatal_files`` 非空的 cell ``comparable=False``，
  ``compute_delta`` 标记该 Δ 不可比、不进决策；``decide_preprocess`` 的 C0 判据
  直接否决该候选。

与 T03 的驱动集成单测互补：T03 走替身跑通 Stage-0~5，本文件在库层把三条红线的
**判定逻辑本身**再次钉死，避免「接线正确但判据被悄悄改弱」。

本文件**不 import cv2 / numpy / scipy**，且除读真实 GT 文件名外不产生任何 I/O
（不变量用合成审计报告喂 ``evaluate_invariant``，纯内存）。
"""

import os
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

import omr_abtest_lib as L  # noqa: E402
import omr_abtest_p1_2 as D  # noqa: E402
from omr_abtest_lib import (  # noqa: E402
    BASELINE_ARM_ID, SANITY_ARM_ID, PC_OFF, PC_ON, cell_id_of,
    CellResult, PageCounts, PreprocessMetricsSummary, PostCorrectSummary,
    DeltaResult, InvariantResult, DecisionThresholds,
    evaluate_invariant, check_transparency, compute_delta, make_decision,
)

#: 提速：bootstrap 压到 100 次（确定性由固定 seed 保证，SK-9）。
FAST_TH = DecisionThresholds(bootstrap_iters=100)

HEAVY = ("cv2", "numpy", "scipy", "pandas", "matplotlib")

CONCERTO_GT_COUNT = 6   # data/omr_eval/real/concerto_pages/*.gt.musicxml
P1_1_GT_COUNT = 7       # D.P1_1_CLEAN_GT 在 data/ 下的实有份数
EXPECTED_CLEAN_GT = CONCERTO_GT_COUNT + P1_1_GT_COUNT  # = 13


# ----------------------------------------------------------------------
# 构造器
# ----------------------------------------------------------------------

def _pages(n, notes_compared, notes_correct, field_checked, field_failed):
    """把整页计数**确定性地**摊到 n 个 page 上（per_page 喂 sign test / bootstrap）。"""
    per = {}
    base_nc, rem_nc = divmod(notes_compared, n)
    base_ok, rem_ok = divmod(notes_correct, n)
    base_fc, rem_fc = divmod(field_checked, n)
    base_ff, rem_ff = divmod(field_failed, n)
    for i in range(n):
        nc = base_nc + (1 if i < rem_nc else 0)
        ok = base_ok + (1 if i < rem_ok else 0)
        fc = base_fc + (1 if i < rem_fc else 0)
        ff = base_ff + (1 if i < rem_ff else 0)
        per["p%d" % (i + 1)] = PageCounts(
            notes_compared=nc, notes_correct=ok,
            field_checked=fc, field_failed=ff)
    return per


def make_cell(cell_id, arm_id, postcorrect, *,
              note_pass_rate=10.0, field_pass_rate=80.0,
              notes_compared=600, notes_correct=60, field_checked=360,
              field_failed=72, fatal_files=(), n_pages=6,
              preprocess=None, category_distribution=None,
              per_page=None):
    """造一个 :class:`CellResult`（字段口径与 harness summary 一致，SK-1）。"""
    cat_dist = category_distribution or {
        "event_count": notes_compared,
        "pitch_octave": notes_compared - notes_correct,
        "rhythm": field_failed,
    }
    return CellResult(
        cell_id=cell_id,
        arm_id=arm_id,
        postcorrect=postcorrect,
        note_pass_rate=note_pass_rate,
        field_pass_rate=field_pass_rate,
        notes_compared=notes_compared,
        notes_correct=notes_correct,
        field_checked=field_checked,
        field_failed=field_failed,
        category_pass={"pitch_octave": note_pass_rate,
                       "rhythm": round(note_pass_rate + 1.0, 2)},
        category_distribution=cat_dist,
        per_page=per_page or _pages(n_pages, notes_compared, notes_correct,
                                    field_checked, field_failed),
        fatal_files=tuple(fatal_files),
        preprocess=preprocess or PreprocessMetricsSummary(),
    )


def clean_report(name, applied=0, kinds=("key",)):
    """合成一份 P1-1 审计报告（不变量守护的输入）。"""
    applied = int(applied)
    return {
        "measuresReconciled": 2,
        "notesTouched": applied,
        "appliedCount": applied,
        "flaggedCount": 0,
        "applied": [{"kind": k} for k in kinds] if applied else [],
        "flagged": [],
    }


def zero_reports_for(names):
    """对一份 GT 文件名清单造「全过」审计报告（applied=0）。"""
    return {name: clean_report(name, applied=0) for name in names}


# ----------------------------------------------------------------------
# Stage-3：不变量守护（R6）
# ----------------------------------------------------------------------

class TestEvaluateInvariant(unittest.TestCase):
    """``evaluate_invariant`` 的纯函数判定逻辑。"""

    def test_all_zero_passes_and_counts(self):
        names = ["g%d.gt.musicxml" % i for i in range(EXPECTED_CLEAN_GT)]
        reports = zero_reports_for(names)
        res = evaluate_invariant(reports)
        self.assertTrue(res.passed)
        self.assertEqual(res.gt_files_checked, EXPECTED_CLEAN_GT)
        self.assertEqual(res.violations, ())
        self.assertEqual(len(res.applied_per_file), EXPECTED_CLEAN_GT)

    def test_single_nonzero_applied_fails(self):
        names = ["g0.gt.musicxml", "g1.gt.musicxml"]
        reports = zero_reports_for(names)
        reports["g1.gt.musicxml"] = clean_report("g1.gt.musicxml", applied=3)
        res = evaluate_invariant(reports)
        self.assertFalse(res.passed)
        self.assertEqual(res.applied_per_file["g1.gt.musicxml"], 3)
        self.assertEqual(res.applied_per_file["g0.gt.musicxml"], 0)
        self.assertTrue(any("g1.gt.musicxml" in v for v in res.violations))

    def test_nonzero_kind_is_listed_in_violation(self):
        reports = {"v.gt.musicxml": clean_report("v.gt.musicxml", applied=2,
                                                  kinds=("key", "rhythm"))}
        res = evaluate_invariant(reports)
        self.assertFalse(res.passed)
        self.assertTrue(any("key" in v and "rhythm" in v
                            for v in res.violations))

    def test_missing_report_is_violation(self):
        """跑不出报告 = 无法自证清白，同样按违规处理（R6 的护栏）。"""
        reports = {"miss.gt.musicxml": None}
        res = evaluate_invariant(reports)
        self.assertFalse(res.passed)
        self.assertEqual(res.applied_per_file["miss.gt.musicxml"], -1)
        self.assertTrue(any("缺失" in v for v in res.violations))

    def test_missing_report_does_not_confuse_with_zero(self):
        reports = {"miss.gt.musicxml": None, "ok.gt.musicxml": clean_report("ok")}
        res = evaluate_invariant(reports)
        self.assertFalse(res.passed)
        self.assertEqual(res.applied_per_file["miss.gt.musicxml"], -1)
        self.assertEqual(res.applied_per_file["ok.gt.musicxml"], 0)

    def test_empty_dict_is_not_vacuously_true(self):
        """QA-1 修复后：0 份覆盖不得「真空为真」——必须判 FAIL。

        旧实现把空集合当成 passed=True，正是 C1′ 红线可被静默绕过的根因。
        """
        res = evaluate_invariant({})
        self.assertFalse(res.passed)
        self.assertEqual(res.gt_files_checked, 0)
        self.assertTrue(any("覆盖不足 0/13" in v for v in res.violations))
        self.assertEqual(res.gt_files_checked, 0)

    def test_real_corpus_13_clean_gt_all_pass(self):
        """🔴 端到端计数：守护确实覆盖 6 concerto + 7 P1-1 = 13 份干净 GT。

        不跑 Pudu——用合成「全过」审计报告喂 ``evaluate_invariant``，
        只验证**覆盖集合与通过判定**两条硬约束。
        """
        tmp = tempfile.mkdtemp(prefix="p1_2_inv_")
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        cfg = D.build_config(corpus_dir=D.DEFAULT_CORPUS, work_root=tmp,
                             run_id="t04_inv", with_env=False)
        driver = D.AbtestDriver(cfg, verbose=False)
        files = driver.invariant_gt_files()
        # 6 页 concerto GT + 7 份 P1-1 语料 = 13（设计 §2.4 / §10）。
        self.assertEqual(len(files), EXPECTED_CLEAN_GT,
                         "Stage-3 必须恰好覆盖 13 份干净 GT")
        names = [os.path.basename(p) for p in files]
        self.assertEqual(names[:CONCERTO_GT_COUNT],
                         sorted(names[:CONCERTO_GT_COUNT]))
        res = evaluate_invariant(zero_reports_for(names))
        self.assertTrue(res.passed, "13 份干净 GT 上 applied 必须全为 0")
        self.assertEqual(res.gt_files_checked, EXPECTED_CLEAN_GT)

    def test_real_corpus_13_clean_gt_one_failure_fails_round(self):
        """真实 13 份清单里只要有一份被后处理改了，整轮 FAIL。"""
        tmp = tempfile.mkdtemp(prefix="p1_2_inv2_")
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        cfg = D.build_config(corpus_dir=D.DEFAULT_CORPUS, work_root=tmp,
                             run_id="t04_inv2", with_env=False)
        driver = D.AbtestDriver(cfg, verbose=False)
        names = [os.path.basename(p) for p in driver.invariant_gt_files()]
        reports = zero_reports_for(names)
        bad = names[0]
        reports[bad] = clean_report(bad, applied=1)
        res = evaluate_invariant(reports)
        self.assertFalse(res.passed)
        self.assertEqual(res.applied_per_file[bad], 1)
        self.assertEqual(res.violations, (
            "%s: applied=1（kinds=key） —— 干净 GT 上产生了修正，"
            "P1-1 红线被打破" % bad,))


# ----------------------------------------------------------------------
# R7：pipe_noop 透明性
# ----------------------------------------------------------------------

class TestTransparencyR7(unittest.TestCase):
    """``check_transparency``：pipe_noop 与 pre_off 必须逐字节等价。"""

    def _baseline(self, **kw):
        return make_cell(cell_id_of(BASELINE_ARM_ID, PC_OFF),
                         BASELINE_ARM_ID, False, **kw)

    def _noop(self, **kw):
        return make_cell(cell_id_of(SANITY_ARM_ID, PC_OFF),
                         SANITY_ARM_ID, False, **kw)

    def test_identical_returns_no_findings(self):
        base = self._baseline()
        noop = self._noop()
        self.assertEqual(check_transparency(noop, base), [])

    def test_note_rate_mismatch_is_finding(self):
        base = self._baseline(note_pass_rate=10.0)
        noop = self._noop(note_pass_rate=11.3)
        findings = check_transparency(noop, base)
        self.assertTrue(findings)
        self.assertTrue(any("note_pass_rate" in f and "R7" in f
                            for f in findings))

    def test_field_rate_mismatch_is_finding(self):
        base = self._baseline(field_pass_rate=80.0)
        noop = self._noop(field_pass_rate=79.0)
        findings = check_transparency(noop, base)
        self.assertTrue(any("field_pass_rate" in f for f in findings))
        self.assertTrue(any("R7" in f for f in findings))

    def test_notes_compared_mismatch_is_finding(self):
        base = self._baseline(notes_compared=600, notes_correct=60)
        noop = self._noop(notes_compared=599, notes_correct=60)
        findings = check_transparency(noop, base)
        self.assertTrue(any("notes_compared" in f for f in findings))

    def test_field_checked_mismatch_is_finding(self):
        base = self._baseline(field_checked=360)
        noop = self._noop(field_checked=358)
        findings = check_transparency(noop, base)
        self.assertTrue(any("field_checked" in f for f in findings))

    def test_category_distribution_mismatch_is_finding(self):
        base = self._baseline(category_distribution={
            "event_count": 600, "pitch_octave": 540, "rhythm": 72})
        noop = self._noop(category_distribution={
            "event_count": 600, "pitch_octave": 539, "rhythm": 72})
        findings = check_transparency(noop, base)
        self.assertTrue(any("category_distribution" in f for f in findings))

    def test_none_cell_returns_empty(self):
        self.assertEqual(check_transparency(None, self._baseline()), [])
        self.assertEqual(check_transparency(self._noop(), None), [])

    def test_transparency_finding_reaches_decision_blocking(self):
        """R7 差异必须流入 ``make_decision.blocking_findings``。"""
        base = self._baseline()
        noop = self._noop(note_pass_rate=12.4)  # 制造透明性破裂
        preset = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                          note_pass_rate=15.0, field_pass_rate=82.0,
                          notes_compared=600, notes_correct=90,
                          field_checked=360, field_failed=64)
        cells = {c.cell_id: c for c in (base, noop, preset)}
        delta = compute_delta(preset, base, FAST_TH)
        findings = check_transparency(noop, base)
        self.assertTrue(findings)
        decision = make_decision(
            cells, [delta],
            InvariantResult(passed=True, gt_files_checked=EXPECTED_CLEAN_GT),
            th=FAST_TH, extra_blocking=findings)
        self.assertTrue(any("R7" in f for f in decision.blocking_findings))


# ----------------------------------------------------------------------
# SK-10：fatal 页排除
# ----------------------------------------------------------------------

class TestFatalExclusionSK10(unittest.TestCase):
    """``fatal_files`` 非空的 cell 不可比，Δ 不进决策。"""

    def _baseline(self, **kw):
        return make_cell(cell_id_of(BASELINE_ARM_ID, PC_OFF),
                         BASELINE_ARM_ID, False, **kw)

    def test_cell_comparable_false_when_fatal(self):
        clean = self._baseline()
        fatal = self._baseline(fatal_files=("p2",))
        self.assertTrue(clean.comparable)
        self.assertFalse(fatal.comparable)

    def test_compute_delta_incomparable_when_cell_fatal(self):
        base = self._baseline()
        cell = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                        note_pass_rate=15.0, notes_compared=600,
                        notes_correct=90, fatal_files=("p2",))
        delta = compute_delta(cell, base, FAST_TH)
        self.assertFalse(delta.comparable,
                         "cell 有 fatal 页 ⇒ Δ 不可比、不参与决策")
        self.assertTrue(any("SK-10" in n for n in delta.notes))

    def test_compute_delta_incomparable_when_baseline_fatal(self):
        base = self._baseline(fatal_files=("p3",))
        cell = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                        note_pass_rate=15.0, notes_compared=600,
                        notes_correct=90)
        delta = compute_delta(cell, base, FAST_TH)
        self.assertFalse(delta.comparable)
        self.assertTrue(any("SK-10" in n for n in delta.notes))

    def test_make_decision_blocks_fatal_cell(self):
        base = self._baseline()
        fatal = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                         note_pass_rate=15.0, notes_compared=600,
                         notes_correct=90, fatal_files=("p2",))
        cells = {c.cell_id: c for c in (base, fatal)}
        delta = compute_delta(fatal, base, FAST_TH)
        decision = make_decision(
            cells, [delta],
            InvariantResult(passed=True, gt_files_checked=EXPECTED_CLEAN_GT),
            th=FAST_TH)
        self.assertTrue(any("SK-10" in f for f in decision.blocking_findings),
                        "fatal cell 必须出现在阻断性发现里")

    def test_decide_preprocess_excludes_fatal_candidate(self):
        """C0 判据：fatal cell 直接被否决，不得推荐默认开。"""
        base = self._baseline()
        good = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                        note_pass_rate=15.0, field_pass_rate=85.0,
                        notes_compared=600, notes_correct=90,
                        field_checked=360, field_failed=54)
        fatal = make_cell(cell_id_of("pre_default", PC_OFF), "pre_default",
                         False, note_pass_rate=20.0, field_pass_rate=90.0,
                         notes_compared=600, notes_correct=120,
                         field_checked=360, field_failed=36,
                         fatal_files=("p2",))
        cells = {c.cell_id: c for c in (base, good, fatal)}
        deltas = [compute_delta(good, base, FAST_TH),
                  compute_delta(fatal, base, FAST_TH)]
        verdict, _trace = L.decide_preprocess(deltas, cells, FAST_TH)
        self.assertEqual(verdict, "on:scan",
                         "fatal 候选被 C0 否决，唯一干净候选 pre_scan 通过")

    def test_fatal_cell_not_recommended_even_if_numbers_look_great(self):
        base = self._baseline()
        fatal = make_cell(cell_id_of("pre_scan", PC_OFF), "pre_scan", False,
                         note_pass_rate=40.0, field_pass_rate=99.0,
                         notes_compared=600, notes_correct=240,
                         field_checked=360, field_failed=4,
                         fatal_files=("p5",))
        cells = {base.cell_id: base, fatal.cell_id: fatal}
        delta = compute_delta(fatal, base, FAST_TH)
        verdict, _trace = L.decide_preprocess([delta], cells, FAST_TH)
        self.assertEqual(verdict, "off",
                         "数值再漂亮，fatal cell 也不许进入默认开关候选")


# ----------------------------------------------------------------------
# 纯净性（与 T03 一致，保证本文件可被沙箱收集）
# ----------------------------------------------------------------------

class TestPurity(unittest.TestCase):
    """本文件不得 import cv2/numpy/scipy，且不得直接起子进程。"""

    def test_no_heavy_modules_loaded(self):
        """增量口径：导入被测的 lib / driver 不得**新增**引入重型库。

        原先断言「当前 sys.modules 里没有 numpy」，在全量 session 下会被前置
        用例的合法 cv2/numpy 使用污染而误报——那是测试隔离缺陷，不是产品缺陷。
        """
        assert_import_is_pure(self, ("omr_abtest_lib", "omr_abtest_p1_2"),
                              HEAVY)

    def test_no_heavy_imports_in_source(self):
        """纯函数层（lib）+ 编排层（driver）都不得 import 重依赖。

        与 T03 的护栏一致：检查**被测源码**而非本测试文件，避免被 docstring
        里的「不 import cv2」字样误伤。
        """
        for target in ("omr_abtest_lib.py", "omr_abtest_p1_2.py"):
            with open(os.path.join(TOOLS, target), "r",
                      encoding="utf-8") as f:
                src = f.read()
            for mod in HEAVY:
                self.assertNotIn("import %s" % mod, src,
                                 "%s 不得 import %s" % (target, mod))


if __name__ == "__main__":
    unittest.main(verbosity=2)
