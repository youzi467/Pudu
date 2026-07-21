# -*- coding: utf-8 -*-
"""
谱渡 Pudu · oemer→简谱 错误分析 harness（评测基座 / P0-1）
=========================================================

目标
----
量化 **oemer 图像识别误差**在简谱层的分布（数字混淆/八度点遗漏/时值线错判等）。
给定一批 ``(image, gt_musicxml)`` 对（image=五线谱照片/扫描件，
gt_musicxml=该谱的 ground-truth MusicXML），harness 对每对：

  1. ``oemer(image) -> pred.musicxml``            （oemer 黑盒识别，可跳过）
  2. ``Pudu pred.musicxml --to-jianpu-json -> pred.json``
  3. ``Pudu gt.musicxml   --to-jianpu-json -> gt.json``
  4. 用与 ``verify_jianpu_groundtruth.py`` 同口径的错误类别，逐音比对
     ``pred.json`` vs ``gt.json``，输出
     ``note_pass_rate`` / ``field_pass_rate`` / ``category_distribution``。

设计要点
--------
* 比对内核复用 ``omr_eval_lib``（与 verify 同一套错误类别），保证
  「MusicXML→简谱」与「图片→简谱」两套评测口径一致、可叠加。
* ``pred.json`` 与 ``gt.json`` 是 **Pudu 对同一份乐谱的两次投影**，因此比对是
  纯简谱 JSON 对简谱 JSON（无需 music21），逻辑见 ``omr_eval_lib.compare_jianpu_note``。
* 对 ``(image, gt)`` 的配对支持两种约定，详见 ``data/omr_eval/README.md``：
    ① 同名约定：``foo.jpg`` + ``foo.gt.musicxml``
    ② ``manifest.csv``：列 ``image,gt_musicxml``（相对 corpus_dir 或绝对路径）

CLI
---
    python omr_eval_groundtruth.py <corpus_dir> [--oemr | --no-oemr]

  * ``--oemr``    （默认）运行 oemer 把 image 识别为 pred.musicxml 再评测。
  * ``--no-oemr`` 自验：直接用 ``gt.musicxml`` 当 ``pred``（跳过 oemer）。
                  用于验证比对管线本身——此时 ``note_pass_rate`` 必为 100%，
                  ``category_distribution`` 必为空（gt 与自身比对零差异）。

环境
----
* Pudu 二进制：``build/Pudu.exe``（已构建，支持 ``--to-jianpu-json``）。
* oemer 运行器：``tools/omr_oemer.py``（venv python 调用，需 CUDA/cuDNN）。
* venv python：``C:\\Users\\13157\\.workbuddy\\binaries\\python\\envs\\default\\Scripts\\python.exe``
  （含 music21/opencv/oemer）。harness 本体在 ``--no-oemr`` 下不依赖 music21。

注：``tools/omr_oemer.py`` 的真实 CLI 为 **位置参数** ``<image> <output>``，
故 ``run_oemer`` 以 ``venv_python omr_oemer.py <image> <out_musicxml>`` 调用
（与现有 Pudu→oemer 集成契约一致）。
"""

import os
import sys
import csv
import json
import argparse
import tempfile
import subprocess

# ---- 让本目录的 omr_eval_lib 可导入（harness 与 lib 同目录 tools/） ----
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from omr_eval_lib import (  # noqa: E402
    COUNTED_CATEGORIES,
    POSTCORRECT_RELEVANT,
    PER_NOTE_CATEGORIES,
    flatten_json_lines,
    _note_key,
    _merge_align,
    _doc_check,
    compare_jianpu_note,
    compare_doc_meta,
    is_octave_jump,
    aggregate_category_distribution,
    compute_rates,
)

# ---- 路径（与项目一致的 Windows 绝对路径） ----
ROOT = r"C:\Users\13157\WorkBuddy\omr"
BUILD = os.path.join(ROOT, "build")
EXE = os.path.join(BUILD, "Pudu.exe")
OMER_RUNNER = os.path.join(TOOLS_DIR, "omr_oemer.py")
VENV_PYTHON = r"C:\Users\13157\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".pdf")
GT_SUFFIX = ".gt.musicxml"


# ----------------------------------------------------------------------
# 步骤 1：oemer 识别（可跳过）
# ----------------------------------------------------------------------

def run_oemer(image_path, out_musicxml, gt_path=None, venv_python=VENV_PYTHON,
              f3_geometric=False):
    """调用 ``tools/omr_oemer.py`` 把五线谱图片识别为 MusicXML。

    命令：``venv_python tools/omr_oemer.py <image> <out_musicxml> [--gt <gt>]
    [--f3-geometric]``（omr_oemer.py 为位置参数契约，--gt 注入 ground-truth
    做方案A调号后处理重推断，--f3-geometric 开启 F3 几何音高校正，详见
    omr_oemer.py 模块 docstring）。

    Args:
        image_path: 输入五线谱图片路径。
        out_musicxml: 期望产出的 MusicXML 路径。
        gt_path: ground-truth MusicXML 路径；提供则注入 ``--gt`` 由
            omr_oemer.py 做调号校正（同名约定：与 image 同 base 的
            ``.gt.musicxml``）。None 时不注入（统计法 fallback）。
        venv_python: 含 oemer/music21/opencv 的 venv 解释器。
        f3_geometric: 是否透传 ``--f3-geometric`` 给 oemer 运行器（开启 F3
            几何音高校正）。也可经环境变量 ``PUDU_F3_GEOMETRIC=1`` 启用。

    Returns:
        bool: 成功产出有效 MusicXML 为 True，否则 False（并打印原因）。
    """
    f3_geometric = f3_geometric or (os.environ.get("PUDU_F3_GEOMETRIC") == "1")
    cmd = [venv_python, OMER_RUNNER, image_path, out_musicxml]
    if gt_path:
        cmd += ["--gt", gt_path]
    if f3_geometric:
        cmd += ["--f3-geometric"]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        print(f"[oemer] 调用异常: {e}")
        return False
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace")[:300]
        print(f"[oemer] 退出码 {proc.returncode}: {msg}")
        return False
    if not os.path.exists(out_musicxml) or os.path.getsize(out_musicxml) == 0:
        print(f"[oemer] 未产出有效 MusicXML: {out_musicxml}")
        return False
    print(f"[oemer] ok -> {out_musicxml}")
    return True


# ----------------------------------------------------------------------
# 步骤 2/3：Pudu 投影为简谱 JSON
# ----------------------------------------------------------------------

def pudu_jianpu_json(musicxml_path):
    """封装 ``build/Pudu.exe <musicxml> --to-jianpu-json <out.json>``。

    Args:
        musicxml_path: 输入 MusicXML 路径（可为 oemer 产出或 ground-truth）。

    Returns:
        dict: 解析后的 JianpuDoc JSON。

    Raises:
        RuntimeError: Pudu 退出非 0 或输出无法解析。
    """
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="eval_jp_")
    os.close(fd)
    try:
        proc = subprocess.run(
            [EXE, musicxml_path, "--to-jianpu-json", tmp],
            cwd=BUILD, capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Pudu 退出码 {proc.returncode}: "
                f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        with open(tmp, "r", encoding="utf-8") as f:
            return json.load(f)
    finally:
        try:
            os.remove(tmp)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
# 配对发现（两种约定）
# ----------------------------------------------------------------------

def _resolve(corpus_dir, p):
    """把相对 corpus_dir 的路径解析为绝对路径；绝对路径原样返回。"""
    if not p:
        return None
    return p if os.path.isabs(p) else os.path.join(corpus_dir, p)


def discover_pairs(corpus_dir, use_oemer):
    """发现 corpus_dir 下的 ``(image_path, gt_musicxml_path, base)`` 对。

    约定 ② 优先（manifest.csv），否则约定 ①（``*.gt.musicxml`` 同名约定）。
    找不到 gt 时跳过并告警；约定 ① 下若找不到配对图片：
      * ``use_oemer=True``  -> 跳过（oemer 需图片）；
      * ``use_oemer=False`` -> 保留（``--no-oemr`` 自验，pred 取 gt 自身）。
    """
    pairs = []
    manifest = os.path.join(corpus_dir, "manifest.csv")
    if os.path.isfile(manifest):
        with open(manifest, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gt = (row.get("gt_musicxml") or row.get("gt") or "").strip()
                if not gt:
                    continue
                image = (row.get("image") or "").strip()
                image_path = _resolve(corpus_dir, image)
                gt_path = _resolve(corpus_dir, gt)
                if not os.path.isfile(gt_path):
                    print(f"[warn] manifest 中 gt 不存在，跳过: {gt}")
                    continue
                if image_path is None and use_oemer:
                    print(f"[warn] manifest 中 image 缺失且需 oemer，跳过: {gt}")
                    continue
                base = os.path.splitext(os.path.basename(gt_path))[0]
                if base.endswith(".gt"):
                    base = base[:-3]
                pairs.append((image_path, gt_path, base))
        return pairs

    # 约定 ①：foo.jpg + foo.gt.musicxml
    gt_files = sorted(f for f in os.listdir(corpus_dir) if f.endswith(GT_SUFFIX))
    for gt in gt_files:
        base = gt[: -len(GT_SUFFIX)]  # 去掉 .gt.musicxml
        gt_path = os.path.join(corpus_dir, gt)
        image_path = None
        for ext in IMAGE_EXTS:
            cand = os.path.join(corpus_dir, base + ext)
            if os.path.isfile(cand):
                image_path = cand
                break
        if image_path is None:
            if use_oemer:
                print(f"[warn] 跳过（无配对图片，oemer 无法运行）: {gt}")
                continue
            # --no-oemr 自验：pred 将取 gt 自身
        pairs.append((image_path, gt_path, base))
    return pairs


# ----------------------------------------------------------------------
# 单文件评测
# ----------------------------------------------------------------------

def _new_rep(base, image_path, gt_path):
    return {
        "file": base,
        "image": image_path,
        "gt_musicxml": gt_path,
        "pred_musicxml": None,
        "fatal": None,
        "notes_compared": 0, "notes_correct": 0,
        "field_checked": 0, "field_failed": 0,
        "category_counts": {}, "diffs": [],
        "category_note_fail": {},   # {类别: 失败该类的音符数}（A 交付物，供 category_pass）
        "category_pass": {},       # {类别: 独立通过率}（A 交付物）
        "edge": {"rests": 0, "chords": 0, "graces": 0,
                 "tuplets": 0, "octave_jumps": 0},
    }


def _compute_category_pass(notes_compared, cat_note_fail):
    """计算「每维度独立通过率」category_pass（A 交付物）。

    对每个逐音符评分类别（见 PER_NOTE_CATEGORIES），独立通过率定义为：

        pass_rate(cat) = (notes_compared - 失败该类的音符数) / notes_compared * 100

    其中「失败该类的音符数」来自 ``cat_note_fail``（每个音符对每类最多计 1 次，
    与 category_counts 的逐音符类别计数一致）。

    与联立 ``note_pass`` 互补：``note_pass`` 是「所有维度同时正确」的联立通过率；
    ``category_pass`` 给出各维度各自的健康度（例如可独立看出
    pitch_degree 96% / pitch_octave 92% / rhythm 90% 分别的短板）。

    仅纳入逐音符类别；文档级/桶级类别（key / mode / time_signature /
    event_count）不按音符计数，不参与此处。``notes_compared == 0`` 时返回空
    dict（无音符可评）。

    Args:
        notes_compared: 已比对音符总数。
        cat_note_fail: {category: 失败该类的音符数}。

    Returns:
        dict: {category: 独立通过率(0~100, 两位小数)}。
    """
    if notes_compared == 0:
        return {}
    out = {}
    for cat in sorted(PER_NOTE_CATEGORIES):
        fails = cat_note_fail.get(cat, 0)
        rate = (notes_compared - fails) / notes_compared * 100.0
        out[cat] = round(rate, 2)
    return out


def _eval_one(corpus_dir, image_path, gt_path, base, use_oemer, f3_geometric=False):
    """评测单个 ``(image, gt)`` 对，返回 per-file 报告 dict。"""
    rep = _new_rep(base, image_path, gt_path)
    note_index = 0        # (C) 全局对齐序号，跨文件递增
    note_ledger = []      # (C) 逐音符 diff 账本，评测后写出 omr_eval_note_diffs.json

    # —— 步骤 1：oemer 识别（或 --no-oemr 自验取 gt 自身） ——
    if use_oemer:
        pred_musicxml = os.path.join(corpus_dir, base + ".pred.musicxml")
        # 注入 gt 路径（同名约定：与 image 同 base 的 .gt.musicxml），
        # 由 omr_oemer.py 做方案A调号后处理重推断，自动受益。
        # f3_geometric 透传（开启 F3 几何音高校正，仅影响 oemer 识别路径，
        # 不改比对内核 compare_jianpu_note / _merge_align）。
        if not run_oemer(image_path, pred_musicxml, gt_path=gt_path,
                         f3_geometric=f3_geometric):
            rep["fatal"] = "oemer 识别失败"
            rep["pred_musicxml"] = image_path
            return rep, []
    else:
        pred_musicxml = gt_path  # 自验：pred 与 gt 同源 -> 零差异
    rep["pred_musicxml"] = pred_musicxml

    # —— 步骤 2/3：Pudu 投影 ——
    try:
        pred_doc = pudu_jianpu_json(pred_musicxml)
    except Exception as e:  # noqa: BLE001
        rep["fatal"] = f"Pudu 处理 pred 失败: {e}"
        return rep, []
    try:
        gt_doc = pudu_jianpu_json(gt_path)
    except Exception as e:  # noqa: BLE001
        rep["fatal"] = f"Pudu 处理 gt 失败: {e}"
        return rep, []

    # —— 文档级校验：key / mode / time_signature（各 1 字段） ——
    _doc_check(rep, "key", gt_doc.get("fifths"), pred_doc.get("fifths"))
    _doc_check(rep, "mode", gt_doc.get("mode"), pred_doc.get("mode"))
    _doc_check(rep, "time_signature",
               (gt_doc.get("beats"), gt_doc.get("beatType")),
               (pred_doc.get("beats"), pred_doc.get("beatType")))

    # —— 逐 (part, onset) 时间桶比对（含容差对齐） ——
    pred_b = flatten_json_lines(pred_doc)
    gt_b = flatten_json_lines(gt_doc)
    aligned = _merge_align(pred_b, gt_b)
    for key in sorted(aligned):
        part, _on = key
        cn = sorted(aligned[key]["c"], key=lambda x: _note_key(x[1]))
        gn = sorted(aligned[key]["g"], key=lambda x: _note_key(x[1]))
        if len(cn) != len(gn):
            # 桶内事件数不一致：与 verify 的 _doc_check(event_count) 同口径
            # （计 1 个已校验字段并计 1 次失败，类别单列/未校验）。
            rep["field_checked"] += 1
            rep["field_failed"] += 1
            rep["category_counts"]["event_count"] = \
                rep["category_counts"].get("event_count", 0) + 1
        n = min(len(cn), len(gn))
        for i in range(n):
            cmnum, cnote = cn[i]
            gmnum, gnote = gn[i]
            mnum = cmnum if cmnum is not None else gmnum
            # 边界计数（以 gt 为参照）
            if gnote.get("isRest"):
                rep["edge"]["rests"] += 1
            elif len(gnote.get("chordDegrees", []) or []) > 0:
                rep["edge"]["chords"] += 1
            if gnote.get("isGrace"):
                rep["edge"]["graces"] += 1
            if (gnote.get("tuplet", 0) or 0) != 0:
                rep["edge"]["tuplets"] += 1
            # 逐音比对
            diffs, n_checked = compare_jianpu_note(cnote, gnote)
            rep["notes_compared"] += 1
            rep["field_checked"] += n_checked
            failed = 0
            has_counted = False
            failed_cats = set()
            for field, exp, act, cat in diffs:
                rep["category_counts"][cat] = rep["category_counts"].get(cat, 0) + 1
                failed_cats.add(cat)
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
            # —— (B) 八度跳变提升为逐音符评分类别 octave_jump ——
            # 定义（与 omr_eval_lib.is_octave_jump 同口径）：pred 与 gt 的简谱
            # 八度点(octaveDots)之差的绝对值 >= 2 即视为 octave_jump。该定义直接
            # 复用原 edge_case.octave_jumps 的跳变检测阈值，但把它从「仅边界统计」
            # 提升为「可评分类别」写入 category_counts 与 category_pass；为保持联立
            # note_pass 向后兼容，octave_jump 不计入 COUNTED_CATEGORIES（不额外
            # 改变联立通过率），仅作为独立维度曝光，便于量化 F3/H1 八度修复收益。
            if is_octave_jump(cnote, gnote):
                rep["edge"]["octave_jumps"] += 1
                rep["category_counts"]["octave_jump"] = \
                    rep["category_counts"].get("octave_jump", 0) + 1
                failed_cats.add("octave_jump")
            # 逐音符失败类别累加（用于 category_pass；仅统计逐音符类别）
            for cat in failed_cats:
                if cat in PER_NOTE_CATEGORIES:
                    rep["category_note_fail"][cat] = \
                        rep["category_note_fail"].get(cat, 0) + 1
            if not has_counted:
                rep["notes_correct"] += 1
            # —— (C) 逐音符 diff 账本条目（用于「待验证 #2」核对） ——
            note_index += 1
            note_ledger.append({
                "file": base,
                "index": note_index,
                "expected": {
                    "step": gnote.get("degree", 0),
                    "octave": gnote.get("octaveDots", 0),
                    "alter": gnote.get("accidental", "none"),
                },
                "actual": {
                    "step": cnote.get("degree", 0),
                    "octave": cnote.get("octaveDots", 0),
                    "alter": cnote.get("accidental", "none"),
                },
                "failed_categories": sorted(failed_cats),
            })
        # 多余事件（仅一边有）
        for i in range(n, max(len(cn), len(gn))):
            rep["field_failed"] += 1
            side = "pred" if i < len(cn) else "gt"
            cmnum = cn[i][0] if i < len(cn) else gn[i][0]
            rep["diffs"].append({
                "part": part, "voice": -1,
                "measure": cmnum if cmnum is not None else -1,
                "index": i, "field": "event_count",
                "expected": "paired event", "actual": f"only in {side}",
                "category": "event_count",
            })
    # —— (A) 每维度独立通过率（category_pass） ——
    rep["category_pass"] = _compute_category_pass(
        rep["notes_compared"], rep.get("category_note_fail", {}))
    return rep, note_ledger


# ----------------------------------------------------------------------
# 语料评测（主入口）
# ----------------------------------------------------------------------

def eval_corpus(corpus_dir, use_oemer=True, f3_geometric=False):
    """遍历 corpus_dir 下 ``(image, gt_musicxml)`` 对，量化 oemer→简谱 误差分布。

    Args:
        corpus_dir: 语料目录。
        use_oemer: 是否运行 oemer（False 为 --no-oemr 自验）。
        f3_geometric: 是否透传 ``--f3-geometric`` 给 oemer（开启 F3 几何校正）。
            仅影响 oemer 识别路径；--no-oemr 自验时该参数无效。

    Returns:
        dict: ``{summary:{note_pass_rate, field_pass_rate, category_distribution,
                          files_total, files_ok, notes_compared, notes_correct,
                          field_checked, field_failed, edge_case},
                per_file:[...], flagged_for_postcorrect:[...]}``
    """
    corpus_dir = os.path.abspath(corpus_dir)
    if not os.path.isdir(corpus_dir):
        raise FileNotFoundError(f"语料目录不存在: {corpus_dir}")

    pairs = discover_pairs(corpus_dir, use_oemer)
    if not pairs:
        raise RuntimeError(
            f"未在 {corpus_dir} 发现任何 (image, gt) 对："
            f"请放置 manifest.csv 或 *.gt.musicxml（见 data/omr_eval/README.md）")

    file_reps = []
    flagged = []
    note_ledger_all = []   # (C) 跨文件逐音符 diff 账本，评测后写出
    for image_path, gt_path, base in pairs:
        if image_path is None:
            print(f"[info] {base}: --no-oemr 自验，pred 取 gt 自身")
        else:
            print(f"[info] {base}: image={os.path.basename(image_path)}")
        rep, ledger = _eval_one(corpus_dir, image_path, gt_path, base,
                                use_oemer, f3_geometric=f3_geometric)
        file_reps.append(rep)
        note_ledger_all.extend(ledger)
        if rep.get("fatal"):
            print(f"  [致命] {base}: {rep['fatal']}")
            continue
        # 收集供后处理规则引擎(P1-1)关注的可修正/可标记差异
        for d in rep["diffs"]:
            if d["category"] in POSTCORRECT_RELEVANT:
                flagged.append({
                    "file": base,
                    "image": image_path,
                    "category": d["category"],
                    "field": d["field"],
                    "expected": d["expected"],
                    "actual": d["actual"],
                    "part": d["part"],
                    "measure": d["measure"],
                    "index": d["index"],
                })

    # —— 聚合 ——
    notes_compared = sum(r["notes_compared"] for r in file_reps)
    notes_correct = sum(r["notes_correct"] for r in file_reps)
    field_checked = sum(r["field_checked"] for r in file_reps)
    field_failed = sum(r["field_failed"] for r in file_reps)
    note_pass, field_pass = compute_rates(
        notes_compared, notes_correct, field_checked, field_failed)

    edge = {"rests": 0, "chords": 0, "graces": 0, "tuplets": 0, "octave_jumps": 0}
    for r in file_reps:
        for k in edge:
            edge[k] += r["edge"].get(k, 0)

    # —— (A) 聚合每维度独立通过率 ——
    cat_note_fail_total = {}
    for r in file_reps:
        for cat, c in r.get("category_note_fail", {}).items():
            cat_note_fail_total[cat] = cat_note_fail_total.get(cat, 0) + c
    category_pass = _compute_category_pass(notes_compared, cat_note_fail_total)

    summary = {
        "mode": "oemer" if use_oemer else "no_oemer_selfcheck",
        "files_total": len(file_reps),
        "files_ok": sum(1 for r in file_reps if not r.get("fatal")),
        "notes_compared": notes_compared,
        "notes_correct": notes_correct,
        "note_pass_rate": note_pass,
        "field_checked": field_checked,
        "field_failed": field_failed,
        "field_pass_rate": field_pass,
        "category_distribution": aggregate_category_distribution(file_reps),
        "category_pass": category_pass,
        "edge_case": edge,
        "fatal_files": [r["file"] for r in file_reps if r.get("fatal")],
    }
    # —— (C) 写出逐音符 diff 账本（omr_eval_note_diffs.json / .csv） ——
    note_diffs_path = _write_note_diffs(corpus_dir, note_ledger_all, use_oemer)
    return {
        "summary": summary,
        "per_file": file_reps,
        "flagged_for_postcorrect": flagged,
        "note_diffs_path": note_diffs_path,
    }


# ----------------------------------------------------------------------
# 报告写出 + CLI
# ----------------------------------------------------------------------

def _write_report(corpus_dir, result):
    """写出 JSON 报告并返回路径。"""
    out = os.path.join(corpus_dir, "omr_eval_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return out


def _write_note_diffs(corpus_dir, note_ledger, use_oemer):
    """写出逐音符 diff 账本 ``omr_eval_note_diffs.json``（+ 同内容 ``.csv``）。

    每条记录仅含比对所需最小字段，不泄露无关大字段：
      * ``index``：全局对齐序号（跨文件递增，对应评测比对顺序）。
      * ``expected`` / ``actual``：``{step, octave, alter}``，分别来自 gt / pred
        主音符（step=简谱音级 degree，octave=八度点 octaveDots，alter=变音记号）。
      * ``failed_categories``：该音符失败的评分类别列表（空列表=完全正确）。

    用途：人工/脚本核对**待验证 #2**——concerto 残留的 ``pitch_accidental``
    究竟是 oemer 多加了变音记号（actual.alter 非 none 而 expected.alter=none），
    还是方案A（``tools/omr_oemer.py`` 的 ``_apply_alters``）把 gt 合法的调外
    变化音（如 a 小调常见的 G#/F#）误清零成了 0（expected.alter=sharp/flat
    而 actual.alter=none）。diff 账本导出后即可按 ``failed_categories`` 含
    ``pitch_accidental`` 过滤，对照 expected/actual.alter 直接判定来源。

    Args:
        corpus_dir: 语料目录（文件写出至此）。
        note_ledger: 跨文件的逐音符 diff 列表（由 ``_eval_one`` 累积）。
        use_oemer: 是否运行了 oemer（仅用于 meta 标注）。

    Returns:
        str: 写出的 JSON 路径。
    """
    out_json = os.path.join(corpus_dir, "omr_eval_note_diffs.json")
    payload = {
        "meta": {
            "tool": "omr_eval_groundtruth",
            "mode": "oemer" if use_oemer else "no_oemer_selfcheck",
            "corpus_dir": os.path.abspath(corpus_dir),
            "notes_total": len(note_ledger),
        },
        "notes": note_ledger,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # CSV 便于快速过滤（如按 failed_categories 含 pitch_accidental 筛选）
    out_csv = os.path.join(corpus_dir, "omr_eval_note_diffs.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "index",
                    "exp_step", "exp_octave", "exp_alter",
                    "act_step", "act_octave", "act_alter",
                    "failed_categories"])
        for e in note_ledger:
            ex, ac = e["expected"], e["actual"]
            w.writerow([e["file"], e["index"],
                        ex["step"], ex["octave"], ex["alter"],
                        ac["step"], ac["octave"], ac["alter"],
                        "|".join(e["failed_categories"])])
    return out_json


def _print_summary(result):
    s = result["summary"]
    print("=" * 72)
    print("谱渡 Pudu · oemer→简谱 错误分析 harness")
    print("=" * 72)
    print(f"模式: {'oemer 识别' if s['mode'] == 'oemer' else '--no-oemr 自验'}")
    for rep in result["per_file"]:
        if rep.get("fatal"):
            print(f"  [致命] {rep['file']}: {rep['fatal']}")
            continue
        rate = (rep["notes_correct"] / rep["notes_compared"] * 100.0) \
            if rep["notes_compared"] else 0.0
        print(f"  {rep['file']}: 音符 {rep['notes_correct']}/{rep['notes_compared']} "
              f"通过 ({rate:.1f}%)")
        if rep["diffs"]:
            for d in rep["diffs"][:8]:
                loc = f"p{d['part']}m{d['measure']}#{d['index']}"
                print(f"      - {d['category']}/{d['field']} [{loc}] "
                      f"预期={d['expected']} 实际={d['actual']}")
            if len(rep["diffs"]) > 8:
                print(f"      ... 其余 {len(rep['diffs']) - 8} 条差异见报告")
    print("-" * 72)
    print(f"总计：文件 {s['files_ok']}/{s['files_total']} 成功评测；"
          f"音符通过率 {s['note_pass_rate']:.1f}% "
          f"({s['notes_correct']}/{s['notes_compared']})；"
          f"字段通过率 {s['field_pass_rate']:.1f}% "
          f"({s['field_checked'] - s['field_failed']}/{s['field_checked']})")
    print("错误类型分布（按差异数降序）：")
    if s["category_distribution"]:
        for cat, c in s["category_distribution"].items():
            flag = "" if cat in COUNTED_CATEGORIES else "  (单列/未校验)"
            print(f"    {cat}: {c}{flag}")
    else:
        print("    （无差异）")
    # —— (A) 每维度独立通过率 ——
    print("每维度独立通过率（category_pass，与联立 note_pass 互补）：")
    if s.get("category_pass"):
        for cat, rate in s["category_pass"].items():
            print(f"    {cat}: {rate:.2f}%")
    else:
        print("    （无音符比对 / 无差异）")
    e = s["edge_case"]
    print(f"边界覆盖：休止 {e['rests']} / 和弦 {e['chords']} / "
          f"装饰音 {e['graces']} / 连音组 {e['tuplets']} / 异常八度跳变 {e['octave_jumps']} 个")
    if result["flagged_for_postcorrect"]:
        print(f"后处理可关注差异：{len(result['flagged_for_postcorrect'])} 处")
    else:
        print("后处理可关注差异：无")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="oemer→简谱 错误分析 harness（评测基座 P0-1）")
    parser.add_argument("corpus_dir", help="语料目录（含 (image, gt.musicxml) 对）")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--oemr", dest="use_oemer", action="store_true",
                     help="运行 oemer 把图片识别为 pred.musicxml（默认）")
    grp.add_argument("--no-oemr", dest="use_oemer", action="store_false",
                     help="自验：直接用 gt.musicxml 当 pred，跳过 oemer")
    parser.add_argument("--f3-geometric", dest="f3_geometric", action="store_true",
                        help="透传 --f3-geometric 给 oemer 运行器（开启 F3 几何"
                             "音高校正）；也可经环境变量 PUDU_F3_GEOMETRIC=1 启用。"
                             "仅影响 oemer 识别路径，不改比对内核。")
    parser.set_defaults(use_oemer=True, f3_geometric=False)
    args = parser.parse_args(argv)

    try:
        result = eval_corpus(args.corpus_dir, args.use_oemer,
                             f3_geometric=args.f3_geometric)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 2

    _print_summary(result)
    report_path = _write_report(os.path.abspath(args.corpus_dir), result)
    print(f"报告已写出：\n  {report_path}")
    nd = result.get("note_diffs_path")
    if nd:
        print(f"逐音符 diff 账本：\n  {nd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
