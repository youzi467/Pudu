// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 3 反向转换（G1）：JianpuDoc -> Score
// 与阶段 2 staffToJianpu 严格互逆；不依赖 pugixml（序列化见 musicxml_serializer.cpp）。
// 复用 fifthsToTonicPc(midiToJianpu) 与 midiToPitch(transpose) 保证音名拼写口径一致。
// ----------------------------------------------------------------------

#include "jianpu_to_staff.hpp"

#include "jianpu_converter.hpp"   // fifthsToTonicPc
#include "transpose.hpp"          // midiToPitch

#include <algorithm>
#include <cmath>
#include <map>
#include <vector>

namespace pudu {

namespace {

// 大调音级 -> 相对主音的半音数（与 jianpu_converter.cpp 的 kMajorScale 严格对应）。
//   {1:0, 2:2, 3:4, 4:5, 5:7, 6:9, 7:11}
const int kDegreeSemi[8] = {0, 0, 2, 4, 5, 7, 9, 11};

// 临时记号 -> 相对主音的半音增量（midiToJianpu 的互逆方向）。
int accidentalDelta(Accidental a) {
    switch (a) {
        case Accidental::Sharp:       return 1;
        case Accidental::Flat:        return -1;
        case Accidental::DoubleSharp: return 2;
        case Accidental::DoubleFlat:  return -2;
        case Accidental::Natural:     return 0;   // 强制还原(alter=0)，与 None 在音级上等价
        default:                      return 0;   // None
    }
}

// (减时线, 增时线) -> (type, 基准 quarterLength)，与 typeToDuration 严格对称。
bool reverseRhythm(int underlines, int augmentDashes,
                   std::string& outType, double& outBaseQl) {
    if (augmentDashes == 3 && underlines == 0) { outType = "whole";  outBaseQl = 4.0;   return true; }
    if (augmentDashes == 1 && underlines == 0) { outType = "half";   outBaseQl = 2.0;   return true; }
    if (augmentDashes == 0 && underlines == 0) { outType = "quarter";outBaseQl = 1.0;   return true; }
    if (augmentDashes == 0 && underlines == 1) { outType = "eighth"; outBaseQl = 0.5;   return true; }
    if (augmentDashes == 0 && underlines == 2) { outType = "16th";   outBaseQl = 0.25;  return true; }
    if (augmentDashes == 0 && underlines == 3) { outType = "32nd";   outBaseQl = 0.125; return true; }
    if (augmentDashes == 0 && underlines == 4) { outType = "64th";   outBaseQl = 0.0625;return true; }
    outType = "quarter"; outBaseQl = 1.0; return false;   // 非法组合回退四分
}

// 附点因子：0 -> 1, 1 -> 1.5, 2+ -> 1.75（与 quarterLengthToRhythm 同口径）
double dotFactor(int dots) {
    if (dots >= 2) return 1.75;
    if (dots == 1) return 1.5;
    return 1.0;
}

// 简谱音 -> 绝对音高 Pitch（逆 midiToJianpu）。
//   M = tonicRefMidi + 12*octaveDots + (scaleSemi + accidentalDelta)，
//   其中 tonicRefMidi = tonicPc + 60，与 midiToJianpu 的 octaveDots 参考点严格互逆。
Pitch jianpuNoteToPitch(const JianpuNote& jn, int tonicPc, bool preferSharp) {
    int baseSemi = kDegreeSemi[jn.degree];
    int semi = baseSemi + accidentalDelta(jn.accidental);
    int tonicRefMidi = tonicPc + 60;
    int M = tonicRefMidi + 12 * jn.octaveDots + semi;
    return midiToPitch(M, preferSharp);
}

// 和弦成员音高：阶段 2 仅存音级(1-7)，反向只能还原音级，无法还原成员的精确八度
//   （已知限制，与阶段 2 边界项对齐）。这里取"相对根音上方最近"的八度，得到标准的
//   和弦叠置（如 C 和弦的 3/5 度落在 E4/G4 而非 E4/G3），听感与记谱更自然。
Pitch chordMemberPitch(int chordDegree, int rootDegree, int rootMidi,
                       bool preferSharp, int memberOctaveDots = 0) {
    int memberSemi = kDegreeSemi[chordDegree];
    int rootSemi = kDegreeSemi[rootDegree];
    int diff = (memberSemi - rootSemi + 12) % 12;   // 0..11，取到根音上方最近同音级
    // M1.5-A：memberOctaveDots 为成员相对根音的八度偏移(+1=高八度/-1=低八度/0=本位)
    return midiToPitch(rootMidi + diff + 12 * memberOctaveDots, preferSharp);
}

// 由简谱音构造 Note（含节奏/八度/记号/和弦），divisions 决定 duration 粒度。
Note buildNote(const JianpuNote& jn, int tonicPc, int divisions, bool preferSharp, int voice) {
    Note n;
    n.voice = voice;
    n.onset = jn.onset;
    n.isGrace = jn.isGrace;
    n.tieStart = jn.tieToNext;        // 起点：连向相邻下一音
    n.tieStop = jn.tieFromPrev;       // M1.5-B：反向还原 tie 的 stop 端（此前恒为 false，属已知限制）

    std::string type; double baseQl;
    reverseRhythm(jn.underlines, jn.augmentDashes, type, baseQl);
    double ql = baseQl * dotFactor(jn.dots);

    if (jn.degree == 0) {
        n.isRest = true;
        n.pitch.hasValue = false;
    } else {
        n.isRest = false;
        n.pitch = jianpuNoteToPitch(jn, tonicPc, preferSharp);
        int rootMidi = n.pitch.midiNumber();
        for (size_t k = 0; k < jn.chordDegrees.size(); ++k)
            n.chordPitches.push_back(chordMemberPitch(
                jn.chordDegrees[k], jn.degree, rootMidi, preferSharp,
                k < jn.chordOctaveDots.size() ? jn.chordOctaveDots[k] : 0));
    }
    n.type = type;
    n.dots = jn.dots;
    n.quarterLength = ql;
    n.duration = static_cast<long>(std::llround(ql * divisions));
    return n;
}

} // anonymous namespace

Score jianpuToStaff(const JianpuDoc& doc, int divisions) {
    Score score;
    if (doc.lines.empty()) return score;   // 空文 -> 空 Score
    score.title = doc.title;

    int tonicPc = fifthsToTonicPc(doc.fifths);
    bool preferSharp = (doc.fifths >= 0);  // 升号调用 ♯、降号调用 ♭（与变调重算一致）

    // 按 partIndex 分组（round-trip 时 partIndex 来自原 Score.parts 下标）
    std::map<int, std::vector<const JianpuLine*>> groups;
    for (const auto& line : doc.lines)
        groups[line.partIndex].push_back(&line);

    for (const auto& kv : groups) {
        int partIndex = kv.first;
        const auto& lines = kv.second;

        Part part;
        part.id = "P" + std::to_string(partIndex + 1);
        part.name = part.id;
        part.attributes.divisions = divisions;
        part.attributes.fifths = doc.fifths;
        part.attributes.mode = doc.mode;
        part.attributes.beats = doc.beats;
        part.attributes.beatType = doc.beatType;
        part.attributes.clefSign = "G";
        part.attributes.clefLine = 2;

        // 度量小节数（取本 part 内 line 的最大小节数）
        size_t mCount = 0;
        for (const auto* ln : lines)
            mCount = std::max(mCount, ln->measures.size());

        for (size_t mi = 0; mi < mCount; ++mi) {
            Measure m;
            m.number = (mi < lines[0]->measures.size())
                          ? lines[0]->measures[mi].number
                          : static_cast<int>(mi + 1);

            // 收集本小节所有 line 的音符，构造 Note
            std::vector<Note> notes;
            for (const auto* ln : lines) {
                if (mi >= ln->measures.size()) continue;
                for (const auto& jn : ln->measures[mi].notes)
                    notes.push_back(buildNote(jn, tonicPc, divisions, preferSharp, ln->voice));
            }
            // 按 (onset, voice) 排序，使序列化 backup/forward 稳定、可读
            std::sort(notes.begin(), notes.end(),
                      [](const Note& a, const Note& b) {
                          if (std::fabs(a.onset - b.onset) > 1e-9) return a.onset < b.onset;
                          return a.voice < b.voice;
                      });
            m.notes = std::move(notes);
            part.measures.push_back(m);
        }
        score.parts.push_back(part);
    }
    return score;
}

} // namespace pudu
