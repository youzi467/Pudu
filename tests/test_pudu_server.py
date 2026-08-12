# -*- coding: utf-8 -*-
"""本地网页应用（tools/pudu_server.py）单测。

覆盖：
  * extract_footnotes：footnote → measure/note_index/reasons/分类计数；无标记 total 0；
    文件缺失 → 空结构；合并原因「；」拆两条。
  * inject_cuda_path：存在目录前置 PATH；缺失 → PATH 不变（CPU 回退）。
  * build_ocr_cmd / build_fixture_cmd / build_render_cmd：命令 argv 精确匹配。
  * parse_multipart：手写 multipart 解析；raw body + X-Filename 上传路径。
  * HTTP 路由：GET / 返回 UI；job_id 路径穿越拒绝 → 404；非图片 → 400。
  * fixture 冒烟（@skipUnless PUDU_EXE 在位）：POST /api/ocr?demo=1 → done →
    jianpu.html 含 fixture 标题、final.musicxml 可解析、review.json total=0。
  * Pudu.exe 缺失 → 作业显式 error（对齐「失败页明确报错」）。

纯 stdlib（urllib / http.server / unittest），不依赖 oemer / numpy。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import pudu_server as ps  # noqa: E402


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else tag


def _build_mx_with_footnotes(path):
    """构造含 footnote 的 score-partwise：note1 无标、note2 时值、note3 合并两条。"""
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", {"id": "P1"})
    m = ET.SubElement(part, "measure", {"number": "1"})

    def _note(step, octave, foot=None):
        n = ET.SubElement(m, "note")
        pitch = ET.SubElement(n, "pitch")
        ET.SubElement(pitch, "step").text = step
        ET.SubElement(pitch, "octave").text = str(octave)
        if foot:
            notations = ET.SubElement(n, "notations")
            fn = ET.SubElement(notations, "footnote")
            fn.text = foot
        return n

    _note("C", 4)                                     # index 1：无标记
    _note("D", 4, "需校对：几何时值未校正")              # index 2
    _note("E", 5, "需校对：几何音高未验证；几何时值未校正")  # index 3
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


# ----------------------------------------------------------------------
# 纯函数单测
# ----------------------------------------------------------------------

class ExtractFootnotesTest(unittest.TestCase):

    def test_basic_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.musicxml")
            _build_mx_with_footnotes(p)
            rev = ps.extract_footnotes(p)
            self.assertEqual(rev["total"], 2)
            self.assertEqual(rev["categories"],
                             {"几何时值未校正": 2, "几何音高未验证": 1})
            it = rev["items"]
            self.assertEqual(len(it), 2)
            self.assertEqual(it[0]["measure"], "1")
            self.assertEqual(it[0]["note_index"], 2)
            self.assertEqual(it[0]["reasons"], ["几何时值未校正"])
            self.assertEqual(it[0]["step"], "D")
            self.assertEqual(it[0]["octave"], "4")
            self.assertEqual(it[1]["note_index"], 3)

    def test_merge_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.musicxml")
            _build_mx_with_footnotes(p)
            rev = ps.extract_footnotes(p)
            self.assertEqual(rev["items"][1]["reasons"],
                             ["几何音高未验证", "几何时值未校正"])

    def test_no_footnotes_total_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.musicxml")
            _build_mx_with_footnotes(p)
            tree = ET.parse(p)
            for measure in tree.getroot().iter("measure"):
                for note in measure.findall("note"):
                    notations = note.find("notations")
                    if notations is None:
                        continue
                    fn = notations.find("footnote")
                    if fn is not None:
                        notations.remove(fn)
            tree.write(p, encoding="UTF-8", xml_declaration=True)
            rev = ps.extract_footnotes(p)
            self.assertEqual(rev, {"total": 0, "categories": {}, "items": []})

    def test_missing_file_empty(self):
        self.assertEqual(ps.extract_footnotes("C:/nonexistent/x.musicxml"),
                         {"total": 0, "categories": {}, "items": []})


class CmdBuildTest(unittest.TestCase):

    def test_build_ocr_cmd_audiveris_default(self):
        cmd = ps.build_ocr_cmd("img.png", "out.musicxml")
        self.assertEqual(cmd[:2], [ps.VENV_PYTHON, os.path.join(ps.TOOLS, "omr_audiveris.py")])
        self.assertEqual(cmd[2:], ["img.png", "out.musicxml"])

    def test_build_ocr_cmd_oemer(self):
        cmd = ps.build_ocr_cmd("img.png", "out.musicxml", engine="oemer")
        self.assertEqual(cmd[:2], [ps.VENV_PYTHON, os.path.join(ps.TOOLS, "omr_oemer.py")])
        self.assertEqual(cmd[2:], ["img.png", "out.musicxml",
                                   "--f3-geometric", "--rhythm-geometric"])

    def test_build_fixture_cmd(self):
        self.assertEqual(
            ps.build_fixture_cmd("img.png", "out.html"),
            [ps.PUDU_EXE, "--from-omr", "img.png", "--omr-engine", "fixture",
             "--to-jianpu-l2", "out.html"])

    def test_build_render_cmd(self):
        self.assertEqual(ps.build_render_cmd("mx", "out.html"),
                         [ps.PUDU_EXE, "mx", "--to-jianpu-l2", "out.html"])


class InjectCudaTest(unittest.TestCase):

    def test_existing_dirs_prepended(self):
        with mock.patch("os.path.isdir", return_value=True), \
             mock.patch.object(ps, "CUDA_BINS", ["C:/cuda", "C:/cudnn"]):
            env = ps.inject_cuda_path({"PATH": "base"})
            self.assertTrue(env["PATH"].startswith("C:/cuda" + os.pathsep + "C:/cudnn"))
            self.assertIn(os.pathsep + "base", env["PATH"])

    def test_missing_dirs_unchanged(self):
        with mock.patch("os.path.isdir", return_value=False):
            env = ps.inject_cuda_path({"PATH": "base"})
            self.assertEqual(env["PATH"], "base")


class ParseMultipartTest(unittest.TestCase):

    def test_multipart_file(self):
        boundary = "----XB"
        body = (b"--" + boundary.encode() + b"\r\n"
                b'Content-Disposition: form-data; name="file"; filename="a.png"\r\n'
                b"Content-Type: image/png\r\n\r\n" + b"\x89PNG\r\n"
                + b"--" + boundary.encode() + b"--\r\n")
        fname, data = ps.parse_multipart(body, "multipart/form-data; boundary=" + boundary)
        self.assertEqual(fname, "a.png")
        self.assertEqual(data, b"\x89PNG")

    def test_missing_boundary_raises(self):
        with self.assertRaises(ValueError):
            ps.parse_multipart(b"x", "multipart/form-data")


def _wait_for_state(job, state, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with job.lock:
            if job.state == state:
                return True
        time.sleep(0.05)
    return False


class WorkerCancelTest(unittest.TestCase):
    """取消状态机单测（确定性，不依赖 oemer/GPU）。"""

    def test_cancel_sets_cancelled(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = ps.JobManager(d)

            def slow_run(mgr, job):            # 先置 running，再阻塞模拟识别中
                mgr.set_state(job, ps.JobState.RUNNING, "extract", "识别中…")
                job.cancel_event.wait(timeout=10)

            with mock.patch.object(ps, "_run_engine", side_effect=slow_run):
                job = mgr.create(".png")
                t = threading.Thread(target=ps.run_worker, args=(job, mgr),
                                     daemon=True)
                t.start()
                self.assertTrue(_wait_for_state(job, "running"),
                                "worker 应进入 running")
                self.assertTrue(mgr.cancel(job.id))
                t.join(timeout=5)
                self.assertFalse(t.is_alive(), "worker 线程应退出")
                with job.lock:
                    self.assertEqual(job.state, "cancelled")

    def test_cancel_after_done_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = ps.JobManager(d)
            job = mgr.create(".png")
            mgr.set_state(job, ps.JobState.DONE, progress=100)
            self.assertFalse(mgr.cancel(job.id))


# ----------------------------------------------------------------------
# HTTP 集成测试（起真实服务器于回环 + 随机端口）
# ----------------------------------------------------------------------

class HttpServerTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mgr = ps.JobManager(self.tmp)
        self.httpd = ps.serve("127.0.0.1", 0, self.mgr)
        self.port = self.httpd.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()

    def tearDown(self):
        self.mgr.shutdown()
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _post(self, path, body=b"", headers=None):
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8") or "{}"
            return e.code, json.loads(raw)

    def _poll_terminal(self, job_id, timeout=20):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            _, body = self._get("/api/status/" + job_id)
            last = json.loads(body.decode("utf-8"))
            if last["state"] in ("done", "error", "cancelled"):
                return last
            time.sleep(0.2)
        self.fail("轮询超时，最后状态: %r" % (last,))

    def test_root_serves_ui(self):
        st, body = self._get("/")
        self.assertEqual(st, 200)
        self.assertIn("谱渡 Pudu".encode("utf-8"), body)

    def test_job_id_traversal_rejected(self):
        st, body = self._get("/api/status/../../etc/passwd")
        self.assertEqual(st, 404)

    def test_status_unknown_id(self):
        st, body = self._get("/api/status/00000000-0000-4000-8000-000000000000")
        self.assertEqual(st, 404)

    def test_ocr_reject_non_image(self):
        st, j = self._post("/api/ocr", body=b"x",
                           headers={"X-Filename": "a.txt"})
        self.assertEqual(st, 400)

    @unittest.skipUnless(os.path.isfile(ps.PUDU_EXE), "Pudu.exe 不在位，跳过 fixture 冒烟")
    def test_fixture_http_smoke(self):
        st, j = self._post("/api/ocr?demo=1")
        self.assertEqual(st, 200)
        self.assertTrue(j["demo"])
        job_id = j["job_id"]
        s = self._poll_terminal(job_id)
        self.assertEqual(s["state"], "done")

        st, body = self._get("/api/result/%s/jianpu.html" % job_id)
        self.assertEqual(st, 200)
        self.assertIn(b"OMR Fixture Sample", body)

        st, body = self._get("/api/result/%s/final.musicxml" % job_id)
        self.assertEqual(st, 200)
        root = ET.fromstring(body)
        self.assertEqual(_local(root.tag), "score-partwise")

        st, body = self._get("/api/result/%s/review.json" % job_id)
        self.assertEqual(st, 200)
        rev = json.loads(body.decode("utf-8"))
        self.assertEqual(rev["total"], 0)

    @unittest.skipUnless(os.path.isfile(ps.PUDU_EXE), "Pudu.exe 不在位，跳过")
    def test_ocr_raw_body_upload(self):
        png = ps._placeholder_png()
        st, j = self._post("/api/ocr?demo=1", body=png, headers={
            "Content-Type": "application/octet-stream",
            "X-Filename": "song.png"})
        self.assertEqual(st, 200)
        s = self._poll_terminal(j["job_id"])
        self.assertEqual(s["state"], "done")

    @mock.patch.object(ps, "PUDU_EXE", os.path.join(os.sep, "nonexistent", "Pudu.exe"))
    def test_error_pudu_missing(self):
        st, j = self._post("/api/ocr?demo=1")
        self.assertEqual(st, 200)
        s = self._poll_terminal(j["job_id"], timeout=10)
        self.assertEqual(s["state"], "error")
        self.assertIn("Pudu.exe 缺失", s["error"])


if __name__ == "__main__":
    unittest.main()
