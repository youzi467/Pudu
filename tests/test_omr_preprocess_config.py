# -*- coding: utf-8 -*-
"""P0-2 预处理配置加载单元测试（纯 stdlib，**不需要 opencv**）。

覆盖需求：

* **R-P0-06 配置健壮性**：4 种异常场景（文件不存在 / JSON 损坏 /
  顶层非 object / 缺字段）都必须返回合法 config 且**不抛异常**。
* **R-P0-08 延迟导入**：``import omr_preprocess`` / ``import omr_pipeline``
  之后 ``"cv2" not in sys.modules``（否则无 cv2 的环境会直接崩）。
* **单一真源**：``tools/omr_preprocess_config.json`` 的 ``default`` 段与
  代码 ``DEFAULTS`` 逐字段、逐类型一致；``presets`` 与代码 ``PRESETS`` 一致。
"""

import copy
import importlib
import json
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

import omr_preprocess  # noqa: E402
from omr_preprocess import (  # noqa: E402
    DEFAULTS, PRESETS, CONFIG_ENV_VAR, PreprocessConfig,
    default_config_path, load_config,
)


def _read_repo_config():
    """读取仓库内置配置 JSON。"""
    with open(default_config_path(), "r", encoding="utf-8") as handle:
        return json.load(handle)


class LazyImportTest(unittest.TestCase):
    """R-P0-08：模块顶层不得 import cv2 / numpy。

    断言口径是**增量**而非全局快照：全量 ``pytest tests/`` 的同一 session 里，
    前置用例（走 cv2 的集成测试）早就把 cv2/numpy 塞进了 ``sys.modules``，
    直接断言「当前不存在」会与被测代码无关地误报。
    :func:`_purity_probe.assert_import_is_pure` 摘掉缓存后重新真导一次，
    只追究**本次导入**拉进来的重型库。
    """

    WATCHED = ("cv2", "numpy")

    def test_importing_omr_preprocess_does_not_pull_cv2(self):
        self.assertIn("omr_preprocess", sys.modules)
        assert_import_is_pure(self, "omr_preprocess", self.WATCHED)

    def test_importing_omr_pipeline_does_not_pull_cv2(self):
        importlib.import_module("omr_pipeline")
        assert_import_is_pure(self, "omr_pipeline", self.WATCHED)

    def test_importing_as_tools_package_does_not_pull_cv2(self):
        """以 ``tools.xxx`` 命名空间包形式导入同样不得触发 cv2。"""
        importlib.import_module("tools.omr_preprocess")
        importlib.import_module("tools.omr_pipeline")
        assert_import_is_pure(
            self, ("tools.omr_preprocess", "tools.omr_pipeline"), ("cv2",))

    def test_source_has_no_toplevel_cv2_import(self):
        """静态检查：源文件里 cv2/numpy 的 import 必须有缩进（在函数内）。"""
        for name in ("omr_preprocess.py", "omr_pipeline.py"):
            path = os.path.join(TOOLS, name)
            with open(path, "r", encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    if line[:1] in (" ", "\t"):
                        continue                      # 有缩进 = 在函数体内
                    if line.startswith(("import cv2", "import numpy",
                                        "from cv2", "from numpy")):
                        self.fail(f"{name}:{lineno} 存在顶层 cv2/numpy import")


class DefaultsSingleSourceTest(unittest.TestCase):
    """DEFAULTS / dataclass / JSON 三者必须完全一致。"""

    def test_dataclass_defaults_match_defaults_dict(self):
        self.assertEqual(PreprocessConfig().to_dict(), DEFAULTS)

    def test_dataclass_field_order_matches_defaults(self):
        self.assertEqual(list(PreprocessConfig().to_dict().keys()),
                         list(DEFAULTS.keys()))

    def test_json_default_section_matches_defaults_dict(self):
        data = _read_repo_config()
        self.assertIn("default", data)
        section = data["default"]
        self.assertEqual(set(section.keys()), set(DEFAULTS.keys()),
                         "JSON default 段的键集合必须与代码 DEFAULTS 一致")
        for key, expected in DEFAULTS.items():
            actual = section[key]
            self.assertEqual(type(actual), type(expected),
                             f"JSON default.{key} 类型不符: "
                             f"{type(actual).__name__} != {type(expected).__name__}")
            self.assertEqual(actual, expected, f"JSON default.{key} 取值不符")

    def test_json_presets_match_code_presets(self):
        data = _read_repo_config()
        self.assertEqual(set(data.get("presets", {}).keys()), set(PRESETS.keys()))
        for name, expected in PRESETS.items():
            self.assertEqual(data["presets"][name], expected,
                             f"JSON presets.{name} 与代码 PRESETS 不一致")

    def test_preset_keys_are_known_config_fields(self):
        for name, section in PRESETS.items():
            for key in section:
                self.assertIn(key, DEFAULTS, f"PRESETS[{name}] 含未知键 {key}")


class LoadConfigRobustnessTest(unittest.TestCase):
    """R-P0-06：4 种异常场景都不许抛，且必须返回合法 config。"""

    def setUp(self):
        self._saved_env = os.environ.pop(CONFIG_ENV_VAR, None)
        self._tmp = tempfile.mkdtemp(prefix="pudu_cfg_test_")

    def tearDown(self):
        if self._saved_env is not None:
            os.environ[CONFIG_ENV_VAR] = self._saved_env
        else:
            os.environ.pop(CONFIG_ENV_VAR, None)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self._tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _assert_valid(self, cfg):
        self.assertIsInstance(cfg, PreprocessConfig)
        self.assertEqual(set(cfg.to_dict().keys()), set(DEFAULTS.keys()))
        self.assertIn(cfg.binarize_method, ("adaptive", "otsu", "none"))
        self.assertEqual(cfg.block_size % 2, 1)
        self.assertGreaterEqual(cfg.block_size, 3)
        self.assertEqual(cfg.shadow_kernel_px % 2, 1)
        self.assertTrue(cfg.denoise_strength == 0 or cfg.denoise_strength % 2 == 1)
        self.assertGreater(cfg.max_deskew_deg, 0.0)
        self.assertLess(cfg.min_deskew_deg, cfg.max_deskew_deg)

    # -- 场景 1：文件不存在 ------------------------------------------------

    def test_missing_file_does_not_raise(self):
        cfg, source, warnings = load_config(
            os.path.join(self._tmp, "definitely_missing.json"))
        self._assert_valid(cfg)
        self.assertTrue(any("不存在" in w for w in warnings), warnings)
        self.assertIsInstance(source, str)

    def test_all_sources_missing_falls_back_to_builtin_defaults(self):
        saved = omr_preprocess.default_config_path
        try:
            omr_preprocess.default_config_path = lambda: os.path.join(
                self._tmp, "nope.json")
            cfg, source, warnings = load_config(
                os.path.join(self._tmp, "also_missing.json"))
            self._assert_valid(cfg)
            self.assertEqual(source, "builtin-defaults")
            self.assertEqual(cfg.to_dict(), DEFAULTS)
        finally:
            omr_preprocess.default_config_path = saved

    # -- 场景 2：JSON 损坏 -------------------------------------------------

    def test_broken_json_does_not_raise(self):
        path = self._write("broken.json", '{"default": {"C": 10,,,}')
        cfg, _source, warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertTrue(any("解析失败" in w for w in warnings), warnings)

    def test_empty_file_does_not_raise(self):
        path = self._write("empty.json", "")
        cfg, _source, warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertTrue(warnings)

    # -- 场景 3：顶层非 object ---------------------------------------------

    def test_toplevel_array_does_not_raise(self):
        path = self._write("array.json", "[1, 2, 3]")
        cfg, _source, warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertTrue(any("顶层不是 JSON object" in w for w in warnings), warnings)

    def test_toplevel_scalar_does_not_raise(self):
        path = self._write("scalar.json", '"hello"')
        cfg, _source, warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertTrue(any("顶层不是 JSON object" in w for w in warnings), warnings)

    # -- 场景 4：缺字段 ----------------------------------------------------

    def test_missing_fields_filled_with_defaults(self):
        path = self._write("partial.json",
                           json.dumps({"default": {"clahe_clip_limit": 4.0}}))
        cfg, source, _warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertEqual(cfg.clahe_clip_limit, 4.0)
        expected = dict(DEFAULTS)
        expected["clahe_clip_limit"] = 4.0
        self.assertEqual(cfg.to_dict(), expected)
        self.assertTrue(source.startswith("cli:"))

    def test_flat_form_is_supported(self):
        path = self._write("flat.json", json.dumps({"block_size": 31, "C": 7}))
        cfg, _source, _warnings = load_config(path)
        self.assertEqual(cfg.block_size, 31)
        self.assertEqual(cfg.C, 7)
        self.assertEqual(cfg.enable_contrast_norm, DEFAULTS["enable_contrast_norm"])

    # -- 其它容错 ----------------------------------------------------------

    def test_unknown_keys_are_ignored_with_warning(self):
        path = self._write("unknown.json",
                           json.dumps({"default": {"no_such_key": 1, "C": 5}}))
        cfg, _source, warnings = load_config(path)
        self.assertEqual(cfg.C, 5)
        self.assertFalse(hasattr(cfg, "no_such_key"))
        self.assertTrue(any("no_such_key" in w for w in warnings), warnings)

    def test_type_mismatch_falls_back_to_default(self):
        path = self._write("badtype.json", json.dumps({
            "default": {"clahe_clip_limit": "not-a-number",
                        "enable_deskew": "yes",
                        "block_size": "31"}}))
        cfg, _source, warnings = load_config(path)
        # 无法安全转换 -> 取默认
        self.assertEqual(cfg.clahe_clip_limit, DEFAULTS["clahe_clip_limit"])
        # 可安全转换 -> 采用转换结果
        self.assertTrue(cfg.enable_deskew)
        self.assertEqual(cfg.block_size, 31)
        self.assertTrue(any("clahe_clip_limit" in w for w in warnings), warnings)

    def test_out_of_range_values_are_clamped(self):
        path = self._write("range.json", json.dumps({"default": {
            "clahe_clip_limit": 99.0,
            "clahe_tile_grid": 999,
            "shadow_kernel_px": 4,
            "denoise_strength": 100,
            "block_size": 2,
            "C": -900,
            "max_deskew_deg": 999.0,
            "border_margin_px": 9999,
            "max_long_side_px": 99999,
        }}))
        cfg, _source, warnings = load_config(path)
        self._assert_valid(cfg)
        self.assertEqual(cfg.clahe_clip_limit, 8.0)
        self.assertEqual(cfg.clahe_tile_grid, 32)
        self.assertEqual(cfg.shadow_kernel_px, 5)   # 4 -> 奇数 5
        self.assertEqual(cfg.denoise_strength, 9)
        self.assertEqual(cfg.block_size, 3)
        self.assertEqual(cfg.C, -50)
        self.assertEqual(cfg.max_deskew_deg, 15.0)
        self.assertEqual(cfg.border_margin_px, 200)
        self.assertEqual(cfg.max_long_side_px, 8000)
        self.assertTrue(warnings)

    def test_illegal_binarize_method_falls_back_to_adaptive(self):
        path = self._write("bm.json",
                           json.dumps({"default": {"binarize_method": "magic"}}))
        cfg, _source, warnings = load_config(path)
        self.assertEqual(cfg.binarize_method, "adaptive")
        self.assertTrue(any("binarize_method" in w for w in warnings), warnings)

    def test_min_deskew_not_less_than_max_is_clamped(self):
        path = self._write("deskew.json", json.dumps({"default": {
            "max_deskew_deg": 2.0, "min_deskew_deg": 5.0}}))
        cfg, _source, warnings = load_config(path)
        self.assertLess(cfg.min_deskew_deg, cfg.max_deskew_deg)
        self.assertTrue(any("min_deskew_deg" in w for w in warnings), warnings)

    # -- 优先级与档位 -------------------------------------------------------

    def test_env_var_is_second_priority(self):
        path = self._write("env.json", json.dumps({"default": {"C": 42}}))
        os.environ[CONFIG_ENV_VAR] = path
        try:
            cfg, source, _warnings = load_config(None)
            self.assertEqual(cfg.C, 42)
            self.assertTrue(source.startswith("env:"))
        finally:
            os.environ.pop(CONFIG_ENV_VAR, None)

    def test_cli_path_beats_env_var(self):
        env_path = self._write("env2.json", json.dumps({"default": {"C": 42}}))
        cli_path = self._write("cli2.json", json.dumps({"default": {"C": 7}}))
        os.environ[CONFIG_ENV_VAR] = env_path
        try:
            cfg, source, _warnings = load_config(cli_path)
            self.assertEqual(cfg.C, 7)
            self.assertTrue(source.startswith("cli:"))
        finally:
            os.environ.pop(CONFIG_ENV_VAR, None)

    def test_repo_config_is_third_priority(self):
        cfg, source, _warnings = load_config(None)
        self.assertTrue(source.startswith("repo:"), source)
        self.assertEqual(cfg.to_dict(), DEFAULTS)

    def test_preset_scan_layer_applied(self):
        cfg, _source, _warnings = load_config(None, preset="scan")
        self.assertEqual(cfg.preset, "scan")
        self.assertFalse(cfg.enable_shadow_suppress)
        self.assertEqual(cfg.binarize_method, "otsu")
        self.assertEqual(cfg.denoise_strength, 3)
        self.assertFalse(cfg.enable_deskew)

    def test_preset_photo_layer_applied(self):
        cfg, _source, _warnings = load_config(None, preset="photo")
        self.assertEqual(cfg.preset, "photo")
        self.assertEqual(cfg.shadow_kernel_px, 41)
        self.assertEqual(cfg.block_size, 31)
        self.assertEqual(cfg.C, 12)
        self.assertTrue(cfg.enable_deskew)
        self.assertEqual(cfg.max_deskew_deg, 2.0)

    def test_preset_low_contrast_layer_applied(self):
        cfg, _source, _warnings = load_config(None, preset="low_contrast")
        self.assertEqual(cfg.preset, "low_contrast")
        self.assertEqual(cfg.clahe_clip_limit, 3.0)
        self.assertEqual(cfg.block_size, 21)
        self.assertEqual(cfg.C, 6)

    def test_unknown_preset_falls_back_to_default(self):
        cfg, _source, warnings = load_config(None, preset="no_such_preset")
        self.assertEqual(cfg.preset, "default")
        self.assertEqual(cfg.to_dict(), DEFAULTS)
        self.assertTrue(any("no_such_preset" in w for w in warnings), warnings)

    def test_active_preset_in_file_is_honoured(self):
        path = self._write("active.json", json.dumps({
            "active_preset": "scan",
            "default": {},
            "presets": {"scan": {"C": 33}}}))
        cfg, _source, _warnings = load_config(path)
        self.assertEqual(cfg.preset, "scan")
        self.assertEqual(cfg.C, 33)                 # 文件 presets 覆盖代码 PRESETS
        self.assertEqual(cfg.binarize_method, "otsu")  # 代码 PRESETS 仍生效

    def test_cli_preset_beats_active_preset(self):
        path = self._write("active2.json", json.dumps({
            "active_preset": "scan", "default": {}, "presets": {}}))
        cfg, _source, _warnings = load_config(path, preset="photo")
        self.assertEqual(cfg.preset, "photo")
        self.assertEqual(cfg.shadow_kernel_px, 41)

    def test_defaults_dict_is_not_mutated_by_load(self):
        snapshot = copy.deepcopy(DEFAULTS)
        load_config(None, preset="photo")
        load_config(None, preset="scan")
        self.assertEqual(DEFAULTS, snapshot)


if __name__ == "__main__":
    unittest.main()
