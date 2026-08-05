# -*- coding: utf-8 -*-
"""谱渡 Pudu · P1-2 · A/B 实验纯函数层（``omr_abtest_lib``）。

定位
----
本模块是 P1-2「预处理 A/B 调参 + 后处理前后对比」的**纯函数层**：

* **零 I/O**：不读文件、不写文件、不建目录（``os.path.join`` 等纯路径拼接除外）。
* **零子进程**：不调 oemer、不调 Pudu。
* **零第三方依赖**：统计只用 stdlib ``math.comb`` / ``random``——**刻意不用 scipy**
  （venv 里虽装了 1.18.0），以保证结论跨环境、跨版本**逐位可复现**（SK-9）。

因此本模块可以脱离 GPU / oemer / Pudu 完整单测，见
``tests/test_omr_abtest_lib.py``。有 I/O 的编排逻辑全部在
``tools/omr_abtest_p1_2.py``。

跨文件红线（设计 §10）
----------------------
* **SK-1**：通过率一律**直取 harness ``summary``**，本模块**禁止重算**
  ``note_pass_rate`` / ``field_pass_rate`` / ``category_pass``。
  唯一例外是「剔除降级页」的第二口径 Δ（:func:`compute_delta` 的
  ``*_excl_degraded`` 字段）——它对 harness **per_file 原始计数**做子集聚合，
  用的是与 harness ``compute_rates`` 完全相同的公式，且在报告里显式标注为
  「第二口径」，不参与主指标。
* **SK-9**：全模块唯一的随机源是 :func:`bootstrap_ci_by_page`，seed 固定在
  :class:`DecisionThresholds.bootstrap_seed`，并落进 ``manifest.json``。
* **SK-11**：``directional`` 结论**禁止**表述为"已验证/已证明"，
  :func:`render_markdown` 强制输出 ``confidence`` 行。

统计口径（设计 §6.2，诚实面对 n=6 页）
--------------------------------------
6 页语料的**有效样本量是 6，不是 944 个音符**（同页音符高度相关）。故：

1. **按页配对符号检验**（:func:`sign_test_p`，精确二项）：6 页下最小可达
   p = 2/2^6 = 0.03125，即**只有 6:0 全胜才够格叫"统计显著"**。
2. **按页 bootstrap 95% CI**（:func:`bootstrap_ci_by_page`，10000 次、固定
   seed）：按**页**而非按音符重抽样，否则 CI 会被严重低估。
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field, replace
from typing import (
    Any, Dict, List, Mapping, Optional, Sequence, Tuple,
)

# 复用 harness 的类别词汇表，避免口径二次定义（SK-1 的延伸）
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
import sys  # noqa: E402

if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from omr_eval_lib import POSTCORRECT_RELEVANT  # noqa: E402
from omr_eval_groundtruth import OemerOpts, ProjectOpts  # noqa: E402

__all__ = [
    "SCHEMA",
    "BASELINE_ARM_ID", "SANITY_ARM_ID", "PROBE_ARM_ID",
    "PC_OFF", "PC_ON", "SIGNIFICANCE_ALPHA",
    "VERDICT_SIGNIFICANT", "VERDICT_DIRECTIONAL",
    "VERDICT_NEUTRAL", "VERDICT_REGRESSION",
    "POSTCORRECT_DEFAULT_ON", "POSTCORRECT_DEFAULT_OFF", "POSTCORRECT_FAIL",
    "ArmSpec", "ScoreSpec", "DecisionThresholds", "EnvFingerprint",
    "ExperimentConfig", "CellPlan", "PageCounts",
    "PreprocessMetricsSummary", "PostCorrectSummary",
    "CellResult", "DeltaResult", "InvariantResult", "Decision",
    "AbtestSummary",
    "cell_id_of", "preset_of_arm",
    "summarize_preprocess", "summarize_postcorrect", "aggregate_cell",
    "sign_test_p", "bootstrap_ci_by_page", "classify_verdict", "compute_delta",
    "evaluate_invariant", "check_transparency", "diagnose_deskew",
    "decide_preprocess", "decide_postcorrect", "make_decision",
    "render_markdown",
    "default_arms", "default_scores",
]

#: 产物 schema 标识（写进 ``abtest_summary.json``）。
SCHEMA: str = "pudu.abtest.p1_2/1"

#: 基线 arm：直调 ``omr_oemer.py``，与历史 07-20 口径逐字节同链路。
BASELINE_ARM_ID: str = "pre_off"
#: 透明性 sanity arm：``omr_pipeline.py --no-preprocess``，应与基线完全一致（R7）。
SANITY_ARM_ID: str = "pipe_noop"
#: K2 单变量隔离探针 arm（U7）：photo preset 但 ``enable_deskew=false``。
PROBE_ARM_ID: str = "pre_photo_nodeskew"

#: 打分维度后缀。
PC_OFF: str = "pc_off"
PC_ON: str = "pc_on"

#: 显著性水平。6 页语料下 6:0 -> p=0.03125 ≤ 0.05；5:1 -> p=0.21875 > 0.05。
SIGNIFICANCE_ALPHA: float = 0.05

VERDICT_SIGNIFICANT: str = "significant"
VERDICT_DIRECTIONAL: str = "directional"
VERDICT_NEUTRAL: str = "neutral"
VERDICT_REGRESSION: str = "regression"

#: 后处理默认口径取值（U6：**只**建议 ``--from-omr`` 入口默认开）。
POSTCORRECT_DEFAULT_ON: str = "on_for_omr_path"
POSTCORRECT_DEFAULT_OFF: str = "off"
POSTCORRECT_FAIL: str = "fail"

#: Stage-3 不变量守护的**规范覆盖份数**：6 页 concerto GT + 7 份 P1-1 语料 = 13。
#: 这是固定的红线清单（与打分语料子集无关），低于此数即视为红线被削弱
#:（QA-1：真空为真缺陷修复——覆盖为 0 / 缩水时不得推荐默认开后处理）。
INVARIANT_EXPECTED_GT: int = 13

_EPS: float = 1e-9


def _r(value: float, digits: int = 4) -> float:
    """四舍五入到指定位数，顺带把 ``-0.0`` 归一成 ``0.0``。"""
    out = round(float(value), digits)
    return 0.0 if out == 0.0 else out


def cell_id_of(arm_id: str, score_suffix: str) -> str:
    """cell 主键：``<arm_id>__<pc_off|pc_on>``。"""
    return f"{arm_id}__{score_suffix}"


def preset_of_arm(arm_id: str) -> str:
    """从 arm_id 反推 preset 名（``pre_scan`` -> ``scan``）。"""
    return arm_id[len("pre_"):] if arm_id.startswith("pre_") else arm_id


# ======================================================================
# 1. 配置类数据结构（全部 frozen）
# ======================================================================


@dataclass(frozen=True)
class ArmSpec:
    """一个实验臂（= 一种 oemer 输入侧配置）。

    Attributes:
        arm_id: 唯一标识（如 ``pre_scan``）。
        preprocess: ``None`` = 直调 ``omr_oemer.py``；``"off"`` = 经
            ``omr_pipeline.py --no-preprocess``；其余 = preset 名。
        preprocess_config: ``--preprocess-config`` 覆盖文件（探针 arm 用）。
        f3_geometric: 恒 False（F3 已证零效果，plan §8）。
        label: 人读标签，进报告表格。
    """

    arm_id: str
    preprocess: Optional[str] = None
    preprocess_config: Optional[str] = None
    f3_geometric: bool = False
    label: str = ""

    def to_oemer_opts(self, preprocess_metrics: Optional[str] = None
                      ) -> OemerOpts:
        """折叠成 harness 的 :class:`OemerOpts`。

        Args:
            preprocess_metrics: metrics sidecar 路径模板（支持 ``{base}``）。
                ``preprocess is None``（直调）时**必须**为 None，否则
                harness 会按 SK-8 抛 ``ValueError``——这里提前置空，
                让"基线 arm 不产 metrics"成为显式语义而非意外。

        Returns:
            OemerOpts: 可直接交给 ``eval_corpus`` 的参数载体。
        """
        metrics = preprocess_metrics if self.preprocess is not None else None
        return OemerOpts(
            preprocess=self.preprocess,
            preprocess_config=(self.preprocess_config
                               if self.preprocess is not None else None),
            preprocess_metrics=metrics,
            f3_geometric=self.f3_geometric,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "preprocess": self.preprocess,
            "preprocess_config": self.preprocess_config,
            "f3_geometric": self.f3_geometric,
            "label": self.label,
        }


@dataclass(frozen=True)
class ScoreSpec:
    """一个打分维度（= 一种 Pudu 投影侧配置）。"""

    postcorrect: bool
    emit_report: bool = True

    @property
    def suffix(self) -> str:
        """``"pc_on"`` / ``"pc_off"``。"""
        return PC_ON if self.postcorrect else PC_OFF

    def to_project_opts(self, report_dir: Optional[str] = None) -> ProjectOpts:
        """折叠成 harness 的 :class:`ProjectOpts`。

        🔴 SK-4：``postcorrect_gt`` 恒 ``False``，本方法**不提供**任何打开它的入参。

        Args:
            report_dir: 后处理审计报告目录；非空且 ``emit_report`` 时，
                报告落 ``<report_dir>/{base}.report.json``（``{base}`` 由
                harness 逐页展开）。
        """
        report = None
        if self.postcorrect and self.emit_report and report_dir:
            report = os.path.join(report_dir, "{base}.report.json")
        return ProjectOpts(
            postcorrect_pred=self.postcorrect,
            postcorrect_gt=False,
            postcorrect_report=report,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"postcorrect": self.postcorrect,
                "emit_report": self.emit_report,
                "suffix": self.suffix}


@dataclass(frozen=True)
class DecisionThresholds:
    """决策阈值（U1 已拍板取默认值）。

    全部落进 ``manifest.json``；改阈值只需重跑 Stage-5（秒级），**不需重跑 oemer**。
    """

    min_note_pass_gain_pp: float = 1.0
    min_field_pass_gain_pp: float = 1.0
    max_category_regress_pp: float = 1.0
    min_improved_pages: int = 5
    max_worsened_pages: int = 1
    require_zero_degraded: bool = True
    postcorrect_min_field_gain_pp: float = 0.5
    bootstrap_iters: int = 10000
    bootstrap_seed: int = 20260801

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_note_pass_gain_pp": self.min_note_pass_gain_pp,
            "min_field_pass_gain_pp": self.min_field_pass_gain_pp,
            "max_category_regress_pp": self.max_category_regress_pp,
            "min_improved_pages": self.min_improved_pages,
            "max_worsened_pages": self.max_worsened_pages,
            "require_zero_degraded": self.require_zero_degraded,
            "postcorrect_min_field_gain_pp": self.postcorrect_min_field_gain_pp,
            "bootstrap_iters": self.bootstrap_iters,
            "bootstrap_seed": self.bootstrap_seed,
        }


@dataclass(frozen=True)
class EnvFingerprint:
    """环境指纹（R4：跨机器/跨时间复核结论的唯一依据）。"""

    pudu_exe_sha256: str = ""
    oemer_version: str = ""
    preprocess_config_sha256: str = ""
    eval_lib_sha256: str = ""
    git_head: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pudu_exe_sha256": self.pudu_exe_sha256,
            "oemer_version": self.oemer_version,
            "preprocess_config_sha256": self.preprocess_config_sha256,
            "eval_lib_sha256": self.eval_lib_sha256,
            "git_head": self.git_head,
        }


@dataclass(frozen=True)
class CellPlan:
    """一个 cell 的执行计划（纯数据，目录尚未创建）。"""

    cell_id: str
    arm: ArmSpec
    score: ScoreSpec
    workspace_dir: str
    cache_dir: str
    needs_oemer: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "arm_id": self.arm.arm_id,
            "postcorrect": self.score.postcorrect,
            "workspace_dir": self.workspace_dir,
            "cache_dir": self.cache_dir,
            "needs_oemer": self.needs_oemer,
        }


def default_arms(deskew_probe: bool = True,
                 probe_config: Optional[str] = None) -> Tuple[ArmSpec, ...]:
    """设计 §2.2 的 6（+1 探针）个 arm。

    Args:
        deskew_probe: 是否附加 ``pre_photo_nodeskew`` 探针（U7 已拍板默认启用）。
        probe_config: 探针用的 preset 覆盖文件路径
            （``tools/omr_abtest_photo_nodeskew.json``）。
    """
    arms = [
        ArmSpec(BASELINE_ARM_ID, None, None, False,
                "基线：直调 omr_oemer.py（历史 07-20 同链路）"),
        ArmSpec(SANITY_ARM_ID, "off", None, False,
                "透明性 sanity：omr_pipeline.py --no-preprocess"),
        ArmSpec("pre_default", "default", None, False,
                "通用增强：CLAHE2.0 + 阴影抑制 + adaptive(25,10)"),
        ArmSpec("pre_scan", "scan", None, False,
                "扫描件档：阴影抑制 off + otsu"),
        ArmSpec("pre_photo", "photo", None, False,
                "拍照档：阴影核 41 + adaptive(31,12) + deskew on（唯一开去扭曲）"),
        ArmSpec("pre_low_contrast", "low_contrast", None, False,
                "低对比档：CLAHE 3.0 + adaptive(21,6)"),
    ]
    if deskew_probe:
        arms.append(ArmSpec(PROBE_ARM_ID, "photo", probe_config, False,
                            "K2 探针：photo 但 enable_deskew=false"))
    return tuple(arms)


def default_scores() -> Tuple[ScoreSpec, ...]:
    """两个打分维度：``pc_off`` 先跑（含 oemer），``pc_on`` 复用 pred。"""
    return (ScoreSpec(postcorrect=False, emit_report=False),
            ScoreSpec(postcorrect=True, emit_report=True))


@dataclass(frozen=True)
class ExperimentConfig:
    """一次 A/B 运行的完整配置快照（写进 ``manifest.json``）。"""

    run_id: str
    corpus_dir: str
    work_root: str
    arms: Tuple[ArmSpec, ...] = field(default_factory=default_arms)
    scores: Tuple[ScoreSpec, ...] = field(default_factory=default_scores)
    baseline_cell: str = cell_id_of(BASELINE_ARM_ID, PC_OFF)
    reuse_oemer_cache: bool = True
    deskew_probe: bool = True
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)
    env: EnvFingerprint = field(default_factory=EnvFingerprint)

    def plan_cells(self) -> List[CellPlan]:
        """展开成 ``len(arms) × len(scores)`` 个 :class:`CellPlan`。

        ``needs_oemer`` 仅对 ``pc_off`` cell 为 True——``pc_on`` cell 复用同
        arm 的 pred（设计洞察 1：后处理只作用于 Pudu 投影层，与 oemer 无关），
        故 oemer 只跑 ``len(arms)`` 轮而非 ``len(arms) × 2`` 轮。

        Returns:
            List[CellPlan]: 顺序为「先按 arm，再按 score」，且 ``pc_off``
            **恒排在同 arm 的 ``pc_on`` 之前**（后者依赖前者的 pred 缓存）。
        """
        ordered_scores = sorted(self.scores, key=lambda s: s.postcorrect)
        plans: List[CellPlan] = []
        for arm in self.arms:
            for score in ordered_scores:
                cid = cell_id_of(arm.arm_id, score.suffix)
                plans.append(CellPlan(
                    cell_id=cid,
                    arm=arm,
                    score=score,
                    workspace_dir=os.path.join(self.work_root, "cells", cid),
                    cache_dir=os.path.join(self.work_root, "cache", arm.arm_id),
                    needs_oemer=not score.postcorrect,
                ))
        return plans

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "corpus_dir": self.corpus_dir,
            "work_root": self.work_root,
            "arms": [a.to_dict() for a in self.arms],
            "scores": [s.to_dict() for s in self.scores],
            "baseline_cell": self.baseline_cell,
            "reuse_oemer_cache": self.reuse_oemer_cache,
            "deskew_probe": self.deskew_probe,
            "thresholds": self.thresholds.to_dict(),
            "env": self.env.to_dict(),
        }


# ======================================================================
# 2. 结果类数据结构
# ======================================================================


@dataclass(frozen=True)
class PageCounts:
    """单页的 harness 原始计数（**不是**重算出来的比率）。"""

    notes_compared: int = 0
    notes_correct: int = 0
    field_checked: int = 0
    field_failed: int = 0
    fatal: bool = False

    @property
    def note_pass_rate(self) -> float:
        """该页音符联立通过率（%）。公式与 harness ``compute_rates`` 一致。"""
        if self.notes_compared <= 0:
            return 0.0
        return self.notes_correct / self.notes_compared * 100.0

    @property
    def field_pass_rate(self) -> float:
        """该页字段通过率（%）。"""
        if self.field_checked <= 0:
            return 0.0
        return (self.field_checked - self.field_failed) / self.field_checked * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notes_compared": self.notes_compared,
            "notes_correct": self.notes_correct,
            "field_checked": self.field_checked,
            "field_failed": self.field_failed,
            "fatal": self.fatal,
        }


@dataclass(frozen=True)
class PreprocessMetricsSummary:
    """一个 cell 的预处理 metrics 汇总（C8 sidecar -> 决策输入，SK-5）。"""

    pages_total: int = 0
    degraded_pages: Tuple[str, ...] = ()
    degrade_reasons: Mapping[str, str] = field(default_factory=dict)
    deskew_decisions: Mapping[str, str] = field(default_factory=dict)
    deskew_applied_deg: Mapping[str, float] = field(default_factory=dict)
    ink_ratio_out: Mapping[str, float] = field(default_factory=dict)
    total_ms_mean: float = 0.0

    def any_degraded(self) -> bool:
        """是否存在降级页（C1 判据的硬门槛）。"""
        return len(self.degraded_pages) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages_total": self.pages_total,
            "degraded_pages": list(self.degraded_pages),
            "degrade_reasons": dict(self.degrade_reasons),
            "deskew_decisions": dict(self.deskew_decisions),
            "deskew_applied_deg": dict(self.deskew_applied_deg),
            "ink_ratio_out": dict(self.ink_ratio_out),
            "total_ms_mean": self.total_ms_mean,
        }


@dataclass(frozen=True)
class PostCorrectSummary:
    """一个 cell 的后处理审计汇总（P1-1 report -> 决策输入）。"""

    applied_total: int = 0
    flagged_total: int = 0
    measures_reconciled: int = 0
    notes_touched: int = 0
    by_kind: Mapping[str, int] = field(default_factory=dict)
    flagged_by_kind: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied_total": self.applied_total,
            "flagged_total": self.flagged_total,
            "measures_reconciled": self.measures_reconciled,
            "notes_touched": self.notes_touched,
            "by_kind": dict(self.by_kind),
            "flagged_by_kind": dict(self.flagged_by_kind),
        }


@dataclass(frozen=True)
class CellResult:
    """一个 cell 的聚合结果。

    🔴 SK-1：``note_pass_rate`` / ``field_pass_rate`` / ``category_pass`` /
    ``category_distribution`` **一律直取 harness summary**，本类不做任何重算。
    """

    cell_id: str
    arm_id: str
    postcorrect: bool
    note_pass_rate: float = 0.0
    field_pass_rate: float = 0.0
    notes_compared: int = 0
    notes_correct: int = 0
    field_checked: int = 0
    field_failed: int = 0
    category_pass: Mapping[str, float] = field(default_factory=dict)
    category_distribution: Mapping[str, int] = field(default_factory=dict)
    per_page: Mapping[str, PageCounts] = field(default_factory=dict)
    per_page_note_pass: Mapping[str, float] = field(default_factory=dict)
    fatal_files: Tuple[str, ...] = ()
    preprocess: PreprocessMetricsSummary = field(
        default_factory=PreprocessMetricsSummary)
    postcorrect_stats: PostCorrectSummary = field(
        default_factory=PostCorrectSummary)
    raw_report_path: str = ""

    @property
    def pages_count(self) -> int:
        return len(self.per_page)

    @property
    def comparable(self) -> bool:
        """SK-10：``fatal_files`` 非空的 cell 不可比，不参与决策。"""
        return len(self.fatal_files) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "arm_id": self.arm_id,
            "postcorrect": self.postcorrect,
            "note_pass_rate": self.note_pass_rate,
            "field_pass_rate": self.field_pass_rate,
            "notes_compared": self.notes_compared,
            "notes_correct": self.notes_correct,
            "field_checked": self.field_checked,
            "field_failed": self.field_failed,
            "category_pass": dict(self.category_pass),
            "category_distribution": dict(self.category_distribution),
            "per_page": {k: v.to_dict() for k, v in self.per_page.items()},
            "per_page_note_pass": dict(self.per_page_note_pass),
            "fatal_files": list(self.fatal_files),
            "preprocess": self.preprocess.to_dict(),
            "postcorrect_stats": self.postcorrect_stats.to_dict(),
            "raw_report_path": self.raw_report_path,
            "comparable": self.comparable,
        }


@dataclass(frozen=True)
class DeltaResult:
    """一个 cell 相对某个 baseline cell 的差值 + 统计判定。"""

    cell_id: str
    baseline_cell_id: str
    d_note_pass_pp: float = 0.0
    d_field_pass_pp: float = 0.0
    d_category_pass_pp: Mapping[str, float] = field(default_factory=dict)
    d_category_count: Mapping[str, int] = field(default_factory=dict)
    d_event_count: int = 0
    pages_improved: int = 0
    pages_worsened: int = 0
    pages_tied: int = 0
    sign_test_p: float = 1.0
    ci95_note_pass_pp: Tuple[float, float] = (0.0, 0.0)
    verdict: str = VERDICT_NEUTRAL
    degraded_contaminated: bool = False
    excluded_pages: Tuple[str, ...] = ()
    d_note_pass_pp_excl_degraded: Optional[float] = None
    d_field_pass_pp_excl_degraded: Optional[float] = None
    comparable: bool = True
    notes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "baseline_cell_id": self.baseline_cell_id,
            "d_note_pass_pp": self.d_note_pass_pp,
            "d_field_pass_pp": self.d_field_pass_pp,
            "d_category_pass_pp": dict(self.d_category_pass_pp),
            "d_category_count": dict(self.d_category_count),
            "d_event_count": self.d_event_count,
            "pages_improved": self.pages_improved,
            "pages_worsened": self.pages_worsened,
            "pages_tied": self.pages_tied,
            "sign_test_p": self.sign_test_p,
            "ci95_note_pass_pp": list(self.ci95_note_pass_pp),
            "verdict": self.verdict,
            "degraded_contaminated": self.degraded_contaminated,
            "excluded_pages": list(self.excluded_pages),
            "d_note_pass_pp_excl_degraded": self.d_note_pass_pp_excl_degraded,
            "d_field_pass_pp_excl_degraded": self.d_field_pass_pp_excl_degraded,
            "comparable": self.comparable,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class InvariantResult:
    """Stage-3 不变量守护结果（P1-1 立项红线，R6）。"""

    passed: bool = True
    gt_files_checked: int = 0
    applied_per_file: Mapping[str, int] = field(default_factory=dict)
    violations: Tuple[str, ...] = ()
    #: 本轮**规范要求**的干净 GT 份数（QA-1）。默认即红线全量 13；只有测试
    #: 替身语料才会随 ``invariant_gt`` 注入一起显式下调。判定层一律读它、
    #: 不再各自读模块常量，避免「按谁的尺子量」出现分歧。
    expected_gt: int = INVARIANT_EXPECTED_GT

    @property
    def coverage_ok(self) -> bool:
        """覆盖度是否达标——低于规范份数即红线缩水（QA-1 真空为真修复）。"""
        return self.gt_files_checked >= self.expected_gt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "gt_files_checked": self.gt_files_checked,
            "expected_gt": self.expected_gt,
            "coverage_ok": self.coverage_ok,
            "applied_per_file": dict(self.applied_per_file),
            "violations": list(self.violations),
        }


@dataclass(frozen=True)
class Decision:
    """最终决策（含逐条判据留痕，可复现、可复核、可推翻）。"""

    preprocess_default: str = "off"
    preprocess_criteria_trace: Tuple[str, ...] = ()
    postcorrect_default: str = POSTCORRECT_DEFAULT_OFF
    postcorrect_criteria_trace: Tuple[str, ...] = ()
    blocking_findings: Tuple[str, ...] = ()
    confidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preprocess_default": self.preprocess_default,
            "preprocess_criteria_trace": list(self.preprocess_criteria_trace),
            "postcorrect_default": self.postcorrect_default,
            "postcorrect_criteria_trace": list(self.postcorrect_criteria_trace),
            "blocking_findings": list(self.blocking_findings),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class AbtestSummary:
    """整轮实验的结果聚合（``abtest_summary.json`` / ``abtest_report.md`` 的源）。"""

    config: ExperimentConfig
    cells: Tuple[CellResult, ...] = ()
    deltas: Tuple[DeltaResult, ...] = ()
    invariant: InvariantResult = field(default_factory=InvariantResult)
    decision: Decision = field(default_factory=Decision)

    def cell_map(self) -> Dict[str, CellResult]:
        return {c.cell_id: c for c in self.cells}

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "run_id": self.config.run_id,
            "config": self.config.to_dict(),
            "cells": [c.to_dict() for c in self.cells],
            "deltas": [d.to_dict() for d in self.deltas],
            "invariant": self.invariant.to_dict(),
            "decision": self.decision.to_dict(),
        }

    def to_markdown(self) -> str:
        return render_markdown(self)


# ======================================================================
# 3. 聚合（SK-1：只取数，不重算）
# ======================================================================


def _page_of_metrics(metrics: Mapping[str, Any]) -> str:
    """从 metrics sidecar 推断页 key。

    优先取驱动注入的 ``page``；否则取 ``src`` 的 basename stem（SK-3 保证
    同一页在所有 cell 用同一 stem，故 stem 是稳定的页主键）。
    """
    page = metrics.get("page")
    if page:
        return str(page)
    src = str(metrics.get("src") or metrics.get("dst") or "")
    if not src:
        return ""
    return os.path.splitext(os.path.basename(src))[0]


def summarize_preprocess(metrics_list: Sequence[Mapping[str, Any]]
                         ) -> PreprocessMetricsSummary:
    """把 N 份 metrics sidecar 折叠成 :class:`PreprocessMetricsSummary`。

    这是**降级唯一可观测通道**（C7/C8）：预处理 fail-open 时 rc 不变、
    harness 完全看不见，只有 sidecar 的 ``degraded`` 字段能揭示
    "这一页其实没做增强"。任何 ``degraded=true`` 的页都会进
    ``degraded_pages``，并被 C1 判据一票否决（SK-5）。

    Args:
        metrics_list: sidecar dict 序列（可含驱动注入的 ``page`` 键）。

    Returns:
        PreprocessMetricsSummary: 空输入返回全零汇总（``any_degraded()`` 为 False）。
    """
    degraded: List[str] = []
    reasons: Dict[str, str] = {}
    decisions: Dict[str, str] = {}
    applied: Dict[str, float] = {}
    ink: Dict[str, float] = {}
    total_ms: List[float] = []

    for metrics in metrics_list:
        if not isinstance(metrics, Mapping):
            continue
        page = _page_of_metrics(metrics)
        if bool(metrics.get("degraded")):
            degraded.append(page)
            reasons[page] = str(metrics.get("degrade_reason") or "unknown")
        decisions[page] = str(metrics.get("deskew_decision") or "disabled")
        try:
            applied[page] = float(metrics.get("deskew_applied_deg") or 0.0)
        except (TypeError, ValueError):
            applied[page] = 0.0
        raw_ink = metrics.get("ink_ratio_out")
        if raw_ink is not None:
            try:
                ink[page] = float(raw_ink)
            except (TypeError, ValueError):
                pass
        try:
            total_ms.append(float(metrics.get("total_ms") or 0.0))
        except (TypeError, ValueError):
            pass

    mean_ms = round(sum(total_ms) / len(total_ms), 3) if total_ms else 0.0
    return PreprocessMetricsSummary(
        pages_total=len(list(metrics_list)),
        degraded_pages=tuple(sorted(degraded)),
        degrade_reasons=reasons,
        deskew_decisions=decisions,
        deskew_applied_deg=applied,
        ink_ratio_out=ink,
        total_ms_mean=mean_ms,
    )


def summarize_postcorrect(reports: Sequence[Mapping[str, Any]]
                          ) -> PostCorrectSummary:
    """把 N 份 P1-1 审计报告折叠成 :class:`PostCorrectSummary`。

    报告 schema 见 ``src/jianpu_postcorrect.cpp::postCorrectReportToJson``：
    ``{measuresReconciled, notesTouched, appliedCount, flaggedCount,
    applied:[{kind,...}], flagged:[{kind,...}]}``。
    """
    applied_total = 0
    flagged_total = 0
    measures = 0
    touched = 0
    by_kind: Dict[str, int] = {}
    flagged_by_kind: Dict[str, int] = {}

    for report in reports:
        if not isinstance(report, Mapping):
            continue
        applied_items = report.get("applied") or []
        flagged_items = report.get("flagged") or []
        applied_total += int(report.get("appliedCount", len(applied_items)) or 0)
        flagged_total += int(report.get("flaggedCount", len(flagged_items)) or 0)
        measures += int(report.get("measuresReconciled", 0) or 0)
        touched += int(report.get("notesTouched", 0) or 0)
        for item in applied_items:
            kind = str((item or {}).get("kind", "unknown"))
            by_kind[kind] = by_kind.get(kind, 0) + 1
        for item in flagged_items:
            kind = str((item or {}).get("kind", "unknown"))
            flagged_by_kind[kind] = flagged_by_kind.get(kind, 0) + 1

    return PostCorrectSummary(
        applied_total=applied_total,
        flagged_total=flagged_total,
        measures_reconciled=measures,
        notes_touched=touched,
        by_kind=by_kind,
        flagged_by_kind=flagged_by_kind,
    )


def aggregate_cell(cell_id: str, arm_id: str, postcorrect: bool,
                   harness_report: Mapping[str, Any],
                   preprocess_metrics: Sequence[Mapping[str, Any]] = (),
                   postcorrect_reports: Sequence[Mapping[str, Any]] = (),
                   raw_report_path: str = "") -> CellResult:
    """把一个 cell 的 harness 报告 + sidecar + 审计报告折叠成 :class:`CellResult`。

    🔴 **SK-1**：``note_pass_rate`` / ``field_pass_rate`` / ``category_pass`` /
    ``category_distribution`` 一律**直接取 harness ``summary``**，本函数
    绝不重算——任何重算都会让 A/B 结果与历史基线（plan §8）口径漂移，
    从而无法与 07-20 的 `note_pass_rate=2.65%` 对齐。

    Args:
        cell_id: cell 主键。
        arm_id: 所属 arm。
        postcorrect: 该 cell 是否开了后处理。
        harness_report: ``eval_corpus`` 的完整返回（含 ``summary`` / ``per_file``）。
        preprocess_metrics: 该 cell 的 metrics sidecar 列表。
        postcorrect_reports: 该 cell 的后处理审计报告列表。
        raw_report_path: harness 原始报告落点（相对 run 目录），进 JSON 备查。

    Returns:
        CellResult
    """
    summary = dict(harness_report.get("summary") or {})
    per_file = harness_report.get("per_file") or []

    per_page: Dict[str, PageCounts] = {}
    per_page_note_pass: Dict[str, float] = {}
    for rep in per_file:
        if not isinstance(rep, Mapping):
            continue
        base = str(rep.get("file") or "")
        counts = PageCounts(
            notes_compared=int(rep.get("notes_compared", 0) or 0),
            notes_correct=int(rep.get("notes_correct", 0) or 0),
            field_checked=int(rep.get("field_checked", 0) or 0),
            field_failed=int(rep.get("field_failed", 0) or 0),
            fatal=bool(rep.get("fatal")),
        )
        per_page[base] = counts
        per_page_note_pass[base] = round(counts.note_pass_rate, 2)

    return CellResult(
        cell_id=cell_id,
        arm_id=arm_id,
        postcorrect=postcorrect,
        note_pass_rate=float(summary.get("note_pass_rate", 0.0) or 0.0),
        field_pass_rate=float(summary.get("field_pass_rate", 0.0) or 0.0),
        notes_compared=int(summary.get("notes_compared", 0) or 0),
        notes_correct=int(summary.get("notes_correct", 0) or 0),
        field_checked=int(summary.get("field_checked", 0) or 0),
        field_failed=int(summary.get("field_failed", 0) or 0),
        category_pass=dict(summary.get("category_pass") or {}),
        category_distribution=dict(summary.get("category_distribution") or {}),
        per_page=per_page,
        per_page_note_pass=per_page_note_pass,
        fatal_files=tuple(summary.get("fatal_files") or ()),
        preprocess=summarize_preprocess(preprocess_metrics),
        postcorrect_stats=summarize_postcorrect(postcorrect_reports),
        raw_report_path=raw_report_path,
    )


# ======================================================================
# 4. 统计（纯 stdlib，逐位可复现）
# ======================================================================


def sign_test_p(improved: int, worsened: int) -> float:
    """按页配对**双侧精确二项符号检验** p 值（H0: p=0.5）。

    标准符号检验口径：ties（打平的页）**剔除**，``n = improved + worsened``。

    公式::

        p = min(1.0, 2 * Σ_{i=0..k} C(n, i) / 2^n),  k = min(improved, worsened)

    实测对表（n=6，设计 §6.2）：

    ======  ======  ==========
    improved worsened  p
    ======  ======  ==========
    6       0       0.03125
    5       1       0.21875
    4       2       0.6875
    3       3       1.0
    ======  ======  ==========

    ⇒ **6 页语料下最小可达 p = 0.03125，只有 6:0 全胜才够格叫"统计显著"**。

    Args:
        improved: 改善的页数（>0）。
        worsened: 恶化的页数（>0）。

    Returns:
        float: p 值（0, 1]；``n <= 0`` 时返回 1.0。
    """
    improved = max(0, int(improved))
    worsened = max(0, int(worsened))
    n = improved + worsened
    if n <= 0:
        return 1.0
    k = min(improved, worsened)
    tail = sum(math.comb(n, i) for i in range(0, k + 1))
    return min(1.0, 2.0 * tail / float(2 ** n))


def bootstrap_ci_by_page(cell_pages: Mapping[str, Tuple[int, int]],
                         base_pages: Mapping[str, Tuple[int, int]],
                         iters: int = 10000,
                         seed: int = 20260801) -> Tuple[float, float]:
    """按**页**有放回重抽样，返回 Δnote_pass_rate 的 95% CI（单位 pp）。

    **为什么必须按页而不是按音符**：同一页的音符共享同一次 oemer 推理、
    同一张图的退化模式，高度相关。按音符 bootstrap 会把有效样本量从 6 虚增到
    944，CI 严重低估、把方向性证据包装成"统计显著"（R2）。

    Args:
        cell_pages: ``{page: (notes_correct, notes_compared)}``（实验组）。
        base_pages: 同上（对照组）。两者按 key 求交集后参与抽样。
        iters: 重抽样次数（默认 10000）。
        seed: 固定随机种子（SK-9：全模块唯一随机源）。

    Returns:
        Tuple[float, float]: ``(lo, hi)``，2.5% / 97.5% 分位数，单位 pp。
        无可用页或 ``iters <= 0`` 时返回 ``(0.0, 0.0)``。
    """
    pages = sorted(set(cell_pages) & set(base_pages))
    if not pages or iters <= 0:
        return (0.0, 0.0)

    cell_vec = [(int(cell_pages[p][0]), int(cell_pages[p][1])) for p in pages]
    base_vec = [(int(base_pages[p][0]), int(base_pages[p][1])) for p in pages]
    n = len(pages)
    rng = random.Random(seed)
    deltas: List[float] = []

    for _ in range(int(iters)):
        c_ok = c_all = b_ok = b_all = 0
        for _i in range(n):
            idx = rng.randrange(n)
            c_ok += cell_vec[idx][0]
            c_all += cell_vec[idx][1]
            b_ok += base_vec[idx][0]
            b_all += base_vec[idx][1]
        c_rate = (c_ok / c_all * 100.0) if c_all else 0.0
        b_rate = (b_ok / b_all * 100.0) if b_all else 0.0
        deltas.append(c_rate - b_rate)

    deltas.sort()
    last = len(deltas) - 1
    lo_idx = int(math.floor(0.025 * last))
    hi_idx = int(math.ceil(0.975 * last))
    return (_r(deltas[lo_idx]), _r(deltas[hi_idx]))


def classify_verdict(d: "DeltaResult", th: DecisionThresholds) -> str:
    """四态判定：``significant`` / ``directional`` / ``neutral`` / ``regression``。

    判定规则（保守优先，守护性实验的正确姿态）：

    * ``Δnote < 0`` -> **regression**（净退化一律标红，不因不显著而放过）。
    * ``Δnote > 0`` 且多数页反而变差（``worsened > improved``）-> **regression**
      （总分靠单页离群值撑起来，不可信）。
    * ``Δnote > 0`` 且 ``worsened == 0`` 且 ``p ≤ 0.05`` 且 CI 不跨 0
      -> **significant**。
    * 其余正向 -> **directional**（方向性证据，**禁止**表述为"已验证"，SK-11）。
    * ``Δnote == 0`` 且无页数倾向 -> **neutral**。
    """
    lo, hi = d.ci95_note_pass_pp
    ci_excludes_zero = (lo > 0.0) or (hi < 0.0)

    if d.d_note_pass_pp < -_EPS:
        return VERDICT_REGRESSION
    if abs(d.d_note_pass_pp) <= _EPS:
        return (VERDICT_REGRESSION if d.pages_worsened > d.pages_improved
                else VERDICT_NEUTRAL)
    if d.pages_worsened > d.pages_improved:
        return VERDICT_REGRESSION
    if (d.pages_worsened == 0
            and d.sign_test_p <= SIGNIFICANCE_ALPHA
            and ci_excludes_zero):
        return VERDICT_SIGNIFICANT
    return VERDICT_DIRECTIONAL


def _pairs(cell: CellResult) -> Dict[str, Tuple[int, int]]:
    """``{page: (notes_correct, notes_compared)}``（bootstrap 入参形态）。"""
    return {p: (c.notes_correct, c.notes_compared)
            for p, c in cell.per_page.items()}


def _subset_rates(cell: CellResult, exclude: Sequence[str]
                  ) -> Tuple[Optional[float], Optional[float]]:
    """对页子集重算 (note_pass, field_pass)——**仅用于第二口径**。

    这是 SK-1 的**唯一例外**（见模块 docstring）：公式与 harness
    ``compute_rates`` 逐字一致，只是分母换成"剔除降级页后的子集"。
    """
    skip = set(exclude)
    n_all = n_ok = f_all = f_bad = 0
    used = 0
    for page, counts in cell.per_page.items():
        if page in skip:
            continue
        used += 1
        n_all += counts.notes_compared
        n_ok += counts.notes_correct
        f_all += counts.field_checked
        f_bad += counts.field_failed
    if used == 0:
        return (None, None)
    note = (n_ok / n_all * 100.0) if n_all else 0.0
    fieldr = ((f_all - f_bad) / f_all * 100.0) if f_all else 0.0
    return (note, fieldr)


def compute_delta(cell: CellResult, baseline: CellResult,
                  thresholds: Optional[DecisionThresholds] = None
                  ) -> DeltaResult:
    """计算 ``cell − baseline`` 的全部差值指标 + 统计判定。

    Δ 一律定义为 ``Δ(x) = cell(x) − baseline(x)``；通过率类单位为**百分点（pp）**。

    产出两套口径（SK-5 / R3）：

    1. **全量 Δ**：直接取 harness summary 相减。
    2. **剔除降级页 Δ**（``*_excl_degraded``）：把 cell 或 baseline 中任一侧
       ``degraded=true`` 的页从分子分母里剔除后重算。仅在存在降级页时非 None。

    Args:
        cell: 实验组。
        baseline: 对照组。
        thresholds: 阈值（提供 bootstrap 次数与 seed）；None 取默认值。

    Returns:
        DeltaResult
    """
    th = thresholds or DecisionThresholds()

    d_note = _r(cell.note_pass_rate - baseline.note_pass_rate)
    d_field = _r(cell.field_pass_rate - baseline.field_pass_rate)

    cats = set(cell.category_pass) | set(baseline.category_pass)
    d_cat_pass = {c: _r(float(cell.category_pass.get(c, 0.0))
                        - float(baseline.category_pass.get(c, 0.0)))
                  for c in sorted(cats)}

    dist_cats = set(cell.category_distribution) | set(
        baseline.category_distribution)
    d_cat_count = {c: int(cell.category_distribution.get(c, 0))
                   - int(baseline.category_distribution.get(c, 0))
                   for c in sorted(dist_cats)}
    d_event = int(d_cat_count.get("event_count", 0))

    improved = worsened = tied = 0
    for page in sorted(set(cell.per_page) & set(baseline.per_page)):
        diff = (cell.per_page[page].note_pass_rate
                - baseline.per_page[page].note_pass_rate)
        if diff > _EPS:
            improved += 1
        elif diff < -_EPS:
            worsened += 1
        else:
            tied += 1

    p_value = round(sign_test_p(improved, worsened), 6)
    ci = bootstrap_ci_by_page(_pairs(cell), _pairs(baseline),
                              th.bootstrap_iters, th.bootstrap_seed)

    degraded = sorted(set(cell.preprocess.degraded_pages)
                      | set(baseline.preprocess.degraded_pages))
    d_note_clean: Optional[float] = None
    d_field_clean: Optional[float] = None
    if degraded:
        cell_note, cell_field = _subset_rates(cell, degraded)
        base_note, base_field = _subset_rates(baseline, degraded)
        if cell_note is not None and base_note is not None:
            d_note_clean = _r(cell_note - base_note)
            d_field_clean = _r((cell_field or 0.0) - (base_field or 0.0))

    notes: List[str] = []
    if degraded:
        notes.append(f"⚠ 降级页 {len(degraded)} 个：{'/'.join(degraded)}"
                     f"（已出剔除降级页第二口径 Δ）")
    if not cell.comparable:
        notes.append(f"⚠ SK-10：cell 有 fatal 页 {list(cell.fatal_files)}，"
                     f"分母漂移，Δ 不可比、不参与决策")
    if not baseline.comparable:
        notes.append(f"⚠ SK-10：baseline 有 fatal 页 {list(baseline.fatal_files)}，"
                     f"Δ 不可比")

    delta = DeltaResult(
        cell_id=cell.cell_id,
        baseline_cell_id=baseline.cell_id,
        d_note_pass_pp=d_note,
        d_field_pass_pp=d_field,
        d_category_pass_pp=d_cat_pass,
        d_category_count=d_cat_count,
        d_event_count=d_event,
        pages_improved=improved,
        pages_worsened=worsened,
        pages_tied=tied,
        sign_test_p=p_value,
        ci95_note_pass_pp=ci,
        verdict=VERDICT_NEUTRAL,
        degraded_contaminated=bool(degraded),
        excluded_pages=tuple(degraded),
        d_note_pass_pp_excl_degraded=d_note_clean,
        d_field_pass_pp_excl_degraded=d_field_clean,
        comparable=cell.comparable and baseline.comparable,
        notes=tuple(notes),
    )
    return replace(delta, verdict=classify_verdict(delta, th))


# ======================================================================
# 5. 不变量 / 透明性 / 探针诊断
# ======================================================================


def evaluate_invariant(reports: Mapping[str, Mapping[str, Any]],
                       *,
                       expected: int = INVARIANT_EXPECTED_GT
                       ) -> InvariantResult:
    """Stage-3 不变量守护：干净 GT 上跑 ``--apply-postcorrect`` 必须 ``applied == 0``。

    这是 P1-1 的立项红线（R6）：后处理规则只允许修 OMR 的错，
    对人工权威 MusicXML **一处都不许改**。任何非零 ``appliedCount``
    都会让整轮实验判 FAIL、不出任何默认开关建议。

    **覆盖度门槛（QA-1 修复）**：``len(reports) < expected``（默认 13 份规范
    清单）一律判 FAIL——空集合或缩水的报告集合不能「真空为真」地放行后处理
    默认开。报告缺一份，红线就少一道防线，必须显式标记。

    Args:
        reports: ``{gt 文件名: P1-1 审计报告 dict}``。报告为 None 表示该文件
            跑失败——同样视为违规（无法自证清白）。
        expected: 期望覆盖的干净 GT 份数（默认 :data:`INVARIANT_EXPECTED_GT`
            = 6 concerto + 7 P1-1 = 13）。驱动层应传入
            ``len(invariant_gt_files())` 的**规范要求值**而非实际值，避免缺
            文件被静默当成「达标」。

    Returns:
        InvariantResult
    """
    applied_per_file: Dict[str, int] = {}
    violations: List[str] = []
    for name in sorted(reports):
        report = reports[name]
        if not isinstance(report, Mapping):
            violations.append(f"{name}: 审计报告缺失/不可解析，无法验证不变量")
            applied_per_file[name] = -1
            continue
        applied = int(report.get("appliedCount",
                                 len(report.get("applied") or [])) or 0)
        applied_per_file[name] = applied
        if applied != 0:
            kinds = sorted({str((x or {}).get("kind", "?"))
                            for x in (report.get("applied") or [])})
            violations.append(
                f"{name}: applied={applied}（kinds={','.join(kinds) or '?'}）"
                f" —— 干净 GT 上产生了修正，P1-1 红线被打破")
    if expected and len(reports) < expected:
        violations.append(
            f"覆盖不足 {len(reports)}/{expected} 份干净 GT——Stage-3 红线缩水，"
            f"P1-1 立项红线（干净 GT 上一处都不许改）无法验证，"
            f"整轮不予推荐默认开后处理")
    return InvariantResult(
        passed=not violations,
        gt_files_checked=len(reports),
        applied_per_file=applied_per_file,
        violations=tuple(violations),
        expected_gt=expected,
    )


def check_transparency(noop_cell: Optional[CellResult],
                       baseline_cell: Optional[CellResult]) -> List[str]:
    """R7：``pipe_noop`` arm 必须与 ``pre_off`` 基线**完全一致**。

    不一致说明 P0-2 的"透明代理"其实有副作用（例如改了图、改了 argv、
    改了产物落点），这会污染所有 preset arm 的 Δ ⇒ 阻断性发现。

    Returns:
        List[str]: 不一致描述列表；空列表表示透明性成立。
    """
    if noop_cell is None or baseline_cell is None:
        return []
    findings: List[str] = []
    checks = (
        ("note_pass_rate", noop_cell.note_pass_rate, baseline_cell.note_pass_rate),
        ("field_pass_rate", noop_cell.field_pass_rate, baseline_cell.field_pass_rate),
        ("notes_compared", noop_cell.notes_compared, baseline_cell.notes_compared),
        ("field_checked", noop_cell.field_checked, baseline_cell.field_checked),
    )
    for name, got, want in checks:
        if abs(float(got) - float(want)) > _EPS:
            findings.append(
                f"R7 透明性破裂：pipe_noop.{name}={got} != pre_off.{name}={want}"
                f" —— omr_pipeline.py --no-preprocess 与直调不等价")
    if dict(noop_cell.category_distribution) != dict(
            baseline_cell.category_distribution):
        findings.append(
            "R7 透明性破裂：pipe_noop 与 pre_off 的 category_distribution 不一致")
    return findings


def diagnose_deskew(deltas: Sequence[DeltaResult]) -> Optional[str]:
    """R1：``pre_photo`` vs ``pre_photo_nodeskew`` 的单变量归因。

    若 ``Δ(photo) < 0`` 且 ``Δ(photo_nodeskew) ≥ 0``，说明拖后腿的正是
    deskew（与 oemer 内部 dewarp 叠加），建议把 photo preset 的
    ``enable_deskew`` 改回 ``false``。

    Returns:
        Optional[str]: 归因结论；证据不足时返回 None。
    """
    by_cell = {d.cell_id: d for d in deltas}
    photo = by_cell.get(cell_id_of("pre_photo", PC_OFF))
    probe = by_cell.get(cell_id_of(PROBE_ARM_ID, PC_OFF))
    if photo is None or probe is None:
        return None
    if photo.d_note_pass_pp < 0.0 <= probe.d_note_pass_pp:
        return (f"R1 归因：pre_photo Δnote={photo.d_note_pass_pp:+.2f}pp < 0 而 "
                f"pre_photo_nodeskew Δnote={probe.d_note_pass_pp:+.2f}pp ≥ 0 "
                f"⇒ deskew 与 oemer 内部 dewarp 冲突，建议把 photo preset 的 "
                f"enable_deskew 改回 false")
    if photo.d_note_pass_pp >= 0.0 and probe.d_note_pass_pp >= 0.0:
        return (f"R1 归因：photo({photo.d_note_pass_pp:+.2f}pp) 与 "
                f"photo_nodeskew({probe.d_note_pass_pp:+.2f}pp) 同为非负，"
                f"未观察到 deskew 与 oemer dewarp 的冲突证据")
    return (f"R1 归因：photo({photo.d_note_pass_pp:+.2f}pp) / "
            f"photo_nodeskew({probe.d_note_pass_pp:+.2f}pp)，"
            f"未构成「deskew 有害」的充分证据")


# ======================================================================
# 6. 决策公式（设计 §6.3 / §6.4，逐条判据留痕）
# ======================================================================


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def decide_preprocess(deltas: Sequence[DeltaResult],
                      cells: Mapping[str, CellResult],
                      th: Optional[DecisionThresholds] = None
                      ) -> Tuple[str, List[str]]:
    """预处理默认开关判定（设计 §6.3 的 C1–C5）。

    候选 = 所有 ``pc_off`` cell，排除基线 ``pre_off``、透明性 sanity
    ``pipe_noop``、以及 K2 探针 ``pre_photo_nodeskew``（探针需要覆盖配置，
    不是可直接推荐的 preset）。

    判据：

    ======  ======================================================
    C1      ``degraded_pages == 0``（降级页会把"没跑"误算成"无收益"）
    C2      ``Δnote ≥ min_note_pass_gain_pp`` **且** ``Δfield ≥ min_field_pass_gain_pp``
    C3      ``∀cat: Δcategory_pass_pp ≥ −max_category_regress_pp``
    C4      ``pages_improved ≥ min_improved_pages`` **且** ``pages_worsened ≤ max_worsened_pages``
    C5      ``Δevent_count ≤ 0``（对齐健康度未恶化）
    ======  ======================================================

    选优：全过者中取 ``Δfield`` 最大；平手取 ``Δnote``；再平手取
    ``total_ms_mean`` 更小者。

    Returns:
        Tuple[str, List[str]]: ``("on:<preset>" | "off", 逐条判据留痕)``。
    """
    th = th or DecisionThresholds()
    trace: List[str] = []
    excluded = {BASELINE_ARM_ID, SANITY_ARM_ID, PROBE_ARM_ID}
    passed: List[Tuple[DeltaResult, CellResult]] = []

    candidates = [d for d in deltas
                  if d.cell_id.endswith("__" + PC_OFF)
                  and d.baseline_cell_id.endswith("__" + PC_OFF)
                  and cells.get(d.cell_id) is not None
                  and cells[d.cell_id].arm_id not in excluded]

    if not candidates:
        trace.append("无候选 preset arm（矩阵里只有基线/sanity/探针）⇒ 判定 off")
        return ("off", trace)

    for d in sorted(candidates, key=lambda x: x.cell_id):
        cell = cells[d.cell_id]
        preset = preset_of_arm(cell.arm_id)

        c0_ok = cell.comparable
        c1_ok = (not cell.preprocess.any_degraded()) if th.require_zero_degraded \
            else True
        c2_ok = (d.d_note_pass_pp >= th.min_note_pass_gain_pp
                 and d.d_field_pass_pp >= th.min_field_pass_gain_pp)
        worst_cat, worst_val = "", 0.0
        for cat, val in d.d_category_pass_pp.items():
            if val < worst_val:
                worst_cat, worst_val = cat, val
        c3_ok = worst_val >= -th.max_category_regress_pp
        c4_ok = (d.pages_improved >= th.min_improved_pages
                 and d.pages_worsened <= th.max_worsened_pages)
        c5_ok = d.d_event_count <= 0

        all_ok = c0_ok and c1_ok and c2_ok and c3_ok and c4_ok and c5_ok
        trace.append(
            f"{cell.arm_id}: "
            f"C0 可比({'无 fatal' if c0_ok else list(cell.fatal_files)}) {_mark(c0_ok)} | "
            f"C1 降级页={len(cell.preprocess.degraded_pages)} {_mark(c1_ok)} | "
            f"C2 Δnote={d.d_note_pass_pp:+.2f}pp(≥{th.min_note_pass_gain_pp}) "
            f"Δfield={d.d_field_pass_pp:+.2f}pp(≥{th.min_field_pass_gain_pp}) {_mark(c2_ok)} | "
            f"C3 最差维度 {worst_cat or '—'}={worst_val:+.2f}pp"
            f"(≥-{th.max_category_regress_pp}) {_mark(c3_ok)} | "
            f"C4 改善/恶化页={d.pages_improved}/{d.pages_worsened}"
            f"(≥{th.min_improved_pages}/≤{th.max_worsened_pages}) {_mark(c4_ok)} | "
            f"C5 Δevent_count={d.d_event_count:+d}(≤0) {_mark(c5_ok)} | "
            f"verdict={d.verdict} p={d.sign_test_p:.4f} "
            f"CI95=[{d.ci95_note_pass_pp[0]:+.2f},{d.ci95_note_pass_pp[1]:+.2f}]pp "
            f"⇒ 判定 {'推荐默认开 ' + preset if all_ok else '不推荐默认开'}")
        if all_ok:
            passed.append((d, cell))

    if not passed:
        best = max(candidates, key=lambda x: (x.d_field_pass_pp,
                                              x.d_note_pass_pp))
        best_cell = cells[best.cell_id]
        trace.append(
            f"无 preset 通过 C1–C5 ⇒ preprocess_default=off（维持 opt-in）。"
            f"手动使用建议：最佳候选 {best_cell.arm_id} "
            f"（Δfield={best.d_field_pass_pp:+.2f}pp / "
            f"Δnote={best.d_note_pass_pp:+.2f}pp / verdict={best.verdict}）")
        return ("off", trace)

    passed.sort(key=lambda pair: (-pair[0].d_field_pass_pp,
                                  -pair[0].d_note_pass_pp,
                                  pair[1].preprocess.total_ms_mean,
                                  pair[1].arm_id))
    win_delta, win_cell = passed[0]
    preset = preset_of_arm(win_cell.arm_id)
    trace.append(
        f"选优：{len(passed)} 个 preset 通过 C1–C5，按 Δfield 降序取 "
        f"{win_cell.arm_id}（Δfield={win_delta.d_field_pass_pp:+.2f}pp / "
        f"Δnote={win_delta.d_note_pass_pp:+.2f}pp / "
        f"total_ms_mean={win_cell.preprocess.total_ms_mean:.1f}）"
        f"⇒ preprocess_default=on:{preset}")
    return (f"on:{preset}", trace)


def decide_postcorrect(deltas: Sequence[DeltaResult],
                       cells: Mapping[str, CellResult],
                       invariant: InvariantResult,
                       th: Optional[DecisionThresholds] = None
                       ) -> Tuple[str, List[str]]:
    """后处理默认开关判定（设计 §6.4 的 C1′–C5′）。

    观测对：``<baseline_arm>__pc_on`` vs ``<baseline_arm>__pc_off``
    （同一批 pred 上做两次投影，唯一变量就是后处理，归因干净）。

    ======  ======================================================
    C1′     不变量硬门槛：干净 GT 上 ``applied == 0``（失败 ⇒ 整轮 FAIL）
    C2′     ``Σ Δcount(cat), cat ∈ POSTCORRECT_RELEVANT < 0``
    C3′     ``∀cat ∉ POSTCORRECT_RELEVANT: Δcount(cat) ≤ 0``
    C4′     ``Δnote_pass_pp ≥ 0``
    C5′     ``Δfield_pass_pp ≥ postcorrect_min_field_gain_pp``
    ======  ======================================================

    Returns:
        Tuple[str, List[str]]: ``("on_for_omr_path" | "off" | "fail", 留痕)``。
        ``"on_for_omr_path"`` 的确切含义（U6）：**只**在 ``--from-omr`` 入口
        默认开 + 提供 ``--no-postcorrect`` 逃生舱；纯 MusicXML→简谱 转换入口
        **保持默认关**，守住"转换 100% 不变"红线。
    """
    th = th or DecisionThresholds()
    trace: List[str] = []

    # QA-1 修复：覆盖度也纳入 C1′ 硬门槛。``gt_files_checked`` 低于规范 13 份
    # （空集合 / 缩水）一律判 FAIL——真空为真是 P1-1 立项红线的致命漏洞。
    coverage_ok = invariant.coverage_ok
    c1_ok = invariant.passed and coverage_ok
    coverage_note = ("" if coverage_ok else
                     f" | 覆盖缩水 {invariant.gt_files_checked}/"
                     f"{invariant.expected_gt}，红线不完整无法验证")
    trace.append(
        f"C1′ 不变量：{invariant.gt_files_checked}/{invariant.expected_gt} 份干净 GT "
        f"跑 --apply-postcorrect，applied 全为 0 {_mark(c1_ok)}"
        + ("" if c1_ok else f" | 违规：{'; '.join(invariant.violations)}{coverage_note}"))
    if not c1_ok:
        trace.append("C1′ 失败 ⇒ 整轮 FAIL，不出任何默认开关建议（P1-1 立项红线）")
        return (POSTCORRECT_FAIL, trace)

    target_id = cell_id_of(BASELINE_ARM_ID, PC_ON)
    base_id = cell_id_of(BASELINE_ARM_ID, PC_OFF)
    pair = next((d for d in deltas
                 if d.cell_id == target_id and d.baseline_cell_id == base_id),
                None)
    if pair is None:
        trace.append(f"缺少观测对 {target_id} vs {base_id} ⇒ 无法判定，取 off")
        return (POSTCORRECT_DEFAULT_OFF, trace)

    cell = cells.get(target_id)
    if cell is not None and not cell.comparable:
        trace.append(f"SK-10：{target_id} 有 fatal 页 {list(cell.fatal_files)}，"
                     f"Δ 不可比 ⇒ 取 off")
        return (POSTCORRECT_DEFAULT_OFF, trace)

    relevant_sum = sum(v for k, v in pair.d_category_count.items()
                       if k in POSTCORRECT_RELEVANT)
    c2_ok = relevant_sum < 0
    trace.append(
        f"C2′ 相关类别净降：Σ Δcount({'/'.join(sorted(POSTCORRECT_RELEVANT))})"
        f"={relevant_sum:+d}(<0) {_mark(c2_ok)}")

    bad_others = {k: v for k, v in pair.d_category_count.items()
                  if k not in POSTCORRECT_RELEVANT and v > 0}
    c3_ok = not bad_others
    trace.append(
        f"C3′ 无关类别不恶化：{'无恶化' if c3_ok else bad_others} {_mark(c3_ok)}")

    c4_ok = pair.d_note_pass_pp >= 0.0
    trace.append(f"C4′ 主指标不倒退：Δnote={pair.d_note_pass_pp:+.2f}pp(≥0) "
                 f"{_mark(c4_ok)}")

    c5_ok = pair.d_field_pass_pp >= th.postcorrect_min_field_gain_pp
    trace.append(f"C5′ 增益门槛：Δfield={pair.d_field_pass_pp:+.2f}pp"
                 f"(≥{th.postcorrect_min_field_gain_pp}) {_mark(c5_ok)}")

    stats = cell.postcorrect_stats if cell else PostCorrectSummary()
    trace.append(
        f"（参考）后处理审计：applied={stats.applied_total} / "
        f"flagged={stats.flagged_total} / 对账小节={stats.measures_reconciled} / "
        f"涉及音符={stats.notes_touched} / by_kind={dict(stats.by_kind)}")

    if c2_ok and c3_ok and c4_ok and c5_ok:
        trace.append(
            "C1′–C5′ 全过 ⇒ postcorrect_default=on_for_omr_path："
            "仅 --from-omr 入口默认开（配 --no-postcorrect 逃生舱），"
            "纯 MusicXML→简谱 转换入口保持默认关（守住「转换 100% 不变」红线）")
        return (POSTCORRECT_DEFAULT_ON, trace)

    failed = [name for name, ok in
              (("C2′", c2_ok), ("C3′", c3_ok), ("C4′", c4_ok), ("C5′", c5_ok))
              if not ok]
    trace.append(f"未通过判据 {'/'.join(failed)} ⇒ postcorrect_default=off")
    return (POSTCORRECT_DEFAULT_OFF, trace)


def make_decision(cells: Mapping[str, CellResult],
                  deltas: Sequence[DeltaResult],
                  invariant: InvariantResult,
                  th: Optional[DecisionThresholds] = None,
                  extra_blocking: Sequence[str] = (),
                  corpus_label: str = "clean-scan corpus") -> Decision:
    """汇总两套判定 + 阻断性发现 + 置信度标注。

    Args:
        cells: ``{cell_id: CellResult}``。
        deltas: 全部 Δ（预处理 Δ 与后处理 Δ 混在一个列表里，靠
            ``baseline_cell_id`` 区分）。
        invariant: Stage-3 不变量结果。
        th: 阈值。
        extra_blocking: 驱动层发现的阻断项（如 R7 透明性破裂）。
        corpus_label: 语料性质描述，进 ``confidence``（U5：结论不外推）。

    Returns:
        Decision
    """
    th = th or DecisionThresholds()
    pre_default, pre_trace = decide_preprocess(deltas, cells, th)
    post_default, post_trace = decide_postcorrect(deltas, cells, invariant, th)

    blocking: List[str] = list(extra_blocking)
    blocking.extend(invariant.violations)
    # QA-1 修复：覆盖缩水（< 规范 13 份）时，即便 ``passed`` 被外部误置为
    # True（如单元测试直接构造），也必须留下阻断性发现，使报告与全量绿跑
    # 可区分。``invariant.violations`` 已含覆盖违规时不再重复追加。
    if not invariant.coverage_ok and not invariant.violations:
        blocking.append(
            f"C1′ 覆盖缩水：仅 {invariant.gt_files_checked}/{invariant.expected_gt} "
            f"份干净 GT 被验证——Stage-3 红线不完整，P1-1 立项红线无法证实，"
            f"整轮不予推荐默认开后处理")
    for cell in sorted(cells.values(), key=lambda c: c.cell_id):
        if not cell.comparable:
            blocking.append(
                f"SK-10：cell {cell.cell_id} 存在 fatal 页 "
                f"{list(cell.fatal_files)}，已排除出决策")

    probe_note = diagnose_deskew(deltas)
    if probe_note:
        pre_trace.append(probe_note)

    baseline = cells.get(cell_id_of(BASELINE_ARM_ID, PC_OFF))
    pages = baseline.pages_count if baseline else 0
    has_significant = any(d.verdict == VERDICT_SIGNIFICANT for d in deltas)
    if invariant.passed and has_significant:
        confidence = (f"significant on at least one arm "
                      f"(n={pages} pages, {corpus_label}; "
                      f"按页符号检验 p≤{SIGNIFICANCE_ALPHA} 且 bootstrap CI 不跨 0)")
    else:
        confidence = (f"directional-only (n={pages} pages, {corpus_label}) "
                      f"—— 方向性证据，未达统计显著，禁止表述为「已验证/已证明」（SK-11）")

    return Decision(
        preprocess_default=pre_default,
        preprocess_criteria_trace=tuple(pre_trace),
        postcorrect_default=post_default,
        postcorrect_criteria_trace=tuple(post_trace),
        blocking_findings=tuple(blocking),
        confidence=confidence,
    )


# ======================================================================
# 7. 渲染
# ======================================================================


def _fmt_ci(ci: Tuple[float, float]) -> str:
    return f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"


_VERDICT_WORDING = {
    VERDICT_SIGNIFICANT: "统计显著",
    VERDICT_DIRECTIONAL: "方向性证据（未达显著）",
    VERDICT_NEUTRAL: "无变化",
    VERDICT_REGRESSION: "退化",
}


def render_markdown(summary: AbtestSummary) -> str:
    """渲染人读版 ``abtest_report.md``（矩阵表 + Δ 表 + 决策留痕）。

    强制包含（SK-11）：``confidence`` 行 + verdict 措辞对照表，
    ``directional`` 一律写成"方向性证据（未达显著）"，
    **不得**出现"已验证/已证明"。

    Args:
        summary: :class:`AbtestSummary`。

    Returns:
        str: Markdown 文本。
    """
    cfg = summary.config
    lines: List[str] = []
    add = lines.append

    add("# 谱渡 Pudu · P1-2 预处理 A/B + 后处理前后对比 · 实验报告")
    add("")
    add(f"> run_id: `{cfg.run_id}`　　语料: `{cfg.corpus_dir}`　　"
        f"baseline: `{cfg.baseline_cell}`")
    add(f"> 产物目录: `{cfg.work_root}`　　schema: `{SCHEMA}`")
    add("")

    # —— 置信度横幅（SK-11 强制）——
    add("## 0. 置信度声明（SK-11）")
    add("")
    add(f"**confidence**: {summary.decision.confidence}")
    add("")
    add("| verdict | 允许的措辞 |")
    add("|---|---|")
    for key, wording in _VERDICT_WORDING.items():
        add(f"| `{key}` | {wording} |")
    add("")
    add("> `directional` 结论**禁止**表述为「已验证 / 已证明」；"
        "结论仅对本语料的谱型成立，不外推到多谱表 / 手写 / 钢琴大谱表（U5）。")
    add("")

    # —— 阻断性发现 ——
    add("## 1. 阻断性发现")
    add("")
    if summary.decision.blocking_findings:
        for item in summary.decision.blocking_findings:
            add(f"- 🔴 {item}")
    else:
        add("- 无。")
    add("")

    # —— 环境指纹 ——
    add("## 2. 环境指纹与阈值（R4 可复现性）")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    for key, value in cfg.env.to_dict().items():
        add(f"| `{key}` | `{value or '—'}` |")
    for key, value in cfg.thresholds.to_dict().items():
        add(f"| `thresholds.{key}` | `{value}` |")
    add("")

    # —— cell 矩阵 ——
    add("## 3. cell 矩阵")
    add("")
    add("| cell_id | arm | postcorrect | note_pass% | field_pass% | "
        "notes | 降级页 | fatal | 后处理 applied/flagged |")
    add("|---|---|---|---|---|---|---|---|---|")
    for cell in summary.cells:
        degraded = (f"⚠ {len(cell.preprocess.degraded_pages)}"
                    if cell.preprocess.any_degraded() else "0")
        add(f"| `{cell.cell_id}` | {cell.arm_id} | "
            f"{'on' if cell.postcorrect else 'off'} | "
            f"{cell.note_pass_rate:.2f} | {cell.field_pass_rate:.2f} | "
            f"{cell.notes_compared} | {degraded} | "
            f"{len(cell.fatal_files)} | "
            f"{cell.postcorrect_stats.applied_total}/"
            f"{cell.postcorrect_stats.flagged_total} |")
    add("")

    # —— Δ 表 ——
    add("## 4. Δ 表（相对各自 baseline）")
    add("")
    add("| cell_id | baseline | Δnote(pp) | Δfield(pp) | Δevent_count | "
        "改善/恶化/打平 | sign p | CI95(pp) | verdict |")
    add("|---|---|---|---|---|---|---|---|---|")
    for d in summary.deltas:
        add(f"| `{d.cell_id}` | `{d.baseline_cell_id}` | "
            f"{d.d_note_pass_pp:+.2f} | {d.d_field_pass_pp:+.2f} | "
            f"{d.d_event_count:+d} | "
            f"{d.pages_improved}/{d.pages_worsened}/{d.pages_tied} | "
            f"{d.sign_test_p:.4f} | {_fmt_ci(d.ci95_note_pass_pp)} | "
            f"`{d.verdict}`（{_VERDICT_WORDING.get(d.verdict, d.verdict)}） |")
    add("")

    # —— 降级双口径 ——
    contaminated = [d for d in summary.deltas if d.degraded_contaminated]
    add("## 5. 降级页双口径（SK-5 / R3）")
    add("")
    if not contaminated:
        add("- 全部 cell `degraded_pages == 0`，无需第二口径。")
    else:
        add("| cell_id | 剔除页 | Δnote 全量 | Δnote 剔除降级页 | "
            "Δfield 全量 | Δfield 剔除降级页 |")
        add("|---|---|---|---|---|---|")
        for d in contaminated:
            clean_n = ("—" if d.d_note_pass_pp_excl_degraded is None
                       else f"{d.d_note_pass_pp_excl_degraded:+.2f}")
            clean_f = ("—" if d.d_field_pass_pp_excl_degraded is None
                       else f"{d.d_field_pass_pp_excl_degraded:+.2f}")
            add(f"| `{d.cell_id}` | ⚠ {'/'.join(d.excluded_pages)} | "
                f"{d.d_note_pass_pp:+.2f} | {clean_n} | "
                f"{d.d_field_pass_pp:+.2f} | {clean_f} |")
    add("")

    # —— 逐维度 ——
    add("## 6. 逐维度 category_pass Δ（pp）")
    add("")
    cats: List[str] = []
    for d in summary.deltas:
        for cat in d.d_category_pass_pp:
            if cat not in cats:
                cats.append(cat)
    cats.sort()
    if cats:
        add("| cell_id | " + " | ".join(f"`{c}`" for c in cats) + " |")
        add("|---" * (len(cats) + 1) + "|")
        for d in summary.deltas:
            row = " | ".join(f"{d.d_category_pass_pp.get(c, 0.0):+.2f}"
                             for c in cats)
            add(f"| `{d.cell_id}` | {row} |")
    else:
        add("- （无逐音符维度数据）")
    add("")

    # —— 不变量 ——
    add("## 7. Stage-3 不变量守护（P1-1 红线）")
    add("")
    add(f"- 结论：**{'PASS ✅' if summary.invariant.passed else 'FAIL 🔴'}**"
        f"（覆盖 {summary.invariant.gt_files_checked}/"
        f"{summary.invariant.expected_gt} 份干净 GT，要求 `applied == 0`）")
    if not summary.invariant.coverage_ok:
        add(f"- 🔴 覆盖缩水：规范要求 {summary.invariant.expected_gt} 份，"
            f"实到 {summary.invariant.gt_files_checked} 份——"
            f"红线不完整，本轮不得据此推荐默认开后处理")
    if summary.invariant.violations:
        for item in summary.invariant.violations:
            add(f"  - 🔴 {item}")
    add("")

    # —— 决策 ——
    add("## 8. 决策")
    add("")
    add(f"- `preprocess_default` = **`{summary.decision.preprocess_default}`**")
    for item in summary.decision.preprocess_criteria_trace:
        add(f"  - {item}")
    add("")
    add(f"- `postcorrect_default` = **`{summary.decision.postcorrect_default}`**")
    for item in summary.decision.postcorrect_criteria_trace:
        add(f"  - {item}")
    add("")
    add(f"- `confidence` = {summary.decision.confidence}")
    add("")
    return "\n".join(lines) + "\n"
