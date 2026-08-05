#ifndef PUDU_JIANPU_POSTCORRECT_HPP
#define PUDU_JIANPU_POSTCORRECT_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · P1-1 后处理音乐规则引擎（jianpu_postcorrect）
//
// 定位（docs/jianpu-ocr-optimization-plan.md §3.2）：
//   挂在 staffToJianpu 之后的一层【确定性】音乐规则引擎，对 oemer 等 OMR
//   引擎的常见错误做"高置信自修 / 低置信标记"。
//
// 铁律（CI 红线）：
//   对干净输入必须是 no-op —— 即由 staffToJianpu 正常转换出来的、各小节严格
//   归零的 JianpuDoc，经本引擎后 applied 与 flagged 均为空，且逐音字段不变。
//   所有规则都只在"违规才触发"，绝不主动重写合法记谱。
//
// 设计要点：
//   - 纯函数式：吃 JianpuDoc（值传递），吐一份可能被修正的副本 + 审计报告，
//     不回改 Score，也不依赖 Score / MusicXML。
//   - 每条修正都带 (part, voice, measure, noteIndex) 真实坐标 + before/after
//     + reason + confidence，可完整回放、可人工复核。
//   - confidence == 1.0 表示"确定自修"（进 applied）；< 1.0 表示"仅标记"
//     （进 flagged）或"低置信自修"（进 applied 但保留低分供人工抽检）。
//   - 绝不臆造音符/休止：占拍不足只标记，不填充。
// ----------------------------------------------------------------------

#include "jianpu_model.hpp"

#include <ostream>
#include <string>
#include <vector>

namespace pudu {

// 规则引擎开关。默认 enabled=false —— 不开启时 correctJianpuDoc 原样返回，
// 保证既有流水线行为逐字节不变。
struct PostCorrectConfig {
    bool enabled = false;
    bool autoFixBeatOverflow = true;   // 小节时长溢出/不足自动纠正
    bool flagOctaveJumps   = true;     // 异常八度跳变标记
    bool enforceKeyConsistency = true; // 调内/临时记号一致性
    bool conservative = true;          // true=非节拍类仅高置信自修，其余仅标记

    // P1-2 Bug B 修复：拍号可信度自证（meter corroboration）。
    //   BeatReconcile 的全部结论都建立在"小节目标拍值 target 正确"这一前提上。
    //   当拍号元数据本身失真（分页 GT 丢失曲中变拍号、OMR 未识别拍号等），
    //   target 是错的，于是【整段】小节都被误判为"不足/溢出"，其中恰好能被
    //   "单音一步"归零的那几处会被静默自修 —— 干净输入 applied>0，红线即破。
    //   开启后：逐拍号段统计"实际占拍"，若存在一个被更多小节一致认同的占拍值
    //   否证了声明拍号，则判定该段 target 不可信，BeatReconcile 整段跳过
    //   （既不改也不标）。该门只会【减少】输出，不会新增任何修正。
    // 🔴 CI 红线依赖此项为 true —— 关闭仅供单测对比两分支行为。
    bool requireMeterCorroboration = true;
};

// 修正类别（对应五类规则）
enum class CorrectionKind { BeatReconcile, OctaveDot, Accidental, TupletGroup, RestFill };

// 流输出（供 EXPECT_EQ 等在失败时打印 enum class；纯诊断用，不影响任何逻辑）。
// 必须在 pudu 命名空间内，EXPECT_EQ 失败时 ADL 才能找到它。
inline std::ostream& operator<<(std::ostream& os, CorrectionKind k) {
    switch (k) {
        case CorrectionKind::BeatReconcile: return os << "BeatReconcile";
        case CorrectionKind::OctaveDot:     return os << "OctaveDot";
        case CorrectionKind::Accidental:    return os << "Accidental";
        case CorrectionKind::TupletGroup:   return os << "TupletGroup";
        case CorrectionKind::RestFill:      return os << "RestFill";
    }
    return os << "CorrectionKind(" << static_cast<int>(k) << ")";
}

// 类别 -> 稳定字符串（JSON 键值 / 日志 / 单测断言共用同一份口径）
const char* correctionKindName(CorrectionKind kind);

// 单条修正记录（审计轨迹）。
//   measure 存【真实小节号】(JianpuMeasure::number)，noteIndex 存小节内下标，
//   -1 表示这是一条小节级（而非某个具体音符）的记录。
struct Correction {
    CorrectionKind kind = CorrectionKind::BeatReconcile;
    int part = 0, voice = 1, measure = 0, noteIndex = -1;
    std::string before, after, reason;
    double confidence = 0.0;           // 1.0=确定自修；<1 仅标记
};

// 引擎报告
struct PostCorrectReport {
    std::vector<Correction> applied;   // 已自动修正（审计轨迹）
    std::vector<Correction> flagged;   // 仅标记待人工
    int measuresReconciled = 0;        // 发生过节拍自修的【不同小节】数
    int notesTouched = 0;              // 被自修改写过的【不同音符】数
};

// 纯函数式：输入 JianpuDoc，输出（可能）修正后的副本 + 报告，不回改 Score。
//   规则执行顺序固定为：
//     BeatReconcile -> Accidental -> OctaveDot -> TupletGroup -> RestFill
//   报告中的 applied/flagged 亦按该顺序追加，便于稳定 diff。
JianpuDoc correctJianpuDoc(JianpuDoc doc, const PostCorrectConfig& cfg,
                           PostCorrectReport& report);

// 报告序列化（供 --postcorrect-report 写出）；返回 JSON 字符串。
//   顶层：{measuresReconciled, notesTouched, appliedCount, flaggedCount,
//          applied:[...], flagged:[...]}
std::string postCorrectReportToJson(const PostCorrectReport& report);

// 便捷函数：把报告 JSON 写到文件。成功返回 true；打不开/写失败返回 false。
bool writePostCorrectReportFile(const PostCorrectReport& report,
                                const std::string& path);

} // namespace pudu

#endif // PUDU_JIANPU_POSTCORRECT_HPP
