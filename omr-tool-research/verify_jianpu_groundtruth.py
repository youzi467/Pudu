# -*- coding: utf-8 -*-
"""
谱渡 Pudu · 简谱转换 ground-truth 校验器（music21 交叉验证）
=================================================================

目标：用 music21 作为独立 ground-truth，校验 C++ 转换器（staffToJianpu）
生成的简谱是否在「音高 / 节奏 / 拍号 / 调号」上准确。

流程（对 data/ 下每个 .musicxml）：
  1) 运行 Pudu.exe --to-jianpu-json <tmp.json> 取转换器输出（JianpuDoc 结构化投影）。
  2) 用 music21 解析同一文件，独立推导「预期简谱」：
       - 音高：首调音级(degree)/临时记号(accidental)/八度点(octaveDots)。
           主音音级 tonicPc = (fifths*7) % 12，大调音阶模板 {0:1,2:2,4:3,5:4,7:5,9:6,11:7}；
           调外音按源 alter 择优（alter<0→上方邻级+Flat；alter>0→下方邻级+Sharp；
           alter==0→上方邻级+Flat），与转换器算法一致但用 Python 独立实现，
           构成跨语言交叉验证（非同源拷贝）。
       - 节奏：(underlines, augmentDashes, dots) 由 quarterLength 反推
           （whole=4.0→增3；half=2.0→增1；quarter=1.0；eighth=0.5→减1；
            16th=0.25→减2；32nd→减3；64th→减4；附点×1.5/×1.75）。
       - 拍号 / 调号：music21 解析到的初始拍号与初始调号（与转换器一致，均取首声部初始值）。
  3) 按 (part, 小节, 起始) 时间桶归并（music21 不保留 voice，两侧按绝对时间轴
     对齐；同桶内多声部音符按音高排序 1:1 配对）、逐事件比对，统计：
       - 通过率（字段级 + 音符级）
       - 错误类型分布（pitch_degree / pitch_accidental / pitch_octave /
                        rhythm / rest / chord / grace / tie / key / time_signature …）
       - 具体差异明细
  4) 边界处理：
       - 休止符：degree 必须为 0（isRest）。
       - 连音组(tuplet)：自选项 A 起解析 <time-modification> 标注分组，转换器输出
           tuplet(实际音符数)，与 music21 的 numberNotesActual 交叉比对（计入通过率）。
           连音内基准节奏由「实际 quarterLength × actual/normal」反推，与转换器同口径。
       - 变调：检测文件内调号变化，信息提示（转换器当前取初始调号）。
       - 和弦 / 装饰音 / 延音线：分别比对 chordDegrees / isGrace / tieToNext。

通过率口径：
   - 音符级通过率 = 0 差异（计入类）的音符数 / 参与比对的音符数。
   - 字段级通过率 = (已校验字段数 - 失败字段数) / 已校验字段数。
     注：连音组(tuplet / tuplet_rhythm)自选项 A 起已计入通过率；仅基准时值无法映射
     为标准时值者(如 7:8/7:4/9:4)单列 rhythm_unresolvable（未校验），不计入分母。

输出：结构化 JSON 报告 + Markdown 摘要 + 控制台汇总。

依赖：music21（已安装于 managed venv）；Pudu.exe 已构建。
运行：<managed_venv>/python.exe omr-tool-research/verify_jianpu_groundtruth.py
"""

import os
import sys
import json
import math
import tempfile
import subprocess
import warnings

# ---- 抑制 music21 / 第三方噪声 ----
warnings.filterwarnings("ignore")
try:
    import logging
    logging.getLogger("music21").setLevel(logging.ERROR)
except Exception:
    pass

from music21 import converter
from music21 import note as m21note
from music21 import chord as m21chord

# ---- 路径（Windows 绝对路径，与项目一致） ----
ROOT = r"C:\Users\13157\WorkBuddy\omr"
BUILD = os.path.join(ROOT, "build")
EXE = os.path.join(BUILD, "Pudu.exe")
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "omr-tool-research")
REPORT_JSON = os.path.join(OUT_DIR, "jianpu_groundtruth_report.json")
REPORT_MD = os.path.join(OUT_DIR, "jianpu_groundtruth_report.md")

# 大调音阶模板：index = pitch class (C=0)，value = 首调音级 1-7，0=非音阶音
MAJOR_SCALE = [1, 0, 2, 0, 3, 4, 0, 5, 0, 6, 0, 7]

# 标准时值基准 -> (增时线, 减时线)，用于 quarterLength 反推
RHYTHM_BASE = [
    (4.0,   3, 0),   # whole
    (2.0,   1, 0),   # half
    (1.0,   0, 0),   # quarter
    (0.5,   0, 1),   # eighth
    (0.25,  0, 2),   # 16th
    (0.125, 0, 3),   # 32nd
    (0.0625, 0, 4),  # 64th
]

# 计入「通过率」的字段级错误类别（其余为单列/未校验类别）
COUNTED_CATEGORIES = {
    "pitch_degree", "pitch_accidental", "pitch_octave",
    "rhythm", "rest", "chord", "grace", "tie",
    "key", "mode", "time_signature",
    "tuplet",          # 选项 A：连音分组标注(转换器 tuplet vs music21 actual-notes)
    "tuplet_rhythm",   # 选项 A：连音内基准节奏(基准时值 = 实际×actual/normal)
}
# 未校验类别（不计入通过率分母，仅列明细）
UNVALIDATED_CATEGORIES = {"rhythm_unresolvable", "event_count"}

# 同桶(同 part/小节/起始)内多声部音符的配对排序键：休止排前，其余按 (八度点, 音级, 记号)
_ACC_RANK = {"none": 0, "flat": 1, "sharp": 2, "natural": 3,
             "doubleflat": 4, "doublesharp": 5}
def _note_key(n):
    return (1 if n.get("isRest") else 0, n.get("octaveDots", 0),
            n.get("degree", 0), _ACC_RANK.get(n.get("accidental", "none"), 0))
def _event_key(e, tonic_pc):
    """与 _note_key 同构的 4 元组排序键（isRest, octave, degree, acc_rank），
    使转换器侧与 music21 侧按「同一套首调音级表示」排序，消除同 onset 两音
    排序方向相反导致的交叉误配。

    背景（partita m178 假阳性根因）：原实现 music21 侧按裸 midi 排序，转换器
    侧按 (degree, accidental) 排序。当同桶两音为 deg5/none 与 deg5/flat（即
    C 与 Bb）时，两侧顺序相反（转换器 [none,flat] vs music21 [Bb(71),C(72)]），
    稳定排序后把 C 错配给 Bb、Bb 错配给 C，产生 4 处假阳性节奏/记号差异。
    改用同一音级键后两侧顺序一致，正确音必与真实同音配对；真实转换器错误
    仍按真实音配对、照常报出，不掩盖缺陷。
    """
    if e["isRest"]:
        return (1, 0, 0, 0)
    p = min(e["pitches"], key=lambda x: x.midi)
    pc = p.pitchClass
    midi = p.midi
    alter = p.alter if p.alter is not None else 0.0
    deg, acc, octv = expected_pitch(pc, alter, midi, tonic_pc)
    return (0, octv, deg, _ACC_RANK.get(acc, 0))


# ----------------------------------------------------------------------
# 预期值推导（与转换器算法一致，但独立 Python 实现 -> 跨语言交叉验证）
# ----------------------------------------------------------------------

def fifths_to_tonic_pc(fifths):
    pc = (fifths * 7) % 12
    if pc < 0:
        pc += 12
    return pc


def expected_pitch(pc, alter, midi, tonic_pc):
    """返回 (degree, accidental_str, octave_dots)。"""
    semi = (pc - tonic_pc) % 12
    if MAJOR_SCALE[semi] != 0:
        degree = MAJOR_SCALE[semi]
        acc = "none"
    else:
        if alter < 0:
            base = (semi + 1) % 12
            acc = "flat"
        elif alter > 0:
            base = (semi - 1 + 12) % 12
            acc = "sharp"
        else:
            base = (semi + 1) % 12
            acc = "flat"
        degree = MAJOR_SCALE[base]
    octave = int(math.floor((midi - (tonic_pc + 60)) / 12.0))
    return degree, acc, octave


def expected_rhythm(ql):
    """由 quarterLength 反推 (underlines, augmentDashes, dots)；无法解析返回 None。"""
    for base, aug, ul in RHYTHM_BASE:
        if abs(ql - base) < 1e-4:
            return (ul, aug, 0)
        if abs(ql - base * 1.5) < 1e-4:   # 单附点
            return (ul, aug, 1)
        if abs(ql - base * 1.75) < 1e-4:  # 双附点
            return (ul, aug, 2)
    return None


# ----------------------------------------------------------------------
# music21 ground-truth 抽取
# ----------------------------------------------------------------------

def get_initial_key_time(score):
    """取初始调号 / 拍号，并检测调号变化。"""
    fifths, mode = 0, "major"
    ts_num, ts_den = 4, 4
    key_changes = False

    keys = list(score.recurse().getElementsByClass("KeySignature"))
    if keys:
        def _ks_mode(ks, default="major"):
            try:
                return ks.asKey().mode or default
            except Exception:
                return default
        fifths = keys[0].sharps
        mode = _ks_mode(keys[0])
        for k in keys[1:]:
            km = _ks_mode(k)
            if k.sharps != fifths or km != mode:
                key_changes = True
                break

    tss = list(score.recurse().getElementsByClass("TimeSignature"))
    if tss:
        ts_num = tss[0].numerator
        ts_den = tss[0].denominator

    return fifths, mode, ts_num, ts_den, key_changes


def to_event(el):
    """把 music21 的 Note/Chord/Rest 转为统一事件 dict。"""
    is_grace = False
    try:
        is_grace = bool(el.duration.isGrace)
    except Exception:
        pass
    try:
        dots = len(el.dots)
    except Exception:
        dots = 0
    try:
        tuplets = tuple(el.duration.tuplets)
    except Exception:
        tuplets = ()
    try:
        ql = float(el.quarterLength)
    except Exception:
        ql = 0.0
    try:
        ntype = el.duration.type
    except Exception:
        ntype = None
    try:
        tie = el.tie.type if el.tie else None
    except Exception:
        tie = None

    if isinstance(el, m21note.Rest):
        return {
            "isRest": True, "isGrace": False, "pitches": [],
            "quarterLength": ql, "type": ntype, "dots": dots,
            "tuplets": tuplets, "tie": tie,
        }
    if isinstance(el, m21chord.Chord):
        return {
            "isRest": False, "isGrace": is_grace,
            "pitches": [n.pitch for n in el.notes],
            "quarterLength": ql, "type": ntype, "dots": dots,
            "tuplets": tuplets, "tie": tie,
        }
    # 单音 Note
    return {
        "isRest": False, "isGrace": is_grace,
        "pitches": [el.pitch],
        "quarterLength": ql, "type": ntype, "dots": dots,
        "tuplets": tuplets, "tie": tie,
    }


def extract_events(score):
    """返回 {(part_idx, onset): [(measure_number, event_dict), ...]}，按绝对时间轴归并。

    说明：
      - onset = measure.offset + el.offset（单位 = quarterLength，与转换器同量纲）。
      - 仅以 (part, onset) 为桶键：转换器对多声部谱的「小节号」可能重复/错位
        （如 partita 全曲 419 个小节对象但编号仅 0..256），但 onset 为声部内
        绝对时间轴、唯一可靠；比对不以小节号为键，避免错配。
      - 同桶内多声部音符（同 onset）在 validate_file 中按音高排序 1:1 配对。
      - measure.recurse() 会丢弃休止符，故显式保留 Note/Chord/Rest。
    """
    result = {}
    for pi, part in enumerate(score.parts):
        for measure in part.getElementsByClass("Measure"):
            mnum = measure.number
            moff = float(measure.offset)
            for el in measure.recurse():
                if not isinstance(el, (m21note.Note, m21note.Rest, m21chord.Chord)):
                    continue
                on = round(moff + float(el.offset), 4)
                result.setdefault((pi, on), []).append((mnum, to_event(el)))
    return result


# ----------------------------------------------------------------------
# 单音比对：返回 (diffs, n_checked)
#   diffs: 每项 (field, expected, actual, category)
#   n_checked: 已校验字段数（计入通过率分母；未校验类别不计入）
# ----------------------------------------------------------------------

def compare_note(conv_note, gt_event, tonic_pc):
    diffs = []
    n_checked = 0

    # ---- 休止符 ----
    if gt_event["isRest"]:
        n_checked += 1
        if not conv_note["isRest"] or conv_note["degree"] != 0:
            diffs.append(("rest(degree=0)", "rest",
                          f"degree={conv_note['degree']} isRest={conv_note['isRest']}",
                          "rest"))
        # 休止也做节奏比对（时值）
        if not gt_event["isGrace"]:
            n_checked, rdiffs = _compare_rhythm(conv_note, gt_event)
            diffs.extend(rdiffs)
        return diffs, n_checked

    # ---- 音高（主音 = pitches[0]） ----
    pitch = gt_event["pitches"][0]
    pc = pitch.pitchClass
    midi = pitch.midi
    alter = pitch.alter if pitch.alter is not None else 0.0
    exp_deg, exp_acc, exp_oct = expected_pitch(pc, alter, midi, tonic_pc)

    n_checked += 1
    if conv_note["degree"] != exp_deg:
        diffs.append(("degree", exp_deg, conv_note["degree"], "pitch_degree"))
    n_checked += 1
    if conv_note["accidental"] != exp_acc:
        diffs.append(("accidental", exp_acc, conv_note["accidental"], "pitch_accidental"))
    n_checked += 1
    if conv_note["octaveDots"] != exp_oct:
        diffs.append(("octaveDots", exp_oct, conv_note["octaveDots"], "pitch_octave"))

    # ---- 和弦（其余音） ----
    if len(gt_event["pitches"]) > 1:
        exp_chord = []
        for p in gt_event["pitches"][1:]:
            d, _, _ = expected_pitch(p.pitchClass, p.alter or 0.0, p.midi, tonic_pc)
            exp_chord.append(d)
        n_checked += 1
        if conv_note["chordDegrees"] != exp_chord:
            diffs.append(("chordDegrees", exp_chord, conv_note["chordDegrees"], "chord"))

        # M1.5-A：逐音八度点（相对根音的偏移），与 chordDegrees 并列比对(ChordMember 维度)。
        #   旧转换器输出无此键 -> 跳过，不引入新的 counted 缺陷。
        if "chordOctaveDots" in conv_note:
            exp_cod = []
            for p in gt_event["pitches"][1:]:
                _, _, moct = expected_pitch(p.pitchClass, p.alter or 0.0, p.midi, tonic_pc)
                exp_cod.append(moct - exp_oct)
            n_checked += 1
            if conv_note["chordOctaveDots"] != exp_cod:
                diffs.append(("chordOctaveDots", exp_cod, conv_note["chordOctaveDots"], "chord"))

    # ---- 装饰音 ----
    n_checked += 1
    if conv_note["isGrace"] != gt_event["isGrace"]:
        diffs.append(("isGrace", gt_event["isGrace"], conv_note["isGrace"], "grace"))

    # ---- 延音线（start + stop 双端，M1.5-B） ----
    gt_tie = gt_event["tie"]
    gt_start = gt_tie in ("start", "continue")      # continue 同时是下一音的起点
    gt_stop = gt_tie in ("stop", "continue")        # continue 同时是上一音的止点
    n_checked += 1
    if conv_note.get("tieToNext", False) != gt_start:
        diffs.append(("tieToNext", gt_start, conv_note.get("tieToNext", False), "tie"))
    n_checked += 1
    if conv_note.get("tieFromPrev", False) != gt_stop:
        diffs.append(("tieFromPrev", gt_stop, conv_note.get("tieFromPrev", False), "tie"))

    # ---- 节奏 ----
    if not gt_event["isGrace"]:
        rn, rdiffs = _compare_rhythm(conv_note, gt_event)
        n_checked += rn
        diffs.extend(rdiffs)

    return diffs, n_checked


def _compare_rhythm(conv_note, gt_event):
    """返回 (n_checked, diffs)。连音组(tuplet)自选项 A 起进入校验（计入通过率）。

    - 连音分组(tuplet)：比对转换器 tuplet 字段(实际音符数)与 music21 的
      numberNotesActual；不一致记为 counted 缺陷。
    - 连音内基准节奏(tuplet_rhythm)：music21 的 quarterLength 为连音「实际」时值，
      基准时值 = 实际 × actual/normal，与转换器(jianpu_converter 由
      quarterLength×actual/normal 反推)同口径；映射为标准 (underlines,augmentDashes,dots)
      后逐字段比对。无法映射(如 7:8/7:4/9:4)单列 rhythm_unresolvable（未校验）。
    """
    diffs = []
    is_tuplet_gt = bool(gt_event["tuplets"])
    conv_grouping = conv_note.get("tuplet", 0) or 0

    if is_tuplet_gt:
        tup = gt_event["tuplets"][0]
        try:
            actual_notes = int(tup.numberNotesActual)
            normal_notes = int(tup.numberNotesNormal)
        except Exception:
            actual_notes = normal_notes = 0
        # —— 连音分组标注校验（计入） ——
        n_checked = 1
        if conv_grouping != actual_notes:
            diffs.append(("tuplet", actual_notes, conv_grouping, "tuplet"))
        # —— 连音内基准节奏校验（计入，基准时值可解析时） ——
        base_ql = gt_event["quarterLength"]
        if normal_notes > 0 and actual_notes > 0:
            base_ql = base_ql * (actual_notes / normal_notes)
        exp_rh = expected_rhythm(base_ql)
        actual = (conv_note["underlines"], conv_note["augmentDashes"], conv_note["dots"])
        if exp_rh is None:
            # 基准时值无法映射为标准时值 -> 节奏不计入，单列未校验
            diffs.append(("rhythm(tuplet)", "unresolvable_ql",
                          gt_event["quarterLength"], "rhythm_unresolvable"))
        else:
            n_checked += 1
            if actual != exp_rh:
                diffs.append(("rhythm(tuplet)", list(exp_rh), list(actual), "tuplet_rhythm"))
        return n_checked, diffs

    # 非连音组：转换器若误标 tuplet -> 记为缺陷（计入）
    if conv_grouping != 0:
        n_checked = 1
        diffs.append(("tuplet", 0, conv_grouping, "tuplet"))
    else:
        n_checked = 0
    # 常规节奏校验（原有逻辑）
    exp_rh = expected_rhythm(gt_event["quarterLength"])
    actual = (conv_note["underlines"], conv_note["augmentDashes"], conv_note["dots"])
    if exp_rh is None:
        diffs.append(("rhythm", "unresolvable_ql",
                      gt_event["quarterLength"], "rhythm_unresolvable"))
        return n_checked, diffs
    if actual != exp_rh:
        diffs.append(("rhythm", list(exp_rh), list(actual), "rhythm"))
    return n_checked + 1, diffs


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def run_converter_json(path):
    """运行 Pudu.exe --to-jianpu-json，返回 (json_obj_or_None, error_str)。"""
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="jianpu_gt_")
    os.close(fd)
    try:
        proc = subprocess.run(
            [EXE, path, "--to-jianpu-json", tmp],
            cwd=BUILD, capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            return None, f"exit={proc.returncode}; stderr={proc.stderr.decode('utf-8','replace')[:300]}"
        with open(tmp, "r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return None, f"exception: {e}"
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def flatten_json_lines(doc):
    """{(part, onset): [(measure_number, note_dict), ...]}，按绝对时间轴归并多声部。

    转换器按 voice 拆成多行；此处跨 voice 归并到同一 part 的绝对时间轴上，
    onset 与 music21 侧同为 quarterLength，两侧以 (part, onset) 为桶比对。
    """
    out = {}
    for line in doc.get("lines", []):
        part = line.get("part", 0)
        for m in line.get("measures", []):
            mnum = m.get("number", 0)
            for n in m.get("notes", []):
                on = round(float(n.get("onset", 0.0)), 4)
                out.setdefault((part, on), []).append((mnum, n))
    return out


def _merge_align(conv_b, gt_b, tol=0.03):
    """将转换器与 music21 的两侧时间桶按「part + 起始容差」对齐合并。

    背景：转换器(divisions 累积)与 music21(有理数)对同音的 quarterLength 起始
    在连音(tuplet)段落会因取整产生系统性偏移（实测 caprice 偏移中位数 0.0125、
    最大 0.025），使同一音被分到两侧相邻桶而误报 event_count。真实音符在连音段
    内相邻间隔 ≥ 0.1667，故 tol=0.03 足以合并同音偏移而不误并真实音符（非连音段
    两侧 onset 本就相等，合并无副作用）。
    返回 {(part, anchor_onset): {"c":[...], "g":[...]}}。
    """
    entries = []
    for (part, on), items in conv_b.items():
        entries.append((part, on, "c", items))
    for (part, on), items in gt_b.items():
        entries.append((part, on, "g", items))
    entries.sort(key=lambda e: (e[0], e[1]))
    out = {}
    cur = None  # (part, anchor_onset)
    for part, on, side, items in entries:
        if cur is None or part != cur[0] or (on - cur[1]) > tol:
            cur = (part, on)
            out[cur] = {"c": [], "g": []}
        out[cur][side].extend(items)
    return out


def validate_file(fn):
    path = os.path.join(DATA, fn)
    rep = {
        "file": fn, "fatal": None,
        "notes_compared": 0, "notes_correct": 0,
        "field_checked": 0, "field_failed": 0,
        "category_counts": {}, "diffs": [],
        "key_change_detected": False,
        "edge": {"rests": 0, "chords": 0, "graces": 0, "tuplets": 0},
    }

    # 1) 转换器输出
    doc, err = run_converter_json(path)
    if doc is None:
        rep["fatal"] = f"转换器运行失败: {err}"
        return rep
    conv_lines = flatten_json_lines(doc)
    doc_fifths = doc.get("fifths", 0)
    doc_mode = doc.get("mode", "major")
    doc_beats = doc.get("beats", 4)
    doc_beat_type = doc.get("beatType", 4)
    tonic_pc = fifths_to_tonic_pc(doc_fifths)

    # 2) music21 ground truth
    try:
        score = converter.parse(path)
    except Exception as e:
        rep["fatal"] = f"music21 解析失败: {e}"
        return rep
    gt_fifths, gt_mode, gt_num, gt_den, key_change = get_initial_key_time(score)
    rep["key_change_detected"] = key_change
    gt_events = extract_events(score)

    # 3) 文档级校验：调号 / 模式 / 拍号（各计 1 个已校验字段）
    _doc_check(rep, "key", gt_fifths, doc_fifths)
    _doc_check(rep, "mode", gt_mode, doc_mode)
    _doc_check(rep, "time_signature", (gt_num, gt_den), (doc_beats, doc_beat_type))

    # 4) 逐 (part, 起始) 时间桶比对（含容差对齐）
    #    music21 不保留 <voice>，两侧均按绝对时间轴归并到同一桶；
    #    同桶内多声部音符按音高排序后 1:1 配对，解决「同 onset 多声部」对齐问题；
    #    _merge_align 以 tol=0.03 合并连音段两侧 onset 系统性偏移（同音，非误并）。
    aligned = _merge_align(conv_lines, gt_events)
    for key in sorted(aligned):
        part, on = key
        conv_seq = aligned[key]["c"]
        gt_seq = aligned[key]["g"]
        if len(conv_seq) != len(gt_seq):
            rep["edge"]["_buckets_mismatched"] = rep["edge"].get("_buckets_mismatched", 0) + 1
            _doc_check(rep, "event_count",
                       f"gt={len(gt_seq)}", f"conv={len(conv_seq)}",
                       part=part, voice=-1)
        cn = sorted(conv_seq, key=lambda x: _note_key(x[1]))
        ge = sorted(gt_seq, key=lambda x: _event_key(x[1], tonic_pc))
        n = min(len(cn), len(ge))
        for i in range(n):
            cmnum, cnote = cn[i]
            gmnum, gevent = ge[i]
            mnum = cmnum if cmnum is not None else gmnum
            # 边界计数
            if gevent["isRest"]:
                rep["edge"]["rests"] += 1
            elif len(gevent["pitches"]) > 1:
                rep["edge"]["chords"] += 1
            if gevent["isGrace"]:
                rep["edge"]["graces"] += 1
            if gevent["tuplets"]:
                rep["edge"]["tuplets"] += 1
            # 比对
            diffs, n_checked = compare_note(cnote, gevent, tonic_pc)
            rep["notes_compared"] += 1
            rep["field_checked"] += n_checked
            failed = 0
            has_counted = False
            for field, exp, act, cat in diffs:
                rep["category_counts"][cat] = rep["category_counts"].get(cat, 0) + 1
                if cat in COUNTED_CATEGORIES:
                    failed += 1
                    has_counted = True
                rep["diffs"].append({
                    "part": part, "voice": -1, "measure": mnum,
                    "index": i, "field": field,
                    "expected": exp if not isinstance(exp, tuple) else list(exp),
                    "actual": act if not isinstance(act, tuple) else list(act),
                    "category": cat,
                })
            rep["field_failed"] += failed
            # 音符级通过：仅存在「计入类」差异才算错误；
            # 仅含未校验类别(连音/非常规时值/事件数)的音符仍记为正确。
            if not has_counted:
                rep["notes_correct"] += 1
        # 多余事件（仅一边有）
        for i in range(n, max(len(cn), len(ge))):
            rep["field_failed"] += 1
            rep["category_counts"]["event_count"] = rep["category_counts"].get("event_count", 0) + 1
            side = "conv" if i < len(cn) else "gt"
            cmnum = cn[i][0] if i < len(cn) else ge[i][0]
            rep["diffs"].append({
                "part": part, "voice": -1, "measure": cmnum if cmnum is not None else -1,
                "index": i, "field": "event_count",
                "expected": "paired event", "actual": f"only in {side}",
                "category": "event_count",
            })

    return rep


def _doc_check(rep, field, exp, act, part=None, voice=None):
    rep["field_checked"] += 1
    if exp != act:
        rep["field_failed"] += 1
        rep["category_counts"][field] = rep["category_counts"].get(field, 0) + 1
        rep["diffs"].append({
            "part": part if part is not None else -1,
            "voice": voice if voice is not None else -1,
            "measure": -1, "index": -1, "field": field,
            "expected": exp if not isinstance(exp, tuple) else list(exp),
            "actual": act if not isinstance(act, tuple) else list(act),
            "category": field,
        })


def main():
    files = sorted(f for f in os.listdir(DATA) if f.endswith(".musicxml"))
    file_reps = []
    agg = {
        "notes_compared": 0, "notes_correct": 0,
        "field_checked": 0, "field_failed": 0,
        "category_distribution": {},
        "edge": {"rests": 0, "chords": 0, "graces": 0, "tuplets": 0, "key_changes": 0},
        "fatal_files": [],
    }

    for fn in files:
        rep = validate_file(fn)
        file_reps.append(rep)
        if rep.get("fatal"):
            agg["fatal_files"].append(fn)
            print(f"[致命] {fn}: {rep['fatal']}")
            continue
        agg["notes_compared"] += rep["notes_compared"]
        agg["notes_correct"] += rep["notes_correct"]
        agg["field_checked"] += rep["field_checked"]
        agg["field_failed"] += rep["field_failed"]
        for cat, c in rep["category_counts"].items():
            agg["category_distribution"][cat] = agg["category_distribution"].get(cat, 0) + c
        if rep["key_change_detected"]:
            agg["edge"]["key_changes"] += 1
        for k in ("rests", "chords", "graces", "tuplets"):
            agg["edge"][k] += rep["edge"][k]

    field_pass_rate = ((agg["field_checked"] - agg["field_failed"]) / agg["field_checked"] * 100.0) \
        if agg["field_checked"] else 0.0
    note_pass_rate = (agg["notes_correct"] / agg["notes_compared"] * 100.0) \
        if agg["notes_compared"] else 0.0

    summary = {
        "files_total": len(files),
        "files_ok": len(files) - len(agg["fatal_files"]),
        "notes_compared": agg["notes_compared"],
        "notes_correct": agg["notes_correct"],
        "note_pass_rate": note_pass_rate,
        "field_checked": agg["field_checked"],
        "field_failed": agg["field_failed"],
        "field_pass_rate": field_pass_rate,
        "category_distribution": dict(sorted(agg["category_distribution"].items(),
                                             key=lambda kv: -kv[1])),
        "edge_case": agg["edge"],
        "fatal_files": agg["fatal_files"],
    }

    report = {"summary": summary, "files": file_reps}
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    _write_markdown(report, REPORT_MD)

    # ---- 控制台汇总 ----
    print("=" * 72)
    print("谱渡 Pudu · 简谱转换 ground-truth 校验（music21 交叉验证）")
    print("=" * 72)
    for rep in file_reps:
        if rep.get("fatal"):
            print(f"  [致命] {rep['file']}: {rep['fatal']}")
            continue
        rate = (rep["notes_correct"] / rep["notes_compared"] * 100.0) \
            if rep["notes_compared"] else 0.0
        kc = " [变调!]" if rep["key_change_detected"] else ""
        print(f"  {rep['file']}: 音符 {rep['notes_correct']}/{rep['notes_compared']} "
              f"通过 ({rate:.1f}%){kc}")
        if rep["diffs"]:
            for d in rep["diffs"][:8]:
                loc = f"p{d['part']}v{d['voice']}m{d['measure']}#{d['index']}"
                print(f"      - {d['category']}/{d['field']} [{loc}] "
                      f"预期={d['expected']} 实际={d['actual']}")
            if len(rep["diffs"]) > 8:
                print(f"      ... 其余 {len(rep['diffs']) - 8} 条差异见报告")
    print("-" * 72)
    print(f"总计：文件 {summary['files_ok']}/{summary['files_total']} 成功解析；"
          f"音符通过率 {note_pass_rate:.1f}% ({agg['notes_correct']}/{agg['notes_compared']})；"
          f"字段通过率 {field_pass_rate:.1f}% "
          f"({agg['field_checked'] - agg['field_failed']}/{agg['field_checked']})")
    print("错误类型分布（按差异数降序）：")
    for cat, c in summary["category_distribution"].items():
        flag = "" if cat in COUNTED_CATEGORIES else "  (单列/未校验)"
        print(f"    {cat}: {c}{flag}")
    e = agg["edge"]
    print(f"边界覆盖：变调文件 {e['key_changes']} 个；休止 {e['rests']} / 和弦 {e['chords']} / "
          f"装饰音 {e['graces']} / 连音组 {e['tuplets']} 个")
    print(f"报告已写出：\n  {REPORT_JSON}\n  {REPORT_MD}")


def _write_markdown(report, path):
    s = report["summary"]
    lines = []
    lines.append("# 谱渡 Pudu · 简谱转换 Ground-Truth 校验报告")
    lines.append("")
    lines.append(f"- 校验方式：music21 独立推导预期简谱，与 C++ 转换器(`staffToJianpu`)输出交叉比对")
    lines.append(f"- 样本文件：{s['files_total']}（成功 {s['files_ok']}，致命失败 {len(s['fatal_files'])}）")
    lines.append(f"- 音符级通过率：**{s['note_pass_rate']:.1f}%** "
                 f"（{s['notes_correct']}/{s['notes_compared']}）")
    lines.append(f"- 字段级通过率：**{s['field_pass_rate']:.1f}%** "
                 f"（{s['field_checked'] - s['field_failed']}/{s['field_checked']}）")
    lines.append("")
    lines.append("## 错误类型分布")
    lines.append("")
    lines.append("| 类别 | 差异数 | 计入通过率 |")
    lines.append("| --- | ---: | --- |")
    for cat, c in s["category_distribution"].items():
        counted = "是" if cat in COUNTED_CATEGORIES else "否（单列/未校验）"
        lines.append(f"| {cat} | {c} | {counted} |")
    lines.append("")
    lines.append("## 边界覆盖")
    lines.append("")
    e = s["edge_case"]
    lines.append(f"- 变调文件（检测到的调号变化）：{e['key_changes']} 个")
    lines.append(f"- 休止符音符：{e['rests']} 个")
    lines.append(f"- 和弦音符：{e['chords']} 个")
    lines.append(f"- 装饰音音符：{e['graces']} 个")
    lines.append(f"- 连音组音符（选项 A 起解析 time-modification 标注分组并进入校验）：{e['tuplets']} 个")
    lines.append(f"- 致命失败文件：{s['fatal_files'] or '无'}")
    lines.append("")
    lines.append("## 各文件明细")
    lines.append("")
    for rep in report["files"]:
        lines.append(f"### {rep['file']}")
        if rep.get("fatal"):
            lines.append(f"- 致命：{rep['fatal']}")
            lines.append("")
            continue
        rate = (rep["notes_correct"] / rep["notes_compared"] * 100.0) \
            if rep["notes_compared"] else 0.0
        lines.append(f"- 音符通过率：{rate:.1f}%（{rep['notes_correct']}/{rep['notes_compared']}）")
        if rep["key_change_detected"]:
            lines.append(f"- ⚠️ 检测到调号变化（转换器取初始调号，变调段不参与逐音比对）")
        if rep["diffs"]:
            lines.append(f"- 差异明细（{len(rep['diffs'])} 条，前 60 条）：")
            lines.append("")
            lines.append("  | part | voice | measure | idx | 类别 | 字段 | 预期 | 实际 |")
            lines.append("  | ---: | ---: | ---: | ---: | --- | --- | --- | --- |")
            for d in rep["diffs"][:60]:
                lines.append(
                    f"  | {d['part']} | {d['voice']} | {d['measure']} | {d['index']} "
                    f"| {d['category']} | {d['field']} | {d['expected']} | {d['actual']} |")
            if len(rep["diffs"]) > 60:
                lines.append(f"  | ... | | | | | | 其余 {len(rep['diffs']) - 60} 条见 JSON | |")
        else:
            lines.append(f"- 无差异 ✅")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
