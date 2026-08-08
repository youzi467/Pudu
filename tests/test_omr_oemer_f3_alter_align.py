# -*- coding: utf-8 -*-
"""方案A↔F3 交互修复单测：索引对齐守卫 + F3 后按 (step, octave) 对齐 gt alter。

背景（2026-08-08 归因，docs/f3-abtest.md）：F3 几何重算覆盖 pred 的
step/octave 后，方案A 的"文档序索引对齐 (step, alter)"立即失效——当 pred/gt
非休止音符数不等（oemer 欠检 ~15%）时索引错位放大，Pudu 依 key+显式 alter
推导音高，step/alter 错配产出大量假阳性变音（F3PC 950 个 pitch_accidental
错误中 811 个 FP）。修复分两步：

  1. ``_apply_alters_gt_aligned`` 仅当 pred/gt 音符数相等时做索引对齐；
     不等则跳过（返回 0，pred 保留原 step/alter）。
  2. F3 后新增 ``_align_alters_by_pitch``：按文档序、保序贪心 1:1 匹配
     (step, octave)，把 gt 的 alter 对齐到 pred，消解 step/alter 错配，
     同时保住 F3 的几何 step 收益。匹配**全局**进行（实测 pred/gt 小节号
     不对齐，故不得按小节号匹配）。

本文件纯 stdlib（xml.etree.ElementTree），不依赖 oemer / numpy。
"""
import os
import sys
import tempfile
import unittest

import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_oemer  # noqa: E402


# ===================== 测试辅助 =====================
def build_score_multi(notes_spec, fifths=None):
    """构造最小 score-partwise，支持多小节 / 指定 octave / 调号。

    Args:
        notes_spec: 元素为 dict：
            - ``kind``: ``"note"``(默认) | ``"rest"``
            - ``measure``: 小节号（默认 1）
            - ``step``: 音级字母（如 ``"C"``）
            - ``octave``: 八度（默认 4）
            - ``alter``: 显式 alter（int/str 或 None 表示不写 ``<alter>``）
        fifths: 若给定，在 measure 1 的 attributes 里写 ``<key><fifths>``。

    Returns:
        xml.etree.ElementTree.Element: 根元素（score-partwise）。
    """
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    measures = {}
    for spec in notes_spec:
        num = str(spec.get("measure", 1))
        if num not in measures:
            m = ET.SubElement(part, "measure", attrib={"number": num})
            if num == "1" and fifths is not None:
                attrs = ET.SubElement(m, "attributes")
                key = ET.SubElement(attrs, "key")
                ET.SubElement(key, "fifths").text = str(fifths)
            measures[num] = m
        measure = measures[num]
        kind = spec.get("kind", "note")
        note = ET.SubElement(measure, "note")
        if kind == "rest":
            ET.SubElement(note, "rest")
            continue
        pitch = ET.SubElement(note, "pitch")
        step_el = ET.SubElement(pitch, "step")
        step_el.text = spec["step"]
        ET.SubElement(pitch, "octave").text = str(spec.get("octave", 4))
        if spec.get("alter") is not None:
            ET.SubElement(pitch, "alter").text = str(spec["alter"])
    return root


def _read_notes(root):
    """按文档序读取所有非休止音符的 (step, octave, alter)，alter 为 int 或 None。"""
    out = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None or step_el.text is None:
            continue
        octave_el = pitch.find("octave")
        octave = int(float(octave_el.text)) if (
            octave_el is not None and octave_el.text is not None) else None
        alter_el = pitch.find("alter")
        alter = int(float(alter_el.text)) if (
            alter_el is not None and alter_el.text is not None) else None
        out.append((str(step_el.text).strip().upper(), octave, alter))
    return out


# ===================== Change 1：索引对齐守卫 =====================
class TestApplyAltersGtAlignedGuard(unittest.TestCase):
    """验证 _apply_alters_gt_aligned 仅在音符数相等时索引对齐，不等则跳过。"""

    def test_equal_count_index_copy(self):
        """音符数相等：仍按文档序索引拷贝 gt 的 (step, alter)（原行为不变）。"""
        gt_root = build_score_multi([
            {"step": "F", "octave": 4, "alter": 1},
            {"step": "G", "octave": 4, "alter": None},
            {"step": "A", "octave": 4, "alter": -1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "octave": 4, "alter": 0},
            {"step": "D", "octave": 4, "alter": 0},
            {"step": "E", "octave": 4, "alter": 0},
        ])
        n = omr_oemer._apply_alters_gt_aligned(pred_root, gt_root, 0)
        self.assertEqual(n, 3)
        self.assertEqual(_read_notes(pred_root),
                         [("F", 4, 1), ("G", 4, None), ("A", 4, -1)])

    def test_equal_count_preserves_octave_duration(self):
        """等长索引拷贝只动 (step, alter)，保留 pred 的 octave。"""
        gt_root = build_score_multi([{"step": "F", "octave": 5, "alter": 1}])
        pred_root = build_score_multi([{"step": "C", "octave": 3, "alter": 0}])
        n = omr_oemer._apply_alters_gt_aligned(pred_root, gt_root, 0)
        self.assertEqual(n, 1)
        # octave 来自 pred（3），step/alter 来自 gt
        self.assertEqual(_read_notes(pred_root), [("F", 3, 1)])

    def test_unequal_more_skips_copy(self):
        """pred 多于 gt：跳过索引对齐，pred 原样保留（返回 0）。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1},
            {"step": "G", "alter": None},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},
            {"step": "D", "alter": 0},
            {"step": "E", "alter": 0},
            {"step": "F", "alter": 0},
        ])
        n = omr_oemer._apply_alters_gt_aligned(pred_root, gt_root, 0)
        self.assertEqual(n, 0)
        # pred 的 (step, alter) 完全未被 gt 覆盖
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, 0), ("D", 4, 0), ("E", 4, 0), ("F", 4, 0)])

    def test_unequal_fewer_skips_copy(self):
        """pred 少于 gt：同样跳过索引对齐（不等即跳，含方向相反）。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1},
            {"step": "G", "alter": -1},
            {"step": "A", "alter": None},
            {"step": "B", "alter": 1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},
            {"step": "D", "alter": 0},
            {"step": "E", "alter": 0},
        ])
        n = omr_oemer._apply_alters_gt_aligned(pred_root, gt_root, 0)
        self.assertEqual(n, 0)
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, 0), ("D", 4, 0), ("E", 4, 0)])

    def test_rest_and_nopitch_ignored_in_count(self):
        """休止符 / 无 pitch 不参与计数，等长判断只针对非休止音符。"""
        gt_root = build_score_multi([
            {"kind": "rest"},
            {"step": "F", "alter": 1},
            {"kind": "rest"},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},
            {"kind": "rest"},
            {"kind": "rest"},
        ])
        # gt 非休止 1 个，pred 非休止 1 个 → 等长 → 索引对齐
        n = omr_oemer._apply_alters_gt_aligned(pred_root, gt_root, 0)
        self.assertEqual(n, 1)
        self.assertEqual(_read_notes(pred_root), [("F", 4, 1)])


# ===================== Change 2：F3 后按 (step, octave) 对齐 =====================
class TestAlignAltersByPitch(unittest.TestCase):
    """验证 _align_alters_by_pitch：全局保序贪心 1:1 匹配 gt alter。"""

    def test_normal_1to1(self):
        """pred/gt 音高一一对应：alter 逐音对齐，含移除与写入。"""
        gt_root = build_score_multi([
            {"step": "C", "alter": None},
            {"step": "F", "alter": 1},
            {"step": "G", "alter": -1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},
            {"step": "F", "alter": None},
            {"step": "G", "alter": 0},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 3)
        # C: gt 无 alter → pred 的 alter 0 被移除；F→1；G→-1
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, None), ("F", 4, 1), ("G", 4, -1)])

    def test_pred_insertion_unmatched_kept(self):
        """pred 多音（gt 无对应）：该音保留原 alter，其余正常对齐。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1},
            {"step": "G", "alter": -1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},   # gt 无 C4 → 保留 alter 0
            {"step": "F", "alter": None},
            {"step": "G", "alter": 0},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 2)
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, 0), ("F", 4, 1), ("G", 4, -1)])

    def test_gt_extra_skipped_by_cursor(self):
        """gt 多音（pred 无对应）：游标跳过，pred 其余音正常对齐。"""
        gt_root = build_score_multi([
            {"step": "A", "alter": 1},    # gt 多出的音（pred 无 A4）
            {"step": "F", "alter": 1},
            {"step": "G", "alter": -1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},    # gt 无 C4 → 保留
            {"step": "F", "alter": None},
            {"step": "G", "alter": 0},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 2)
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, 0), ("F", 4, 1), ("G", 4, -1)])

    def test_measure_drift_still_aligns(self):
        """pred/gt 小节号不对齐（实测 pred 22 vs gt 20 小节）：按文档序全局对齐。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1, "measure": 1},
            {"step": "G", "alter": -1, "measure": 3},
        ])
        pred_root = build_score_multi([
            {"step": "F", "alter": 0, "measure": 1},
            {"step": "G", "alter": 0, "measure": 2},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 2)
        self.assertEqual(_read_notes(pred_root),
                         [("F", 4, 1), ("G", 4, -1)])

    def test_repeated_pitch_cursor_monotone(self):
        """重复音高：游标单调推进，不回头重复消费同一 gt 音符。"""
        gt_root = build_score_multi([
            {"step": "A", "alter": None},   # 第一个 A4 无变音
            {"step": "B", "alter": None},
            {"step": "A", "alter": 1},      # 第二个 A4 有变音
        ])
        pred_root = build_score_multi([
            {"step": "A", "alter": 0},
            {"step": "A", "alter": 0},
            {"step": "B", "alter": 0},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 2)
        # pred[0] A4 → gt[0] A4 (None)；pred[1] A4 → gt[2] A4 (1)（gt[1] B4 已被跳过）
        # pred[2] B4 从游标后找 → gt[1] B4 在游标前 → 未命中，保留 0
        self.assertEqual(_read_notes(pred_root),
                         [("A", 4, None), ("A", 4, 1), ("B", 4, 0)])

    def test_octave_disambiguation(self):
        """同 step 不同 octave：按 (step, octave) 区分，不串八度。"""
        gt_root = build_score_multi([
            {"step": "C", "octave": 4, "alter": None},
            {"step": "C", "octave": 5, "alter": 1},
        ])
        pred_root = build_score_multi([
            {"step": "C", "octave": 4, "alter": 0},
            {"step": "C", "octave": 5, "alter": 0},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 2)
        self.assertEqual(_read_notes(pred_root),
                         [("C", 4, None), ("C", 5, 1)])

    def test_remove_alter_when_gt_has_none(self):
        """gt 未显式写变音记号：pred 的显式 alter 被移除（避免伪变音）。"""
        gt_root = build_score_multi([{"step": "F", "alter": None}])
        pred_root = build_score_multi([{"step": "F", "alter": 2}])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 1)
        self.assertEqual(_read_notes(pred_root), [("F", 4, None)])

    def test_rest_nopitch_robust(self):
        """休止符 / 无 pitch / 无 step 跳过，不影响其余音符对齐。"""
        gt_root = build_score_multi([
            {"kind": "rest"},
            {"step": "F", "alter": 1},
            {"kind": "rest"},
        ])
        pred_root = build_score_multi([
            {"kind": "rest"},
            {"step": "F", "alter": 0},
            {"kind": "rest"},
        ])
        n = omr_oemer._align_alters_by_pitch(pred_root, gt_root)
        self.assertEqual(n, 1)
        self.assertEqual(_read_notes(pred_root), [("F", 4, 1)])


# ===================== 集成：correct_key_signature 不等长路径 =====================
class TestCorrectKeySignatureUnequal(unittest.TestCase):
    """文件级集成：音符数不等时 correct_key_signature 跳过索引拷贝但仍写回调号。"""

    def _write(self, root):
        fd, path = tempfile.mkstemp(suffix=".musicxml")
        os.close(fd)
        tree = ET.ElementTree(root)
        tree.write(path, encoding="UTF-8", xml_declaration=True)
        return path

    def test_unequal_gt_returns_fifths_and_keeps_pred_notes(self):
        """不等长 + 有 gt：target fifths 生效，pred 音符 (step, alter) 不被 gt 覆盖。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1},   # gt 调号为 D 大调（fifths=2），2 个音符
            {"step": "C", "alter": 1},
        ], fifths=2)
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},   # pred 3 个音符（oemer 过切分/多音）
            {"step": "D", "alter": 0},
            {"step": "E", "alter": 0},
        ], fifths=0)
        gt_path = self._write(gt_root)
        pred_path = self._write(pred_root)
        try:
            ret = omr_oemer.correct_key_signature(pred_path, gt_path)
            self.assertEqual(ret, 2)  # fifths=2（D 大调）
            tree = ET.parse(pred_path)
            root = tree.getroot()
            omr_oemer._strip_ns(root)
            # 不等长 → 索引对齐被跳过，pred 音符 (step, alter) 原样保留
            self.assertEqual(_read_notes(root),
                             [("C", 4, 0), ("D", 4, 0), ("E", 4, 0)])
            # 调号确实被覆盖为 fifths=2
            fifths = [k.find("fifths").text for k in root.iter("key")
                      if k.find("fifths") is not None]
            self.assertTrue(all(str(f) == "2" for f in fifths))
        finally:
            for p in (gt_path, pred_path):
                if os.path.exists(p):
                    os.remove(p)

    def test_equal_gt_returns_fifths_and_aligns(self):
        """等长 + 有 gt：索引拷贝照常生效（回归原行为）。"""
        gt_root = build_score_multi([
            {"step": "F", "alter": 1},
            {"step": "C", "alter": None},
        ], fifths=2)
        pred_root = build_score_multi([
            {"step": "C", "alter": 0},
            {"step": "D", "alter": 0},
        ], fifths=0)
        gt_path = self._write(gt_root)
        pred_path = self._write(pred_root)
        try:
            ret = omr_oemer.correct_key_signature(pred_path, gt_path)
            self.assertEqual(ret, 2)
            tree = ET.parse(pred_path)
            root = tree.getroot()
            omr_oemer._strip_ns(root)
            self.assertEqual(_read_notes(root),
                             [("F", 4, 1), ("C", 4, None)])
        finally:
            for p in (gt_path, pred_path):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
