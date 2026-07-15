// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：时值类型 -> 减时线/增时线（§5 case 3 + 边界/错误）
// 被测函数：typeToDuration
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"

TEST(typeToDuration_whole_is_3_augment) {
    int ul, ad; pudu::typeToDuration("whole", ul, ad);
    EXPECT_EQ(ul, 0); EXPECT_EQ(ad, 3);
}
TEST(typeToDuration_half_is_1_augment) {
    int ul, ad; pudu::typeToDuration("half", ul, ad);
    EXPECT_EQ(ul, 0); EXPECT_EQ(ad, 1);
}
TEST(typeToDuration_quarter_is_0_0) {
    int ul, ad; pudu::typeToDuration("quarter", ul, ad);
    EXPECT_EQ(ul, 0); EXPECT_EQ(ad, 0);
}
TEST(typeToDuration_eighth_is_1_underline) {
    int ul, ad; pudu::typeToDuration("eighth", ul, ad);
    EXPECT_EQ(ul, 1); EXPECT_EQ(ad, 0);
}
TEST(typeToDuration_16th_is_2_underlines) {
    int ul, ad; pudu::typeToDuration("16th", ul, ad);
    EXPECT_EQ(ul, 2); EXPECT_EQ(ad, 0);
}
TEST(typeToDuration_32nd_is_3_underlines) {
    int ul, ad; pudu::typeToDuration("32nd", ul, ad);
    EXPECT_EQ(ul, 3); EXPECT_EQ(ad, 0);
}
TEST(typeToDuration_64th_is_4_underlines) {
    int ul, ad; pudu::typeToDuration("64th", ul, ad);
    EXPECT_EQ(ul, 4); EXPECT_EQ(ad, 0);
}

// 错误处理：未知/缺失 type 按四分(0,0)处理，不崩溃
TEST(typeToDuration_unknown_type_defaults_to_quarter) {
    int ul, ad; pudu::typeToDuration("triplet", ul, ad);
    EXPECT_EQ(ul, 0); EXPECT_EQ(ad, 0);
}
TEST(typeToDuration_empty_type_defaults_to_quarter) {
    int ul, ad; pudu::typeToDuration("", ul, ad);
    EXPECT_EQ(ul, 0); EXPECT_EQ(ad, 0);
    EXPECT_NO_THROW(pudu::typeToDuration("???", ul, ad));
}
