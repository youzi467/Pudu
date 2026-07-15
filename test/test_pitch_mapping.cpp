// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试：绝对音高 -> 首调音级/记号/八度点（§5 case 1/2 + 边界/错误）
// 被测函数：midiToJianpu、midiToDegree
// ----------------------------------------------------------------------

#include "pudu_test.hpp"
#include "jianpu_converter.hpp"
#include "score_model.hpp"

namespace {
pudu::Pitch mk(char step, int alter, int octave) {
    pudu::Pitch p;
    p.step = step;
    p.alter = alter;
    p.octave = octave;
    p.hasValue = true;
    return p;
}
} // namespace

// ===== §5 case 1：中音区 / 升八度 / 降八度 =====

TEST(midiToJianpu_C4_in_C_major_is_degree1_middle) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('C', 0, 4), pudu::fifthsToTonicPc(0), deg, acc, od);
    EXPECT_EQ(deg, 1);
    EXPECT_TRUE(acc == pudu::Accidental::None);
    EXPECT_EQ(od, 0);
}
TEST(midiToJianpu_G4_in_C_major_is_degree5) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('G', 0, 4), pudu::fifthsToTonicPc(0), deg, acc, od);
    EXPECT_EQ(deg, 5);
    EXPECT_EQ(od, 0);
}
TEST(midiToJianpu_C5_in_C_major_octave_up) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('C', 0, 5), pudu::fifthsToTonicPc(0), deg, acc, od);
    EXPECT_EQ(deg, 1);
    EXPECT_EQ(od, 1);   // 1'
}
TEST(midiToJianpu_C3_in_C_major_octave_down) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('C', 0, 3), pudu::fifthsToTonicPc(0), deg, acc, od);
    EXPECT_EQ(deg, 1);
    EXPECT_EQ(od, -1);  // 1,
}

// ===== §5 case 2：D 大调调外音记号方向 =====

TEST(midiToJianpu_Gsharp4_in_D_major_is_sharp4) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('G', 1, 4), pudu::fifthsToTonicPc(2), deg, acc, od);
    EXPECT_EQ(deg, 4);
    EXPECT_TRUE(acc == pudu::Accidental::Sharp); // #4
}
TEST(midiToJianpu_C4_in_D_major_is_flat7) {
    int deg; pudu::Accidental acc; int od;
    pudu::midiToJianpu(mk('C', 0, 4), pudu::fifthsToTonicPc(2), deg, acc, od);
    EXPECT_EQ(deg, 7);
    EXPECT_TRUE(acc == pudu::Accidental::Flat);  // b7（规范 §5 case 2）
}

// midiToDegree 与 midiToJianpu 音级一致
TEST(midiToDegree_matches_midiToJianpu_degree) {
    pudu::Pitch p = mk('E', 0, 4);
    int pc = pudu::fifthsToTonicPc(0);
    EXPECT_EQ(pudu::midiToDegree(p, pc), 3);
}

// 错误处理：非法 step（非 A-G）不崩溃、结果确定（回退到 C/主音）
TEST(midiToJianpu_invalid_step_does_not_throw) {
    pudu::Pitch p = mk('X', 0, 4);
    int deg; pudu::Accidental acc; int od;
    EXPECT_NO_THROW(pudu::midiToJianpu(p, pudu::fifthsToTonicPc(0), deg, acc, od));
    EXPECT_EQ(deg, 1);  // stepToSemitone 默认回退 0 -> 主音
}

// 错误处理：休止式 Pitch（hasValue=false）不崩溃
TEST(midiToJianpu_rest_pitch_does_not_throw) {
    pudu::Pitch p;
    p.hasValue = false;  // 默认值 C4
    int deg; pudu::Accidental acc; int od;
    EXPECT_NO_THROW(pudu::midiToJianpu(p, pudu::fifthsToTonicPc(0), deg, acc, od));
}
