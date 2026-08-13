# -*- coding: utf-8 -*-
"""Audiveris 适配层（tools/omr_audiveris.py）单测。

覆盖：
  * resolve_audiveris_exe：env → 仓库默认 → PATH 三级选址；显式缺失 → None。
  * count_pdf_pages：/Count 解析与 /Type/Page 退化计数。
  * build_av_cmd：PNG 无 -sheets / PDF 有 -sheets N；flag 顺序。
  * extract_mxl：ZIP 内同名 .xml 解出（跳过 META-INF）。
  * locate_export：平铺 / 嵌套 / 唯一兜底三种布局。
  * merge_pages：顺序重编号、跨页 divisions 重算守卫、页 2 attributes 保留。
  * main 流程（mock AV）：fifths 不被覆盖（禁 keysig fallback）、拍号打标。
  * 真实冒烟（@skipUnless AV exe 在位）：canon PDF 坏页跳过、bach PDF 3 页拼接。

纯 stdlib（xml.etree / zipfile / unittest + mock），不依赖 oemer / numpy。
"""
import os
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest import mock

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_audiveris as oa  # noqa: E402


def _make_mxl(path, xml_name, xml_content):
    """构造合法 .mxl（ZIP 内含 <name>.xml + META-INF/container.xml）。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(xml_name, xml_content)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container><rootfiles/></container>')


def _simple_xml(fifths="2", note_durs=("1", "1")):
    """构造 AV 风格 score-partwise（单 part P1、1 小节、divisions=1）。"""
    root = ET.Element("score-partwise", {"version": "4.0.3"})
    part = ET.SubElement(root, "part", {"id": "P1"})
    m = ET.SubElement(part, "measure", {"number": "1"})
    attrs = ET.SubElement(m, "attributes")
    ET.SubElement(attrs, "divisions").text = "1"
    key = ET.SubElement(attrs, "key")
    ET.SubElement(key, "fifths").text = fifths
    tm = ET.SubElement(attrs, "time")
    ET.SubElement(tm, "beats").text = "4"
    ET.SubElement(tm, "beat-type").text = "4"
    for dur in note_durs:
        n = ET.SubElement(m, "note")
        pitch = ET.SubElement(n, "pitch")
        ET.SubElement(pitch, "step").text = "C"
        ET.SubElement(pitch, "octave").text = "4"
        ET.SubElement(n, "duration").text = dur
    tree = ET.ElementTree(root)
    buf = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    buf.close()
    tree.write(buf.name, encoding="UTF-8", xml_declaration=True)
    with open(buf.name, "r", encoding="utf-8") as f:
        return f.read()


class ResolveExeTest(unittest.TestCase):

    def test_env_present(self):
        with mock.patch.dict(os.environ, {"PUDU_AUDIVERIS_EXE": "C:/x/Audiveris.exe"}), \
             mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(oa.resolve_audiveris_exe(), "C:/x/Audiveris.exe")

    def test_env_set_but_missing_returns_none(self):
        with mock.patch.dict(os.environ, {"PUDU_AUDIVERIS_EXE": "C:/missing.exe"}), \
             mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(oa.resolve_audiveris_exe())

    def test_default_path_used(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(oa.resolve_audiveris_exe(), oa._DEFAULT_EXE)

    def test_which_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("os.path.isfile", return_value=False), \
             mock.patch("shutil.which", return_value="C:/PATH/Audiveris.exe"):
            self.assertEqual(oa.resolve_audiveris_exe(), "C:/PATH/Audiveris.exe")


class CountPdfPagesTest(unittest.TestCase):

    def test_count_field(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.pdf")
            with open(p, "wb") as f:
                f.write(b"%PDF-1.4\n/Count 3\n/Pages\n/Count 1\n")
            self.assertEqual(oa.count_pdf_pages(p), 3)

    def test_type_page_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.pdf")
            with open(p, "wb") as f:
                f.write(b"/Type/Page\n/Type /Page\n/Type/Pages\n/Type/Page\n")
            self.assertEqual(oa.count_pdf_pages(p), 3)


class BuildAvCmdTest(unittest.TestCase):

    def test_single(self):
        self.assertEqual(
            oa.build_av_cmd("av.exe", "in.png", "out"),
            ["av.exe", "-batch", "-export", "-output", "out", "--", "in.png"])

    def test_sheet(self):
        self.assertEqual(
            oa.build_av_cmd("av.exe", "in.pdf", "out", sheet=2),
            ["av.exe", "-batch", "-export", "-sheets", "2",
             "-output", "out", "--", "in.pdf"])


class ExtractMxlTest(unittest.TestCase):

    def test_extract_skips_meta_inf(self):
        with tempfile.TemporaryDirectory() as d:
            mxl = os.path.join(d, "book.mxl")
            _make_mxl(mxl, "book.xml", "<score-partwise/>")
            out = os.path.join(d, "out.xml")
            self.assertTrue(oa.extract_mxl(mxl, out))
            with open(out, "r", encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "<score-partwise/>")

    def test_extract_missing_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.xml")
            self.assertFalse(oa.extract_mxl(os.path.join(d, "none.mxl"), out))


class LocateExportTest(unittest.TestCase):

    def test_flat(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "book.mxl")
            open(p, "w").close()
            self.assertEqual(oa.locate_export(d, "book"), p)

    def test_nested(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "book")
            os.makedirs(sub)
            p = os.path.join(sub, "book.mxl")
            open(p, "w").close()
            self.assertEqual(oa.locate_export(d, "book"), p)

    def test_single_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "whatever.mxl")
            open(p, "w").close()
            self.assertEqual(oa.locate_export(d, "book"), p)


class MergePagesTest(unittest.TestCase):

    @staticmethod
    def _two_page_xml(path, base_num=1, divisions="8"):
        root = ET.Element("score-partwise", {"version": "4.0.3"})
        part = ET.SubElement(root, "part", {"id": "P1"})
        for i in range(2):
            m = ET.SubElement(part, "measure", {"number": str(base_num + i)})
            attrs = ET.SubElement(m, "attributes")
            ET.SubElement(attrs, "divisions").text = divisions
            n = ET.SubElement(m, "note")
            ET.SubElement(n, "duration").text = "1"
        tree = ET.ElementTree(root)
        tree.write(path, encoding="UTF-8", xml_declaration=True)

    def test_renumbers_and_keeps_attributes(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = os.path.join(d, "p1.xml")
            p2 = os.path.join(d, "p2.xml")
            out = os.path.join(d, "out.musicxml")
            self._two_page_xml(p1, base_num=1)
            self._two_page_xml(p2, base_num=1)   # 页 2 也从 1 起 → 必须重编号
            n = oa.merge_pages([p1, p2], out)
            self.assertEqual(n, 4)
            root = ET.parse(out).getroot()
            nums = [int(m.attrib["number"]) for m in root.findall("part")[0]]
            self.assertEqual(nums, [1, 2, 3, 4])
            # 每小节 attributes/divisions 保留
            measures = root.findall("part")[0].findall("measure")
            self.assertEqual(len(measures), 4)
            for m in measures:
                self.assertIsNotNone(m.find("attributes/divisions"))

    def test_divisions_rescale(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = os.path.join(d, "p1.xml")
            p2 = os.path.join(d, "p2.xml")
            out = os.path.join(d, "out.musicxml")
            self._two_page_xml(p1, divisions="8")   # 页 1 divisions=8
            self._two_page_xml(p2, divisions="4")   # 页 2 divisions=4
            oa.merge_pages([p1, p2], out)
            root = ET.parse(out).getroot()
            durs = [int(dur.text) for dur in root.iter("duration")]
            # 页 1 两条 duration=1（div8）；页 2 两条 duration=1（div4）→ 换算为 2
            self.assertEqual(durs, [1, 1, 2, 2])


class MainFlowTest(unittest.TestCase):
    """mock AV 的主流程：禁 keysig fallback + 拍号打标。"""

    def _run_main(self, fifths, note_durs, in_path, out_path, xml_name="fake.xml"):
        # 构造真 .mxl 供 extract_mxl 解包；mock 掉 AV 子进程
        with tempfile.TemporaryDirectory() as d:
            mxl = os.path.join(d, "fake.mxl")
            _make_mxl(mxl, xml_name, _simple_xml(fifths=fifths, note_durs=note_durs))
            with mock.patch.object(oa, "_run_audiveris", return_value=(0, "")), \
                 mock.patch.object(oa, "locate_export", return_value=mxl):
                rc = oa.main([in_path, out_path])
        return rc

    def test_png_preserves_fifths(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.png")
            open(inp, "w").close()
            out = os.path.join(d, "out.musicxml")
            rc = self._run_main("2", ("1", "1"), inp, out)
            self.assertEqual(rc, 0)
            root = ET.parse(out).getroot()
            self.assertEqual({k.text for k in root.iter("fifths")}, {"2"})
            # 无 keysig 改写 stage（AV 原生 fifths 不被统计 fallback 覆盖）
            self.assertEqual(len(list(root.iter("key"))), 1)

    def test_meter_marking(self):
        # 5 个四分音符在 4/4 小节 = 5 拍 → 打「需校对」footnote
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.png")
            open(inp, "w").close()
            out = os.path.join(d, "out.musicxml")
            rc = self._run_main("0", ("1", "1", "1", "1", "1"), inp, out)
            self.assertEqual(rc, 0)
            foots = [fn.text for fn in ET.parse(out).getroot().iter("footnote")]
            self.assertEqual(foots, ["需校对：小节节拍不符"])

    def test_missing_input_rc1(self):
        self.assertEqual(oa.main(["C:/nonexistent/in.png", "C:/out.musicxml"]), 1)

    def test_usage_rc2(self):
        self.assertEqual(oa.main(["only_input.png"]), 2)


class ResolutionRetryTest(unittest.TestCase):
    """低分辨率失败自动放大重试（2x→3x）。"""

    RES_TEXT = (
        "WARN ... With a too low interline value of 8 pixels,\n"
        "either this sheet contains no multi-line staves,\n"
        "or the picture resolution is too low (try 300 DPI).\n"
        "This interline value is NOT RELIABLE!\n"
        "Sheet ... flagged as invalid.\n"
    )

    @staticmethod
    def _mk_input(d):
        inp = os.path.join(d, "in.png")
        with open(inp, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        return inp

    def test_is_resolution_failure_matches(self):
        self.assertTrue(oa._is_resolution_failure(self.RES_TEXT))
        self.assertTrue(oa._is_resolution_failure("resolution is too low"))
        self.assertTrue(oa._is_resolution_failure(
            "With a too low interline value of 8 pixels"))
        self.assertFalse(oa._is_resolution_failure(""))
        self.assertFalse(oa._is_resolution_failure(None))
        self.assertFalse(oa._is_resolution_failure(
            "No system found on this sheet"))   # 非分辨率失败 → 不重试

    def test_upscale_image_real(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL 不可用")
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.png")
            dst = os.path.join(d, "dst.png")
            Image.new("L", (100, 50), 200).save(src)
            self.assertTrue(oa.upscale_image(src, dst, 2))
            with Image.open(dst) as im:
                self.assertEqual(im.size, (200, 100))

    def test_main_retries_upscale_then_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            inp = self._mk_input(d)
            out = os.path.join(d, "out.musicxml")
            mxl = os.path.join(d, "fake.mxl")
            _make_mxl(mxl, "fake.xml", _simple_xml(fifths="2", note_durs=("1", "1")))
            calls = {"n": 0}

            def fake_run(cmd, timeout=oa._TIMEOUT_S):
                calls["n"] += 1
                return (1, self.RES_TEXT) if calls["n"] == 1 else (0, "")

            with mock.patch.object(oa, "_run_audiveris", side_effect=fake_run), \
                 mock.patch.object(oa, "upscale_image", return_value=True), \
                 mock.patch.object(oa, "locate_export", return_value=mxl):
                rc = oa.main([inp, out])
            self.assertEqual(rc, 0)
            self.assertEqual(calls["n"], 2)   # 原图失败 1 次 + 放大重试 1 次
            root = ET.parse(out).getroot()
            self.assertEqual({k.text for k in root.iter("fifths")}, {"2"})

    def test_main_retries_then_reports_failure(self):
        with tempfile.TemporaryDirectory() as d:
            inp = self._mk_input(d)
            out = os.path.join(d, "out.musicxml")
            calls = {"n": 0}

            def fake_run(cmd, timeout=oa._TIMEOUT_S):
                calls["n"] += 1
                return (1, self.RES_TEXT)

            with mock.patch.object(oa, "_run_audiveris", side_effect=fake_run), \
                 mock.patch.object(oa, "upscale_image", return_value=True), \
                 mock.patch("sys.stderr"):
                rc = oa.main([inp, out])
            self.assertEqual(rc, 1)
            self.assertEqual(calls["n"], 3)   # 原图 + 2x + 3x 全失败

    def test_main_no_retry_on_other_failure(self):
        with tempfile.TemporaryDirectory() as d:
            inp = self._mk_input(d)
            out = os.path.join(d, "out.musicxml")
            calls = {"n": 0}

            def fake_run(cmd, timeout=oa._TIMEOUT_S):
                calls["n"] += 1
                return (1, "No system found on this sheet")

            with mock.patch.object(oa, "_run_audiveris", side_effect=fake_run), \
                 mock.patch.object(oa, "upscale_image", return_value=True) as up, \
                 mock.patch("sys.stderr"):
                rc = oa.main([inp, out])
            self.assertEqual(rc, 1)
            self.assertEqual(calls["n"], 1)   # 非分辨率失败 → 不放大
            up.assert_not_called()


@unittest.skipUnless(oa.resolve_audiveris_exe() is not None,
                     "Audiveris 未安装（build/_audiveris 或 PATH）")
class RealAvSmokeTest(unittest.TestCase):
    """真实 AV 冒烟：依赖已安装的 Audiveris.exe。"""

    DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")

    def test_canon_pdf_bad_page_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "canon.musicxml")
            rc = oa.main([os.path.join(self.DATA, "canon-in-d-violin-solo.pdf"), out])
            self.assertEqual(rc, 0)
            root = ET.parse(out).getroot()
            self.assertEqual({k.text for k in root.iter("fifths")}, {"2"})
            self.assertEqual(root.findall("part")[0].attrib["id"], "P1")

    def test_bach_pdf_three_pages_merge_continuous(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "bach.musicxml")
            rc = oa.main([os.path.join(self.DATA, "bach-cello-suite-no-1-for-violin.pdf"),
                          out])
            self.assertEqual(rc, 0)
            root = ET.parse(out).getroot()
            nums = [int(m.attrib["number"]) for m in root.findall("part")[0]]
            self.assertEqual(nums, list(range(1, len(nums) + 1)))
            self.assertEqual({k.text for k in root.iter("fifths")}, {"2"})
            self.assertGreater(len(list(root.iter("note"))), 500)


if __name__ == "__main__":
    unittest.main()
