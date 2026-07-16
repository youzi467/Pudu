// ----------------------------------------------------------------------
// 谱渡 Pudu · G4 简谱文本解析器单元测试
//
// 覆盖：基本音级/onset 累计、八度点、临时记号、时值（减时/增时/附点）、
//       休止、和弦、连音线、多声部与小节切分、调号头行解析，以及
//       端到端闭环（parseJianpuText -> jianpuToStaff -> scoreToMusicXML ->
//       MusicXMLParser::parseString 读回，声部/调号/拍号/音高序列一致）。
// 另含错误用例：非法音级、空输入、非法调名。
//
// 运行：build/PuduTests.exe
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_text_parser.hpp"
#include "jianpu_to_staff.hpp"
#include "jianpu_model.hpp"
#include "musicxml_parser.hpp"
#include "score_model.hpp"

#include <string>
#include <utility>   // std::pair（音高序列断言用）
#include <vector>

using namespace pudu;

// 取单一声部第一小节所有音符（便于断言）
static const std::vector<JianpuNote>& firstMeasureNotes(const JianpuDoc& doc) {
    return doc.lines[0].measures[0].notes;
}

TEST(parse_basic_degree_onset) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 1 2 3 4", out, err));
    EXPECT_EQ(out.lines.size(), 1);
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 4u);
    EXPECT_EQ(n[0].degree, 1);
    EXPECT_EQ(n[1].degree, 2);
    EXPECT_EQ(n[2].degree, 3);
    EXPECT_EQ(n[3].degree, 4);
    // onset 按四分音符累计
    EXPECT_EQ(n[0].onset, 0.0);
    EXPECT_EQ(n[1].onset, 1.0);
    EXPECT_EQ(n[2].onset, 2.0);
    EXPECT_EQ(n[3].onset, 3.0);
}

TEST(parse_octave_dots) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 1' 2,, 3'''", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 3u);
    EXPECT_EQ(n[0].degree, 1); EXPECT_EQ(n[0].octaveDots, 1);
    EXPECT_EQ(n[1].degree, 2); EXPECT_EQ(n[1].octaveDots, -2);
    EXPECT_EQ(n[2].degree, 3); EXPECT_EQ(n[2].octaveDots, 3);
}

TEST(parse_accidentals) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: #1 b2 n3 x4 bb5", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 5u);
    EXPECT_EQ(n[0].accidental, Accidental::Sharp);
    EXPECT_EQ(n[1].accidental, Accidental::Flat);
    EXPECT_EQ(n[2].accidental, Accidental::Natural);
    EXPECT_EQ(n[3].accidental, Accidental::DoubleSharp);
    EXPECT_EQ(n[4].accidental, Accidental::DoubleFlat);
}

TEST(parse_durations) {
    JianpuDoc out; std::string err;
    // 八分(_) / 十六分(__) / 二分( -) / 全音符( - - -)
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 5_ 5__ 5 - 5 - - -", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 4u);
    EXPECT_EQ(n[0].underlines, 1);    // 八分
    EXPECT_EQ(n[1].underlines, 2);    // 十六分
    EXPECT_EQ(n[2].augmentDashes, 1); // 二分
    EXPECT_EQ(n[3].augmentDashes, 3); // 全音符
}

TEST(parse_dots) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 5. 5..", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 2u);
    EXPECT_EQ(n[0].dots, 1);
    EXPECT_EQ(n[1].dots, 2);
}

TEST(parse_rest) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 1 0 2", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 3u);
    EXPECT_EQ(n[0].degree, 1);
    EXPECT_EQ(n[1].degree, 0);   // 休止
    EXPECT_EQ(n[2].degree, 2);
}

TEST(parse_chord) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: [1 3 5]", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 1u);
    EXPECT_EQ(n[0].degree, 1);
    EXPECT_EQ(n[0].chordDegrees.size(), 2u);
    EXPECT_EQ(n[0].chordDegrees[0], 3);
    EXPECT_EQ(n[0].chordDegrees[1], 5);
}

TEST(parse_tie) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: 1~ 2", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 2u);
    EXPECT_TRUE(n[0].tieToNext);
    EXPECT_FALSE(n[1].tieToNext);
}

TEST(parse_chord_with_accidental) {
    // renderJianpuNote 对带记号的和弦输出 #[1 3 5]（记号紧贴 '['），
    // 解析器须将其整体成词：主音 degree=1 + Sharp，其余和弦音 3/5。
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=C 4/4 (major)\nvoice1: #[1 3 5]", out, err));
    auto& n = firstMeasureNotes(out);
    EXPECT_EQ(n.size(), 1u);
    EXPECT_EQ(n[0].degree, 1);
    EXPECT_EQ(n[0].accidental, Accidental::Sharp);
    EXPECT_EQ(n[0].chordDegrees.size(), 2u);
    EXPECT_EQ(n[0].chordDegrees[0], 3);
    EXPECT_EQ(n[0].chordDegrees[1], 5);
}

TEST(parse_multivoice_measures) {
    JianpuDoc out; std::string err;
    const char* txt =
        "小星星\n"
        "1=C 4/4 (major)\n"
        "voice1: 1 1 5 5 | 6 6 5 - ||\n"
        "voice2: 7 7 6 6 | 5 5 4 - ||\n";
    EXPECT_TRUE(parseJianpuText(txt, out, err));
    EXPECT_EQ(out.title, "小星星");
    EXPECT_EQ(out.lines.size(), 2u);

    // 声部与 partIndex
    EXPECT_EQ(out.lines[0].voice, 1);
    EXPECT_EQ(out.lines[0].partIndex, 0);
    EXPECT_EQ(out.lines[1].voice, 2);
    EXPECT_EQ(out.lines[1].partIndex, 1);

    // 每声部 2 小节；小节1 含 4 音，小节2 含 3 音（末音二分）
    EXPECT_EQ(out.lines[0].measures.size(), 2u);
    EXPECT_EQ(out.lines[1].measures.size(), 2u);
    EXPECT_EQ(out.lines[0].measures[0].notes.size(), 4u);
    EXPECT_EQ(out.lines[0].measures[1].notes.size(), 3u);
    EXPECT_EQ(out.lines[1].measures[0].notes.size(), 4u);
    EXPECT_EQ(out.lines[1].measures[1].notes.size(), 3u);

    // 二分音符：augmentDashes=1，onset 累计正确（小节2: 6 6 5 - → onsets 0,1,2）
    EXPECT_EQ(out.lines[0].measures[1].notes[2].augmentDashes, 1);
    EXPECT_EQ(out.lines[0].measures[1].notes[0].onset, 0.0);
    EXPECT_EQ(out.lines[0].measures[1].notes[2].onset, 2.0);
}

TEST(parse_header_key_beats_mode) {
    JianpuDoc out; std::string err;
    EXPECT_TRUE(parseJianpuText("1=D 4/4 (major)\nvoice1: 1 2 3", out, err));
    EXPECT_EQ(out.fifths, 2);          // D 大调 = 2 个升号
    EXPECT_EQ(out.beats, 4);
    EXPECT_EQ(out.beatType, 4);
    EXPECT_EQ(out.mode, "major");
    EXPECT_EQ(out.tonicLabel, "1=D");
}

TEST(parse_header_minor_suffix_from_keyname) {
    JianpuDoc out; std::string err;
    // 调名自带小调（Am），无显式 (mode) 时 mode 应推为 minor
    EXPECT_TRUE(parseJianpuText("1=Am 3/4\nvoice1: 1 2 3", out, err));
    EXPECT_EQ(out.fifths, 0);
    EXPECT_EQ(out.beats, 3);
    EXPECT_EQ(out.beatType, 4);
    EXPECT_EQ(out.mode, "minor");
}

// ---- 错误用例 ----
TEST(parse_error_illegal_degree) {
    JianpuDoc out; std::string err;
    EXPECT_FALSE(parseJianpuText("8 8", out, err));   // 无头行 + 非法音级 8
    EXPECT_FALSE(err.empty());
}

TEST(parse_error_empty) {
    JianpuDoc out; std::string err;
    EXPECT_FALSE(parseJianpuText("", out, err));
    EXPECT_FALSE(err.empty());
}

TEST(parse_error_no_header) {
    JianpuDoc out; std::string err;
    EXPECT_FALSE(parseJianpuText("voice1: 1 2 3", out, err));   // 缺少 1= 头行
    EXPECT_FALSE(err.empty());
}

TEST(parse_error_bad_key) {
    JianpuDoc out; std::string err;
    EXPECT_FALSE(parseJianpuText("1=ZZZ 4/4 (major)\nvoice1: 1 2 3", out, err));
    EXPECT_FALSE(err.empty());
}

// ---- 端到端闭环：文本 -> Score -> MusicXML -> 解析回 Score ----
TEST(parse_roundtrip_single_voice) {
    const char* txt =
        "小星星\n"
        "1=C 4/4 (major)\n"
        "voice1: 1 2 3 4 5 6 7\n";
    JianpuDoc doc; std::string err;
    EXPECT_TRUE(parseJianpuText(txt, doc, err));

    Score score = jianpuToStaff(doc, 4);
    std::string xml = scoreToMusicXML(score);
    EXPECT_TRUE(!xml.empty());

    MusicXMLParser parser;
    Score back;
    std::string perr;
    EXPECT_TRUE(parser.parseString(xml, back, perr));
    if (!perr.empty()) std::cerr << "[roundtrip] parse error: " << perr << std::endl;

    // 声部 / 调号 / 拍号
    EXPECT_EQ(back.parts.size(), 1u);
    EXPECT_EQ(back.title, "小星星");
    EXPECT_EQ(back.parts[0].attributes.fifths, 0);
    EXPECT_EQ(back.parts[0].attributes.mode, "major");
    EXPECT_EQ(back.parts[0].attributes.beats, 4);
    EXPECT_EQ(back.parts[0].attributes.beatType, 4);

    // 音高序列：C4 D4 E4 F4 G4 A4 B4
    std::vector<std::pair<char, int>> got;
    for (const auto& m : back.parts[0].measures)
        for (const auto& n : m.notes)
            if (!n.isRest) got.push_back({n.pitch.step, n.pitch.octave});
    std::vector<std::pair<char, int>> expect = {
        {'C', 4}, {'D', 4}, {'E', 4}, {'F', 4}, {'G', 4}, {'A', 4}, {'B', 4}};
    EXPECT_EQ(got.size(), expect.size());
    for (size_t i = 0; i < expect.size(); ++i) {
        EXPECT_EQ(got[i].first, expect[i].first);
        EXPECT_EQ(got[i].second, expect[i].second);
    }
}

TEST(parse_roundtrip_chord_and_tie) {
    const char* txt =
        "1=C 4/4 (major)\n"
        "voice1: [1 3 5] 2~ 3\n";
    JianpuDoc doc; std::string err;
    EXPECT_TRUE(parseJianpuText(txt, doc, err));

    Score score = jianpuToStaff(doc, 4);
    std::string xml = scoreToMusicXML(score);
    MusicXMLParser parser;
    Score back;
    std::string perr;
    EXPECT_TRUE(parser.parseString(xml, back, perr));
    if (!perr.empty()) std::cerr << "[roundtrip-chord] parse error: " << perr << std::endl;

    // 事件序列：和弦(1 事件) + 2(tieStart) + 3 = 3 个主事件
    int events = 0;
    for (const auto& m : back.parts[0].measures) events += static_cast<int>(m.notes.size());
    EXPECT_EQ(events, 3);

    const Note& chordRoot = back.parts[0].measures[0].notes[0];
    EXPECT_EQ(chordRoot.pitch.step, 'C');
    EXPECT_EQ(chordRoot.chordPitches.size(), 2u);
    EXPECT_EQ(chordRoot.chordPitches[0].step, 'E');
    EXPECT_EQ(chordRoot.chordPitches[1].step, 'G');

    // 第二音带连音线起始
    EXPECT_TRUE(back.parts[0].measures[0].notes[1].tieStart);
}
