// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 3 反向转换单测（G1 jianpuToStaff + G3 round-trip 音高守恒）
// 本文件仅依赖内存模型（不引用 pugixml），可在 g++ / MSVC 下编译运行。
// G2(scoreToMusicXML 序列化) 的自洽测试见 test_serializer.cpp（需 pugixml，仅 MSVC 构建）。
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_to_staff.hpp"
#include "jianpu_converter.hpp"   // staffToJianpu
#include "score_model.hpp"
#include "jianpu_model.hpp"
#include "test_helpers.hpp"

#include <vector>

using namespace pudu;

namespace {

// 构造单声部单小节简谱文档（onset 依次排开）
JianpuDoc mkDoc(int fifths, const std::string& mode,
                const std::vector<JianpuNote>& notes) {
    JianpuDoc doc;
    doc.fifths = fifths;
    doc.mode = mode;
    doc.beats = 4;
    doc.beatType = 4;
    doc.tonicLabel = "1=X";
    doc.title = "t";
    JianpuLine line; line.voice = 1; line.partIndex = 0;
    JianpuMeasure m; m.number = 1;
    double o = 0.0;
    for (JianpuNote n : notes) { n.onset = o; m.notes.push_back(n); o += 1.0; }
    line.measures.push_back(m);
    doc.lines.push_back(line);
    return doc;
}

JianpuNote mkJn(int degree, int octaveDots = 0,
                Accidental acc = Accidental::None,
                int underlines = 0, int augmentDashes = 0, int dots = 0) {
    JianpuNote n;
    n.degree = degree;
    n.octaveDots = octaveDots;
    n.accidental = acc;
    n.underlines = underlines;
    n.augmentDashes = augmentDashes;
    n.dots = dots;
    return n;
}

} // namespace

// ===== G1：音级 -> 绝对音高（逆 midiToJianpu） =====

TEST(jianpu_to_staff_degree_to_pitch_C) {
    // C 大调（fifths=0）：1=C4 3=E4 5=G4
    JianpuDoc doc = mkDoc(0, "major", { mkJn(1), mkJn(3), mkJn(5) });
    Score s = jianpuToStaff(doc);
    EXPECT_EQ(s.parts.size(), 1);
    EXPECT_EQ(s.parts[0].measures[0].notes.size(), 3);
    const auto& notes = s.parts[0].measures[0].notes;
    EXPECT_EQ(notes[0].pitch.step, 'C'); EXPECT_EQ(notes[0].pitch.octave, 4); EXPECT_EQ(notes[0].pitch.alter, 0);
    EXPECT_EQ(notes[1].pitch.step, 'E'); EXPECT_EQ(notes[1].pitch.octave, 4);
    EXPECT_EQ(notes[2].pitch.step, 'G'); EXPECT_EQ(notes[2].pitch.octave, 4);
}

TEST(jianpu_to_staff_degree_to_pitch_G) {
    // G 大调（fifths=1）：1=G4 4=C5 7=F#5（preferSharp -> ♯）
    JianpuDoc doc = mkDoc(1, "major", { mkJn(1), mkJn(4), mkJn(7) });
    Score s = jianpuToStaff(doc);
    const auto& notes = s.parts[0].measures[0].notes;
    EXPECT_EQ(notes[0].pitch.step, 'G'); EXPECT_EQ(notes[0].pitch.octave, 4);
    EXPECT_EQ(notes[1].pitch.step, 'C'); EXPECT_EQ(notes[1].pitch.octave, 5);
    EXPECT_EQ(notes[2].pitch.step, 'F'); EXPECT_EQ(notes[2].pitch.alter, 1); EXPECT_EQ(notes[2].pitch.octave, 5);
}

TEST(jianpu_to_staff_octave_dots) {
    // 八度点：+1 -> C5, -1 -> C3（C 大调，degree 1）
    JianpuDoc doc = mkDoc(0, "major", { mkJn(1, 1), mkJn(1, -1) });
    Score s = jianpuToStaff(doc);
    const auto& notes = s.parts[0].measures[0].notes;
    EXPECT_EQ(notes[0].pitch.octave, 5);
    EXPECT_EQ(notes[1].pitch.octave, 3);
}

TEST(jianpu_to_staff_accidental_flat_in_C) {
    // C 大调下降 7 度：degree 7 + Flat -> Bb 经 preferSharp 拼写为 A#4
    JianpuDoc doc = mkDoc(0, "major", { mkJn(7, 0, Accidental::Flat) });
    Score s = jianpuToStaff(doc);
    const auto& n = s.parts[0].measures[0].notes[0];
    EXPECT_EQ(n.pitch.step, 'A'); EXPECT_EQ(n.pitch.alter, 1); EXPECT_EQ(n.pitch.octave, 4);
}

// ===== G1：时值 -> type + duration =====

TEST(jianpu_to_staff_rhythm) {
    JianpuDoc doc = mkDoc(0, "major", {
        mkJn(1, 0, Accidental::None, 0, 0, 0),   // quarter
        mkJn(1, 0, Accidental::None, 0, 1, 0),   // half
        mkJn(1, 0, Accidental::None, 0, 3, 0),   // whole
        mkJn(1, 0, Accidental::None, 1, 0, 0),   // eighth
        mkJn(1, 0, Accidental::None, 0, 0, 1),   // dotted quarter
    });
    Score s = jianpuToStaff(doc, 4);   // divisions=4
    const auto& notes = s.parts[0].measures[0].notes;
    EXPECT_EQ(notes[0].type, "quarter"); EXPECT_EQ(notes[0].duration, 4);  EXPECT_EQ(notes[0].dots, 0);
    EXPECT_EQ(notes[1].type, "half");    EXPECT_EQ(notes[1].duration, 8);
    EXPECT_EQ(notes[2].type, "whole");   EXPECT_EQ(notes[2].duration, 16);
    EXPECT_EQ(notes[3].type, "eighth");  EXPECT_EQ(notes[3].duration, 2);
    EXPECT_EQ(notes[4].type, "quarter"); EXPECT_EQ(notes[4].duration, 6); EXPECT_EQ(notes[4].dots, 1);
}

// ===== G1：休止 / 和弦 / 多声部 =====

TEST(jianpu_to_staff_rest) {
    JianpuDoc doc = mkDoc(0, "major", { mkJn(0), mkJn(1) });
    Score s = jianpuToStaff(doc);
    EXPECT_TRUE(s.parts[0].measures[0].notes[0].isRest);
    EXPECT_FALSE(s.parts[0].measures[0].notes[1].isRest);
}

TEST(jianpu_to_staff_chord_pitchclass) {
    // degree 1 + 和弦 [3,5]：根音 C4，和弦音取最近邻 -> E4 / G4（pitch class 守恒）
    JianpuDoc doc = mkDoc(0, "major", { mkJn(1, 0, Accidental::None, 0, 0, 0) });
    doc.lines[0].measures[0].notes[0].chordDegrees = {3, 5};
    Score s = jianpuToStaff(doc);
    const auto& n = s.parts[0].measures[0].notes[0];
    EXPECT_EQ(n.chordPitches.size(), 2);
    EXPECT_EQ(n.chordPitches[0].step, 'E'); EXPECT_EQ(n.chordPitches[0].octave, 4);
    EXPECT_EQ(n.chordPitches[1].step, 'G'); EXPECT_EQ(n.chordPitches[1].octave, 4);
}

TEST(jianpu_to_staff_multivoice_single_part) {
    // 两个 voice 落在同一 partIndex -> 单 Part，两 voice
    JianpuDoc doc;
    doc.fifths = 0; doc.mode = "major"; doc.beats = 4; doc.beatType = 4;
    doc.title = "t";
    for (int v : {1, 2}) {
        JianpuLine line; line.voice = v; line.partIndex = 0;
        JianpuMeasure m; m.number = 1;
        JianpuNote jn = mkJn(1); jn.onset = 0;
        m.notes.push_back(jn);
        line.measures.push_back(m);
        doc.lines.push_back(line);
    }
    Score s = jianpuToStaff(doc);
    EXPECT_EQ(s.parts.size(), 1);
    EXPECT_EQ(s.parts[0].measures[0].notes.size(), 2);
    int v1 = 0, v2 = 0;
    for (const auto& n : s.parts[0].measures[0].notes)
        if (n.voice == 1) ++v1; else if (n.voice == 2) ++v2;
    EXPECT_EQ(v1, 1); EXPECT_EQ(v2, 1);
}

// ===== G3：Round-trip 音高守恒（五线 -> 简 -> 五线） =====

TEST(jianpu_to_staff_roundtrip_pitch_conservation) {
    // 构造单声部 C 大调旋律，跑 staffToJianpu -> jianpuToStaff，
    // 还原音高序列(step/alter/octave) 应与原谱一致（验收标准核心）。
    Measure m1, m2;
    m1.number = 1; m2.number = 2;
    m1.notes = { mkNote(mkPitch('C', 0, 4), "quarter", 0),
                 mkNote(mkPitch('D', 0, 4), "quarter", 1),
                 mkNote(mkPitch('E', 0, 4), "half",   2) };
    m2.notes = { mkNote(mkPitch('G', 0, 4), "eighth", 0),
                 mkNote(mkPitch('A', 0, 4), "eighth", 1),
                 mkNote(mkPitch('B', 0, 4), "quarter", 2) };
    Score orig = mkScore(0, "major", 4, 4, {m1, m2}, "roundtrip");

    JianpuDoc doc = staffToJianpu(orig);
    Score back = jianpuToStaff(doc);

    EXPECT_EQ(back.parts.size(), orig.parts.size());
    // 展平两谱的音高序列（按全局 onset 顺序），逐音比对 step/alter/octave
    auto flatten = [](const Score& sc, std::vector<Pitch>& out) {
        // 按 part/onset 收集所有实音
        for (const auto& part : sc.parts)
            for (const auto& m : part.measures)
                for (const auto& n : m.notes)
                    if (!n.isRest) out.push_back(n.pitch);
    };
    std::vector<Pitch> a, b;
    flatten(orig, a); flatten(back, b);
    EXPECT_EQ(a.size(), b.size());
    for (size_t i = 0; i < a.size() && i < b.size(); ++i) {
        EXPECT_EQ(a[i].step,   b[i].step);
        EXPECT_EQ(a[i].alter,  b[i].alter);
        EXPECT_EQ(a[i].octave, b[i].octave);
    }
}
