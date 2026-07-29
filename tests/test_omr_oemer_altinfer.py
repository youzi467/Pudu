# -*- coding: utf-8 -*-
"""P2 M2-opt-A2：无 gt 兜底分支 ``_apply_alters`` 保留显式 alter 单测。

覆盖 DoD 对齐的「a 小调、C 大调、≤2 升降号边界」用例：

  修复前：``_apply_alters`` 把每个音符的 ``<alter>`` 强制重拼写为目标调号下的值
  ``_accidental_map(new_fifths).get(step, 0)``。当 ``new_fifths == 0``（如 a 小调）
  时 ``_accidental_map(0) == {}``，所有 alter 被清零，含 a 小调合法的 G#/C# 也丢失
  （pitch_accidental 精度泄漏）。

  修复后：信任 oemer 已显式拼写的音高，仅对未显式拼写的音符按目标调号推断；并对
  显式 alter 做整数规范化（如 "1.0"→"1"）。

本文件纯 stdlib（xml.etree.ElementTree）+ numpy，不依赖 oemer（运行环境可能无 oemer）。
"""
import os
import sys
import unittest

import numpy as np  # noqa: F401  （沿用项目测试约定；本文件主体仅依赖 stdlib）

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_oemer  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402


# ===================== 测试辅助 =====================
def build_score(notes_spec):
    """构造最小 ``score-partwise``，含单个 part 与单个 measure 的音符列表。

    Args:
        notes_spec: 元素为 dict，可选字段：
            - ``kind``: ``"note"``(默认) | ``"rest"`` | ``"nopitch"`` | ``"nostep"``
            - ``step``: 音级字母（如 ``"C"``）
            - ``alter``: 显示 alter 值（int/str 或 None 表示不写 ``<alter>``）

    Returns:
        xml.etree.ElementTree.Element: 根元素（score-partwise）。
    """
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    part.set("id", "P1")
    measure = ET.SubElement(part, "measure")
    measure.set("number", "1")
    for spec in notes_spec:
        kind = spec.get("kind", "note")
        note = ET.SubElement(measure, "note")
        if kind == "rest":
            ET.SubElement(note, "rest")
            continue
        if kind == "nopitch":
            continue  # 仅 <note> 无 <pitch>
        pitch = ET.SubElement(note, "pitch")
        if kind == "nostep":
            ET.SubElement(pitch, "octave").text = "4"
            continue  # <pitch> 无 <step>
        step_el = ET.SubElement(pitch, "step")
        step_el.text = spec["step"]
        ET.SubElement(pitch, "octave").text = "4"
        if spec.get("alter") is not None:
            alter_el = ET.SubElement(pitch, "alter")
            alter_el.text = str(spec["alter"])
    return root


def _first_note_with_step(root, step):
    """按文档序返回第一个匹配 step 的非休止 note 元素（找不到返回 None）。"""
    target = str(step).strip().upper()
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None or step_el.text is None:
            continue
        if str(step_el.text).strip().upper() != target:
            continue
        return note
    return None


def get_alter(root, step):
    """按文档序找第一个匹配 step 的非休止 note 的 alter（返回 int 或 None）。"""
    note = _first_note_with_step(root, step)
    if note is None:
        return None
    pitch = note.find("pitch")
    alter_el = pitch.find("alter")
    if alter_el is None or alter_el.text is None or str(alter_el.text).strip() == "":
        return None
    return int(float(alter_el.text))


def get_alter_text(root, step):
    """按文档序找第一个匹配 step 的非休止 note 的 alter 原始文本（返回 str 或 None）。"""
    note = _first_note_with_step(root, step)
    if note is None:
        return None
    pitch = note.find("pitch")
    alter_el = pitch.find("alter")
    return None if alter_el is None or alter_el.text is None else str(alter_el.text)


# ===================== 测试用例 =====================
class TestApplyAltersAltInfer(unittest.TestCase):
    """验证 _apply_alters 修复后：保留显式 alter + 仅对未显式拼写音按调号推断。"""

    def test_a_minor_fifths_0_keep_explicit_g_sharp(self):
        """a 小调 fifths=0：显式 G#/C# 必须保留，不被清零（关键用例）。"""
        root = build_score([
            {"step": "G", "alter": 1},
            {"step": "C", "alter": 1},
            {"step": "E"},
            {"step": "A"},
        ])
        omr_oemer._apply_alters(root, 0)
        self.assertEqual(get_alter(root, "G"), 1)  # 关键：不被清零
        self.assertEqual(get_alter(root, "C"), 1)
        self.assertEqual(get_alter(root, "E"), 0)
        self.assertEqual(get_alter(root, "A"), 0)

    def test_c_major_fifths_0_no_accidentals(self):
        """C 大调 fifths=0：无变化音，全部补 alter=0，不引入意外 sharps。"""
        root = build_score([
            {"step": "C"}, {"step": "D"}, {"step": "E"},
            {"step": "F"}, {"step": "G"}, {"step": "A"}, {"step": "B"},
        ])
        omr_oemer._apply_alters(root, 0)
        for s in "CDEFGAB":
            self.assertEqual(get_alter(root, s), 0)

    def test_d_major_fifths_2_omit_alter_inferred(self):
        """D 大调 fifths=2：漏写 alter 的 F/C 推断为 #，显式 G# 保留。"""
        root = build_score([
            {"step": "F"},
            {"step": "C"},
            {"step": "G", "alter": 1},
            {"step": "E"},
        ])
        omr_oemer._apply_alters(root, 2)
        self.assertEqual(get_alter(root, "F"), 1)
        self.assertEqual(get_alter(root, "C"), 1)
        self.assertEqual(get_alter(root, "G"), 1)  # 显式保留
        self.assertEqual(get_alter(root, "E"), 0)

    def test_bb_major_fifths_neg2_inferred(self):
        """Bb 大调 fifths=-2：降号推断，显式 A- 保留。"""
        root = build_score([
            {"step": "B"},
            {"step": "E"},
            {"step": "A", "alter": -1},
            {"step": "C"},
        ])
        omr_oemer._apply_alters(root, -2)
        self.assertEqual(get_alter(root, "B"), -1)
        self.assertEqual(get_alter(root, "E"), -1)
        self.assertEqual(get_alter(root, "A"), -1)  # 显式保留
        self.assertEqual(get_alter(root, "C"), 0)

    def test_explicit_alter_normalized(self):
        """显式 alter 规范化：oemer 偶发浮点字符串 '1.0' → '1'。"""
        root = build_score([
            {"step": "G", "alter": "1.0"},
        ])
        omr_oemer._apply_alters(root, 0)
        self.assertEqual(get_alter_text(root, "G"), "1")

    def test_robust_rest_nopitch_nostep(self):
        """休止符跳过 + 无 pitch / 无 step 健壮性：不抛异常且不影响其他音符。"""
        root = build_score([
            {"kind": "rest"},
            {"kind": "nopitch"},
            {"kind": "nostep"},
            {"step": "G", "alter": 1},
        ])
        # 不应抛异常
        omr_oemer._apply_alters(root, 0)
        self.assertEqual(get_alter(root, "G"), 1)

    def test_fifths_1_g_major(self):
        """≤2 升降号边界外合理行为：G 大调 fifths=1，F→1。"""
        root = build_score([{"step": "F"}])
        omr_oemer._apply_alters(root, 1)
        self.assertEqual(get_alter(root, "F"), 1)

    def test_fifths_neg1_f_major(self):
        """≤2 升降号边界外合理行为：F 大调 fifths=-1，B→-1。"""
        root = build_score([{"step": "B"}])
        omr_oemer._apply_alters(root, -1)
        self.assertEqual(get_alter(root, "B"), -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
