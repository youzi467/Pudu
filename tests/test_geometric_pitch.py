# -*- coding: utf-8 -*-
"""F3 几何重算核心单元测试（纯 stdlib，无需 oemer / GPU）。

覆盖：
  * _round_half_up（round-half-up，非银行家舍入）
  * _pos_to_step_octave（与 oemer decode_note 同口径；边界 A0~C8）
  * _geometric_pos（谱线/间/加线 pos 正确；bottom=max(y) 语义）
  * recompute_pitch_from_geometry：
      - 发射序 1:1 对齐覆盖 step/octave
      - alter / 时值（duration/type）/ 休止符原样保留
      - sidecar 缺失返回 0 且不改文件（非致命）
      - 多声部按 track 分流（G/F 谱号各自 anchor）
      - 退化 B 计划：lines!=5 跳过；clef 非 G/F 跳过
"""

import os
import sys
import json
import math
import unittest
import tempfile
import xml.etree.ElementTree as ET

# 让本测试可导入 tools/geometric_pitch
TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from geometric_pitch import (  # noqa: E402
    SidecarDoc, StaffGeometry, LineGeom, ClefGeometry, NoteGeometry,
    recompute_pitch_from_geometry, _geometric_pos, _pos_to_step_octave,
    _round_half_up,
)


def make_staff(track, unit_size, bottom_y, top_y, staff_id=0, n_lines=5,
               group=0):
    """构造一个 n_lines 条谱线的 StaffGeometry（y 从 bottom 到 top 均匀）。"""
    step = (bottom_y - top_y) / (n_lines - 1) if n_lines > 1 else 0.0
    lines = [LineGeom(y_center=bottom_y - i * step) for i in range(n_lines)]
    return StaffGeometry(staff_id=staff_id, track=track, group=group,
                         unit_size=unit_size, y_center=(bottom_y + top_y) / 2.0,
                         lines=lines)


def write_musicxml(path, notes_spec):
    """notes_spec: list of {step, octave, alter, duration, type, is_rest}。"""
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    measure = ET.SubElement(part, "measure", attrib={"number": "1"})
    for ns in notes_spec:
        note = ET.SubElement(measure, "note")
        if ns.get("is_rest"):
            ET.SubElement(note, "rest")
        else:
            pitch = ET.SubElement(note, "pitch")
            s = ET.SubElement(pitch, "step")
            s.text = ns["step"]
            a = ET.SubElement(pitch, "alter")
            a.text = str(ns["alter"])
            o = ET.SubElement(pitch, "octave")
            o.text = str(ns["octave"])
        d = ET.SubElement(note, "duration")
        d.text = str(ns["duration"])
        t = ET.SubElement(note, "type")
        t.text = ns["type"]
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def first_two_notes(path):
    """读取 musicxml，返回前两个非休止音符的 (step, octave, alter, duration, type)。"""
    tree = ET.parse(path)
    root = tree.getroot()
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag
    out = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        pitch = note.find("pitch")
        step = pitch.find("step").text
        alter = pitch.find("alter").text
        octave = pitch.find("octave").text
        duration = note.find("duration").text
        typ = note.find("type").text
        out.append((step, octave, alter, duration, typ))
    return out


class TestRoundHalfUp(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(_round_half_up(0.5), 1)
        self.assertEqual(_round_half_up(2.4), 2)
        self.assertEqual(_round_half_up(2.6), 3)
        self.assertEqual(_round_half_up(1.5), 2)

    def test_negative(self):
        self.assertEqual(_round_half_up(-0.5), -1)
        self.assertEqual(_round_half_up(-2.4), -2)
        self.assertEqual(_round_half_up(-2.6), -3)
        self.assertEqual(_round_half_up(-1.5), -2)

    def test_integer(self):
        self.assertEqual(_round_half_up(3.0), 3)
        self.assertEqual(_round_half_up(-3.0), -3)


class TestPosToStepOctave(unittest.TestCase):
    def test_g_clef(self):
        # pos=0 -> D4, pos=7 -> D5, pos=-1 -> C4
        self.assertEqual(_pos_to_step_octave(0, "G"), ("D", 4))
        self.assertEqual(_pos_to_step_octave(1, "G"), ("E", 4))
        self.assertEqual(_pos_to_step_octave(7, "G"), ("D", 5))
        self.assertEqual(_pos_to_step_octave(-1, "G"), ("C", 4))
        # 底线 pos=1 -> E4
        self.assertEqual(_pos_to_step_octave(1, "G"), ("E", 4))

    def test_f_clef(self):
        self.assertEqual(_pos_to_step_octave(0, "F"), ("F", 2))
        self.assertEqual(_pos_to_step_octave(1, "F"), ("G", 2))
        self.assertEqual(_pos_to_step_octave(7, "F"), ("F", 3))

    def test_boundaries(self):
        # A0：F 谱号 pos=-12（底线 G2 为 pos1，下行 13 半音级到 A0）
        self.assertEqual(_pos_to_step_octave(-12, "F"), ("A", 0))
        # C8：G 谱号 pos=27
        self.assertEqual(_pos_to_step_octave(27, "G"), ("C", 8))
        # 非零正例：F 谱号 pos=9 -> A3
        self.assertEqual(_pos_to_step_octave(9, "F"), ("A", 3))

    def test_range_valid(self):
        # 仅在合法音域内的 pos 区间（A0..C8）检查 octv 落在 [0,8]
        for pos in range(-12, 28):
            for clef in ("G", "F"):
                step, octv = _pos_to_step_octave(pos, clef)
                self.assertIn(step, {"C", "D", "E", "F", "G", "A", "B"})
                self.assertTrue(0 <= octv <= 8,
                                f"pos={pos} clef={clef} -> {step}{octv}")


class TestGeometricPos(unittest.TestCase):
    def setUp(self):
        # 5 条谱线，G 谱号；unit_size=11.2；底线 y=1256，顶线 y=1211.2
        self.unit = 11.2
        self.bottom = 1256.0
        self.top = 1211.2
        self.staff = make_staff(0, self.unit, self.bottom, self.top)

    def test_bottom_line_is_max_y(self):
        # 不论 lines 列表顺序如何，bottom_line_y 应取 max(y)
        self.assertAlmostEqual(self.staff.bottom_line_y(), self.bottom)
        rev = make_staff(0, self.unit, self.bottom, self.top)
        rev.lines = list(reversed(rev.lines))
        self.assertAlmostEqual(rev.bottom_line_y(), self.bottom)

    def test_on_lines_and_spaces(self):
        # 底线（cy=1256）→ pos1 (E4)
        self.assertEqual(_geometric_pos(self.staff, "G", 1256.0), 1)
        # 半音级上方（cy=1250.4）→ pos2 (F4)
        self.assertEqual(_geometric_pos(self.staff, "G", 1250.4), 2)
        # 一间上方（cy=1244.8）→ pos3 (G4)
        self.assertEqual(_geometric_pos(self.staff, "G", 1244.8), 3)
        # 顶线（cy=1211.2）→ pos9 (D5)
        self.assertEqual(_geometric_pos(self.staff, "G", 1211.2), 9)

    def test_ledger_below(self):
        # 底线下 2 个半音级（cy=1267.2）→ pos -1 (C4)
        self.assertEqual(_geometric_pos(self.staff, "G", 1267.2), -1)
        # 底线下 4 个半音级（cy=1278.4）→ pos -3 (A3)
        self.assertEqual(_geometric_pos(self.staff, "G", 1278.4), -3)

    def test_ledger_above(self):
        # 顶线上 2 个半音级（cy=1200.0）→ pos 11 (E5)
        self.assertEqual(_geometric_pos(self.staff, "G", 1200.0), 11)


class TestRecomputeAlign(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f3_test_")

    def _sidecar(self, staves, clefs, notes):
        doc = SidecarDoc(
            schema_version=1, source_image="x.png", musicxml="x.musicxml",
            coordinate_space="pixel_model", note_order="oemer_emission",
            staves=staves, clefs=clefs, notes=notes,
            unit_size_px=11.2, image_width_px=None, image_height_px=None)
        p = os.path.join(self.tmp, "x.geometry.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        return p

    def test_1to1_overwrite_preserves_alter_duration(self):
        # 一个 G 谱表 staff（底线 y=1256），两个音符
        staff = make_staff(0, 11.2, 1256.0, 1211.2)
        # note0: cy=1256.0 -> pos1 -> E4；note1: cy=1244.8 -> pos3 -> G4
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 1250.0, 20.0, 1262.0),
                         center=(15.0, 1256.0), ink_centroid=(15.0, 1256.0),
                         staff_line_pos=1, sfn=None),
            NoteGeometry(id=1, track=0, group=0,
                         bbox=(40.0, 1239.0, 50.0, 1251.0),
                         center=(45.0, 1244.8), ink_centroid=(45.0, 1244.8),
                         staff_line_pos=3, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G", line=None,
                              x_center=5.0, y_center=1234.0, sign="G")]
        sidecar = self._sidecar([staff], clefs, notes)

        mxl = os.path.join(self.tmp, "x.musicxml")
        # 原始（oemer 可能误猜）step/octave 故意写错，alter/duration 保留
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 1, "duration": 2, "type": "eighth"},
            {"step": "B", "octave": 3, "alter": -1, "duration": 4, "type": "half"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 2)
        res = first_two_notes(mxl)
        # note0 -> E4, alter 保持 1, duration 2, type eighth
        self.assertEqual(res[0], ("E", "4", "1", "2", "eighth"))
        # note1 -> G4, alter 保持 -1, duration 4, type half
        self.assertEqual(res[1], ("G", "4", "-1", "4", "half"))

    def test_rest_preserved(self):
        staff = make_staff(0, 11.2, 1256.0, 1211.2)
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 1250.0, 20.0, 1262.0),
                         center=(15.0, 1256.0), ink_centroid=(15.0, 1256.0),
                         staff_line_pos=1, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G")]
        sidecar = self._sidecar([staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
            {"is_rest": True, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 1)  # 休止符未计入

    def test_missing_sidecar_returns_zero_unchanged(self):
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        with open(mxl, "rb") as f:
            before = f.read()
        n = recompute_pitch_from_geometry(mxl, os.path.join(self.tmp, "nope.geometry.json"))
        self.assertEqual(n, 0)
        with open(mxl, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)  # 文件未改动

    def test_multistaff_track_routing(self):
        # staff0 = G 谱号（底线 y=256），staff1 = F 谱号（底线 y=256）
        g_staff = make_staff(0, 11.2, 256.0, 211.2, staff_id=0)
        f_staff = make_staff(1, 11.2, 256.0, 211.2, staff_id=1)
        # note0 在 G staff 底线（cy=256）-> pos1 -> E4
        # note1 在 F staff 底线（cy=256）-> pos1 -> G2（底线即 pos1，非 pos0）
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 250.0, 20.0, 262.0),
                         center=(15.0, 256.0), ink_centroid=(15.0, 256.0),
                         staff_line_pos=1, sfn=None),
            NoteGeometry(id=1, track=1, group=0,
                         bbox=(40.0, 250.0, 50.0, 262.0),
                         center=(45.0, 256.0), ink_centroid=(45.0, 256.0),
                         staff_line_pos=0, sfn=None),
        ]
        clefs = [
            ClefGeometry(track=0, type="G"),
            ClefGeometry(track=1, type="F"),
        ]
        sidecar = self._sidecar([g_staff, f_staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
            {"step": "D", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 2)
        res = first_two_notes(mxl)
        self.assertEqual(res[0], ("E", "4", "0", "1", "quarter"))
        self.assertEqual(res[1], ("G", "2", "0", "1", "quarter"))

    def test_lines_not_five_skipped(self):
        # 只有 4 条谱线的 staff -> 该音符跳过（保留原值）
        bad_staff = make_staff(0, 11.2, 256.0, 211.2, n_lines=4)
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 250.0, 20.0, 262.0),
                         center=(15.0, 256.0), ink_centroid=(15.0, 256.0),
                         staff_line_pos=1, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G")]
        sidecar = self._sidecar([bad_staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 0)  # 跳过
        res = first_two_notes(mxl)
        self.assertEqual(res[0][0], "C")  # 原值保留

    def test_unknown_clef_skipped(self):
        staff = make_staff(0, 11.2, 256.0, 211.2)
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 250.0, 20.0, 262.0),
                         center=(15.0, 256.0), ink_centroid=(15.0, 256.0),
                         staff_line_pos=1, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="percussion")]  # 非 G/F
        sidecar = self._sidecar([staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 0)
        res = first_two_notes(mxl)
        self.assertEqual(res[0][0], "C")


if __name__ == "__main__":
    unittest.main(verbosity=2)
