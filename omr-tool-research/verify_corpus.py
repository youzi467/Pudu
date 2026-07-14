# -*- coding: utf-8 -*-
"""
谱渡 Pudu · 样例谱批量核对脚本
------------------------------------------------------------
对 data/ 下每个 .musicxml：
  1) 运行 Pudu.exe 捕获输出
  2) 用源 XML 计算"预期值"（严格对齐 parser 的实现语义）
  3) 逐项比对，输出 PASS/FAIL
比对项（每声部）：标题 / 声部数 / 调号 / 拍号 / divisions / 谱号 /
                小节数 / 音符事件总数(含休止) / 休止符数 / 首音
另附结构诊断：多谱号(多 staff)、和弦音数、grace 音数、backup 数。
"""
import os, re, sys, subprocess
import xml.etree.ElementTree as ET

BUILD = r"C:\Users\13157\WorkBuddy\omr\build"
EXE   = os.path.join(BUILD, "Pudu.exe")
DATA  = r"C:\Users\13157\WorkBuddy\omr\data"

# ---- 复刻 main.cpp 的 keyName，保证预期字符串与程序输出一致 ----
def key_name(fifths, mode):
    majorPos = ["C","G","D","A","E","B","F#","C#"]
    majorNeg = ["C","F","Bb","Eb","Ab","Db","Gb","Cb"]
    minorPos = ["a","e","b","f#","c#","g#","d#","a#"]
    minorNeg = ["a","d","g","c","f","bb","eb","ab"]
    if mode == "minor":
        table = minorPos if fifths >= 0 else minorNeg
    else:
        table = majorPos if fifths >= 0 else majorNeg
    idx = fifths if fifths >= 0 else -fifths
    if idx > 7: idx = 7
    return table[idx] + (" 小调" if mode == "minor" else " 大调")

def pitch_label(step, alter, octave):
    s = step
    if alter == 1: s += "#"
    elif alter == -1: s += "b"
    return s + str(octave)

# ---- 解析源 XML，得到预期 ----
def expected_from_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "score-partwise":
        return {"root_ok": False, "root_tag": root.tag}
    exp = {"root_ok": True, "parts": []}
    # 标题：movement-title 优先，否则 work/work-title，否则回退 <credit> 顶层行
    title = ""
    mt = root.find("movement-title")
    if mt is not None and mt.text:
        title = mt.text
    else:
        w = root.find("work")
        if w is not None:
            wt = w.find("work-title")
            if wt is not None and wt.text:
                title = wt.text
    if not title:
        credits = []
        for cw in root.findall(".//credit-words"):
            t = (cw.text or "").strip()
            if not t:
                continue
            dy = cw.find("default-y")
            yy = int(dy.text) if dy is not None and dy.text else 0
            credits.append((yy, t))
        if credits:
            # 对齐 parser：default-y 最大者优先，否则第一条
            credits.sort(key=lambda x: -x[0])
            title = credits[0][1]
    exp["title"] = title if title else "(无)"

    # 源 credit 有效行数（对齐 parser：仅保留非空行）
    src_credits = 0
    for cw in root.findall(".//credit-words"):
        if (cw.text or "").strip():
            src_credits += 1
    exp["src_credits"] = src_credits

    # part-list 名称映射
    names = {}
    pl = root.find("part-list")
    if pl is not None:
        for sp in pl.findall("score-part"):
            pid = sp.get("id","")
            pn = sp.find("part-name")
            names[pid] = (pn.text if pn is not None and pn.text else "")

    for part in root.findall("part"):
        pid = part.get("id","")
        p = {"id": pid, "name": names.get(pid,"")}
        # 首个 attributes（对齐 parser：全声部第一次遇到的 attributes）
        divisions, fifths, mode = 1, 0, "major"
        beats, beat_type = 4, 4
        clef_sign, clef_line = "G", 2
        seen_attr = False
        # 结构诊断
        note_events = 0    # 所有 <note>
        rests = 0
        chords = 0         # 含 <chord/> 的 note
        graces = 0         # 含 <grace/> 的 note
        backups = 0
        n_measures = 0
        clef_count_first_attr = 0
        first_note_label = None

        for m in part.findall("measure"):
            n_measures += 1
            for child in list(m):
                tag = child.tag
                if tag == "attributes" and not seen_attr:
                    d = child.find("divisions")
                    if d is not None and d.text: divisions = int(d.text)
                    k = child.find("key")
                    if k is not None:
                        f = k.find("fifths")
                        if f is not None and f.text: fifths = int(f.text)
                        mo = k.find("mode")
                        if mo is not None and mo.text: mode = mo.text
                    t = child.find("time")
                    if t is not None:
                        b = t.find("beats")
                        if b is not None and b.text: beats = int(b.text)
                        bt = t.find("beat-type")
                        if bt is not None and bt.text: beat_type = int(bt.text)
                    c = child.find("clef")  # 只取第一个 clef（对齐 parser）
                    if c is not None:
                        s = c.find("sign")
                        if s is not None and s.text: clef_sign = s.text
                        ln = c.find("line")
                        if ln is not None and ln.text: clef_line = int(ln.text)
                    clef_count_first_attr = len(child.findall("clef"))
                    seen_attr = True
                elif tag == "attributes":
                    pass
                elif tag == "note":
                    note_events += 1
                    is_rest = child.find("rest") is not None
                    if is_rest: rests += 1
                    if child.find("chord") is not None: chords += 1
                    if child.find("grace") is not None: graces += 1
                    if first_note_label is None:
                        if is_rest:
                            first_note_label = "休止(全小节)"
                        else:
                            pit = child.find("pitch")
                            if pit is not None:
                                st = pit.find("step")
                                al = pit.find("alter")
                                oc = pit.find("octave")
                                step = st.text if st is not None and st.text else "C"
                                alter = int(al.text) if al is not None and al.text else 0
                                octave = int(oc.text) if oc is not None and oc.text else 4
                                first_note_label = pitch_label(step, alter, octave)
                            else:
                                first_note_label = "C4"  # 无 pitch 无 rest 的退化
                elif tag == "backup":
                    backups += 1
        # 解析器把 <chord/> 后续音并入首个音的 chordPitches，不再单独成事件，
        # 因此"程序输出事件数"= 源 <note> 数 - chord 后续音数（chords 即后续音数）
        note_events_expected = note_events - chords
        p.update({
            "divisions": divisions, "fifths": fifths, "mode": mode,
            "beats": beats, "beat_type": beat_type,
            "clef_sign": clef_sign, "clef_line": clef_line,
            "key_name": key_name(fifths, mode),
            "clef_str": f"{clef_sign}{clef_line}",
            "n_measures": n_measures,
            "note_events": note_events, "rests": rests,
            "chords": chords, "graces": graces, "backups": backups,
            "clef_count_first_attr": clef_count_first_attr,
            "first_note": first_note_label if first_note_label else "(无)",
            "note_events_expected": note_events_expected,
        })
        exp["parts"].append(p)
    return exp

# ---- 解析 Pudu.exe 的实际输出 ----
def actual_from_output(text):
    act = {"parts": []}
    m = re.search(r"标题:\s*(.*)", text)
    act["title"] = m.group(1).strip() if m else None
    m = re.search(r"抬头行数\(credit\):\s*(\d+)", text)
    act["credits"] = int(m.group(1)) if m else None
    m = re.search(r"声部数:\s*(\d+)", text)
    act["parts_count"] = int(m.group(1)) if m else None
    act["load_failed"] = ("文件加载失败" in text) or ("内嵌样例" in text)
    act["assert_failed"] = "断言失败" in text

    # 按声部切块
    lines = text.splitlines()
    cur = None
    for ln in lines:
        hm = re.match(r"声部\[(.*?)\]\s*(.*?):\s*(.+?),\s*拍号\s*(\d+)/(\d+),\s*divisions=(\d+),\s*谱号\s*(\S+)", ln)
        if hm:
            if cur is not None: act["parts"].append(cur)
            cur = {
                "id": hm.group(1), "name": hm.group(2),
                "key_name": hm.group(3).strip(),
                "beats": int(hm.group(4)), "beat_type": int(hm.group(5)),
                "divisions": int(hm.group(6)), "clef_str": hm.group(7),
                "n_measures": None, "note_events": 0, "rests": 0,
                "first_note": None,
            }
            continue
        mm = re.match(r"\s*小节数:\s*(\d+)", ln)
        if mm and cur is not None:
            cur["n_measures"] = int(mm.group(1)); continue
        me = re.match(r"\s*小节\s*(\d+):(.*)", ln)
        if me and cur is not None:
            toks = me.group(2).split()
            for t in toks:
                cur["note_events"] += 1
                if t == "0":
                    cur["rests"] += 1
                    if cur["first_note"] is None: cur["first_note"] = "休止(全小节)"
                else:
                    if cur["first_note"] is None:
                        cur["first_note"] = t.split("/")[0]
    if cur is not None: act["parts"].append(cur)
    return act

def cmp_item(results, name, exp, act):
    ok = (exp == act)
    results.append((name, ok, exp, act))
    return ok

def main():
    files = sorted([f for f in os.listdir(DATA) if f.endswith(".musicxml")])
    all_reports = []
    for fn in files:
        path = os.path.join(DATA, fn)
        try:
            proc = subprocess.run([EXE, path], cwd=BUILD, capture_output=True, timeout=60)
            out = proc.stdout.decode("utf-8", "replace")
            err = proc.stderr.decode("utf-8", "replace")
            rc = proc.returncode
        except Exception as e:
            all_reports.append({"file": fn, "fatal": f"运行异常: {e}"})
            continue
        exp = expected_from_xml(path)
        act = actual_from_output(out)
        rep = {"file": fn, "rc": rc, "stderr": err.strip(),
               "exp": exp, "act": act, "checks": [], "diag": []}
        results = rep["checks"]
        # 标题
        cmp_item(results, "标题", exp.get("title"), act.get("title"))
        # credit 抬头行数（有效行）
        cmp_item(results, "抬头行数(credit)", exp.get("src_credits", 0), act.get("credits"))
        # 声部数
        cmp_item(results, "声部数", len(exp.get("parts", [])), act.get("parts_count"))
        # 逐声部
        ep = exp.get("parts", [])
        ap = act.get("parts", [])
        for i, e in enumerate(ep):
            a = ap[i] if i < len(ap) else {}
            pre = f"P#{i+1}({e['id']})"
            cmp_item(results, f"{pre} 调号", e["key_name"], a.get("key_name"))
            cmp_item(results, f"{pre} 拍号", f"{e['beats']}/{e['beat_type']}",
                     f"{a.get('beats')}/{a.get('beat_type')}")
            cmp_item(results, f"{pre} divisions", e["divisions"], a.get("divisions"))
            cmp_item(results, f"{pre} 谱号", e["clef_str"], a.get("clef_str"))
            cmp_item(results, f"{pre} 小节数", e["n_measures"], a.get("n_measures"))
            cmp_item(results, f"{pre} 音符事件总数", e["note_events_expected"], a.get("note_events"))
            cmp_item(results, f"{pre} 休止符数", e["rests"], a.get("rests"))
            cmp_item(results, f"{pre} 首音", e["first_note"], a.get("first_note"))
            # 结构诊断（非 pass/fail，仅提示语义局限）
            if e["chords"] > 0:
                rep["diag"].append(f"{pre} 源含 {e['chords']} 个和弦音(<chord/>)→被拍平为顺序音符")
            if e["graces"] > 0:
                rep["diag"].append(f"{pre} 源含 {e['graces']} 个装饰音(<grace/>)→无时值，计入事件数")
            if e["backups"] > 0:
                rep["diag"].append(f"{pre} 源含 {e['backups']} 个 <backup>(多声部/多层)→被跳过，音符顺序堆叠")
            if e["clef_count_first_attr"] > 1:
                rep["diag"].append(f"{pre} 源首个 attributes 有 {e['clef_count_first_attr']} 个谱号(多 staff)→仅取第一个")
        all_reports.append(rep)

    # ---- 打印汇总 ----
    total_pass = total_fail = 0
    for rep in all_reports:
        print("="*70)
        print("文件:", rep["file"], "| 退出码:", rep.get("rc"))
        if rep.get("fatal"):
            print("  致命:", rep["fatal"]); continue
        if rep.get("stderr"):
            print("  stderr:", rep["stderr"])
        npass = sum(1 for c in rep["checks"] if c[1])
        nfail = len(rep["checks"]) - npass
        total_pass += npass; total_fail += nfail
        for name, ok, e, a in rep["checks"]:
            mark = "PASS" if ok else "FAIL"
            if ok:
                print(f"  [{mark}] {name}: {e}")
            else:
                print(f"  [{mark}] {name}: 预期={e!r} 实际={a!r}")
        for d in rep["diag"]:
            print("  [诊断]", d)
        print(f"  小计: PASS {npass} / FAIL {nfail}")
    print("="*70)
    print(f"总计: PASS {total_pass} / FAIL {total_fail} / 文件数 {len(all_reports)}")

if __name__ == "__main__":
    main()
