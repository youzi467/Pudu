// ----------------------------------------------------------------------
// 谱渡 Pudu · P1-1 后处理音乐规则引擎实现
//
// 五类规则（执行顺序固定）：
//   1. BeatReconcile —— 小节节拍对账（用户决策 b：默认积极自修）
//   2. Accidental    —— 临时记号 / 调号一致性（保守：仅 trivially-safe 自修）
//   3. OctaveDot     —— 八度点异常（保守：以标记为主）
//   4. TupletGroup   —— 连音组自洽（只标记）
//   5. RestFill      —— 疑似遗漏音符/休止（只标记，绝不臆造）
//
// 不变量守护（贯穿全文件的第一原则）：
//   干净输入（staffToJianpu 正常产出、小节严格归零）必须触发 0 处修正。
//   为此，每条规则的触发条件都被刻意收紧到"clean converter output 不可达"
//   的取值域上，详见各规则处的推导注释。
// ----------------------------------------------------------------------

#include "jianpu_postcorrect.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#include <tuple>
#include <utility>
#include <vector>

namespace pudu {

const char* correctionKindName(CorrectionKind kind) {
    switch (kind) {
        case CorrectionKind::BeatReconcile: return "BeatReconcile";
        case CorrectionKind::OctaveDot:     return "OctaveDot";
        case CorrectionKind::Accidental:    return "Accidental";
        case CorrectionKind::TupletGroup:   return "TupletGroup";
        case CorrectionKind::RestFill:      return "RestFill";
    }
    return "Unknown";
}

namespace {

// ======================================================================
// 0. 基础常量 / 时值换算
// ======================================================================

// 时长比较容差。与 jianpu_converter.cpp::quarterLengthToRhythm 的 1e-4 同量级，
// 保证两侧对"是否命中标准时值"的判断口径一致。
constexpr double kEps = 1e-4;

// 简谱时值基准阶梯（由长到短），与 quarterLengthToRhythm 的 kBases/kAug/kUl
// 严格一一对应，保证正向(本文件)与反向(转换器)互逆。
struct RhythmRung {
    double base;        // quarterLength 基准值
    int underlines;     // 减时线
    int augmentDashes;  // 增时线
};
const RhythmRung kLadder[7] = {
    {4.0000, 0, 3},   // 全音符   1 - - -
    {2.0000, 0, 1},   // 二分音符 1 -
    {1.0000, 0, 0},   // 四分音符 1
    {0.5000, 1, 0},   // 八分音符
    {0.2500, 2, 0},   // 十六分
    {0.1250, 3, 0},   // 三十二分
    {0.0625, 4, 0},   // 六十四分
};
constexpr int kRungCount = 7;
constexpr int kQuarterRung = 2;   // kLadder 中"四分音符"的下标
constexpr int kMaxDots = 2;       // 与 quarterLengthToRhythm 一致：最多双附点

// 附点系数：0 -> 1.0, 1 -> 1.5, 2 -> 1.75（通式 2 - 2^-dots）
double dotFactor(int dots) {
    if (dots <= 0) return 1.0;
    return 2.0 - std::pow(0.5, static_cast<double>(dots));
}

// 连音组的 normal 数：约定取"小于 actual 的最大 2 的幂"。
//   3 连音 -> 2（与转换器 tupletNormal=2 一致）
//   5/6/7 连音 -> 4（五连音按 实际 = 基准 × 4/5，仅为近似约定，标记时会注明）
//   9 连音 -> 8
int tupletNormalFor(int actual) {
    if (actual <= 1) return 1;
    int n = 1;
    while (n * 2 < actual) n *= 2;
    return n;
}

// 正向换算：JianpuNote -> 实际占拍(quarterLength)。与转换器的
// quarterLengthToRhythm 互逆（转换器里 rhythmQl = ql × actual / normal，
// 故 实际 ql = 基准 × normal / actual）。
//
// 约定与边界：
//   - 装饰音不占基本时值，返回 0.0（jianpu_model.hpp 对 isGrace 的定义）。
//   - 减时线与增时线互斥；underlines > 0 时忽略 augmentDashes。
//   - 增时线通式：每条增时线 +1 拍（half=1 条 -> 2.0；whole=3 条 -> 4.0）。
//   - underlines > 4 按 4 条封顶（六十四分），避免越界。
double noteQuarterLength(const JianpuNote& n) {
    if (n.isGrace) return 0.0;

    double base = 1.0;
    int ul = n.underlines;
    if (ul < 0) ul = 0;
    if (ul > 0) {
        if (ul > 4) ul = 4;
        base = kLadder[kQuarterRung + ul].base;
    } else {
        int ad = n.augmentDashes;
        if (ad < 0) ad = 0;
        base = 1.0 + static_cast<double>(ad);
    }

    double ql = base * dotFactor(n.dots);

    if (n.tuplet > 1) {
        // P1-1 返工：优先使用转换器透传的真实 normal-notes(tupletNormal)，
        // 仅当解析层未给出时再退回到"小于 actual 的最大 2 的幂"近似约定，
        // 避免 2:3 二连音 / 4:3 四连音 等非三连音比被错算成 1/3 / 1/4 而引发误改写。
        const int normal = (n.tupletNormal > 0) ? n.tupletNormal : tupletNormalFor(n.tuplet);
        ql = ql * static_cast<double>(normal) / static_cast<double>(n.tuplet);
    }
    return ql;
}

// 把一个音符定位到 (rung, dots) 时值格点上。
// 返回 false 表示"不在标准格点上 / 不适合被改写"，此时该音不参与节拍归责：
//   连音组、未解析时值、装饰音、非法附点数、减增时线并存、非标准增时线数。
bool noteLatticePos(const JianpuNote& n, int& outRung, int& outDots) {
    if (n.isGrace || n.tuplet > 0 || n.rhythmUnresolvable) return false;
    if (n.dots < 0 || n.dots > kMaxDots) return false;

    if (n.underlines > 0) {
        if (n.underlines > 4 || n.augmentDashes != 0) return false;
        outRung = kQuarterRung + n.underlines;
    } else if (n.underlines < 0) {
        return false;
    } else {
        if (n.augmentDashes == 0)      outRung = 2;   // 四分
        else if (n.augmentDashes == 1) outRung = 1;   // 二分
        else if (n.augmentDashes == 3) outRung = 0;   // 全音符
        else return false;                            // 如 ad==2（3 拍）另有等价写法，不改写
    }
    outDots = n.dots;
    return true;
}

// 小节目标时长 = beats × 4 / beatType（4/4 -> 4.0；3/4 -> 3.0；6/8 -> 3.0；12/8 -> 6.0）。
// P1-1 返工：改为【逐小节】取值——小节自身拍号(beats/beatType > 0)优先，
//   否则回退到文档全局(doc.beats/beatType)，再否则默认 4/4。
//   这样曲中变拍号、implicit 等都能被精确对账，避免把"变拍号/不完全小节"误当
//   "节拍错误"而静默改写（正是此前破坏 no-op 红线的根因之一）。
double measureTargetQl(const JianpuDoc& doc, const JianpuMeasure& m) {
    const int beats    = (m.beats    > 0) ? m.beats    : ((doc.beats    > 0) ? doc.beats    : 4);
    const int beatType = (m.beatType > 0) ? m.beatType : ((doc.beatType > 0) ? doc.beatType : 4);
    return static_cast<double>(beats) * 4.0 / static_cast<double>(beatType);
}

// ======================================================================
// 1. 文本工具
// ======================================================================

std::string fmtQl(double v) {
    std::ostringstream os;
    os << std::fixed << std::setprecision(4) << v;
    return os.str();
}

std::string fmtConfidence(double v) {
    std::ostringstream os;
    os << std::fixed << std::setprecision(3) << v;
    return os.str();
}

// 时值描述串（before/after 用；机读友好、人读也够直观）
std::string rhythmLabel(int underlines, int augmentDashes, int dots, double ql) {
    std::ostringstream os;
    os << "ul=" << underlines << " ad=" << augmentDashes << " dots=" << dots
       << " ql=" << fmtQl(ql);
    return os.str();
}

std::string rhythmLabel(const JianpuNote& n) {
    return rhythmLabel(n.underlines, n.augmentDashes, n.dots, noteQuarterLength(n));
}

const char* accidentalName(Accidental a) {
    switch (a) {
        case Accidental::None:        return "none";
        case Accidental::Sharp:       return "sharp";
        case Accidental::Flat:        return "flat";
        case Accidental::Natural:     return "natural";
        case Accidental::DoubleSharp: return "doublesharp";
        case Accidental::DoubleFlat:  return "doubleflat";
    }
    return "none";
}

// 音符的简谱标签（"5'" / "b3," / "0"），用于 before/after 与 reason
std::string degreeLabel(const JianpuNote& n) {
    if (n.degree == 0) return "0";
    std::string s;
    switch (n.accidental) {
        case Accidental::Sharp:       s += "#";  break;
        case Accidental::Flat:        s += "b";  break;
        case Accidental::Natural:     s += "n";  break;
        case Accidental::DoubleSharp: s += "x";  break;
        case Accidental::DoubleFlat:  s += "bb"; break;
        default: break;
    }
    s += std::to_string(n.degree);
    for (int i = 0; i < n.octaveDots; ++i) s += "'";
    for (int i = 0; i < -n.octaveDots; ++i) s += ",";
    return s;
}

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

// ======================================================================
// 2. 引擎运行期状态
// ======================================================================

using NoteKey = std::tuple<int, int, int>;      // (lineIdx, measureIdx, noteIndex)
using MeasureKey = std::pair<int, int>;         // (lineIdx, measureIdx)

struct EngineState {
    PostCorrectReport* report = nullptr;
    std::set<NoteKey> touchedNotes;             // 去重后的"被改写音符"
    std::set<MeasureKey> reconciledMeasures;    // 去重后的"节拍自修小节"
    std::vector<Correction> pendingRestFill;    // BeatReconcile 判定为"不足且不可解"
};

Correction makeCorrection(CorrectionKind kind, const JianpuLine& line,
                          const JianpuMeasure& measure, int noteIndex,
                          std::string before, std::string after,
                          std::string reason, double confidence) {
    Correction c;
    c.kind = kind;
    c.part = line.partIndex;
    c.voice = line.voice;
    c.measure = measure.number;
    c.noteIndex = noteIndex;
    c.before = std::move(before);
    c.after = std::move(after);
    c.reason = std::move(reason);
    c.confidence = confidence;
    return c;
}

// 记一条"仅标记"
void flag(EngineState& st, Correction c) {
    st.report->flagged.push_back(std::move(c));
}

// 记一条"已自修"，并登记被触及的音符坐标（-1 表示小节级，不计入 notesTouched）
void applyFix(EngineState& st, Correction c, int lineIdx, int measureIdx) {
    if (c.noteIndex >= 0)
        st.touchedNotes.insert(NoteKey{lineIdx, measureIdx, c.noteIndex});
    st.report->applied.push_back(std::move(c));
}

// ======================================================================
// 3. 规则 1：BeatReconcile —— 小节节拍对账（积极自修）
// ======================================================================
//
// 流程：
//   sum = Σ noteQuarterLength(note)；diff = sum - target。
//   |diff| < eps                 -> 完全不处理（干净输入的 no-op 保证在此）。
//   小节为空                     -> 跳过（无归责对象）。
//   含 rhythmUnresolvable        -> 仅标记（时值本身就没解出来，不敢改）。
//   行首小节且不足               -> 视为弱起(anacrusis)，跳过（避免系统性误报）。
//   否则枚举"单音一个标准步"的候选：
//     候选 = 把某个音符在时值格点上移动 |Δrung| <= 1 且 |Δdots| <= 1，
//            使小节恰好归零。
//     - 候选全部落在【同一个音符】上 -> 无歧义归责 -> 自修（confidence=1.0）
//     - 候选跨多个音符               -> 歧义 -> 仅标记
//     - 无候选 且 溢出               -> 仅标记（无单音标准步可解）
//     - 无候选 且 不足               -> 交给规则 5 RestFill 标记
//
// 说明：onset 字段不做重排。onset 是"从声部起点算起"的累计时间轴，改一个小节
//   会级联影响其后所有小节；后处理只修记谱时值，时间轴留给下游按需重算。
void ruleBeatReconcile(EngineState& st, const PostCorrectConfig& cfg,
                       JianpuDoc& doc) {
    // P1-1 返工·安全门：多声部（多行）稀疏声部的小节 target 不可信
    //   （稀疏声部 <forward> 不物化休止、中途进入声部等会让单声部 sum 远小于目标，
    //   盲目对账会制造此前 QA 曝光的 103 处 confidence=1.0 静默改写）。
    //   治本方案下多声部的 target 仍不可信，故整条规则跳过（其余四类规则不受影响，
    //   且 RestFill 也因 pendingRestFill 为空而保持静默）—— 守住"干净输入 0 修正"红线。
    if (doc.lines.size() > 1) return;

    struct Cand {
        int noteIdx = 0;
        int rung = 0, dots = 0;          // 目标格点
        int fromRung = 0, fromDots = 0;  // 原格点（用于确定性排序）
    };

    for (size_t li = 0; li < doc.lines.size(); ++li) {
        JianpuLine& line = doc.lines[li];
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            JianpuMeasure& m = line.measures[mi];
            if (m.notes.empty()) continue;   // 空小节：无归责对象

            // P1-1 返工：不完全小节(implicit)——记谱上的补白/弱起段，target 不适用，
            // 既不改也不标（比"行首弱起"更彻底：任意位置的 implicit 小节都跳过）。
            if (m.implicit) continue;

            // P1-1 返工：逐小节目标拍值（小节自身拍号优先，否则回退文档全局）
            const double target = measureTargetQl(doc, m);

            double sum = 0.0;
            bool anyUnresolvable = false;
            bool anyTuplet = false;
            bool anyTupletMissingNormal = false;
            for (const auto& n : m.notes) {
                sum += noteQuarterLength(n);
                if (n.rhythmUnresolvable) anyUnresolvable = true;
                if (n.tuplet > 0) {
                    anyTuplet = true;
                    if (n.tupletNormal <= 0) anyTupletMissingNormal = true;
                }
            }
            const double diff = sum - target;
            if (std::fabs(diff) < kEps) continue;   // ★ 不变量红线：归零即 no-op

            // P1-1 返工：含未解析时值的小节整条跳过（既不改也不标）。
            //   rhythmUnresolvable 是【转换层】的数据质量标记（7:4 / 9:8 等极端连音比
            //   无法映射为标准简谱时值），转换器已把它作为一等字段写进自身输出。
            //   后处理再复述一遍既不增加信息，又会让干净出版谱（Paganini Op.1 No.24
            //   的 7 连音/9 连音段）产生标记，直接破坏"干净输入 0 标记"红线。
            //   本引擎的职责是找 OMR 误识，不是复述表示能力的固有边界。
            if (anyUnresolvable) continue;

            // P1-1 返工：连音组 normal 未知时，占拍无法精确折算（如 7:4/9:8 等极端比
            //   解析层没给出 normal-notes），整小节跳过（保守，不赌——既不改也不标）。
            if (anyTuplet && anyTupletMissingNormal) continue;

            // 弱起小节：本行第一小节且占拍不足，按记谱惯例属合法不完全小节
            if (mi == 0 && diff < -kEps) continue;

            // P1-1 返工：结构性段落边界处的不足拍小节，是出版记谱的合法写法而非错误。
            //   反复段末尾小节与弱起互补（badinerie m16：2/4 里只有 1 拍 + 反向反复记号）、
            //   Fine / 终止小节收束（badinerie m40：1 拍 + light-heavy + 延长记号）都属此类。
            //   这类小节的"目标拍值"本就不适用，故对【不足】不做任何归责。
            //   注意只豁免不足，不豁免溢出——段落边界小节溢出仍是确定性错误。
            if (m.sectionEnd && diff < -kEps) continue;

            // ---- 枚举单音一步候选 ----
            std::vector<Cand> cands;
            for (size_t ni = 0; ni < m.notes.size(); ++ni) {
                int rung = 0, dots = 0;
                if (!noteLatticePos(m.notes[ni], rung, dots)) continue;
                const double oldQl = kLadder[rung].base * dotFactor(dots);
                for (int r = rung - 1; r <= rung + 1; ++r) {
                    if (r < 0 || r >= kRungCount) continue;
                    for (int d = dots - 1; d <= dots + 1; ++d) {
                        if (d < 0 || d > kMaxDots) continue;
                        if (r == rung && d == dots) continue;
                        const double newQl = kLadder[r].base * dotFactor(d);
                        if (std::fabs(sum - oldQl + newQl - target) < kEps) {
                            Cand c;
                            c.noteIdx = static_cast<int>(ni);
                            c.rung = r; c.dots = d;
                            c.fromRung = rung; c.fromDots = dots;
                            cands.push_back(c);
                        }
                    }
                }
            }

            std::set<int> candNotes;
            for (const auto& c : cands) candNotes.insert(c.noteIdx);

            if (candNotes.size() == 1) {
                // 唯一归责：同一音符上可能存在多个等价格点（时值理论上唯一，
                // 此处仍做确定性排序兜底，保证跨平台结果一致）。
                std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) {
                    const int da = std::abs(a.dots - a.fromDots);
                    const int db = std::abs(b.dots - b.fromDots);
                    if (da != db) return da < db;
                    const int ra = std::abs(a.rung - a.fromRung);
                    const int rb = std::abs(b.rung - b.fromRung);
                    if (ra != rb) return ra < rb;
                    if (a.rung != b.rung) return a.rung < b.rung;
                    return a.dots < b.dots;
                });
                const Cand& best = cands.front();
                JianpuNote& n = m.notes[static_cast<size_t>(best.noteIdx)];

                const std::string before = rhythmLabel(n);
                const std::string after = rhythmLabel(
                    kLadder[best.rung].underlines, kLadder[best.rung].augmentDashes,
                    best.dots, kLadder[best.rung].base * dotFactor(best.dots));

                std::string reason =
                    std::string("小节") + (diff > 0 ? "溢出 " : "不足 ") +
                    fmtQl(std::fabs(diff)) + " 拍(sum=" + fmtQl(sum) +
                    ", target=" + fmtQl(target) + ")，唯一可无歧义归责音符 #" +
                    std::to_string(best.noteIdx) + "(" + degreeLabel(n) +
                    ")，调整一个标准时值步后精确归零";

                if (cfg.autoFixBeatOverflow) {
                    n.underlines = kLadder[best.rung].underlines;
                    n.augmentDashes = kLadder[best.rung].augmentDashes;
                    n.dots = best.dots;
                    st.reconciledMeasures.insert(MeasureKey{static_cast<int>(li),
                                                            static_cast<int>(mi)});
                    applyFix(st, makeCorrection(CorrectionKind::BeatReconcile, line, m,
                                                best.noteIdx, before, after, reason, 1.0),
                             static_cast<int>(li), static_cast<int>(mi));
                } else {
                    flag(st, makeCorrection(CorrectionKind::BeatReconcile, line, m,
                                            best.noteIdx, before, after,
                                            reason + "（autoFixBeatOverflow=false，仅标记）",
                                            0.90));
                }
            } else if (!cands.empty()) {
                // 多个音符都能单独归零 -> 无法无歧义归责 -> 仅标记
                std::string who;
                for (int idx : candNotes) {
                    if (!who.empty()) who += ",";
                    who += "#" + std::to_string(idx);
                }
                flag(st, makeCorrection(
                    CorrectionKind::BeatReconcile, line, m, -1,
                    "sum=" + fmtQl(sum), "target=" + fmtQl(target),
                    std::string("小节") + (diff > 0 ? "溢出 " : "不足 ") +
                    fmtQl(std::fabs(diff)) + " 拍，存在 " +
                    std::to_string(candNotes.size()) + " 个等效候选音符(" + who +
                    ")，无法无歧义归责，仅标记待人工", 0.45));
            } else if (diff > 0.0) {
                // 溢出但无单音标准步可解（需跨多音）-> 仅标记
                flag(st, makeCorrection(
                    CorrectionKind::BeatReconcile, line, m, -1,
                    "sum=" + fmtQl(sum), "target=" + fmtQl(target),
                    "小节溢出 " + fmtQl(diff) +
                    " 拍，无单音标准时值步可精确归零（需跨多音改写），仅标记待人工", 0.35));
            } else {
                // 不足且无单音标准步可解 -> 交给规则 5 RestFill（绝不臆造休止）
                st.pendingRestFill.push_back(makeCorrection(
                    CorrectionKind::RestFill, line, m, -1,
                    "sum=" + fmtQl(sum), "target=" + fmtQl(target),
                    "小节占拍不足 " + fmtQl(-diff) +
                    " 拍且非单音标准步可解，疑似遗漏音符/休止（不自动填充）", 0.40));
            }
        }
    }
}

// ======================================================================
// 4. 规则 2：Accidental —— 临时记号 / 调号一致性（保守）
// ======================================================================
//
// 关键推导（这是守住不变量的核心）：
//   staffToJianpu 的 midiToJianpu 只可能产出三种临时记号取值：
//     None  —— 命中大调音阶；
//     Sharp —— 走 base=(semi-1)%12 分支，落点音级只可能是 {1,2,4,5,6}；
//     Flat  —— 走 base=(semi+1)%12 分支，落点音级只可能是 {2,3,5,6,7}。
//   因此以下取值组合【干净转换绝不可能产出】，一旦出现必是 OMR 误标或
//   文本输入笔误，可安全介入：
//     · Sharp 落在音级 3 或 7
//     · Flat  落在音级 1 或 4
//     · 任何 Natural（转换器从不产出还原号）
//     · 任何 DoubleSharp / DoubleFlat
//   规则只在这个"不可达取值域"上工作 => 干净输入必然 0 触发。
//
// 在此基础上再叠加"是否冗余于调号"判定：
//   首调体系下音级 1-7 已把调号吸收进去；调号所"变"的那些音级若再带同向
//   临时记号，就是 oemer 把调号记号误挂到音头上的典型症状。
//   f>0 时被升的音级顺序：7,3,6,2,5,1,4（G 大调 -> {7}；D 大调 -> {7,3} ...）
//   f<0 时被降的音级顺序：4,1,5,2,6,3,7（F 大调 -> {4}；Bb 大调 -> {4,1} ...）
//   小调按首调相对法（1=关系大调主音），fifths 相同，故复用同一张表。

const int kSharpOrder[7] = {7, 3, 6, 2, 5, 1, 4};
const int kFlatOrder[7]  = {4, 1, 5, 2, 6, 3, 7};

// 调号在首调体系下已吸收的音级集合
void keySignatureDegrees(int fifths, std::set<int>& sharped, std::set<int>& flatted) {
    sharped.clear();
    flatted.clear();
    int n = (fifths >= 0) ? fifths : -fifths;
    if (n > 7) n = 7;
    for (int i = 0; i < n; ++i) {
        if (fifths > 0) sharped.insert(kSharpOrder[i]);
        else if (fifths < 0) flatted.insert(kFlatOrder[i]);
    }
}

// 该 (音级, 记号) 组合是否为"干净转换不可达"
bool converterUnreachable(int degree, Accidental a) {
    switch (a) {
        case Accidental::Sharp:       return degree == 3 || degree == 7;
        case Accidental::Flat:        return degree == 1 || degree == 4;
        case Accidental::Natural:     return true;
        case Accidental::DoubleSharp: return true;
        case Accidental::DoubleFlat:  return true;
        default: return false;   // None
    }
}

void ruleAccidental(EngineState& st, const PostCorrectConfig& cfg, JianpuDoc& doc) {
    std::set<int> sharped, flatted;
    keySignatureDegrees(doc.fifths, sharped, flatted);

    for (size_t li = 0; li < doc.lines.size(); ++li) {
        JianpuLine& line = doc.lines[li];
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            JianpuMeasure& m = line.measures[mi];

            // 临时记号作用域：以小节为界（标准记谱惯例）。
            // 记录本小节内此前出现过非 None 记号的音级，供还原号合法性判定。
            std::set<int> degreesWithAcc;

            for (size_t ni = 0; ni < m.notes.size(); ++ni) {
                JianpuNote& n = m.notes[ni];
                const int noteIdx = static_cast<int>(ni);

                if (n.degree < 1 || n.degree > 7) continue;               // 休止/非法音级
                const Accidental a = n.accidental;
                if (a == Accidental::None) continue;                      // 无记号：不触发

                if (!converterUnreachable(n.degree, a)) {
                    // 干净转换可产出的合法记法（如 D 大调的 b7、Eb 大调的 b5），
                    // 属正常调外音，绝不介入 —— 这是 no-op 不变量的直接保障。
                    degreesWithAcc.insert(n.degree);
                    continue;
                }

                const std::string before = degreeLabel(n);
                const bool keyRedundantSharp =
                    (a == Accidental::Sharp) && doc.fifths > 0 && sharped.count(n.degree) > 0;
                const bool keyRedundantFlat =
                    (a == Accidental::Flat) && doc.fifths < 0 && flatted.count(n.degree) > 0;

                if (keyRedundantSharp || keyRedundantFlat) {
                    // trivially-safe 自修：调号已吸收该音级的变音，此处记号纯属冗余
                    n.accidental = Accidental::None;
                    applyFix(st, makeCorrection(
                        CorrectionKind::Accidental, line, m, noteIdx,
                        before, degreeLabel(n),
                        std::string("音级 ") + std::to_string(n.degree) + " 的 " +
                        accidentalName(a) + " 与调号(fifths=" +
                        std::to_string(doc.fifths) + ")重复：首调体系下该音级已含此变音，"
                        "且该组合为干净转换不可达，判定为 OMR 把调号记号误挂到音头，安全移除",
                        1.0), static_cast<int>(li), static_cast<int>(mi));
                } else if (a == Accidental::Natural) {
                    if (degreesWithAcc.count(n.degree) == 0) {
                        // 本小节内该音级此前无临时记号 -> 还原号无可还原对象。
                        // 首调体系下裸音级本就是调内音，还原号语义为空，安全移除。
                        n.accidental = Accidental::None;
                        applyFix(st, makeCorrection(
                            CorrectionKind::Accidental, line, m, noteIdx,
                            before, degreeLabel(n),
                            std::string("音级 ") + std::to_string(n.degree) +
                            " 的还原号在本小节内无可还原的前置临时记号，"
                            "首调体系下语义为空，安全移除", 1.0),
                            static_cast<int>(li), static_cast<int>(mi));
                    }
                    // 有前置临时记号 -> 合法还原号，放行不动
                } else if (a == Accidental::DoubleSharp || a == Accidental::DoubleFlat) {
                    if (!cfg.conservative) {
                        const Accidental demoted = (a == Accidental::DoubleSharp)
                            ? Accidental::Sharp : Accidental::Flat;
                        n.accidental = demoted;
                        applyFix(st, makeCorrection(
                            CorrectionKind::Accidental, line, m, noteIdx,
                            before, degreeLabel(n),
                            std::string("重升/重降记号极罕见，conservative=false 下"
                            "降级为单升/单降（低置信，建议人工复核）"), 0.50),
                            static_cast<int>(li), static_cast<int>(mi));
                    } else {
                        flag(st, makeCorrection(
                            CorrectionKind::Accidental, line, m, noteIdx,
                            before, before,
                            std::string("音级 ") + std::to_string(n.degree) + " 带 " +
                            accidentalName(a) +
                            "：干净转换不可达且极罕见，疑似 OMR 误识，仅标记", 0.40));
                    }
                } else {
                    // 不可达但与调号无关（如 C 大调的 #3 / F 大调的 b1）。
                    // 语义上等价于相邻音级，但直接删记号会改变音高，故默认只标记。
                    if (!cfg.conservative) {
                        n.accidental = Accidental::None;
                        applyFix(st, makeCorrection(
                            CorrectionKind::Accidental, line, m, noteIdx,
                            before, degreeLabel(n),
                            std::string("音级 ") + std::to_string(n.degree) + " 带 " +
                            accidentalName(a) +
                            "：干净转换不可达，conservative=false 下移除记号"
                            "（低置信，会改变音高，建议人工复核）", 0.50),
                            static_cast<int>(li), static_cast<int>(mi));
                    } else {
                        flag(st, makeCorrection(
                            CorrectionKind::Accidental, line, m, noteIdx,
                            before, before,
                            std::string("音级 ") + std::to_string(n.degree) + " 带 " +
                            accidentalName(a) +
                            "：干净转换不可达（首调下等价于相邻音级），疑似记号误识，仅标记",
                            0.50));
                    }
                }

                degreesWithAcc.insert(n.degree);
            }
        }
    }
}

// ======================================================================
// 5. 规则 3：OctaveDot —— 八度点异常（保守，以标记为主）
// ======================================================================
//
// 绝对音高在转换后已坍缩为首调音级，真实八度无法恢复，故本规则只做
// "内部一致性"检查：
//   (a) 延音线两端音级相同但八度点不同 —— 延音线在定义上连接同一音高，
//       这是自洽性硬矛盾，可锚定前一音无歧义修复（confidence=0.9）。
//       干净输入下延音两端由同一音高分别换算，必然一致 => 0 触发。
//   (b) 相邻音跨 >= 2 个八度（24 半音）的跳变 —— 仅标记，不自修。
//       若该跳变"跳出去又跳回来"（孤立尖刺），置信度提高；
//       仅在 conservative=false 时才做轻量自修（锚定前一音的八度区）。

const int kDegreeSemitone[8] = {0, 0, 2, 4, 5, 7, 9, 11};   // 下标 = 音级 1..7

int pitchPosition(const JianpuNote& n) {
    int d = n.degree;
    if (d < 1 || d > 7) d = 1;
    return n.octaveDots * 12 + kDegreeSemitone[d];
}

// 使某音尽量贴近 anchorPos 的八度点取值
int nearestOctaveDots(const JianpuNote& n, int anchorPos) {
    int d = n.degree;
    if (d < 1 || d > 7) d = 1;
    const double raw = static_cast<double>(anchorPos - kDegreeSemitone[d]) / 12.0;
    return static_cast<int>(std::lround(raw));
}

void ruleOctaveDot(EngineState& st, const PostCorrectConfig& cfg, JianpuDoc& doc) {
    if (!cfg.flagOctaveJumps) return;

    // 一行内的发声音序列（跨小节连续；休止与装饰音不参与旋律轮廓判定）
    struct Anchor { int mi = 0; int ni = 0; };

    for (size_t li = 0; li < doc.lines.size(); ++li) {
        JianpuLine& line = doc.lines[li];

        std::vector<Anchor> seq;
        for (size_t mi = 0; mi < line.measures.size(); ++mi) {
            const JianpuMeasure& m = line.measures[mi];
            for (size_t ni = 0; ni < m.notes.size(); ++ni) {
                const JianpuNote& n = m.notes[ni];
                if (n.degree == 0 || n.isGrace) continue;
                seq.push_back(Anchor{static_cast<int>(mi), static_cast<int>(ni)});
            }
        }
        if (seq.size() < 2) continue;

        auto noteAt = [&](const Anchor& a) -> JianpuNote& {
            return line.measures[static_cast<size_t>(a.mi)]
                       .notes[static_cast<size_t>(a.ni)];
        };

        for (size_t k = 1; k < seq.size(); ++k) {
            JianpuNote& prev = noteAt(seq[k - 1]);
            JianpuNote& curr = noteAt(seq[k]);
            JianpuMeasure& currMeasure = line.measures[static_cast<size_t>(seq[k].mi)];

            // ---- (a) 延音线八度自洽（trivially-safe，可无歧义修复）----
            if (prev.tieToNext && curr.tieFromPrev &&
                prev.degree == curr.degree && prev.octaveDots != curr.octaveDots) {
                const std::string before = degreeLabel(curr);
                const int oldDots = curr.octaveDots;
                curr.octaveDots = prev.octaveDots;
                applyFix(st, makeCorrection(
                    CorrectionKind::OctaveDot, line, currMeasure, seq[k].ni,
                    before, degreeLabel(curr),
                    "延音线两端音级相同(" + std::to_string(prev.degree) +
                    ")但八度点不一致(" + std::to_string(prev.octaveDots) + " vs " +
                    std::to_string(oldDots) +
                    ")，延音线定义上连接同一音高，锚定前一音修复",
                    0.90), static_cast<int>(li), static_cast<int>(seq[k].mi));
                continue;
            }

            // ---- (b) 大跨度八度跳变 ----
            const int prevPos = pitchPosition(prev);
            const int currPos = pitchPosition(curr);
            const int jump = std::abs(currPos - prevPos);
            if (jump < 24) continue;   // 阈值：>= 2 个八度才视为异常

            // 孤立尖刺：跳出去又跳回来，且前后两音在同一音区内
            bool spike = false;
            if (k + 1 < seq.size()) {
                const int nextPos = pitchPosition(noteAt(seq[k + 1]));
                if (std::abs(nextPos - prevPos) < 12 && std::abs(currPos - nextPos) >= 24)
                    spike = true;
            }

            // P1-1 返工·关键收紧：只有【孤立尖刺】才是八度点误识的可辨识特征。
            //   单纯的"相邻音跨 >= 2 个八度"在真实出版曲目中是完全正常的音区转换：
            //   实测 7 份出版 GT 谱共 54 处 >= 24 半音跳变（Paganini Op.1 No.24 41 处、
            //   Bach BWV1004 6 处、Summer 5 处、Vivaldi 2 处，最大 43 半音），
            //   其中【尖刺 0 处】——即该分支 54/54 全是误报，把"大跳=异常"当前提是错的。
            //   反之，"跳出去 >= 2 个八度、又立刻跳回原音区"才违反旋律连续性，
            //   是 oemer 把八度点加错/漏加的典型症状，且在同一批 GT 上 0 触发。
            //   故非尖刺的大跳一律放行，守住"干净输入 0 标记"红线。
            if (!spike) continue;

            const std::string before = degreeLabel(curr);
            const std::string detail =
                "相邻音 " + degreeLabel(prev) + " -> " + before + " 跳变 " +
                std::to_string(jump) + " 个半音(>= 2 个八度)";

            // 走到这里必为孤立尖刺（非尖刺已在上方 continue）
            if (!cfg.conservative) {
                const int fixed = nearestOctaveDots(curr, prevPos);
                curr.octaveDots = fixed;
                applyFix(st, makeCorrection(
                    CorrectionKind::OctaveDot, line, currMeasure, seq[k].ni,
                    before, degreeLabel(curr),
                    detail + "，且为跳出即跳回的孤立尖刺；conservative=false 下"
                    "锚定前一音区回收八度点（低置信，建议人工复核）", 0.55),
                    static_cast<int>(li), static_cast<int>(seq[k].mi));
            } else {
                flag(st, makeCorrection(
                    CorrectionKind::OctaveDot, line, currMeasure, seq[k].ni,
                    before, before,
                    detail + "，且为跳出即跳回的孤立尖刺，高度疑似八度点误识"
                    "；真实八度已在首调坍缩中丢失，不自动修复，仅标记", 0.60));
            }
        }
    }
}

// ======================================================================
// 6. 规则 4：TupletGroup —— 连音组自洽（只标记）
// ======================================================================
//
// 只检查"结构性不自洽"，不碰时值：
//   · tuplet 标注值 < 2（非法连音比）
//   · 同值连音组成员数不是 tuplet 的整数倍（如三连音只识别出 2 个）
//   · 组内含未解析时值
// 混合时值连音组（四分+八分三连音）是合法记谱，不标记。
void ruleTupletGroup(EngineState& st, JianpuDoc& doc) {
    for (const auto& line : doc.lines) {
        for (const auto& m : line.measures) {
            size_t i = 0;
            while (i < m.notes.size()) {
                const int t = m.notes[i].tuplet;
                if (t <= 0) { ++i; continue; }

                size_t j = i;
                while (j < m.notes.size() && m.notes[j].tuplet == t) ++j;
                const int count = static_cast<int>(j - i);
                const std::string span =
                    "#" + std::to_string(i) + "..#" + std::to_string(j - 1);

                if (t < 2) {
                    flag(st, makeCorrection(
                        CorrectionKind::TupletGroup, line, m, static_cast<int>(i),
                        "tuplet=" + std::to_string(t), "tuplet=" + std::to_string(t),
                        "非法连音组标注（actual-notes 必须 >= 2），成员 " + span + "，仅标记",
                        0.50));
                } else if (count % t != 0) {
                    flag(st, makeCorrection(
                        CorrectionKind::TupletGroup, line, m, static_cast<int>(i),
                        "count=" + std::to_string(count), "count%" + std::to_string(t) + "==0",
                        std::to_string(t) + " 连音组连续成员数为 " + std::to_string(count) +
                        "，不是 " + std::to_string(t) + " 的整数倍，疑似漏识/多识成员(" +
                        span + ")，仅标记", 0.50));
                }
                // P1-1 返工：删除"连音组内含未解析时值"标记分支。
                //   rhythmUnresolvable 表示 7:4 / 9:8 等极端连音比无法映射为标准简谱
                //   时值——这是简谱【表示能力】的固有边界，不是连音组结构不自洽，
                //   更不是 OMR 误识。转换器已在自身输出里逐音记录该字段，后处理复述
                //   只会让干净出版谱（Paganini Op.1 No.24 的 7/9 连音段共 4 处）产生
                //   标记，破坏红线。本规则只保留真正的结构性不自洽检查
                //   （非法连音比 t<2、成员数不成组 count%t!=0）。
                i = j;
            }
        }
    }
}

// ======================================================================
// 7. 规则 5：RestFill —— 疑似遗漏音符/休止（只标记，绝不臆造）
// ======================================================================
void ruleRestFill(EngineState& st) {
    for (auto& c : st.pendingRestFill)
        st.report->flagged.push_back(std::move(c));
    st.pendingRestFill.clear();
}

// ======================================================================
// 8. JSON 序列化
// ======================================================================

std::string correctionToJson(const Correction& c) {
    std::string s = "{";
    s += "\"kind\":\"" + std::string(correctionKindName(c.kind)) + "\"";
    s += ",\"part\":" + std::to_string(c.part);
    s += ",\"voice\":" + std::to_string(c.voice);
    s += ",\"measure\":" + std::to_string(c.measure);
    s += ",\"noteIndex\":" + std::to_string(c.noteIndex);
    s += ",\"before\":\"" + jsonEscape(c.before) + "\"";
    s += ",\"after\":\"" + jsonEscape(c.after) + "\"";
    s += ",\"reason\":\"" + jsonEscape(c.reason) + "\"";
    s += ",\"confidence\":" + fmtConfidence(c.confidence);
    s += "}";
    return s;
}

} // anonymous namespace

// ======================================================================
// 9. 对外入口
// ======================================================================

JianpuDoc correctJianpuDoc(JianpuDoc doc, const PostCorrectConfig& cfg,
                           PostCorrectReport& report) {
    report = PostCorrectReport{};
    if (!cfg.enabled) return doc;   // 总开关关闭：原样返回，零副作用

    EngineState st;
    st.report = &report;

    // 固定执行顺序：BeatReconcile -> Accidental -> OctaveDot -> TupletGroup -> RestFill
    // 注：BeatReconcile 现自行按"逐小节"计算 target（含多声部安全门），不再由外部分发。
    ruleBeatReconcile(st, cfg, doc);
    if (cfg.enforceKeyConsistency) ruleAccidental(st, cfg, doc);
    ruleOctaveDot(st, cfg, doc);
    ruleTupletGroup(st, doc);
    ruleRestFill(st);

    report.measuresReconciled = static_cast<int>(st.reconciledMeasures.size());
    report.notesTouched = static_cast<int>(st.touchedNotes.size());
    return doc;
}

std::string postCorrectReportToJson(const PostCorrectReport& report) {
    std::string j = "{";
    j += "\"measuresReconciled\":" + std::to_string(report.measuresReconciled);
    j += ",\"notesTouched\":" + std::to_string(report.notesTouched);
    j += ",\"appliedCount\":" + std::to_string(report.applied.size());
    j += ",\"flaggedCount\":" + std::to_string(report.flagged.size());

    j += ",\"applied\":[";
    for (size_t i = 0; i < report.applied.size(); ++i) {
        if (i) j += ",";
        j += correctionToJson(report.applied[i]);
    }
    j += "]";

    j += ",\"flagged\":[";
    for (size_t i = 0; i < report.flagged.size(); ++i) {
        if (i) j += ",";
        j += correctionToJson(report.flagged[i]);
    }
    j += "]";

    j += "}";
    return j;
}

bool writePostCorrectReportFile(const PostCorrectReport& report,
                                const std::string& path) {
    if (path.empty()) return false;
    std::ofstream f(path, std::ios::binary);
    if (!f) return false;
    f << postCorrectReportToJson(report);
    return static_cast<bool>(f);
}

} // namespace pudu
