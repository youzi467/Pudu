// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：调号 -> 主音音级 / 调名字母（§5 case 9 + 边界/错误）
// 被测函数：fifthsToTonicPc、fifthsToTonicName
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"

// ===== fifthsToTonicPc：五度圈步数 -> 主音 pitch class（0-11）=====

TEST(fifthsToTonicPc_C_major_is_0) {
    EXPECT_EQ(pudu::fifthsToTonicPc(0), 0);
}
TEST(fifthsToTonicPc_G_major_is_7) {
    EXPECT_EQ(pudu::fifthsToTonicPc(1), 7);
}
TEST(fifthsToTonicPc_D_major_is_2) {
    EXPECT_EQ(pudu::fifthsToTonicPc(2), 2);
}
TEST(fifthsToTonicPc_A_major_is_9) {
    EXPECT_EQ(pudu::fifthsToTonicPc(3), 9);
}
TEST(fifthsToTonicPc_E_major_is_4) {
    EXPECT_EQ(pudu::fifthsToTonicPc(4), 4);
}
TEST(fifthsToTonicPc_B_major_is_11) {
    EXPECT_EQ(pudu::fifthsToTonicPc(5), 11);
}
TEST(fifthsToTonicPc_Fsharp_major_is_6) {
    EXPECT_EQ(pudu::fifthsToTonicPc(6), 6);
}
// 边界：负调号（降号）取正模，不为负
TEST(fifthsToTonicPc_F_major_negative_wraps_positive) {
    EXPECT_EQ(pudu::fifthsToTonicPc(-1), 5);   // F = pc 5
}
TEST(fifthsToTonicPc_Bb_major_is_10) {
    EXPECT_EQ(pudu::fifthsToTonicPc(-2), 10);  // Bb = pc 10
}
// 边界：超出 ±7 仍以 12 为周期，结果落在 0..11
TEST(fifthsToTonicPc_large_fifths_still_in_range) {
    int pc = pudu::fifthsToTonicPc(12);
    EXPECT_TRUE(pc >= 0 && pc < 12);
    EXPECT_EQ(pc, pudu::fifthsToTonicPc(0)); // 12 个五度回到 C
}

// ===== fifthsToTonicName：调号 -> "1=X" 字母（§5 case 9）=====

TEST(fifthsToTonicName_covers_spec_keys) {
    EXPECT_EQ(pudu::fifthsToTonicName(0, "major"), "C");
    EXPECT_EQ(pudu::fifthsToTonicName(1, "major"), "G");
    EXPECT_EQ(pudu::fifthsToTonicName(2, "major"), "D");
    EXPECT_EQ(pudu::fifthsToTonicName(3, "major"), "A");
    EXPECT_EQ(pudu::fifthsToTonicName(4, "major"), "E");
    EXPECT_EQ(pudu::fifthsToTonicName(5, "major"), "B");
    EXPECT_EQ(pudu::fifthsToTonicName(6, "major"), "F#");
    EXPECT_EQ(pudu::fifthsToTonicName(-1, "major"), "F");
    EXPECT_EQ(pudu::fifthsToTonicName(-2, "major"), "Bb");
    EXPECT_EQ(pudu::fifthsToTonicName(-3, "major"), "Eb");
    EXPECT_EQ(pudu::fifthsToTonicName(-4, "major"), "Ab");
    EXPECT_EQ(pudu::fifthsToTonicName(-5, "major"), "Db");
}

// 错误处理：超出 ±7 的调号钳制到边界字母，不崩溃、结果确定
TEST(fifthsToTonicName_out_of_range_clamps) {
    EXPECT_EQ(pudu::fifthsToTonicName(8, "major"), "C#");
    EXPECT_EQ(pudu::fifthsToTonicName(-9, "major"), "Cb");
    EXPECT_NO_THROW(pudu::fifthsToTonicName(100, "major"));
}

// 小调采用首调相对法：1 落关系大调主音（共享同一调号）
TEST(fifthsToTonicName_minor_uses_relative_major) {
    EXPECT_EQ(pudu::fifthsToTonicName(0, "minor"), "C");   // a 小调 -> 1=C
    EXPECT_EQ(pudu::fifthsToTonicName(-1, "minor"), "F");  // d 小调 -> 1=F
    EXPECT_EQ(pudu::fifthsToTonicName(2, "minor"), "D");   // b 小调 -> 1=D
}
