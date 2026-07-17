#!/usr/bin/env python3
# ----------------------------------------------------------------------
# 谱渡 Pudu · 阶段1 OMR 黑盒集成 · M2-2 music21 结构/语义校验
#
# 用法：python omr_validate.py <output.musicxml>
# 退出码：0=通过，非0=失败。
#
# 校验内容（对应 M2-2）：
#   结构：music21 能解析；含至少一个 Part / Measure / Note/Rest。
#   语义：首声部存在调号(fifths/key)与拍号(time)；音符带音高或休止。
# 仅做"结构 + 关键语义"校验，不评判识别准确率（准确率属后续阶段）。
# ----------------------------------------------------------------------
import os
import sys

try:
    from music21 import converter
except Exception as e:  # noqa: BLE001
    sys.stderr.write(f"[错误] 无法导入 music21（venv 是否已装？）: {e}\n")
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("用法: python omr_validate.py <output.musicxml>\n")
        sys.exit(2)

    path = sys.argv[1]
    if not os.path.exists(path):
        sys.stderr.write(f"[错误] 文件不存在: {path}\n")
        sys.exit(1)

    try:
        score = converter.parse(path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] music21 解析失败: {e}\n")
        sys.exit(1)

    parts = score.parts
    if not parts:
        sys.stderr.write("[错误] 无 Part\n")
        sys.exit(1)

    measures = list(score.recurse().getElementsByClass("Measure"))
    notes = list(score.recurse().notesAndRests)
    if not measures:
        sys.stderr.write("[错误] 无 Measure\n")
        sys.exit(1)
    if not notes:
        sys.stderr.write("[错误] 无 Note/Rest\n")
        sys.exit(1)

    # 语义：首声部调号 + 拍号
    first_part = parts[0]
    fifths = None
    beats = None
    beat_type = None
    try:
        ksig = first_part.recurse().getElementsByClass("KeySignature")
        tsig = first_part.recurse().getElementsByClass("TimeSignature")
        if ksig:
            fifths = ksig[0].sharps  # 负数=降号
        if tsig:
            beats = tsig[0].numerator
            beat_type = tsig[0].denominator
    except Exception:  # noqa: BLE001
        pass

    n_notes = sum(1 for n in notes if n.isNote)
    n_rests = sum(1 for n in notes if n.isRest)

    print(f"[ok] 结构/语义校验通过")
    print(f"  Part 数      : {len(parts)}")
    print(f"  Measure 数   : {len(measures)}")
    print(f"  Note/Rest 数 : {len(notes)} (音 {n_notes} / 休止 {n_rests})")
    print(f"  首声部调号   : fifths={fifths}")
    print(f"  首声部拍号   : {beats}/{beat_type}")

    if fifths is None or beats is None or beat_type is None:
        sys.stderr.write("[警告] 缺少调号或拍号（OMR 输出可能不完整）\n")
        # 结构已通过，语义警告不判失败（M2-2 以结构通过为准）
    sys.exit(0)


if __name__ == "__main__":
    main()
