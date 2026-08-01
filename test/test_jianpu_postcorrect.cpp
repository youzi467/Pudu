// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：P1-1 后处理音乐规则引擎（jianpu_postcorrect）
//
// 覆盖：
//   0. 总开关关闭 -> 完全 no-op
//   1. ★ 不变量红线：干净 4/4 旋律 -> applied/flagged 均空、逐音字段不变
//   2. BeatReconcile 自修（唯一归责）
//   3. BeatReconcile 歧义 -> 仅标记
//   4. OctaveDot 大跨度跳变 -> 仅标记
//   5. Accidental 冗余记号移除（G 大调 #7）
//   6. RestFill 占拍不足且不可解 -> 仅标记
//   7. postCorrectReportToJson 基本结构
//
// 被测函数：correctJianpuDoc、postCorrectReportToJson
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"
#include "jianpu_postcorrect.hpp"
#include "musicxml_parser.hpp"   // P1-1 语料回归：直接加载出版级 GT 谱
#include "test_helpers.hpp"

#include <fstream>
#include <string>
#include <vector>

using namespace pudu;

namespace {

// test_helpers.hpp 的 mkNote 不填 quarterLength（默认 0.0），会让
// staffToJianpu 认为时值未解析（rhythmUnresolvable=true）。本套用例需要
// "干净输入"，故统一走这个包装：显式补齐 quarterLength。
Note mkQ(char step, int alter, int octave, const std::string& type,
         int onset, double ql, int voice = 1, int dots = 0) {
    Note n = mkNote(mkPitch(step, alter, octave), type, onset, voice, dots);
    n.quarterLength = ql;
    return n;
}

Note mkRestQ(const std::string& type, int onset, double ql, int voice = 1) {
    Note n = mkRest(type, onset, voice);
    n.quarterLength = ql;
    return n;
}

// 默认开启的引擎配置（与 main.cpp 的 --apply-postcorrect 口径一致）
PostCorrectConfig enabledCfg() {
    PostCorrectConfig cfg;
    cfg.enabled = true;
    cfg.autoFixBeatOverflow = true;
    return cfg;
}

// 逐音字段比对（不变量测试用；覆盖 JianpuNote 全部语义字段）
bool sameNote(const JianpuNote& a, const JianpuNote& b) {
    return a.degree == b.degree &&
           a.octaveDots == b.octaveDots &&
           a.accidental == b.accidental &&
           a.underlines == b.underlines &&
           a.augmentDashes == b.augmentDashes &&
           a.dots == b.dots &&
           a.onset == b.onset &&
           a.tieToNext == b.tieToNext &&
           a.tieFromPrev == b.tieFromPrev &&
           a.isGrace == b.isGrace &&
           a.tuplet == b.tuplet &&
           a.chordDegrees == b.chordDegrees &&
           a.chordOctaveDots == b.chordOctaveDots &&
           a.rhythmUnresolvable == b.rhythmUnresolvable;
}

bool sameDoc(const JianpuDoc& a, const JianpuDoc& b) {
    if (a.title != b.title || a.tonicLabel != b.tonicLabel || a.mode != b.mode) return false;
    if (a.beats != b.beats || a.beatType != b.beatType || a.fifths != b.fifths) return false;
    if (a.lines.size() != b.lines.size()) return false;
    for (size_t li = 0; li < a.lines.size(); ++li) {
        const JianpuLine& la = a.lines[li];
        const JianpuLine& lb = b.lines[li];
        if (la.voice != lb.voice || la.partIndex != lb.partIndex) return false;
        if (la.measures.size() != lb.measures.size()) return false;
        for (size_t mi = 0; mi < la.measures.size(); ++mi) {
            const JianpuMeasure& ma = la.measures[mi];
            const JianpuMeasure& mb = lb.measures[mi];
            if (ma.number != mb.number) return false;
            if (ma.notes.size() != mb.notes.size()) return false;
            for (size_t ni = 0; ni < ma.notes.size(); ++ni)
                if (!sameNote(ma.notes[ni], mb.notes[ni])) return false;
        }
    }
    return true;
}

int countKind(const std::vector<Correction>& v, CorrectionKind k) {
    int c = 0;
    for (const auto& x : v) if (x.kind == k) ++c;
    return c;
}

const Correction* findKind(const std::vector<Correction>& v, CorrectionKind k) {
    for (const auto& x : v) if (x.kind == k) return &x;
    return nullptr;
}

// 干净的小星星片段（C 大调 4/4，两小节各严格 4 拍）
JianpuDoc cleanTwinkleDoc() {
    Measure m1; m1.number = 1;
    m1.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m1.notes.push_back(mkQ('C', 0, 4, "quarter", 1, 1.0));
    m1.notes.push_back(mkQ('G', 0, 4, "quarter", 2, 1.0));
    m1.notes.push_back(mkQ('G', 0, 4, "quarter", 3, 1.0));

    Measure m2; m2.number = 2;
    m2.notes.push_back(mkQ('A', 0, 4, "quarter", 4, 1.0));
    m2.notes.push_back(mkQ('A', 0, 4, "quarter", 5, 1.0));
    m2.notes.push_back(mkQ('G', 0, 4, "half",    6, 2.0));

    Score s = mkScore(0, "major", 4, 4, {m1, m2}, "小星星片段");
    return staffToJianpu(s);
}

// P1-1：在若干候选前缀下解析 data/ 路径，适配不同 ctest 工作目录
std::string resolveDataPath(const std::string& rel) {
    const char* prefixes[] = {"", "../", "../../", "../../../", "../../../../"};
    for (const char* p : prefixes) {
        std::ifstream f(std::string(p) + rel);
        if (f.good()) return std::string(p) + rel;
    }
    return rel;  // 退回原样，交由解析器报错（测试会捕获 err 非空）
}

// 直接构造单声部单行的 JianpuDoc（绕过 Score），用于测试 BeatReconcile 的
// 连音 / 变拍号路径（这些路径无需经 MusicXML 解析即可聚焦验证）。
JianpuDoc buildSingleLineDoc(int beats, int beatType) {
    JianpuDoc doc;
    doc.beats = beats;
    doc.beatType = beatType;
    JianpuLine line;
    line.voice = 1;
    line.partIndex = 0;
    doc.lines.push_back(line);
    return doc;
}

} // anonymous namespace

// ======================================================================
// 0. 总开关：enabled=false 时完全 no-op
// ======================================================================

TEST(postcorrect_disabled_is_pure_noop) {
    JianpuDoc doc = cleanTwinkleDoc();
    PostCorrectConfig cfg;              // enabled 默认 false
    PostCorrectReport rep;
    JianpuDoc out;
    EXPECT_NO_THROW(out = correctJianpuDoc(doc, cfg, rep));
    EXPECT_TRUE(rep.applied.empty());
    EXPECT_TRUE(rep.flagged.empty());
    EXPECT_EQ(rep.measuresReconciled, 0);
    EXPECT_EQ(rep.notesTouched, 0);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 1. ★ 不变量红线：干净输入必须 0 修正、0 标记、文档逐音不变
// ======================================================================

TEST(postcorrect_clean_input_is_noop) {
    JianpuDoc doc = cleanTwinkleDoc();

    // 前置健全性：确认这份 fixture 确实是"干净"的（时值全部解析成功）
    for (const auto& m : doc.lines[0].measures)
        for (const auto& n : m.notes)
            EXPECT_FALSE(n.rhythmUnresolvable);

    PostCorrectReport rep;
    JianpuDoc out;
    EXPECT_NO_THROW(out = correctJianpuDoc(doc, enabledCfg(), rep));

    EXPECT_EQ(rep.applied.size(), 0u);        // 一处都不许自修
    EXPECT_EQ(rep.flagged.size(), 0u);        // 一处都不许标记
    EXPECT_EQ(rep.measuresReconciled, 0);
    EXPECT_EQ(rep.notesTouched, 0);
    EXPECT_TRUE(sameDoc(doc, out));           // 逐音字段完全一致
}

// 干净输入下含休止符 / 三连音 / 弱起小节，同样必须 no-op
TEST(postcorrect_clean_input_with_rest_and_triplet_is_noop) {
    // 小节 1（弱起）：只有 1 拍，属合法不完全小节
    Measure m1; m1.number = 1;
    m1.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));

    // 小节 2：三连音八分 ×3（合计 1 拍）+ 四分休止 + 二分
    Measure m2; m2.number = 2;
    for (int i = 0; i < 3; ++i) {
        Note t = mkQ('E', 0, 4, "eighth", 1, 1.0 / 3.0);
        t.tupletActual = 3;
        t.tupletNormal = 2;
        m2.notes.push_back(t);
    }
    m2.notes.push_back(mkRestQ("quarter", 2, 1.0));
    m2.notes.push_back(mkQ('G', 0, 4, "half", 3, 2.0));

    Score s = mkScore(0, "major", 4, 4, {m1, m2}, "弱起+三连音");
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 2. BeatReconcile：唯一归责 -> 自动修正
// ======================================================================

TEST(postcorrect_beat_reconcile_autofix_unique_candidate) {
    // 4/4 小节塞进 5 拍：四分 ×3 + 二分。
    // 只有那个二分音符改成四分（2.0 -> 1.0）能精确归零 -> 唯一归责 -> 自修。
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('D', 0, 4, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('E', 0, 4, "quarter", 2, 1.0));
    m.notes.push_back(mkQ('F', 0, 4, "half",    3, 2.0));
    Score s = mkScore(0, "major", 4, 4, {m}, "溢出小节");
    JianpuDoc doc = staffToJianpu(s);

    // 前置：确认构造出来的确实是 5 拍
    EXPECT_EQ(doc.lines[0].measures[0].notes.size(), 4u);
    EXPECT_EQ(doc.lines[0].measures[0].notes[3].augmentDashes, 1);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(rep.applied.size(), 1u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_EQ(rep.measuresReconciled, 1);
    EXPECT_EQ(rep.notesTouched, 1);

    const Correction* c = findKind(rep.applied, CorrectionKind::BeatReconcile);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_EQ(c->kind, CorrectionKind::BeatReconcile);
        EXPECT_EQ(c->noteIndex, 3);
        EXPECT_EQ(c->measure, 1);
        EXPECT_EQ(c->part, 0);
        EXPECT_EQ(c->voice, 1);
        EXPECT_TRUE(c->confidence >= 1.0);
        EXPECT_TRUE(!c->reason.empty());
        EXPECT_TRUE(c->before != c->after);
    }

    // 修正后该音变为四分音符，小节归零
    const JianpuNote& fixed = out.lines[0].measures[0].notes[3];
    EXPECT_EQ(fixed.augmentDashes, 0);
    EXPECT_EQ(fixed.underlines, 0);
    EXPECT_EQ(fixed.dots, 0);
    // 其余音符不受影响
    EXPECT_EQ(out.lines[0].measures[0].notes[0].augmentDashes, 0);
    EXPECT_EQ(out.lines[0].measures[0].notes[0].degree, 1);

    // 幂等性：对已归零的结果再跑一次，应完全 no-op
    PostCorrectReport rep2;
    JianpuDoc out2 = correctJianpuDoc(out, enabledCfg(), rep2);
    EXPECT_EQ(rep2.applied.size(), 0u);
    EXPECT_EQ(rep2.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(out, out2));
}

// autoFixBeatOverflow=false 时同一场景只标记不自修
TEST(postcorrect_beat_reconcile_flag_only_when_autofix_disabled) {
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('D', 0, 4, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('E', 0, 4, "quarter", 2, 1.0));
    m.notes.push_back(mkQ('F', 0, 4, "half",    3, 2.0));
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectConfig cfg = enabledCfg();
    cfg.autoFixBeatOverflow = false;
    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, cfg, rep);

    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::BeatReconcile), 1);
    EXPECT_EQ(rep.measuresReconciled, 0);
    EXPECT_TRUE(sameDoc(doc, out));   // 未自修 -> 文档不变
}

// ======================================================================
// 3. BeatReconcile：多候选歧义 -> 仅标记
// ======================================================================

TEST(postcorrect_beat_reconcile_ambiguous_only_flags) {
    // 4/4 塞进 5 拍：二分 + 二分 + 四分。
    // 两个二分音符各自改成四分都能归零 -> 无法无歧义归责 -> 仅标记。
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "half",    0, 2.0));
    m.notes.push_back(mkQ('D', 0, 4, "half",    2, 2.0));
    m.notes.push_back(mkQ('E', 0, 4, "quarter", 4, 1.0));
    Score s = mkScore(0, "major", 4, 4, {m}, "歧义小节");
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.measuresReconciled, 0);
    EXPECT_EQ(rep.notesTouched, 0);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::BeatReconcile), 1);

    const Correction* c = findKind(rep.flagged, CorrectionKind::BeatReconcile);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_TRUE(c->confidence < 1.0);
        EXPECT_EQ(c->noteIndex, -1);       // 小节级标记
        EXPECT_EQ(c->measure, 1);
    }
    EXPECT_TRUE(sameDoc(doc, out));        // 歧义场景绝不改文档
}

// ======================================================================
// 4. OctaveDot：跨 2 个八度的跳变 -> 仅标记
// ======================================================================

TEST(postcorrect_octave_dot_large_jump_flagged) {
    // P1-1 返工：只有【孤立尖刺】才判为八度点误识，故 fixture 必须真正跳出又跳回。
    //   C4 -> C6 -> C4：两跳各 24 半音，且首尾同音区 => 违反旋律连续性，
    //   正是 oemer 八度点加错的典型症状。小节仍严格 4 拍，无 BeatReconcile 干扰。
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('C', 0, 6, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('C', 0, 4, "half",    2, 2.0));
    Score s = mkScore(0, "major", 4, 4, {m}, "八度尖刺");
    JianpuDoc doc = staffToJianpu(s);

    // 前置：确认八度点确实是 0 / +2 / 0
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].octaveDots, 0);
    EXPECT_EQ(doc.lines[0].measures[0].notes[1].octaveDots, 2);
    EXPECT_EQ(doc.lines[0].measures[0].notes[2].octaveDots, 0);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(rep.applied.size(), 0u);                                  // 保守：不自修
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::OctaveDot), 1);

    const Correction* c = findKind(rep.flagged, CorrectionKind::OctaveDot);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_EQ(c->kind, CorrectionKind::OctaveDot);
        EXPECT_EQ(c->noteIndex, 1);        // 标记在跳到的那个音上
        EXPECT_TRUE(c->confidence < 1.0);
    }
    EXPECT_TRUE(sameDoc(doc, out));        // 真实八度不可恢复 -> 不改文档
}

// flagOctaveJumps=false 时该规则整体关闭
TEST(postcorrect_octave_dot_rule_can_be_disabled) {
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('C', 0, 6, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('C', 0, 4, "half",    2, 2.0));
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectConfig cfg = enabledCfg();
    cfg.flagOctaveJumps = false;
    PostCorrectReport rep;
    correctJianpuDoc(doc, cfg, rep);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::OctaveDot), 0);
}

// ======================================================================
// 5. Accidental：冗余于调号的临时记号 -> trivially-safe 自修
// ======================================================================

TEST(postcorrect_accidental_redundant_sharp_removed) {
    // G 大调(fifths=1)：F#4 正常转换为 音级 7 / accidental=None。
    // 模拟 oemer 把调号升号误挂到音头上 -> 给音级 7 加一个多余的 Sharp。
    Measure m; m.number = 1;
    for (int i = 0; i < 4; ++i)
        m.notes.push_back(mkQ('F', 1, 4, "quarter", i, 1.0));
    Score s = mkScore(1, "major", 4, 4, {m}, "G大调冗余升号");
    JianpuDoc doc = staffToJianpu(s);

    // 前置：确认干净转换的确是 7 / None
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 7);
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].accidental, Accidental::None);
    EXPECT_EQ(doc.fifths, 1);

    // 注入错误
    doc.lines[0].measures[0].notes[0].accidental = Accidental::Sharp;

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(countKind(rep.applied, CorrectionKind::Accidental), 1);
    const Correction* c = findKind(rep.applied, CorrectionKind::Accidental);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_EQ(c->kind, CorrectionKind::Accidental);
        EXPECT_EQ(c->noteIndex, 0);
        EXPECT_EQ(c->measure, 1);
        EXPECT_TRUE(c->confidence >= 1.0);
    }
    EXPECT_EQ(out.lines[0].measures[0].notes[0].accidental, Accidental::None);
    EXPECT_EQ(out.lines[0].measures[0].notes[0].degree, 7);   // 音级不动
    EXPECT_EQ(rep.notesTouched, 1);
}

// 无可还原对象的还原号同样属"干净转换不可达"，安全移除
TEST(postcorrect_accidental_stray_natural_removed) {
    Measure m; m.number = 1;
    for (int i = 0; i < 4; ++i)
        m.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0));
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    doc.lines[0].measures[0].notes[2].accidental = Accidental::Natural;

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(countKind(rep.applied, CorrectionKind::Accidental), 1);
    EXPECT_EQ(out.lines[0].measures[0].notes[2].accidental, Accidental::None);
}

// enforceKeyConsistency=false 时该规则整体关闭
TEST(postcorrect_accidental_rule_can_be_disabled) {
    Measure m; m.number = 1;
    for (int i = 0; i < 4; ++i)
        m.notes.push_back(mkQ('F', 1, 4, "quarter", i, 1.0));
    Score s = mkScore(1, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);
    doc.lines[0].measures[0].notes[0].accidental = Accidental::Sharp;

    PostCorrectConfig cfg = enabledCfg();
    cfg.enforceKeyConsistency = false;
    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, cfg, rep);

    EXPECT_EQ(countKind(rep.applied, CorrectionKind::Accidental), 0);
    EXPECT_EQ(out.lines[0].measures[0].notes[0].accidental, Accidental::Sharp);
}

// ======================================================================
// 6. RestFill：占拍不足且不可解 -> 仅标记（绝不臆造休止）
// ======================================================================

TEST(postcorrect_rest_fill_flags_unresolvable_deficit) {
    // 小节 1 干净 4 拍（保证不被当作弱起）；
    // 小节 2 只有两个八分（共 1 拍），缺 3 拍。
    // 任何"单音一步"最多只能把八分变成四分附点(0.75)，无法补足 3 拍 -> RestFill。
    Measure m1; m1.number = 1;
    for (int i = 0; i < 4; ++i)
        m1.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0));

    Measure m2; m2.number = 2;
    m2.notes.push_back(mkQ('C', 0, 4, "eighth", 4, 0.5));
    m2.notes.push_back(mkQ('D', 0, 4, "eighth", 5, 0.5));

    Score s = mkScore(0, "major", 4, 4, {m1, m2}, "缺拍小节");
    JianpuDoc doc = staffToJianpu(s);

    // 前置：确认两个八分确实是 underlines=1
    EXPECT_EQ(doc.lines[0].measures[1].notes[0].underlines, 1);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::RestFill), 1);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::BeatReconcile), 0);  // 不重复计

    const Correction* c = findKind(rep.flagged, CorrectionKind::RestFill);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_EQ(c->kind, CorrectionKind::RestFill);
        EXPECT_EQ(c->measure, 2);
        EXPECT_EQ(c->noteIndex, -1);
        EXPECT_TRUE(c->confidence < 1.0);
    }
    // 绝不臆造：音符数量不变
    EXPECT_EQ(out.lines[0].measures[1].notes.size(), 2u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 7. TupletGroup：成员数不成组 -> 仅标记
// ======================================================================

TEST(postcorrect_tuplet_group_incomplete_flagged) {
    // 三连音八分只识别出 2 个（漏识 1 个）+ 二分 + 四分：
    //   占拍 = 0.5×2/3 ×2 + 2.0 + 1.0 = 3.6667（不足），
    //   但重点断言的是 TupletGroup 结构性标记。
    Measure m; m.number = 1;
    for (int i = 0; i < 2; ++i) {
        Note t = mkQ('E', 0, 4, "eighth", 0, 1.0 / 3.0);
        t.tupletActual = 3;
        t.tupletNormal = 2;
        m.notes.push_back(t);
    }
    m.notes.push_back(mkQ('G', 0, 4, "half",    1, 2.0));
    m.notes.push_back(mkQ('A', 0, 4, "quarter", 3, 1.0));
    Score s = mkScore(0, "major", 4, 4, {m}, "残缺三连音");
    JianpuDoc doc = staffToJianpu(s);

    EXPECT_EQ(doc.lines[0].measures[0].notes[0].tuplet, 3);

    PostCorrectReport rep;
    correctJianpuDoc(doc, enabledCfg(), rep);

    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::TupletGroup), 1);
    const Correction* c = findKind(rep.flagged, CorrectionKind::TupletGroup);
    EXPECT_TRUE(c != nullptr);
    if (c) {
        EXPECT_EQ(c->noteIndex, 0);
        EXPECT_TRUE(c->confidence < 1.0);
    }
}

// ======================================================================
// 8. postCorrectReportToJson：结构完整、可被脚本解析
// ======================================================================

TEST(postcorrect_report_json_structure) {
    Measure m; m.number = 1;
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('D', 0, 4, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('E', 0, 4, "quarter", 2, 1.0));
    m.notes.push_back(mkQ('F', 0, 4, "half",    3, 2.0));
    Score s = mkScore(0, "major", 4, 4, {m});
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectReport rep;
    correctJianpuDoc(doc, enabledCfg(), rep);

    std::string json;
    EXPECT_NO_THROW(json = postCorrectReportToJson(rep));
    EXPECT_TRUE(json.front() == '{' && json.back() == '}');
    EXPECT_TRUE(json.find("\"measuresReconciled\":1") != std::string::npos);
    EXPECT_TRUE(json.find("\"notesTouched\":1") != std::string::npos);
    EXPECT_TRUE(json.find("\"appliedCount\":1") != std::string::npos);
    EXPECT_TRUE(json.find("\"flaggedCount\":0") != std::string::npos);
    EXPECT_TRUE(json.find("\"applied\":[") != std::string::npos);
    EXPECT_TRUE(json.find("\"flagged\":[]") != std::string::npos);
    EXPECT_TRUE(json.find("\"kind\":\"BeatReconcile\"") != std::string::npos);
    EXPECT_TRUE(json.find("\"confidence\":1.000") != std::string::npos);
    EXPECT_TRUE(json.find("\"noteIndex\":3") != std::string::npos);
    EXPECT_TRUE(json.find("\"reason\":\"") != std::string::npos);
}

// 空报告也要输出合法 JSON 骨架
TEST(postcorrect_report_json_empty_safe) {
    PostCorrectReport rep;
    std::string json;
    EXPECT_NO_THROW(json = postCorrectReportToJson(rep));
    EXPECT_TRUE(json.find("\"applied\":[]") != std::string::npos);
    EXPECT_TRUE(json.find("\"flagged\":[]") != std::string::npos);
    EXPECT_TRUE(json.find("\"measuresReconciled\":0") != std::string::npos);
    EXPECT_TRUE(json.front() == '{' && json.back() == '}');
}

// 空文档 / 空小节：不崩溃、不误报
TEST(postcorrect_empty_doc_safe) {
    JianpuDoc doc;
    PostCorrectReport rep;
    JianpuDoc out;
    EXPECT_NO_THROW(out = correctJianpuDoc(doc, enabledCfg(), rep));
    EXPECT_TRUE(rep.applied.empty());
    EXPECT_TRUE(rep.flagged.empty());
    EXPECT_TRUE(out.lines.empty());
}

TEST(postcorrect_empty_measure_is_skipped) {
    JianpuDoc doc;
    doc.beats = 4;
    doc.beatType = 4;
    JianpuLine line;
    line.voice = 1;
    line.partIndex = 0;
    JianpuMeasure m;
    m.number = 1;               // 无音符
    line.measures.push_back(m);
    doc.lines.push_back(line);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_TRUE(rep.applied.empty());
    EXPECT_TRUE(rep.flagged.empty());
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 9. P1-1 返工：连音组非三连音比（tupletNormal 透传）也必须 no-op
// ======================================================================

// 12/8（target = 12×4/8 = 6.0）：8 个二连音八分(2:3)，每音 0.5×3/2 = 0.75，合计 6.0。
// 旧实现用 tupletNormalFor(2)=1 会错算成 0.25/音 -> 触发误改写；修复后精确归零。
TEST(postcorrect_tuplet_duplet_12_8_noop) {
    JianpuDoc doc = buildSingleLineDoc(12, 8);
    JianpuMeasure m; m.number = 1;
    for (int i = 0; i < 8; ++i) {
        JianpuNote n;
        n.degree = 1 + (i % 7);
        n.underlines = 1;   // eighth
        n.tuplet = 2;        // 二连音
        n.tupletNormal = 3;  // 2:3（normal-notes=3）
        m.notes.push_back(n);
    }
    doc.lines[0].measures.push_back(m);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// 6/8（target = 6×4/8 = 3.0）：8 个四连音八分(4:3)，每音 0.5×3/4 = 0.375，合计 3.0。
// 旧实现用 tupletNormalFor(4)=2 会错算成 0.25/音 -> 触发误改写；修复后精确归零。
TEST(postcorrect_tuplet_quadruplet_6_8_noop) {
    JianpuDoc doc = buildSingleLineDoc(6, 8);
    JianpuMeasure m; m.number = 1;
    for (int i = 0; i < 8; ++i) {
        JianpuNote n;
        n.degree = 1 + (i % 7);
        n.underlines = 1;   // eighth
        n.tuplet = 4;        // 四连音
        n.tupletNormal = 3;  // 4:3（normal-notes=3）
        m.notes.push_back(n);
    }
    doc.lines[0].measures.push_back(m);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 10. P1-1 返工：曲中变拍号也必须 no-op（逐小节目标拍值）
// ======================================================================

TEST(postcorrect_mid_piece_time_change_noop) {
    Measure m1; m1.number = 1;  // 首小节：回退全局 4/4
    for (int i = 0; i < 4; ++i)
        m1.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0));
    Measure m2; m2.number = 2;
    m2.beats = 3; m2.beatType = 4;  // 曲中变拍号 -> 3/4
    for (int i = 0; i < 3; ++i)
        m2.notes.push_back(mkQ('D', 0, 4, "quarter", i, 1.0));

    Score s = mkScore(0, "major", 4, 4, {m1, m2}, "变拍号");
    JianpuDoc doc = staffToJianpu(s);

    // 前置：确认小节拍号已透传（首小节 0 回退全局，变拍小节 3 透传）
    EXPECT_EQ(doc.lines[0].measures[0].beats, 0);
    EXPECT_EQ(doc.lines[0].measures[1].beats, 3);
    EXPECT_EQ(doc.lines[0].measures[1].beatType, 4);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 11. P1-1 返工：多声部中途进入声部必须 no-op（多声部安全门）
// ======================================================================

TEST(postcorrect_multi_voice_late_entry_noop) {
    Score s;
    s.parts.emplace_back();
    s.parts[0].id = "P1"; s.parts[0].name = "P1";
    s.parts[0].attributes.fifths = 0; s.parts[0].attributes.mode = "major";
    s.parts[0].attributes.beats = 4; s.parts[0].attributes.beatType = 4;

    // voice 1：两小节各 4 个四分（干净满拍）
    Measure m1; m1.number = 1;
    for (int i = 0; i < 4; ++i) m1.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0, 1));
    Measure m2; m2.number = 2;
    for (int i = 0; i < 4; ++i) m2.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0, 1));

    // voice 2：中途进入（仅第 2 小节），且稀疏（2 个四分，仅占 2 拍）。
    // 若无安全门，该声部会被误判为"占拍不足"而触发 RestFill 标记。
    m2.notes.push_back(mkQ('G', 0, 4, "quarter", 0, 1.0, 2));
    m2.notes.push_back(mkQ('G', 0, 4, "quarter", 1, 1.0, 2));

    s.parts[0].measures.push_back(m1);
    s.parts[0].measures.push_back(m2);

    JianpuDoc doc = staffToJianpu(s);
    EXPECT_EQ(doc.lines.size(), 2u);  // 多声部 -> 多行

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    // 安全门：多声部稀疏声部 target 不可信，BeatReconcile 整条跳过 -> 0 改写 0 标记
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
}

// ======================================================================
// 11b. P1-1 返工·第二轮：出版记谱合法写法的 no-op 保证
//      以下四类都在真实 GT 谱上被实测到，且此前均产生误改写/误标记。
// ======================================================================

// (1) 段落边界的不完全小节（反复段末尾 / Fine 终止小节）——合法不足拍，不得归责。
//     对应 badinerie m16（2/4 里 1 拍 + 反向反复）与 m40（1 拍 + light-heavy）。
TEST(postcorrect_section_end_partial_measure_noop) {
    Measure m1; m1.number = 1;                       // 满拍，确保不被当作弱起
    for (int i = 0; i < 2; ++i)
        m1.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0));

    Measure m2; m2.number = 2;                       // 2/4 里只有 1 拍，但位于反复段末尾
    m2.notes.push_back(mkQ('E', 0, 4, "quarter", 2, 1.0));
    m2.sectionEnd = true;

    Score s = mkScore(0, "major", 2, 4, {m1, m2}, "反复段末尾不完全小节");
    JianpuDoc doc = staffToJianpu(s);
    EXPECT_TRUE(doc.lines[0].measures[1].sectionEnd);   // 字段确已透传

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// (1b) 但段落边界【溢出】仍必须被抓——豁免只针对"不足"，不得放大成万能免死金牌。
TEST(postcorrect_section_end_overflow_still_reconciled) {
    Measure m; m.number = 1;                         // 4/4 塞 5 拍，且带终止线
    for (int i = 0; i < 3; ++i)
        m.notes.push_back(mkQ('C', 0, 4, "quarter", i, 1.0));
    m.notes.push_back(mkQ('F', 0, 4, "half", 3, 2.0));
    m.sectionEnd = true;

    Score s = mkScore(0, "major", 4, 4, {m}, "终止小节溢出");
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectReport rep;
    correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(countKind(rep.applied, CorrectionKind::BeatReconcile), 1);
}

// (2) 装饰音不得被判为"时值未解析"——装饰音无 <duration>，ql 恒为 0 属正常。
TEST(postcorrect_grace_note_is_not_unresolvable_noop) {
    Measure m; m.number = 1;
    Note g = mkNote(mkPitch('D', 0, 5), "eighth", 0);
    g.isGrace = true;                                // 不设 quarterLength：模拟真实 <grace/>
    m.notes.push_back(g);
    for (int i = 0; i < 4; ++i)
        m.notes.push_back(mkQ('C', 0, 5, "quarter", i, 1.0));

    Score s = mkScore(0, "major", 4, 4, {m}, "装饰音小节");
    JianpuDoc doc = staffToJianpu(s);

    // 核心断言：装饰音必须是"已解析"的，否则会毒化后处理判断
    EXPECT_TRUE(doc.lines[0].measures[0].notes[0].isGrace);
    EXPECT_FALSE(doc.lines[0].measures[0].notes[0].rhythmUnresolvable);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_EQ(rep.flagged.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// (3) 单向大跳（不跳回）是正常音区转换，不得标记。
//     实测 7 份出版 GT 谱共 54 处 >= 24 半音跳变，尖刺 0 处，全属此类。
TEST(postcorrect_octave_plain_large_leap_is_noop) {
    Measure m; m.number = 1;                         // C4 -> C6 -> D6：跳上去就留在高音区
    m.notes.push_back(mkQ('C', 0, 4, "quarter", 0, 1.0));
    m.notes.push_back(mkQ('C', 0, 6, "quarter", 1, 1.0));
    m.notes.push_back(mkQ('D', 0, 6, "half",    2, 2.0));

    Score s = mkScore(0, "major", 4, 4, {m}, "单向大跳");
    JianpuDoc doc = staffToJianpu(s);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::OctaveDot), 0);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// (4) 含"未解析时值"的小节不得被标记：这是简谱表示能力的固有边界，不是 OMR 误识。
//     真实来源（Paganini Op.1 No.24 m138）：7:8 的 32 分连音，divisions=480 时
//     单音精确时值 480/7=68.571 无法整除，谱面只能写 <duration>69</duration>，
//     反推 rhythmQl=0.12578 与 32 分音符 0.125 差 7.8e-4 > 容差 1e-4 ->
//     转换器如实置 rhythmUnresolvable。此时小节和也随之带上舍入残差，
//     后处理必须整条跳过（既不改也不标）。
TEST(postcorrect_extreme_tuplet_ratio_is_noop) {
    JianpuDoc doc = buildSingleLineDoc(4, 4);

    JianpuMeasure m1; m1.number = 1;                 // 干净满拍，确保 m2 不被当作弱起
    for (int i = 0; i < 4; ++i) {
        JianpuNote n; n.degree = 1 + i; m1.notes.push_back(n);
    }
    doc.lines[0].measures.push_back(m1);

    JianpuMeasure m2; m2.number = 2;                 // 7:8 连音 + 2 个四分 = 3.0 != 4.0
    for (int i = 0; i < 7; ++i) {
        JianpuNote n;
        n.degree = 1 + (i % 7);
        n.underlines = 3;            // 32nd
        n.tuplet = 7;
        n.tupletNormal = 8;          // 7:8
        n.rhythmUnresolvable = true; // divisions 网格无法精确表示 1/7
        m2.notes.push_back(n);
    }
    for (int i = 0; i < 2; ++i) {
        JianpuNote n; n.degree = 1; m2.notes.push_back(n);
    }
    doc.lines[0].measures.push_back(m2);

    PostCorrectReport rep;
    JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::TupletGroup), 0);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::BeatReconcile), 0);
    EXPECT_EQ(countKind(rep.flagged, CorrectionKind::RestFill), 0);
    EXPECT_EQ(rep.applied.size(), 0u);
    EXPECT_TRUE(sameDoc(doc, out));
}

// ======================================================================
// 12. P1-1 返工·语料级 no-op 回归（硬红线）
//     出版级 GT 谱经 staffToJianpu 后跑后处理，applied 与 flagged 必须皆空。
//     此前 QA 在真实 GT 谱上曝出 103 处 confidence=1.0 静默改写，正是本红线
//     明令禁止的。用每文件一个 TEST 以便失败时能精确定位到具体谱面。
// ======================================================================

namespace {
// 单份 GT 谱的 no-op 断言（宏展开为独立 TEST，命名含谱面标识）
#define PC_CORPUS_TEST(fileRel, testName)                                   \
    TEST(testName) {                                                         \
        const std::string path = resolveDataPath(fileRel);                   \
        Score score; std::string err;                                        \
        MusicXMLParser parser;                                              \
        bool ok = parser.loadFromFile(path, score, err);                     \
        EXPECT_TRUE(ok);                                                      \
        if (!ok) return;                                                      \
        JianpuDoc doc = staffToJianpu(score);                                \
        EXPECT_FALSE(doc.lines.empty());                                      \
        if (doc.lines.empty()) return;                                       \
        PostCorrectReport rep;                                               \
        JianpuDoc out = correctJianpuDoc(doc, enabledCfg(), rep);           \
        EXPECT_TRUE(rep.applied.empty());                                     \
        EXPECT_TRUE(rep.flagged.empty());                                     \
    }
} // anonymous namespace

PC_CORPUS_TEST("data/solo-violin-partita-no-2-in-d-minor-j-s-bach-bwv-1004.musicxml",
               postcorrect_corpus_bach_partita_no_2)
PC_CORPUS_TEST("data/j-s-bach-cello-suite-n-1-bwv-1007-1-prelude.musicxml",
               postcorrect_corpus_cello_suite_no_1)
PC_CORPUS_TEST("data/concerto-in-a-minor-a-vivaldi.musicxml",
               postcorrect_corpus_vivaldi_concerto_a_minor)
PC_CORPUS_TEST("data/badinerie-for-flute-by-js-bach.musicxml",
               postcorrect_corpus_badinerie)
PC_CORPUS_TEST("data/solo-violin-caprice-no-24-in-a-minor-n-paganini-op-1-no-24.musicxml",
               postcorrect_corpus_paganini_caprice_24)
PC_CORPUS_TEST("data/canon-in-d-violin-solo.musicxml",
               postcorrect_corpus_canon_in_d)
PC_CORPUS_TEST("data/summer-third-movement.musicxml",
               postcorrect_corpus_summer_third_movement)

