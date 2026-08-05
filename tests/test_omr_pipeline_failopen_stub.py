# -*- coding: utf-8 -*-
"""fix (b) fail-open 兜底桩测试：增强图 oemer 失败时自动回退原图重跑。

只依赖标准库 + 注入假 runner，不调真 oemer / 不依赖 opencv。

覆盖：
  F1. 带 preset（吃增强图）且 oemer 失败 → 自动对原图重跑，raw 成功 → rc=0，
      标记 degraded="oemer_failed_on_enhanced→fell_back_to_raw"，metrics 记录
      fell_back_to_raw=True 且保留 enhanced_oemer_rc / enhanced_oemer_stderr；
  F2. 边界：--no-preprocess（off 路径）oemer 失败 → 不二次重跑，rc 原样透传；
  F3. 边界：回退的原图 oemer 也失败 → 不再二次重跑（无死循环），标记 fatal；
  F4. 边界：预处理因 noop 配置跳过（未吃增强图）oemer 失败 → 不重跑；
  F5. 边界：输入为 unsupported（PDF）跳过预处理 oemer 失败 → 不重跑；
  F6. 失败 trace 完整保留进 metrics sidecar（enhanced_oemer_rc / stderr）。
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
import omr_pipeline    # noqa: E402


class _Runner:
    """可编程假下游：对每次调用依次返回预设结果；结果用尽后复用最后一个。"""

    def __init__(self, results):
        # results: list of (rc, stdout, stderr)
        self.results = list(results) or [(0, "", "")]
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        rc, out, err = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        return rc, out, err

    @property
    def last(self):
        return self.calls[-1]

    @property
    def last_input(self):
        return self.calls[-1][2]


class FailOpenStubTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pudu_failopen_")
        self.src = os.path.join(self.tmp, "river_1.png")
        with open(self.src, "wb") as handle:
            handle.write(b"fake-image-bytes")
        self.out = os.path.join(self.tmp, "river_1.musicxml")
        self.metrics = os.path.join(self.tmp, "failopen_metrics.json")
        self._saved = omr_preprocess.preprocess_for_omr

    def tearDown(self):
        omr_preprocess.preprocess_for_omr = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _install_success_stub(self):
        def _stub(src, dst, cfg=None):
            with open(dst, "wb") as handle:
                handle.write(b"enhanced-png-bytes")
            return omr_preprocess.build_metrics(
                ok=True, degraded=False, src=src, dst=dst,
                config=(cfg or omr_preprocess.PreprocessConfig()).to_dict())
        omr_preprocess.preprocess_for_omr = _stub

    def _run(self, argv, runner):
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = omr_pipeline.run(argv, runner=runner)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def _read_metrics(self, path=None):
        target = path or self.metrics
        self.assertTrue(os.path.isfile(target), f"metrics sidecar 未写出: {target}")
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # F1：增强图失败 → 回退原图成功 → fail-open
    def test_enhanced_failure_falls_back_to_raw_success(self):
        self._install_success_stub()
        # 第一次（增强图）失败，第二次（原图）成功
        runner = _Runner([(1, "", "ValueError: max() iterable argument is empty"),
                          (0, "<score-partwise/>", "")])
        argv = [self.src, self.out, "--preprocess-preset", "photo",
                "--preprocess-metrics", self.metrics]
        rc, stdout, _stderr = self._run(argv, runner)
        # 必须两次调用：增强 + 原图
        self.assertEqual(len(runner.calls), 2, "应触发一次原图重跑")
        self.assertNotEqual(runner.calls[0][2], self.src)  # 首次 = 增强临时图
        self.assertEqual(runner.calls[1][2], self.src, "二次重跑必须吃原图")
        self.assertEqual(rc, 0)  # fail-open 成功
        self.assertIn("<score-partwise/>", stdout)
        metrics = self._read_metrics()
        self.assertTrue(metrics["fell_back_to_raw"])
        self.assertTrue(metrics["degraded"])
        self.assertEqual(metrics["degrade_reason"],
                         omr_pipeline._DEGRADE_ENHANCED_FAILED_FALLBACK)
        self.assertEqual(metrics["enhanced_oemer_rc"], 1)
        self.assertIn("max() iterable argument is empty",
                      metrics["enhanced_oemer_stderr"])
        self.assertEqual(metrics["raw_oemer_rc"], 0)

    # F2：off 路径不重跑
    def test_off_path_does_not_rerun_on_failure(self):
        self._install_success_stub()
        runner = _Runner([(1, "", "boom")])
        argv = [self.src, self.out, "--no-preprocess",
                "--preprocess-metrics", self.metrics]
        rc, _o, _e = self._run(argv, runner)
        self.assertEqual(len(runner.calls), 1, "off 路径不得二次重跑")
        self.assertEqual(runner.calls[0][2], self.src)
        self.assertEqual(rc, 1)  # 原样透传
        metrics = self._read_metrics()
        # 本用例锁定的语义是「off 路径 oemer 失败时绝不二次重跑」，
        # 判据是 fell_back_to_raw 与 calls 数，**不是** degraded。
        # off 路径（--no-preprocess）本就带既有降级标记
        # degraded=True / degrade_reason="skipped:no_preprocess_flag"，
        # 那是 P3 就有的「跳过预处理」语义，与 fix (b) 兜底无关；
        # 对它断言 False 会把既有行为误判成回归（对齐 F5 的写法）。
        self.assertFalse(metrics["fell_back_to_raw"])
        self.assertEqual(metrics["degrade_reason"], "skipped:no_preprocess_flag")
        # 兜底诊断字段是 schema 常驻键，未兜底时应保持未填充（None / ""）。
        self.assertIsNone(metrics["enhanced_oemer_rc"],
                          "off 路径不得填充兜底诊断字段")
        self.assertIsNone(metrics["raw_oemer_rc"],
                          "off 路径不得填充兜底诊断字段")

    # F3：原图也失败 → fatal，不再重跑（无死循环）
    def test_raw_also_fails_records_fatal_no_loop(self):
        self._install_success_stub()
        runner = _Runner([(1, "", "enhanced failed"),
                          (2, "", "raw also failed")])
        argv = [self.src, self.out, "--preprocess-preset", "photo",
                "--preprocess-metrics", self.metrics]
        rc, _o, _e = self._run(argv, runner)
        self.assertEqual(len(runner.calls), 2, "原图失败不得触发第三次重跑")
        self.assertEqual(rc, 2)  # 透传原图 rc（致命，不回退到崩溃）
        metrics = self._read_metrics()
        self.assertTrue(metrics["fell_back_to_raw"])
        self.assertTrue(metrics["degraded"])
        self.assertEqual(metrics["degrade_reason"],
                         omr_pipeline._DEGRADE_ENHANCED_FAILED_RAW_ALSO)
        self.assertEqual(metrics["enhanced_oemer_rc"], 1)
        self.assertEqual(metrics["raw_oemer_rc"], 2)

    # F4：noop 配置 → 未吃增强图 → oemer 失败不重跑
    def test_noop_config_not_fed_enhanced_no_rerun(self):
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
        runner = _Runner([(1, "", "boom")])
        argv = [self.src, self.out, "--preprocess-config", cfg_path,
                "--preprocess-metrics", self.metrics]
        rc, _o, _e = self._run(argv, runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][2], self.src)
        metrics = self._read_metrics()
        self.assertFalse(metrics["fell_back_to_raw"])

    # F5：unsupported 输入（PDF）→ 跳过预处理 → 不重跑
    def test_unsupported_input_no_rerun(self):
        pdf = os.path.join(self.tmp, "score.pdf")
        with open(pdf, "wb") as handle:
            handle.write(b"%PDF-1.4")
        out = os.path.join(self.tmp, "score.musicxml")
        metrics = os.path.join(self.tmp, "pdf_metrics.json")
        self._install_success_stub()
        runner = _Runner([(1, "", "boom")])
        argv = [pdf, out, "--preprocess-preset", "photo",
                "--preprocess-metrics", metrics]
        rc, _o, _e = self._run(argv, runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][2], pdf)
        self.assertEqual(rc, 1)
        m = self._read_metrics(metrics)
        self.assertFalse(m["fell_back_to_raw"])
        self.assertEqual(m["degrade_reason"], "skipped:unsupported_input")

    # F6：失败 trace 完整保留（含 rc 与 stderr）
    def test_failure_trace_preserved_in_metrics(self):
        self._install_success_stub()
        runner = _Runner([(7, "", "Traceback: oemer blew up\nValueError: max() ..."),
                          (0, "", "")])
        argv = [self.src, self.out, "--preprocess-preset", "photo",
                "--preprocess-metrics", self.metrics]
        rc, _o, _e = self._run(argv, runner)
        self.assertEqual(rc, 0)
        metrics = self._read_metrics()
        self.assertEqual(metrics["enhanced_oemer_rc"], 7)
        self.assertIn("oemer blew up", metrics["enhanced_oemer_stderr"])
        self.assertEqual(metrics["raw_oemer_rc"], 0)
        self.assertEqual(metrics["raw_oemer_stderr"], "")


if __name__ == "__main__":
    unittest.main()
