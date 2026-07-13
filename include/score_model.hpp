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

// 音符（或休止符）
struct Note {
    bool isRest = false;           // true=休止符（无 pitch）
    Pitch pitch;                   // 音高（休止符时忽略）
    long duration = 0;             // 时值整数（单位 = divisions）
    std::string type;              // whole/half/quarter/eighth/16th/...
    int dots = 0;                  // 附点个数
    bool tieStart = false;         // <tie type="start">
    bool tieStop  = false;         // <tie type="stop">
};

// 小节
struct Measure {
    int number = 0;                // 小节号（来自 measure@number）
    std::vector<Note> notes;       // 本小节内音符（按出现顺序）
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
    std::string title;             // 可选（movement-title / work-title）
    std::vector<Part> parts;       // 声部列表

    bool isEmpty() const { return parts.empty(); }
};

} // namespace pudu

#endif // PUDU_SCORE_MODEL_HPP
