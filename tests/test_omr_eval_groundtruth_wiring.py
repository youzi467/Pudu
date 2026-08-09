# -*- coding: utf-8 -*-
"""P1-2 · T01 harness 接线单测（**不跑 oemer / 不跑 Pudu / 不需 GPU**）。

被测对象：``tools/omr_eval_groundtruth.py`` 的 4 处可选参数化（设计 §2.4）。

覆盖需求
--------
* **SK-7 红线（最重要）**：所有新增参数缺省时，``run_oemer`` /
  ``pudu_jianpu_json`` 构造的子进程 argv 与 P1-2 改动前**逐 token 相同**。
  本文件独立复刻了改动前的 argv 构造逻辑（``legacy_*_cmd``）作为黄金参照。
* **6 种 arm 的 argv 逐 token 校验**：``pre_off`` / ``pipe_noop`` /
  ``pre_default`` / ``pre_scan`` / ``pre_photo`` / ``pre_low_contrast``
  （外加 ``pre_photo_nodeskew`` 探针 arm）。
* **SK-2**：所有 arm 一律带 ``--gt``（少一个就毁掉可比性）。
* **SK-8**：``preprocess is None`` 时传 ``preprocess_config/metrics``
  必须抛 ``ValueError``（禁止静默忽略）。
* **SK-4 红线**：``eval_corpus`` 对 ``project_opts.postcorrect_gt=True``
  硬断言；gt 侧投影永不携带 ``--apply-postcorrect``。
* ``reuse_pred`` 语义：命中即跳过 oemer；缺失即 fatal（不静默回退跑 oemer）。
* ``{base}`` 占位符逐页展开（SK-5 降级可观测的前提）。
* ``summary.experiment`` 自描述字段（R4 可复现性）。

本测试**不 import cv2 / numpy**（沿用 P0-2 规则，保证沙箱可收集）。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import omr_eval_groundtruth as G  # noqa: E402
from omr_eval_groundtruth import OemerOpts, ProjectOpts  # noqa: E402


# ----------------------------------------------------------------------
# 黄金参照：P1-2 改动**之前**的 argv 构造逻辑（逐字复刻，独立于被测代码）
# ----------------------------------------------------------------------

def legacy_run_oemer_cmd(image_path, out_musicxml, gt_path=None,
                         venv_python=G.VENV_PYTHON, f3_geometric=False):
    """改动前 ``run_oemer`` 的 argv（复刻自 omr_eval_groundtruth.py:116-120）。"""
    cmd = [venv_python, G.OMER_RUNNER, image_path, out_musicxml]
    if gt_path:
        cmd += ["--gt", gt_path]
    if f3_geometric:
        cmd += ["--f3-geometric"]
    return cmd


def legacy_pudu_cmd(musicxml_path, tmp_json):
    """改动前 ``pudu_jianpu_json`` 的 argv（复刻自 :157）。"""
    return [G.EXE, musicxml_path, "--to-jianpu-json", tmp_json]


# ----------------------------------------------------------------------
# subprocess.run 替身
# ----------------------------------------------------------------------

class FakeCompleted(object):
    """``subprocess.CompletedProcess`` 的最小替身。"""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder(object):
    """记录所有 ``subprocess.run`` 调用的 argv，并按需伪造产物。

    Attributes:
        calls: 逐次调用的 argv 列表（``List[List[str]]``）。
        rc: 伪造的退出码。
        make_outputs: 是否伪造产物文件（oemer 的 out.musicxml / Pudu 的 out.json）。
    """

    def __init__(self, rc=0, make_outputs=True):
        self.calls = []
        self.rc = rc
        self.make_outputs = make_outputs

    def __call__(self, cmd, *args, **kwargs):
        argv = list(cmd)
        self.calls.append(argv)
        if self.make_outputs and len(argv) >= 4:
            if "--to-jianpu-json" in argv:
                out = argv[argv.index("--to-jianpu-json") + 1]
                with open(out, "w", encoding="utf-8") as handle:
                    json.dump({"fifths": 0, "mode": "major",
                               "beats": 4, "beatType": 4, "parts": []}, handle)
            else:
                out = argv[3]
                parent = os.path.dirname(os.path.abspath(out))
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent, exist_ok=True)
                with open(out, "w", encoding="utf-8") as handle:
                    handle.write("<score-partwise/>")
        return FakeCompleted(self.rc)

    @property
    def last(self):
        return self.calls[-1]


class _BaseWiringTest(unittest.TestCase):
    """公共夹具：清掉 PUDU_F3_GEOMETRIC 环境变量的干扰。"""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("PUDU_F3_GEOMETRIC", None)
        self.tmpdir = tempfile.mkdtemp(prefix="pudu_wiring_")

    def tearDown(self):
        self._env.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _path(self, name):
        return os.path.join(self.tmpdir, name)


# ======================================================================
# 1. SK-7 红线：默认路径逐字节不变
# ======================================================================

class DefaultArgvUnchangedTest(_BaseWiringTest):
    """🔴 默认参数下 argv 必须与改动前逐 token 相同。"""

    def _run(self, **kwargs):
        rec = Recorder()
        out = self._path("out.musicxml")
        with mock.patch.object(G.subprocess, "run", rec):
            G.run_oemer(self._path("in.jpg"), out, **kwargs)
        return rec.last

    def test_run_oemer_default_no_gt(self):
        got = self._run()
        self.assertEqual(
            got, legacy_run_oemer_cmd(self._path("in.jpg"),
                                      self._path("out.musicxml")))

    def test_run_oemer_default_with_gt(self):
        gt = self._path("in.gt.musicxml")
        got = self._run(gt_path=gt)
        self.assertEqual(
            got, legacy_run_oemer_cmd(self._path("in.jpg"),
                                      self._path("out.musicxml"), gt_path=gt))

    def test_run_oemer_default_with_gt_and_f3(self):
        gt = self._path("in.gt.musicxml")
        got = self._run(gt_path=gt, f3_geometric=True)
        self.assertEqual(
            got, legacy_run_oemer_cmd(self._path("in.jpg"),
                                      self._path("out.musicxml"),
                                      gt_path=gt, f3_geometric=True))

    def test_run_oemer_default_custom_venv(self):
        got = self._run(gt_path=None, venv_python=r"X:\py.exe")
        self.assertEqual(
            got, legacy_run_oemer_cmd(self._path("in.jpg"),
                                      self._path("out.musicxml"),
                                      venv_python=r"X:\py.exe"))

    def test_run_oemer_default_matrix_bytewise(self):
        """gt × f3 全组合（4 例）逐 token 比对，一个 token 都不许多/少/换位。"""
        for gt in (None, self._path("g.gt.musicxml")):
            for f3 in (False, True):
                with self.subTest(gt=bool(gt), f3=f3):
                    got = self._run(gt_path=gt, f3_geometric=f3)
                    want = legacy_run_oemer_cmd(
                        self._path("in.jpg"), self._path("out.musicxml"),
                        gt_path=gt, f3_geometric=f3)
                    self.assertEqual(got, want)
                    self.assertNotIn("--preprocess-preset", got)
                    self.assertNotIn("--preprocess-config", got)
                    self.assertNotIn("--preprocess-metrics", got)
                    self.assertNotIn("--no-preprocess", got)
                    self.assertEqual(got[1], G.OMER_RUNNER)

    def test_run_oemer_rhythm_flag_appended_after_f3(self):
        """🔴 R-geo 回归守卫（2026-08-09 bug 修复）：rhythm_geometric=True 时
        argv 必须含 ``--rhythm-geometric``，且紧跟在 ``--f3-geometric`` 之后。
        此前 f623221 只把 flag 接进 OemerOpts/签名/CLI，实际 cmd 构建漏加，
        eval harness 复现不了 83.19%（靠环境变量 PUDU_RHYTHM_GEOMETRIC 走通）。"""
        gt = self._path("g.gt.musicxml")
        for has_gt in (False, True):
            for f3 in (False, True):
                with self.subTest(gt=has_gt, f3=f3):
                    got = self._run(gt_path=gt if has_gt else None,
                                    f3_geometric=f3, rhythm_geometric=True)
                    want = legacy_run_oemer_cmd(
                        self._path("in.jpg"), self._path("out.musicxml"),
                        gt_path=gt if has_gt else None, f3_geometric=f3)
                    want += ["--rhythm-geometric"]
                    self.assertEqual(got, want)
                    self.assertEqual(got.count("--rhythm-geometric"), 1)
                    if f3:  # 位置：紧跟在 --f3-geometric 之后
                        self.assertEqual(
                            got.index("--rhythm-geometric"),
                            got.index("--f3-geometric") + 1)

    def test_run_oemer_rhythm_flag_absent_by_default(self):
        """默认（rhythm_geometric=False）不出现 ``--rhythm-geometric``（SK-7
        兼容：改动后默认 argv 仍与改动前逐 token 相同）。"""
        for f3 in (False, True):
            with self.subTest(f3=f3):
                got = self._run(f3_geometric=f3)
                self.assertNotIn("--rhythm-geometric", got)

    def test_pudu_jianpu_json_default_unchanged(self):
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            G.pudu_jianpu_json(self._path("x.musicxml"))
        got = rec.last
        self.assertEqual(len(got), 4)
        self.assertEqual(got[:3], legacy_pudu_cmd(self._path("x.musicxml"),
                                                  got[3])[:3])
        self.assertEqual(got, legacy_pudu_cmd(self._path("x.musicxml"), got[3]))
        self.assertNotIn("--apply-postcorrect", got)
        self.assertNotIn("--postcorrect-report", got)


# ======================================================================
# 2. 6 种 arm 的 argv 逐 token 校验
# ======================================================================

class ArmArgvTest(_BaseWiringTest):
    """每个 arm 的 runner 与 flag 顺序都必须精确。"""

    def _argv(self, **kwargs):
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            G.run_oemer(self._path("p1.jpg"), self._path("p1.pred.musicxml"),
                        gt_path=self._path("p1.gt.musicxml"), **kwargs)
        return rec.last

    def test_arm_pre_off_direct_call(self):
        """arm ``pre_off``：preprocess=None -> 直调 omr_oemer.py（基线）。"""
        self.assertEqual(self._argv(), [
            G.VENV_PYTHON, G.OMER_RUNNER,
            self._path("p1.jpg"), self._path("p1.pred.musicxml"),
            "--gt", self._path("p1.gt.musicxml"),
        ])

    def test_arm_pipe_noop(self):
        """arm ``pipe_noop``：经代理但 --no-preprocess（透明性 sanity）。"""
        self.assertEqual(self._argv(preprocess="off"), [
            G.VENV_PYTHON, G.PIPELINE_RUNNER,
            self._path("p1.jpg"), self._path("p1.pred.musicxml"),
            "--no-preprocess",
            "--gt", self._path("p1.gt.musicxml"),
        ])

    def test_arm_presets(self):
        """arm ``pre_default`` / ``pre_scan`` / ``pre_photo`` / ``pre_low_contrast``。"""
        for preset in ("default", "scan", "photo", "low_contrast"):
            with self.subTest(preset=preset):
                self.assertEqual(self._argv(preprocess=preset), [
                    G.VENV_PYTHON, G.PIPELINE_RUNNER,
                    self._path("p1.jpg"), self._path("p1.pred.musicxml"),
                    "--preprocess-preset", preset,
                    "--gt", self._path("p1.gt.musicxml"),
                ])

    def test_arm_photo_nodeskew_probe(self):
        """arm ``pre_photo_nodeskew``（U7 探针）：photo preset + 覆盖配置。"""
        cfg = os.path.join(TOOLS, "omr_abtest_photo_nodeskew.json")
        self.assertEqual(
            self._argv(preprocess="photo", preprocess_config=cfg), [
                G.VENV_PYTHON, G.PIPELINE_RUNNER,
                self._path("p1.jpg"), self._path("p1.pred.musicxml"),
                "--preprocess-preset", "photo",
                "--preprocess-config", cfg,
                "--gt", self._path("p1.gt.musicxml"),
            ])

    def test_arm_direct_with_rgeo(self):
        """直调路径 rhythm_geometric=True 也带 flag（修复覆盖两条 runner 路径）。"""
        self.assertEqual(self._argv(rhythm_geometric=True), [
            G.VENV_PYTHON, G.OMER_RUNNER,
            self._path("p1.jpg"), self._path("p1.pred.musicxml"),
            "--gt", self._path("p1.gt.musicxml"),
            "--rhythm-geometric",
        ])

    def test_arm_pipe_off_with_rgeo(self):
        """代理路径（preprocess='off'）同样带 flag。"""
        self.assertEqual(self._argv(preprocess="off", rhythm_geometric=True), [
            G.VENV_PYTHON, G.PIPELINE_RUNNER,
            self._path("p1.jpg"), self._path("p1.pred.musicxml"),
            "--no-preprocess",
            "--gt", self._path("p1.gt.musicxml"),
            "--rhythm-geometric",
        ])

    def test_arm_with_metrics_sidecar(self):
        """SK-5：显式 --preprocess-metrics 必须出现在 --gt 之前、preset 之后。"""
        metrics = self._path("p1.preprocess.json")
        self.assertEqual(
            self._argv(preprocess="scan", preprocess_metrics=metrics), [
                G.VENV_PYTHON, G.PIPELINE_RUNNER,
                self._path("p1.jpg"), self._path("p1.pred.musicxml"),
                "--preprocess-preset", "scan",
                "--preprocess-metrics", metrics,
                "--gt", self._path("p1.gt.musicxml"),
            ])

    def test_all_arms_carry_gt(self):
        """🔴 SK-2：所有 arm 一律带 --gt，少一个就毁掉可比性。"""
        for preprocess in (None, "off", "default", "scan",
                           "photo", "low_contrast"):
            with self.subTest(preprocess=preprocess):
                argv = self._argv(preprocess=preprocess)
                self.assertIn("--gt", argv)
                self.assertEqual(argv[argv.index("--gt") + 1],
                                 self._path("p1.gt.musicxml"))

    def test_private_flags_never_leak_to_direct_runner(self):
        """SK-8 的另一面：直调 runner 的 argv 里绝不出现私有 flag。"""
        argv = self._argv()
        for flag in ("--preprocess-preset", "--preprocess-config",
                     "--preprocess-metrics", "--no-preprocess", "--keep-temp"):
            self.assertNotIn(flag, argv)


# ======================================================================
# 3. SK-8：误配必须炸，不许静默
# ======================================================================

class Sk8GuardTest(_BaseWiringTest):
    """``preprocess is None`` + 私有 flag = ValueError。"""

    def test_config_without_preprocess_raises(self):
        with self.assertRaises(ValueError) as ctx:
            G.run_oemer("a.jpg", "b.musicxml", preprocess_config="c.json")
        self.assertIn("SK-8", str(ctx.exception))

    def test_metrics_without_preprocess_raises(self):
        with self.assertRaises(ValueError):
            G.run_oemer("a.jpg", "b.musicxml", preprocess_metrics="m.json")

    def test_no_subprocess_launched_on_misconfig(self):
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            with self.assertRaises(ValueError):
                G.run_oemer("a.jpg", "b.musicxml", preprocess_config="c.json")
        self.assertEqual(rec.calls, [])

    def test_off_plus_config_is_allowed(self):
        """``preprocess='off'`` 走代理，此时携带 config 是合法的。"""
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            G.run_oemer(self._path("a.jpg"), self._path("b.musicxml"),
                        preprocess="off", preprocess_config="c.json")
        self.assertIn("--preprocess-config", rec.last)


# ======================================================================
# 4. Pudu 投影侧（接线点 ②）
# ======================================================================

class PuduProjectionArgvTest(_BaseWiringTest):
    """``--apply-postcorrect`` / ``--postcorrect-report`` 的精确拼装。"""

    def _argv(self, **kwargs):
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            G.pudu_jianpu_json(self._path("pred.musicxml"), **kwargs)
        return rec.last

    def test_postcorrect_on(self):
        argv = self._argv(postcorrect=True)
        self.assertEqual(argv[:3], [G.EXE, self._path("pred.musicxml"),
                                    "--to-jianpu-json"])
        self.assertEqual(argv[4:], ["--apply-postcorrect"])

    def test_postcorrect_with_report(self):
        report = os.path.join(self.tmpdir, "pc", "p1.report.json")
        argv = self._argv(postcorrect=True, postcorrect_report=report)
        self.assertEqual(argv[4:], ["--apply-postcorrect",
                                    "--postcorrect-report", report])
        # 报告父目录必须被提前建好，否则 Pudu 写出会失败
        self.assertTrue(os.path.isdir(os.path.dirname(report)))

    def test_report_without_postcorrect_still_emits_flag(self):
        """只给 report 不给 postcorrect 时不加 --apply-postcorrect（语义正交）。"""
        report = self._path("r.json")
        argv = self._argv(postcorrect=False, postcorrect_report=report)
        self.assertNotIn("--apply-postcorrect", argv)
        self.assertIn("--postcorrect-report", argv)

    def test_returns_parsed_json(self):
        rec = Recorder()
        with mock.patch.object(G.subprocess, "run", rec):
            doc = G.pudu_jianpu_json(self._path("pred.musicxml"))
        self.assertEqual(doc["fifths"], 0)

    def test_nonzero_rc_raises(self):
        rec = Recorder(rc=3)
        with mock.patch.object(G.subprocess, "run", rec):
            with self.assertRaises(RuntimeError):
                G.pudu_jianpu_json(self._path("pred.musicxml"))


# ======================================================================
# 5. _eval_one / eval_corpus 透传（接线点 ③）
# ======================================================================

class _Corpus(object):
    """在临时目录里造一份最小语料（1 页：jpg + gt.musicxml）。"""

    def __init__(self, root, pages=("p1",)):
        self.root = root
        self.pages = list(pages)
        for base in self.pages:
            with open(os.path.join(root, base + ".jpg"), "wb") as handle:
                handle.write(b"\xff\xd8\xff")
            with open(os.path.join(root, base + ".gt.musicxml"), "w",
                      encoding="utf-8") as handle:
                handle.write("<score-partwise/>")

    def write_pred(self, base, content="<score-partwise/>"):
        path = os.path.join(self.root, base + ".pred.musicxml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path


class EvalWiringTest(_BaseWiringTest):
    """``oemer_opts`` / ``project_opts`` / ``reuse_pred`` 的端到端透传。"""

    def setUp(self):
        super(EvalWiringTest, self).setUp()
        self.corpus = _Corpus(self.tmpdir)
        self.oemer_calls = []
        self.pudu_calls = []

    def _fake_run_oemer(self, image_path, out_musicxml, **kwargs):
        self.oemer_calls.append(dict(kwargs, image=image_path,
                                     out=out_musicxml))
        with open(out_musicxml, "w", encoding="utf-8") as handle:
            handle.write("<score-partwise/>")
        return True

    def _fake_pudu(self, musicxml_path, **kwargs):
        self.pudu_calls.append(dict(kwargs, musicxml=musicxml_path))
        return {"fifths": 0, "mode": "major", "beats": 4, "beatType": 4,
                "parts": []}

    def _patched(self):
        return mock.patch.multiple(
            G, run_oemer=self._fake_run_oemer,
            pudu_jianpu_json=self._fake_pudu)

    def test_default_opts_pass_none(self):
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True)
        self.assertEqual(len(self.oemer_calls), 1)
        call = self.oemer_calls[0]
        self.assertIsNone(call["preprocess"])
        self.assertIsNone(call["preprocess_config"])
        self.assertIsNone(call["preprocess_metrics"])
        self.assertEqual(result["summary"]["experiment"]["preprocess"], None)

    def test_oemer_opts_forwarded(self):
        opts = OemerOpts(preprocess="scan",
                         preprocess_config="cfg.json",
                         preprocess_metrics=os.path.join(
                             self.tmpdir, "{base}.preprocess.json"))
        with self._patched():
            G.eval_corpus(self.tmpdir, use_oemer=True, oemer_opts=opts)
        call = self.oemer_calls[0]
        self.assertEqual(call["preprocess"], "scan")
        self.assertEqual(call["preprocess_config"], "cfg.json")
        # {base} 必须被展开成当前页 stem（SK-3 / SK-5）
        self.assertEqual(call["preprocess_metrics"],
                         os.path.join(self.tmpdir, "p1.preprocess.json"))

    def test_project_opts_pred_only(self):
        """🔴 SK-4：pred 侧带 postcorrect，gt 侧必须**不带**。"""
        opts = ProjectOpts(postcorrect_pred=True,
                           postcorrect_report=os.path.join(
                               self.tmpdir, "pc", "{base}.report.json"))
        with self._patched():
            G.eval_corpus(self.tmpdir, use_oemer=True, project_opts=opts)
        self.assertEqual(len(self.pudu_calls), 2)
        pred_call, gt_call = self.pudu_calls
        self.assertTrue(pred_call["postcorrect"])
        self.assertEqual(pred_call["postcorrect_report"],
                         os.path.join(self.tmpdir, "pc", "p1.report.json"))
        self.assertTrue(pred_call["musicxml"].endswith(".pred.musicxml"))
        # gt 侧：以默认参数调用（无 postcorrect kwarg）
        self.assertTrue(gt_call["musicxml"].endswith(".gt.musicxml"))
        self.assertNotIn("postcorrect", gt_call)

    def test_sk4_hard_assert(self):
        """🔴 postcorrect_gt=True 必须直接炸掉，绝不放行。"""
        with self.assertRaises(AssertionError) as ctx:
            G.eval_corpus(self.tmpdir, use_oemer=True,
                          project_opts=ProjectOpts(postcorrect_gt=True))
        self.assertIn("SK-4", str(ctx.exception))

    def test_reuse_pred_skips_oemer(self):
        self.corpus.write_pred("p1")
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True,
                                   reuse_pred=True)
        self.assertEqual(self.oemer_calls, [])
        self.assertEqual(result["summary"]["fatal_files"], [])
        self.assertTrue(result["summary"]["experiment"]["reuse_pred"])

    def test_reuse_pred_missing_is_fatal(self):
        """缺 pred 时必须 fatal，**不得**静默回退去跑 oemer。"""
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True,
                                   reuse_pred=True)
        self.assertEqual(self.oemer_calls, [])
        self.assertEqual(result["summary"]["fatal_files"], ["p1"])

    def test_reuse_pred_empty_file_is_fatal(self):
        path = self.corpus.write_pred("p1", content="")
        self.assertEqual(os.path.getsize(path), 0)
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True,
                                   reuse_pred=True)
        self.assertEqual(result["summary"]["fatal_files"], ["p1"])

    def test_experiment_field_shape(self):
        opts = OemerOpts(preprocess="photo", preprocess_config="c.json")
        popts = ProjectOpts(postcorrect_pred=True)
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True,
                                   oemer_opts=opts, project_opts=popts)
        exp = result["summary"]["experiment"]
        self.assertEqual(exp["preprocess"], "photo")
        self.assertEqual(exp["preprocess_config"], "c.json")
        self.assertTrue(exp["postcorrect_pred"])
        self.assertFalse(exp["postcorrect_gt"])
        self.assertFalse(exp["reuse_pred"])

    def test_existing_summary_keys_preserved(self):
        """新增 experiment 键不得挤掉/改写任何既有键（SK-7 口径不漂移）。"""
        with self._patched():
            result = G.eval_corpus(self.tmpdir, use_oemer=True)
        for key in ("mode", "files_total", "files_ok", "notes_compared",
                    "notes_correct", "note_pass_rate", "field_checked",
                    "field_failed", "field_pass_rate",
                    "category_distribution", "category_pass", "edge_case",
                    "fatal_files"):
            self.assertIn(key, result["summary"])


# ======================================================================
# 6. CLI 层
# ======================================================================

class CliWiringTest(_BaseWiringTest):
    """``main()`` 把 flag 正确折叠成 OemerOpts / ProjectOpts。"""

    def setUp(self):
        super(CliWiringTest, self).setUp()
        _Corpus(self.tmpdir)
        self.captured = {}

    def _fake_eval_corpus(self, corpus_dir, use_oemer=True, **kwargs):
        self.captured = dict(kwargs, corpus_dir=corpus_dir,
                             use_oemer=use_oemer)
        return {
            "summary": {
                "mode": "oemer", "files_total": 0, "files_ok": 0,
                "notes_compared": 0, "notes_correct": 0, "note_pass_rate": 0.0,
                "field_checked": 0, "field_failed": 0, "field_pass_rate": 0.0,
                "category_distribution": {}, "category_pass": {},
                "edge_case": {"rests": 0, "chords": 0, "graces": 0,
                              "tuplets": 0, "octave_jumps": 0},
                "fatal_files": [], "experiment": {},
            },
            "per_file": [], "flagged_for_postcorrect": [],
            "note_diffs_path": None,
        }

    def _main(self, extra):
        with mock.patch.object(G, "eval_corpus", self._fake_eval_corpus):
            rc = G.main([self.tmpdir] + list(extra))
        return rc

    def test_defaults(self):
        self.assertEqual(self._main([]), 0)
        self.assertEqual(self.captured["oemer_opts"], OemerOpts())
        self.assertEqual(self.captured["project_opts"], ProjectOpts())
        self.assertFalse(self.captured["reuse_pred"])

    def test_preprocess_preset(self):
        self._main(["--preprocess-preset", "scan"])
        self.assertEqual(self.captured["oemer_opts"].preprocess, "scan")

    def test_omr_preprocess_preset_alias(self):
        """设计 §2.4 写的是 --omr-preprocess-preset，保留为别名。"""
        self._main(["--omr-preprocess-preset", "photo"])
        self.assertEqual(self.captured["oemer_opts"].preprocess, "photo")

    def test_no_preprocess_maps_to_off(self):
        self._main(["--no-preprocess"])
        self.assertEqual(self.captured["oemer_opts"].preprocess, "off")

    def test_postcorrect_flags(self):
        self._main(["--apply-postcorrect",
                    "--postcorrect-report", "r/{base}.json"])
        popts = self.captured["project_opts"]
        self.assertTrue(popts.postcorrect_pred)
        self.assertFalse(popts.postcorrect_gt)
        self.assertEqual(popts.postcorrect_report, "r/{base}.json")

    def test_reuse_pred_flag(self):
        self._main(["--reuse-pred"])
        self.assertTrue(self.captured["reuse_pred"])

    def test_preset_and_no_preprocess_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self._main(["--preprocess-preset", "scan", "--no-preprocess"])

    def test_no_cli_path_to_postcorrect_gt(self):
        """🔴 CLI 不得提供任何打开 postcorrect_gt 的途径。"""
        with self.assertRaises(SystemExit):
            self._main(["--apply-postcorrect-gt"])


# ======================================================================
# 7. {base} 展开纯函数
# ======================================================================

class ExpandBaseTest(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertIsNone(G._expand_base(None, "p1"))
        self.assertIsNone(G._expand_base("", "p1"))

    def test_no_placeholder_is_identity(self):
        self.assertEqual(G._expand_base("a/b.json", "p1"), "a/b.json")

    def test_placeholder_replaced_everywhere(self):
        self.assertEqual(G._expand_base("d/{base}/{base}.json", "p7"),
                         "d/p7/p7.json")

    def test_windows_path_survives(self):
        self.assertEqual(
            G._expand_base(r"C:\x\{base}.preprocess.json", "concerto_p1"),
            r"C:\x\concerto_p1.preprocess.json")


if __name__ == "__main__":
    unittest.main()
