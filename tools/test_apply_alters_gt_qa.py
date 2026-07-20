#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立(第二层)回归验证：omr_oemer.py Plan A 调号后处理 _apply_alters_gt_aligned 修复。

QA 工程师 Edward(严过关) 独立撰写，不依赖实现者自测结论。
仅用标准库 xml.etree 在内存构造 MusicXML，不 import oemer / music21。

覆盖(对应 team-lead 指派):
  (a) a 小调保留 G#/C#（含旧行为清零对照）
  (b) canon 误键 F->F# 修正
  (c) 无 gt 兜底 _apply_alters(root,2) D 大调 F/C=="1" 其余=="0"，且与 _accidental_map 契约一致(不回归)
  (d) 多声部对齐：同结构正确；per-part 音符数不同 -> 跨 part 错配(已知局限演示)；
      part 数不同且 gt 重排 -> 跨 part 错配(已知局限演示)
  (e) gt 音符数 < pred（过切分）：多出 pred 音符保持原 alter
  (f) pred 含 <rest>：跳过不崩
  (g) gt 某音无 <alter>：pred 对应 <alter> 被移除
  (+）八度不同步局限演示
  (w) correct_key_signature 端到端分支接线验证（有 gt -> 对齐 / 无 gt -> 兜底）

运行：
  python tools/test_apply_alters_gt_qa.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omr_oemer  # noqa: E402
from omr_oemer import (  # noqa: E402
    _apply_alters,
    _apply_alters_gt_aligned,
    correct_key_signature,
    _accidental_map,
)
import xml.etree.ElementTree as ET


# ----------------------------------------------------------------------
# 构造器
# ----------------------------------------------------------------------
def mk_note(step=None, alter=None, octave=4, rest=False):
    """构造一个 <note>。alter=None 表示不写 <alter>；rest=True 表示休止符。

    休止符可不传 step（step 仅非休止音符使用）。
    """
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
    o.text = str(octave)
    return note


def mk_root(notes):
    """单 part：把若干 <note> 包进 score-partwise>part>measure。"""
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part")
    measure = ET.SubElement(part, "measure")
    for n in notes:
        measure.append(n)
    return root


def mk_root_parts(parts, keys=None):
    """多 part：parts 为 list[list[note]]；keys 为可选 list[int|None] 给各 part 写 <key><fifths>。"""
    root = ET.Element("score-partwise")
    for pi, notes in enumerate(parts):
        part = ET.SubElement(root, "part")
        measure = ET.SubElement(part, "measure")
        if keys is not None and keys[pi] is not None:
            attrs = ET.SubElement(measure, "attributes")
            key = ET.SubElement(attrs, "key")
            f = ET.SubElement(key, "fifths")
            f.text = str(keys[pi])
        for n in notes:
            measure.append(n)
    return root


# ----------------------------------------------------------------------
# 访问器
# ----------------------------------------------------------------------
def non_rest_notes(root):
    return [n for n in root.iter("note") if n.find("rest") is None]


def alter_of(note):
    el = note.find("pitch/alter")
    return el.text if el is not None else None


def step_of(note):
    return note.find("pitch/step").text


def octave_of(note):
    return note.find("pitch/octave").text


# ----------------------------------------------------------------------
# (a) a 小调保留 G#/C#
# ----------------------------------------------------------------------
def test_a_minor_keeps_sharps_full_scale():
    """修复后：gt 的 G#/C# 逐音拷回 pred，不被清零。"""
    pred = mk_root([mk_note("A"), mk_note("B"), mk_note("C", 0), mk_note("D"),
                    mk_note("E"), mk_note("F"), mk_note("G", 0)])
    gt = mk_root([mk_note("A"), mk_note("B"), mk_note("C", 1), mk_note("D"),
                  mk_note("E"), mk_note("F"), mk_note("G", 1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    assert alter_of(notes[2]) == "1", "a 小调 C 应保留 gt 的 #1"
    assert alter_of(notes[6]) == "1", "a 小调 G 应保留 gt 的 #1"
    # gt 自然音(无 alter) -> pred 对应 alter 被移除
    assert alter_of(notes[0]) is None, "gt A 无 alter 时 pred A 的 alter 应被移除"


def test_a_minor_old_behavior_wipes_sharps():
    """对照(旧 bug)：无 gt 时 _apply_alters(root,0) 把所有 alter 清零 -> G#/C# 被抹。"""
    pred = mk_root([mk_note("A"), mk_note("B"), mk_note("C", 0), mk_note("D"),
                    mk_note("E"), mk_note("F"), mk_note("G", 0)])
    _apply_alters(pred, 0)  # 旧兜底在 a 小调(fifths=0)的行为
    notes = non_rest_notes(pred)
    assert alter_of(notes[2]) == "0", "旧行为：C# 被清为 0（bug 对照）"
    assert alter_of(notes[6]) == "0", "旧行为：G# 被清为 0（bug 对照）"


# ----------------------------------------------------------------------
# (b) canon 误键 F -> F#
# ----------------------------------------------------------------------
def test_canon_f_to_fsharp():
    """pred F 误键为 0，gt 对齐后应为 #1。"""
    pred = mk_root([mk_note("D", 0), mk_note("E", 0), mk_note("F", 0), mk_note("A", 0)])
    gt = mk_root([mk_note("D", 0), mk_note("E", 0), mk_note("F", 1), mk_note("A", 0)])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    assert alter_of(notes[2]) == "1", "canon F 应修正为 #1"


# ----------------------------------------------------------------------
# (c) 无 gt 兜底 + 不回归
# ----------------------------------------------------------------------
def test_no_gt_fallback_d_major():
    """_apply_alters(root,2) D 大调：F/C=='1'，其余=='0'。"""
    pred = mk_root([mk_note(s, 0) for s in ["C", "D", "E", "F", "G", "A", "B"]])
    _apply_alters(pred, 2)
    alters = {step_of(non_rest_notes(pred)[i]): alter_of(non_rest_notes(pred)[i])
              for i in range(7)}
    assert alters["F"] == "1" and alters["C"] == "1"
    assert all(alters[s] == "0" for s in ["D", "E", "G", "A", "B"])


def test_no_gt_fallback_consistent_with_accidental_map():
    """不回归：_apply_alters 输出须与 _accidental_map(fifths) 契约完全一致。"""
    for fifths in (-3, -1, 0, 1, 2, 4):
        pred = mk_root([mk_note(s, 0) for s in ["C", "D", "E", "F", "G", "A", "B"]])
        _apply_alters(pred, fifths)
        expected = _accidental_map(fifths)
        for i, step in enumerate(["C", "D", "E", "F", "G", "A", "B"]):
            got = alter_of(non_rest_notes(pred)[i])
            assert got == str(expected.get(step, 0)), \
                f"fifths={fifths} step={step}: 期望 {expected.get(step,0)} 实得 {got}"


# ----------------------------------------------------------------------
# (d) 多声部对齐
# ----------------------------------------------------------------------
def test_multi_part_same_structure_aligned():
    """同结构(2 part，各 3 音) -> 跨 part 文档顺序对齐正确。"""
    pred = mk_root_parts([
        [mk_note("C", 0), mk_note("D", 0), mk_note("E", 0)],
        [mk_note("F", 0), mk_note("G", 0), mk_note("A", 0)],
    ])
    gt = mk_root_parts([
        [mk_note("C", 0), mk_note("D", 0), mk_note("E", 1)],
        [mk_note("F", 1), mk_note("G", 0), mk_note("A", 0)],
    ])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    # 全局文档顺序：part1(C,D,E) 然后 part2(F,G,A)
    assert alter_of(notes[2]) == "1", "part1 第3音 E 应得 gt part1 的 #1"
    assert alter_of(notes[3]) == "1", "part2 第1音 F 应得 gt part2 的 #1"
    assert alter_of(notes[0]) == "0" and alter_of(notes[4]) == "0"


def test_multi_part_per_part_note_count_diff_misaligns():
    """已知局限演示：pred 与 gt 的 per-part 音符数不同 -> 全局索引对齐产生跨 part 错配。

    pred: part1=[C,D,E,F](4), part2=[G,A](2)
    gt  : part1=[C,D](2),   part2=[E,F,G,A](4)   (per-part 数量不一致)
    全局索引下 pred part1 的 E/F 会被 gt part2 的 #E/#F 污染 -> 错配。
    """
    pred = mk_root_parts([
        [mk_note("C", 0), mk_note("D", 0), mk_note("E", 0), mk_note("F", 0)],
        [mk_note("G", 0), mk_note("A", 0)],
    ])
    gt = mk_root_parts([
        [mk_note("C", 0), mk_note("D", 0)],
        [mk_note("E", 1), mk_note("F", 1), mk_note("G", 1), mk_note("A", 1)],
    ])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    # 实际行为(已知局限)：pred[2]=E(part1#3) 对齐到 gt[2]=E(part2#1) -> #1
    #                      pred[3]=F(part1#4) 对齐到 gt[3]=F(part2#2) -> #1
    assert alter_of(notes[2]) == "1", "跨 part 错配：pred part1 的 E 被 gt part2 的 #E 污染"
    assert alter_of(notes[3]) == "1", "跨 part 错配：pred part1 的 F 被 gt part2 的 #F 污染"


def test_multi_part_part_count_diff_reordered_misaligns():
    """已知局限演示：gt part 数与 pred 不同且音序重排 -> 跨 part 错配（step 被改写）。"""
    pred = mk_root_parts([
        [mk_note("C", 0), mk_note("D", 0), mk_note("E", 0)],
        [mk_note("F", 0), mk_note("G", 0), mk_note("A", 0)],
    ])
    gt = mk_root_parts([
        [mk_note("F", 1), mk_note("G", 1), mk_note("A", 1),
         mk_note("C", 0), mk_note("D", 0), mk_note("E", 0)],
    ])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    # 全局索引：pred[0]=C 对齐 gt[0]=F -> step 被改写为 "F"
    assert step_of(notes[0]) == "F", "跨 part 错配：pred 的 C 被 gt 首音 F 覆盖 step"
    assert alter_of(notes[0]) == "1"


# ----------------------------------------------------------------------
# (e) gt 音符数 < pred（过切分）
# ----------------------------------------------------------------------
def test_gt_fewer_than_pred_keeps_extra():
    """pred 音符数多于 gt：多出的 pred 音符保持原 alter。"""
    pred = mk_root([mk_note("C", 0), mk_note("D", 2), mk_note("E", 3)])
    gt = mk_root([mk_note("C", 1), mk_note("D", 1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    assert alter_of(notes[0]) == "1"   # C 对齐为 1
    assert alter_of(notes[1]) == "1"   # D 对齐为 1
    assert alter_of(notes[2]) == "3"   # E 超出 gt，保持原 3


# ----------------------------------------------------------------------
# (f) pred 含 <rest>
# ----------------------------------------------------------------------
def test_pred_contains_rest_skipped():
    """pred 含休止符：跳过不崩，其余音符正确对齐。"""
    pred = mk_root([mk_note("C", 0), mk_note(rest=True), mk_note("E", 0)])
    gt = mk_root([mk_note("C", 1), mk_note("E", 1)])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)  # 仅非休止
    assert alter_of(notes[0]) == "1"
    assert alter_of(notes[1]) == "1"
    # 休止符元素仍在
    rests = [n for n in mk_root([mk_note("C", 0), mk_note(rest=True), mk_note("E", 0)]).iter("note")
             if n.find("rest") is not None]
    assert len(rests) == 1


# ----------------------------------------------------------------------
# (g) gt 某音无 <alter> -> 移除 pred 对应 alter
# ----------------------------------------------------------------------
def test_gt_missing_alter_removes_pred_alter():
    """gt 某音无 <alter>：pred 对应 <alter> 被移除（多音上下文）。"""
    pred = mk_root([mk_note("C", 0), mk_note("D", 1)])
    gt = mk_root([mk_note("C", None), mk_note("D", 0)])
    _apply_alters_gt_aligned(pred, gt, 0)
    notes = non_rest_notes(pred)
    assert alter_of(notes[0]) is None, "gt C 无 alter -> pred C 的 alter 应被删除"
    assert alter_of(notes[1]) == "0"


# ----------------------------------------------------------------------
# (+) 八度不同步局限演示
# ----------------------------------------------------------------------
def test_octave_not_synced_limitation():
    """已知局限演示：仅拷贝 (step,alter)，不同步 octave -> pred 保持自身八度。"""
    pred = mk_root([mk_note("C", 0, octave=4)])
    gt = mk_root([mk_note("C", 1, octave=5)])  # 同 step，gt 高八度且带 #
    _apply_alters_gt_aligned(pred, gt, 0)
    n = non_rest_notes(pred)[0]
    assert step_of(n) == "C"
    assert alter_of(n) == "1"          # alter 被拷入
    assert octave_of(n) == "4"         # octave 未同步(仍是 pred 的 4)


# ----------------------------------------------------------------------
# (w) correct_key_signature 端到端分支接线
# ----------------------------------------------------------------------
def _write_tmp(root, suffix=".musicxml"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def test_correct_key_signature_with_gt_branch():
    """有 gt -> 走 _apply_alters_gt_aligned 对齐分支；a 小调 G#/C# 保留。"""
    pred = mk_root_parts([[
        mk_note("A"), mk_note("B"), mk_note("C", 0), mk_note("D"),
        mk_note("E"), mk_note("F"), mk_note("G", 0)]], keys=[0])
    gt = mk_root_parts([[
        mk_note("A"), mk_note("B"), mk_note("C", 1), mk_note("D"),
        mk_note("E"), mk_note("F"), mk_note("G", 1)]], keys=[0])
    pred_path = _write_tmp(pred)
    gt_path = _write_tmp(gt)
    try:
        result = correct_key_signature(pred_path, gt_path)
        assert result == 0, f"目标 fifths 应为 0，实得 {result}"
        tree = ET.parse(pred_path)
        root = tree.getroot()
        notes = non_rest_notes(root)
        assert alter_of(notes[2]) == "1", "有 gt 分支：C# 应保留"
        assert alter_of(notes[6]) == "1", "有 gt 分支：G# 应保留"
        # 调号已写入
        assert root.find("part/measure/attributes/key/fifths") is not None
    finally:
        os.remove(pred_path)
        os.remove(gt_path)


def test_correct_key_signature_no_gt_fallback_branch():
    """无 gt -> 回退 _apply_alters 兜底；统计法推断 D 大调，F/C=='1'。"""
    # pred 音符已显式带 D 大调拼写 -> 统计推断 fifths=2
    pred = mk_root_parts([[
        mk_note("C", 1), mk_note("D", 0), mk_note("E", 0), mk_note("F", 1),
        mk_note("G", 0), mk_note("A", 0), mk_note("B", 0)]])
    pred_path = _write_tmp(pred)
    try:
        result = correct_key_signature(pred_path, None)
        assert result == 2, f"无 gt 应统计推断 fifths=2，实得 {result}"
        tree = ET.parse(pred_path)
        root = tree.getroot()
        notes = non_rest_notes(root)
        alters = {step_of(notes[i]): alter_of(notes[i]) for i in range(len(notes))}
        assert alters["F"] == "1" and alters["C"] == "1"
        assert all(alters[s] == "0" for s in ["D", "E", "G", "A", "B"])
    finally:
        os.remove(pred_path)


# ----------------------------------------------------------------------
# 运行器
# ----------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
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
            print(f"[ERROR] {t.__name__}: {type(e).__name__}: {e!r}")
    print(f"\n总计: {len(tests)}  通过: {passed}  失败: {failed}")
    sys.exit(1 if failed else 0)
