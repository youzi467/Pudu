// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段1 OMR 黑盒集成 · ctest 集成用例 (M2-3)
//
// 验证"OMR 产出 -> MusicXMLParser -> staffToJianpu -> 简谱结果"全链路。
// 使用 fixture 引擎（C++ 原生，确定性、零外部依赖），不依赖真 OMR 重引擎/网络，
// 从而 ctest 在任何环境均可确定性通过；真引擎（oemer）走同一 omr_adapter 契约。
//
// 注意：pudu_test 框架的 EXPECT_* 不支持 `<<` 流式附加信息，断言仅用基础形式。
// ----------------------------------------------------------------------

#include "pudu_test.hpp"

#include "omr_adapter.hpp"
#include "musicxml_parser.hpp"
#include "jianpu_converter.hpp"
#include "jianpu_model.hpp"
#include "score_model.hpp"

#include <string>

namespace {

// 统计一份 JianpuDoc 的总音符数（含休止）
int countNotes(const pudu::JianpuDoc& doc) {
    int n = 0;
    for (const auto& line : doc.lines)
        for (const auto& m : line.measures)
            n += static_cast<int>(m.notes.size());
    return n;
}

} // namespace

// M2-3-1：fixture 引擎可运行并产出合法 MusicXML 文件
TEST(omr_adapter_fixture_engine_produces_musicxml) {
    pudu::OmrEngineConfig cfg;
    cfg.engine = "fixture";
    std::string out = "test_omr_fixture_out.musicxml";
    std::string err;
    bool ok = pudu::runOmr("dummy_input.png", out, cfg, err);
    EXPECT_TRUE(ok);
    if (ok) {
        // 产物应存在且含 score-partwise 根（adapter 已校验，这里再确认可被解析器加载）
        pudu::Score score;
        pudu::MusicXMLParser parser;
        std::string perr;
        EXPECT_TRUE(parser.loadFromFile(out, score, perr));
    }
}

// M2-3-2：全链路串通（OMR 产出 -> 解析 -> 简谱结果断言）
TEST(omr_adapter_fixture_full_pipeline) {
    pudu::OmrEngineConfig cfg;
    cfg.engine = "fixture";
    std::string out = "test_omr_pipeline.musicxml";
    std::string err;
    EXPECT_TRUE(pudu::runOmr("dummy.png", out, cfg, err));

    pudu::Score score;
    pudu::MusicXMLParser parser;
    std::string perr;
    EXPECT_TRUE(parser.loadFromFile(out, score, perr));
    EXPECT_FALSE(score.isEmpty());

    pudu::JianpuDoc doc = pudu::staffToJianpu(score);
    EXPECT_FALSE(doc.lines.empty());
    EXPECT_FALSE(doc.lines[0].measures.empty());
    EXPECT_FALSE(doc.lines[0].measures[0].notes.empty());

    // fixture 样例为 C 大调 4/4 "小星星"前两句：共 7 音，首音为 do(1)
    EXPECT_EQ(countNotes(doc), 7);
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 1);
    EXPECT_EQ(doc.beats, 4);
    EXPECT_EQ(doc.beatType, 4);
}

// M2-1 派生：fixture 引擎始终可用（isOmrEngineAvailable 恒 true）
TEST(omr_adapter_fixture_always_available) {
    pudu::OmrEngineConfig cfg;
    cfg.engine = "fixture";
    std::string detail;
    EXPECT_TRUE(pudu::isOmrEngineAvailable(cfg, detail));
}

// 边界：未知引擎名应安全失败（不崩溃，返回 false）
TEST(omr_adapter_unknown_engine_fails) {
    pudu::OmrEngineConfig cfg;
    cfg.engine = "no_such_engine";
    std::string out = "x.musicxml";
    std::string err;
    EXPECT_FALSE(pudu::runOmr("in", out, cfg, err));
}
