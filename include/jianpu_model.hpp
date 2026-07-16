#ifndef PUDU_JIANPU_MODEL_HPP
#define PUDU_JIANPU_MODEL_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 2 简谱数据模型（L0 权威内部模型）
//
// 对应 omr-tool-research/jianpu_output_spec.md §1。
// 消费 include/score_model.hpp 的 Score（含 onset/voice/chordPitches/isGrace/tie）。
//
// 设计要点（见规范 §0）：
//   - 一份数据、三种呈现：L0 语义模型 + L1 纯文本 + L2 二维渲染，并保留
//     Score/MusicXML 作 canonical 中间产物（L3）。
//   - L0 只存语义字段（音级/八度/时值/记号），不存字符；渲染器各自投影，
//     阶段 3 反向转换直接消费 L0，互不绑死。
//   - 首调（movable-do）：1 = 主音，按调号定位；调外音用临时记号表示，不移调。
//   - JianpuNote 字段与 Note.onset/voice/chordPitches/isGrace/tieStart/tieStop
//     一一对应，转换不回改 Score。
// ----------------------------------------------------------------------

#include <ostream>
#include <string>
#include <vector>

namespace pudu {

// 临时记号（数字左侧）。DoubleSharp/DoubleFlat 为后续扩展预留。
enum class Accidental { None, Sharp, Flat, Natural, DoubleSharp, DoubleFlat };

// 流输出（供 EXPECT_EQ 等在失败时打印 enum class；纯诊断用，不影响任何逻辑）。
// 必须在 pudu 命名空间内，EXPECT_EQ 失败时 ADL 才能找到它。
inline std::ostream& operator<<(std::ostream& os, Accidental a) {
    switch (a) {
        case Accidental::None:        return os << "None";
        case Accidental::Sharp:       return os << "Sharp";
        case Accidental::Flat:        return os << "Flat";
        case Accidental::Natural:     return os << "Natural";
        case Accidental::DoubleSharp: return os << "DoubleSharp";
        case Accidental::DoubleFlat:  return os << "DoubleFlat";
    }
    return os << "Accidental(" << static_cast<int>(a) << ")";
}

// 单个简谱音（或休止）
struct JianpuNote {
    int degree = 0;             // 0=休止, 1-7=首调音级(do..si)
    int octaveDots = 0;         // +n=上方点(升八度), -n=下方点(降八度), 0=中音区
    Accidental accidental = Accidental::None;  // 临时记号(数字左侧)

    int underlines = 0;         // 减时线: 0=四分,1=八分,2=十六分,3=三十二分...
    int augmentDashes = 0;      // 增时线: 数字右"-"数(二分=1, 全音符=3)
    int dots = 0;               // 附点数(×1.5 / ×1.75)
    double onset = 0.0;         // 起始位置(单位=四分音符/quarterLength)，与 music21 同量纲

    bool tieToNext = false;     // 连音线连向下一音
    bool isGrace = false;       // 装饰音(小音符, 不占基本时值)
    int tuplet = 0;             // 连音组: 0=常规,3=三连音,5=五连音...（阶段 2 暂置 0）
    std::vector<int> chordDegrees;  // 和弦其余音级(主音在 degree)；逐音八度点后续扩展
};

// 小节（按 onset 升序的音序列）
struct JianpuMeasure {
    int number = 0;
    std::vector<JianpuNote> notes;
};

// 单行（一个声部/层）。多声部谱 -> 多行。
struct JianpuLine {
    int voice = 1;
    int partIndex = 0;          // 所属声部在 Score.parts 中的下标（校验器按 (part,voice) 对齐）
    std::vector<JianpuMeasure> measures;
};

// 整份简谱文档（L0 根）
struct JianpuDoc {
    std::string title;
    std::string tonicLabel;     // "1=D"
    std::string mode = "major"; // major/minor
    int beats = 4;
    int beatType = 4;
    int fifths = 0;             // 调号(五度圈步数)；供校验器还原主音音级，对齐转换器实际使用的调
    std::vector<JianpuLine> lines;  // 多声部 -> 多行
};

} // namespace pudu

#endif // PUDU_JIANPU_MODEL_HPP
