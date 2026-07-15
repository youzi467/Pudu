#ifndef PUDU_JIANPU_TO_STAFF_HPP
#define PUDU_JIANPU_TO_STAFF_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 3 反向转换（简谱 -> 五线谱）
//
// G1  jianpuToStaff  : JianpuDoc(L0 简谱) -> Score(五线谱内存模型)
// G2  scoreToMusicXML: Score -> 完整可解析的 .musicxml(score-partwise) 字符串
//
// 与阶段 2 staffToJianpu 严格互逆（同一组映射表反向推导）：
//   - 音级 -> 绝对音高：逆 midiToJianpu（复用 transpose::midiToPitch 做 MIDI->音名拼写）；
//   - 八度点 -> octave：与 midiToJianpu 的 octaveDots 严格互逆；
//   - 时值 -> type + duration：underlines/augmentDashes/dots 逆查节律表；
//   - 全局属性 -> ScoreAttributes；多声部按 line.partIndex/voice 还原；
//   - 休止 / 和弦 / 装饰音 / 延音线 映射回 Note。
//
// 设计原则（与文档 stage3_action_plan.md §5 一致）：
//   - 对 staffToJianpu / 渲染器零侵入：全部为新增函数。
//   - divisions 在反向生成时选定（默认 4），round-trip 音高守恒不受其影响。
//   - 和弦逐音八度点在阶段 2 仅存音级，反向只能还原到"根音最近邻"八度，
//     此为已知限制（与阶段 2 边界项对齐），已在代码注释标注。
// ----------------------------------------------------------------------

#include <string>

#include "jianpu_model.hpp"
#include "score_model.hpp"

namespace pudu {

// G1：简谱 L0 文档 -> 五线谱 Score（canonical 内存模型）。
//   divisions：反向生成选用的 divisions（默认 4），决定 duration 整数粒度与导出 MusicXML。
//   返回空 Score（isEmpty()==true）当且仅当 doc.lines 为空。
Score jianpuToStaff(const JianpuDoc& doc, int divisions = 4);

// G2：Score -> 完整可解析的 .musicxml（score-partwise）字符串。
//   用 pugixml 写出（与 MusicXMLParser 对称）。写出文件可被本仓库解析器读回且语义等价。
//   - 多声部用 <backup>/<forward> 还原并行时序；和弦后续音用 <chord/>；
//   - <attributes> 含 divisions / key(fifths+mode) / time / clef。
//   不写 lyric / notations / 多谱号等（MVP，与解析器一致）。
std::string scoreToMusicXML(const Score& score);

} // namespace pudu

#endif // PUDU_JIANPU_TO_STAFF_HPP
