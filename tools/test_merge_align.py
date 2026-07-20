# -*- coding: utf-8 -*-
"""
_merge_align fallback 单测
==========================

聚焦验证「同小节内音序对齐」fallback：oemer 时值漂移使 pred 的 onset 相对 gt 偏移
超过 tol 时，同源音符不再被计为 event_count「未配对」，而是按同 (part, measure)
内的序列顺序配对。

运行：
    python tools/test_merge_align.py
    python -m tools.test_merge_align        # 亦可

仅依赖本目录的 omr_eval_lib（无第三方依赖）。
"""

import os
import sys
import unittest

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from omr_eval_lib import _merge_align, _note_key  # noqa: E402


def _note(degree, octave=0, accidental="none", is_rest=False):
    """构造最小简谱音符 dict（满足 _note_key 所需字段）。"""
    return {
        "degree": degree,
        "octaveDots": octave,
        "accidental": accidental,
        "isRest": is_rest,
        "underlines": 0,
        "augmentDashes": 0,
        "dots": 0,
    }


def _simulate_consumer(aligned):
    """复刻 omr_eval_groundtruth.py 的消费端配对逻辑，返回 (notes_compared, event_unpaired)。

    仅统计「配对数」与「事件数未配对（单边桶/桶内数量不一致）」，用于断言 fallback
    是否把漂移音符送进 1:1 桶比较、而非计为未配对。
    """
    notes_compared = 0
    event_unpaired = 0
    for key in sorted(aligned):
        bucket = aligned[key]
        cn = sorted(bucket["c"], key=lambda x: _note_key(x[1]))
        gn = sorted(bucket["g"], key=lambda x: _note_key(x[1]))
        if len(cn) != len(gn):
            event_unpaired += 1
        n = min(len(cn), len(gn))
        notes_compared += n
        # 余量项也计为未配对事件
        event_unpaired += max(len(cn), len(gn)) - n
    return notes_compared, event_unpaired


class TestMergeAlignFallback(unittest.TestCase):
    """验证 fallback 把时值漂移的同源音符配对而非计为未配对。"""

    def test_drift_paired_via_fallback(self):
        # 同一小节、同一序列，但 pred onset 整体 +0.5（远超 tol=0.03）。
        gt_b = {
            (0, 0.0): [(1, _note(1))],
            (0, 1.0): [(1, _note(2))],
            (0, 2.0): [(1, _note(3))],
        }
        pred_b = {
            (0, 0.5): [(1, _note(1))],
            (0, 1.5): [(1, _note(2))],
            (0, 2.5): [(1, _note(3))],
        }
        merged = _merge_align(pred_b, gt_b)
        # 3 个 fallback 1:1 桶（每个 c/g 各 1 音）
        self.assertEqual(len(merged), 3)
        for key, bucket in merged.items():
            self.assertEqual(len(bucket["c"]), 1)
            self.assertEqual(len(bucket["g"]), 1)
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 3)   # 全部进入比较
        self.assertEqual(event_unpaired, 0)   # 不再计为未配对

    def test_onset_aligned_multivoice_regression(self):
        # 回归：onset 本就对齐的多声部音符仍留在原 onset 桶，并按 _note_key 配对。
        n1 = _note(1, octave=0)
        n2 = _note(5, octave=1)  # 八度更高 -> _note_key 排序在后
        gt_b = {(0, 0.0): [(1, n1), (1, n2)]}
        pred_b = {(0, 0.0): [(1, n1), (1, n2)]}
        merged = _merge_align(pred_b, gt_b)
        self.assertEqual(len(merged), 1)
        key = next(iter(merged))
        cn = sorted(merged[key]["c"], key=lambda x: _note_key(x[1]))
        gn = sorted(merged[key]["g"], key=lambda x: _note_key(x[1]))
        self.assertEqual(len(cn), 2)
        self.assertEqual(len(gn), 2)
        # 位置配对应按 _note_key：degree1 配 degree1，degree5 配 degree5
        self.assertEqual(cn[0][1]["degree"], gn[0][1]["degree"])
        self.assertEqual(cn[1][1]["degree"], gn[1][1]["degree"])
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 2)
        self.assertEqual(event_unpaired, 0)

    def test_extra_note_is_only_in_pred(self):
        # pred 比 gt 多一个音（误检）-> 应配对前两个、第三个标 only in pred。
        gt_b = {
            (0, 0.0): [(1, _note(1))],
            (0, 1.0): [(1, _note(2))],
        }
        pred_b = {
            (0, 0.5): [(1, _note(1))],
            (0, 1.5): [(1, _note(2))],
            (0, 2.5): [(1, _note(3))],  # 多余
        }
        merged = _merge_align(pred_b, gt_b)
        # 2 个 1:1 fallback 桶 + 1 个单边（c-only）孤独桶
        self.assertEqual(len(merged), 3)
        c_only = [k for k, b in merged.items() if len(b["g"]) == 0]
        self.assertEqual(len(c_only), 1)
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 2)   # 仅 2 个真配对
        # 多余音符正确暴露：消费端对单边桶计 2 次 event_count
        # （桶数量不一致 + "only in pred" 明细）
        self.assertEqual(event_unpaired, 2)

    def test_no_cross_measure_pairing(self):
        # fallback 仅限同 (part, measure)：measure1 的 gt 与 measure2 的 pred
        # 不应配对（确属不同小节，可能本就是漏检/误检）。
        gt_b = {(0, 0.0): [(1, _note(1))]}    # measure 1
        pred_b = {(0, 0.5): [(2, _note(9))]}  # measure 2（不同 mnum）
        merged = _merge_align(pred_b, gt_b)
        # 两个单边桶，互不配对
        self.assertEqual(len(merged), 2)
        for bucket in merged.values():
            self.assertTrue(
                (len(bucket["c"]) == 0) != (len(bucket["g"]) == 0)
            )
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 0)   # 不跨小节误配
        # 2 个单边桶（c-only / g-only）各计 2 次 event_count
        self.assertEqual(event_unpaired, 4)

    def test_original_tolerance_merge_still_works(self):
        # 回归：极小偏移（< tol）仍由主路径合并为单桶。
        a = {(0, 1.00): [("m", _note(1))]}
        b = {(0, 1.01): [("m", _note(1))]}
        merged = _merge_align(a, b, tol=0.03)
        self.assertEqual(len(merged), 1)
        key = next(iter(merged))
        self.assertEqual(len(merged[key]["c"]), 1)
        self.assertEqual(len(merged[key]["g"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
