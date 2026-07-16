// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 2 简谱转换器实现（Score -> JianpuDoc）
// 依据 omr-tool-research/jianpu_output_spec.md §2/§4 实现。
// 不回改 Score：仅读取，结果是一份 L0 语义投影。
// ----------------------------------------------------------------------

#include "jianpu_converter.hpp"

#include <algorithm>
#include <cmath>
#include <set>
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
        // 收集本声部出现的 voice 集合（多声部 -> 多行），用 std::set 保证稳定升序
        std::set<int> voiceSet;
        for (const auto& m : part.measures)
            for (const auto& n : m.notes)
                voiceSet.insert(n.voice);

        for (int voice : voiceSet) {
            JianpuLine line;
            line.voice = voice;
            line.partIndex = static_cast<int>(pi);

            for (const auto& measure : part.measures) {
                JianpuMeasure jm;
                jm.number = measure.number;

                // 仅取本 voice 的音符，按 onset 升序（对齐演奏/书写顺序）
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
                    if (quarterLengthToRhythm(rhythmQl, ul, ad, dz)) {
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
    for (int i = 0; i < k; ++i) s += "\xE2\x80\x94"; // —
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

// 单数字核心（休止为 0；否则 临时记号 + 数字 + 附点）
std::string l2Digit(const JianpuNote& jn) {
    if (jn.degree == 0)
        return "<span class=\"jp-num rest\">0</span>";
    std::string acc = l2Accidental(jn.accidental);
    std::string core = "<span class=\"jp-num\">" + acc + std::to_string(jn.degree) + "</span>";
    core += l2Dots(jn.dots);
    return core;
}

// 音符单元（不含减时线；减时线由小节层 beam 组统一绘制）
std::string l2NoteCell(const JianpuNote& jn) {
    std::string cell = "<span class=\"note";
    if (jn.isGrace) cell += " grace";
    cell += "\">";
    cell += l2OctaveDots(jn.octaveDots);
    if (jn.tieToNext) cell += l2Tie();
    if (!jn.chordDegrees.empty()) {
        cell += "<span class=\"chord\">";
        cell += l2Digit(jn);   // 根音点由上方 l2OctaveDots(jn.octaveDots) 负责
        for (size_t k = 0; k < jn.chordDegrees.size(); ++k) {
            int d = jn.chordDegrees[k];
            int od = (k < jn.chordOctaveDots.size()) ? jn.chordOctaveDots[k] : 0;
            cell += "<span class=\"jp-num\">" + std::to_string(d) + "</span>";
            cell += l2OctaveDots(od);   // M1.5-A：成员音八度点紧贴该成员数字
        }
        cell += "</span>";
    } else {
        cell += l2Digit(jn);
    }
    cell += l2Augment(jn.augmentDashes);
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
    ".barline{display:inline-block;width:2px;height:48px;background:#2b2b2b;margin:0 4px;align-self:flex-end;}"
    ".barline.final{position:relative;}"
    ".barline.final::after{content:'';position:absolute;left:4px;top:0;width:2px;height:48px;background:#2b2b2b;}"
    ".note{position:relative;display:inline-flex;align-items:flex-end;justify-content:center;"
    "min-width:1.9em;padding:18px 4px 12px;}"
    ".note.grace .jp-num{font-size:1.05rem;opacity:.65;}"
    ".jp-core{display:inline-flex;align-items:center;}"
    ".jp-num{font-family:'Times New Roman',Georgia,serif;font-size:1.75rem;line-height:1;font-weight:600;}"
    ".jp-num.rest{font-weight:400;color:#555;}"
    ".chord{display:flex;flex-direction:column;align-items:center;}"
    ".chord .jp-num{font-size:1.35rem;}"
    ".jp-up{position:absolute;top:0;left:50%;transform:translateX(-50%);"
    "display:flex;flex-direction:column;align-items:center;line-height:.7;font-size:.7rem;}"
    ".jp-down{position:absolute;top:2.1em;left:50%;transform:translateX(-50%);"
    "display:flex;flex-direction:column-reverse;align-items:center;line-height:.7;font-size:.7rem;}"
    ".jp-dot{font-size:.7rem;line-height:.7;color:#1f2933;}"
    ".jp-dot2{font-size:1rem;margin-left:1px;color:#1f2933;}"
    ".jp-aug{font-size:1.15rem;letter-spacing:-2px;margin-left:2px;align-self:center;}"
    ".beam{position:relative;display:inline-flex;align-items:flex-end;}"
    ".beam-lines{position:absolute;left:8px;right:8px;bottom:3px;}"
    ".jp-under{position:absolute;left:50%;transform:translateX(-50%);bottom:2px;display:block;width:1.5em;}"
    ".jp-tie{position:absolute;top:-12px;left:50%;transform:translateX(-50%);}";

} // anonymous namespace

std::string jianpuToL2(const JianpuDoc& doc) {
    std::string title = doc.title.empty() ? "(无标题)" : doc.title;
    std::string key = doc.tonicLabel + " " + std::to_string(doc.beats) + "/" +
                      std::to_string(doc.beatType) + " (" + doc.mode + ")";

    std::string body;
    for (const auto& line : doc.lines) {
        body += "<div class=\"line\">";
        body += "<span class=\"voice-label\">voice" + std::to_string(line.voice) + "</span>";
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            body += l2Measure(line.measures[mi]);
            if (mi + 1 < line.measures.size())
                body += "<span class=\"barline\"></span>";
        }
        body += "<span class=\"barline final\"></span>";
        body += "</div>";
    }

    std::string html;
    html += "<!DOCTYPE html>";
    html += "<html lang=\"zh\"><head><meta charset=\"utf-8\">";
    html += "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">";
    html += "<title>谱渡 · 简谱 L2 — " + l2Escape(title) + "</title>";
    html += "<style>" + std::string(kL2Css) + "</style></head><body>";
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
