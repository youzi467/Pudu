# -*- coding: utf-8 -*-
import os, json, subprocess, tempfile
from music21 import converter
from music21 import note as m21note
from music21 import chord as m21chord

ROOT = r"C:\Users\13157\WorkBuddy\omr"
BUILD = os.path.join(ROOT, "build"); EXE = os.path.join(BUILD, "Pudu.exe")
DATA = os.path.join(ROOT, "data")
FN = "solo-violin-partita-no-2-in-d-minor-j-s-bach-bwv-1004.musicxml"
PATH = os.path.join(DATA, FN)

# 转换器
fd, tmp = tempfile.mkstemp(suffix=".json"); os.close(fd)
subprocess.run([EXE, PATH, "--to-jianpu-json", tmp], cwd=BUILD, check=True)
doc = json.load(open(tmp, encoding="utf-8")); os.remove(tmp)

print("=== 转换器 JSON：每 line 的 (part,voice) 与音符数 ===")
for line in doc["lines"]:
    n = sum(len(m["notes"]) for m in line["measures"])
    print(f"  part={line['part']} voice={line['voice']} notes={n} measures={len(line['measures'])}")

# music21 per part/voice
print("\n=== music21：每 (part,voice) 音符数 ===")
s = converter.parse(PATH)
gt_total = 0
for pi, part in enumerate(s.parts):
    from collections import Counter
    c = Counter()
    for m in part.getElementsByClass("Measure"):
        for el in m.recurse():
            if not isinstance(el, (m21note.Note, m21note.Rest, m21chord.Chord)):
                continue
            vid = getattr(el, "voice", None)
            try: v = int(vid) if vid is not None else 1
            except Exception: v = 1
            c[v] += 1
    gt_total += sum(c.values())
    print(f"  PART {pi}: total={sum(c.values())} by_voice={dict(c)}")
print("  GT total =", gt_total)

# 全局 XML <note> 计数（作为基准）
import xml.etree.ElementTree as ET
tree = ET.parse(PATH); root = tree.getroot()
notes = root.findall(".//note")
chords = [n for n in notes if n.find("chord") is not None]
print(f"\n=== 原始 XML：<note> 总数={len(notes)}，其中 <chord> 后续={len(chords)}，"
      f"等效主事件={len(notes)-len(chords)} ===")
