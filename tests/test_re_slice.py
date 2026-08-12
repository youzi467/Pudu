# -*- coding: utf-8 -*-
"""方案4/2 单测：拍号约束保守重切 + 小节节拍校验打标。

背景（memory jianpu-attribution-reframe，2026-08-10 归因）：oemer 的小节分段
错误是简谱坏小节的**主导根因**——音符音高时值全对，只是被插/漏了纵线（铁证 bach
p1 开头切 2/14/4/12 vs 真 16/16）。re_slice_measures 把音符流按拍号 target 贪心
重切；保守门（碎片页 / 切点偏差 > tol / 无 meter）外不改文件。
mark_meter_constraint_failures 对 |fill − target| > tol 的小节打 footnote 兜底。

覆盖：
  * 重切：2/14/4/12 四小节 → 16/16 两小节，音符集合保持、连续编号
  * gate：切点偏差 > tol → None 且文件字节不变
  * gate：碎片页（<3 小节）→ None
  * gate：无 meter（fill 平票）→ None
  * 幂等：重切后二次调用结构不变
  * 幻影 v2 归并：重建后单声部、无 forward/backup
  * 和弦保持：<chord> 子符紧随父符
  * 节拍校验：欠/超填小节打标；达标不打；幂等不重复

纯 stdlib（xml.etree.ElementTree），不依赖 oemer / numpy。
"""
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
_QL_TO_TYPE = {0.25: "16th", 0.5: "eighth", 1.0: "quarter", 2.0: "half", 4.0: "whole"}


def build_score(measures, time=None):
    """构造 score-partwise。measures: list[list[dict]]（每小节音符组）。

    note dict: ``ql``（时值）、``step``/``octave``、``voice``（默认 1）、
    ``rest``、``chord``（True=子符，紧随父符）。measure 1 attributes 含 divisions，
    可选预置 <time>（镜像 oemer 输出 / 方案1 注入结果）。
    """
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    for i, mnotes in enumerate(measures, start=1):
        m = ET.SubElement(part, "measure", attrib={"number": str(i)})
        if i == 1:
            attrs = ET.SubElement(m, "attributes")
            ET.SubElement(attrs, "divisions").text = str(DIVISIONS)
            if time:
                t = ET.SubElement(attrs, "time")
                ET.SubElement(t, "beats").text = str(time[0])
                ET.SubElement(t, "beat-type").text = str(time[1])
        for spec in mnotes:
            n = ET.SubElement(m, "note")
            if spec.get("chord"):
                ET.SubElement(n, "chord")
            ET.SubElement(n, "voice").text = spec.get("voice", "1")
            if spec.get("rest"):
                ET.SubElement(n, "rest")
            else:
                p = ET.SubElement(n, "pitch")
                ET.SubElement(p, "step").text = spec.get("step", "C")
                ET.SubElement(p, "octave").text = str(spec.get("octave", 4))
            ET.SubElement(n, "duration").text = str(int(spec["ql"] * DIVISIONS))
            tp = _QL_TO_TYPE.get(spec["ql"])
            if tp:
                ET.SubElement(n, "type").text = tp
    return root


def write(root, prefix="rslice_"):
    tmp = tempfile.mkdtemp(prefix=prefix)
    path = os.path.join(tmp, "x.musicxml")
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def sixteenths(n, **kw):
    return [{"ql": 0.25, **kw} for _ in range(n)]


def parse_measures(path):
    root = ET.parse(path).getroot()
    gp._strip_ns(root)
    div = gp._first_divisions(root)
    out = []
    for m in root.iter("measure"):
        notes = []
        for n in m.findall("note"):
            notes.append((n.findtext("voice") or "1",
                          n.find("chord") is not None,
                          gp._note_ql(n, div)))
        out.append({"number": m.get("number"), "notes": notes})
    return out


# ===================== 重切 =====================
class TestReSlice(unittest.TestCase):
    def test_corrects_mis_sliced_page(self):
        # 2/14/4/12 四小节（bach p1 开头形态）→ 重切为 16/16 两小节
        measures = [sixteenths(2), sixteenths(14), sixteenths(4), sixteenths(12)]
        path = write(build_score(measures, time=(4, 4)))
        self.assertEqual(gp.re_slice_measures(path), 2)
        out = parse_measures(path)
        self.assertEqual([m["number"] for m in out], ["1", "2"])
        for m in out:
            self.assertEqual(round(sum(x[2] for x in m["notes"]), 3), 4.0)
            self.assertEqual(len(m["notes"]), 16)

    def test_gate_big_eps_no_change(self):
        # 首小节超填 0.5（1 个 4 分错读）→ 切点偏差 0.5 > tol → None 且字节不变
        measures = [sixteenths(14) + [{"ql": 1.0}],
                    sixteenths(16), sixteenths(16), sixteenths(16)]
        path = write(build_score(measures, time=(4, 4)))
        with open(path, "rb") as f:
            before = f.read()
        self.assertIsNone(gp.re_slice_measures(path))
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(before, after)

    def test_gate_fragment_page(self):
        # <3 小节 → 拍号不可靠，不重切
        path = write(build_score([sixteenths(16), sixteenths(16)], time=(4, 4)))
        self.assertIsNone(gp.re_slice_measures(path))

    def test_gate_no_meter(self):
        # 无 <time>，fill 3.0/4.0/2.0 平票 → 推断 None → 不重切
        measures = [[{"ql": 1.0} for _ in range(3)],
                    [{"ql": 1.0} for _ in range(4)],
                    [{"ql": 1.0} for _ in range(2)]]
        path = write(build_score(measures))
        self.assertIsNone(gp.re_slice_measures(path))

    def test_idempotent(self):
        # 2/4 拍、8×16 分真小节；错切 2/6/3/5/4/4 → 8/8/8 三小节（≥3 门通过）。
        # 二次调用结构不变、仍返回小节数（非 None）。
        measures = [sixteenths(2), sixteenths(6), sixteenths(3),
                    sixteenths(5), sixteenths(4), sixteenths(4)]
        path = write(build_score(measures, time=(2, 4)))
        self.assertEqual(gp.re_slice_measures(path), 3)
        first = parse_measures(path)
        self.assertEqual(gp.re_slice_measures(path), 3)
        second = parse_measures(path)
        self.assertEqual([m["number"] for m in first], [m["number"] for m in second])
        for a, b in zip(first, second):
            self.assertEqual(len(a["notes"]), len(b["notes"]))

    def test_voice_merge_single_voice(self):
        # 幻影 v2（v1=3×4 分 + backup + v2=1×4 分）→ 重切后单声部、无 forward/backup
        m1 = [{"ql": 1.0, "voice": "1"} for _ in range(3)]
        m1 += [{"ql": 1.0, "voice": "2"}]
        path = write(build_score([m1] + [sixteenths(16) for _ in range(3)], time=(4, 4)))
        self.assertEqual(gp.re_slice_measures(path), 4)
        tree = ET.parse(path)
        root = tree.getroot()
        gp._strip_ns(root)
        self.assertEqual(root.findall(".//forward") + root.findall(".//backup"), [])
        voices = {n.findtext("voice") for n in root.iter("note")}
        self.assertEqual(voices, {"1"})

    def test_chord_stays_with_parent(self):
        # 和弦子符紧随父符、同小节
        m1 = [{"ql": 0.25, "octave": 4}, {"ql": 0.25, "octave": 5, "chord": True}]
        m1 += sixteenths(14)
        path = write(build_score([m1] + [sixteenths(16) for _ in range(3)], time=(4, 4)))
        self.assertEqual(gp.re_slice_measures(path), 4)
        out = parse_measures(path)
        self.assertEqual(out[0]["number"], "1")
        notes = out[0]["notes"]
        # 第 2 个音符必须是第 1 个的 chord 子符（紧随）
        self.assertTrue(notes[1][1])          # chord=True
        self.assertFalse(notes[0][1])         # 父符非 chord


# ===================== 节拍校验打标 =====================
class TestMarkMeterConstraint(unittest.TestCase):
    def test_marks_off_target_measures(self):
        # m2 欠填 0.5、m3 超填 0.5 → 打标；m1 达标 → 不打
        measures = [sixteenths(16),
                    sixteenths(14),
                    sixteenths(18)]
        path = write(build_score(measures, time=(4, 4)))
        self.assertEqual(gp.mark_meter_constraint_failures(path), 2)
        root = ET.parse(path).getroot()
        gp._strip_ns(root)
        marks = []
        for m in root.iter("measure"):
            first = m.find("note")
            fn = first.find("./notations/footnote") if first is not None else None
            marks.append((m.get("number"), fn.text if fn is not None else None))
        self.assertEqual(marks[0][1], None)
        self.assertIn("小节节拍不符", marks[1][1])
        self.assertIn("小节节拍不符", marks[2][1])

    def test_idempotent_no_dup(self):
        measures = [sixteenths(16), sixteenths(14)]
        path = write(build_score(measures, time=(4, 4)))
        self.assertEqual(gp.mark_meter_constraint_failures(path), 1)
        self.assertEqual(gp.mark_meter_constraint_failures(path), 0)
        root = ET.parse(path).getroot()
        gp._strip_ns(root)
        fns = root.findall(".//footnote")
        self.assertEqual(len(fns), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
