# -*- coding: utf-8 -*-
"""
omr_eval_lib 纯函数单测
=======================

手搓极小 case 验证比对内核逻辑，重点确认：
  * expected_rhythm 的 quarterLength -> (underlines, augmentDashes, dots) 反推；
  * compare_jianpu_note 能把「某字段不符」归到正确错误类别；
  * flatten_json_lines / _merge_align 的桶归并与容差对齐；
  * compare_doc_meta 的文档级 key/mode/time_signature 分类。

运行（venv 或系统 python 均可，本模块无第三方依赖）：
    python tools/omr_eval_lib_test.py
"""

import os
import sys
import unittest

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from omr_eval_lib import (  # noqa: E402
    expected_rhythm,
    fifths_to_tonic_pc,
    flatten_json_lines,
    _merge_align,
    compare_jianpu_note,
    compare_doc_meta,
    COUNTED_CATEGORIES,
)


class TestExpectedRhythm(unittest.TestCase):
    """quarterLength -> (underlines, augmentDashes, dots) 反推。"""

    def test_standard_values(self):
        self.assertEqual(expected_rhythm(1.0), (0, 0, 0))    # quarter
        self.assertEqual(expected_rhythm(0.5), (1, 0, 0))    # eighth
        self.assertEqual(expected_rhythm(0.25), (2, 0, 0))   # 16th
        self.assertEqual(expected_rhythm(2.0), (0, 1, 0))    # half
        self.assertEqual(expected_rhythm(4.0), (0, 3, 0))    # whole

    def test_dotted(self):
        self.assertEqual(expected_rhythm(1.5), (0, 0, 1))    # dotted quarter
        self.assertEqual(expected_rhythm(0.75), (1, 0, 1))   # dotted eighth
        self.assertEqual(expected_rhythm(3.0), (0, 1, 1))    # dotted half
        self.assertEqual(expected_rhythm(3.5), (0, 1, 2))    # double-dotted half

    def test_unresolvable(self):
        # 三连音时值（1/3、2/3 拍）无法映射为标准时值 -> None
        self.assertIsNone(expected_rhythm(1.0 / 3.0))
        self.assertIsNone(expected_rhythm(2.0 / 3.0))
        # 五连音八分（0.2 拍）亦不可解析 -> None
        self.assertIsNone(expected_rhythm(0.2))


class TestFifthsToTonicPc(unittest.TestCase):
    def test_known(self):
        self.assertEqual(fifths_to_tonic_pc(0), 0)   # C
        self.assertEqual(fifths_to_tonic_pc(2), 2)   # D
        self.assertEqual(fifths_to_tonic_pc(-1), 5)  # F (取正模)


class TestCompareJianpuNote(unittest.TestCase):
    """compare_jianpu_note：两简谱 JSON 音符逐音比对，类别应正确。"""

    def _base_note(self, **over):
        n = {
            "degree": 1, "octaveDots": 0, "accidental": "none",
            "underlines": 0, "augmentDashes": 0, "dots": 0,
            "isRest": False, "isGrace": False,
            "tieToNext": False, "tieFromPrev": False,
            "tuplet": 0, "chordDegrees": [], "chordOctaveDots": [],
        }
        n.update(over)
        return n

    def test_identical(self):
        a = self._base_note()
        b = self._base_note()
        diffs, n_checked = compare_jianpu_note(a, b)
        self.assertEqual(diffs, [])
        self.assertGreater(n_checked, 0)

    def test_pitch_degree(self):
        pred = self._base_note(degree=2)
        gt = self._base_note(degree=1)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "pitch_degree" for _, _, _, cat in diffs))

    def test_pitch_octave(self):
        pred = self._base_note(octaveDots=1)
        gt = self._base_note(octaveDots=0)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "pitch_octave" for _, _, _, cat in diffs))

    def test_pitch_accidental(self):
        pred = self._base_note(accidental="sharp")
        gt = self._base_note(accidental="none")
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "pitch_accidental" for _, _, _, cat in diffs))

    def test_rhythm(self):
        pred = self._base_note(underlines=1)  # 八分
        gt = self._base_note(underlines=0)    # 四分
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "rhythm" for _, _, _, cat in diffs))

    def test_rest_vs_note(self):
        pred = self._base_note(degree=3)
        gt = self._base_note(isRest=True, degree=0)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "rest" for _, _, _, cat in diffs))

    def test_tie(self):
        pred = self._base_note(tieToNext=False)
        gt = self._base_note(tieToNext=True)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "tie" for _, _, _, cat in diffs))

    def test_tuplet_grouping(self):
        pred = self._base_note(tuplet=0)
        gt = self._base_note(tuplet=3)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "tuplet" for _, _, _, cat in diffs))

    def test_tuplet_rhythm_category(self):
        # 连音内节奏不符 -> tuplet_rhythm（而非 rhythm）
        pred = self._base_note(tuplet=3, underlines=1)
        gt = self._base_note(tuplet=3, underlines=0)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "tuplet_rhythm" for _, _, _, cat in diffs))
        self.assertFalse(any(cat == "rhythm" for _, _, _, cat in diffs))

    def test_chord(self):
        pred = self._base_note(chordDegrees=[3])
        gt = self._base_note(chordDegrees=[5])
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "chord" for _, _, _, cat in diffs))

    def test_grace(self):
        pred = self._base_note(isGrace=False)
        gt = self._base_note(isGrace=True)
        diffs, _ = compare_jianpu_note(pred, gt)
        self.assertTrue(any(cat == "grace" for _, _, _, cat in diffs))

    def test_category_is_counted(self):
        # 任意 counted 类别都应出现在 COUNTED_CATEGORIES 中
        pred = self._base_note(degree=9)
        gt = self._base_note(degree=1)
        diffs, _ = compare_jianpu_note(pred, gt)
        for _, _, _, cat in diffs:
            self.assertIn(cat, COUNTED_CATEGORIES)


class TestFlattenAndAlign(unittest.TestCase):
    def _doc(self, notes):
        # notes: list of (part, onset, note)
        lines = {}
        for part, onset, note in notes:
            lines.setdefault(part, []).append((0, note))
        doc = {"lines": []}
        for part, items in lines.items():
            doc["lines"].append({"part": part, "measures": [
                {"number": 1, "notes": [dict(n, onset=on) for on, (_, n) in
                 [(_ons, (None, _n)) for _ons, _n in [(o, n) for o, n in [(0, it[1]) for it in items]]]]}
            ]})
        return doc

    def test_flatten(self):
        doc = {"lines": [{"part": 0, "measures": [
            {"number": 1, "notes": [
                {"degree": 1, "onset": 0.0},
                {"degree": 2, "onset": 1.0},
            ]}]}]}
        flat = flatten_json_lines(doc)
        self.assertIn((0, 0.0), flat)
        self.assertIn((0, 1.0), flat)
        self.assertEqual(len(flat[(0, 0.0)]), 1)

    def test_merge_align_tolerance(self):
        # 同音但因 divisions 取整产生 0.01 偏移 -> 应合并到同桶
        a = {(0, 1.00): [("m", {"degree": 1})]}
        b = {(0, 1.01): [("m", {"degree": 1})]}
        merged = _merge_align(a, b, tol=0.03)
        self.assertEqual(len(merged), 1)
        key = next(iter(merged))
        self.assertEqual(len(merged[key]["c"]), 1)
        self.assertEqual(len(merged[key]["g"]), 1)


class TestCompareDocMeta(unittest.TestCase):
    def test_key_mismatch(self):
        pred = {"fifths": 0, "mode": "major", "beats": 4, "beatType": 4}
        gt = {"fifths": 2, "mode": "major", "beats": 4, "beatType": 4}
        diffs = compare_doc_meta(pred, gt)
        self.assertTrue(any(cat == "key" for _, _, _, cat in diffs))

    def test_mode_mismatch(self):
        pred = {"fifths": 0, "mode": "minor", "beats": 4, "beatType": 4}
        gt = {"fifths": 0, "mode": "major", "beats": 4, "beatType": 4}
        diffs = compare_doc_meta(pred, gt)
        self.assertTrue(any(cat == "mode" for _, _, _, cat in diffs))

    def test_time_signature_mismatch(self):
        pred = {"fifths": 0, "mode": "major", "beats": 3, "beatType": 4}
        gt = {"fifths": 0, "mode": "major", "beats": 4, "beatType": 4}
        diffs = compare_doc_meta(pred, gt)
        self.assertTrue(any(cat == "time_signature" for _, _, _, cat in diffs))

    def test_identical_meta(self):
        meta = {"fifths": 2, "mode": "major", "beats": 4, "beatType": 4}
        self.assertEqual(compare_doc_meta(meta, meta), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
