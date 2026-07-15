// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：Score -> JianpuDoc 主流程 + L1 渲染
// （§5 case 3/4/5/6/7/8 + 全局属性 + 边界/错误）
// 被测函数：staffToJianpu、jianpuToL1
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"
#include "test_helpers.hpp"

using namespace pudu;

// ===== §5 case 3 + 附点：附点四分通过 Note.dots 表达 =====

TEST(staffToJianpu_dotted_quarter_keeps_dots) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 0, 1, 1)); // 附点四分
    Score s = mkScore(0, "major", 4, 4, {m}, "附点测试");
    JianpuDoc doc = staffToJianpu(s);
    EXPECT_EQ(doc.lines.size(), 1u);
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].dots, 1);
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 1);
}

// ===== §5 case 4：全休止 0 - - - 与八分休止 =====

TEST(staffToJianpu_whole_rest_renders_zero_augment3) {
    Measure m; m.number = 1;
    m.notes.push_back(mkRest("whole", 0));
    Score s = mkScore(0, "major", 4, 4, {m}, "全休止");
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.degree, 0);
    EXPECT_EQ(jn.augmentDashes, 3);
    EXPECT_EQ(jn.underlines, 0);
}
TEST(staffToJianpu_eighth_rest_has_underline) {
    Measure m; m.number = 1;
    m.notes.push_back(mkRest("eighth", 0));
    Score s = mkScore(0, "major", 4, 4, {m}, "八分休止");
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.degree, 0);
    EXPECT_EQ(jn.underlines, 1);
}

// ===== §5 case 5：三和弦 主音 + 2 成员（音级正确；逐音八度点为后续扩展）=====

TEST(staffToJianpu_triad_chord_stores_degrees) {
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "quarter", 0);
    n.chordPitches.push_back(mkPitch('E', 0, 4));
    n.chordPitches.push_back(mkPitch('G', 0, 4));
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m}, "C和弦");
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.degree, 1);                  // C = 1
    EXPECT_EQ(jn.chordDegrees.size(), 2u);
    EXPECT_EQ(jn.chordDegrees[0], 3);         // E = 3
    EXPECT_EQ(jn.chordDegrees[1], 5);         // G = 5
}

// ===== §5 case 6：多声部，backup 后 voice2 与 voice1 onset 对齐，各成一行 =====

TEST(staffToJianpu_multi_voice_splits_lines) {
    Measure m; m.number = 1;
    // voice1: C4 @0, E4 @1 ；voice2: G3 @0, B3 @1（onset 对齐）
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 0, 1));
    m.notes.push_back(mkNote(mkPitch('G', 0, 3), "quarter", 0, 2));
    m.notes.push_back(mkNote(mkPitch('E', 0, 4), "quarter", 1, 1));
    m.notes.push_back(mkNote(mkPitch('B', 0, 3), "quarter", 1, 2));
    Score s = mkScore(0, "major", 4, 4, {m}, "二声部");
    JianpuDoc doc = staffToJianpu(s);
    EXPECT_EQ(doc.lines.size(), 2u);

    const JianpuLine* v1 = nullptr;
    const JianpuLine* v2 = nullptr;
    for (const auto& l : doc.lines) {
        if (l.voice == 1) v1 = &l;
        if (l.voice == 2) v2 = &l;
    }
    EXPECT_TRUE(v1 != nullptr);
    EXPECT_TRUE(v2 != nullptr);
    EXPECT_EQ(v1->measures[0].notes.size(), 2u);
    EXPECT_EQ(v2->measures[0].notes.size(), 2u);
    // 同 onset 音符在各自行内按 onset 升序排列
    EXPECT_EQ(v1->measures[0].notes[0].degree, 1); // C
    EXPECT_EQ(v1->measures[0].notes[1].degree, 3); // E
    EXPECT_EQ(v2->measures[0].notes[0].degree, 5); // G（低八度）
    EXPECT_EQ(v2->measures[0].notes[1].degree, 7); // B
}

// ===== §5 case 7：装饰音不占基本拍，标记正确 =====

TEST(staffToJianpu_grace_note_flagged) {
    Measure m; m.number = 1;
    Note grace = mkNote(mkPitch('D', 0, 4), "eighth", 0);
    grace.isGrace = true;
    m.notes.push_back(grace);
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 1));
    Score s = mkScore(0, "major", 4, 4, {m}, "装饰音");
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& g = doc.lines[0].measures[0].notes[0];
    EXPECT_TRUE(g.isGrace);
    EXPECT_EQ(g.degree, 2);  // D = 2
}

// ===== §5 case 8：跨小节延音线 =====

TEST(staffToJianpu_tie_across_measures) {
    Measure m1; m1.number = 1;
    Note n1 = mkNote(mkPitch('C', 0, 4), "half", 0);
    n1.tieStart = true;
    m1.notes.push_back(n1);
    Measure m2; m2.number = 2;
    Note n2 = mkNote(mkPitch('C', 0, 4), "half", 0);
    n2.tieStop = true;
    m2.notes.push_back(n2);
    Score s = mkScore(0, "major", 4, 4, {m1, m2}, "延音");
    JianpuDoc doc = staffToJianpu(s);
    EXPECT_EQ(doc.lines[0].measures.size(), 2u);
    EXPECT_TRUE(doc.lines[0].measures[0].notes[0].tieToNext);   // 起点画连音线
    EXPECT_FALSE(doc.lines[0].measures[1].notes[0].tieToNext);  // 止点不画
    EXPECT_EQ(doc.lines[0].measures[1].notes[0].degree, 1);
}

// ===== 选项 B：节奏以 quarterLength 为准，解耦于 <type>（稳健于 type/duration 不一致） =====

TEST(staffToJianpu_rhythm_from_quarterLength_overrides_bad_type) {
    // 源 MusicXML 常见坑：<type>=quarter 但 <duration> 实际 = 2 拍
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "quarter", 0);
    n.quarterLength = 2.0;          // 实际半音符
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.augmentDashes, 1);  // 半音符增时线（而非 type 误导的四分）
    EXPECT_EQ(jn.underlines, 0);
    EXPECT_EQ(jn.dots, 0);
}

TEST(staffToJianpu_rhythm_dotted_from_quarterLength) {
    // 源标 <type>=half 但实际 = half+dot = 3 拍
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "half", 0);
    n.quarterLength = 3.0;
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.augmentDashes, 1);  // 半音符增时线
    EXPECT_EQ(jn.dots, 1);           // 附点（由 ql 反推，非 type）
}

TEST(staffToJianpu_rhythm_fallback_to_type_for_tuplet) {
    // 连音组 quarterLength 无法映射为标准时值 -> 回退 <type> 记谱值，不污染输出
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "eighth", 0);
    n.quarterLength = 0.6667;        // 三连音四分（2/3 拍），非标准
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.underlines, 1);     // 八分减时线（来自 type 回退）
    EXPECT_EQ(jn.dots, 0);
}

TEST(staffToJianpu_annotates_tuplet_grouping) {
    // 选项 A：解析到 <time-modification> 后，转换器应将实际音符数写入 jn.tuplet。
    // 三连音八分(实际 ql=1/3，基准 = (1/3)×3/2 = 0.5 = 八分) -> ul=1, dots=0。
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "eighth", 0);
    n.quarterLength = 1.0 / 3.0;
    n.tupletActual = 3;        // 三连音
    n.tupletNormal = 2;
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.tuplet, 3);          // 连音分组标注
    EXPECT_EQ(jn.underlines, 1);      // 八分减时线（基准节奏 = quarterLength×actual/normal）
    EXPECT_EQ(jn.dots, 0);
}

TEST(staffToJianpu_non_tuplet_tuplet_field_is_zero) {
    // 常规音符无 time-modification -> tuplet 保持 0（不误标连音组）
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('G', 0, 4), "quarter", 0);
    n.quarterLength = 1.0;
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.tuplet, 0);
}

TEST(staffToJianpu_tuplet_base_rhythm_matches_type) {
    // 选项 A 约定：三连音八分(type=eighth, 实际 ql=1/3)基准节奏=八分(ul=1,dots=0)，
    //   与校验器 base_ql = 实际×actual/normal = (1/3)×1.5 = 0.5 同口径 -> 校验通过。
    Measure m; m.number = 1;
    Note n = mkNote(mkPitch('C', 0, 4), "eighth", 0);
    n.quarterLength = 1.0 / 3.0;     // 三连音八分实际时值(非标准)
    n.tupletActual = 3;
    n.tupletNormal = 2;
    m.notes.push_back(n);
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    const JianpuNote& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.tuplet, 3);          // 分组标注
    EXPECT_EQ(jn.underlines, 1);      // 基准=八分
    EXPECT_EQ(jn.dots, 0);
}

// 全局属性：调号/拍号/标题正确投影到 doc
TEST(staffToJianpu_propagates_header) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('G', 0, 4), "quarter", 0));
    Score s = mkScore(2, "major", 3, 4, {m}, "D大调片段");
    JianpuDoc doc = staffToJianpu(s);
    EXPECT_EQ(doc.tonicLabel, "1=D");
    EXPECT_EQ(doc.beats, 3);
    EXPECT_EQ(doc.beatType, 4);
    EXPECT_EQ(doc.title, "D大调片段");
}

// 错误处理：空 Score 返回空文档，不崩溃
TEST(staffToJianpu_empty_score_returns_empty_doc) {
    Score s;
    JianpuDoc doc;
    EXPECT_NO_THROW(doc = staffToJianpu(s));
    EXPECT_TRUE(doc.lines.empty());
    EXPECT_EQ(doc.tonicLabel, "");
}

// ===== jianpuToL1 渲染（验证用）=====

TEST(jianpuToL1_renders_header_and_notes) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 0));
    m.notes.push_back(mkNote(mkPitch('G', 0, 4), "quarter", 1));
    Score s = mkScore(0, "major", 4, 4, {m}, "小星星片段");
    JianpuDoc doc = staffToJianpu(s);
    std::string out = jianpuToL1(doc);
    EXPECT_TRUE(out.find("小星星片段") != std::string::npos);
    EXPECT_TRUE(out.find("1=C 4/4") != std::string::npos);
    EXPECT_TRUE(out.find("1") != std::string::npos);
    EXPECT_TRUE(out.find("5") != std::string::npos);
}

// 错误处理：空文档不崩溃，至少输出抬头占位
TEST(jianpuToL1_empty_doc_safe) {
    JianpuDoc doc;
    std::string out;
    EXPECT_NO_THROW(out = jianpuToL1(doc));
    EXPECT_TRUE(!out.empty());
}

// ===== jianpuToL2 渲染（二维 HTML/Unicode）=====

// 自包含 HTML：含 DOCTYPE、数字节点、抬头、调号
TEST(jianpuToL2_self_contained_html) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 0));
    Score s = mkScore(0, "major", 4, 4, {m}, "L2片段");
    JianpuDoc doc = staffToJianpu(s);
    std::string html;
    EXPECT_NO_THROW(html = jianpuToL2(doc));
    EXPECT_TRUE(html.find("<!DOCTYPE html>") != std::string::npos);
    EXPECT_TRUE(html.find("jp-num") != std::string::npos);     // 数字节点
    EXPECT_TRUE(html.find("L2片段") != std::string::npos);     // 标题
    EXPECT_TRUE(html.find("1=C 4/4") != std::string::npos);    // 调号抬头
}

// 减时线横向连写：连续两个八分音符应连成 beam 组（含 beam-lines 贯穿线）
TEST(jianpuToL2_beam_for_consecutive_eighths) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "eighth", 0));
    m.notes.push_back(mkNote(mkPitch('D', 0, 4), "eighth", 1));
    Score s = mkScore(0, "major", 4, 4, {m}, "连写");
    JianpuDoc doc = staffToJianpu(s);
    std::string html = jianpuToL2(doc);
    EXPECT_TRUE(html.find("class=\"beam\"") != std::string::npos);
    EXPECT_TRUE(html.find("beam-lines") != std::string::npos);
}

// 高低八度点：高音(C5)渲染上点(jp-up)，低音(C3)渲染下点(jp-down)
TEST(jianpuToL2_octave_dots_high_and_low) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 5), "quarter", 0)); // 升八度
    m.notes.push_back(mkNote(mkPitch('C', 0, 3), "quarter", 1)); // 降八度
    Score s = mkScore(0, "major", 4, 4, {m}, "八度点");
    JianpuDoc doc = staffToJianpu(s);
    std::string html = jianpuToL2(doc);
    EXPECT_TRUE(html.find("jp-up") != std::string::npos);
    EXPECT_TRUE(html.find("jp-down") != std::string::npos);
}

// 错误处理：空文档不崩溃，仍输出合法 HTML 骨架
TEST(jianpuToL2_empty_doc_safe) {
    JianpuDoc doc;
    std::string html;
    EXPECT_NO_THROW(html = jianpuToL2(doc));
    EXPECT_TRUE(html.find("<!DOCTYPE html>") != std::string::npos);
}

// ===== L3 JSON 输出：无损结构化，供校验器逐音比对 =====

// 正常：单音 C4(大调) -> degree=1, octaveDots=0, accidental=none，且顶层含 fifths/tonicLabel
TEST(jianpuToJson_single_note_basic) {
    Measure m; m.number = 1;
    m.notes.push_back(mkNote(mkPitch('C', 0, 4), "quarter", 0));
    Score s = mkScore(0, "major", 4, 4, {m}, "JSON测试");
    JianpuDoc doc = staffToJianpu(s);
    std::string json;
    EXPECT_NO_THROW(json = jianpuToJson(doc));
    EXPECT_TRUE(json.find("\"fifths\":0") != std::string::npos);
    EXPECT_TRUE(json.find("\"tonicLabel\":\"1=C\"") != std::string::npos);
    EXPECT_TRUE(json.find("\"degree\":1") != std::string::npos);
    EXPECT_TRUE(json.find("\"octaveDots\":0") != std::string::npos);
    EXPECT_TRUE(json.find("\"accidental\":\"none\"") != std::string::npos);
    EXPECT_TRUE(json.find("\"lines\":[") != std::string::npos);
}

// 错误处理：空文档不崩溃，仍输出合法 JSON 骨架（含 lines:[]）
TEST(jianpuToJson_empty_doc_safe) {
    JianpuDoc doc;
    std::string json;
    EXPECT_NO_THROW(json = jianpuToJson(doc));
    EXPECT_TRUE(json.find("\"lines\":[]") != std::string::npos);
    // 顶层为对象且以 } 结尾（基本结构完整）
    EXPECT_TRUE(json.front() == '{' && json.back() == '}');
}
