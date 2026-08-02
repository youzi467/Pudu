# -*- coding: utf-8 -*-
"""P0-2 omr_pipeline 端到端桩测试（**不需要 opencv / 不调真 oemer**）。

通过注入假 ``runner``（替身下游）与可控的增强桩/异常，验证主流程：

1. 增强成功 -> 下游 input == 临时增强 PNG；
2. 预处理异常 / 无 cv2 / 非图像输入 / ``--no-preprocess`` / no-op 配置
   -> 降级，下游 input == **原始 input**（fail-open 红线）；
3. 临时目录成功后被删除；``--keep-temp`` 时保留并在 stderr 打印路径；
4. ``.preprocess.json`` 写出且 schema 完整；``--preprocess-metrics`` 可改落点；
5. 下游 rc 原样透传；stdout/stderr 原样转发且本脚本诊断只走 stderr。
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import omr_preprocess  # noqa: E402
import omr_pipeline  # noqa: E402


class _Runner:
    """假下游：记录 argv，可选地伪造产物与 rc/stdout/stderr。"""

    def __init__(self, returncode=0, stdout="", stderr="", emit_out=False):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.emit_out = emit_out

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.emit_out and len(cmd) >= 4:
            with open(cmd[3], "w", encoding="utf-8") as handle:
                handle.write("<score-partwise version=\"4.0\"/>")
        return self.returncode, self.stdout, self.stderr

    @property
    def last(self):
        return self.calls[-1]

    @property
    def last_input(self):
        return self.calls[-1][2]

    @property
    def last_output(self):
        return self.calls[-1][3]


class PipelineE2EStubTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pudu_e2e_test_")
        self.src = os.path.join(self.tmp, "river_1.png")
        with open(self.src, "wb") as handle:
            handle.write(b"fake-image-bytes")
        self.out = os.path.join(self.tmp, "river_1.musicxml")
        self.enhanced_paths = []
        self._saved_preprocess = omr_preprocess.preprocess_for_omr
        self._saved_lazy = omr_preprocess._lazy_cv2

    def tearDown(self):
        omr_preprocess.preprocess_for_omr = self._saved_preprocess
        omr_preprocess._lazy_cv2 = self._saved_lazy
        for path in self.enhanced_paths:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- 桩 ----------------------------------------------------------------

    def _install_success_stub(self):
        """把增强替换成"写占位文件 + 返回 ok metrics"。"""
        recorded = self.enhanced_paths

        def _stub(src, dst, cfg=None):
            with open(dst, "wb") as handle:
                handle.write(b"enhanced-png-bytes")
            recorded.append(dst)
            return omr_preprocess.build_metrics(
                ok=True, degraded=False, src=src, dst=dst,
                config=(cfg or omr_preprocess.PreprocessConfig()).to_dict(),
                size_in=[1000, 700], size_out=[1000, 700],
                mean_intensity_in=180.0, mean_intensity_out=230.0,
                mean_contrast_in=40.0, mean_contrast_out=90.0,
                binarize_method="adaptive", ink_ratio_out=0.06,
                steps_timing_ms={"read": 3.0, "write": 4.0}, total_ms=20.0)

        omr_preprocess.preprocess_for_omr = _stub

    def _install_no_cv2(self):
        """让 _lazy_cv2 抛 ImportError，走真实 fail-open 分支。"""
        def _boom():
            raise ImportError("No module named 'cv2'")
        omr_preprocess._lazy_cv2 = _boom

    def _install_raising_stub(self):
        """让增强直接抛异常（验证 pipeline 自己也兜得住）。"""
        def _stub(src, dst, cfg=None):
            raise RuntimeError("模拟增强炸了")
        omr_preprocess.preprocess_for_omr = _stub

    def _run(self, argv, runner):
        """跑一次 pipeline 并捕获 stdout/stderr。"""
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = omr_pipeline.run(argv, runner=runner)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def _read_metrics(self, path=None):
        target = path or omr_pipeline.metrics_sidecar_path(self.out)
        self.assertTrue(os.path.isfile(target), f"metrics sidecar 未写出: {target}")
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # -- ① 增强成功 --------------------------------------------------------

    def test_success_forwards_temp_png(self):
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        rc, _stdout, _stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 0)
        forwarded = runner.last_input
        self.assertNotEqual(forwarded, self.src)
        self.assertTrue(forwarded.endswith("river_1.pre.png"), forwarded)
        self.assertIn(omr_pipeline.TEMP_DIR_PREFIX, forwarded)
        self.assertEqual(runner.last_output, self.out)

    def test_success_metrics_ok(self):
        self._install_success_stub()
        self._run([self.src, self.out], _Runner(emit_out=True))
        metrics = self._read_metrics()
        self.assertTrue(metrics["ok"])
        self.assertFalse(metrics["degraded"])
        self.assertEqual(metrics["degrade_reason"], "")

    # -- ② 降级 ------------------------------------------------------------

    def test_no_cv2_degrades_to_original_input(self):
        self._install_no_cv2()
        runner = _Runner(emit_out=True)
        rc, _stdout, stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 0)
        self.assertEqual(runner.last_input, self.src)
        self.assertIn("[警告][preprocess]", stderr)
        metrics = self._read_metrics()
        self.assertFalse(metrics["ok"])
        self.assertTrue(metrics["degraded"])
        self.assertTrue(metrics["degrade_reason"])

    def test_preprocess_exception_degrades_to_original_input(self):
        self._install_raising_stub()
        runner = _Runner(emit_out=True)
        rc, _stdout, _stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 0)
        self.assertEqual(runner.last_input, self.src)
        metrics = self._read_metrics()
        self.assertFalse(metrics["ok"])
        self.assertIn("RuntimeError", metrics["degrade_reason"])

    def test_non_image_input_is_skipped(self):
        pdf = os.path.join(self.tmp, "score.pdf")
        with open(pdf, "wb") as handle:
            handle.write(b"%PDF-1.4")
        out = os.path.join(self.tmp, "score.musicxml")
        self._install_success_stub()          # 即便桩可用也不应被调用
        runner = _Runner(emit_out=True)
        rc, _stdout, _stderr = self._run([pdf, out], runner)
        self.assertEqual(rc, 0)
        self.assertEqual(runner.last_input, pdf)
        self.assertEqual(self.enhanced_paths, [], "非图像输入不得触发增强")
        metrics = self._read_metrics(omr_pipeline.metrics_sidecar_path(out))
        self.assertEqual(metrics["degrade_reason"], "skipped:unsupported_input")

    def test_no_preprocess_flag_is_skipped(self):
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        self._run([self.src, self.out, "--no-preprocess"], runner)
        self.assertEqual(runner.last_input, self.src)
        self.assertEqual(self.enhanced_paths, [])
        self.assertEqual(self._read_metrics()["degrade_reason"],
                         "skipped:no_preprocess_flag")

    def test_noop_config_is_skipped(self):
        cfg_path = os.path.join(self.tmp, "noop.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({"default": {
                "enable_contrast_norm": False,
                "enable_shadow_suppress": False,
                "enable_deskew": False,
                "enable_border_crop": False,
                "denoise_strength": 0,
                "binarize_method": "none",
                "max_long_side_px": 0,
                "upscale_min_long_side_px": 0}}, handle)
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        self._run([self.src, self.out, "--preprocess-config", cfg_path], runner)
        self.assertEqual(runner.last_input, self.src)
        self.assertEqual(self.enhanced_paths, [])
        self.assertEqual(self._read_metrics()["degrade_reason"],
                         "skipped:noop_config")

    # -- ③ 临时目录生命周期 -------------------------------------------------

    def test_temp_dir_removed_after_success(self):
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        self._run([self.src, self.out], runner)
        temp_dir = os.path.dirname(runner.last_input)
        self.assertIn(omr_pipeline.TEMP_DIR_PREFIX, temp_dir)
        self.assertFalse(os.path.exists(temp_dir), "成功后临时目录必须删除")

    def test_temp_dir_removed_even_when_downstream_fails(self):
        self._install_success_stub()
        runner = _Runner(returncode=1)
        rc, _stdout, _stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.dirname(runner.last_input)))

    def test_keep_temp_preserves_dir_and_prints_path(self):
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        _rc, _stdout, stderr = self._run(
            [self.src, self.out, "--keep-temp"], runner)
        temp_dir = os.path.dirname(runner.last_input)
        self.assertTrue(os.path.isdir(temp_dir), "--keep-temp 必须保留临时目录")
        self.assertIn(temp_dir, stderr)
        self.assertIn("--keep-temp", stderr)
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_no_residue_in_output_dir(self):
        """工作区零残留：out_dir 里不得留下 .pre.* 中间产物。"""
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        # 模拟下游崩溃后遗留 <stem>.pre.musicxml / .pre.geometry.json
        residue_xml = os.path.join(self.tmp, "river_1.pre.musicxml")
        residue_geo = os.path.join(self.tmp, "river_1.pre.geometry.json")

        def _runner_leaving_residue(cmd):
            for path in (residue_xml, residue_geo):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("leftover")
            return runner(cmd)

        self._run([self.src, self.out], _runner_leaving_residue)
        self.assertFalse(os.path.exists(residue_xml), "残留 .pre.musicxml 未清理")
        self.assertFalse(os.path.exists(residue_geo), "残留 .pre.geometry.json 未清理")

    # -- ④ metrics sidecar -------------------------------------------------

    def test_metrics_schema_is_complete(self):
        self._install_success_stub()
        self._run([self.src, self.out], _Runner(emit_out=True))
        metrics = self._read_metrics()
        expected = set(omr_preprocess.build_metrics().keys())
        self.assertEqual(set(metrics.keys()), expected)
        self.assertEqual(metrics["schema"], omr_preprocess.METRICS_SCHEMA)
        self.assertEqual(set(metrics["steps_timing_ms"].keys()),
                         set(omr_preprocess.TIMING_STEPS))
        self.assertEqual(set(metrics["config"].keys()),
                         set(omr_preprocess.DEFAULTS.keys()))
        self.assertTrue(metrics["config_source"])
        self.assertIsInstance(metrics["warnings"], list)
        self.assertEqual(metrics["tool_version"], omr_preprocess.TOOL_VERSION)

    def test_metrics_path_follows_geometry_naming_family(self):
        self._install_success_stub()
        self._run([self.src, self.out], _Runner(emit_out=True))
        self.assertTrue(os.path.isfile(
            os.path.join(self.tmp, "river_1.preprocess.json")))

    def test_custom_metrics_path_is_honoured(self):
        self._install_success_stub()
        custom = os.path.join(self.tmp, "sub", "my_metrics.json")
        self._run([self.src, self.out, "--preprocess-metrics", custom],
                  _Runner(emit_out=True))
        self.assertTrue(os.path.isfile(custom))
        self.assertFalse(os.path.exists(
            omr_pipeline.metrics_sidecar_path(self.out)))

    def test_metrics_records_preset(self):
        self._install_success_stub()
        self._run([self.src, self.out, "--preprocess-preset", "photo"],
                  _Runner(emit_out=True))
        metrics = self._read_metrics()
        self.assertEqual(metrics["preset"], "photo")
        self.assertEqual(metrics["config"]["shadow_kernel_px"], 41)

    def test_emit_metrics_sidecar_false_writes_nothing(self):
        cfg_path = os.path.join(self.tmp, "nometrics.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({"default": {"emit_metrics_sidecar": False}}, handle)
        self._install_success_stub()
        self._run([self.src, self.out, "--preprocess-config", cfg_path],
                  _Runner(emit_out=True))
        self.assertFalse(os.path.exists(
            omr_pipeline.metrics_sidecar_path(self.out)))

    # -- ⑤ rc / 流透传 ------------------------------------------------------

    def test_rc_and_streams_are_forwarded(self):
        self._install_success_stub()
        runner = _Runner(returncode=3,
                         stdout="[ok] oemer 产出 MusicXML: x\n",
                         stderr="[警告] 下游告警\n")
        rc, stdout, stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 3)
        self.assertIn("[ok] oemer 产出 MusicXML: x", stdout)
        self.assertIn("[警告] 下游告警", stderr)

    def test_stdout_contains_only_downstream_output(self):
        """stdout 纯净：pipeline 自身诊断一律走 stderr。"""
        self._install_success_stub()
        runner = _Runner(stdout="DOWNSTREAM-ONLY\n", emit_out=True)
        _rc, stdout, stderr = self._run([self.src, self.out], runner)
        self.assertEqual(stdout, "DOWNSTREAM-ONLY\n")
        self.assertIn("[preprocess]", stderr)

    def test_degraded_run_still_forwards_rc(self):
        self._install_no_cv2()
        runner = _Runner(returncode=1)
        rc, _stdout, _stderr = self._run([self.src, self.out], runner)
        self.assertEqual(rc, 1)

    # -- 单参调用（R-P0-04 的端到端形态） ------------------------------------

    def test_single_positional_end_to_end(self):
        self._install_success_stub()
        runner = _Runner(emit_out=True)
        rc, _stdout, _stderr = self._run([self.src], runner)
        self.assertEqual(rc, 0)
        self.assertEqual(runner.last_output, self.out)
        self.assertTrue(runner.last_input.endswith("river_1.pre.png"))
        self.assertTrue(os.path.isfile(self.out))
        self.assertTrue(os.path.isfile(
            os.path.join(self.tmp, "river_1.preprocess.json")))

    # -- ⑥ P3 加固回归（QA 严过关复核提出） ---------------------------------

    def test_sweep_never_deletes_final_output_on_name_collision(self):
        """P3-1：out_path 撞上 <stem>.pre.musicxml 时不得误删正式产物。

        这是最阴险的失效模式——rc 仍是 0，但产物被 finally 里的兜底清扫
        静默删掉。产品入口（C++ 用 <input>.pudu.musicxml）不可达，
        但手工命令行可触发，且一旦触发就是无声的数据丢失。
        """
        self._install_success_stub()
        collide = os.path.join(self.tmp, "river_1.pre.musicxml")
        runner = _Runner(emit_out=True)
        rc, _stdout, stderr = self._run([self.src, collide], runner)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(collide),
                        "正式产物被残留清扫误删（P3-1 回归）")
        self.assertNotIn("已清理临时残留: " + collide, stderr)

    def test_sweep_never_deletes_final_geometry_sidecar_on_collision(self):
        """P3-1：geometry sidecar 撞名时同样不得被删。

        下游按 ``out_path.replace('.musicxml', '.geometry.json')`` 写 sidecar
        （omr_oemer.py:816）。当 out 为 ``<stem>.pre.musicxml`` 时，
        该 sidecar 恰好等于清扫目标 ``<stem>.pre.geometry.json``。
        """
        self._install_success_stub()
        collide = os.path.join(self.tmp, "river_1.pre.musicxml")
        sidecar = os.path.join(self.tmp, "river_1.pre.geometry.json")

        def _runner_with_sidecar(cmd):
            with open(sidecar, "w", encoding="utf-8") as handle:
                handle.write('{"staffs": []}')
            return _Runner(emit_out=True)(cmd)

        self._run([self.src, collide], _runner_with_sidecar)
        self.assertTrue(os.path.isfile(sidecar),
                        "正式 geometry sidecar 被误删（P3-1 回归）")

    def test_sweep_still_removes_real_residue_after_p3_fix(self):
        """P3-1 反向保险：加了保护集之后，真残留仍必须被清掉。

        修 bug 时最容易犯的错是"保护过度"——把清扫整个废掉。
        这里用 C++ 真实口径的 out 名，确保保护集不误伤正常清扫路径。
        """
        self._install_success_stub()
        out = os.path.join(self.tmp, "river_1.png.pudu.musicxml")
        residue_xml = os.path.join(self.tmp, "river_1.pre.musicxml")
        residue_geo = os.path.join(self.tmp, "river_1.pre.geometry.json")

        def _runner_leaving_residue(cmd):
            for path in (residue_xml, residue_geo):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("leftover")
            return _Runner(emit_out=True)(cmd)

        self._run([self.src, out], _runner_leaving_residue)
        self.assertTrue(os.path.isfile(out))
        self.assertFalse(os.path.exists(residue_xml), "真残留漏清（保护过度）")
        self.assertFalse(os.path.exists(residue_geo), "真残留漏清（保护过度）")

    def test_protected_outputs_covers_out_and_sidecars(self):
        """P3-1 单元层：保护集须覆盖 out、geometry sidecar 与自定义 metrics。"""
        out = os.path.join(self.tmp, "a.musicxml")
        metrics = os.path.join(self.tmp, "custom.json")
        protected = omr_pipeline._protected_outputs(out, metrics)
        self.assertIn(os.path.abspath(out), protected)
        self.assertIn(os.path.abspath(
            os.path.join(self.tmp, "a.geometry.json")), protected)
        self.assertIn(os.path.abspath(metrics), protected)
        # 无关文件不得被误纳入保护
        self.assertNotIn(os.path.abspath(
            os.path.join(self.tmp, "a.pre.musicxml")), protected)

    def test_explicit_metrics_flag_overrides_config_switch(self):
        """P3-2：CLI 显式 --preprocess-metrics 压过 emit_metrics_sidecar=false。

        命令行是"这一次"的明确指令，配置文件只是默认策略。
        用户点名要指标文件，不该被静默吞掉。
        """
        cfg_path = os.path.join(self.tmp, "nometrics.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({"default": {"emit_metrics_sidecar": False}}, handle)
        explicit = os.path.join(self.tmp, "explicit_metrics.json")
        self._install_success_stub()
        _rc, _stdout, stderr = self._run(
            [self.src, self.out,
             "--preprocess-config", cfg_path,
             "--preprocess-metrics", explicit], _Runner(emit_out=True))
        self.assertTrue(os.path.isfile(explicit),
                        "显式 --preprocess-metrics 被配置静默吞掉（P3-2 回归）")
        self.assertIn("显式指定", stderr)          # 应有可见提示
        metrics = self._read_metrics(explicit)
        self.assertEqual(metrics["schema"], omr_preprocess.METRICS_SCHEMA)

    def test_config_switch_still_suppresses_default_metrics_path(self):
        """P3-2 反向保险：不显式指定时，emit_metrics_sidecar=false 仍完全不写。"""
        cfg_path = os.path.join(self.tmp, "nometrics.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({"default": {"emit_metrics_sidecar": False}}, handle)
        self._install_success_stub()
        self._run([self.src, self.out, "--preprocess-config", cfg_path],
                  _Runner(emit_out=True))
        self.assertFalse(os.path.exists(
            omr_pipeline.metrics_sidecar_path(self.out)))
        leftovers = [f for f in os.listdir(self.tmp)
                     if f.endswith(".preprocess.json")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
