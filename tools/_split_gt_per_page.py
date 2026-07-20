#!/usr/bin/env python3
# 非破坏式：把整曲 gt (240 小节) 按 oemer 各页检测的小节数切成每页 gt。
# 关键修正：原曲 <divisions>/<key>/<time>/<clef> 仅在 measure 1 声明，切到 p2..p6
# 时这些页缺失 <attributes> -> Pudu 无法算时长 -> onset 算飞 -> 评测对齐崩。
# 故把 measure 1 的 <attributes> 作为"参考属性"注入每页首小节，使每页自包含。
import xml.etree.ElementTree as ET, os, shutil, copy

D = r"C:\Users\13157\WorkBuddy\omr\data\omr_eval\real\concerto_pages"
BAK = os.path.join(D, "_backup_full_gt")
SRC = os.path.join(BAK, "concerto-in-a-minor-a-vivaldi_p1.gt.full.musicxml")  # 6 份相同，取备份其一
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'
DOCTYPE = '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">'

# oemer 各页检测小节数（p1..p5 用此，p6 吸收余量）
per_page = [28, 24, 24, 40, 50]

def main():
    # 1) 首次运行才备份 6 份整曲 gt（非破坏）
    os.makedirs(BAK, exist_ok=True)
    for pg in ["p1","p2","p3","p4","p5","p6"]:
        src = os.path.join(D, f"concerto-in-a-minor-a-vivaldi_{pg}.gt.musicxml")
        dst = os.path.join(BAK, f"concerto-in-a-minor-a-vivaldi_{pg}.gt.full.musicxml")
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            print(f"  备份 {pg}.gt.musicxml -> _backup_full_gt/")
    if not os.path.exists(SRC):
        print("[错误] 备份源不存在，无法切分。请确认 _backup_full_gt/ 完好。")
        return

    # 2) 解析整曲
    tree = ET.parse(SRC); root = tree.getroot()
    parts = list(root.iter("part"))
    assert len(parts) == 1, f"预期 1 part, 实际 {len(parts)}"
    part = parts[0]
    measures = [c for c in list(part) if c.tag == "measure"]
    total = len(measures)
    print(f"整曲: parts={len(parts)} measures={total}")

    # 取 measure 1 的 <attributes> 作为参考属性（含 divisions/time/key/clef）
    ref_attrs = None
    for m in measures:
        a = m.find("attributes")
        if a is not None:
            ref_attrs = copy.deepcopy(a)
            break
    assert ref_attrs is not None, "整曲 measure 1 无 <attributes>，无法提取 divisions"
    div = ref_attrs.find("divisions")
    print(f"参考属性已提取: divisions={div.text if div is not None else '?'}"
          f" 含key={ref_attrs.find('key') is not None}"
          f" 含time={ref_attrs.find('time') is not None}"
          f" 含clef={ref_attrs.find('clef') is not None}")

    # 3) 计算每页小节范围（p6 吸收余量）
    ranges = []
    s = 0
    for c in per_page:
        ranges.append((s, s + c)); s += c
    ranges.append((s, total))  # p6 余下全部
    print("每页小节范围:", ranges, " 合计:", sum(e-s for s,e in ranges))

    # 4) 表头元素（part 之前的所有子节点，如 part-list）
    header = [copy.deepcopy(c) for c in list(root) if c.tag != "part"]
    part_id = part.get("id")

    # 5) 逐页生成（每页首小节注入参考属性 -> 自包含）
    for i, (s, e) in enumerate(ranges, 1):
        pg = f"p{i}"
        chunk = measures[s:e]
        new_root = ET.Element("score-partwise", {"version": root.get("version", "3.1")})
        for h in header:
            new_root.append(copy.deepcopy(h))
        new_part = ET.SubElement(new_root, "part", {"id": part_id})
        for mi, m in enumerate(chunk):
            m2 = copy.deepcopy(m)
            if mi == 0:
                # 仅当首小节尚无 divisions 时才注入（避免重复，但保证存在）
                first_attrs = m2.find("attributes")
                need_inject = (first_attrs is None) or (first_attrs.find("divisions") is None)
                if need_inject:
                    # 放到首小节最前（在 print/direction/note 之前），Pudu 读首个 divisions
                    ref = copy.deepcopy(ref_attrs)
                    m2.insert(0, ref)
            new_part.append(m2)
        body = ET.tostring(new_root, encoding="unicode")
        out = os.path.join(D, f"concerto-in-a-minor-a-vivaldi_{pg}.gt.musicxml")
        with open(out, "w", encoding="utf-8") as f:
            f.write(XML_DECL + "\n" + DOCTYPE + "\n" + body + "\n")
        # 校验
        t2 = ET.parse(out); rp = list(t2.getroot().iter("part"))[0]
        nm = sum(1 for c in list(rp) if c.tag == "measure")
        nn = sum(1 for n in rp.iter("note") if n.find("rest") is None and n.find("pitch") is not None)
        has_div = any(m2.find("attributes") is not None and m2.find("attributes").find("divisions") is not None
                     for m2 in rp.iter("measure"))
        print(f"  {pg}.gt.musicxml: measures={nm} (期望 {e-s}) notes={nn} divisions存在={has_div}")

    print("切分完成（已注入参考属性，每页自包含）。")

if __name__ == "__main__":
    main()
