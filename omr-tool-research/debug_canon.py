# -*- coding: utf-8 -*-
import os, json, subprocess, tempfile
from music21 import converter

ROOT = r"C:\Users\13157\WorkBuddy\omr"
BUILD = os.path.join(ROOT, "build")
EXE = os.path.join(BUILD, "Pudu.exe")
DATA = os.path.join(ROOT, "data")
FN = "canon-in-d-violin-solo.musicxml"
PATH = os.path.join(DATA, FN)

# --- 转换器 JSON ---
fd, tmp = tempfile.mkstemp(suffix=".json")
os.close(fd)
subprocess.run([EXE, PATH, "--to-jianpu-json", tmp], cwd=BUILD, check=True)
doc = json.load(open(tmp, encoding="utf-8"))
os.remove(tmp)

print("=== 转换器 JSON：各 line 的 (part, voice) 与每小节首音 ===")
for line in doc["lines"]:
    print(f"  line part={line['part']} voice={line['voice']} measures={len(line['measures'])}")
    for m in line["measures"][:6]:
        degs = [n["degree"] for n in m["notes"]]
        print(f"    m{m['number']}: {degs}")

print("\n=== music21：每个 part 的前 6 个事件 ===")
s = converter.parse(PATH)
for pi, part in enumerate(s.parts):
    print(f"  PART {pi} (nParts={len(s.parts)})")
    cnt = 0
    for m in part.getElementsByClass("Measure"):
        for el in m.recurse().notes:
            vid = getattr(el, "voice", None)
            try:
                v = int(vid) if vid is not None else 1
            except Exception:
                v = 1
            if el.isRest:
                desc = f"REST ql={el.quarterLength}"
            elif el.isChord:
                desc = "CHORD " + "/".join(str(p) for p in el.pitches)
            else:
                try:
                    t = el.duration.type
                except Exception:
                    t = "?"
                desc = f"{el.pitch} ql={el.quarterLength} type={t}"
            print(f"    p{pi}v{v}m{m.number} {desc}")
            cnt += 1
            if cnt >= 6:
                break
        if cnt >= 6:
            break
