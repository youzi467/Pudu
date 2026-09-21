// ----------------------------------------------------------------------
// 谱渡 Pudu · P1/P2 渲染配置单元测试
//   覆盖：固定每行小节数切分、行首小节号（仅系统首行）、空声部休止符填充、
//         implicit 弱起跳过、大谱表自动识别/手动配对/关闭，以及解析器 <staff>/<staves>。
//   纯内存模型 + 字符串计数断言，零文件依赖、零外部引擎。
// ----------------------------------------------------------------------

#include "jianpu_converter.hpp"
#include "jianpu_model.hpp"
#include "musicxml_parser.hpp"
#include "pudu_test.hpp"
#include "test_helpers.hpp"

#include <string>
#include <vector>

namespace {

size_t countOcc(const std::string& hay, const std::string& needle) {
    size_t n = 0, pos = 0;
    while ((pos = hay.find(needle, pos)) != std::string::npos) {
        ++n; pos += needle.size();
    }
    return n;
}

// 构造一条仅含实音（音级 = (m%7)+1）的 voice 行，共 measuresPerVoice 小节
pudu::JianpuLine mkLine(int voice, int measuresPerVoice) {
    pudu::JianpuLine l;
    l.voice = voice;
    for (int m = 1; m <= measuresPerVoice; ++m) {
        pudu::JianpuMeasure jm;
        jm.number = m;
        pudu::JianpuNote jn;
        jn.degree = (m % 7) + 1;
        jm.notes.push_back(jn);
        l.measures.push_back(jm);
    }
    return l;
}

// 构造一份简单 JianpuDoc：voices 条 voice 行，各 measuresPerVoice 小节
pudu::JianpuDoc mkDoc(int voices, int measuresPerVoice) {
    pudu::JianpuDoc doc;
    doc.mode = "major";
    doc.tonicLabel = "1=C";
    doc.beats = 4;
    doc.beatType = 4;
    for (int v = 1; v <= voices; ++v)
        doc.lines.push_back(mkLine(v, measuresPerVoice));
    return doc;
}

std::string l2Body(const pudu::JianpuDoc& doc, const pudu::JianpuRenderConfig& cfg) {
    std::string html = "          " + pudu::jianpuToL2(doc, cfg);
    auto pos = html.find("<div class=\"score\">");
    return (pos == std::string::npos) ? std::string() : html.substr(pos);
}

} // namespace

TEST(render_fixed_slicing_single_voice_systems) {
    auto doc = mkDoc(1, 9);                     // 9 小节单声部
    pudu::JianpuRenderConfig cfg;
    cfg.measuresPerLine = 4;
    std::string body = l2Body(doc, cfg);
    EXPECT_EQ(countOcc(body, "class=\"system\""), 3u);      // ceil(9/4)=3 系统
    EXPECT_EQ(countOcc(body, "class=\"measure\""), 9u);     // 小节数守恒
}

TEST(render_line_number_only_first_row_per_system) {
    // 单声部 9 小节, N=4 → 系统 1,5,9 三行，各带行首节号
    auto doc = mkDoc(1, 9);
    pudu::JianpuRenderConfig cfg;
    cfg.measuresPerLine = 4;
    std::string body = l2Body(doc, cfg);
    EXPECT_EQ(countOcc(body, "class=\"line-number\""), 3u);
}

TEST(render_line_number_multi_voice_shared_once) {
    // 双声部各 5 小节, N=4 → 2 系统；节号仅系统首行一次（双行共享）
    auto doc = mkDoc(2, 5);
    pudu::JianpuRenderConfig cfg;
    cfg.measuresPerLine = 4;
    std::string body = l2Body(doc, cfg);
    EXPECT_EQ(countOcc(body, "class=\"system\""), 2u);
    EXPECT_EQ(countOcc(body, "class=\"line-number\""), 2u);
}

TEST(render_empty_voice_rest_fill) {
    // voice2 第 3 小节无音符：fill=true 补 0，fill=false 空
    auto doc = mkDoc(2, 4);
    doc.lines[1].measures[2].notes.clear();     // 制造空小节
    pudu::JianpuRenderConfig on;                on.fillEmptyVoiceRest = true;
    pudu::JianpuRenderConfig off;
    std::string bOn = l2Body(doc, on);
    std::string bOff = l2Body(doc, off);
    EXPECT_GT(countOcc(bOn, "jp-num rest"), countOcc(bOff, "jp-num rest"));
    // 其它小节仍为实音（非休止）→ 休止数不超过 1 个空小节的合成
    EXPECT_LE(countOcc(bOn, "jp-num rest"), countOcc(bOff, "jp-num rest") + 8);
}

TEST(render_implicit_weak_pickup_skipped) {
    // 空小节且 implicit=true → 即便 fill=true 也不补 0
    auto doc = mkDoc(1, 3);
    doc.lines[0].measures[0].implicit = true;   // 弱起
    doc.lines[0].measures[0].notes.clear();
    pudu::JianpuRenderConfig on; on.fillEmptyVoiceRest = true;
    std::string bOn = l2Body(doc, on);
    // weak-pickup 小节被跳过填充，当前该行不含任何合成休止（其余小节均有实音）
    EXPECT_EQ(countOcc(bOn, "jp-num rest"), 0u);
}

TEST(render_default_cfg_no_system_or_grand_classes) {
    // 无任何参数：不得泄漏系统/行号/大谱表类（与纯行输出一致）
    auto doc = mkDoc(2, 4);
    std::string body = l2Body(doc, pudu::JianpuRenderConfig{});
    EXPECT_EQ(countOcc(body, "class=\"system\""), 0u);
    EXPECT_EQ(countOcc(body, "class=\"line-number\""), 0u);
    EXPECT_EQ(countOcc(body, "system-grand"), 0u);
}

// —— P2：大谱表 ——
// 单 part 内双谱表：staff1/voice1 上行 + staff2/voice5 下行
pudu::Score mkGrandScore() {
    pudu::Score s;
    s.title = "grand";
    pudu::Measure m1, m2;
    m1.number = 1;
    m2.number = 2;
    m1.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 5), "quarter", 0, 1, 0, 1)); // 上行 staff1
    m1.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 3), "quarter", 0, 5, 0, 2)); // 下行 staff2
    m2.notes.push_back(pudu::mkNote(pudu::mkPitch('G', 0, 5), "quarter", 0, 1, 0, 1));
    m2.notes.push_back(pudu::mkNote(pudu::mkPitch('G', 0, 3), "quarter", 0, 5, 0, 2));
    pudu::Part part = pudu::mkPart("P1", "Piano", 0, 4, 4, {m1, m2}, /*staves=*/2);
    s.parts.push_back(part);
    return s;
}

TEST(grand_auto_single_part_multi_staff) {
    auto score = mkGrandScore();
    auto doc = pudu::staffToJianpu(score);
    // 两 voice → 两行；各行谱表透传正确
    EXPECT_EQ(doc.lines.size(), 2u);
    // 找到上行(staff=1) 与下行(staff=2)
    int hasUp = 0, hasDown = 0;
    for (const auto& l : doc.lines) {
        if (l.staff == 1) hasUp = 1;
        if (l.staff == 2) hasDown = 1;
    }
    EXPECT_EQ(hasUp, 1);
    EXPECT_EQ(hasDown, 1);

    // 默认 auto → 大谱表：花括号 + system-grand + 行标签
    std::string body = l2Body(doc, pudu::JianpuRenderConfig{});
    EXPECT_GT(countOcc(body, "system-grand"), 0u);
    EXPECT_GT(countOcc(body, "class=\"grand-brace\""), 0u);
    EXPECT_GT(countOcc(body, "class=\"grand-grid\""), 0u);
}

TEST(grand_auto_disabled_normal_lines) {
    auto score = mkGrandScore();
    auto doc = pudu::staffToJianpu(score);
    pudu::JianpuRenderConfig cfg;
    cfg.autoGrandStaff = false;     // --no-grand-staff-auto
    std::string body = l2Body(doc, cfg);
    EXPECT_EQ(countOcc(body, "system-grand"), 0u);
    EXPECT_EQ(countOcc(body, "class=\"grand-brace\""), 0u);
}

TEST(grand_manual_pair_two_parts) {
    // 两个平行 part（无 <staff> 标签），手动 --grand-staff 0,1 配对
    pudu::Score s;
    pudu::Measure a, b;
    a.number = 1; b.number = 1;
    a.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 5), "quarter", 0));  // part0 上行
    b.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 3), "quarter", 0));  // part1 下行
    s.parts.push_back(pudu::mkPart("P1", "RH", 0, 4, 4, {a}));
    s.parts.push_back(pudu::mkPart("P2", "LH", 0, 4, 4, {b}));
    auto doc = pudu::staffToJianpu(s);
    EXPECT_EQ(doc.lines.size(), 2u);

    pudu::JianpuRenderConfig paired;
    paired.grandStaffPairs.push_back({0, 1});
    std::string body = l2Body(doc, paired);
    EXPECT_GT(countOcc(body, "system-grand"), 0u);

    pudu::JianpuRenderConfig unpaired;
    EXPECT_EQ(countOcc(l2Body(doc, unpaired), "system-grand"), 0u);
}

TEST(grand_not_triggered_single_staff) {
    // 单 part 单谱表（无 staff≥2）→ 绝不自动成大谱表
    auto doc = mkDoc(2, 4);
    for (auto& l : doc.lines) l.staff = 0;
    std::string body = l2Body(doc, pudu::JianpuRenderConfig{});
    EXPECT_EQ(countOcc(body, "system-grand"), 0u);
}

TEST(parser_reads_staff_and_staves) {
    static const char* XML =
        "<score-partwise><part-list><score-part id=\"P1\"><part-name>Piano</part-name></score-part></part-list>"
        "<part id=\"P1\">"
        "<measure number=\"1\"><attributes><divisions>2</divisions><time><beats>4</beats><beat-type>4</beat-type></time>"
        "<staves>2</staves><clef><sign>G</sign><line>2</line></clef></attributes>"
        "<note><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><staff>1</staff><type>quarter</type></note>"
        "<note><pitch><step>C</step><octave>3</octave></pitch><duration>2</duration><voice>5</voice><staff>2</staff><type>quarter</type></note>"
        "</measure>"
        "</part></score-partwise>";
    pudu::Score score;
    pudu::MusicXMLParser parser;
    std::string err;
    EXPECT_TRUE(parser.parseString(XML, score, err));
    EXPECT_FALSE(score.parts.empty());
    // <staves> 已解析
    EXPECT_EQ(score.parts[0].attributes.staves, 2);
    // <staff> 已透传到 Note（上行/下行各一）
    bool sawStaff1 = false, sawStaff2 = false;
    for (const auto& m : score.parts[0].measures)
        for (const auto& n : m.notes) {
            if (n.staff == 1) sawStaff1 = true;
            if (n.staff == 2) sawStaff2 = true;
        }
    EXPECT_TRUE(sawStaff1);
    EXPECT_TRUE(sawStaff2);
}