// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 3 序列化自洽测试（G2）
// Score -> MusicXML -> 解析回 Score，语义应等价（需 pugixml，仅 MSVC 构建编译）。
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_to_staff.hpp"
#include "musicxml_parser.hpp"
#include "score_model.hpp"
#include "jianpu_model.hpp"
#include "test_helpers.hpp"

#include <vector>

using namespace pudu;

TEST(serializer_roundtrip_equivalence) {
    // 构造单声部 C 大调旋律（含二分/四分/八分与附点）
    Measure m1, m2;
    m1.number = 1; m2.number = 2;
    m1.notes = { mkNote(mkPitch('C', 0, 4), "quarter", 0),
                 mkNote(mkPitch('E', 0, 4), "quarter", 1),
                 mkNote(mkPitch('G', 0, 4), "half",   2, 1, 1) }; // 附点二分
    m2.notes = { mkNote(mkPitch('A', 0, 4), "eighth", 0),
                 mkNote(mkPitch('B', 0, 4), "eighth", 1),
                 mkNote(mkPitch('C', 0, 5), "quarter", 2) };
    Score orig = mkScore(0, "major", 4, 4, {m1, m2}, "serialize-test");

    // G2：写出
    std::string xml = scoreToMusicXML(orig);
    EXPECT_TRUE(!xml.empty());

    // 解析回
    MusicXMLParser parser;
    Score back;
    std::string err;
    bool ok = parser.parseString(xml, back, err);
    EXPECT_TRUE(ok);
    if (!ok) { std::cerr << "[serializer] parse error: " << err << std::endl; return; }

    // 比对待还原：声部数 / 标题 / 全局属性
    EXPECT_EQ(back.parts.size(), 1);
    EXPECT_EQ(back.title, "serialize-test");
    EXPECT_EQ(back.parts[0].attributes.fifths, 0);
    EXPECT_EQ(back.parts[0].attributes.beats, 4);
    EXPECT_EQ(back.parts[0].attributes.beatType, 4);

    // 比对音高序列（step/alter/octave）
    auto flatten = [](const Score& sc, std::vector<Pitch>& out) {
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
