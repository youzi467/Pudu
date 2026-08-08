# -*- coding: utf-8 -*-
"""
_merge_align 整 part 保序对齐单测（R1）
====================================

R1 把旧的「按同 (part, measure) 同小节定位配对」fallback 替换为整 part
Needleman–Wunsch 全局保序对齐：oemer 时值漂移 + 小节边界错位使 pred 的 onset 与
小节号都相对 gt 不可信，同小节定位会把同源音符拆进不同小节组、配对退化为随机
（旧 pitch_degree ≈ 1/7 随机基线）。新实现无视小节号，按 part 内 onset 序全局
配对、容增删（漏检/误检仍以 event_count 暴露）。

覆盖：
  * 漂移音符经 NW 配对而非计为未配对（原 fallback 行为继承）
  * 小节边界错位（R1 根因）回归
  * NW 直接单测：中段插入/删除、休止↔音符不误配

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

from omr_eval_lib import _merge_align, _note_key, _nw_align  # noqa: E402


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
        # 回归：同 onset 多声部音符两侧同序（序列内 _note_key 定序），NW 正确 1:1 配对。
        # degree1 与 degree5（八度更高 -> _note_key 排序在后）各配各，不交叉。
        n1 = _note(1, octave=0)
        n2 = _note(5, octave=1)  # 八度更高 -> _note_key 排序在后
        gt_b = {(0, 0.0): [(1, n1), (1, n2)]}
        pred_b = {(0, 0.0): [(1, n1), (1, n2)]}
        merged = _merge_align(pred_b, gt_b)
        self.assertEqual(len(merged), 2)   # 2 个 NW 1:1 桶（n1、n2 各一）
        for bucket in merged.values():
            self.assertEqual(len(bucket["c"]), 1)
            self.assertEqual(len(bucket["g"]), 1)
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

    def test_measure_shift_does_not_break_pairing(self):
        # R1 回归：pred 小节边界相对 gt 错位（pred 的 m2 同时承载 gt 的 m2+m3
        # 内容），且 onset 整体 +0.5 漂移（远超 tol）。
        # 旧的「按同 (part, measure) 定位配对」会把同源音符拆进不同小节组、
        # 配对退化为随机；新整 part 保序 NW 无视小节号，按音序全局配对 -> 全 1:1。
        gt_b = {
            (0, 0.0): [(1, _note(1))],
            (0, 1.0): [(2, _note(2))],
            (0, 2.0): [(3, _note(3))],
        }
        pred_b = {
            (0, 0.5): [(1, _note(1))],
            (0, 1.5): [(2, _note(2))],   # pred 的 m2 承载 gt 的 m2+m3
            (0, 2.5): [(2, _note(3))],
        }
        merged = _merge_align(pred_b, gt_b)
        self.assertEqual(len(merged), 3)   # 3 个 1:1 NW 桶
        for bucket in merged.values():
            self.assertEqual(len(bucket["c"]), 1)
            self.assertEqual(len(bucket["g"]), 1)
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 3)   # 全部进入比较
        self.assertEqual(event_unpaired, 0)   # 不再计为未配对

    def test_lone_notes_pair_as_mismatch_not_unpaired(self):
        # 新语义（整 part 全局对齐）文档化：同 part 下孤独音符不再因小节号不同而
        # 拒绝配对。全局对齐的取舍——数量相等的两端必定配对（配对得分 ≥ 双 gap），
        # 不同音高会在比对中如实记录为 pitch 不匹配，而非隐藏进 event_count。
        # （旧 test_no_cross_measure_pairing 断言"不跨小节配对"，已被 R1 撤销：
        #  小节号在漂移场景不可信，正是 R1 要修的根因。）
        gt_b = {(0, 0.0): [(1, _note(1))]}
        pred_b = {(0, 0.5): [(2, _note(9))]}
        merged = _merge_align(pred_b, gt_b)
        self.assertEqual(len(merged), 1)
        bucket = next(iter(merged.values()))
        self.assertEqual(len(bucket["c"]), 1)
        self.assertEqual(len(bucket["g"]), 1)
        notes_compared, event_unpaired = _simulate_consumer(merged)
        self.assertEqual(notes_compared, 1)
        self.assertEqual(event_unpaired, 0)

    def test_original_tolerance_merge_still_works(self):
        # 回归：极小偏移（< tol）仍由主路径合并为单桶。
        a = {(0, 1.00): [("m", _note(1))]}
        b = {(0, 1.01): [("m", _note(1))]}
        merged = _merge_align(a, b, tol=0.03)
        self.assertEqual(len(merged), 1)
        key = next(iter(merged))
        self.assertEqual(len(merged[key]["c"]), 1)
        self.assertEqual(len(merged[key]["g"]), 1)


class TestNwAlign(unittest.TestCase):
    """_nw_align 直接单测：保序、容增删、休止处理（不经过 _merge_align 桶归并）。"""

    def test_insertion_in_middle_is_leftover(self):
        # pred 中间多一个音（误检）-> 该音落 c_leftover，前后正常保序配对。
        c_items = [(1, _note(1)), (1, _note(2)), (1, _note(3))]
        g_items = [(1, _note(1)), (1, _note(3))]
        pairs, c_left, g_left = _nw_align(c_items, g_items)
        self.assertEqual([p[0][1]["degree"] for p in pairs], [1, 3])
        self.assertEqual([it[1]["degree"] for it in c_left], [2])
        self.assertEqual(g_left, [])

    def test_deletion_in_middle_is_leftover(self):
        # gt 中间多一个音（pred 漏检）-> 该音落 g_leftover。
        c_items = [(1, _note(1)), (1, _note(3))]
        g_items = [(1, _note(1)), (1, _note(2)), (1, _note(3))]
        pairs, c_left, g_left = _nw_align(c_items, g_items)
        self.assertEqual([p[1][1]["degree"] for p in pairs], [1, 3])
        self.assertEqual([it[1]["degree"] for it in g_left], [2])
        self.assertEqual(c_left, [])

    def test_rest_not_misaligned_to_note(self):
        # pred 末尾多一个休止、gt 无对应 -> 休止应走 gap（c_leftover），
        # 不得与前面的音符错配（休止↔音符 强负分 _ALIGN_REST_MISMATCH=-4，
        # 远比 gap -2 差）。
        c_items = [(1, _note(1)), (1, _note(1, is_rest=True))]
        g_items = [(1, _note(1))]
        pairs, c_left, g_left = _nw_align(c_items, g_items)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0][1]["degree"], 1)  # pred 音符配 gt 音符
        self.assertEqual(len(c_left), 1)
        self.assertTrue(c_left[0][1]["isRest"])
        self.assertEqual(g_left, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
