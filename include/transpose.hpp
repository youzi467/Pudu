#ifndef PUDU_TRANSPOSE_HPP
#define PUDU_TRANSPOSE_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 变调重算模块（阶段 2 边界补全 / 阶段 3 硬前置）
//
// 作用：在「解析层(Score)」与「简谱投影(JianpuDoc)」之间，提供一道
//       主音参考系变换。把 staffToJianpu 原本"以谱面调号为基准"的隐式
//       变调，泛化为"以用户指定目标调为基准"的显式变调。
//
// 两种模式（见 transposeScore）：
//   - Transpose（移调）：移动实际音高，简谱数字相对原调不变，"1=X" 改变。
//     对应歌手移调 / 乐器移调 / 简化调号。
//   - Rekey（改写调号）：实际音高不动，简谱数字相对新主音重算，"1=X" 改变。
//     对应记谱改写 / 教学对照。
//
// 设计要点：
//   - 单一事实源 = canonical Score。变调在 Score 上就地平移音高(或仅改调号)，
//     再走已有、已 100% 校验的 staffToJianpu 产出 JianpuDoc。
//     保证 L0 与 Score 自洽，直接满足阶段 3 往返(G3) 音高守恒的前提。
//   - 复用 fifthsToTonicPc / midiToJianpu 等纯函数，零新增音级算法，
//     不重新发明轮子，只换主音参考系。
//   - 音高平移通过 MIDI 中转(midiNumber <-> Pitch)，避免 step/alter 进位错误。
// ----------------------------------------------------------------------

#include <climits>
#include <string>
#include <utility>

#include "score_model.hpp"
#include "jianpu_model.hpp"
#include "jianpu_converter.hpp"

namespace pudu {

// 变调模式
enum class TransposeMode {
    Transpose,  // 听感变调：移动实际音高，简谱数字相对原调不变
    Rekey       // 改写调号：实际音高不变，简谱数字相对新主音重算
};

// 目标调规格
struct TransposeTarget {
    int fifths = 0;            // 目标调号（五度圈步数），用于标签与 Rekey 模式
    std::string mode = "major";
    int semitones = INT_MIN;   // 仅 --transpose 字面位移模式使用；非 INT_MIN 时
                               //   直接按该半音数平移（不走最近路径）
};

// 解析调名 -> (五度圈步数, 解析出的大小调)。
//   支持大小写/空白/♯♭ 容错；name 可带 "m" / "minor" / "小调" 后缀（此时忽略 defaultMode）。
//   例： "C"->(0,major)  "F#"->(6,major)  "Bb"->(-2,major)
//        "a"->(0,minor)  "e"->(1,minor)  "Am"->(0,minor)  "d minor"->(-1,minor)
//   无法解析时抛 std::invalid_argument。
std::pair<int, std::string> parseKeyName(const std::string& name,
                                         const std::string& defaultMode = "major");

// 调名 -> 五度圈步数（便捷封装，等价于 parseKeyName(name, mode).first）。
int tonicNameToFifths(const std::string& name, const std::string& mode = "major");

// 半音位移 -> 最接近(同号优先、最小绝对值)的五度圈步数，用于 --transpose ±N 的标签推导。
//   例： +2->2(D)  +1->7(C#)  -1->-7(Cb)  -2->-2(Bb)  +5->-1(F)  +6->6(F#)  -6->-6(Gb)  +12->0
int semitonesToFifths(int semitones);

// MIDI 音高编号 -> Pitch（按 preferSharp 选择升/降号拼写；仅影响 out-of-scale 音的 ♯/♭ 方向）。
//   与 midiToJianpu 互逆的"MIDI -> 音名"侧；阶段 3 反向转换(jianpuToStaff)复用它，
//   保证简谱->五线谱的音名拼写与变调重算(transpose.cpp)口径完全一致。
Pitch midiToPitch(int midi, bool preferSharp);

// 核心：在 canonical Score 上就地变调，并返回实际生效的半音位移 Δ（Rekey 恒为 0）。
//   - Transpose 模式：每个 Note.pitch（含和弦音）平移 Δ 半音，听感改变、简谱数字不变；
//   - Rekey 模式：仅改写调号（fifths/mode），音高不动，简谱数字相对新主音重算。
// Δ 来源：target.semitones != INT_MIN 取其字面值；否则取
//   (targetPc - srcPc) 在 [-6,6] 内的最近路径，保证不跨八度跳变。
// 不改动节奏字段（onset/voice/chord 结构/quarterLength 等）。
// 前置：score 非空且首声部含有效 attributes；否则抛 std::invalid_argument。
int transposeScore(Score& score, const TransposeTarget& target, TransposeMode mode);

// 便捷：对 Score 副本变调后产出简谱文档（不就地修改入参）。
JianpuDoc transposeStaffToJianpu(const Score& score,
                                 const TransposeTarget& target,
                                 TransposeMode mode);

} // namespace pudu

#endif // PUDU_TRANSPOSE_HPP
