# -*- coding: utf-8 -*-
"""低置信度标记（需校对 footnote）单测：F3/R-geo B 计划跳过打标。

覆盖（docs/product-status.md §5 决策，仅 MusicXML；读短嫌疑已按 2026-08-10
实测丢弃——196 读短簇几何+beam 双盲，抓 0 真读短）：
  * F3 五个 B 计划跳过分支 → `<notations><footnote>需校对：几何音高未验证`
    （percussion 谱号 / 4 线谱表 / cy 可疑各一例）
  * R-geo B 计划跳过（非标准 class）→ `几何时值未校正`
  * 干净可校正音符 → 不打标；仅缩守卫命中 → 不打标（含读短嫌疑阈值在内）
  * sidecar 缺失 → 返回 0 且字节不变（F3 与 R-geo）
  * F3→R-geo 跨 pass：同一音符恰一个 footnote、原因以「；」合并
  * F3 二次运行幂等；_mark_needs_review 单测

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

DIVISIONS = 16  # 1 分音符 = 16 单位；16 分 = 4、8 分 = 8、4 分 = 16、2 分 = 32
UNIT = 10.0     # 几何约定：1 个 16 分间距 = 10px

_QL_TO_TYPE = {0.25: "16th", 0.5: "eighth", 1.0: "quarter", 2.0: "half", 4.0: "whole"}


def _ql_to_dur(ql):
    return int(ql * DIVISIONS)


def build_score(notes_spec):
    """构造最小 score-partwise。

    Args:
        notes_spec: 元素为 dict：
            - ``ql``: quarterLength（决定 ``<duration>``）
            - ``measure``: 小节号（默认 1）
            - ``x``: 该音符几何 x（默认按出现序 10/20/30...，仅进 sidecar）
            - ``rest``: True 表示休止符（无 pitch，不参与 sidecar 映射）
            - ``step/alter/octave``: 初始音高（默认 C/0/3，F3 可被覆盖）
            - ``type``: 显式 ``<type>`` 文本（默认按 ql 映射）
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
            measures[num] = m
        note = ET.SubElement(measures[num], "note")
        if spec.get("rest"):
            ET.SubElement(note, "rest")
            ET.SubElement(note, "duration").text = str(_ql_to_dur(spec["ql"]))
            continue
        pitch = ET.SubElement(note, "pitch")
        ET.SubElement(pitch, "step").text = spec.get("step", "C")
        ET.SubElement(pitch, "alter").text = str(spec.get("alter", 0))
        ET.SubElement(pitch, "octave").text = str(spec.get("octave", 3))
        ET.SubElement(note, "duration").text = str(_ql_to_dur(spec["ql"]))
        tp = spec.get("type")
        if tp is None:
            tp = _QL_TO_TYPE.get(spec["ql"])
        if tp:
            ET.SubElement(note, "type").text = tp
    return root


def build_sidecar(notes_spec, n_lines=5, clef_type="G"):
    """从 notes_spec 构造 sidecar JSON dict（发射序 1:1 = 非休止音符文档序）。

    每个 spec 支持：
        x:           几何 x（默认 10/20/...）
        ink_y:       墨迹质心 y（默认 100；999 触发 F3 cy 可疑跳过）
        staff_line_pos: oemer 原猜 diatonic pos（默认 1）
    """
    g_notes = []
    idx = 0
    for spec in notes_spec:
        if spec.get("rest"):
            continue
        x = spec.get("x", (idx + 1) * UNIT)
        ink_y = spec.get("ink_y", 100.0)
        g_notes.append({
            "id": idx,
            "track": 0,
            "group": 0,
            "bbox": [x, ink_y - 5.0, x + 5.0, ink_y + 5.0],
            "center": [x, ink_y],
            "ink_centroid": [x, ink_y],
            "staff_line_pos": spec.get("staff_line_pos", 1),
            "sfn": None,
        })
        idx += 1
    step = 40.0 / (n_lines - 1) if n_lines > 1 else 0.0
    doc = {
        "schema_version": 1,
        "source_image": "test.png",
        "musicxml": "test.musicxml",
        "coordinate_space": "pixel_model",
        "note_order": "oemer_emission",
        "staves": [{
            "staff_id": 0, "track": 0, "group": 0, "unit_size": UNIT,
            "y_center": 100.0,
            "lines": [{"y_center": 120.0 - i * step, "thickness": 1.0}
                      for i in range(n_lines)],
        }],
        "clefs": [{"track": 0, "type": clef_type, "line": None,
                   "x_center": 5.0, "y_center": 100.0, "sign": clef_type}],
        "notes": g_notes,
    }
    return doc


def write_pair(notes_spec, n_lines=5, clef_type="G", prefix="mark_"):
    """score + sidecar 写盘，返回 (mx_path, sidecar_path)。"""
    tmp = tempfile.mkdtemp(prefix=prefix)
    root = build_score(notes_spec)
    mx_path = os.path.join(tmp, "x.musicxml")
    sc_path = os.path.join(tmp, "x.geometry.json")
    ET.ElementTree(root).write(mx_path, encoding="UTF-8", xml_declaration=True)
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(build_sidecar(notes_spec, n_lines=n_lines, clef_type=clef_type), f)
    return mx_path, sc_path


def read_footnotes(root):
    """返回 {非休止音符文档序索引: footnote 文本或 None}。"""
    out = {}
    idx = 0
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        fns = note.findall(".//footnote")
        out[idx] = fns[0].text if fns else None
        idx += 1
    return out


def parse_clean(path):
    tree = ET.parse(path)
    root = tree.getroot()
    gp._strip_ns(root)
    return root


def anchors(n, measure=1, ql=0.25):
    """n 个等距 16 分锚点（x=10/20/...，供 R-geo 校准）。"""
    return [{"ql": ql, "measure": measure, "x": (i + 1) * UNIT} for i in range(n)]


# ===================== _mark_needs_review 单测 =====================
class TestMarkHelper(unittest.TestCase):
    def test_fresh_note_returns_true(self):
        note = ET.Element("note")
        self.assertTrue(gp._mark_needs_review(note, gp._REASON_PITCH_SKIP))
        fn = note.find("./notations/footnote")
        self.assertIsNotNone(fn)
        self.assertEqual(fn.text, "需校对：几何音高未验证")

    def test_same_reason_idempotent(self):
        note = ET.Element("note")
        self.assertTrue(gp._mark_needs_review(note, gp._REASON_PITCH_SKIP))
        self.assertFalse(gp._mark_needs_review(note, gp._REASON_PITCH_SKIP))
        self.assertEqual(len(note.findall(".//footnote")), 1)

    def test_merge_different_reasons_single_footnote(self):
        note = ET.Element("note")
        gp._mark_needs_review(note, gp._REASON_PITCH_SKIP)
        self.assertTrue(gp._mark_needs_review(note, gp._REASON_RHYTHM_SKIP))
        fns = note.findall(".//footnote")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].text, "需校对：几何音高未验证；几何时值未校正")

    def test_footnote_inserted_before_tuplet(self):
        note = ET.Element("note")
        notations = ET.SubElement(note, "notations")
        ET.SubElement(notations, "tuplet")
        gp._mark_needs_review(note, gp._REASON_PITCH_SKIP)
        ns = note.find("notations")
        self.assertEqual(ns[0].tag, "footnote")
        self.assertEqual(ns.find("footnote"), ns[0])


# ===================== F3 标记 =====================
class TestF3Marking(unittest.TestCase):
    def test_percussion_clef_marked(self):
        mx, sc = write_pair([{"ql": 1.0, "type": "quarter"}], clef_type="percussion")
        n = gp.recompute_pitch_from_geometry(mx, sc)
        self.assertEqual(n, 0)
        root = parse_clean(mx)
        fns = root.findall(".//footnote")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].text, "需校对：几何音高未验证")

    def test_four_line_staff_marked(self):
        mx, sc = write_pair([{"ql": 1.0, "type": "quarter"}], n_lines=4)
        n = gp.recompute_pitch_from_geometry(mx, sc)
        self.assertEqual(n, 0)
        root = parse_clean(mx)
        fns = root.findall(".//footnote")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].text, "需校对：几何音高未验证")

    def test_cy_suspicious_marked(self):
        # ink_y=999 → 几何 pos 距 oemer 原猜 staff_line_pos=1 偏差 176 > 16 → 跳过打标
        mx, sc = write_pair([{"ql": 1.0, "type": "quarter", "ink_y": 999.0}])
        n = gp.recompute_pitch_from_geometry(mx, sc)
        self.assertEqual(n, 0)
        root = parse_clean(mx)
        fns = root.findall(".//footnote")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].text, "需校对：几何音高未验证")

    def test_clean_corrected_no_footnote(self):
        mx, sc = write_pair([{"ql": 1.0, "type": "quarter"}])
        n = gp.recompute_pitch_from_geometry(mx, sc)
        self.assertEqual(n, 1)
        root = parse_clean(mx)
        self.assertIsNone(root.find(".//notations"))

    def test_missing_sidecar_byte_unchanged(self):
        mx, _ = write_pair([{"ql": 1.0, "type": "quarter"}])
        with open(mx, "rb") as f:
            before = f.read()
        n = gp.recompute_pitch_from_geometry(
            mx, os.path.join(os.path.dirname(mx), "nope.geometry.json"))
        self.assertEqual(n, 0)
        with open(mx, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_f3_twice_single_footnote(self):
        mx, sc = write_pair([{"ql": 1.0, "type": "quarter"}], clef_type="percussion")
        self.assertEqual(gp.recompute_pitch_from_geometry(mx, sc), 0)
        self.assertEqual(gp.recompute_pitch_from_geometry(mx, sc), 0)
        root = parse_clean(mx)
        self.assertEqual(len(root.findall(".//footnote")), 1)


# ===================== R-geo 标记 =====================
class TestRGeoMarking(unittest.TestCase):
    def _build(self, notes_spec):
        fd, mx_path = tempfile.mkstemp(suffix=".musicxml")
        os.close(fd)
        sc_path = mx_path.replace(".musicxml", ".geometry.json")
        try:
            ET.ElementTree(build_score(notes_spec)).write(
                mx_path, encoding="UTF-8", xml_declaration=True)
            with open(sc_path, "w", encoding="utf-8") as f:
                json.dump(build_sidecar(notes_spec), f)
            n = gp.recompute_rhythm_from_geometry(mx_path, sc_path)
            return n, parse_clean(mx_path)
        finally:
            for p in (mx_path, sc_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_read_short_suspect_guard_no_mark(self):
        # measure1: 40 个 16 分锚点（校准 unit=10）
        # measure2: X=16分(x=10) 仅 g_next=80 → class8 > 2*current1（读短嫌疑阈值）
        #           命中 only-shrink 守卫，但读短标记已按决策丢弃 → 不打标
        #           Y=half(x=90)  g_prev=80 → class8 == current8 → 也不打标
        notes = anchors(40)
        notes.append({"ql": 0.25, "measure": 2, "x": 1 * UNIT})    # X
        notes.append({"ql": 2.0, "measure": 2, "x": 9 * UNIT})     # Y
        n, r = self._build(notes)
        self.assertEqual(n, 0)
        fns = read_footnotes(r)
        self.assertTrue(all(fns[i] is None for i in range(41)))
        self.assertIsNone(fns[41])

    def test_nonstandard_class_marked_guard_not(self):
        # measure2 两个 16 分相距 6*UNIT → cls=6 非标准 → 几何时值未校正
        # 锚点本身命中 only-shrink 守卫（cls=1 == current）→ 不打标
        notes = anchors(40)
        notes.append({"ql": 0.25, "measure": 2, "x": 1 * UNIT})
        notes.append({"ql": 0.25, "measure": 2, "x": 7 * UNIT})    # gap 6*UNIT
        n, r = self._build(notes)
        self.assertEqual(n, 0)
        fns = read_footnotes(r)
        self.assertTrue(all(fns[i] is None for i in range(40)))
        self.assertEqual(fns[40], "需校对：几何时值未校正")
        self.assertEqual(fns[41], "需校对：几何时值未校正")

    def test_clean_rewrite_no_footnote(self):
        # 40 锚点 + 4 个被读长的 4 分（等距 16 分网格）→ 缩回 16 分，无任何标记
        notes = anchors(40) + [{"ql": 1.0} for _ in range(4)]
        n, r = self._build(notes)
        self.assertEqual(n, 4)
        self.assertIsNone(r.find(".//notations"))

    def test_ambiguous_boundary_not_shrunk_not_marked(self):
        # measure2: 两个 8 分相距 1.45*UNIT（比值 1.45 → 贴近 1.5 边界的模糊区）。
        # 置信窗 _RHYTHM_SIDE_CONFIDENCE=0.25 排除该侧 → 全部模糊 → 不改写也不打标
        # （2026-08-10 重跑过缩修复：模糊区 81.6% 在 GT 非 16 分，保守不动）。
        notes = anchors(40)
        notes.append({"ql": 0.5, "measure": 2, "x": 1 * UNIT})
        notes.append({"ql": 0.5, "measure": 2, "x": 2.45 * UNIT})
        n, r = self._build(notes)
        self.assertEqual(n, 0)
        fns = read_footnotes(r)
        self.assertTrue(all(fns[i] is None for i in range(42)))


# ===================== 跨 pass 去重 =====================
class TestCrossPass(unittest.TestCase):
    def test_f3_then_rgeo_single_footnote_merged(self):
        # measure1: 40 锚点（F3 可校正、R-geo 校准）
        # measure2: X(ink_y=999 → F3 cy 可疑跳过打标；gap 6*UNIT → R-geo 非标准 class)
        #           + Y(8 分，gap 6*UNIT → R-geo 非标准 class)
        # F3 给 X 打「几何音高未验证」；R-geo 在 X 现有 footnote 上追加「几何时值未校正」
        # → X 恰一个 footnote、含两原因；Y 仅被 R-geo 打「几何时值未校正」。
        notes = anchors(40)
        notes.append({"ql": 0.25, "measure": 2, "x": 1 * UNIT, "ink_y": 999.0})
        notes.append({"ql": 0.5, "measure": 2, "x": 7 * UNIT})
        mx, sc = write_pair(notes)
        n1 = gp.recompute_pitch_from_geometry(mx, sc)
        n2 = gp.recompute_rhythm_from_geometry(mx, sc)
        root = parse_clean(mx)
        self.assertEqual(n1, 41)  # 40 锚点 + Y 被校正
        self.assertEqual(n2, 0)   # 无改写（X、Y 均为非标准 class，只打标）
        fns = [f.text for f in root.findall(".//footnote")]
        x_fn = [t for t in fns if "几何音高未验证" in t]
        self.assertEqual(len(x_fn), 1)  # X 恰一个 footnote，跨 pass 去重
        self.assertIn("几何时值未校正", x_fn[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
