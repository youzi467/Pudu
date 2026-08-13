#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------
# 谱渡 Pudu · MusicXML 层差异检测
#
# 直接对比两个 MusicXML（识别输出 <pred.musicxml> vs 样本/GT <gt.musicxml>），
# 在 MusicXML 字段层报告差异，不依赖 Pudu.exe / music21（纯 stdlib + 复用
# omr_eval_lib 的 NW 对齐内核）。
#
# 与现有「简谱 JSON 层」评测（omr_eval_groundtruth.py）互补：
#   * 简谱层：Pudu.exe 把两个 MusicXML 投影为简谱，逐音比 degree/octaveDots/
#     underlines —— 测 Pudu 投影精度。
#   * 本工具：直接在 MusicXML 字段层比 pitch step/alter/octave、duration→qlen、
#     rest/grace/chord/tie、key/time_signature —— 测 MusicXML 一等输出精度。
#
# 对齐策略：**不能按小节号硬对齐**（实测 bach_p1 GT 20 小节 vs pred 18、canon_p1
# GT 264 音 vs pred 262），故复用 omr_eval_lib._nw_align（Needleman–Wunsch 全局
# 保序对齐，容增删）。对齐投影键用 midi-as-degree：事件 dict 内带
# degree=midi / octaveDots=0 / accidental="none"，使 midi 成为唯一音高锚。
#
# 类别词表（MusicXML 层，勿与简谱层的 underlines/augmentDashes/tuplet 混用）：
#   pitch / rhythm / rest / grace / chord / tie / key / time_signature
# event_count 单列（不计入通过率分母，与简谱层同口径）。
#
# CLI：
#   python omr_musicxml_diff.py <pred.musicxml> <gt.musicxml> [--limit N] [--json out.json]
# exit：文件缺失 → 1；正常恒 0（本工具是「检测差异」，有差异 ≠ 调用失败）。
# ----------------------------------------------------------------------
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from omr_eval_lib import (_nw_align, compare_doc_meta, compute_rates)  # noqa: E402

# ----------------------------------------------------------------------
# 类别词表（MusicXML 层）
# ----------------------------------------------------------------------

# 计入「通过率」的类别（字段级）
COUNTED_MXML = {"pitch", "rhythm", "rest", "grace", "chord", "tie",
                "key", "time_signature"}

# 逐音符评分类别（参与 category_pass 独立通过率）
PER_NOTE_MXML = {"pitch", "rhythm", "rest", "grace", "chord", "tie"}

# 十二平均律半音表（step -> pitch class）
_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

_QL_TOL = 1e-6  # qlen 浮点容差


# ----------------------------------------------------------------------
# 解析层
# ----------------------------------------------------------------------

def _local(tag) -> str:
    """取标签本地名（去掉 XML 命名空间前缀）。"""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _strip_ns(root):
    """就地剥命名空间（实测 GT 3.1 / pred 4.0.3 均无 ns，兜底用）。"""
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _midi(step: str, alter: int, octave: int) -> int:
    """step/alter/octave -> MIDI 编号。step 为空（rest）→ 0。"""
    if not step:
        return 0
    pc = _SEMI.get(step.upper(), 0)
    return 12 * (int(octave) + 1) + pc + int(alter or 0)


def _doc_meta(root) -> Dict:
    """取首个 <attributes> 的 {fifths, mode, beats, beatType}。"""
    attrs = root.find(".//attributes")
    meta = {"fifths": None, "mode": None, "beats": None, "beatType": None}
    if attrs is None:
        return meta
    meta["fifths"] = attrs.findtext("key/fifths")
    meta["mode"] = attrs.findtext("key/mode")
    meta["beats"] = attrs.findtext("time/beats")
    meta["beatType"] = attrs.findtext("time/beat-type")
    return meta


def _parse_note(note_el, divisions: int, mnum: int) -> Dict:
    """解析单个 <note> 为事件 dict（既喂对齐又喂比对）。"""
    is_rest = note_el.find("rest") is not None
    is_grace = note_el.find("grace") is not None
    is_chord = note_el.find("chord") is not None

    step = note_el.findtext("pitch/step")
    alter = note_el.findtext("pitch/alter")
    octave = note_el.findtext("pitch/octave")
    midi = _midi(step, int(alter) if alter else 0, int(octave) if octave else 0)

    dur_text = note_el.findtext("duration")
    # grace 通常无 <duration>；缺省 0（qlen=0.0，节奏比对按 qlen+type）
    duration = int(dur_text) if dur_text and dur_text.strip() else 0

    # tie 直接子元素 type="start|stop"（多元素容错）
    tie_to_next = any(t.attrib.get("type") == "start" for t in note_el.findall("tie"))
    tie_from_prev = any(t.attrib.get("type") == "stop" for t in note_el.findall("tie"))

    return {
        "mnum": mnum,
        "midi": midi,
        "step": step or "",
        "alter": int(alter) if alter else 0,
        "octave": int(octave) if octave else 0,
        "duration": duration,
        "qlen": duration / float(divisions) if divisions else 0.0,
        "type": note_el.findtext("type") or "",
        "isRest": is_rest,
        "isGrace": is_grace,
        "isChord": is_chord,
        "tieToNext": tie_to_next,
        "tieFromPrev": tie_from_prev,
        # NW 投影键（omr_eval_lib._nw_align 经 _default_note 读这 4 键）：
        "degree": midi,          # midi 作为唯一音高锚
        "octaveDots": 0,
        "accidental": "none",
    }


def parse_musicxml(path: str) -> Tuple[Dict, Dict]:
    """解析 MusicXML → (doc_meta, {part_id: [event, ...]})。

    divisions 按小节继承：小节无 <attributes>/<divisions> 时沿用上一小节（缺省 8）。
    只取 measure 直接子元素 <note>（backup/forward 语料无；出现时其不产生音符事件）。
    """
    tree = ET.parse(path)
    root = _strip_ns(tree.getroot())
    meta = _doc_meta(root)
    parts: Dict[str, List[Dict]] = {}
    for part in root.findall("part"):
        pid = part.attrib.get("id", "P1")
        events: List[Dict] = []
        divisions = 8
        for m in part.findall("measure"):
            try:
                mnum = int(m.attrib.get("number", "0"))
            except ValueError:
                mnum = 0
            attrs = m.find("attributes")
            if attrs is not None and attrs.findtext("divisions"):
                try:
                    divisions = int(attrs.findtext("divisions"))
                except (TypeError, ValueError):
                    pass
            for n in m.findall("note"):
                events.append(_parse_note(n, divisions, mnum))
        parts[pid] = events
    return meta, parts


# ----------------------------------------------------------------------
# 比对层
# ----------------------------------------------------------------------

def _compare_mxml_rhythm(pred_ev: Dict, gt_ev: Dict) -> Tuple[int, List]:
    """比对时值（qlen 容差 + type 字符串）。返回 (n_checked, diffs)。"""
    diffs = []
    n_checked = 1
    if abs(float(pred_ev["qlen"]) - float(gt_ev["qlen"])) > _QL_TOL:
        diffs.append(("qlen", gt_ev["qlen"], pred_ev["qlen"], "rhythm"))
    if pred_ev["type"] != gt_ev["type"]:
        diffs.append(("type", gt_ev["type"], pred_ev["type"], "rhythm"))
    return n_checked, diffs


def compare_musicxml_event(pred_ev: Dict, gt_ev: Dict) -> Tuple[List, int]:
    """比对两个 MusicXML 音符事件。返回 (diffs, n_checked)。

    镜像 omr_eval_lib.compare_jianpu_note 的 (diffs, n_checked) 口径，但类别用
    MusicXML 层词表：pitch（含 step/alter/octave/midi）/ rhythm / rest / grace /
    chord / tie。
    """
    diffs = []
    n_checked = 0

    # ---- 休止符 ----
    if gt_ev["isRest"]:
        n_checked += 1
        if not pred_ev["isRest"]:
            diffs.append(("isRest", True, pred_ev["isRest"], "rest"))
        rn, rdiffs = _compare_mxml_rhythm(pred_ev, gt_ev)
        n_checked += rn
        diffs.extend(rdiffs)
        return diffs, n_checked

    # ---- 音高（category 统一 "pitch"） ----
    n_checked += 1
    if pred_ev["step"] != gt_ev["step"]:
        diffs.append(("step", gt_ev["step"], pred_ev["step"], "pitch"))
    n_checked += 1
    if pred_ev["alter"] != gt_ev["alter"]:
        diffs.append(("alter", gt_ev["alter"], pred_ev["alter"], "pitch"))
    n_checked += 1
    if pred_ev["octave"] != gt_ev["octave"]:
        diffs.append(("octave", gt_ev["octave"], pred_ev["octave"], "pitch"))
    n_checked += 1
    if pred_ev["midi"] != gt_ev["midi"]:
        diffs.append(("midi", gt_ev["midi"], pred_ev["midi"], "pitch"))

    # ---- 和弦 / 装饰音 / 延音线 ----
    n_checked += 1
    if pred_ev["isChord"] != gt_ev["isChord"]:
        diffs.append(("isChord", gt_ev["isChord"], pred_ev["isChord"], "chord"))
    n_checked += 1
    if pred_ev["isGrace"] != gt_ev["isGrace"]:
        diffs.append(("isGrace", gt_ev["isGrace"], pred_ev["isGrace"], "grace"))
    n_checked += 1
    if pred_ev["tieToNext"] != gt_ev["tieToNext"]:
        diffs.append(("tieToNext", gt_ev["tieToNext"], pred_ev["tieToNext"], "tie"))
    n_checked += 1
    if pred_ev["tieFromPrev"] != gt_ev["tieFromPrev"]:
        diffs.append(("tieFromPrev", gt_ev["tieFromPrev"], pred_ev["tieFromPrev"], "tie"))

    # ---- 节奏 ----
    rn, rdiffs = _compare_mxml_rhythm(pred_ev, gt_ev)
    n_checked += rn
    diffs.extend(rdiffs)

    return diffs, n_checked


# ----------------------------------------------------------------------
# 对齐 + 聚合
# ----------------------------------------------------------------------

def _new_rep(pred_path: str, gt_path: str) -> Dict:
    """报告容器（对齐 omr_eval_groundtruth._eval_one 的 rep schema）。"""
    return {
        "pred_musicxml": pred_path,
        "gt_musicxml": gt_path,
        "notes_compared": 0, "notes_correct": 0,
        "field_checked": 0, "field_failed": 0,
        "category_counts": {}, "diffs": [],
        "category_note_fail": {},
        "category_pass": {},
        "note_pass": 0.0, "field_pass": 0.0,
    }


def _record_leftover(rep: Dict, side: str, ev: Dict, part: str) -> None:
    """未配对音符（only-in-pred / only-in-gt）→ event_count 口径。

    与简谱层一致：计 1 个已校验字段并计 1 次失败，类别单列（不计入通过率分母）。
    """
    rep["field_checked"] += 1
    rep["field_failed"] += 1
    rep["category_counts"]["event_count"] = \
        rep["category_counts"].get("event_count", 0) + 1
    rep["diffs"].append({
        "part": part, "measure": ev.get("mnum", -1),
        "field": f"{side}-only",
        "expected": None, "actual": None,
        "category": "event_count",
    })


def _align_per_part(pred_events: List[Dict], gt_events: List[Dict]):
    """单 part 音符流 NW 对齐。返回 (pairs, c_left, g_left)。

    item 形状 `(mnum, event_dict)` 喂 omr_eval_lib._nw_align（经 _default_note
    读 degree/octaveDots/accidental/isRest 投影键）。leftover 为未配对事件。
    """
    c_items = [(ev["mnum"], ev) for ev in pred_events]
    g_items = [(ev["mnum"], ev) for ev in gt_events]
    return _nw_align(c_items, g_items)


def _compare_part(rep: Dict, part: str, pred_events: List[Dict],
                  gt_events: List[Dict]) -> None:
    """单 part：NW 对齐 + 逐事件比对 + leftover 计数。"""
    pairs, c_left, g_left = _align_per_part(pred_events, gt_events)
    for c_item, g_item in pairs:
        c_ev, g_ev = c_item[1], g_item[1]
        diffs, n_checked = compare_musicxml_event(c_ev, g_ev)
        rep["notes_compared"] += 1
        rep["field_checked"] += n_checked
        failed = 0
        failed_cats = set()
        for field, exp, act, cat in diffs:
            rep["category_counts"][cat] = rep["category_counts"].get(cat, 0) + 1
            failed_cats.add(cat)
            if cat in COUNTED_MXML:
                failed += 1
            rep["diffs"].append({
                "part": part, "measure": c_ev.get("mnum", g_ev.get("mnum", -1)),
                "field": field,
                "expected": exp if not isinstance(exp, tuple) else list(exp),
                "actual": act if not isinstance(act, tuple) else list(act),
                "category": cat,
            })
        rep["field_failed"] += failed
        if not failed_cats:
            rep["notes_correct"] += 1
        for cat in failed_cats:
            if cat in PER_NOTE_MXML:
                rep["category_note_fail"][cat] = rep["category_note_fail"].get(cat, 0) + 1
    for ev in c_left:
        _record_leftover(rep, "pred", ev[1], part)
    for ev in g_left:
        _record_leftover(rep, "gt", ev[1], part)


def _category_pass(notes_compared: int, cat_note_fail: Dict) -> Dict:
    """每维度独立通过率（仅 PER_NOTE_MXML，镜像简谱层口径）。"""
    if notes_compared == 0:
        return {}
    out = {}
    for cat in sorted(PER_NOTE_MXML):
        fails = cat_note_fail.get(cat, 0)
        out[cat] = round((notes_compared - fails) / notes_compared * 100.0, 2)
    return out


def diff_files(pred_path: str, gt_path: str) -> Tuple[Dict, List]:
    """对比两个 MusicXML，返回 (rep, ledger)。ledger 即 rep["diffs"]。"""
    p_meta, p_parts = parse_musicxml(pred_path)
    g_meta, g_parts = parse_musicxml(gt_path)
    rep = _new_rep(pred_path, gt_path)

    # —— 文档级：复用 compare_doc_meta，但跳过 mode（pred 缺 <mode> 防假阳） ——
    for field, exp, act, cat in compare_doc_meta(p_meta, g_meta):
        if cat == "mode":
            continue
        rep["field_checked"] += 1
        rep["field_failed"] += 1
        rep["category_counts"][cat] = rep["category_counts"].get(cat, 0) + 1
        rep["diffs"].append({
            "part": -1, "measure": -1, "field": field,
            "expected": exp if not isinstance(exp, tuple) else list(exp),
            "actual": act if not isinstance(act, tuple) else list(act),
            "category": cat,
        })

    # —— 逐 part 按索引配对（sorted 保证两侧顺序一致） ——
    p_ids = sorted(p_parts)
    g_ids = sorted(g_parts)
    for i, pid in enumerate(p_ids):
        if i < len(g_ids):
            _compare_part(rep, pid, p_parts[pid], g_parts[g_ids[i]])
        else:
            for ev in p_parts[pid]:
                _record_leftover(rep, "pred", ev, pid)
    for j in range(len(p_ids), len(g_ids)):
        for ev in g_parts[g_ids[j]]:
            _record_leftover(rep, "gt", ev, g_ids[j])

    rep["category_pass"] = _category_pass(rep["notes_compared"],
                                          rep["category_note_fail"])
    rep["note_pass"], rep["field_pass"] = compute_rates(
        rep["notes_compared"], rep["notes_correct"],
        rep["field_checked"], rep["field_failed"])
    return rep, rep["diffs"]


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def render_text(rep: Dict, *, limit: Optional[int] = None) -> str:
    """中文可读报告。"""
    lines = []
    lines.append("=" * 60)
    lines.append(f"pred: {rep['pred_musicxml']}")
    lines.append(f"gt  : {rep['gt_musicxml']}")
    lines.append("=" * 60)
    lines.append(f"音符比对: {rep['notes_compared']}  全对: {rep['notes_correct']}  "
                 f"note_pass: {rep['note_pass']:.2f}%")
    lines.append(f"字段比对: {rep['field_checked']}  失败: {rep['field_failed']}  "
                 f"field_pass: {rep['field_pass']:.2f}%")
    if rep["category_pass"]:
        cp = "  ".join(f"{k}={v}%" for k, v in rep["category_pass"].items())
        lines.append(f"逐维通过率: {cp}")
    if rep["category_counts"]:
        agg = sorted(rep["category_counts"].items(), key=lambda kv: -kv[1])
        lines.append("类别分布: " + "  ".join(f"{k}={v}" for k, v in agg))
    diffs = rep["diffs"]
    if diffs:
        lines.append(f"--- 差异明细（共 {len(diffs)} 条"
                     + (f"，显示前 {limit} 条" if limit else "") + "）---")
        shown = diffs if limit is None else diffs[:limit]
        for d in shown:
            exp = d["expected"]
            act = d["actual"]
            if isinstance(exp, list):
                exp = "/".join(str(x) for x in exp)
            if isinstance(act, list):
                act = "/".join(str(x) for x in act)
            lines.append(f"  [{d['category']}] part={d['part']} "
                         f"measure={d['measure']} {d['field']}: "
                         f"gt={exp} pred={act}")
    else:
        lines.append("无差异")
    return "\n".join(lines)


def render_json(rep: Dict) -> Dict:
    """机器可读账本（复制，避免泄漏内部引用）。"""
    out = dict(rep)
    out["diffs"] = list(rep["diffs"])
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omr_musicxml_diff.py",
        description="对比两个 MusicXML（识别输出 vs 样本/GT），在 MusicXML 字段层报告差异。")
    parser.add_argument("pred_musicxml", help="识别输出的 MusicXML")
    parser.add_argument("gt_musicxml", help="样本/GT 的 MusicXML")
    parser.add_argument("--limit", type=int, default=None,
                        help="差异明细显示条数（缺省全部）")
    parser.add_argument("--json", metavar="OUT", default=None,
                        help="写机器可读账本到指定文件")
    args = parser.parse_args(argv)

    if not os.path.exists(args.pred_musicxml):
        sys.stderr.write(f"[错误] pred 文件不存在: {args.pred_musicxml}\n")
        return 1
    if not os.path.exists(args.gt_musicxml):
        sys.stderr.write(f"[错误] gt 文件不存在: {args.gt_musicxml}\n")
        return 1

    try:
        rep, _ledger = diff_files(args.pred_musicxml, args.gt_musicxml)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] 对比失败: {e}\n")
        return 1

    sys.stdout.write(render_text(rep, limit=args.limit) + "\n")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(render_json(rep), f, ensure_ascii=False, indent=2)
        sys.stdout.write(f"[ok] 账本已写: {args.json}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
