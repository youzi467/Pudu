#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯标准库自测：验证 omr_oemer 调号后处理（gt 对齐法）修复精度泄漏。

不依赖 oemer / music21，仅用 xml.etree 构造内存 MusicXML 并断言。
可用以下任一方式运行：
    python tools/test_apply_alters_gt.py
    python -m pytest tools/test_apply_alters_gt.py -q
"""
import os
import sys
import xml.etree.ElementTree as ET

# 让测试既能 `python tools/...` 直接运行，也能被 pytest 收集
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omr_oemer  # noqa: E402
from omr_oemer import _apply_alters, _apply_alters_gt_aligned  # noqa: E402


# ----------------------------------------------------------------------
# 构造器
# ----------------------------------------------------------------------
def make_note(step, alter=None, rest=False):
    """构造一个 MusicXML <note> 元素。alter=None 表示不写 <alter>。"""
    note = ET.Element("note")
    if rest:
        ET.SubElement(note, "rest")
        return note
    pitch = ET.SubElement(note, "pitch")
    s = ET.SubElement(pitch, "step")
    s.text = step
    if alter is not None:
        a = ET.SubElement(pitch, "alter")
        a.text = str(alter)
    o = ET.SubElement(pitch, "octave")
    o.text = "4"
    return note


def make_root(notes):
    """把若干 <note> 包进 score-partwise>part>measure。"""
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    for n in notes:
        measure.append(n)
    return root


def note_alter(root, idx=0):
    """取 root 中第 idx 个非休止 note 的 <alter> 文本（None 表示无该元素）。"""
    notes = [n for n in root.iter("note") if n.find("rest") is None]
    alter_el = notes[idx].find("pitch/alter")
    return alter_el.text if alter_el is not None else None


def note_step(root, idx=0):
    """取 root 中第 idx 个非休止 note 的 <step> 文本。"""
    notes = [n for n in root.iter("note") if n.find("rest") is None]
    return notes[idx].find("pitch/step").text


# ----------------------------------------------------------------------
# 测试用例
# ----------------------------------------------------------------------
def test_a_minor_keeps_sharps():
    """(a) a 小调：oemer 误把 G# 清零为 0，gt 对齐后应为 1。"""
    pred = make_root([make_note("G", alter=0)])
    gt = make_root([make_note("G", alter=1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_alter(pred, 0) == "1", "a 小调 G 应保留 gt 的 #1，而非被清零"


def test_canon_wrong_key_corrected():
    """(b) canon 式：pred F 误键为 0，gt 对齐后应为 1。"""
    pred = make_root([make_note("F", alter=0)])
    gt = make_root([make_note("F", alter=1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_alter(pred, 0) == "1", "canon F 应修正为 #1"


def test_no_gt_fallback_respell():
    """(c) 无 gt 兜底：_apply_alters(D 大调, fifths=2) 令 F/C==1，其余==0。"""
    pred = make_root([make_note(s, alter=0)
                      for s in ["C", "D", "E", "F", "G", "A", "B"]])
    _apply_alters(pred, 2)
    alters = {note_step(pred, i): note_alter(pred, i) for i in range(7)}
    assert alters["F"] == "1" and alters["C"] == "1"
    assert all(alters[s] == "0" for s in ["D", "E", "G", "A", "B"])


def test_self_consistent():
    """(d) 自洽：pred 与 gt 完全一致时，输出与输入一致（不变）。"""
    notes = [make_note("C", alter=1),
             make_note("D", alter=0),
             make_note("E", alter=None)]
    pred = make_root(notes)
    gt = make_root([make_note("C", alter=1),
                    make_note("D", alter=0),
                    make_note("E", alter=None)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_step(pred, 0) == "C" and note_alter(pred, 0) == "1"
    assert note_step(pred, 1) == "D" and note_alter(pred, 1) == "0"
    assert note_step(pred, 2) == "E" and note_alter(pred, 2) is None


def test_pred_more_than_gt_keeps_extra():
    """(e.1) pred 音符数 > gt 时，多出的 pred 音符保持原 alter。"""
    pred = make_root([make_note("C", alter=0),
                      make_note("D", alter=2),
                      make_note("E", alter=3)])
    gt = make_root([make_note("C", alter=1),
                    make_note("D", alter=1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_alter(pred, 0) == "1"   # C 对齐为 1
    assert note_alter(pred, 1) == "1"   # D 对齐为 1
    assert note_alter(pred, 2) == "3"   # E 超出 gt，保持原 3


def test_pred_has_rest_skipped():
    """(e.2) pred 含 <rest> 时跳过不报错，且其余音符正确对齐。"""
    pred = make_root([make_note("C", alter=0),
                      make_note("C", rest=True),
                      make_note("E", alter=0)])
    gt = make_root([make_note("C", alter=1),
                    make_note("E", alter=1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_alter(pred, 0) == "1"
    assert note_alter(pred, 1) == "1"


def test_gt_missing_alter_removes_pred_alter():
    """(e.3) gt 某音无 <alter> 时，pred 对应 <alter> 被移除。"""
    pred = make_root([make_note("C", alter=0)])
    gt = make_root([make_note("C", alter=None)])
    _apply_alters_gt_aligned(pred, gt, 0)
    assert note_alter(pred, 0) is None, "gt 无 alter 时 pred 的 alter 应被删除"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"[PASS] {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[ERROR] {t.__name__}: {e!r}")
    print(f"\n总计: {len(tests)}  通过: {passed}  失败: {failed}")
    sys.exit(1 if failed else 0)
