// ----------------------------------------------------------------------
// 谱渡 Pudu · G4 简谱文本输入解析器实现（L1 文本 -> L0 文档）
//
// 严格逆 renderJianpuNote（jianpu_converter.cpp），支持其输出格式及常见简谱
// 文本简写。详见 include/jianpu_text_parser.hpp。
//
// 语法（与 jianpuToL1 输出一一对应）：
//   标题行    ：任意非空文本（首个非空、且不像 1=.../不以 voice 开头的行）
//   调号头行  ：1=<调名> [beats/beatType] [(mode)]   如 "1=C 4/4 (major)"
//   声部行    ：voiceN: <音符序列>  音符用空格分隔，| 与 || 为小节分隔符
//   单音 token：
//     休止       0
//     装饰音前缀 g（在数字前）
//     记号       # Sharp  b Flat  n Natural  x DoubleSharp  bb DoubleFlat
//     和弦       [主音 其余音级...]  如 [1 3 5]（主音固定括号内第一个）
//     八度点     '（octaveDots+1，可多个）  ,（octaveDots-1，可多个）
//     增时线      -（augmentDashes+1，可多个；如  - =二分， - - - =全音符）
//     减时线     _（underlines+1，可多个：1=八分、2=十六、3=三十二、4=六十四）
//     附点       .（dots+1，可多个；1=×1.5，2=×1.75）
//     连音线     ~（tieToNext=true）
// ----------------------------------------------------------------------

#include "jianpu_text_parser.hpp"

#include "jianpu_to_staff.hpp"   // 仅为与既有架构保持一致（同含 score_model.hpp）
#include "transpose.hpp"          // parseKeyName：调名 -> (fifths, mode)

#include <algorithm>   // std::find / std::sort 等（MSVC 不隐式带入，显式 include）
#include <cctype>      // std::isdigit / std::isspace
#include <cstdlib>     // std::stoi
#include <exception>   // std::exception
#include <sstream>     // std::istringstream
#include <stdexcept>   // std::invalid_argument（parseKeyName 可能抛出）
#include <string>
#include <vector>

namespace pudu {

namespace {

// ---- 小工具 ----

// 去除首尾空白（含 \r）
std::string trim(const std::string& s) {
    size_t b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return {};
    size_t e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

// 转小写（ASCII）
std::string toLower(std::string s) {
    for (char& c : s)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>('a' + (c - 'A'));
    return s;
}

// 按空白切分
std::vector<std::string> splitWs(const std::string& s) {
    std::vector<std::string> out;
    std::istringstream iss(s);
    std::string tok;
    while (iss >> tok) out.push_back(tok);
    return out;
}

// 解析并校验一个音级字符串（0=休止, 1-7=音级）。越界/非数字 -> false。
bool parseDegree(const std::string& s, int& out, std::string& err) {
    if (s.empty()) { err = "空音级"; return false; }
    for (char c : s)
        if (!std::isdigit(static_cast<unsigned char>(c))) {
            err = "音级含非数字字符: " + s;
            return false;
        }
    try {
        int d = std::stoi(s);
        if (d < 0 || d > 7) {
            err = "非法音级(必须为 0-7): " + s;
            return false;
        }
        out = d;
        return true;
    } catch (const std::exception&) {
        err = "音级解析失败: " + s;
        return false;
    }
}

// 单音 quarterLength（与 jianpu_to_staff.cpp 的 reverseRhythm + dotFactor 同口径）。
//   augmentDashes/underlines 决定基准时值，dots 决定附点因子。
double noteQuarterLength(const JianpuNote& jn) {
    double base = 1.0;
    if (jn.augmentDashes == 3 && jn.underlines == 0)      base = 4.0;    // 全音符
    else if (jn.augmentDashes == 1 && jn.underlines == 0) base = 2.0;    // 二分
    else if (jn.augmentDashes == 0 && jn.underlines == 0) base = 1.0;    // 四分
    else if (jn.augmentDashes == 0 && jn.underlines == 1) base = 0.5;    // 八分
    else if (jn.augmentDashes == 0 && jn.underlines == 2) base = 0.25;   // 十六分
    else if (jn.augmentDashes == 0 && jn.underlines == 3) base = 0.125;  // 三十二分
    else if (jn.augmentDashes == 0 && jn.underlines == 4) base = 0.0625; // 六十四分
    else base = 1.0;                                                // 非法组合回退四分
    double dot = (jn.dots >= 2) ? 1.75 : (jn.dots == 1 ? 1.5 : 1.0);
    return base * dot;
}

// 重算当前小节累计 quarterLength（用于设置下一音 onset 与增时线推进游标）。
double recomputeCursor(const std::vector<JianpuNote>& notes) {
    double c = 0.0;
    for (const auto& n : notes) c += noteQuarterLength(n);
    return c;
}

// ---- 单音 token 解析（严格逆 renderJianpuNote） ----
bool parseNoteToken(const std::string& tok, JianpuNote& jn, std::string& err) {
    if (tok.empty()) { err = "空音符记号"; return false; }
    size_t i = 0;

    // 装饰音前缀 g
    if (tok[i] == 'g') { jn.isGrace = true; ++i; }

    // 临时记号（注意 bb 占两字符，必须先于单字符 b 判定）
    if (tok.compare(i, 2, "bb") == 0) {
        jn.accidental = Accidental::DoubleFlat; i += 2;
    } else if (tok[i] == '#') {
        jn.accidental = Accidental::Sharp; ++i;
    } else if (tok[i] == 'b') {
        jn.accidental = Accidental::Flat; ++i;
    } else if (tok[i] == 'n') {
        jn.accidental = Accidental::Natural; ++i;
    } else if (tok[i] == 'x') {
        jn.accidental = Accidental::DoubleSharp; ++i;
    }

    // 和弦 [主音 其余音级...] 或 单音 数字
    if (i < tok.size() && tok[i] == '[') {
        size_t close = tok.find(']', i);
        if (close == std::string::npos) {
            err = "和弦括号未闭合: " + tok;
            return false;
        }
        std::string inner = tok.substr(i + 1, close - i - 1);
        std::vector<std::string> parts = splitWs(inner);
        if (parts.empty()) {
            err = "和弦为空: " + tok;
            return false;
        }
        std::vector<int> degs;
        for (const auto& p : parts) {
            int d = 0;
            if (!parseDegree(p, d, err)) return false;
            degs.push_back(d);
        }
        jn.degree = degs[0];
        for (size_t k = 1; k < degs.size(); ++k)
            jn.chordDegrees.push_back(degs[k]);
        i = close + 1;
    } else {
        // 单音：读取连续数字作为音级
        std::string num;
        while (i < tok.size() && std::isdigit(static_cast<unsigned char>(tok[i]))) {
            num += tok[i];
            ++i;
        }
        if (num.empty()) {
            err = "音符缺少音级数字: " + tok;
            return false;
        }
        int d = 0;
        if (!parseDegree(num, d, err)) return false;
        jn.degree = d;
    }

    // 后续修饰符：' 升八度点  , 降八度点  . 附点  _ 减时线  ~ 连音线
    for (; i < tok.size(); ++i) {
        char c = tok[i];
        if (c == '\'')      jn.octaveDots++;
        else if (c == ',')  jn.octaveDots--;
        else if (c == '.')  jn.dots++;
        else if (c == '_')  jn.underlines++;
        else if (c == '~')  jn.tieToNext = true;
        else {
            err = std::string("音符记号含非法字符 '") + c + "': " + tok;
            return false;
        }
    }
    return true;
}

// 把声部行内容切分为 token；和弦 [..] 视为单个 token（含内部空格），
// 每个 '|' 为独立的小节分隔符 token。
std::vector<std::string> tokenizeVoice(const std::string& s) {
    std::vector<std::string> toks;
    std::string cur;
    bool inBracket = false;
    for (char c : s) {
        if (inBracket) {
            cur += c;
            if (c == ']') {
                toks.push_back(cur);
                cur.clear();
                inBracket = false;
            }
        } else if (c == '[') {
            // 不 flush：把 '[' 及其前缀（如 g#）并入同一个和弦 token，
            // 保证 renderJianpuNote 产生的 #[1 3 5] 整体成词（严格逆渲染器）。
            cur += c;
            inBracket = true;
        } else if (c == '|') {
            if (!cur.empty()) { toks.push_back(cur); cur.clear(); }
            toks.push_back("|");
        } else if (std::isspace(static_cast<unsigned char>(c))) {
            if (!cur.empty()) { toks.push_back(cur); cur.clear(); }
        } else {
            cur += c;
        }
    }
    if (!cur.empty()) toks.push_back(cur);
    return toks;
}

// ---- 调号头行解析：1=<调名> [beats/beatType] [(mode)] ----
bool parseHeader(const std::string& line, JianpuDoc& out, std::string& err) {
    // line 以 "1=" 开头，去掉前缀
    std::string rest = line.substr(2);
    std::vector<std::string> toks = splitWs(rest);
    if (toks.empty()) {
        err = "调号头行缺少调名";
        return false;
    }
    const std::string& keyname = toks[0];

    // 复用 parseKeyName 求 fifths（无法解析则抛错，这里捕获为 false）
    int fifths = 0;
    std::string keyMode = "major";
    try {
        auto [f, m] = parseKeyName(keyname, "major");
        fifths = f;
        keyMode = m;
    } catch (const std::exception& e) {
        err = std::string("无法解析调名 '") + keyname + "': " + e.what();
        return false;
    }
    out.fifths = fifths;
    out.tonicLabel = "1=" + keyname;

    // 解析 beats/beatType 与 mode（括号或裸 major/minor）
    std::string explicitMode;
    for (size_t i = 1; i < toks.size(); ++i) {
        const std::string& t = toks[i];
        size_t slash = t.find('/');
        if (slash != std::string::npos) {
            try {
                int b = std::stoi(t.substr(0, slash));
                int bt = std::stoi(t.substr(slash + 1));
                if (b > 0 && bt > 0) { out.beats = b; out.beatType = bt; }
            } catch (const std::exception&) { /* 非数字则忽略，保留默认 4/4 */ }
            continue;
        }
        if (!t.empty() && t.front() == '(' && t.back() == ')') {
            std::string mm = trim(t.substr(1, t.size() - 2));
            if (!mm.empty()) explicitMode = mm;
            continue;
        }
        std::string low = toLower(t);
        if (low == "major" || low == "minor") { explicitMode = low; continue; }
    }

    out.mode = explicitMode.empty() ? keyMode : explicitMode;
    return true;
}

// ---- 声部行解析：voiceN: <音符序列> ----
bool parseVoiceLine(const std::string& line, JianpuLine& out, std::string& err) {
    size_t colon = line.find(':');
    if (colon == std::string::npos) {
        err = "声部行缺少 ':': " + line;
        return false;
    }
    std::string prefix = line.substr(0, colon);   // "voice12"
    std::string content = line.substr(colon + 1);

    std::string numPart = prefix.substr(5);        // "voice" 之后的编号
    if (numPart.empty()) {
        err = "声部行缺少声部编号: " + line;
        return false;
    }
    int voice = 0;
    try {
        voice = std::stoi(numPart);
    } catch (const std::exception&) {
        err = "声部编号非法: " + prefix;
        return false;
    }
    if (voice < 1) {
        err = "声部编号必须 >= 1: " + prefix;
        return false;
    }
    out.voice = voice;
    out.partIndex = voice - 1;

    std::vector<std::string> toks = tokenizeVoice(content);

    JianpuMeasure cur;
    cur.number = 1;
    double measureCursor = 0.0;
    int mnum = 1;

    for (const auto& tok : toks) {
        if (tok == "|") {
            // 小节分隔：仅当当前小节含音符才落盘，避免空小节
            if (!cur.notes.empty()) out.measures.push_back(cur);
            cur = JianpuMeasure{};
            ++mnum;
            cur.number = mnum;
            measureCursor = 0.0;
            continue;
        }
        if (tok == "-") {
            // 增时线：作用于当前小节最后一个音
            if (!cur.notes.empty()) {
                cur.notes.back().augmentDashes++;
                measureCursor = recomputeCursor(cur.notes);
            }
            continue;
        }
        JianpuNote jn;
        if (!parseNoteToken(tok, jn, err)) return false;
        jn.onset = measureCursor;             // onset = 当前小节累计 quarterLength
        cur.notes.push_back(jn);
        measureCursor = recomputeCursor(cur.notes);
    }

    // 收尾：最后一个小节若有音符则落盘
    if (!cur.notes.empty()) out.measures.push_back(cur);
    return true;
}

} // anonymous namespace

bool parseJianpuText(const std::string& text, JianpuDoc& out, std::string& err) {
    out = JianpuDoc{};   // 进入即清空，避免调用方残留数据泄漏
    err.clear();

    // 按行切分（兼容 \r\n）
    std::vector<std::string> lines;
    {
        std::istringstream iss(text);
        std::string ln;
        while (std::getline(iss, ln)) {
            if (!ln.empty() && ln.back() == '\r') ln.pop_back();
            lines.push_back(ln);
        }
    }

    bool foundHeader = false;
    bool foundTitle = false;

    for (const auto& rawLine : lines) {
        std::string line = trim(rawLine);
        if (line.empty()) continue;

        if (line.rfind("1=", 0) == 0) {                 // 调号头行
            if (!parseHeader(line, out, err)) return false;
            foundHeader = true;
        } else if (line.rfind("voice", 0) == 0) {       // 声部行
            JianpuLine jl;
            if (!parseVoiceLine(line, jl, err)) return false;
            out.lines.push_back(std::move(jl));
        } else if (!foundTitle) {                       // 标题行（首个符合条件的）
            out.title = line;
            foundTitle = true;
        }
        // 其余非头/非声部的行忽略（容错）
    }

    if (!foundHeader) {
        err = "缺少调号头行（应以 '1=' 开头，如 '1=C 4/4 (major)'）";
        return false;
    }
    return true;
}

} // namespace pudu
