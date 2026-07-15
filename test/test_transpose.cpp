// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：变调重算模块（transpose.hpp）
// 被测：parseKeyName / tonicNameToFifths / semitonesToFifths /
//       transposeScore / transposeStaffToJianpu
// 覆盖：正常路径、与预期规则一致、边界、异常输入。
// 不依赖 MusicXML 解析 / pugixml，仅用内存模型构造 Score。
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "transpose.hpp"
#include "test_helpers.hpp"

// ===== parseKeyName / tonicNameToFifths：调名解析 =====

TEST(transpose_parse_major_keys) {
    EXPECT_EQ(pudu::tonicNameToFifths("C"), 0);
    EXPECT_EQ(pudu::tonicNameToFifths("G"), 1);
    EXPECT_EQ(pudu::tonicNameToFifths("D"), 2);
    EXPECT_EQ(pudu::tonicNameToFifths("A"), 3);
    EXPECT_EQ(pudu::tonicNameToFifths("E"), 4);
    EXPECT_EQ(pudu::tonicNameToFifths("B"), 5);
    EXPECT_EQ(pudu::tonicNameToFifths("F#"), 6);
    EXPECT_EQ(pudu::tonicNameToFifths("C#"), 7);
}

TEST(transpose_parse_flat_keys) {
    EXPECT_EQ(pudu::tonicNameToFifths("F"), -1);
    EXPECT_EQ(pudu::tonicNameToFifths("Bb"), -2);
    EXPECT_EQ(pudu::tonicNameToFifths("Eb"), -3);
    EXPECT_EQ(pudu::tonicNameToFifths("Ab"), -4);
    EXPECT_EQ(pudu::tonicNameToFifths("Db"), -5);
    EXPECT_EQ(pudu::tonicNameToFifths("Gb"), -6);
    EXPECT_EQ(pudu::tonicNameToFifths("Cb"), -7);
}

TEST(transpose_parse_minor_keys) {
    EXPECT_EQ(pudu::tonicNameToFifths("a", "minor"), 0);   // a 小调 -> 0 (C)
    EXPECT_EQ(pudu::tonicNameToFifths("e", "minor"), 1);
    EXPECT_EQ(pudu::tonicNameToFifths("b", "minor"), 2);
    EXPECT_EQ(pudu::tonicNameToFifths("f#", "minor"), 3);
    EXPECT_EQ(pudu::tonicNameToFifths("d", "minor"), -1);
    EXPECT_EQ(pudu::tonicNameToFifths("g", "minor"), -2);
    EXPECT_EQ(pudu::tonicNameToFifths("c", "minor"), -3);
    EXPECT_EQ(pudu::tonicNameToFifths("f", "minor"), -4);
}

TEST(transpose_parse_suffix_and_tolerance) {
    // 后缀 "m" / "minor" / "小调" 自带大小调语义，忽略 defaultMode
    EXPECT_EQ(pudu::tonicNameToFifths("Am"), 0);
    EXPECT_EQ(pudu::tonicNameToFifths("a minor"), 0);
    EXPECT_EQ(pudu::tonicNameToFifths("C major"), 0);
    EXPECT_EQ(pudu::tonicNameToFifths("d小调"), -1);
    // 大小写 / 空白容错
    EXPECT_EQ(pudu::tonicNameToFifths("  f#  "), 6);
    EXPECT_EQ(pudu::tonicNameToFifths("D"), 2);
    EXPECT_EQ(pudu::tonicNameToFifths("C major"), 0);     // 显式大调后缀
    // Unicode 升号 ♯ 等价 #（"F♯" -> 6）
    EXPECT_EQ(pudu::tonicNameToFifths("F\xE2\x99\xAF"), 6);
}

TEST(transpose_parse_invalid_throws) {
    EXPECT_THROW(pudu::tonicNameToFifths("H"));
    EXPECT_THROW(pudu::tonicNameToFifths(""));
    EXPECT_THROW(pudu::tonicNameToFifths("Xyz"));
    EXPECT_THROW(pudu::tonicNameToFifths("12"));
}

TEST(transpose_parse_returns_mode) {
    auto maj = pudu::parseKeyName("D");
    EXPECT_EQ(maj.first, 2);
    EXPECT_EQ(maj.second, "major");
    auto min = pudu::parseKeyName("a", "minor");   // 显式 minor：a 小调 -> 0
    EXPECT_EQ(min.first, 0);
    EXPECT_EQ(min.second, "minor");
    auto minSuf = pudu::parseKeyName("e minor");
    EXPECT_EQ(minSuf.first, 1);
    EXPECT_EQ(minSuf.second, "minor");
}

// ===== semitonesToFifths：半音 -> 调号（标签推导） =====

TEST(transpose_semitones_to_fifths) {
    EXPECT_EQ(pudu::semitonesToFifths(2), 2);    // +2(大二度) -> D
    EXPECT_EQ(pudu::semitonesToFifths(1), 7);    // +1 -> C#(升号优先)
    EXPECT_EQ(pudu::semitonesToFifths(-1), -7);  // -1 -> Cb(降号优先)
    EXPECT_EQ(pudu::semitonesToFifths(-2), -2);  // -2 -> Bb
    EXPECT_EQ(pudu::semitonesToFifths(5), -1);   // +5(纯四度) -> F
    EXPECT_EQ(pudu::semitonesToFifths(7), 1);    // +7(纯五度) -> G
    EXPECT_EQ(pudu::semitonesToFifths(6), 6);    // +6 -> F#
    EXPECT_EQ(pudu::semitonesToFifths(-6), -6);  // -6 -> Gb
    EXPECT_EQ(pudu::semitonesToFifths(0), 0);
    EXPECT_EQ(pudu::semitonesToFifths(12), 0);   // 八度回到 C
}

// ===== 工具：构造含 C-D-E 的 C 大调单声部 Score =====

namespace {
pudu::Score mkCDScore(int srcFifths = 0, const std::string& mode = "major") {
    pudu::Measure m;
    m.number = 1;
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 4), "quarter", 0));
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('D', 0, 4), "quarter", 1));
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('E', 0, 4), "quarter", 2));
    std::vector<pudu::Measure> ms = {m};
    return pudu::mkScore(srcFifths, mode, 4, 4, ms, "测试曲");
}
} // anonymous namespace

// ===== transposeStaffToJianpu：Transpose 模式（听感变调，数字不变） =====

TEST(transpose_to_D_preserves_numerals) {
    pudu::Score s = mkCDScore(0, "major");
    pudu::JianpuDoc doc = pudu::transposeStaffToJianpu(
        s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    EXPECT_EQ(doc.fifths, 2);
    EXPECT_EQ(doc.tonicLabel, "1=D");
    // 首调数字不变：C-D-E 在 D 大调下仍为 1-2-3
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 1);
    EXPECT_EQ(doc.lines[0].measures[0].notes[1].degree, 2);
    EXPECT_EQ(doc.lines[0].measures[0].notes[2].degree, 3);
    // 节奏字段不受变调影响
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].underlines, 0);
}

TEST(transpose_by_semitones_matches_by_key) {
    pudu::Score s = mkCDScore(0, "major");
    // --transpose +2 与 --key D 应给出同一结果（数字 1-2-3，标签 1=D）
    pudu::JianpuDoc byKey = pudu::transposeStaffToJianpu(
        s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    pudu::JianpuDoc bySemi = pudu::transposeStaffToJianpu(
        s, {pudu::semitonesToFifths(2), "major", 2}, pudu::TransposeMode::Transpose);
    EXPECT_EQ(byKey.tonicLabel, bySemi.tonicLabel);
    for (size_t i = 0; i < 3; ++i)
        EXPECT_EQ(byKey.lines[0].measures[0].notes[i].degree,
                  bySemi.lines[0].measures[0].notes[i].degree);
}

// ===== transposeScore：数据同步（音高平移） —— 阶段 3 前置核心 =====

TEST(transpose_score_shifts_pitch_and_label) {
    pudu::Score s = mkCDScore(0, "major");
    int delta = pudu::transposeScore(s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    EXPECT_EQ(delta, 2);                              // C(0)->D(2)：最近路径 +2
    EXPECT_EQ(s.parts[0].attributes.fifths, 2);       // 调号更新
    EXPECT_EQ(s.parts[0].measures[0].notes[0].pitch.midiNumber(), 62); // C4(60)+2
    EXPECT_EQ(s.parts[0].measures[0].notes[1].pitch.midiNumber(), 64); // D4(62)
    EXPECT_EQ(s.parts[0].measures[0].notes[2].pitch.midiNumber(), 66); // E4(64)+2
}

TEST(transpose_score_empty_throws) {
    pudu::Score empty;
    EXPECT_THROW(pudu::transposeScore(empty, {2, "major", INT_MIN},
                                      pudu::TransposeMode::Transpose));
}

// ===== Rekey 模式：音高不变，数字相对新主音重算 =====

TEST(rekey_to_G_recomputes_numerals_keeps_pitch) {
    pudu::Score s = mkCDScore(0, "major");
    pudu::JianpuDoc doc = pudu::transposeStaffToJianpu(
        s, {1, "major", INT_MIN}, pudu::TransposeMode::Rekey);
    EXPECT_EQ(doc.fifths, 1);
    EXPECT_EQ(doc.tonicLabel, "1=G");
    // C-D-E(pc 0,2,4) 相对 G(pc 7)：4,5,6
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 4);
    EXPECT_EQ(doc.lines[0].measures[0].notes[1].degree, 5);
    EXPECT_EQ(doc.lines[0].measures[0].notes[2].degree, 6);
    // 音高不动（就地验证）
    pudu::Score s2 = mkCDScore(0, "major");
    int delta = pudu::transposeScore(s2, {1, "major", INT_MIN}, pudu::TransposeMode::Rekey);
    EXPECT_EQ(delta, 0);
    EXPECT_EQ(s2.parts[0].measures[0].notes[0].pitch.midiNumber(), 60); // C4 不变
}

// ===== 边界：休止符 / 和弦 =====

TEST(transpose_keeps_rest_as_rest) {
    pudu::Measure m; m.number = 1;
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('C', 0, 4), "quarter", 0));
    m.notes.push_back(pudu::mkRest("quarter", 1));
    pudu::Score s = pudu::mkScore(0, "major", 4, 4, {m}, "带休止");
    pudu::JianpuDoc doc = pudu::transposeStaffToJianpu(
        s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    // 休止符变调后仍为 0
    EXPECT_EQ(doc.lines[0].measures[0].notes[1].degree, 0);
    // 实音仍正确平移并投影
    EXPECT_EQ(doc.lines[0].measures[0].notes[0].degree, 1);
}

TEST(transpose_chord_shifts_all_voices) {
    pudu::Measure m; m.number = 1;
    pudu::Note n = pudu::mkNote(pudu::mkPitch('C', 0, 4), "quarter", 0);
    n.chordPitches.push_back(pudu::mkPitch('E', 0, 4)); // C+E 和弦
    m.notes.push_back(n);
    pudu::Score s = pudu::mkScore(0, "major", 4, 4, {m}, "和弦");
    pudu::JianpuDoc doc = pudu::transposeStaffToJianpu(
        s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    const auto& jn = doc.lines[0].measures[0].notes[0];
    EXPECT_EQ(jn.degree, 1);              // C->D 主音
    EXPECT_EQ(jn.chordDegrees.size(), 1u); // 和弦其余音同步重算
    EXPECT_EQ(jn.chordDegrees[0], 3);     // E->F# 在三度(以 D 为 1：D E F# => F#为3)
}

// ===== 拼写偏好：升号调用 ♯、降号调用 ♭ =====
// 该偏好作用于【变调平移后的 Pitch 拼写】(midiToPitch)，故在 Pitch 层断言最清晰。

TEST(transpose_spelling_sharp_key_uses_sharp) {
    // C 大调 B4(pc11) 移到 D 大调(升号调, +2)：B4+2 = C#5，应记为 C#(step C, alter +1)。
    pudu::Measure m; m.number = 1;
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('B', 0, 4), "quarter", 0));
    pudu::Score s = pudu::mkScore(0, "major", 4, 4, {m}, "拼写");
    pudu::transposeScore(s, {2, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    const auto& p = s.parts[0].measures[0].notes[0].pitch;
    EXPECT_EQ(p.step, 'C');
    EXPECT_EQ(p.alter, 1);   // 升号拼写
}

TEST(transpose_spelling_flat_key_uses_flat) {
    // C 大调 F4(pc5) 移到 F 大调(降号调, +5)：F4+5 = Bb4，应记为 Bb(step B, alter -1)。
    pudu::Measure m; m.number = 1;
    m.notes.push_back(pudu::mkNote(pudu::mkPitch('F', 0, 4), "quarter", 0));
    pudu::Score s = pudu::mkScore(0, "major", 4, 4, {m}, "拼写");
    pudu::transposeScore(s, {-1, "major", INT_MIN}, pudu::TransposeMode::Transpose);
    const auto& p = s.parts[0].measures[0].notes[0].pitch;
    EXPECT_EQ(p.step, 'B');
    EXPECT_EQ(p.alter, -1);  // 降号拼写
}
