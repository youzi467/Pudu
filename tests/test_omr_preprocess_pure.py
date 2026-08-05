# -*- coding: utf-8 -*-
"""P0-2 预处理纯函数单元测试（**不需要 opencv**）。

覆盖需求：

* **R-P0-05 / P1-01 纠偏安全**：:func:`decide_deskew` 的全部边界
  （开关关 / None / NaN / inf / 0.0 / 恰等于 min / 恰等于 max / 超 max /
  低于 min / 正负号取反），**超限绝不强扭**。
* **P1-04 可观测性**：:func:`build_metrics` 产出的 schema 完整、键恒在、类型正确。
* **fail-open**：注入异常后 ``ok=False`` / ``degraded=True`` 且
  ``degrade_reason`` 非空；``fail_open=False`` 时如实抛出。
* :func:`is_supported_input` / :func:`is_noop_config` 的判定边界。
* **Bug C 过度预处理**：:func:`safe_denoise_strength` 的线宽感知钳制
  （1px 五线必须关掉去噪）、:func:`staffline_retention` /
  :func:`is_over_processed` 的熔断阈值与"无法判定时不熔断"契约，
  以及新增 metrics 字段的默认值/类型。
"""

import math
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import omr_preprocess  # noqa: E402
from omr_preprocess import (  # noqa: E402
    DEFAULTS, METRICS_SCHEMA, STAFFLINE_RETENTION_MIN, TIMING_STEPS,
    TOOL_VERSION,
    DeskewDecision, PreprocessConfig,
    build_metrics, decide_deskew, is_noop_config, is_over_processed,
    is_supported_input, preprocess_for_omr, safe_denoise_strength,
    staffline_retention,
)


def _deskew_cfg(**overrides) -> PreprocessConfig:
    """构造一个开启纠偏的配置（min=0.15, max=2.0）。"""
    cfg = PreprocessConfig()
    cfg.enable_deskew = True
    cfg.max_deskew_deg = 2.0
    cfg.min_deskew_deg = 0.15
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class DecideDeskewTest(unittest.TestCase):
    """R-P0-05 / P1-01：纠偏决策边界。"""

    def test_returns_decision_dataclass(self):
        result = decide_deskew(1.0, _deskew_cfg())
        self.assertIsInstance(result, DeskewDecision)
        self.assertEqual(
            (result.apply, result.angle_deg, result.reason),
            (True, -1.0, "apply"))

    # -- 开关 --------------------------------------------------------------

    def test_disabled_switch_never_rotates(self):
        cfg = _deskew_cfg(enable_deskew=False)
        for angle in (None, 0.0, 0.5, 1.0, -1.0, 100.0, float("nan")):
            result = decide_deskew(angle, cfg)
            self.assertFalse(result.apply)
            self.assertEqual(result.angle_deg, 0.0)
            self.assertEqual(result.reason, "disabled")

    def test_disabled_takes_precedence_over_everything(self):
        self.assertEqual(decide_deskew(1.0, PreprocessConfig()).reason, "disabled")

    # -- 无角度 ------------------------------------------------------------

    def test_none_angle(self):
        result = decide_deskew(None, _deskew_cfg())
        self.assertEqual((result.apply, result.angle_deg, result.reason),
                         (False, 0.0, "no_angle"))

    def test_nan_angle(self):
        result = decide_deskew(float("nan"), _deskew_cfg())
        self.assertEqual((result.apply, result.angle_deg, result.reason),
                         (False, 0.0, "no_angle"))

    def test_inf_angle(self):
        for angle in (float("inf"), float("-inf")):
            result = decide_deskew(angle, _deskew_cfg())
            self.assertEqual((result.apply, result.angle_deg, result.reason),
                             (False, 0.0, "no_angle"))

    def test_non_numeric_angle(self):
        result = decide_deskew("abc", _deskew_cfg())
        self.assertEqual(result.reason, "no_angle")
        self.assertFalse(result.apply)

    # -- 阈值边界 ----------------------------------------------------------

    def test_zero_angle_is_below_min(self):
        result = decide_deskew(0.0, _deskew_cfg())
        self.assertEqual((result.apply, result.angle_deg, result.reason),
                         (False, 0.0, "below_min"))

    def test_below_min(self):
        for angle in (0.14, -0.14, 0.0001):
            result = decide_deskew(angle, _deskew_cfg())
            self.assertEqual(result.reason, "below_min")
            self.assertFalse(result.apply)
            self.assertEqual(result.angle_deg, 0.0)

    def test_exactly_min_is_applied(self):
        result = decide_deskew(0.15, _deskew_cfg())
        self.assertTrue(result.apply)
        self.assertEqual(result.reason, "apply")
        self.assertAlmostEqual(result.angle_deg, -0.15)

    def test_exactly_max_is_applied(self):
        result = decide_deskew(2.0, _deskew_cfg())
        self.assertTrue(result.apply)
        self.assertEqual(result.reason, "apply")
        self.assertAlmostEqual(result.angle_deg, -2.0)

    def test_exactly_negative_max_is_applied(self):
        result = decide_deskew(-2.0, _deskew_cfg())
        self.assertTrue(result.apply)
        self.assertAlmostEqual(result.angle_deg, 2.0)

    def test_above_max_never_forces_rotation(self):
        """超限**绝不强扭**：多半是测角失败，硬转会毁掉好图。"""
        for angle in (2.0001, 3.0, 45.0, -90.0, 179.9):
            result = decide_deskew(angle, _deskew_cfg())
            self.assertEqual(result.reason, "above_max")
            self.assertFalse(result.apply)
            self.assertEqual(result.angle_deg, 0.0)

    def test_min_zero_allows_zero_angle(self):
        cfg = _deskew_cfg(min_deskew_deg=0.0)
        result = decide_deskew(0.0, cfg)
        self.assertTrue(result.apply)
        self.assertEqual(result.reason, "apply")
        self.assertEqual(abs(result.angle_deg), 0.0)

    def test_sign_is_inverted(self):
        self.assertAlmostEqual(decide_deskew(1.3, _deskew_cfg()).angle_deg, -1.3)
        self.assertAlmostEqual(decide_deskew(-1.3, _deskew_cfg()).angle_deg, 1.3)

    def test_integer_angle_accepted(self):
        result = decide_deskew(1, _deskew_cfg())
        self.assertTrue(result.apply)
        self.assertAlmostEqual(result.angle_deg, -1.0)

    def test_bool_angle_is_rejected(self):
        """bool 是 int 的子类，但把 True 当 1 度显然是调用方 bug -> no_angle。"""
        self.assertEqual(decide_deskew(True, _deskew_cfg()).reason, "no_angle")


class BuildMetricsTest(unittest.TestCase):
    """P1-04：metrics schema 完整性与类型。"""

    EXPECTED_KEYS = {
        "schema", "ok", "degraded", "degrade_reason", "src", "dst",
        "config", "config_source", "preset", "size_in", "size_out",
        "mean_intensity_in", "mean_intensity_out",
        "mean_contrast_in", "mean_contrast_out",
        "binarize_method", "bin_thresh", "ink_ratio_out",
        # Bug C 诊断字段：五线保真度（线宽 / 实际去噪核 / 能量留存）
        "staffline_thickness_px", "denoise_strength_applied",
        "staffline_energy_in", "staffline_energy_out", "staffline_retention",
        "deskew_angle_est_deg", "deskew_applied_deg", "deskew_decision",
        "steps_timing_ms", "total_ms", "warnings", "tool_version",
        # fix (b) fail-open 兜底追踪字段（默认空，fail-open 时填充）
        "fell_back_to_raw", "enhanced_oemer_rc", "enhanced_oemer_stderr",
        "raw_oemer_rc", "raw_oemer_stderr",
    }

    def test_empty_call_produces_full_schema(self):
        metrics = build_metrics()
        self.assertEqual(set(metrics.keys()), self.EXPECTED_KEYS)
        self.assertEqual(metrics["schema"], METRICS_SCHEMA)
        self.assertEqual(metrics["tool_version"], TOOL_VERSION)

    def test_all_timing_keys_always_present(self):
        metrics = build_metrics(steps_timing_ms={"read": 1.5})
        timing = metrics["steps_timing_ms"]
        self.assertEqual(set(timing.keys()), set(TIMING_STEPS))
        self.assertEqual(timing["read"], 1.5)
        for step in TIMING_STEPS:
            if step != "read":
                self.assertEqual(timing[step], 0.0)
            self.assertIsInstance(timing[step], float)

    def test_unknown_timing_key_is_dropped_with_warning(self):
        metrics = build_metrics(steps_timing_ms={"bogus": 5.0})
        self.assertNotIn("bogus", metrics["steps_timing_ms"])
        self.assertTrue(any("bogus" in w for w in metrics["warnings"]))

    def test_types(self):
        metrics = build_metrics(
            ok=1, degraded=0, src="a.png", dst="b.png",
            size_in=(100, 200), size_out=[50, 60],
            mean_intensity_in=200.5, ink_ratio_out=0.05,
            deskew_angle_est_deg=None, deskew_applied_deg=None,
            total_ms=12.3456789, warnings=["w1"])
        self.assertIsInstance(metrics["ok"], bool)
        self.assertIsInstance(metrics["degraded"], bool)
        self.assertTrue(metrics["ok"])
        self.assertFalse(metrics["degraded"])
        self.assertEqual(metrics["size_in"], [100, 200])
        self.assertEqual(metrics["size_out"], [50, 60])
        self.assertIsInstance(metrics["config"], dict)
        self.assertIsNone(metrics["deskew_angle_est_deg"])
        self.assertEqual(metrics["deskew_applied_deg"], 0.0)
        self.assertEqual(metrics["total_ms"], 12.346)
        self.assertIn("w1", metrics["warnings"])

    def test_default_config_is_defaults_copy(self):
        metrics = build_metrics()
        self.assertEqual(metrics["config"], DEFAULTS)
        metrics["config"]["C"] = 999
        self.assertNotEqual(DEFAULTS["C"], 999)   # 必须是副本，不能污染真源

    def test_bad_size_degrades_to_zero(self):
        metrics = build_metrics(size_in="not-a-size", size_out=None)
        self.assertEqual(metrics["size_in"], [0, 0])
        self.assertEqual(metrics["size_out"], [0, 0])

    def test_nan_stats_become_none(self):
        metrics = build_metrics(mean_intensity_in=float("nan"),
                                mean_contrast_out=float("inf"))
        self.assertIsNone(metrics["mean_intensity_in"])
        self.assertIsNone(metrics["mean_contrast_out"])

    def test_ink_ratio_out_of_range_adds_warning(self):
        low = build_metrics(ink_ratio_out=0.0)
        self.assertTrue(any("ink_ratio_out" in w for w in low["warnings"]))
        high = build_metrics(ink_ratio_out=0.99)
        self.assertTrue(any("ink_ratio_out" in w for w in high["warnings"]))

    def test_ink_ratio_in_range_adds_no_warning(self):
        metrics = build_metrics(ink_ratio_out=0.08)
        self.assertEqual(metrics["warnings"], [])

    def test_is_json_serialisable(self):
        import json
        metrics = build_metrics(config=PreprocessConfig().to_dict())
        text = json.dumps(metrics, ensure_ascii=False, indent=2)
        self.assertEqual(json.loads(text)["schema"], METRICS_SCHEMA)


class SupportedInputTest(unittest.TestCase):
    """图像扩展名白名单（PDF 等保守跳过）。"""

    def test_image_extensions_supported(self):
        for name in ("a.jpg", "a.JPEG", "a.png", "b/c.Bmp", "d.tif",
                     "d.tiff", "e.webp", "f.gif"):
            self.assertTrue(is_supported_input(name), name)

    def test_non_image_not_supported(self):
        for name in ("a.pdf", "a.PDF", "a.musicxml", "a", "a.txt", "a.svg"):
            self.assertFalse(is_supported_input(name), name)

    def test_empty_and_none(self):
        self.assertFalse(is_supported_input(""))
        self.assertFalse(is_supported_input(None))


class NoopConfigTest(unittest.TestCase):
    """全关配置应被识别为 no-op（上游据此跳过预处理）。"""

    def _all_off(self) -> PreprocessConfig:
        cfg = PreprocessConfig()
        cfg.enable_contrast_norm = False
        cfg.enable_shadow_suppress = False
        cfg.enable_deskew = False
        cfg.enable_border_crop = False
        cfg.denoise_strength = 0
        cfg.binarize_method = "none"
        cfg.max_long_side_px = 0
        cfg.upscale_min_long_side_px = 0
        return cfg

    def test_all_off_is_noop(self):
        self.assertTrue(is_noop_config(self._all_off()))

    def test_defaults_are_not_noop(self):
        self.assertFalse(is_noop_config(PreprocessConfig()))

    def test_single_switch_breaks_noop(self):
        for field, value in (("enable_contrast_norm", True),
                             ("enable_shadow_suppress", True),
                             ("enable_deskew", True),
                             ("enable_border_crop", True),
                             ("denoise_strength", 3),
                             ("binarize_method", "otsu"),
                             ("max_long_side_px", 2000),
                             ("upscale_min_long_side_px", 1200)):
            cfg = self._all_off()
            setattr(cfg, field, value)
            self.assertFalse(is_noop_config(cfg), field)


class FailOpenTest(unittest.TestCase):
    """fail-open：任何异常都不得阻断主流程。"""

    def setUp(self):
        self._saved_lazy = omr_preprocess._lazy_cv2
        self._tmp = tempfile.mkdtemp(prefix="pudu_failopen_")
        self._src = os.path.join(self._tmp, "in.png")
        with open(self._src, "wb") as handle:
            handle.write(b"not-a-real-png")
        self._dst = os.path.join(self._tmp, "out.pre.png")

    def tearDown(self):
        omr_preprocess._lazy_cv2 = self._saved_lazy
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_import_error_degrades_gracefully(self):
        def _boom():
            raise ImportError("No module named 'cv2'")
        omr_preprocess._lazy_cv2 = _boom

        metrics = preprocess_for_omr(self._src, self._dst, PreprocessConfig())
        self.assertFalse(metrics["ok"])
        self.assertTrue(metrics["degraded"])
        self.assertTrue(metrics["degrade_reason"])
        self.assertIn("opencv", metrics["degrade_reason"])
        self.assertEqual(metrics["dst"], self._src)   # 降级 -> 指回原图
        self.assertFalse(os.path.exists(self._dst))

    def test_runtime_error_degrades_gracefully(self):
        def _boom():
            raise RuntimeError("模拟像素流水线炸了")
        omr_preprocess._lazy_cv2 = _boom

        metrics = preprocess_for_omr(self._src, self._dst, PreprocessConfig())
        self.assertFalse(metrics["ok"])
        self.assertTrue(metrics["degraded"])
        self.assertIn("RuntimeError", metrics["degrade_reason"])
        self.assertEqual(metrics["schema"], METRICS_SCHEMA)
        self.assertEqual(set(metrics["steps_timing_ms"].keys()), set(TIMING_STEPS))

    def test_fail_closed_raises(self):
        def _boom():
            raise RuntimeError("模拟像素流水线炸了")
        omr_preprocess._lazy_cv2 = _boom

        cfg = PreprocessConfig()
        cfg.fail_open = False
        with self.assertRaises(RuntimeError):
            preprocess_for_omr(self._src, self._dst, cfg)

    def test_degraded_metrics_are_json_serialisable(self):
        import json

        def _boom():
            raise ImportError("no cv2")
        omr_preprocess._lazy_cv2 = _boom

        metrics = preprocess_for_omr(self._src, self._dst, PreprocessConfig())
        payload = json.loads(json.dumps(metrics, ensure_ascii=False))
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["degrade_reason"])


class SafeDenoiseStrengthTest(unittest.TestCase):
    """Bug C 防线①：中值滤波核的线宽感知钳制（纯函数）。

    安全条件 ``k <= 2t - 1``（推导见 :func:`safe_denoise_strength` 文档串）。
    railA 语料实测 ``t=1`` -> 必须返回 0（完全关闭去噪）。
    """

    def test_one_px_staffline_disables_denoise(self):
        """核心回归：1px 五线时任何请求核都必须被钳成 0。"""
        for requested in (3, 5, 7, 9):
            self.assertEqual(safe_denoise_strength(requested, 1.0), 0,
                             f"requested={requested}")

    def test_two_px_staffline_allows_kernel_three_only(self):
        """t=2 -> limit=2*2-1=3：只放行最小核，更大的请求一律削到 3。"""
        self.assertEqual(safe_denoise_strength(3, 2.0), 3)
        self.assertEqual(safe_denoise_strength(9, 2.0), 3)

    def test_thick_staffline_keeps_requested_kernel(self):
        """线够粗时不应无谓削弱去噪能力。"""
        self.assertEqual(safe_denoise_strength(3, 5.0), 3)
        self.assertEqual(safe_denoise_strength(5, 5.0), 5)
        self.assertEqual(safe_denoise_strength(9, 5.0), 9)

    def test_even_limit_rounds_down_to_odd(self):
        """t=3.5 -> limit=2*3-1=5（int 截断），结果必须是奇数。"""
        result = safe_denoise_strength(9, 3.5)
        self.assertEqual(result % 2, 1)
        self.assertEqual(result, 5)

    def test_requested_zero_or_negative_stays_off(self):
        for requested in (0, -1, 2):
            self.assertEqual(safe_denoise_strength(requested, 10.0), 0,
                             f"requested={requested}")

    def test_unmeasurable_thickness_is_conservative(self):
        """测不出线宽时宁可不去噪——保住五线远比去噪重要。"""
        for thickness in (None, 0, 0.0, -1.0, float("nan"), "abc"):
            self.assertEqual(safe_denoise_strength(5, thickness), 0,
                             f"thickness={thickness!r}")

    def test_garbage_requested_is_safe(self):
        self.assertEqual(safe_denoise_strength(None, 5.0), 0)
        self.assertEqual(safe_denoise_strength("x", 5.0), 0)

    def test_return_type_is_int(self):
        self.assertIsInstance(safe_denoise_strength(5, 5.0), int)
        self.assertIsInstance(safe_denoise_strength(5, None), int)


class StafflineRetentionTest(unittest.TestCase):
    """Bug C 防线②：五线能量留存率与过度预处理判定（纯函数）。"""

    def test_ratio_is_out_over_in(self):
        self.assertAlmostEqual(staffline_retention(0.02, 0.01), 0.5)
        self.assertAlmostEqual(staffline_retention(0.02, 0.02), 1.0)

    def test_undecidable_inputs_return_none(self):
        """原图本就没有五线 / 输入无效 -> None（不得据此降级）。"""
        for pair in ((0.0, 0.01), (None, 0.01), (0.02, None),
                     (-0.1, 0.01), ("x", 0.01)):
            self.assertIsNone(staffline_retention(*pair), f"pair={pair}")

    def test_over_processed_threshold(self):
        self.assertTrue(is_over_processed(0.35))     # railA denoise 实测档
        self.assertTrue(is_over_processed(0.55))
        self.assertFalse(is_over_processed(0.60))    # 恰等于下限 -> 放行
        self.assertFalse(is_over_processed(0.97))    # 健康档
        self.assertFalse(is_over_processed(1.01))

    def test_none_retention_never_trips(self):
        """无法判定时绝不熔断（避免把测量失败变成功能回归）。"""
        self.assertFalse(is_over_processed(None))
        self.assertFalse(is_over_processed("x"))
        self.assertFalse(is_over_processed(float("nan")))

    def test_custom_threshold(self):
        self.assertTrue(is_over_processed(0.8, min_retention=0.9))
        self.assertFalse(is_over_processed(0.8, min_retention=0.7))

    def test_default_threshold_matches_constant(self):
        self.assertEqual(STAFFLINE_RETENTION_MIN, 0.60)


class BugCMetricsFieldTest(unittest.TestCase):
    """Bug C 新增 metrics 字段的默认值与类型契约。"""

    def test_defaults_are_null_safe(self):
        metrics = build_metrics()
        self.assertIsNone(metrics["staffline_thickness_px"])
        self.assertIsNone(metrics["staffline_energy_in"])
        self.assertIsNone(metrics["staffline_energy_out"])
        self.assertIsNone(metrics["staffline_retention"])
        self.assertEqual(metrics["denoise_strength_applied"], 0)
        self.assertIsInstance(metrics["denoise_strength_applied"], int)

    def test_values_are_coerced(self):
        metrics = build_metrics(
            staffline_thickness_px="1", denoise_strength_applied="5",
            staffline_energy_in=0.02, staffline_energy_out=0.01,
            staffline_retention_ratio=0.5)
        self.assertEqual(metrics["staffline_thickness_px"], 1.0)
        self.assertEqual(metrics["denoise_strength_applied"], 5)
        self.assertAlmostEqual(metrics["staffline_retention"], 0.5)

    def test_bad_denoise_applied_falls_back_to_zero(self):
        self.assertEqual(
            build_metrics(denoise_strength_applied=None)[
                "denoise_strength_applied"], 0)
        self.assertEqual(
            build_metrics(denoise_strength_applied="x")[
                "denoise_strength_applied"], 0)

    def test_staffline_timing_key_exists(self):
        """新增的测量步骤必须进 TIMING_STEPS，否则会被静默丢弃并告警。"""
        self.assertIn("staffline", TIMING_STEPS)
        metrics = build_metrics(steps_timing_ms={"staffline": 2.0})
        self.assertEqual(metrics["steps_timing_ms"]["staffline"], 2.0)
        self.assertEqual(metrics["warnings"], [])


class MathSanityTest(unittest.TestCase):
    """确保测试文件本身依赖的数学假设成立（防止误报）。"""

    def test_nan_is_not_comparable(self):
        self.assertTrue(math.isnan(float("nan")))


if __name__ == "__main__":
    unittest.main()
