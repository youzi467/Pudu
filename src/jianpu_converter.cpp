// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 2 简谱转换器实现（Score -> JianpuDoc）
// 依据 omr-tool-research/jianpu_output_spec.md §2/§4 实现。
// 不回改 Score：仅读取，结果是一份 L0 语义投影。
// ----------------------------------------------------------------------

#include "jianpu_converter.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <utility>
#include <vector>

namespace pudu {

// 调号 -> 调名字母（规范 §2.4）
std::string fifthsToTonicName(int fifths, const std::string& /*mode*/) {
    // 大调表（按 fifths 绝对值索引；正负分别走升号/降号序列）
    static const std::string kMajorPos[] = {"C", "G", "D", "A", "E", "B", "F#", "C#"};
    static const std::string kMajorNeg[] = {"C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"};
    int idx = (fifths >= 0) ? fifths : -fifths;
    if (idx > 7) idx = 7;
    // 小调采用首调相对法（1=关系大调主音）：直接返回同名大调字母即可，
    // 关系大调与本调共享同一调号(fifths 相同)。"6=X" 标法后置。
    return (fifths >= 0) ? kMajorPos[idx] : kMajorNeg[idx];
}

// 绝对音高 -> 首调音级 / 临时记号 / 八度点（规范 §2.1 / §2.2）
void midiToJianpu(const Pitch& p, int tonicPc,
                  int& outDegree, Accidental& outAccidental, int& outOctaveDots) {
    int M = p.midiNumber();
    int semi = (M - tonicPc) % 12;       // 相对主音的半音数 0-11
    if (semi < 0) semi += 12;

    // 大调音阶模板：semi -> 音级(1-7)，非音阶位置为 0
    //   {0:1, 2:2, 4:3, 5:4, 7:5, 9:6, 11:7}
    static const int kMajorScale[12] = {1, 0, 2, 0, 3, 4, 0, 5, 0, 6, 0, 7};

    if (kMajorScale[semi] != 0) {
        outDegree = kMajorScale[semi];
        outAccidental = Accidental::None;
    } else {
        // 调外音：落到相邻音级，记号方向按谱面 alter 择优（规范 §2.1 / §5 case 2）
        //   alter<0 -> 取(semi+1)音级 + Flat（向上借邻级，如 b7）
        //   alter>0 -> 取(semi-1)音级 + Sharp（向下借邻级，如 #4）
        //   alter==0（调外自然音，如 D 大调中的 C）-> 取上方邻级 + Flat，
        //     得到 b7 而非 #6，符合 §5 case 2 示例。
        //     注：完整等音异名拼写法（如 F 大调 B 自然应记 #4）仍属后置边界。
        if (p.alter < 0) {
            int base = (semi + 1) % 12;
            outDegree = kMajorScale[base];
            outAccidental = Accidental::Flat;
        } else if (p.alter > 0) {
            int base = (semi - 1 + 12) % 12;
            outDegree = kMajorScale[base];
            outAccidental = Accidental::Sharp;
        } else {
            int base = (semi + 1) % 12;
            outDegree = kMajorScale[base];
            outAccidental = Accidental::Flat;
        }
    }

    // 八度点：以参考八度主音(第4组, MIDI = tonicPc + 60)为 0 点，
    //   每差 12 半音 ±1 点。floor 而非整数除法，避免负数截断错误（规范 §2.2）。
    int tonicRefMidi = tonicPc + 60;
    double d = static_cast<double>(M - tonicRefMidi) / 12.0;
    outOctaveDots = static_cast<int>(std::floor(d));
}

// 时值 type -> (减时线, 增时线)（规范 §2.3 表）
void typeToDuration(const std::string& type, int& outUnderlines, int& outAugmentDashes) {
    if (type == "whole")        { outAugmentDashes = 3; outUnderlines = 0; }
    else if (type == "half")    { outAugmentDashes = 1; outUnderlines = 0; }
    else if (type == "quarter") { outAugmentDashes = 0; outUnderlines = 0; }
    else if (type == "eighth")  { outAugmentDashes = 0; outUnderlines = 1; }
    else if (type == "16th")    { outAugmentDashes = 0; outUnderlines = 2; }
    else if (type == "32nd")    { outAugmentDashes = 0; outUnderlines = 3; }
    else if (type == "64th")    { outAugmentDashes = 0; outUnderlines = 4; }
    else { outAugmentDashes = 0; outUnderlines = 0; }  // 未知/缺失 -> 默认四分
}

// 由 quarterLength 反推 (减时线, 增时线, 附点)（规范 §2.3 表）。
// 与校验器 verify_jianpu_groundtruth.py 的 expected_rhythm 使用同一组基准，
// 保证跨语言一致；无法映射到标准时值（如连音组 2/3、4/5 拍）返回 false。
// 背景：部分源 MusicXML 的 <type> 与 <duration> 不一致，以实际 quarterLength
// 为准更稳健。解析器已在 Note.quarterLength 按生效 <divisions> 换算好。
bool quarterLengthToRhythm(double ql, int& outUnderlines, int& outAugmentDashes, int& outDots) {
    static const double kBases[] = {4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625};
    static const int kAug[]       = {  3,   1,   0,   0,    0,     0,      0};
    static const int kUl[]        = {  0,   0,   0,   1,    2,     3,      4};
    for (int i = 0; i < 7; ++i) {
        if (std::fabs(ql - kBases[i])       < 1e-4) { outUnderlines = kUl[i]; outAugmentDashes = kAug[i]; outDots = 0; return true; }
        if (std::fabs(ql - kBases[i] * 1.5) < 1e-4) { outUnderlines = kUl[i]; outAugmentDashes = kAug[i]; outDots = 1; return true; }
        if (std::fabs(ql - kBases[i] * 1.75) < 1e-4) { outUnderlines = kUl[i]; outAugmentDashes = kAug[i]; outDots = 2; return true; }
    }
    return false;  // 非标准时值（连音组等）
}

// 主转换（规范 §4 伪代码）
JianpuDoc staffToJianpu(const Score& score) {
    JianpuDoc doc;
    if (score.isEmpty()) return doc;

    doc.title = score.title;

    // 全局属性取首声部（MVP 单声部；多声部各自属性在后续扩展中按 part 细化）
    const ScoreAttributes& attr = score.parts[0].attributes;
    doc.mode = attr.mode;
    doc.beats = attr.beats;
    doc.beatType = attr.beatType;
    doc.fifths = attr.fifths;   // 供 --to-jianpu-json 校验器还原主音音级
    doc.tonicLabel = "1=" + fifthsToTonicName(attr.fifths, attr.mode);

    int tonicPc = fifthsToTonicPc(attr.fifths);

    for (size_t pi = 0; pi < score.parts.size(); ++pi) {
        const auto& part = score.parts[pi];
        // 收集本声部出现的 voice 集合（多声部 -> 多行，保持既有 L0/L1/L3 语义不变）。
        //   P2 只读谱表号并透传到 line.staff 供 L2 大谱表分组，不改 L0 的行划分。
        std::set<int> voiceSet;
        for (const auto& m : part.measures)
            for (const auto& n : m.notes)
                voiceSet.insert(n.voice);

        for (int voice : voiceSet) {
            JianpuLine line;
            line.voice = voice;
            line.partIndex = static_cast<int>(pi);
            // P2：本声部音符的谱表归属（同一声部通常固定在一根谱表）。取最大值；
            //   单谱表 / 未标注时为 0，不影响既有行为与 L1/L3 输出。
            int lineStaff = 0;
            for (const auto& m : part.measures)
                for (const auto& n : m.notes)
                    if (n.voice == voice && n.staff > lineStaff) lineStaff = n.staff;
            line.staff = lineStaff;   // 仅供 L2 大谱表分组；pair 恒 -1，渲染器再配对

            for (const auto& measure : part.measures) {
                JianpuMeasure jm;
                jm.number = measure.number;
                // P1-1：透传本小节拍号与不完全小节标记（供后处理引擎逐小节对账）。
                //   单声部单拍号 fixture 的 Score::Measure.beats 默认 0，这里原样透传，
                //   后处理回退到 doc.beats/beatType，行为与改动前逐字节一致。
                jm.beats = measure.beats;
                jm.beatType = measure.beatType;
                jm.implicit = measure.implicit;
                jm.sectionEnd = measure.sectionEnd;

                // 仅取本 voice 的音符，按 onset 升序（非常段既有语义，L1/L3 不变）
                std::vector<const Note*> sel;
                for (const auto& n : measure.notes)
                    if (n.voice == voice) sel.push_back(&n);
                std::sort(sel.begin(), sel.end(),
                          [](const Note* a, const Note* b) { return a->onset < b->onset; });

                for (const Note* np : sel) {
                    const Note& n = *np;
                    JianpuNote jn;

                    if (n.isRest) {
                        jn.degree = 0;        // 休止
                    } else {
                        int deg; Accidental acc; int od;
                        midiToJianpu(n.pitch, tonicPc, deg, acc, od);
                        jn.degree = deg;
                        jn.accidental = acc;
                        jn.octaveDots = od;
                    }

                    // 节奏：以实际 quarterLength 为准（稳健于 <type>/<duration> 不一致，选项 B）。
                    // 连音组：基准时值 = 实际时值 × actual/normal，与校验器(music21 base_ql)同口径；
                    //   源 <type>/<duration> 不一致时以此为准更稳健（如 7:4 三十二分误标）。
                    //   仍无法映射为标准时值(如 7:8/7:4/9:4 的极端比)则回退 <type> 记谱值。
                    int ul, ad, dz;
                    double rhythmQl = n.quarterLength;
                    if (n.tupletActual > 0 && n.tupletNormal > 0)
                        rhythmQl = n.quarterLength * n.tupletActual / n.tupletNormal;
                    if (n.isGrace) {
                        // P1-1 返工：装饰音按定义不占基本时值，MusicXML 中 <grace/>
                        //   音符没有 <duration>，故 quarterLength 恒为 0。此时
                        //   quarterLengthToRhythm(0) 必然失败，若据此置
                        //   rhythmUnresolvable，等于把"合法的装饰音"污染成"时值解析
                        //   失败"——干净出版谱也会被误标（badinerie m40 即此症状），
                        //   进而毒化后处理 BeatReconcile/TupletGroup 的判断。
                        //   装饰音的记谱时值只能来自 <type>，这不是"无法解析"。
                        typeToDuration(n.type, ul, ad);
                        jn.underlines = ul;
                        jn.augmentDashes = ad;
                        jn.dots = n.dots;
                    } else if (quarterLengthToRhythm(rhythmQl, ul, ad, dz)) {
                        jn.underlines = ul;
                        jn.augmentDashes = ad;
                        jn.dots = dz;
                    } else {
                        // M1.5-C：极端连音比(如 7:8/7:4/9:4)无法映射标准简谱时值，
                        // 回退 <type> 记谱，并显式标记该音为未解析（机读、可聚合）。
                        typeToDuration(n.type, ul, ad);
                        jn.underlines = ul;
                        jn.augmentDashes = ad;
                        jn.dots = n.dots;
                        jn.rhythmUnresolvable = true;
                    }

                    jn.onset = n.onset;   // 供校验器跨声部按时间轴归并
                    jn.isGrace = n.isGrace;
                    jn.tieToNext = n.tieStart;   // 延音弧画在本音(起点)上（规范 §2.5）
                    jn.tieFromPrev = n.tieStop;  // M1.5-B：反向还原 tie 的 stop 端

                    // 连音组标注（选项 A）：actual-notes>0 表示属连音组，
                    //   tuplet 存实际音符数(3=三连音,5=五连音...)，供校验器核对分组。
                    //   节奏仍由 quarterLength 反推(连音组回退 <type>，与音乐21 基准时值同口径)。
                    jn.tuplet = (n.tupletActual > 0) ? n.tupletActual : 0;
                    // P1-1：透传连音"常规音符数"(normal-notes)。后处理 BeatReconcile
                    //   优先用它精确折算占拍（2:3 二连音 / 4:3 四连音等非三连音比不再被错算）。
                    jn.tupletNormal = n.tupletNormal;

                    // 和弦：主音已在 degree，其余音各自换算音级（规范 §2.5）。
                    // M1.5-A：逐音八度点按"相对根音"的偏移成对存储，与 chordDegrees 等长。
                    for (const auto& cp : n.chordPitches) {
                        int md; Accidental ma; int mod;
                        midiToJianpu(cp, tonicPc, md, ma, mod);
                        jn.chordDegrees.push_back(md);
                        jn.chordOctaveDots.push_back(mod - jn.octaveDots);
                    }

                    jm.notes.push_back(jn);
                }
                line.measures.push_back(jm);
            }
            doc.lines.push_back(line);
        }
    }
    return doc;
}

// ---- L1 纯文本渲染（验证用，非生产渲染器） ----
namespace {

std::string renderJianpuNote(const JianpuNote& jn) {
    std::string s;
    if (jn.degree == 0) {
        // 休止符：标准简谱不用增时线。带增时线的长休止按拍数拆成多个 "0"
        //   （整小节 4 拍 → "0 0 0 0"，二分休止 2 拍 → "0 0"），总时长不变。
        if (jn.augmentDashes > 0) {
            double beats = (jn.augmentDashes >= 3) ? 4.0 : 2.0;  // 全音符→4 拍，二分→2 拍
            if (jn.dots == 1) beats *= 1.5;                       // 附点 ×1.5
            else if (jn.dots == 2) beats *= 1.75;                 // 复附点 ×1.75
            int n = static_cast<int>(std::lround(beats));
            s = "0";
            for (int i = 1; i < n; ++i) s += " 0";
            if (jn.tieToNext) s += "~";                           // 连音线保留
            return s;   // 休止不再走下方增时线/减时线/附点
        }
        s = "0";                                   // 休止
    } else {
        if (jn.isGrace) s += "g";                  // 装饰音前缀
        switch (jn.accidental) {
            case Accidental::Sharp:       s += "#";  break;
            case Accidental::Flat:        s += "b";  break;
            case Accidental::Natural:     s += "n";  break;
            case Accidental::DoubleSharp: s += "x";  break;
            case Accidental::DoubleFlat:  s += "bb"; break;
            default: break;
        }
        if (!jn.chordDegrees.empty()) {            // 和弦: [主音 其余...]（M1.5-A：逐音八度点）
            s += "[" + std::to_string(jn.degree);
            // 根音的 octaveDots 紧贴根音数字（不套整组和弦括号后）
            if (jn.octaveDots > 0)
                for (int i = 0; i < jn.octaveDots; ++i) s += "'";
            else if (jn.octaveDots < 0)
                for (int i = 0; i < -jn.octaveDots; ++i) s += ",";
            for (size_t k = 0; k < jn.chordDegrees.size(); ++k) {
                s += " " + std::to_string(jn.chordDegrees[k]);
                // 成员音八度点相对根音(chordOctaveDots[k])，紧贴该成员数字
                int od = (k < jn.chordOctaveDots.size()) ? jn.chordOctaveDots[k] : 0;
                if (od > 0)
                    for (int i = 0; i < od; ++i) s += "'";
                else if (od < 0)
                    for (int i = 0; i < -od; ++i) s += ",";
            }
            s += "]";
        } else {
            s += std::to_string(jn.degree);
            if (jn.octaveDots > 0)                 // 升八度点 '
                for (int i = 0; i < jn.octaveDots; ++i) s += "'";
            else if (jn.octaveDots < 0)            // 降八度点 ,
                for (int i = 0; i < -jn.octaveDots; ++i) s += ",";
        }
    }
    for (int i = 0; i < jn.augmentDashes; ++i) s += " -";  // 增时线
    for (int i = 0; i < jn.underlines; ++i) s += "_";      // 减时线
    for (int i = 0; i < jn.dots; ++i) s += ".";            // 附点
    if (jn.tieToNext) s += "~";                             // 连音线（L2 用 SVG 弧）
    return s;
}

} // anonymous namespace

std::string jianpuToL1(const JianpuDoc& doc) {
    std::string out;
    out += doc.title.empty() ? "(无标题)" : doc.title;
    out += "\n";
    out += doc.tonicLabel + " " + std::to_string(doc.beats) + "/" +
           std::to_string(doc.beatType) + "  (" + doc.mode + ")\n";
    for (const auto& line : doc.lines) {
        out += "voice" + std::to_string(line.voice) + ": ";
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            const auto& m = line.measures[mi];
            for (const auto& n : m.notes) out += renderJianpuNote(n) + " ";
            if (mi + 1 < line.measures.size()) out += "| ";
        }
        out += "||\n";
    }
    return out;
}

// ---- L2 HTML/Unicode 二维渲染（规范 §3.2） ----
// 设计：每个音符是一个 .note（相对定位），内部用绝对定位把八度点(上/下)、
// 减时线(下方贯穿)、连音弧(上方)投影到二维；数字与增时线水平居中成一行。
// 同值连续音符(underlines 相同)在小节层连成 beam 组，减时线横向连写为一条/多条贯穿线。
namespace {

std::string l2Escape(const std::string& s) {
    std::string o;
    o.reserve(s.size());
    for (char c : s) {
        switch (c) {
            case '&': o += "&amp;"; break;
            case '<': o += "&lt;";  break;
            case '>': o += "&gt;";  break;
            case '"': o += "&quot;"; break;
            case '\'': o += "&#39;"; break;
            default: o += c;
        }
    }
    return o;
}

// 临时记号 Unicode 字形（显式 UTF-8 字节，避免源码编码问题）
const char* l2Accidental(Accidental a) {
    switch (a) {
        case Accidental::Sharp:       return "\xE2\x99\xAF"; // ♯
        case Accidental::Flat:        return "\xE2\x99\xAD"; // ♭
        case Accidental::Natural:     return "\xE2\x99\xAE"; // ♮
        case Accidental::DoubleSharp: return "x";
        case Accidental::DoubleFlat:  return "bb";
        default: return "";
    }
}

// 八度点：n>0 上方点(·)，n<0 下方点；逐点纵向堆叠
std::string l2OctaveDots(int n) {
    if (n == 0) return "";
    std::string dots;
    int cnt = (n > 0) ? n : -n;
    for (int i = 0; i < cnt; ++i) dots += "<span class=\"jp-dot\">\xC2\xB7</span>"; // ·
    if (n > 0) return "<span class=\"jp-up\">" + dots + "</span>";
    return "<span class=\"jp-down\">" + dots + "</span>";
}

// 增时线（—），k 条，置于数字右侧
std::string l2Augment(int k) {
    if (k <= 0) return "";
    std::string s = "<span class=\"jp-aug\">";
    for (int i = 0; i < k; ++i) {
        if (i) s += " ";               // 多条增时线以空格隔开：— — —
        s += "\xE2\x80\x94"; // —
    }
    s += "</span>";
    return s;
}

// 附点（·），k 个，置于数字右侧
std::string l2Dots(int k) {
    std::string s;
    for (int i = 0; i < k; ++i) s += "<span class=\"jp-dot2\">\xC2\xB7</span>";
    return s;
}

// 连音弧（内联 SVG，位于数字上方）
std::string l2Tie() {
    return "<svg class=\"jp-tie\" viewBox=\"0 0 28 10\" width=\"28\" height=\"10\" "
           "aria-hidden=\"true\"><path d=\"M3 8 Q14 0 25 8\" fill=\"none\" "
           "stroke=\"#1f2933\" stroke-width=\"1.3\" stroke-linecap=\"round\"/></svg>";
}

// 减时线（横向连写）：k 条贯穿横线，height 由 k 决定（repeating-gradient 每 5px 一线）
std::string l2BeamLines(int k) {
    int h = k * 5 - 3;   // k=1→2, k=2→7, k=3→12
    if (h < 2) h = 2;
    return "<span class=\"beam-lines\" style=\"height:" + std::to_string(h) +
           "px;background-image:repeating-linear-gradient(to bottom,"
           "#1f2933 0 1.5px,transparent 1.5px 5px);\"></span>";
}

// 减时线（孤立音符）：仅本数字下方一小段
std::string l2UnderIsolated(int k) {
    if (k <= 0) return "";
    int h = k * 5 - 3;
    if (h < 2) h = 2;
    return "<span class=\"jp-under\" style=\"height:" + std::to_string(h) +
           "px;background-image:repeating-linear-gradient(to bottom,"
           "#1f2933 0 1.5px,transparent 1.5px 5px);\"></span>";
}

// 休止符按拍数拆分的 "0" 个数（标准简谱休止不用增时线）
int l2RestBeats(const JianpuNote& jn) {
    if (jn.augmentDashes <= 0) return 1;
    double beats = (jn.augmentDashes >= 3) ? 4.0 : 2.0;
    if (jn.dots == 1) beats *= 1.5;
    else if (jn.dots == 2) beats *= 1.75;
    return static_cast<int>(std::lround(beats));
}

// 单个音符数字核心：八度点(上/下) + 临时记号(左上角标) + 数字 + 附点。
// 全部封进 .jp-core —— 它是居中与定位的参照，保证八度点/升降号都贴着数字，
// 不会像之前那样锚在宽 .note 单元格上、被增时线撑出而错位。
std::string l2Digit(const JianpuNote& jn) {
    if (jn.degree == 0) {
        // 休止符：不加增时线；长休止按拍数拆成多个 "0"（整小节 → 0 0 0 0）
        int beats = l2RestBeats(jn);
        if (beats <= 1)
            return "<span class=\"jp-num rest\">0</span>";
        std::string s;
        for (int i = 0; i < beats; ++i) {
            if (i) s += "&nbsp;";
            s += "<span class=\"jp-num rest\">0</span>";
        }
        return s;
    }
    std::string core = "<span class=\"jp-core\">";
    core += l2OctaveDots(jn.octaveDots);                // 八度点贴数字顶部/底部
    std::string acc = l2Accidental(jn.accidental);
    if (!acc.empty()) core += "<span class=\"jp-acc\">" + acc + "</span>"; // 左上角标
    core += "<span class=\"jp-num\">" + std::to_string(jn.degree) + "</span>";
    core += l2Dots(jn.dots);
    core += "</span>";
    return core;
}

// 和弦成员音：数字 + 该成员自身八度点（不带临时记号/附点——附点只在根音）
std::string l2ChordMember(int degree, int octaveDots) {
    std::string m = "<span class=\"jp-core\">";
    m += l2OctaveDots(octaveDots);
    m += "<span class=\"jp-num\">" + std::to_string(degree) + "</span>";
    m += "</span>";
    return m;
}

// 音符单元（不含减时线；减时线由小节层 beam 组统一绘制）
std::string l2NoteCell(const JianpuNote& jn) {
    std::string cell = "<span class=\"note";
    if (jn.isGrace) cell += " grace";
    cell += "\">";
    if (jn.tieToNext) cell += l2Tie();
    if (!jn.chordDegrees.empty()) {
        cell += "<span class=\"chord\">";
        cell += l2Digit(jn);   // 根音：八度点/临时记号/附点已在 .jp-core 内
        for (size_t k = 0; k < jn.chordDegrees.size(); ++k) {
            int d = jn.chordDegrees[k];
            int od = (k < jn.chordOctaveDots.size()) ? jn.chordOctaveDots[k] : 0;
            cell += l2ChordMember(d, od);   // M1.5-A：成员音八度点紧贴该成员数字
        }
        cell += "</span>";
    } else {
        cell += l2Digit(jn);
    }
    // 休止符不加增时线（l2Digit 已按拍数拆分为多个 0）
    if (jn.degree != 0) cell += l2Augment(jn.augmentDashes);
    cell += "</span>";
    return cell;
}

// 带孤立减时线的音符（不成 beam 组的单个短音符）
std::string l2NoteCellIsolated(const JianpuNote& jn) {
    std::string cell = l2NoteCell(jn);
    // 在末尾 </span> 前插入减时线
    size_t pos = cell.rfind("</span>");
    if (pos != std::string::npos)
        cell.insert(pos, l2UnderIsolated(jn.underlines));
    return cell;
}

// 单小节：连续同值(underlines)音符连成 beam 组做横向连写
std::string l2Measure(const JianpuMeasure& m) {
    std::string out = "<div class=\"measure\">";
    size_t i = 0;
    while (i < m.notes.size()) {
        const JianpuNote& n = m.notes[i];
        int k = n.underlines;
        if (k > 0) {
            size_t j = i;
            while (j < m.notes.size() && m.notes[j].underlines == k) ++j;
            if (j - i >= 2) {                 // 成组 -> 横向连写
                out += "<span class=\"beam\">";
                for (size_t t = i; t < j; ++t) out += l2NoteCell(m.notes[t]);
                out += l2BeamLines(k);
                out += "</span>";
            } else {                          // 孤立短音符 -> 各自减时线
                out += l2NoteCellIsolated(m.notes[i]);
            }
            i = j;
        } else {
            out += l2NoteCell(n);
            ++i;
        }
    }
    out += "</div>";
    return out;
}

// 最小内联 CSS（浅色主题，自包含、可直接浏览器打开）
const char* kL2Css =
    "*,*::before,*::after{box-sizing:border-box;}"
    "body{margin:0;background:#f5f3ec;color:#1f2933;"
    "font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans SC',sans-serif;}"
    ".score{max-width:920px;margin:32px auto;padding:28px 32px;background:#fffdf7;"
    "border:1px solid #e6e1d3;border-radius:14px;box-shadow:0 8px 30px rgba(60,50,20,.08);}"
    ".header{margin-bottom:16px;border-bottom:2px solid #2b2b2b;padding-bottom:10px;}"
    ".title{font-size:1.5rem;font-weight:600;}"
    ".key{margin-top:4px;color:#5b6470;font-size:.95rem;letter-spacing:.5px;}"
    ".line{display:flex;flex-wrap:wrap;align-items:flex-end;gap:2px;padding:18px 0;"
    "border-bottom:1px dashed #ece7d8;}"
    ".voice-label{font-size:.75rem;color:#9aa0a6;margin-right:10px;align-self:center;min-width:42px;}"
    ".measure{display:inline-flex;align-items:flex-end;padding:0 1px;}"
    ".barline{display:inline-block;width:2px;height:52px;background:#2b2b2b;margin:0 4px;align-self:flex-end;}"
    ".barline.final{position:relative;}"
    ".barline.final::after{content:'';position:absolute;left:4px;top:0;width:2px;height:52px;background:#2b2b2b;}"
    ".note{position:relative;display:inline-flex;align-items:flex-end;justify-content:center;"
    "min-width:2.1em;padding:20px 4px 14px;}"
    ".note.grace .jp-num{font-size:1.05rem;opacity:.65;}"
    ".jp-core{position:relative;display:inline-flex;align-items:center;line-height:1;}"
    ".jp-num{font-family:'Times New Roman',Georgia,serif;font-size:1.75rem;line-height:1;font-weight:600;}"
    ".jp-num.rest{font-weight:400;color:#555;}"
    ".jp-acc{position:absolute;left:-0.45em;top:-0.55em;font-size:.9rem;line-height:1;"
    "color:#1f2933;font-family:'Times New Roman',Georgia,serif;white-space:nowrap;}"
    ".chord{display:flex;flex-direction:column;align-items:center;}"
    ".chord .jp-num{font-size:1.35rem;}"
    ".chord .jp-acc{left:0;top:-0.55em;}"
    ".jp-up{position:absolute;left:50%;top:-0.65em;transform:translateX(-50%);"
    "display:flex;flex-direction:column;align-items:center;line-height:.7;font-size:1.05rem;}"
    ".jp-down{position:absolute;left:50%;top:calc(100% + 0.9em);transform:translateX(-50%);"
    "display:flex;flex-direction:column-reverse;align-items:center;line-height:.7;font-size:1.05rem;}"
    ".jp-dot{font-size:1.2rem;line-height:.7;color:#1f2933;}"
    ".jp-dot2{font-size:1.45rem;margin-left:2px;color:#1f2933;}"
    ".jp-aug{font-size:1.15rem;letter-spacing:0;margin-left:2px;align-self:center;}"
    ".beam{position:relative;display:inline-flex;align-items:flex-end;}"
    ".beam-lines{position:absolute;left:8px;right:8px;bottom:3px;}"
    ".jp-under{position:absolute;left:50%;transform:translateX(-50%);bottom:2px;display:block;width:1.5em;}"
    ".jp-tie{position:absolute;top:-12px;left:50%;transform:translateX(-50%);}";

// P1：仅在固定每行小节数（measuresPerLine>0）时追加的系统样式，保证默认输出与 v0.9.1 逐字节一致
const char* kL2SystemCss =
    ".system{margin-bottom:14px;}"
    ".line-number{font-size:.78rem;color:#5b6470;align-self:center;margin-right:8px;"
    "min-width:2em;text-align:center;font-family:'Times New Roman',Georgia,serif;}";

// P2：大谱表 —— 上下两行按小节纵向对齐（同一系统的列对齐），左侧花括号连接。
// 仅在启用大谱表时追加，不影响普通输出。
const char* kL2GrandCss =
    ".grand-wrap{display:flex;align-items:stretch;gap:4px;margin:2px 0 12px;}"
    ".grand-brace{width:20px;flex:0 0 20px;align-self:stretch;color:#2b2b2b;}"
    ".grand-body{flex:1;min-width:0;}"
    ".grand-label{align-self:stretch;display:flex;flex-direction:column;align-items:center;"
    "justify-content:flex-start;padding-right:6px;padding-top:22px;"
    "font-size:.72rem;color:#9aa0a6;line-height:1.3;}"
    ".grand-label .line-number{margin:0;min-width:auto;font-size:.78rem;color:#5b6470;}"
    ".grand-grid{display:grid;align-items:flex-end;row-gap:10px;}"
    // 大谱表小节线：每小节左侧一条纵线作小节分隔（首小节即系统开口线）；
    // 系统末小节经 .final 追加一条细双纵线。box-sizing 全局 border-box，
    // 故 2px 边框在列宽内、不破坏上下行列对齐。
    ".grand-grid .measure{padding:0 1px;border-left:2px solid #2b2b2b;}"
    ".grand-grid .measure.final{position:relative;}"
    ".grand-grid .measure.final::after{content:'';position:absolute;top:0;"
    "right:-4px;width:2px;height:100%;background:#2b2b2b;}"
    ".grand-cell{display:inline-block;min-width:2.1em;}";

// —— P1：空声部休止符填充 ——
// 把空小节（notes 为空、非 implicit）合成为等时值休止符序列。
// 长效：先尝试单一长休止（全/二分+附点…）；非整数节拍回退为多个四分休止。
std::vector<JianpuNote> l2MeasureRests(const JianpuMeasure& m, const JianpuDoc& doc) {
    int beats = (m.beats > 0) ? m.beats : doc.beats;
    int beatType = (m.beatType > 0) ? m.beatType : doc.beatType;
    if (beatType <= 0) beatType = 4;
    double ql = static_cast<double>(beats) * 4.0 / beatType;

    std::vector<JianpuNote> out;
    int ul, ad, dz;
    if (quarterLengthToRhythm(ql, ul, ad, dz)) {
        JianpuNote r; r.degree = 0; r.underlines = 0; r.augmentDashes = ad; r.dots = dz;
        out.push_back(r);
    } else {
        int n = static_cast<int>(std::lround(ql));
        if (n <= 0) n = 1;
        if (n <= 16) {
            for (int i = 0; i < n; ++i) { JianpuNote r; r.degree = 0; out.push_back(r); }
        } else {
            JianpuNote r; r.degree = 0; r.augmentDashes = 3; out.push_back(r);
        }
    }
    return out;
}

// 渲染一个小节；空小节（非 implicit）按需填充休止
std::string l2MeasureFilled(const JianpuMeasure& m, const JianpuDoc& doc, bool fillEmpty) {
    if (fillEmpty && m.notes.empty() && !m.implicit) {
        JianpuMeasure filled = m;
        filled.notes = l2MeasureRests(m, doc);
        filled.implicit = false;
        return l2Measure(filled);
    }
    return l2Measure(m);
}

// 渲染一条 voice 行在 [begin,end) 之间的切片；系统首行插起始小节号
std::string l2LineSlice(const JianpuLine& line, size_t begin, size_t end,
                        const JianpuDoc& doc, bool fillEmpty, bool showNumber) {
    std::string out = "<div class=\"line\">";
    if (showNumber)
        out += "<span class=\"line-number\">"
               + std::to_string(line.measures[begin].number) + "</span>";
    out += "<span class=\"voice-label\">voice" + std::to_string(line.voice) + "</span>";
    for (size_t mi = begin; mi < end; ++mi) {
        out += l2MeasureFilled(line.measures[mi], doc, fillEmpty);
        if (mi + 1 < end) out += "<span class=\"barline\"></span>";
    }
    out += "<span class=\"barline final\"></span>";
    out += "</div>";
    return out;
}

// P1：按 N 小节切分为系统；每系统按 voice 行堆叠，仅首行标小节号
std::string l2Systems(const JianpuDoc& doc, int N, bool fillEmpty) {
    size_t maxM = 0;
    for (const auto& line : doc.lines) maxM = std::max(maxM, line.measures.size());
    size_t systems = (maxM + N - 1) / N;
    if (systems == 0 && maxM > 0) systems = 1;

    std::string out;
    for (size_t k = 0; k < systems; ++k) {
        size_t begin = k * N;
        out += "<div class=\"system\">";
        bool numbered = true;   // 该系统首个有内容的 voice 行带小节号
        for (const auto& line : doc.lines) {
            if (line.measures.size() <= begin) continue;
            size_t le = std::min(begin + N, line.measures.size());
            out += l2LineSlice(line, begin, le, doc, fillEmpty, numbered);
            numbered = false;
        }
        out += "</div>";
    }
    return out;
}

// —— P2b：同谱表声部合并（按拍并成一条音流）——
// 把大谱表内同一谱表（上/下）的所有 voice 在 idx 处的小节合并：所有实音按 onset
// 升序并流；同 onset（同拍）的重叠音叠成和弦（chordDegrees）。该谱表整列无实音时，
// 按需合成休止（fillEmpty），否则留空槽。只影响 L2 渲染，不回改 L0/lines。
static JianpuMeasure l2MergeStaffMeasure(const JianpuDoc& doc,
                                         const std::vector<size_t>& members,
                                         const std::vector<int>& role,
                                         int wantRole, size_t idx, bool fillEmpty) {
    JianpuMeasure merged;
    std::vector<JianpuNote> pool;
    bool anyReal = false;
    int beatsD = 0, btD = 0;
    for (auto li : members) {
        if (role[li] != wantRole) continue;
        const auto& L = doc.lines[li];
        if (idx >= L.measures.size()) continue;
        const auto& m = L.measures[idx];
        if (merged.number == 0) merged.number = m.number;
        if (m.beats)    { beatsD = m.beats;    merged.beats    = m.beats; }
        if (m.beatType) { btD = m.beatType;    merged.beatType = m.beatType; }
        merged.implicit = merged.implicit || m.implicit;
        if (m.notes.empty()) continue;        // 空 voice：交给下方整体合成/忽略
        anyReal = true;
        for (const auto& n : m.notes) pool.push_back(n);
    }
    if (pool.empty()) {
        // 该谱表整列无实音 → 按需合成休止；否则留空槽
        if (fillEmpty && !merged.implicit) {
            JianpuMeasure tmpl; tmpl.number = merged.number;
            tmpl.beats = beatsD; tmpl.beatType = btD;
            merged.notes = l2MeasureRests(tmpl, doc);
        }
        return merged;
    }
    // 按 onset 升序（同一单位；同起点视为拍对齐）。此时 anyReal 引用已无用，忽略。
    std::stable_sort(pool.begin(), pool.end(),
        [](const JianpuNote& a, const JianpuNote& b) { return a.onset < b.onset; });
    std::vector<JianpuNote> out;
    for (auto& n : pool) {
        if (!out.empty() && (n.onset - out.back().onset) < 1e-6) {
            JianpuNote& root = out.back();
            if (root.degree == 0) {           // 休止让位给同拍实音
                out.back() = n; continue;
            }
            if (n.degree != 0) {              // 同拍实音 → 叠成和弦成员（相对根音八度偏移）
                root.chordDegrees.push_back(n.degree);
                root.chordOctaveDots.push_back(n.octaveDots - root.octaveDots);
            }
        } else {
            out.push_back(n);
        }
    }
    merged.notes = std::move(out);
    return merged;
}

// 估算单小节渲染宽度（px）：音符数 × 单音基准宽；长休止按拆拍数放宽；和弦成员叠
// 在同一槽内不额外增宽；beam 组仍按各数字占宽计。
static double l2MeasurePx(const JianpuMeasure& m) {
    constexpr double kNotePx = 33.0;
    double w = 2.0;                             // 小节左右 padding 余量
    for (const auto& n : m.notes)
        w += (n.degree == 0) ? kNotePx * l2RestBeats(n) : kNotePx;
    return w;
}

// 大谱表某单位：逐列渲染宽 = max(上/下合并列宽)
static std::vector<double> l2ColWidthsGrand(const JianpuDoc& doc,
    const std::vector<size_t>& members, const std::vector<int>& role,
    size_t maxM, bool fillEmpty) {
    std::vector<double> w(maxM, 0.0);
    for (size_t idx = 0; idx < maxM; ++idx) {
        double up = l2MeasurePx(l2MergeStaffMeasure(doc, members, role, 0, idx, fillEmpty));
        double dn = l2MeasurePx(l2MergeStaffMeasure(doc, members, role, 1, idx, fillEmpty));
        w[idx] = (up > dn) ? up : dn;
    }
    return w;
}

// 普通行集合：逐列渲染宽 = 各行列宽取 max（自适应按最宽行/最挤分块决定 N）
static std::vector<double> l2ColWidthsLines(const JianpuDoc& doc,
                                            const std::vector<size_t>& lines,
                                            size_t maxM) {
    std::vector<double> w(maxM, 0.0);
    for (auto li : lines) {
        const auto& L = doc.lines[li];
        for (size_t idx = 0; idx < L.measures.size() && idx < maxM; ++idx)
            if (l2MeasurePx(L.measures[idx]) > w[idx]) w[idx] = l2MeasurePx(L.measures[idx]);
    }
    return w;
}

// 不重叠 N 档分块：是否每一块累计宽都不超可用宽
static bool l2FitsChunk(const std::vector<double>& w, int n, double usable) {
    for (size_t k = 0; k < w.size(); k += static_cast<size_t>(n)) {
        double s = 0;
        size_t lim = std::min(k + static_cast<size_t>(n), w.size());
        for (size_t i = k; i < lim; ++i) s += w[i];
        if (s > usable) return false;
    }
    return true;
}

// 逐偶数档降档求第一个放得下的 N（8→6→4→2），全不行则回退到 2
static int l2FitN(const std::vector<double>& w, int desired, double usable) {
    for (int n = desired - (desired & 1); n >= 2; n -= 2)
        if (l2FitsChunk(w, n, usable)) return n;
    return 2;
}

// 每行可用宽度（px）：内容宽 856 减去行首节号/声部标签（普通行），或花括号/列标签
// /行首节号（大谱表）。略保守以留白。
static constexpr double kLineUsablePx  = 772.0;
static constexpr double kGrandUsablePx = 756.0;

// —— P2 大谱表渲染 ——
// 大谱表 = 若干「上行行」(staff=1 / 手动配对上游) + 若干「下行行」(staff=2 / 下游)。
// 同一系统的上下行按小节【列对齐】渲染（绝不各自换行错位），左侧花括号连接，
// 行首小节号仅标在首个上行行。列对齐网格：每列 = 一个小节，跨所有上下行。

std::string l2GrandBrace() {
    // 经典花括号曲线（自上而下再折回中点）：空心朝左留白，贴近钢琴谱左花括号观感。
    return "<svg class=\"grand-brace\" viewBox=\"0 0 20 100\" preserveAspectRatio=\"none\" aria-hidden=\"true\">"
           "<path d=\"M16 6 C5 6 1 26 2 38 L13 50 L2 62 C1 74 5 94 16 94\" fill=\"none\" "
           "stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"round\"/></svg>";
}

// 大谱表一行（上=右手 / 下=左手）：标签列 + 该谱表合并后的各小节。
// 标签列：行首小节号（仅上行）+ 「上/下·v…（合并声部名）」；小节列用共享网格占位，
// 使上行/下行同名小节严格列对齐。
std::string l2GrandRow(const JianpuDoc& doc, const std::vector<size_t>& members,
                       const std::vector<int>& role, int wantRole,
                       const std::vector<int>& voices, bool isFirst,
                       size_t begin, size_t cols, bool fillEmpty) {
    std::string out = "<div class=\"grand-label\">";
    if (isFirst) {
        for (auto li : members)
            if (role[li] == wantRole) {
                const auto& L = doc.lines[li];
                if (begin < L.measures.size()) {
                    out += "<span class=\"line-number\">" + std::to_string(L.measures[begin].number) + "</span>";
                    break;
                }
            }
    }
    std::string side = (wantRole == 1) ? "下" : "上";
    std::string vlabel;
    for (size_t i = 0; i < voices.size(); ++i) {
        if (i) vlabel += ",";
        vlabel += "v" + std::to_string(voices[i]);
    }
    out += "<span>" + side + (vlabel.empty() ? "" : "·" + vlabel) + "</span>";
    out += "</div>";
    for (size_t c = 0; c < cols; ++c) {
        size_t idx = begin + c;
        JianpuMeasure merged = l2MergeStaffMeasure(doc, members, role, wantRole, idx, fillEmpty);
        if (merged.notes.empty()) {
            out += "<div class=\"grand-cell\"></div>";
        } else {
            std::string md = l2Measure(merged);
            if (c == cols - 1) {                       // 系统末小节 → 双纵线
                size_t p = md.find("class=\"measure\"");
                if (p != std::string::npos) md.replace(p, 15, "class=\"measure final\"");
            }
            out += md;
        }
    }
    return out;
}

// 渲染一个系统单位的整条大谱表（members 有序：上行行在前，下行行在后）。
// [P2b 合并] 不再逐 voice 出行；同一谱表的所有 voice 合并成一行 → 每系统恰好两行：
//   上行 = 所有上行(role 0) 声部合并，下行 = 所有下行(role 1) 声部合并。
std::string l2GrandSystems(const JianpuDoc& doc, const std::vector<size_t>& members,
                           const std::vector<int>& role, int N, bool fillEmpty) {
    size_t maxM = 0;
    for (auto li : members) maxM = std::max(maxM, doc.lines[li].measures.size());
    if (maxM == 0) return "";
    int W = (N > 0) ? N : static_cast<int>(maxM);   // 未指定时整段作一个系统（保持列对齐）
    if (W <= 0) W = 1;

    // 按谱表分上/下两组（声部名供行标签显示）
    std::vector<size_t> up, down;
    std::vector<int> upV, downV;
    for (auto li : members) {
        if (role[li] == 1) { down.push_back(li); downV.push_back(doc.lines[li].voice); }
        else               { up.push_back(li);   upV.push_back(doc.lines[li].voice); }
    }

    std::string out;
    for (size_t k = 0; k * static_cast<size_t>(W) < maxM; ++k) {
        size_t begin = k * static_cast<size_t>(W);
        size_t cols = std::min(static_cast<size_t>(W), maxM - begin);
        out += "<div class=\"system system-grand\"><div class=\"grand-wrap\">";
        out += l2GrandBrace();
        out += "<div class=\"grand-body\">";
        // 【列对齐关键】上下两行共用同一网格：第 0 列=行标签，其后每列=同一个小节。
        out += "<div class=\"grand-grid\" style=\"grid-template-columns:auto repeat("
               + std::to_string(cols) + ",max-content)\">";
        out += l2GrandRow(doc, members, role, 0, upV,   true,  begin, cols, fillEmpty);
        out += l2GrandRow(doc, members, role, 1, downV, false, begin, cols, fillEmpty);
        out += "</div></div></div>"; // grand-grid + grand-body + grand-wrap + system
    }
    return out;
}

// 单条非大谱表行、固定每行 N 小节：渲染为独立系统（每系统一行，行首带小节号）。
std::string l2SingleLineSystems(const JianpuLine& line, const JianpuDoc& doc, int N, bool fillEmpty) {
    size_t m = line.measures.size();
    if (m == 0) return "";
    std::string out;
    for (size_t k = 0; k * static_cast<size_t>(N) < m; ++k) {
        size_t begin = k * static_cast<size_t>(N);
        size_t le = std::min(begin + static_cast<size_t>(N), m);
        out += "<div class=\"system\">";
        out += l2LineSlice(line, begin, le, doc, fillEmpty, true);
        out += "</div>";
    }
    return out;
}

// 计算每行的大谱表配对：(pairId 组号, role 0=上行/1=下行)。返回是否启用了大谱表。
//   手动 --grand-staff 优先；其次 autoGrandStaff 对含 staff≥2 的单 part 自动配对。
//   配对只影响 L2 渲染分组，不回改 L0/lines。
static bool l2ComputeGrand(const JianpuDoc& doc, const JianpuRenderConfig& cfg,
                           std::vector<int>& pairId, std::vector<int>& role) {
    const size_t n = doc.lines.size();
    pairId.assign(n, -1);
    role.assign(n, -1);
    int gid = 1;

    // 手动配对：{上游 part 下标, 下游 part 下标}
    for (const auto& pr : cfg.grandStaffPairs) {
        for (size_t i = 0; i < n; ++i) {
            if (pairId[i] > 0) continue;
            if (doc.lines[i].partIndex == pr.first)      { pairId[i] = gid; role[i] = 0; }
            else if (doc.lines[i].partIndex == pr.second) { pairId[i] = gid; role[i] = 1; }
        }
        ++gid;
    }

    // 自动识别：单一 part 内含双谱表（存在 staff≥2 的行）→ 该 part 全部行配对
    if (cfg.autoGrandStaff) {
        std::set<int> multiParts;
        for (size_t i = 0; i < n; ++i)
            if (doc.lines[i].staff >= 2) multiParts.insert(doc.lines[i].partIndex);
        for (int pi : multiParts) {
            bool taken = false;
            for (size_t i = 0; i < n; ++i)
                if (doc.lines[i].partIndex == pi && pairId[i] > 0) { taken = true; break; }
            if (taken) continue;
            for (size_t i = 0; i < n; ++i)
                if (doc.lines[i].partIndex == pi && pairId[i] < 0)
                    pairId[i] = gid;
            // 上下行按谱表归属定（staff≥2=下行，其余=上行）
            for (size_t i = 0; i < n; ++i)
                if (pairId[i] == gid) role[i] = (doc.lines[i].staff >= 2) ? 1 : 0;
            ++gid;
        }
    }

    for (size_t i = 0; i < n; ++i)
        if (pairId[i] > 0) return true;
    return false;
}

// 按 doc 顺序把行归并为「渲染单元」：要么单条普通行，要么包含上下行的大谱表组。
struct RenderUnit { std::vector<size_t> lines; bool grand; };
static std::vector<RenderUnit> l2BuildUnits(const std::vector<int>& pairId,
                                            const std::vector<int>& role) {
    const size_t n = pairId.size();
    std::vector<unsigned char> emitted(n, 0);
    std::vector<RenderUnit> units;
    for (size_t i = 0; i < n; ++i) {
        if (emitted[i]) continue;
        if (pairId[i] < 0) { units.push_back({{i}, false}); emitted[i] = 1; continue; }
        std::vector<size_t> mem;
        for (size_t j = 0; j < n; ++j)
            if (pairId[j] == pairId[i]) { mem.push_back(j); emitted[j] = 1; }
        std::stable_sort(mem.begin(), mem.end(),
                         [&](size_t a, size_t b) { return role[a] < role[b]; });  // 上行先于下行
        units.push_back({std::move(mem), true});
    }
    return units;
}

} // anonymous namespace

std::string jianpuToL2(const JianpuDoc& doc, const JianpuRenderConfig& cfg) {
    std::string title = doc.title.empty() ? "(无标题)" : doc.title;
    std::string key = doc.tonicLabel + " " + std::to_string(doc.beats) + "/" +
                      std::to_string(doc.beatType) + " (" + doc.mode + ")";

    // —— P2：大谱表配对（仅影响 L2 渲染分组，不回改 L0/lines）——
    std::vector<int> pairId, role;
    const bool hasGrand = l2ComputeGrand(doc, cfg, pairId, role);

    // 自适应每行小节数（仅 measuresPerLine>0 时生效）
    const bool autoFit = cfg.autoFitMeasures && cfg.measuresPerLine > 0;

    std::string body;
    if (hasGrand) {
        // 大谱表：按 doc 顺序归并渲染单元；上下行组内列对齐、同谱表声部合并，普通行独立渲染
        auto units = l2BuildUnits(pairId, role);
        for (const auto& u : units) {
            if (!u.grand) {
                const auto& L = doc.lines[u.lines[0]];
                int N = cfg.measuresPerLine;
                if (autoFit) {
                    size_t maxM = L.measures.size();
                    auto w = l2ColWidthsLines(doc, {u.lines[0]}, maxM);
                    N = l2FitN(w, cfg.measuresPerLine, kLineUsablePx);
                }
                if (N > 0)
                    body += l2SingleLineSystems(L, doc, N, cfg.fillEmptyVoiceRest);
                else
                    body += l2LineSlice(L, 0, L.measures.size(), doc, cfg.fillEmptyVoiceRest, false);
            } else {
                int N = cfg.measuresPerLine;
                if (autoFit) {
                    size_t maxM = 0;
                    for (auto li : u.lines) maxM = std::max(maxM, doc.lines[li].measures.size());
                    auto w = l2ColWidthsGrand(doc, u.lines, role, maxM, cfg.fillEmptyVoiceRest);
                    N = l2FitN(w, cfg.measuresPerLine, kGrandUsablePx);
                }
                body += l2GrandSystems(doc, u.lines, role, N, cfg.fillEmptyVoiceRest);
            }
        }
    } else if (autoFit || cfg.measuresPerLine > 0) {
        // P1：固定/自适应每行小节数 → 按系统切分，仅系统首行标小节号
        int N = cfg.measuresPerLine;
        if (autoFit) {
            std::vector<size_t> all(doc.lines.size());
            for (size_t i = 0; i < doc.lines.size(); ++i) all[i] = i;
            size_t maxM = 0;
            for (const auto& l : doc.lines) maxM = std::max(maxM, l.measures.size());
            auto w = l2ColWidthsLines(doc, all, maxM);
            N = l2FitN(w, cfg.measuresPerLine, kLineUsablePx);
        }
        body = l2Systems(doc, N, cfg.fillEmptyVoiceRest);
    } else {
        // 默认：整段单行输出（与 v0.9.1 逐字节一致），空声部仍可按需补 0
        for (const auto& line : doc.lines) {
            body += l2LineSlice(line, 0, line.measures.size(), doc,
                                cfg.fillEmptyVoiceRest, false);
        }
    }

    std::string html;
    html += "<!DOCTYPE html>";
    html += "<html lang=\"zh\"><head><meta charset=\"utf-8\">";
    html += "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">";
    html += "<title>谱渡 · 简谱 L2 — " + l2Escape(title) + "</title>";
    std::string css = kL2Css;
    if (cfg.measuresPerLine > 0) css += kL2SystemCss;
    if (hasGrand) css += kL2GrandCss;
    html += "<style>" + css + "</style></head><body>";
    html += "<div class=\"score\">";
    html += "<div class=\"header\"><div class=\"title\">" + l2Escape(title) + "</div>";
    html += "<div class=\"key\">" + l2Escape(key) + "</div></div>";
    html += body;
    html += "</div></body></html>";
    return html;
}

// ---- L3 结构化 JSON 输出（供外部校验器逐音比对，无损、可解析） ----
namespace {

std::string jsonEscape(const std::string& s) {
    std::string o;
    o.reserve(s.size());
    static const char* hex = "0123456789abcdef";
    for (char c : s) {
        switch (c) {
            case '"':  o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n";  break;
            case '\r': o += "\\r";  break;
            case '\t': o += "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    o += "\\u00";
                    o += hex[(static_cast<unsigned char>(c) >> 4) & 0xf];
                    o += hex[static_cast<unsigned char>(c) & 0xf];
                } else {
                    o += c;
                }
        }
    }
    return o;
}

const char* jsonAccidental(Accidental a) {
    switch (a) {
        case Accidental::Sharp:       return "sharp";
        case Accidental::Flat:        return "flat";
        case Accidental::Natural:     return "natural";
        case Accidental::DoubleSharp: return "doublesharp";
        case Accidental::DoubleFlat:  return "doubleflat";
        default: return "none";
    }
}

std::string jsonNote(const JianpuNote& jn) {
    std::string s = "{";
    s += "\"degree\":" + std::to_string(jn.degree);
    s += ",\"octaveDots\":" + std::to_string(jn.octaveDots);
    s += ",\"accidental\":\"" + std::string(jsonAccidental(jn.accidental)) + "\"";
    s += ",\"underlines\":" + std::to_string(jn.underlines);
    s += ",\"augmentDashes\":" + std::to_string(jn.augmentDashes);
    s += ",\"dots\":" + std::to_string(jn.dots);
    s += ",\"onset\":" + std::to_string(std::round(jn.onset * 10000.0) / 10000.0);
    s += ",\"isRest\":" + std::string(jn.degree == 0 ? "true" : "false");
    s += ",\"isGrace\":" + std::string(jn.isGrace ? "true" : "false");
    s += ",\"tieToNext\":" + std::string(jn.tieToNext ? "true" : "false");
    s += ",\"tieFromPrev\":" + std::string(jn.tieFromPrev ? "true" : "false");
    s += ",\"tuplet\":" + std::to_string(jn.tuplet);
    s += ",\"rhythmUnresolvable\":" + std::string(jn.rhythmUnresolvable ? "true" : "false");
    s += ",\"chordDegrees\":[";
    for (size_t i = 0; i < jn.chordDegrees.size(); ++i) {
        if (i) s += ",";
        s += std::to_string(jn.chordDegrees[i]);
    }
    s += "]";
    s += ",\"chordOctaveDots\":[";
    for (size_t i = 0; i < jn.chordOctaveDots.size(); ++i) {
        if (i) s += ",";
        s += std::to_string(jn.chordOctaveDots[i]);
    }
    s += "]";
    s += "}";
    return s;
}

} // anonymous namespace

std::string jianpuToJson(const JianpuDoc& doc) {
    std::string tonic = doc.tonicLabel;
    size_t eq = tonic.find('=');
    if (eq != std::string::npos) tonic = tonic.substr(eq + 1);

    std::string j = "{";
    j += "\"title\":\"" + jsonEscape(doc.title) + "\"";
    j += ",\"tonicLabel\":\"" + jsonEscape(doc.tonicLabel) + "\"";
    j += ",\"tonic\":\"" + jsonEscape(tonic) + "\"";
    j += ",\"mode\":\"" + jsonEscape(doc.mode) + "\"";
    j += ",\"fifths\":" + std::to_string(doc.fifths);
    j += ",\"beats\":" + std::to_string(doc.beats);
    j += ",\"beatType\":" + std::to_string(doc.beatType);
    j += ",\"lines\":[";
    for (size_t li = 0; li < doc.lines.size(); ++li) {
        const auto& line = doc.lines[li];
        if (li) j += ",";
        j += "{\"voice\":" + std::to_string(line.voice) +
             ",\"part\":" + std::to_string(line.partIndex) + ",\"measures\":[";
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            const auto& m = line.measures[mi];
            if (mi) j += ",";
            j += "{\"number\":" + std::to_string(m.number) + ",\"notes\":[";
            for (size_t ni = 0; ni < m.notes.size(); ++ni) {
                if (ni) j += ",";
                j += jsonNote(m.notes[ni]);
            }
            j += "]}";
        }
        j += "]}";
    }
    j += "]}";
    return j;
}

} // namespace pudu
