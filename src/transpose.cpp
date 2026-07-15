// ----------------------------------------------------------------------
// 谱渡 Pudu · 变调重算实现（see include/transpose.hpp）
// 设计：单一事实源 = canonical Score；变调在 Score 上平移音高(或仅改调号)，
//       再复用 staffToJianpu 产出 JianpuDoc（保证 L0↔Score 自洽，阶段 3 前置）。
// 不引入新音级算法，复用 fifthsToTonicPc / midiToJianpu。
// ----------------------------------------------------------------------

#include "transpose.hpp"

#include <algorithm>
#include <cctype>
#include <climits>
#include <cstdlib>
#include <map>
#include <stdexcept>
#include <utility>

namespace pudu {

// 升号拼写表：pc -> (step, alter)（用于目标为升号调时的 out-of-scale 音）
const std::pair<char, int> kSharpSpelling[12] = {
    {'C', 0}, {'C', 1}, {'D', 0}, {'D', 1}, {'E', 0}, {'F', 0},
    {'F', 1}, {'G', 0}, {'G', 1}, {'A', 0}, {'A', 1}, {'B', 0}
};
// 降号拼写表：pc -> (step, alter)（用于目标为降号调时）
const std::pair<char, int> kFlatSpelling[12] = {
    {'C', 0}, {'D', -1}, {'D', 0}, {'E', -1}, {'E', 0}, {'F', 0},
    {'G', -1}, {'G', 0}, {'A', -1}, {'A', 0}, {'B', -1}, {'B', 0}
};

// MIDI -> Pitch（按 preferSharp 选择拼写；仅影响 out-of-scale 音的 ♯/♭ 方向）。
//   声明见 transpose.hpp；阶段 3 jianpuToStaff 复用，保证音名拼写字节级一致。
Pitch midiToPitch(int midi, bool preferSharp) {
    Pitch p;
    int pc = ((midi % 12) + 12) % 12;
    int octave = midi / 12 - 1;
    const auto& sp = preferSharp ? kSharpSpelling[pc] : kFlatSpelling[pc];
    p.step = sp.first;
    p.alter = sp.second;
    p.octave = octave;
    p.hasValue = true;
    return p;
}

namespace {

// 平移单个 Pitch（通过 MIDI 中转，避免 step/alter 进位错误）
void shiftPitch(Pitch& p, int delta, bool preferSharp) {
    if (!p.hasValue) return;
    p = midiToPitch(p.midiNumber() + delta, preferSharp);
}

std::string trimCopy(const std::string& s) {
    size_t b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return {};
    size_t e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

// 去空白、转小写、♯/♭/♮(UTF-8 三字节) -> #/b/#。
//   ♯ = E2 99 AF, ♭ = E2 99 AD, ♮ = E2 99 AE。
//   其余多字节字符（中文等）原样保留，交由上层解析（无法识别自然抛错）。
std::string normalizeKey(const std::string& s) {
    std::string o = trimCopy(s);
    std::string out;
    out.reserve(o.size());
    for (size_t i = 0; i < o.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(o[i]);
        // 识别 UTF-8 三字节变音记号
        if (c == 0xE2 && i + 2 < o.size()) {
            unsigned char c1 = static_cast<unsigned char>(o[i + 1]);
            unsigned char c2 = static_cast<unsigned char>(o[i + 2]);
            if (c1 == 0x99 && (c2 == 0xAF || c2 == 0xAD || c2 == 0xAE)) {
                out += (c2 == 0xAD) ? 'b' : '#';   // ♭ -> b，♯/♮ -> #
                i += 2;
                continue;
            }
        }
        if (c >= 'A' && c <= 'Z') c = static_cast<unsigned char>('a' + (c - 'A'));
        out += static_cast<char>(c);
    }
    return out;
}

// 大小调名 -> fifths 表（已规范化：小写、#/♭）
const std::map<std::string, int>& majorTable() {
    static const std::map<std::string, int> t = {
        {"c", 0}, {"g", 1}, {"d", 2}, {"a", 3}, {"e", 4}, {"b", 5},
        {"f#", 6}, {"c#", 7},
        {"f", -1}, {"bb", -2}, {"eb", -3}, {"ab", -4}, {"db", -5}, {"gb", -6}, {"cb", -7}
    };
    return t;
}
const std::map<std::string, int>& minorTable() {
    static const std::map<std::string, int> t = {
        {"a", 0}, {"e", 1}, {"b", 2}, {"f#", 3}, {"c#", 4}, {"g#", 5},
        {"d#", 6}, {"a#", 7},
        {"d", -1}, {"g", -2}, {"c", -3}, {"f", -4}, {"bb", -5}, {"eb", -6}, {"ab", -7}
    };
    return t;
}

} // anonymous namespace

std::pair<int, std::string> parseKeyName(const std::string& name,
                                         const std::string& defaultMode) {
    std::string norm = normalizeKey(name);
    bool minor = (defaultMode == "minor");
    if (norm.size() >= 5 && norm.substr(norm.size() - 5) == "minor") {
        minor = true; norm = trimCopy(norm.substr(0, norm.size() - 5));
    } else if (norm.size() >= 5 && norm.substr(norm.size() - 5) == "major") {
        norm = trimCopy(norm.substr(0, norm.size() - 5));   // 大调：minor 维持 default
    } else if (norm.size() >= 6 && norm.substr(norm.size() - 6) == "\xe5\xb0\x8f\xe8\xb0\x83") {
        // "小调" UTF-8（2 个汉字 = 6 字节）
        minor = true; norm = trimCopy(norm.substr(0, norm.size() - 6));
    } else if (norm.size() >= 2 && norm.back() == 'm' && norm != "m") {
        minor = true; norm = trimCopy(norm.substr(0, norm.size() - 1));
    }

    const auto& table = minor ? minorTable() : majorTable();
    auto it = table.find(norm);
    if (it == table.end())
        throw std::invalid_argument("无法识别的调名: " + name);
    return {it->second, minor ? "minor" : "major"};
}

int tonicNameToFifths(const std::string& name, const std::string& mode) {
    return parseKeyName(name, mode).first;
}

int semitonesToFifths(int semitones) {
    int pc = ((semitones % 12) + 12) % 12;
    int sign = (semitones > 0) ? 1 : (semitones < 0) ? -1 : 0;
    int sameSign = 0, sameSignAbs = 100;   // 同号且最近（优先）
    int any = 0, anyAbs = 100;              // 兜底：任意最近
    for (int f = -7; f <= 7; ++f) {
        if (fifthsToTonicPc(f) != pc) continue;
        int a = std::abs(f);
        if (a < anyAbs) { anyAbs = a; any = f; }
        bool match = (sign == 0) ? (f == 0)
                                 : ((f > 0 && sign > 0) || (f < 0 && sign < 0));
        if (match && a < sameSignAbs) { sameSignAbs = a; sameSign = f; }
    }
    return (sameSignAbs != 100) ? sameSign : any;
}

int transposeScore(Score& score, const TransposeTarget& target, TransposeMode mode) {
    if (score.isEmpty())
        throw std::invalid_argument("transposeScore: score 为空，无法变调");

    const ScoreAttributes& srcAttr = score.parts[0].attributes;
    int srcPc = fifthsToTonicPc(srcAttr.fifths);

    int delta;
    if (mode == TransposeMode::Rekey) {
        delta = 0;   // 听感不变，仅改写调号
    } else if (target.semitones != INT_MIN) {
        delta = target.semitones;   // 字面位移（--transpose ±N）
    } else {
        int tgtPc = fifthsToTonicPc(target.fifths);
        delta = tgtPc - srcPc;
        if (delta > 6) delta -= 12; // 取 [-6,6] 内最近路径，避免跨八度跳变
        if (delta < -6) delta += 12;
    }

    // 拼写偏好：按目标调号决定（升号调用 ♯，降号调用 ♭），与音乐记谱惯例一致。
    bool preferSharp = (target.fifths >= 0);

    if (mode == TransposeMode::Transpose && delta != 0) {
        for (auto& part : score.parts)
            for (auto& m : part.measures)
                for (auto& n : m.notes) {
                    if (!n.isRest) {
                        shiftPitch(n.pitch, delta, preferSharp);
                        for (auto& cp : n.chordPitches)
                            shiftPitch(cp, delta, preferSharp);
                    }
                }
    }

    // 两模式都更新调号（key 标签）。多声部统一改写。
    for (auto& part : score.parts) {
        part.attributes.fifths = target.fifths;
        if (!target.mode.empty())
            part.attributes.mode = target.mode;
    }
    return delta;
}

JianpuDoc transposeStaffToJianpu(const Score& score,
                                 const TransposeTarget& target,
                                 TransposeMode mode) {
    Score copy = score;   // 按值拷贝（Score 全值语义，无指针/引用成员）
    transposeScore(copy, target, mode);
    return staffToJianpu(copy);
}

} // namespace pudu
