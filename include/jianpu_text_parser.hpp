#ifndef PUDU_JIANPU_TEXT_PARSER_HPP
#define PUDU_JIANPU_TEXT_PARSER_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · G4 简谱文本输入解析器（L1 文本 -> L0 文档）
//
// 作用：把简谱纯文本（与 jianpuToL1 输出同形，或常见简写）解析为 JianpuDoc，
//       作为阶段 3 反向转换(jianpuToStaff / scoreToMusicXML)的输入，形成
//       "文本 -> 五线谱 MusicXML" 的闭环。
//
// 设计原则（与 G1/G2 一致）：
//   - 纯新增模块，不改动任何既有文件逻辑（零回归）。
//   - 解析器严格逆 renderJianpuNote（见 jianpu_converter.cpp），保证
//     jianpuToL1(doc) 产出的文本可被本解析器无损读回（端到端闭环）。
//   - 不抛异常：成功返回 true 并填充 out，失败返回 false 并写 err（非空）。
//   - 调号复用 transpose::parseKeyName 求 fifths，避免重复造轮子。
// ----------------------------------------------------------------------

#include <string>

#include "jianpu_model.hpp"

namespace pudu {

// 解析简谱 L1 文本 -> JianpuDoc。
//   text：多行简谱文本（标题行 / 头行 / voiceN: 行）。
//   out ：成功时填充的 JianpuDoc（进入本函数即先清空）。
//   err ：失败时写入的非空错误信息（成功时清空）。
// 返回：成功 true / 失败 false。
//   失败情形（健壮性）：空串、无调号头行(1=...)、非法音级(如 8/字母)、
//   无法解析的调名(parseKeyName 抛错)等。
bool parseJianpuText(const std::string& text, JianpuDoc& out, std::string& err);

} // namespace pudu

#endif // PUDU_JIANPU_TEXT_PARSER_HPP
