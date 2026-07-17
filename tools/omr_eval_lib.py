# -*- coding: utf-8 -*-
"""
谱渡 Pudu · 简谱评测共享内核（omr_eval_lib）
============================================

从 `omr-tool-research/verify_jianpu_groundtruth.py` 抽取的可导入共享模块，供：

  * ``verify_jianpu_groundtruth.py`` —— MusicXML→简谱 校验（music21 交叉验证）
  * ``omr_eval_groundtruth.py``      —— oemer→简谱 评测 harness（双 Pudu 输出比对）

共用 **同一套错误类别口径** 与比对原语，避免逻辑分叉。

设计要点
--------
* 本模块为【纯 Python / 无第三方依赖】——不 import ``music21``，因此 harness
  在 ``--no-oemr`` 自验模式下无需 music21 即可运行（仅依赖 Pudu.exe）。
* 错误类别词汇表（``COUNTED_CATEGORIES``）与 ``verify_jianpu_groundtruth.py``
  完全一致：pitch_degree / pitch_accidental / pitch_octave / rhythm / rest /
  chord / grace / tie / key / mode / time_signature / tuplet / tuplet_rhythm。
  未校验类别（不计入通过率分母，仅列明细）见 ``UNVALIDATED_CATEGORIES``。

导出
----
* 常量：``MAJOR_SCALE`` / ``RHYTHM_BASE`` / ``COUNTED_CATEGORIES`` /
  ``UNVALIDATED_CATEGORIES`` / ``POSTCORRECT_RELEVANT``
* 推导：``fifths_to_tonic_pc`` / ``expected_pitch`` / ``expected_rhythm``
* 结构原语：``flatten_json_lines`` / ``_note_key`` / ``_merge_align`` / ``_doc_check``
* 比对内核：``compare_jianpu_note``（两简谱 JSON 音符逐音比对）
         ``compare_doc_meta``（文档级 key/mode/time_signature 比对）
         ``aggregate_category_distribution`` / ``compute_rates``
"""

import math

# ----------------------------------------------------------------------
# 常量（与 verify_jianpu_groundtruth.py 同口径）
# ----------------------------------------------------------------------

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
    "tuplet",          # 连音分组标注(转换器 tuplet vs ground-truth tuplet)
    "tuplet_rhythm",   # 连音内基准节奏(underlines/augmentDashes/dots)
}

# 未校验类别（不计入通过率分母，仅列明细）
UNVALIDATED_CATEGORIES = {"rhythm_unresolvable", "event_count"}

# 后处理规则引擎（P1-1）可修正/标记的错误类别（harness flagged_for_postcorrect 用）。
# 覆盖：节拍对账(rhythm/tuplet/tuplet_rhythm)、八度跳变(pitch_octave)、调内一致性(key/mode)。
POSTCORRECT_RELEVANT = {
    "rhythm", "tuplet", "tuplet_rhythm", "pitch_octave", "key", "mode",
}

# 同桶(同 part/onset)内多声部音符的配对排序键：休止排前，其余按 (八度点, 音级, 记号)
_ACC_RANK = {"none": 0, "flat": 1, "sharp": 2, "natural": 3,
             "doubleflat": 4, "doublesharp": 5}


# ----------------------------------------------------------------------
# 预期值推导（纯函数，无第三方依赖）
# ----------------------------------------------------------------------

def fifths_to_tonic_pc(fifths):
    """调号 fifths -> 主音 pitch class（取正模）。"""
    pc = (fifths * 7) % 12
    if pc < 0:
        pc += 12
    return pc


def expected_pitch(pc, alter, midi, tonic_pc):
    """由裸 pitch class / alter / midi 推导 (degree, accidental_str, octave_dots)。

    与转换器算法一致（大调首调音阶），但独立实现 -> 跨语言交叉验证。
    """
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
# 结构原语
# ----------------------------------------------------------------------

def _note_key(n):
    """同桶内多声部音符的配对排序键（isRest, octave, degree, acc_rank）。

    转换器侧与 ground-truth 侧都按此键排序，消除同 onset 两音排序方向
    相反导致的交叉误配（详见 verify_jianpu_groundtruth._event_key 注释）。
    """
    return (1 if n.get("isRest") else 0, n.get("octaveDots", 0),
            n.get("degree", 0), _ACC_RANK.get(n.get("accidental", "none"), 0))


def flatten_json_lines(doc):
    """{(part, onset): [(measure_number, note_dict), ...]}，按绝对时间轴归并多声部。

    Pudu 的 JianpuDoc JSON 按 voice 拆成多行；此处跨 voice 归并到同一 part 的
    绝对时间轴上，onset 单位为 quarterLength，与另一侧的 (part, onset) 桶对齐。
    与 verify_jianpu_groundtruth.flatten_json_lines 同实现，保证口径一致。
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
    """将两侧时间桶按「part + 起始容差」对齐合并。

    背景：转换器(divisions 累积)与 ground-truth(可能不同 divisions)对同一音的
    onset 在连音(tuplet)段落会因取整产生系统性偏移。tol=0.03 足以合并同音偏移
    而不误并真实音符（连音段内相邻间隔远大于此）。
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


def _doc_check(rep, field, exp, act, part=None, voice=None):
    """文档/桶级单字段校验，就地累加 rep 的 field_checked/field_failed/分类计数。"""
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


# ----------------------------------------------------------------------
# 比对内核（harness 主用：两简谱 JSON 音符逐音比对）
# ----------------------------------------------------------------------

def _default_note(n):
    """把简谱 JSON 音符规整为全字段字典，保证比对键齐全（容错缺省值）。"""
    return {
        "degree": n.get("degree", 0),
        "octaveDots": n.get("octaveDots", 0),
        "accidental": n.get("accidental", "none"),
        "underlines": n.get("underlines", 0),
        "augmentDashes": n.get("augmentDashes", 0),
        "dots": n.get("dots", 0),
        "isRest": n.get("isRest", False),
        "isGrace": n.get("isGrace", False),
        "tieToNext": n.get("tieToNext", False),
        "tieFromPrev": n.get("tieFromPrev", False),
        "tuplet": n.get("tuplet", 0) or 0,
        "chordDegrees": n.get("chordDegrees", []) or [],
        "chordOctaveDots": n.get("chordOctaveDots", None),
        "rhythmUnresolvable": n.get("rhythmUnresolvable", False),
    }


def _compare_jianpu_rhythm(p, g):
    """比对两简谱音符的时值字段。返回 (n_checked, diffs)。

    连音组(tuplet)标注不一致计为 counted 缺陷；连音内基准节奏归入
    ``tuplet_rhythm``，常规节奏归入 ``rhythm``。
    """
    diffs = []
    is_tuplet = (g["tuplet"] != 0) or (p["tuplet"] != 0)
    n_checked = 0
    # —— 连音分组标注校验（计入） ——
    if g["tuplet"] != p["tuplet"]:
        n_checked += 1
        diffs.append(("tuplet", g["tuplet"], p["tuplet"], "tuplet"))
    # —— 常规/基准节奏校验（计入） ——
    exp = (g["underlines"], g["augmentDashes"], g["dots"])
    act = (p["underlines"], p["augmentDashes"], p["dots"])
    n_checked += 1
    if exp != act:
        cat = "tuplet_rhythm" if is_tuplet else "rhythm"
        diffs.append(("rhythm", list(exp), list(act), cat))
    return n_checked, diffs


def compare_jianpu_note(pred_note, gt_note):
    """比对一个预测简谱音符与一个 ground-truth 简谱音符。

    两侧均为 Pudu ``--to-jianpu-json`` 产出的 JianpuDoc 音符 dict（同 schema）。
    返回 ``(diffs, n_checked)``：
      * ``diffs``：元素为 ``(field, expected, actual, category)`` 元组；
      * ``n_checked``：已校验字段数（计入通过率分母；未校验类别不计入）。

    错误类别复用 ``COUNTED_CATEGORIES`` 词汇：pitch_degree / pitch_accidental /
    pitch_octave / rhythm / rest / chord / grace / tie / tuplet / tuplet_rhythm。
    """
    p = _default_note(pred_note)
    g = _default_note(gt_note)
    diffs = []
    n_checked = 0

    # ---- 休止符 ----
    if g["isRest"]:
        n_checked += 1
        if (not p["isRest"]) or p["degree"] != 0:
            diffs.append(("isRest/degree", True,
                          f"isRest={p['isRest']} degree={p['degree']}", "rest"))
        rn, rdiffs = _compare_jianpu_rhythm(p, g)
        n_checked += rn
        diffs.extend(rdiffs)
        return diffs, n_checked

    # ---- 音高（主音） ----
    n_checked += 1
    if p["degree"] != g["degree"]:
        diffs.append(("degree", g["degree"], p["degree"], "pitch_degree"))
    n_checked += 1
    if p["accidental"] != g["accidental"]:
        diffs.append(("accidental", g["accidental"], p["accidental"], "pitch_accidental"))
    n_checked += 1
    if p["octaveDots"] != g["octaveDots"]:
        diffs.append(("octaveDots", g["octaveDots"], p["octaveDots"], "pitch_octave"))

    # ---- 和弦（其余音） ----
    if len(g["chordDegrees"]) > 0:
        n_checked += 1
        if p["chordDegrees"] != g["chordDegrees"]:
            diffs.append(("chordDegrees", g["chordDegrees"],
                          p["chordDegrees"], "chord"))
        if g["chordOctaveDots"] is not None:
            n_checked += 1
            if p["chordOctaveDots"] is None or p["chordOctaveDots"] != g["chordOctaveDots"]:
                diffs.append(("chordOctaveDots", g["chordOctaveDots"],
                              p["chordOctaveDots"], "chord"))

    # ---- 装饰音 ----
    n_checked += 1
    if p["isGrace"] != g["isGrace"]:
        diffs.append(("isGrace", g["isGrace"], p["isGrace"], "grace"))

    # ---- 延音线（双端） ----
    n_checked += 1
    if p["tieToNext"] != g["tieToNext"]:
        diffs.append(("tieToNext", g["tieToNext"], p["tieToNext"], "tie"))
    n_checked += 1
    if p["tieFromPrev"] != g["tieFromPrev"]:
        diffs.append(("tieFromPrev", g["tieFromPrev"], p["tieFromPrev"], "tie"))

    # ---- 节奏 ----
    rn, rdiffs = _compare_jianpu_rhythm(p, g)
    n_checked += rn
    diffs.extend(rdiffs)

    return diffs, n_checked


def compare_doc_meta(pred_meta, gt_meta):
    """比对文档级 meta（fifths/mode/beats/beatType），返回 diffs 列表。

    每处差异 category 为 key / mode / time_signature（均计入通过率）。
    """
    diffs = []
    if pred_meta.get("fifths") != gt_meta.get("fifths"):
        diffs.append(("fifths", gt_meta.get("fifths"),
                      pred_meta.get("fifths"), "key"))
    if pred_meta.get("mode") != gt_meta.get("mode"):
        diffs.append(("mode", gt_meta.get("mode"),
                      pred_meta.get("mode"), "mode"))
    gt_ts = (gt_meta.get("beats"), gt_meta.get("beatType"))
    pred_ts = (pred_meta.get("beats"), pred_meta.get("beatType"))
    if gt_ts != pred_ts:
        diffs.append(("time_signature", list(gt_ts), list(pred_ts), "time_signature"))
    return diffs


# ----------------------------------------------------------------------
# 聚合工具
# ----------------------------------------------------------------------

def aggregate_category_distribution(file_reps):
    """将多个 per-file 报告的 category_counts 合并为全局分布（按差异数降序）。"""
    agg = {}
    for rep in file_reps:
        for cat, c in rep.get("category_counts", {}).items():
            agg[cat] = agg.get(cat, 0) + c
    return dict(sorted(agg.items(), key=lambda kv: -kv[1]))


def compute_rates(notes_compared, notes_correct, field_checked, field_failed):
    """返回 (note_pass_rate, field_pass_rate)，百分比（0~100）。"""
    note_pass = (notes_correct / notes_compared * 100.0) if notes_compared else 0.0
    field_pass = ((field_checked - field_failed) / field_checked * 100.0) \
        if field_checked else 0.0
    return note_pass, field_pass


if __name__ == "__main__":
    # 轻量自测：验证共享内核导入与基本推导无误（正式单测见 omr_eval_lib_test.py）
    assert expected_rhythm(1.0) == (0, 0, 0)
    assert expected_rhythm(0.5) == (1, 0, 0)
    assert expected_rhythm(2.0) == (0, 1, 0)
    assert expected_rhythm(3.0) == (0, 1, 1)   # dotted half
    assert expected_rhythm(0.75) == (1, 0, 1)  # dotted eighth
    assert expected_rhythm(0.333) is None
    assert fifths_to_tonic_pc(2) == 2
    diffs, n_checked = compare_jianpu_note(
        {"degree": 1, "octaveDots": 0, "accidental": "none"},
        {"degree": 2, "octaveDots": 0, "accidental": "none"})
    assert any(cat == "pitch_degree" for _, _, _, cat in diffs)
    assert n_checked > 0
    print("[omr_eval_lib] 自测通过")
