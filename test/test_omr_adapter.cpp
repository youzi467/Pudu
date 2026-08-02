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
#include <fstream>
#include <sstream>

namespace {

// 统计一份 JianpuDoc 的总音符数（含休止）
int countNotes(const pudu::JianpuDoc& doc) {
    int n = 0;
    for (const auto& line : doc.lines)
        for (const auto& m : line.measures)
            n += static_cast<int>(m.notes.size());
    return n;
}

// 读整个文件为字符串（用于逐字节比对产物）；读不到返回空串
std::string slurp(const std::string& path) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) return std::string();
    std::ostringstream oss;
    oss << ifs.rdbuf();
    return oss.str();
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

// ---------------------------------------------------------------- P0-2 回归
// P0-2-C1：OmrEngineConfig.preprocess 默认必须为 false（no-op 红线：默认关）。
// 任何把默认改成 true 的改动都会让"开关关时链路与 P0-2 之前一致"的承诺失效。
TEST(omr_adapter_preprocess_defaults_off) {
    pudu::OmrEngineConfig cfg;
    EXPECT_FALSE(cfg.preprocess);
}

// P0-2-C2：preprocess 开关不得影响 fixture 引擎——两次产出应逐字节一致。
// fixture 是 C++ 原生分支（在 oemer 分支之前 return），preprocess 对它必须完全透明。
TEST(omr_adapter_preprocess_transparent_for_fixture) {
    pudu::OmrEngineConfig off;
    off.engine = "fixture";
    off.preprocess = false;
    std::string outOff = "test_omr_pre_off.musicxml";
    std::string errOff;
    EXPECT_TRUE(pudu::runOmr("dummy.png", outOff, off, errOff));

    pudu::OmrEngineConfig on;
    on.engine = "fixture";
    on.preprocess = true;
    std::string outOn = "test_omr_pre_on.musicxml";
    std::string errOn;
    EXPECT_TRUE(pudu::runOmr("dummy.png", outOn, on, errOn));

    std::string a = slurp(outOff);
    std::string b = slurp(outOn);
    EXPECT_FALSE(a.empty());
    EXPECT_TRUE(a == b);

    // 简谱侧结果同样不受影响（全链路等价）
    pudu::Score s1, s2;
    pudu::MusicXMLParser p1, p2;
    std::string e1, e2;
    EXPECT_TRUE(p1.loadFromFile(outOff, s1, e1));
    EXPECT_TRUE(p2.loadFromFile(outOn, s2, e2));
    EXPECT_EQ(countNotes(pudu::staffToJianpu(s1)),
              countNotes(pudu::staffToJianpu(s2)));
}

// P0-2-C3：preprocess=true 不改变 oemer 分支的前置校验语义
// （toolsDir 为空仍应安全失败，而不是拼出半截命令去起子进程）。
TEST(omr_adapter_preprocess_requires_tools_dir) {
    pudu::OmrEngineConfig cfg;
    cfg.engine = "oemer";
    cfg.toolsDir = "";
    cfg.preprocess = true;
    std::string err;
    EXPECT_FALSE(pudu::runOmr("in.png", "out.musicxml", cfg, err));
    EXPECT_FALSE(err.empty());

    cfg.preprocess = false;
    std::string err2;
    EXPECT_FALSE(pudu::runOmr("in.png", "out.musicxml", cfg, err2));
    EXPECT_TRUE(err == err2);   // 开关不改变失败诊断
}
