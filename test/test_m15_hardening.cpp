// ----------------------------------------------------------------------
// 谱渡 Pudu · M1.5「边界硬化」针对性回归测试（QA 严过关）
//
// 覆盖三子项（均用内存构造 JianpuDoc/Score，或解析 MusicXML 字符串，
// 不依赖外部样本文件）：
//   A 和弦逐音八度点：文本→模型闭环、L1 渲染逐音不整组套用、
//                     内存 Score 与序列化双粒度往返守恒、JSON 透出。
//   B tieStop 反向：staffToJianpu 据 tieStop 写 tieFromPrev、
//                   jianpuToStaff 据 tieFromPrev 设 tieStop、
//                   含 continue 链 start→continue→stop 的往返守恒。
//   C 极端连音比容错：7:8/7:4/9:4 不崩溃、rhythmUnresolvable 标记、
//                     不污染相邻常规音符、JSON 透出、序列化往返仍标记。
//
// 编译说明：renderJianpuNote 位于 jianpu_converter.cpp 的匿名命名空间
//   （未导出），故 A 的渲染断言统一经由 jianpuToL1（其内部调用
//   renderJianpuNote）完成，等价于直接验证其输出。
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"   // staffToJianpu / jianpuToL1 / jianpuToJson
#include "jianpu_to_staff.hpp"    // jianpuToStaff / scoreToMusicXML
#include "jianpu_text_parser.hpp" // parseJianpuText
#include "jianpu_model.hpp"
#include "score_model.hpp"
#include "musicxml_parser.hpp"
#include "test_helpers.hpp"

#include <cmath>
#include <string>
#include <vector>

using namespace pudu;

namespace {

// 构造一个和弦根音（degree + 根音 octaveDots + 逐音 chordDegrees/chordOctaveDots）
JianpuNote mkChordRoot(int degree, int octaveDots,
                       const std::vector<int>& chordDegrees,
                       const std::vector<int>& chordOctaveDots) {
    JianpuNote n;
    n.degree = degree;
    n.octaveDots = octaveDots;
    n.underlines = 0; n.augmentDashes = 0; n.dots = 0;
    n.chordDegrees = chordDegrees;
    n.chordOctaveDots = chordOctaveDots;
    return n;
}

// 单声部单小节简谱文档（一个和弦音，onset=0）
JianpuDoc mkChordDoc(int fifths, const std::string& mode,
                     const JianpuNote& note) {
    JianpuDoc doc;
    doc.fifths = fifths;
    doc.mode = mode;
    doc.beats = 4;
    doc.beatType = 4;
    doc.tonicLabel = "1=X";
    doc.title = "t";
    JianpuLine line; line.voice = 1; line.partIndex = 0;
    JianpuMeasure m; m.number = 1; m.notes.push_back(note);
    line.measures.push_back(m);
    doc.lines.push_back(line);
    return doc;
}

// 单简谱音构造（沿用 test_jianpu_to_staff.cpp 的 mkJn 语义）
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

// 取第一声部第一小节音符列表
std::vector<JianpuNote>& firstMeasure(JianpuDoc& doc) {
    return doc.lines[0].measures[0].notes;
}

} // namespace

// ===================== A 和弦逐音八度点 =====================

// A 文本→模型闭环：[1' 3,] → degree=1, octaveDots=1, chordDegrees=[3], chordOctaveDots=[-1]
TEST(m15_A_text_parse_chord_pervoice_octave) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: [1' 3,]", out, err));
    auto& n = firstMeasure(out)[0];
    EXPECT_EQ(n.degree, 1);
    EXPECT_EQ(n.octaveDots, 1);                 // 根音 '（相对主音参考八度）
    EXPECT_EQ(n.chordDegrees.size(), 1u);
    EXPECT_EQ(n.chordDegrees[0], 3);
    EXPECT_EQ(n.chordOctaveDots.size(), 1u);
    EXPECT_EQ(n.chordOctaveDots[0], -1);        // 成员 3 相对根音降八度
}

// A 渲染：逐音八度点紧邻各自数字，不得套在整组和弦括号之后
TEST(m15_A_render_l1_pervoice_dots_not_whole_group) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: [1' 3,]", out, err));
    std::string l1 = jianpuToL1(out);
    EXPECT_TRUE(l1.find("[1' 3,]") != std::string::npos);   // 根音'贴1，成员,贴3

    // 反向对照：[1 3'] → 根音无点、成员3带'；回归缺陷会渲染成 "[1 3]'"
    JianpuDoc out2; std::string err2;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: [1 3']", out2, err2));
    std::string l1b = jianpuToL1(out2);
    EXPECT_TRUE(l1b.find("[1 3']") != std::string::npos);
    EXPECT_TRUE(l1b.find("[1 3]'") == std::string::npos);    // 不得整组套用
}

// A 渲染：内存构造的模型也经由 renderJianpuNote 逐音渲染（[1' 3, 5']）
TEST(m15_A_render_from_model_pervoice_dots) {
    JianpuDoc doc = mkChordDoc(0, "major", mkChordRoot(1, 1, {3, 5}, {-1, 1}));
    std::string l1 = jianpuToL1(doc);
    EXPECT_TRUE(l1.find("[1' 3, 5']") != std::string::npos);
}

// A 往返（内存 Score）：JianpuDoc → jianpuToStaff → staffToJianpu，chordOctaveDots 逐项守恒
TEST(m15_A_roundtrip_memory_chordOctaveDots_conserved) {
    JianpuDoc doc = mkChordDoc(0, "major", mkChordRoot(1, 1, {3}, {-1}));
    Score sc = jianpuToStaff(doc, 4);
    JianpuDoc back = staffToJianpu(sc);
    auto& n = firstMeasure(back)[0];
    EXPECT_EQ(n.degree, 1);
    EXPECT_EQ(n.chordDegrees.size(), 1u);
    EXPECT_EQ(n.chordDegrees[0], 3);
    EXPECT_EQ(n.chordOctaveDots.size(), 1u);
    EXPECT_EQ(n.chordOctaveDots[0], -1);
}

// A 往返（序列化）：JianpuDoc → jianpuToStaff → scoreToMusicXML → 重解析 → staffToJianpu
TEST(m15_A_roundtrip_serialized_chordOctaveDots_conserved) {
    JianpuDoc doc = mkChordDoc(0, "major", mkChordRoot(1, 1, {3}, {-1}));
    Score sc = jianpuToStaff(doc, 4);
    std::string xml = scoreToMusicXML(sc);
    MusicXMLParser parser; Score back; std::string perr;
    EXPECT_TRUE(parser.parseString(xml, back, perr));
    JianpuDoc doc2 = staffToJianpu(back);
    auto& n = firstMeasure(doc2)[0];
    EXPECT_EQ(n.chordDegrees.size(), 1u);
    EXPECT_EQ(n.chordDegrees[0], 3);
    EXPECT_EQ(n.chordOctaveDots.size(), 1u);
    EXPECT_EQ(n.chordOctaveDots[0], -1);
}

// A 三成员互异八度点：序列化往返逐项守恒 [1' 3, 5'] → chordOctaveDots=[-1,1]
TEST(m15_A_three_member_distinct_dots_conserved) {
    JianpuDoc doc = mkChordDoc(0, "major", mkChordRoot(1, 1, {3, 5}, {-1, 1}));
    Score sc = jianpuToStaff(doc, 4);
    std::string xml = scoreToMusicXML(sc);
    MusicXMLParser parser; Score back; std::string perr;
    EXPECT_TRUE(parser.parseString(xml, back, perr));
    JianpuDoc doc2 = staffToJianpu(back);
    auto& n = firstMeasure(doc2)[0];
    EXPECT_EQ(n.chordDegrees.size(), 2u);
    EXPECT_EQ(n.chordDegrees[0], 3);
    EXPECT_EQ(n.chordDegrees[1], 5);
    EXPECT_EQ(n.chordOctaveDots.size(), 2u);
    EXPECT_EQ(n.chordOctaveDots[0], -1);
    EXPECT_EQ(n.chordOctaveDots[1], 1);
}

// A JSON 透出 chordOctaveDots
TEST(m15_A_json_exposes_chordOctaveDots) {
    JianpuDoc doc = mkChordDoc(0, "major", mkChordRoot(1, 1, {3}, {-1}));
    std::string json = jianpuToJson(doc);
    EXPECT_TRUE(json.find("\"chordOctaveDots\":[-1]") != std::string::npos);
}

// ===================== B tieStop 反向还原 =====================

// B staffToJianpu 据 Note.tieStop 写 JianpuNote.tieFromPrev
TEST(m15_B_staffToJianpu_writes_tieFromPrev) {
    Measure m; m.number = 1;
    Note n1 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n1.tieStart = true;
    Note n2 = mkNote(mkPitch('C', 0, 4), "quarter", 1); n2.tieStop = true;
    m.notes.push_back(n1); m.notes.push_back(n2);
    Score s = mkScore(0, "major", 4, 4, {m}, "tie");
    JianpuDoc doc = staffToJianpu(s);
    auto& notes = firstMeasure(doc);
    EXPECT_EQ(notes.size(), 2u);
    EXPECT_TRUE(notes[0].tieToNext);     // 起点画连音线
    EXPECT_FALSE(notes[0].tieFromPrev);  // 非 stop 端
    EXPECT_FALSE(notes[1].tieToNext);
    EXPECT_TRUE(notes[1].tieFromPrev);   // stop 端 -> tieFromPrev
}

// B jianpuToStaff 据 JianpuNote.tieFromPrev 设 Note.tieStop
TEST(m15_B_jianpuToStaff_sets_tieStop) {
    JianpuDoc doc;
    doc.fifths = 0; doc.mode = "major"; doc.beats = 4; doc.beatType = 4;
    doc.tonicLabel = "1=X"; doc.title = "t";
    JianpuLine line; line.voice = 1; line.partIndex = 0;
    JianpuMeasure m; m.number = 1;
    JianpuNote a = mkJn(1); a.onset = 0; a.tieToNext = true;    // 起点
    JianpuNote b = mkJn(1); b.onset = 1; b.tieFromPrev = true;  // stop 端
    m.notes.push_back(a); m.notes.push_back(b);
    line.measures.push_back(m); doc.lines.push_back(line);
    Score sc = jianpuToStaff(doc, 4);
    auto& notes = sc.parts[0].measures[0].notes;
    EXPECT_EQ(notes.size(), 2u);
    EXPECT_TRUE(notes[0].tieStart);
    EXPECT_FALSE(notes[0].tieStop);
    EXPECT_FALSE(notes[1].tieStart);
    EXPECT_TRUE(notes[1].tieStop);     // 反向还原成功
}

// B 往返（内存 Score）start+stop 配对：tieStart/tieStop 逐项守恒，时值不拆不并
TEST(m15_B_roundtrip_memory_start_stop) {
    Measure m; m.number = 1;
    Note n1 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n1.tieStart = true;
    Note n2 = mkNote(mkPitch('C', 0, 4), "quarter", 1); n2.tieStop = true;
    m.notes.push_back(n1); m.notes.push_back(n2);
    Score orig = mkScore(0, "major", 4, 4, {m}, "tie");
    JianpuDoc doc = staffToJianpu(orig);
    Score back = jianpuToStaff(doc, 4);
    auto& o = orig.parts[0].measures[0].notes;
    auto& b = back.parts[0].measures[0].notes;
    EXPECT_EQ(b.size(), o.size());
    EXPECT_EQ(b[0].tieStart, o[0].tieStart);
    EXPECT_EQ(b[0].tieStop,  o[0].tieStop);
    EXPECT_EQ(b[1].tieStart, o[1].tieStart);
    EXPECT_EQ(b[1].tieStop,  o[1].tieStop);
}

// B 往返（内存 Score）start→continue→stop 三音链：逐项守恒
TEST(m15_B_roundtrip_memory_continue_chain) {
    Measure m; m.number = 1;
    Note n1 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n1.tieStart = true;                 // start
    Note n2 = mkNote(mkPitch('C', 0, 4), "quarter", 1); n2.tieStart = true; n2.tieStop = true; // continue
    Note n3 = mkNote(mkPitch('C', 0, 4), "quarter", 2); n3.tieStop = true;                  // stop
    m.notes.push_back(n1); m.notes.push_back(n2); m.notes.push_back(n3);
    Score orig = mkScore(0, "major", 4, 4, {m}, "chain");
    JianpuDoc doc = staffToJianpu(orig);
    // 中间校验：staffToJianpu 逐音写出 tieToNext/tieFromPrev
    auto& jn = firstMeasure(doc);
    EXPECT_FALSE(jn[0].tieFromPrev); EXPECT_TRUE(jn[0].tieToNext);
    EXPECT_TRUE(jn[1].tieFromPrev);  EXPECT_TRUE(jn[1].tieToNext);
    EXPECT_TRUE(jn[2].tieFromPrev);  EXPECT_FALSE(jn[2].tieToNext);
    Score back = jianpuToStaff(doc, 4);
    auto& o = orig.parts[0].measures[0].notes;
    auto& b = back.parts[0].measures[0].notes;
    EXPECT_EQ(b.size(), o.size());
    for (size_t i = 0; i < 3; ++i) {
        EXPECT_EQ(b[i].tieStart, o[i].tieStart);
        EXPECT_EQ(b[i].tieStop,  o[i].tieStop);
    }
}

// B 往返（序列化）：Score → scoreToMusicXML → 重解析 → staffToJianpu → jianpuToStaff，
//    stop 端不被吞、不被误加
TEST(m15_B_roundtrip_serialized_start_stop) {
    Measure m; m.number = 1;
    Note n1 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n1.tieStart = true;
    Note n2 = mkNote(mkPitch('C', 0, 4), "quarter", 1); n2.tieStop = true;
    m.notes.push_back(n1); m.notes.push_back(n2);
    Score orig = mkScore(0, "major", 4, 4, {m}, "tie");
    std::string xml = scoreToMusicXML(orig);   // Score 直接序列化（jianpuToStaff 收 JianpuDoc）
    MusicXMLParser parser; Score back; std::string perr;
    EXPECT_TRUE(parser.parseString(xml, back, perr));
    auto& bn = back.parts[0].measures[0].notes;
    EXPECT_TRUE(bn[0].tieStart);    // 起点保留
    EXPECT_TRUE(bn[1].tieStop);     // stop 端经 MusicXML 往返仍解析为 tieStop
    // 再经 staffToJianpu 应写出 tieFromPrev=true 给 stop 音
    JianpuDoc doc = staffToJianpu(back);
    auto& jn = firstMeasure(doc);
    EXPECT_FALSE(jn[0].tieFromPrev);
    EXPECT_TRUE(jn[1].tieFromPrev);
    // 再 jianpuToStaff 应还原 tieStop（不丢、不误加）
    Score sc2 = jianpuToStaff(doc, 4);
    auto& bn2 = sc2.parts[0].measures[0].notes;
    EXPECT_FALSE(bn2[0].tieStop);
    EXPECT_TRUE(bn2[1].tieStop);
}

// ===================== C 极端连音比容错 =====================

// C 内存构造 7:8 / 7:4 / 9:4 极端比：不崩溃、标记 rhythmUnresolvable、
//   逐音独立、不污染相邻常规音符、tuplet 字段反映极端比
TEST(m15_C_extreme_tuplet_marks_and_no_pollution) {
    Measure m; m.number = 1;
    Note n0 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n0.quarterLength = 1.0;             // 常规
    Note n1 = mkNote(mkPitch('E', 0, 4), "eighth", 1);                                       // 7:8 极端
    n1.quarterLength = 0.4; n1.tupletActual = 7; n1.tupletNormal = 8; n1.type = "eighth";
    Note n2 = mkNote(mkPitch('G', 0, 4), "quarter", 2); n2.quarterLength = 1.0;             // 常规
    Note n3 = mkNote(mkPitch('A', 0, 4), "eighth", 3);                                       // 7:4 极端
    n3.quarterLength = 0.6; n3.tupletActual = 7; n3.tupletNormal = 4; n3.type = "eighth";
    Note n4 = mkNote(mkPitch('B', 0, 4), "quarter", 4); n4.quarterLength = 1.0;             // 常规
    Note n5 = mkNote(mkPitch('C', 0, 5), "eighth", 5);                                       // 9:4 极端
    n5.quarterLength = 0.8; n5.tupletActual = 9; n5.tupletNormal = 4; n5.type = "eighth";
    m.notes.push_back(n0); m.notes.push_back(n1); m.notes.push_back(n2);
    m.notes.push_back(n3); m.notes.push_back(n4); m.notes.push_back(n5);
    Score s = mkScore(0, "major", 4, 4, {m}, "extreme");
    JianpuDoc doc;
    EXPECT_NO_THROW(doc = staffToJianpu(s));   // AC-C1：不崩溃
    auto& notes = firstMeasure(doc);
    EXPECT_EQ(notes.size(), 6u);
    // 常规音符不标记、不被污染
    EXPECT_FALSE(notes[0].rhythmUnresolvable);
    EXPECT_FALSE(notes[2].rhythmUnresolvable);
    EXPECT_FALSE(notes[4].rhythmUnresolvable);
    EXPECT_EQ(notes[0].degree, 1); EXPECT_EQ(notes[0].octaveDots, 0);
    EXPECT_EQ(notes[2].degree, 5); EXPECT_EQ(notes[2].octaveDots, 0);
    EXPECT_EQ(notes[4].degree, 7); EXPECT_EQ(notes[4].octaveDots, 0);
    // 极端音符标记，且逐音独立
    EXPECT_TRUE(notes[1].rhythmUnresolvable);
    EXPECT_TRUE(notes[3].rhythmUnresolvable);
    EXPECT_TRUE(notes[5].rhythmUnresolvable);
    EXPECT_EQ(notes[1].tuplet, 7);
    EXPECT_EQ(notes[3].tuplet, 7);
    EXPECT_EQ(notes[5].tuplet, 9);
    // 极端音符自身音高/八度点不受影响
    EXPECT_EQ(notes[1].degree, 3); EXPECT_EQ(notes[1].octaveDots, 0);
    EXPECT_EQ(notes[5].degree, 1); EXPECT_EQ(notes[5].octaveDots, 1);
}

// C JSON 透出 rhythmUnresolvable（机读报告）
TEST(m15_C_json_reports_rhythmUnresolvable) {
    Measure m; m.number = 1;
    Note n0 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n0.quarterLength = 1.0;
    Note n1 = mkNote(mkPitch('E', 0, 4), "eighth", 1);
    n1.quarterLength = 0.4; n1.tupletActual = 7; n1.tupletNormal = 8; n1.type = "eighth";
    m.notes.push_back(n0); m.notes.push_back(n1);
    Score s = mkScore(0, "major", 4, 4, {m}, "json");
    JianpuDoc doc = staffToJianpu(s);
    std::string json = jianpuToJson(doc);
    EXPECT_TRUE(json.find("\"rhythmUnresolvable\":true") != std::string::npos);
    EXPECT_TRUE(json.find("\"rhythmUnresolvable\":false") != std::string::npos);
}

// C 序列化往返（高精度 divisions）：极端比仍被标记、进程不崩溃
TEST(m15_C_serialized_roundtrip_preserves_mark) {
    Measure m; m.number = 1;
    Note n0 = mkNote(mkPitch('C', 0, 4), "quarter", 0); n0.quarterLength = 1.0;
    Note n1 = mkNote(mkPitch('E', 0, 4), "eighth", 1);
    n1.quarterLength = 0.4; n1.tupletActual = 7; n1.tupletNormal = 8; n1.type = "eighth";
    m.notes.push_back(n0); m.notes.push_back(n1);
    Part p; p.id = "P1"; p.name = "P1";
    p.attributes.divisions = 480; p.attributes.fifths = 0; p.attributes.mode = "major";
    p.attributes.beats = 4; p.attributes.beatType = 4;
    p.measures.push_back(m);
    Score s; s.parts.push_back(p);
    // 设置 duration 使序列化精确保留 quarterLength（480 divisions）
    for (auto& nt : s.parts[0].measures[0].notes)
        nt.duration = static_cast<long>(std::llround(nt.quarterLength * 480));
    std::string xml = scoreToMusicXML(s);
    MusicXMLParser parser; Score back; std::string perr;
    EXPECT_NO_THROW(parser.parseString(xml, back, perr));
    EXPECT_TRUE(back.parts[0].attributes.divisions == 480);
    JianpuDoc doc;
    EXPECT_NO_THROW(doc = staffToJianpu(back));   // AC-C1：不崩溃
    auto& notes = firstMeasure(doc);
    EXPECT_EQ(notes.size(), 2u);
    EXPECT_FALSE(notes[0].rhythmUnresolvable);    // 常规
    EXPECT_TRUE(notes[1].rhythmUnresolvable);     // 极端比仍被标记
}
