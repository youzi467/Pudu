#ifndef PUDU_TEST_HELPERS_HPP
#define PUDU_TEST_HELPERS_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 测试 fixture 构造辅助（inline，跨 TU 无 ODR 问题）
//   仅构造最小 Score 内存模型，用于 staffToJianpu 端到端用例，
//   不依赖 MusicXML 解析 / pugixml。
// ----------------------------------------------------------------------

#include "score_model.hpp"

#include <string>
#include <vector>

namespace pudu {

// 构造一个有效音高（hasValue=true）
inline Pitch mkPitch(char step, int alter, int octave) {
    Pitch p;
    p.step = step;
    p.alter = alter;
    p.octave = octave;
    p.hasValue = true;
    return p;
}

// 构造一个实音音符
inline Note mkNote(const Pitch& p, const std::string& type,
                   int onset, int voice = 1, int dots = 0) {
    Note n;
    n.isRest = false;
    n.pitch = p;
    n.type = type;
    n.onset = onset;
    n.voice = voice;
    n.dots = dots;
    return n;
}

// 构造一个休止符
inline Note mkRest(const std::string& type, int onset, int voice = 1) {
    Note n;
    n.isRest = true;
    n.type = type;
    n.onset = onset;
    n.voice = voice;
    return n;
}

// 构造单声部（MVP）Score：给定调号/拍号/小节序列
inline Score mkScore(int fifths, const std::string& mode,
                     int beats, int beatType,
                     const std::vector<Measure>& measures,
                     const std::string& title = "") {
    Score s;
    s.title = title;
    Part part;
    part.id = "P1";
    part.name = "P1";
    part.attributes.fifths = fifths;
    part.attributes.mode = mode;
    part.attributes.beats = beats;
    part.attributes.beatType = beatType;
    part.measures = measures;
    s.parts.push_back(part);
    return s;
}

} // namespace pudu

#endif // PUDU_TEST_HELPERS_HPP
