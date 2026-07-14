#ifndef PUDU_SCORE_MODEL_HPP
#define PUDU_SCORE_MODEL_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · MusicXML 内存模型（MVP 版）
//
// 对应 omr-tool-research/musicxml_mvp_tags.md 中的标签集：
//   Pitch      <- <pitch> (step/alter/octave)
//   Note       <- <note>  (pitch|rest, duration, type, dot, tie)
//   Measure    <- <measure>
//   ScoreAttributes <- <attributes> (divisions/key/time/clef)
//   Part       <- <part> (+ <part-list>/<score-part> 的 id/name)
//   Score      <- <score-partwise>
//
// 设计原则：
//   - 只承载 MVP 必需字段，跳过清单见 musicxml_mvp_tags.md §3。
//   - 结构可被后续阶段 2/3 转换器直接 include 复用，扩展时只加字段。
//   - 提供 midiNumber() 等辅助方法，便于「绝对音高 -> 首调音级」换算。
// ----------------------------------------------------------------------

#include <string>
#include <vector>

namespace pudu {

// 音高：step(A-G) + alter(变音) + octave(八度组号, 中央 C = 4)
struct Pitch {
    char step = 'C';          // A-G
    int alter = 0;            // -1=降, 0=还原, +1=升（MVP 仅支持整数半音）
    int octave = 4;           // 八度组号（scientific pitch notation）
    bool hasValue = false;    // 是否为有效音高（休止符时为 false）

    // 计算 MIDI 音高编号（C4 = 60），方便后续换算简谱音级
    int midiNumber() const {
        return 12 * (octave + 1) + stepToSemitone(step) + alter;
    }

    static int stepToSemitone(char s) {
        switch (s) {
            case 'C': return 0;
            case 'D': return 2;
            case 'E': return 4;
            case 'F': return 5;
            case 'G': return 7;
            case 'A': return 9;
            case 'B': return 11;
            default:  return 0;
        }
    }
};

// 谱面抬头信息行（来自 <credit>/<credit-words>）
// MusicXML 中标题/作者/版权等通常以多条 credit-words 形式写在 <credit> 里，
// 单声部谱或扫描/OMR 生成的谱常只把标题放在 credit 中（此时无 movement-title）。
struct Credit {
    std::string text;           // credit-words 的文本内容
    int defaultY = 0;           // 纵坐标（页面坐标，越大越靠上）；无该属性时为 0
    std::string justification;  // 对齐方式（left/center/right），可选

    // 校验：文本非空（去除首尾空白后）才视为有效抬头行
    bool isValid() const {
        size_t b = text.find_first_not_of(" \t\r\n");
        size_t e = text.find_last_not_of(" \t\r\n");
        return b != std::string::npos && e != std::string::npos && e >= b;
    }
    // 去除首尾空白后的实际文本
    std::string trimmed() const {
        size_t b = text.find_first_not_of(" \t\r\n");
        if (b == std::string::npos) return {};
        size_t e = text.find_last_not_of(" \t\r\n");
        return text.substr(b, e - b + 1);
    }
};

// 音符（或休止符）
struct Note {
    bool isRest = false;           // true=休止符（无 pitch）
    Pitch pitch;                   // 音高（休止符时忽略）
    long duration = 0;             // 时值整数（单位 = divisions）

    // —— 阶段 2（简谱转换）前置字段：2026-07-14 统一补齐 ——
    int onset = 0;                 // 本音符在【小节内】的起始位置（单位 = divisions，
                                  //   与 duration 同量纲）。由 parseMeasure 的游标在各
                                  //   <note> 处维护；和弦音(chord)与上一音同 onset；
                                  //   <backup>/<forward> 会回退/前进游标。
                                  //   用途：还原真实时间轴，按 (onset, voice) 排序即
                                  //   得演奏顺序，供简谱分层/对齐使用。
    int voice = 1;                 // 声部/层编号（来自 <voice>），默认 1。
                                  //   多声部谱中各层独立成线，简谱可按 voice 分行。
    std::vector<Pitch> chordPitches; // 和弦内【其余】音高（不含本 note.pitch）。
                                  //   仅当本音为和弦主音(首个、无 <chord/>) 时填充；
                                  //   后续 <chord/> 音并入此列表，不再单独成事件。
                                  //   用途：简谱和弦标记 / 钢琴谱纵向叠加。
    bool isGrace = false;          // 是否为装饰音（<grace>）。装饰音无 <duration>，
                                  //   不推进时间轴。简谱可用小音符或特殊记号表示。

    std::string type;              // whole/half/quarter/eighth/16th/...
    int dots = 0;                  // 附点个数
    bool tieStart = false;         // <tie type="start">
    bool tieStop  = false;         // <tie type="stop">
};

// 小节
struct Measure {
    int number = 0;                // 小节号（来自 measure@number）
    std::vector<Note> notes;       // 本小节内音符（按出现顺序；和弦后续音已并入
                                  //   chordPitches，不再单独入此列表，故不会重复计数）

    // 真实事件数（不含被合并的和弦音），阶段 2 统计/校验用
    int totalEvents() const {
        int n = 0;
        for (const auto& nt : notes)
            if (nt.chordPitches.empty()) ++n;  // 和弦主音算 1 个事件
            else ++n;                          // 单音/休止也都是 1 个事件
        return static_cast<int>(notes.size());
    }
};

// 全局属性（通常出现在首个小节的 <attributes>）
struct ScoreAttributes {
    int divisions = 1;             // 1 个四分音符 = divisions 个 duration 单位
    int fifths = 0;                // 调号（五度圈步数）：0=C, 1=G, -1=F ...
    std::string mode = "major";    // major / minor
    int beats = 4;                 // 拍号分子
    int beatType = 4;              // 拍号分母
    std::string clefSign = "G";    // 谱号
    int clefLine = 2;              // 谱号线
};

// 声部（单声部时 parts.size() == 1）
struct Part {
    std::string id;                // 对应 part-list 里的 score-part@id
    std::string name;              // part-name
    ScoreAttributes attributes;    // 该声部的全局属性
    std::vector<Measure> measures; // 小节序列
};

// 整个乐谱
struct Score {
    std::string title;             // 便捷字段：优选出的主标题（见 pickTitle）
    std::vector<Credit> credits;   // 全部抬头行（movement-title/work-title 之外，
                                  //   来自 <credit>/<credit-words>）
    std::vector<Part> parts;       // 声部列表

    bool isEmpty() const { return parts.empty(); }

    // 从 credits 中优选主标题：取纵坐标 defaultY 最大（最靠上）的有效行；
    //   无 defaultY 时取第一条有效行。credit 顺序通常先标题后作者，故最靠上≈标题。
    //   movement-title / work-title 已优先写入 title，仅当其为空时才回退到 credit。
    void pickTitle() {
        if (!title.empty()) return;          // 已经有更权威的标题，不再回退
        int bestY = -1;
        const Credit* best = nullptr;
        for (const auto& c : credits) {
            if (!c.isValid()) continue;      // 跳过空行
            if (c.defaultY > bestY) {        // 越靠上(defaultY 越大)越优先
                bestY = c.defaultY;
                best = &c;
            }
        }
        if (best) title = best->trimmed();
    }
};

} // namespace pudu

#endif // PUDU_SCORE_MODEL_HPP
