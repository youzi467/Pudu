# -*- coding: utf-8 -*-
"""P0-2 omr_pipeline 参数透传单元测试（**不需要 opencv / 不调真 oemer**）。

覆盖需求：

* **R-P0-03 透明代理**：任意参数组合下，转发给 ``omr_oemer.py`` 的 argv
  与"不开预处理时的基准 argv"**仅在 input 位置不同**，其余顺序/取值完全一致。
* **R-P0-04 out_path 陷阱**：1 个位置参数调用时，转发 argv 必须含**显式**
  out_path，且其值 == 与**原始 input** 同目录同 stem 的 ``.musicxml``
  （与 ``omr_oemer.py:754-765`` 的推导逐字对齐）；2 参时原样透传。
* **P1-02 私有 flag 隔离**：``--preprocess-config`` / ``--preprocess-preset``
  / ``--preprocess-metrics`` / ``--keep-temp`` / ``--no-preprocess``
  绝不出现在下游 argv。
* **P1-03 前向兼容**：任何未知 ``-`` 开头 token 原样转发。
"""

import os
import sys
import tempfile
import shutil
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import omr_preprocess  # noqa: E402
import omr_pipeline  # noqa: E402
from omr_pipeline import (  # noqa: E402
    ArgError, build_downstream_cmd, downstream_script_path,
    metrics_sidecar_path, parse_args, resolve_out_path, split_args,
)


def oemer_reference_out_path(positional):
    """``omr_oemer.py:754-765`` 的 out_path 推导（独立复刻，用于交叉验证）。"""
    in_path = positional[0]
    if len(positional) >= 2:
        return positional[1]
    in_abs = os.path.abspath(in_path)
    stem = os.path.splitext(os.path.basename(in_abs))[0]
    return os.path.join(os.path.dirname(in_abs), stem + ".musicxml")


class SplitArgsTest(unittest.TestCase):
    """三集合拆分。"""

    def test_bare_positional(self):
        positional, private, passthrough = split_args(["in.png"])
        self.assertEqual(positional, ["in.png"])
        self.assertEqual(passthrough, [])
        self.assertIsNone(private["config_path"])
        self.assertFalse(private["keep_temp"])
        self.assertFalse(private["no_preprocess"])

    def test_two_positionals(self):
        positional, _private, passthrough = split_args(["in.png", "out.musicxml"])
        self.assertEqual(positional, ["in.png", "out.musicxml"])
        self.assertEqual(passthrough, [])

    def test_private_value_flags_space_form(self):
        _pos, private, passthrough = split_args([
            "in.png",
            "--preprocess-config", "cfg.json",
            "--preprocess-preset", "photo",
            "--preprocess-metrics", "m.json"])
        self.assertEqual(private["config_path"], "cfg.json")
        self.assertEqual(private["preset"], "photo")
        self.assertEqual(private["metrics_path"], "m.json")
        self.assertEqual(passthrough, [])

    def test_private_value_flags_equals_form(self):
        _pos, private, passthrough = split_args([
            "in.png",
            "--preprocess-config=cfg.json",
            "--preprocess-preset=scan",
            "--preprocess-metrics=m.json"])
        self.assertEqual(private["config_path"], "cfg.json")
        self.assertEqual(private["preset"], "scan")
        self.assertEqual(private["metrics_path"], "m.json")
        self.assertEqual(passthrough, [])

    def test_private_bool_flags(self):
        _pos, private, passthrough = split_args(
            ["in.png", "--keep-temp", "--no-preprocess"])
        self.assertTrue(private["keep_temp"])
        self.assertTrue(private["no_preprocess"])
        self.assertEqual(passthrough, [])

    def test_missing_value_raises(self):
        for argv in (["in.png", "--preprocess-config"],
                     ["in.png", "--preprocess-preset"],
                     ["in.png", "--preprocess-metrics"],
                     ["in.png", "--preprocess-config="]):
            with self.assertRaises(ArgError, msg=str(argv)):
                split_args(argv)

    def test_gt_value_is_not_mistaken_for_positional(self):
        positional, _private, passthrough = split_args(
            ["in.png", "--gt", "gt.musicxml"])
        self.assertEqual(positional, ["in.png"])
        self.assertEqual(passthrough, ["--gt", "gt.musicxml"])

    def test_gt_missing_value_raises(self):
        with self.assertRaises(ArgError):
            split_args(["in.png", "--gt"])

    def test_gt_equals_form_passthrough(self):
        positional, _private, passthrough = split_args(["in.png", "--gt=gt.xml"])
        self.assertEqual(positional, ["in.png"])
        self.assertEqual(passthrough, ["--gt=gt.xml"])

    def test_downstream_bool_flags_passthrough(self):
        _pos, _private, passthrough = split_args(
            ["in.png", "--f3-geometric", "--no-f3-sidecar"])
        self.assertEqual(passthrough, ["--f3-geometric", "--no-f3-sidecar"])

    def test_unknown_flags_are_forwarded(self):
        """P1-03 前向兼容：omr_oemer.py 以后新增 flag 无需改本文件。"""
        _pos, _private, passthrough = split_args(
            ["in.png", "--brand-new-flag", "-x", "--another=1"])
        self.assertEqual(passthrough, ["--brand-new-flag", "-x", "--another=1"])

    def test_order_is_preserved(self):
        _pos, _private, passthrough = split_args([
            "in.png", "--f3-geometric", "--gt", "g.xml",
            "--keep-temp", "--no-f3-sidecar", "--zzz"])
        self.assertEqual(passthrough,
                         ["--f3-geometric", "--gt", "g.xml",
                          "--no-f3-sidecar", "--zzz"])

    def test_interleaved_private_and_downstream(self):
        positional, private, passthrough = split_args([
            "--preprocess-preset", "photo", "in.png", "--gt", "g.xml",
            "out.musicxml", "--f3-geometric", "--keep-temp"])
        self.assertEqual(positional, ["in.png", "out.musicxml"])
        self.assertEqual(private["preset"], "photo")
        self.assertTrue(private["keep_temp"])
        self.assertEqual(passthrough, ["--gt", "g.xml", "--f3-geometric"])


class ParseArgsTest(unittest.TestCase):
    def test_no_positional_raises(self):
        with self.assertRaises(ArgError):
            parse_args([])
        with self.assertRaises(ArgError):
            parse_args(["--keep-temp"])

    def test_too_many_positionals_raises(self):
        with self.assertRaises(ArgError):
            parse_args(["a.png", "b.musicxml", "c"])


class ResolveOutPathTest(unittest.TestCase):
    """R-P0-04：与 omr_oemer.py:754-765 逐字对齐。"""

    def test_two_positionals_uses_second_verbatim(self):
        self.assertEqual(resolve_out_path(["in.png", "weird/out.musicxml"]),
                         "weird/out.musicxml")

    def test_one_positional_derives_sibling_musicxml(self):
        for raw in ("data/river_1.jpg", "in.png", "./x/y.jpeg",
                    "C:/tmp/a b/c.d.png"):
            self.assertEqual(resolve_out_path([raw]),
                             oemer_reference_out_path([raw]), raw)

    def test_derived_path_is_absolute_sibling(self):
        derived = resolve_out_path(["data/river_1.jpg"])
        self.assertTrue(os.path.isabs(derived))
        self.assertEqual(os.path.basename(derived), "river_1.musicxml")
        self.assertEqual(os.path.dirname(derived),
                         os.path.dirname(os.path.abspath("data/river_1.jpg")))

    def test_empty_raises(self):
        with self.assertRaises(ArgError):
            resolve_out_path([])


class BuildDownstreamCmdTest(unittest.TestCase):
    def test_always_two_positionals(self):
        cmd = build_downstream_cmd("py", "s.py", "in.png", "out.musicxml", [])
        self.assertEqual(cmd, ["py", "s.py", "in.png", "out.musicxml"])

    def test_passthrough_appended_in_order(self):
        cmd = build_downstream_cmd("py", "s.py", "i", "o",
                                   ["--gt", "g", "--f3-geometric"])
        self.assertEqual(cmd, ["py", "s.py", "i", "o",
                               "--gt", "g", "--f3-geometric"])

    def test_downstream_script_is_omr_oemer_next_to_pipeline(self):
        script = downstream_script_path()
        self.assertTrue(os.path.isabs(script))
        self.assertEqual(os.path.basename(script), "omr_oemer.py")
        self.assertTrue(os.path.isfile(script), "omr_oemer.py 必须存在且未被改名")
        self.assertEqual(os.path.dirname(script),
                         os.path.dirname(os.path.abspath(omr_pipeline.__file__)))


class MetricsSidecarPathTest(unittest.TestCase):
    def test_musicxml_suffix_replaced(self):
        self.assertEqual(metrics_sidecar_path("a/b.musicxml"),
                         "a/b.preprocess.json")

    def test_non_musicxml_gets_suffix_appended(self):
        self.assertEqual(metrics_sidecar_path("a/b"), "a/b.preprocess.json")

    def test_same_family_as_geometry_sidecar(self):
        out = "d/river_1.musicxml"
        self.assertEqual(metrics_sidecar_path(out), "d/river_1.preprocess.json")
        self.assertEqual(out.replace(".musicxml", ".geometry.json"),
                         "d/river_1.geometry.json")


class _CmdCapture:
    """假 runner：只记录 argv，不真的起子进程。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        return self.returncode, self.stdout, self.stderr

    @property
    def last(self):
        return self.calls[-1]


class ForwardedArgvTest(unittest.TestCase):
    """R-P0-03 / P1-02：转发 argv 的逐项等价性。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pudu_argv_test_")
        self.src = os.path.join(self._tmp, "river_1.png")
        with open(self.src, "wb") as handle:
            handle.write(b"fake-image-bytes")
        self.gt = os.path.join(self._tmp, "gt.musicxml")
        with open(self.gt, "w", encoding="utf-8") as handle:
            handle.write("<score-partwise/>")
        # 用桩替换真实增强，彻底脱离 cv2
        self._saved_preprocess = omr_preprocess.preprocess_for_omr
        omr_preprocess.preprocess_for_omr = self._stub_preprocess

    def tearDown(self):
        omr_preprocess.preprocess_for_omr = self._saved_preprocess
        shutil.rmtree(self._tmp, ignore_errors=True)

    @staticmethod
    def _stub_preprocess(src, dst, cfg=None):
        """假增强：写一个占位文件，返回 ok 的 metrics。"""
        with open(dst, "wb") as handle:
            handle.write(b"enhanced-png-bytes")
        return omr_preprocess.build_metrics(
            ok=True, degraded=False, src=src, dst=dst,
            config=(cfg or omr_preprocess.PreprocessConfig()).to_dict(),
            size_in=[100, 50], size_out=[100, 50], ink_ratio_out=0.05)

    def _forward(self, argv):
        """跑一次 pipeline，返回 (rc, 下游 argv)。"""
        capture = _CmdCapture()
        rc = omr_pipeline.run(argv, runner=capture)
        return rc, capture.last

    def _baseline(self, in_path, out_path, passthrough):
        return [sys.executable, downstream_script_path(), in_path, out_path] \
            + list(passthrough)

    # -- 只有 input 位置不同 ------------------------------------------------

    def test_only_input_position_differs_from_baseline(self):
        out = os.path.join(self._tmp, "out.musicxml")
        combos = [
            ([self.src, out], []),
            ([self.src, out, "--f3-geometric"], ["--f3-geometric"]),
            ([self.src, out, "--gt", self.gt], ["--gt", self.gt]),
            ([self.src, out, "--gt=" + self.gt, "--no-f3-sidecar"],
             ["--gt=" + self.gt, "--no-f3-sidecar"]),
            ([self.src, out, "--f3-geometric", "--gt", self.gt,
              "--no-f3-sidecar", "--future-flag"],
             ["--f3-geometric", "--gt", self.gt,
              "--no-f3-sidecar", "--future-flag"]),
        ]
        for argv, passthrough in combos:
            _rc, cmd = self._forward(argv)
            expected = self._baseline(cmd[2], out, passthrough)
            self.assertEqual(cmd, expected, f"argv={argv}")
            # input 位置必须是临时增强图，其余逐项与基准一致
            self.assertNotEqual(cmd[2], self.src)
            self.assertTrue(cmd[2].endswith("river_1.pre.png"), cmd[2])

    def test_no_preprocess_forwards_original_input(self):
        out = os.path.join(self._tmp, "out.musicxml")
        _rc, cmd = self._forward([self.src, out, "--no-preprocess",
                                  "--f3-geometric"])
        self.assertEqual(cmd, self._baseline(self.src, out, ["--f3-geometric"]))

    # -- R-P0-04 --------------------------------------------------------

    def test_single_positional_gets_explicit_out_path(self):
        _rc, cmd = self._forward([self.src])
        self.assertEqual(len(cmd) - 2, 2, "必须恰好 2 个位置参数")
        self.assertEqual(cmd[3], oemer_reference_out_path([self.src]))
        self.assertEqual(cmd[3], os.path.join(self._tmp, "river_1.musicxml"))
        # 关键：out_path 由**原始 input** 推导，而非临时增强图
        self.assertNotIn("river_1.pre", cmd[3])

    def test_two_positionals_are_passed_through_verbatim(self):
        out = os.path.join(self._tmp, "custom name.musicxml")
        _rc, cmd = self._forward([self.src, out])
        self.assertEqual(cmd[3], out)

    def test_out_path_identical_with_and_without_preprocess(self):
        _rc, with_pre = self._forward([self.src])
        _rc2, without_pre = self._forward([self.src, "--no-preprocess"])
        self.assertEqual(with_pre[3], without_pre[3])
        self.assertEqual(without_pre[2], self.src)

    # -- P1-02 私有 flag 隔离 ----------------------------------------------

    def test_private_flags_never_reach_downstream(self):
        out = os.path.join(self._tmp, "out.musicxml")
        cfg_json = os.path.join(self._tmp, "cfg.json")
        with open(cfg_json, "w", encoding="utf-8") as handle:
            handle.write("{}")
        argv = [self.src, out,
                "--preprocess-config", cfg_json,
                "--preprocess-preset", "photo",
                "--preprocess-metrics", os.path.join(self._tmp, "m.json"),
                "--keep-temp", "--no-preprocess",
                "--gt", self.gt, "--f3-geometric"]
        _rc, cmd = self._forward(argv)
        forbidden = ("--preprocess-config", "--preprocess-preset",
                     "--preprocess-metrics", "--keep-temp", "--no-preprocess",
                     "photo", cfg_json)
        for token in forbidden:
            self.assertNotIn(token, cmd, f"私有 token 泄漏到下游: {token}")
        self.assertEqual(cmd, self._baseline(self.src, out,
                                             ["--gt", self.gt, "--f3-geometric"]))

    def test_private_flags_equals_form_never_reach_downstream(self):
        out = os.path.join(self._tmp, "out.musicxml")
        argv = [self.src, out, "--preprocess-preset=scan",
                "--preprocess-config=" + os.path.join(self._tmp, "nope.json"),
                "--no-f3-sidecar"]
        _rc, cmd = self._forward(argv)
        self.assertEqual(cmd, self._baseline(cmd[2], out, ["--no-f3-sidecar"]))
        for token in cmd:
            self.assertFalse(token.startswith("--preprocess-"), token)

    # -- 退出码 ------------------------------------------------------------

    def test_rc_is_forwarded(self):
        out = os.path.join(self._tmp, "out.musicxml")
        for code in (0, 1, 2, 7, 255):
            capture = _CmdCapture(returncode=code)
            self.assertEqual(omr_pipeline.run([self.src, out], runner=capture),
                             code)

    def test_bad_args_return_2(self):
        capture = _CmdCapture()
        self.assertEqual(omr_pipeline.run([], runner=capture), 2)
        self.assertEqual(omr_pipeline.run(["--preprocess-config"], runner=capture), 2)
        self.assertEqual(omr_pipeline.run([self.src, "a", "b", "c"],
                                          runner=capture), 2)
        self.assertEqual(capture.calls, [], "参数错误时不得触发下游")

    def test_missing_input_returns_1(self):
        capture = _CmdCapture()
        rc = omr_pipeline.run([os.path.join(self._tmp, "nope.png")],
                              runner=capture)
        self.assertEqual(rc, 1)
        self.assertEqual(capture.calls, [], "输入不存在时不得触发下游")


if __name__ == "__main__":
    unittest.main()
