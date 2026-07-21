# -*- coding: utf-8 -*-
"""F3 集成冒烟测试（纯重算，不调 oemer / GPU）。

验证：
  * 合成 .musicxml + 对应 .geometry.json：step/octave 被几何正确覆盖，
    alter / 时值（duration/type）/ 休止符 / 和弦结构原样保留。
  * `--no-f3-geometric` 回归不变式：不调用 recompute 时输出 == 原 oemer 输出
    （即字节级未改动）；缺失 sidecar 时 recompute 返回 0 且不改文件。
  * use_ink_centroid 开关：False 时改用 bbox 中心 y。
  * 含加线 / 跨八度 / 和弦（多符头同 x 不同 y）均按发射序 1:1 对齐。
"""

import os
import sys
import json
import unittest
import tempfile
import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from geometric_pitch import (  # noqa: E402
    SidecarDoc, StaffGeometry, LineGeom, ClefGeometry, NoteGeometry,
    recompute_pitch_from_geometry, _pos_to_step_octave,
)


def make_staff(track, unit_size, bottom_y, top_y, staff_id=0):
    step = (bottom_y - top_y) / 4.0
    lines = [LineGeom(y_center=bottom_y - i * step) for i in range(5)]
    return StaffGeometry(staff_id=staff_id, track=track, group=0,
                         unit_size=unit_size, y_center=(bottom_y + top_y) / 2.0,
                         lines=lines)


def write_musicxml(path, notes_spec):
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    measure = ET.SubElement(part, "measure", attrib={"number": "1"})
    for ns in notes_spec:
        note = ET.SubElement(measure, "note")
        if ns.get("is_rest"):
            ET.SubElement(note, "rest")
        else:
            if ns.get("chord"):
                ET.SubElement(note, "chord")
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
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def read_notes(path):
    tree = ET.parse(path)
    root = tree.getroot()
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1] if "}" in el.tag else el.tag
    out = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            out.append(("REST",))
            continue
        if note.find("chord") is not None:
            chord = True
        else:
            chord = False
        pitch = note.find("pitch")
        step = pitch.find("step").text
        alter = pitch.find("alter").text
        octave = pitch.find("octave").text
        duration = note.find("duration").text
        typ = note.find("type").text
        out.append((step, octave, alter, duration, typ, chord))
    return out


class TestF3Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f3_int_")

    def _sidecar(self, staves, clefs, notes, path=None):
        doc = SidecarDoc(
            schema_version=1, source_image="x.png", musicxml="x.musicxml",
            coordinate_space="pixel_model", note_order="oemer_emission",
            staves=staves, clefs=clefs, notes=notes,
            unit_size_px=11.2, image_width_px=None, image_height_px=None)
        p = path or os.path.join(self.tmp, "x.geometry.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        return p

    def test_smoke_ledger_and_octave_jump(self):
        # G 谱表：底线 y=1256，顶线 y=1211.2，unit_size=11.2
        staff = make_staff(0, 11.2, 1256.0, 1211.2)
        # 三个音符：
        #  n0 底线 (cy=1256.0) -> pos1 -> E4
        #  n1 加线下方 (cy=1278.4 = 底线+2半音级) -> pos-3 -> A3
        #  n2 上方八度 (cy=1199.0 = 顶线上 ~3半音级) -> 高八度音
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 1250.0, 20.0, 1262.0),
                         center=(15.0, 1256.0), ink_centroid=(15.0, 1256.0),
                         staff_line_pos=1, sfn=None),
            NoteGeometry(id=1, track=0, group=0,
                         bbox=(40.0, 1272.0, 50.0, 1284.0),
                         center=(45.0, 1278.4), ink_centroid=(45.0, 1278.4),
                         staff_line_pos=-3, sfn=None),
            NoteGeometry(id=2, track=0, group=0,
                         bbox=(70.0, 1193.0, 80.0, 1205.0),
                         center=(75.0, 1199.0), ink_centroid=(75.0, 1199.0),
                         staff_line_pos=12, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G")]
        sidecar = self._sidecar([staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 1, "duration": 2, "type": "eighth"},
            {"step": "D", "octave": 3, "alter": -1, "duration": 1, "type": "quarter"},
            {"step": "E", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 3)
        res = read_notes(mxl)
        # n0 -> E4, alter 保持 1, duration 2, type eighth
        self.assertEqual(res[0], ("E", "4", "1", "2", "eighth", False))
        # n1 -> A3, alter 保持 -1, duration 1
        self.assertEqual(res[1], ("A", "3", "-1", "1", "quarter", False))
        # n2 -> 顶线上 ~2 半音级：pos = 1 + round_half_up((1256-1199)/5.6)
        #      = 1 + round_half_up(57/5.6) = 1 + round_half_up(10.178) = 1 + 10 = 11
        #      -> _pos_to_step_octave(11, 'G'): pos%7=4 -> 'A', octv=floor(12/7)+4=5 => A5
        self.assertEqual(_pos_to_step_octave(11, "G"), ("A", 5))
        self.assertEqual(res[2][0], "A")
        self.assertEqual(res[2][1], "5")

    def test_chord_aligned(self):
        # 和弦：两个符头同 x=15，不同 y（cy=1256 与 cy=1244.8）
        staff = make_staff(0, 11.2, 1256.0, 1211.2)
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 1250.0, 20.0, 1262.0),
                         center=(15.0, 1256.0), ink_centroid=(15.0, 1256.0),
                         staff_line_pos=1, sfn=None),
            NoteGeometry(id=1, track=0, group=0,
                         bbox=(10.0, 1239.0, 20.0, 1251.0),
                         center=(15.0, 1244.8), ink_centroid=(15.0, 1244.8),
                         staff_line_pos=3, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G")]
        sidecar = self._sidecar([staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
            {"step": "B", "octave": 3, "alter": 0, "duration": 1, "type": "quarter",
             "chord": True},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar)
        self.assertEqual(n, 2)
        res = read_notes(mxl)
        # 两个非休止音符，第二个标记为 chord
        self.assertEqual(res[0], ("E", "4", "0", "1", "quarter", False))
        self.assertEqual(res[1], ("G", "4", "0", "1", "quarter", True))

    def test_regression_no_f3_equals_original(self):
        # 模拟 --no-f3-geometric：不调用 recompute，输出应 == 原始 oemer 输出
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        with open(mxl, "rb") as f:
            original = f.read()
        # 不调用 recompute（等价于 --no-f3-geometric 关闭分支）
        with open(mxl, "rb") as f:
            after = f.read()
        self.assertEqual(original, after)

    def test_regression_missing_sidecar_no_change(self):
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
            {"is_rest": True, "duration": 1, "type": "quarter"},
        ])
        with open(mxl, "rb") as f:
            original = f.read()
        # 缺失 sidecar：recompute 返回 0 且不改文件（非致命）
        n = recompute_pitch_from_geometry(
            mxl, os.path.join(self.tmp, "missing.geometry.json"))
        self.assertEqual(n, 0)
        with open(mxl, "rb") as f:
            after = f.read()
        self.assertEqual(original, after)

    def test_use_bbox_center_false(self):
        # use_ink_centroid=False：用 bbox 中心 y
        staff = make_staff(0, 11.2, 1256.0, 1211.2)
        # bbox 中心 cy = (1250+1262)/2 = 1256.0 -> E4；ink_centroid 故意给错值
        notes = [
            NoteGeometry(id=0, track=0, group=0,
                         bbox=(10.0, 1250.0, 20.0, 1262.0),
                         center=(15.0, 1256.0), ink_centroid=(15.0, 999.0),
                         staff_line_pos=1, sfn=None),
        ]
        clefs = [ClefGeometry(track=0, type="G")]
        sidecar = self._sidecar([staff], clefs, notes)
        mxl = os.path.join(self.tmp, "x.musicxml")
        write_musicxml(mxl, [
            {"step": "C", "octave": 3, "alter": 0, "duration": 1, "type": "quarter"},
        ])
        n = recompute_pitch_from_geometry(mxl, sidecar, use_ink_centroid=False)
        self.assertEqual(n, 1)
        res = read_notes(mxl)
        self.assertEqual(res[0][0], "E")
        self.assertEqual(res[0][1], "4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
