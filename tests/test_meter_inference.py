# -*- coding: utf-8 -*-
"""拍号推断 + <time> 注入（方案1）单测。

背景（docs/ 决策 + build/_meter_proto*.py 定稿）：oemer 不检测拍号 → pred MusicXML
无 <time> → C++ 渲染器回退默认 4/4，语料 7/15 页标题拍号与每小节对账目标错。
本模块双信号推断：几何 span（优先）→ 时值 fill（仅当 span 不可得）→ None（保留默认）。

覆盖：
  * span 信号：4/4、3/4、2/4 各一组相干小节 → (beats, 4)
  * span 可得但不相干（两拍数平票）→ None（映射可能损坏，弃判不回落 fill）
  * fill 兜底（无 sidecar）：4/4、6/4 → (beats, 4)
  * 优先级：span 相干时 fill 不同也采 span
  * 注入：<time> 落在 <key> 之后、值正确；二次注入幂等；已有 <time> 时更新不重复
  * 推断失败 → 不改文件（字节不变）

纯 stdlib（xml.etree.ElementTree + json），不依赖 oemer / numpy。
"""
import json
import os
import sys
import tempfile
import unittest

import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import geometric_pitch as gp  # noqa: E402

DIVISIONS = 16  # 1 分音符 = 16 单位；16 分 = 4、4 分 = 16
UNIT = 10.0     # 几何约定：1 个 16 分间距 = 10px

_QL_TO_TYPE = {0.25: "16th", 0.5: "eighth", 1.0: "quarter", 2.0: "half", 4.0: "whole"}


def _ql_to_dur(ql):
    return int(ql * DIVISIONS)


def build_score(notes_spec, with_key=False, time=None):
    """构造最小 score-partwise（measure 1 含 attributes；可含 <key> / 既有 <time>）。

    Args:
        notes_spec: 元素为 dict：``ql``（时值）、``measure``（小节号，默认 1）、
            ``x``（几何 x，仅进 sidecar）、``rest``（True=休止）。
        with_key: measure 1 attributes 追加 ``<key><fifths>N</fifths></key>``
            （镜像 oemer 输出，供断言 <time> 落在 <key> 之后的 DTD 子序）。
        time: ``(beats, beat_type)`` 元组；给定则 measure 1 预置 <time>（测幂等更新）。
    """
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    measures = {}
    for spec in notes_spec:
        num = str(spec.get("measure", 1))
        if num not in measures:
            m = ET.SubElement(part, "measure", attrib={"number": num})
            if num == "1":
                attrs = ET.SubElement(m, "attributes")
                ET.SubElement(attrs, "divisions").text = str(DIVISIONS)
                if with_key:
                    key = ET.SubElement(attrs, "key")
                    ET.SubElement(key, "fifths").text = "1"
                if time:
                    t = ET.SubElement(attrs, "time")
                    ET.SubElement(t, "beats").text = str(time[0])
                    ET.SubElement(t, "beat-type").text = str(time[1])
            measures[num] = m
        note = ET.SubElement(measures[num], "note")
        # 镜像 oemer：每个 <note> 都带 <voice>（_measure_fill_ql 按声部求和）
        ET.SubElement(note, "voice").text = spec.get("voice", "1")
        if spec.get("rest"):
            ET.SubElement(note, "rest")
            ET.SubElement(note, "duration").text = str(_ql_to_dur(spec["ql"]))
            continue
        pitch = ET.SubElement(note, "pitch")
        ET.SubElement(pitch, "step").text = spec.get("step", "C")
        ET.SubElement(pitch, "octave").text = str(spec.get("octave", 3))
        ET.SubElement(note, "duration").text = str(_ql_to_dur(spec["ql"]))
        tp = spec.get("type")
        if tp is None:
            tp = _QL_TO_TYPE.get(spec["ql"])
        if tp:
            ET.SubElement(note, "type").text = tp
    return root


def build_sidecar(notes_spec):
    """sidecar JSON dict（发射序 1:1 = 非休止音符文档序；仅 x 参与 span 信号）。"""
    g_notes = []
    idx = 0
    for spec in notes_spec:
        if spec.get("rest"):
            continue
        x = spec.get("x", (idx + 1) * UNIT)
        g_notes.append({
            "id": idx, "track": 0, "group": 0,
            "bbox": [x, 95.0, x + 5.0, 105.0],
            "center": [x, 100.0],
            "ink_centroid": [x, 100.0],
            "staff_line_pos": 1, "sfn": None,
        })
        idx += 1
    doc = {
        "schema_version": 1, "source_image": "test.png",
        "musicxml": "test.musicxml", "coordinate_space": "pixel_model",
        "note_order": "oemer_emission",
        "staves": [{
            "staff_id": 0, "track": 0, "group": 0, "unit_size": UNIT,
            "y_center": 100.0,
            "lines": [{"y_center": 120.0 - i * 10.0, "thickness": 1.0}
                      for i in range(5)],
        }],
        "clefs": [{"track": 0, "type": "G", "line": None,
                   "x_center": 5.0, "y_center": 100.0, "sign": "G"}],
        "notes": g_notes,
    }
    return doc


def _tmp_path(prefix="meter_"):
    return tempfile.mkdtemp(prefix=prefix)


def write_pair(notes_spec, with_key=False, time=None, prefix="meter_", with_sidecar=True):
    """score + sidecar 写盘；with_sidecar=False 时只写 score（fill 兜底路径）。"""
    tmp = _tmp_path(prefix)
    mx_path = os.path.join(tmp, "x.musicxml")
    ET.ElementTree(build_score(notes_spec, with_key=with_key, time=time)).write(
        mx_path, encoding="UTF-8", xml_declaration=True)
    if with_sidecar:
        sc_path = os.path.join(tmp, "x.geometry.json")
        with open(sc_path, "w", encoding="utf-8") as f:
            json.dump(build_sidecar(notes_spec), f)
    else:
        sc_path = None
    return mx_path, sc_path


def anchors(n, measure=1, ql=0.25):
    """n 个等距 16 分锚点（x=10/20/...，供 _calibrate_unit 校准 unit=UNIT）。"""
    return [{"ql": ql, "measure": measure, "x": (i + 1) * UNIT} for i in range(n)]


def span_measures(span_px, n_meas=3, x0=10, start=2):
    """n 个小节各 2 音符跨 span_px（x0 → x0+span_px），逐小节连续成组。

    组序镜像语料：oemer 每小节音符在 MusicXML 与 sidecar 中同为文档序，
    因此 notes_spec 必须按「小节 → 小节内音符」连续排布，跨小节交错会破坏
    sidecar↔MusicXML 的 1:1 发射序映射（R-geo 同约定）。
    调用方以 ``anchors(40) + span_measures(...) + span_measures(...)`` 拼接，
    保证 measure 1 锚点整体在前、各测试小节块依次连续。
    """
    out = []
    for m in range(start, start + n_meas):
        out.append({"ql": 1.0, "measure": m, "x": x0})
        out.append({"ql": 1.0, "measure": m, "x": x0 + span_px})
    return out


def _clean(path):
    tree = ET.parse(path)
    root = tree.getroot()
    gp._strip_ns(root)
    return root


def _first_time(path):
    root = _clean(path)
    return root.find("./part/measure[@number='1']/attributes/time")


# ===================== span 信号 =====================
class TestSpanSignal(unittest.TestCase):
    def test_four_four(self):
        # 3 小节各跨 160px = 16 个 16 分单位 → 4 拍
        mx, sc = write_pair(anchors(40) + span_measures(16 * UNIT))
        self.assertEqual(gp.infer_meter(mx, sc), (4, 4))

    def test_three_four(self):
        mx, sc = write_pair(anchors(40) + span_measures(12 * UNIT))
        self.assertEqual(gp.infer_meter(mx, sc), (3, 4))

    def test_two_four(self):
        mx, sc = write_pair(anchors(40) + span_measures(8 * UNIT))
        self.assertEqual(gp.infer_meter(mx, sc), (2, 4))

    def test_incoherent_span_returns_none(self):
        # 小节 2-4 跨 8 单位（2 拍）+ 小节 5-7 跨 24 单位（6 拍）→ 3:3 平票 → 弃判
        notes = anchors(40) + span_measures(8 * UNIT, n_meas=3, start=2)
        notes += span_measures(24 * UNIT, n_meas=3, start=5)
        mx, sc = write_pair(notes)
        self.assertIsNone(gp.infer_meter(mx, sc))

    def test_span_wins_over_contradictory_fill(self):
        # span 相干 4 拍，但 fill 每小节仅 2 拍（2 个 4 分）→ 采 span，不回落 fill
        mx, sc = write_pair(anchors(40) + span_measures(16 * UNIT))
        self.assertEqual(gp.infer_meter(mx, sc), (4, 4))


# ===================== fill 兜底（无 sidecar） =====================
class TestFillFallback(unittest.TestCase):
    def test_four_four_no_sidecar(self):
        # 3 小节各 4 个 4 分 → fill=4.0 → (4,4)
        notes = [{"ql": 1.0, "measure": m} for m in range(1, 4) for _ in range(4)]
        mx, _ = write_pair(notes, with_sidecar=False)
        self.assertEqual(gp.infer_meter(mx, None), (4, 4))

    def test_six_four_no_sidecar(self):
        notes = [{"ql": 1.0, "measure": m} for m in range(1, 4) for _ in range(6)]
        mx, _ = write_pair(notes, with_sidecar=False)
        self.assertEqual(gp.infer_meter(mx, None), (6, 4))

    def test_incoherent_fill_returns_none(self):
        # 3 小节 fill 各不同（2.0/3.0/6.0 → 1:1:1 平票）→ 无众数 → None
        notes = []
        for m, n in zip(range(1, 4), (2, 3, 6)):
            notes += [{"ql": 1.0, "measure": m} for _ in range(n)]
        mx, _ = write_pair(notes, with_sidecar=False)
        self.assertIsNone(gp.infer_meter(mx, None))


# ===================== <time> 注入 =====================
class TestInjection(unittest.TestCase):
    def test_inject_after_key(self):
        # 4/4 相干 span；<time> 须落在 <key> 之后（DTD 子序 divisions, key, time）
        mx, sc = write_pair(anchors(40) + span_measures(16 * UNIT), with_key=True)
        self.assertEqual(gp.inject_time_signature(mx, sc), (4, 4))
        attrs = _clean(mx).find("./part/measure[@number='1']/attributes")
        tags = [el.tag for el in attrs]
        self.assertLess(tags.index("key"), tags.index("time"))
        t = attrs.find("time")
        self.assertEqual(t.findtext("beats"), "4")
        self.assertEqual(t.findtext("beat-type"), "4")

    def test_inject_into_first_attributes(self):
        # <time> 只进 measure 1 的 attributes；其他小节无重复
        mx, sc = write_pair(anchors(40) + span_measures(16 * UNIT))
        self.assertEqual(gp.inject_time_signature(mx, sc), (4, 4))
        root = _clean(mx)
        times = root.findall(".//time")
        self.assertEqual(len(times), 1)
        self.assertIsNotNone(_first_time(mx))

    def test_inject_idempotent_single_time(self):
        mx, sc = write_pair(anchors(40) + span_measures(12 * UNIT))
        self.assertEqual(gp.inject_time_signature(mx, sc), (3, 4))
        self.assertEqual(gp.inject_time_signature(mx, sc), (3, 4))
        root = _clean(mx)
        self.assertEqual(len(root.findall(".//time")), 1)
        t = root.find(".//time")
        self.assertEqual(t.findtext("beats"), "3")

    def test_existing_time_updated_in_place(self):
        # 既有 <time>2/4</time> → 注入 4/4 时原位更新，不新增
        mx, sc = write_pair(anchors(40) + span_measures(16 * UNIT), time=(2, 4))
        self.assertEqual(gp.inject_time_signature(mx, sc), (4, 4))
        root = _clean(mx)
        self.assertEqual(len(root.findall(".//time")), 1)
        t = root.find(".//time")
        self.assertEqual(t.findtext("beats"), "4")
        self.assertEqual(t.findtext("beat-type"), "4")

    def test_no_change_when_inference_none(self):
        # 平票 → 推断 None → 不改文件（字节不变）
        notes = anchors(40) + span_measures(8 * UNIT, n_meas=3, start=2)
        notes += span_measures(24 * UNIT, n_meas=3, start=5)
        mx, sc = write_pair(notes)
        with open(mx, "rb") as f:
            before = f.read()
        self.assertIsNone(gp.inject_time_signature(mx, sc))
        with open(mx, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
