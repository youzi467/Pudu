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
  ``UNVALIDATED_CATEGORIES`` / ``POSTCORRECT_RELEVANT`` / ``PER_NOTE_CATEGORIES``
* 推导：``fifths_to_tonic_pc`` / ``expected_pitch`` / ``expected_rhythm``
* 结构原语：``flatten_json_lines`` / ``_note_key`` / ``_merge_align`` / ``_doc_check``
* 比对内核：``compare_jianpu_note``（两简谱 JSON 音符逐音比对）
         ``compare_doc_meta``（文档级 key/mode/time_signature 比对）
         ``is_octave_jump``（H2(B) 八度跳变评分类别判定）
         ``aggregate_category_distribution`` / ``compute_rates``
"""

import math
from collections import defaultdict

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

# 逐音符评分类别（参与「每维度独立通过率」category_pass 计算）。
# 区别于文档级/桶级类别 key / mode / time_signature / event_count —— 后者不按
# 音符计数，仅列明细（见 UNVALIDATED_CATEGORIES / _doc_check），不参与 category_pass。
# ``octave_jump`` 由 H2(B) 提升为逐音符评分类别：pred 与 gt 的简谱八度点
# (octaveDots) 之差绝对值 >= 2。它不计入 COUNTED_CATEGORIES，因此不改变联立
# note_pass（向后兼容），仅作为独立维度进入 category_counts 与 category_pass。
PER_NOTE_CATEGORIES = {
    "pitch_degree", "pitch_accidental", "pitch_octave",
    "rhythm", "tuplet_rhythm", "rest", "chord", "grace", "tie",
    "octave_jump",
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


def _measure_of(item):
    """从 ``flatten_json_lines`` 产出的 ``(mnum, note)`` 元组提取小节号。

    小节号缺失或非元组时归一为 -1，保证分组键始终可哈希、可分组。
    """
    try:
        mnum = item[0] if isinstance(item, (list, tuple)) else None
    except (TypeError, IndexError):
        mnum = None
    return mnum if mnum is not None else -1


def _merge_align(conv_b, gt_b, tol=0.03):
    """将两侧时间桶按「part + 起始容差」对齐，并提供「同小节内音序对齐」fallback。

    阶段 1（主路径，保持原行为）
    ---------------------------
    按 (part, onset) 容差合并，处理同 onset 多声部、连音段系统性偏移。返回的桶若
    c 与 g 双边都存在则视为「已配对」，原样输出，由消费端按 ``_note_key`` 配对。

    阶段 2（fallback：绕过 oemer 时值漂移）
    ---------------------------------------
    oemer 的时值识别会漂移，使 pred 音符的 onset 相对 gt 偏移超过 ``tol``（极端时
    整页 onset 爬到 ~2298 而非 ~96）。同源音符于是落入不同 onset 桶、被计为
    ``event_count``「未配对」，从不真正比较 —— 这正是评测中 ``note_pass`` 畸低、
    ``event_count`` 未配对畸高的根因。

    为绕过该漂移，把所有「孤独音符」（仅单边非空的 onset 桶中的音符）按相同
    ``(part, measure)`` 内的**序列顺序**（按 onset 在组内排序）配对：位置 *i* 的
    孤独 c 与位置 *i* 的孤独 g 合并为 1:1 fallback 桶；剩余项作为单边孤独桶输出，
    由消费端正确标为 "only in pred" / "only in gt" 的 ``event_count`` 差异。

    该 fallback 是启发式，严格优于现状（现状下漂移音符从不比较）；oemer 真实的
    漏检/误检仍会以 ``event_count`` 暴露。

    返回值契约
    ----------
    ``{(part, anchor): {"c":[(mnum, note)...], "g":[(mnum, note)...]}}``。
    ``anchor`` 可为 onset（阶段1）或预留数值键（阶段2），均满足「可哈希、可排序、
    且 ``key[0] == part``」的消费端契约（消费端仅用 ``part`` 并迭代桶）。
    """
    # ===== 阶段 1：onset 容差合并（原逻辑，主路径） =====
    entries = []
    for (part, on), items in conv_b.items():
        entries.append((part, on, "c", items))
    for (part, on), items in gt_b.items():
        entries.append((part, on, "g", items))
    entries.sort(key=lambda e: (e[0], e[1]))

    onset_buckets = {}
    cur = None  # (part, anchor_onset)
    for part, on, side, items in entries:
        if cur is None or part != cur[0] or (on - cur[1]) > tol:
            cur = (part, on)
            onset_buckets[cur] = {"c": [], "g": []}
        onset_buckets[cur][side].extend(items)

    # ===== 阶段 2：同小节内音序对齐 fallback =====
    out = {}

    # 2a. 已配对桶（c 与 g 均非空）原样输出；单边桶收集「孤独音符」。
    #     孤独音符记录其原始 onset（= 所在 onset 桶的 anchor），用于组内序列排序。
    lonely = []  # [(part, mnum, side, onset, (mnum, note))]
    for key, bucket in onset_buckets.items():
        part, anchor = key
        c_items = bucket["c"]
        g_items = bucket["g"]
        if len(c_items) > 0 and len(g_items) > 0:
            out[key] = bucket  # 已配对，原样保留（消费端按 _note_key 配对）
            continue
        if len(c_items) > 0:
            for item in c_items:
                lonely.append((part, _measure_of(item), "c", anchor, item))
        else:  # g_items 非空、c_items 空
            for item in g_items:
                lonely.append((part, _measure_of(item), "g", anchor, item))

    # 2b. 按 (part, measure) 分组（measure 缺失时归一为 -1，保证可哈希/可分组）。
    groups = defaultdict(lambda: {"c": [], "g": []})
    for (part, mnum, side, onset, item) in lonely:
        groups[(part, mnum)][side].append((onset, item))

    # 2c. 组内各自按 onset 排序，按位置配对。
    #     fallback 键用预留数值区间（>= 1e9），与真实 onset（远小于此）严格隔离，
    #     保证与阶段1 的 (part, onset) 浮点键在同一字典「可排序、不冲突」。
    fb_counter = 0
    FB_BASE = 1e9
    for (_part, _mnum), grp in groups.items():
        c_sorted = sorted(grp["c"], key=lambda x: x[0])  # [(onset, (mnum, note)), ...]
        g_sorted = sorted(grp["g"], key=lambda x: x[0])
        n_c = len(c_sorted)
        n_g = len(g_sorted)
        n_pair = min(n_c, n_g)
        for i in range(n_pair):
            fb_key = (_part, FB_BASE + fb_counter)
            fb_counter += 1
            out[fb_key] = {"c": [c_sorted[i][1]], "g": [g_sorted[i][1]]}
        # 余量：仅单边存在 -> 单边孤独桶（消费端标为 only in pred / only in gt）。
        for i in range(n_pair, n_c):
            fb_key = (_part, FB_BASE + fb_counter)
            fb_counter += 1
            out[fb_key] = {"c": [c_sorted[i][1]], "g": []}
        for i in range(n_pair, n_g):
            fb_key = (_part, FB_BASE + fb_counter)
            fb_counter += 1
            out[fb_key] = {"c": [], "g": [g_sorted[i][1]]}

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


def is_octave_jump(pred_note, gt_note, threshold=2):
    """判定某音符是否构成「八度跳变」评分类别（H2(B) 交付物）。

    定义（清晰、可复现）
    -------------------
    简谱记谱中 ``octaveDots`` 表示八度点层数（+1=高八度一个点，-1=低八度一个点，
    依此类推；正负分别对应上/下加线）。当某音符 predicted 与 gt 的
    ``octaveDots`` 之差的绝对值 **>= threshold（默认 2）** 时，视为一次
    ``octave_jump``。

    此定义**直接复用**原 harness 在 ``edge_case.octave_jumps`` 中的跳变检测逻辑
    （``abs(p_octaveDots - g_octaveDots) >= 2``），但将其从「仅边界统计」提升为
    「逐音符可评分类别 octave_jump」：写入 ``category_counts`` 与 ``category_pass``，
    以便量化 F3/H1 对八度错的修复收益。

    注意：octave_jump 是 pitch_octave（任意八度点差）的**严格子集**（大八度错）。
    为保持联立 note_pass 向后兼容，octave_jump **不** 加入 COUNTED_CATEGORIES，
    即它不改变 note_pass / notes_correct，仅作为独立维度进入评分类别报告。

    Args:
        pred_note: 预测简谱音符 dict（含 ``octaveDots``）。
        gt_note: ground-truth 简谱音符 dict（含 ``octaveDots``）。
        threshold: 八度点差阈值，默认 2。

    Returns:
        bool: 是否构成 octave_jump。
    """
    p = _default_note(pred_note)
    g = _default_note(gt_note)
    return abs(p["octaveDots"] - g["octaveDots"]) >= threshold


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
