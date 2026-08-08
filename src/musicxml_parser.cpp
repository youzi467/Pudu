// ----------------------------------------------------------------------
// 谱渡 Pudu · MusicXML 解析器骨架实现（pugixml）
// 覆盖 MVP 标签集：score-partwise / part / measure / attributes / note
// 额外处理（阶段 2 前置）：<chord>(和弦归并) / <grace>(装饰音) /
//   <backup><forward>(时间游标) / <voice>(声部) —— 见 score_model.hpp Note 字段。
// 仍未处理（详见 musicxml_mvp_tags.md §3）：lyric / notations / <staff> 分层 /
//   多谱号共存 / 连音 tuplet 等。
// ----------------------------------------------------------------------

#include "musicxml_parser.hpp"

#include <sstream>
#include <fstream>
#include <windows.h>

namespace {

// UTF-8 路径 -> 宽字符，供 pugixml 的 wchar_t* load_file 使用，
// 从而支持含中文/特殊字符的路径（ANSI fopen 在中文 Windows 下会失败）
std::wstring utf8ToWide(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, nullptr, 0);
    if (n <= 1) return {};
    std::wstring w(n - 1, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), -1, &w[0], n);
    return w;
}

// 是否为 ZIP 文件（.mxl 即 ZIP）：魔数 "PK"（0x50 0x4B）
bool isZipFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    unsigned char sig[2] = {0, 0};
    f.read(reinterpret_cast<char*>(sig), 2);
    return f.gcount() == 2 && sig[0] == 'P' && sig[1] == 'K';
}

} // namespace

namespace pudu {

bool MusicXMLParser::loadFromFile(const std::string& path, Score& out, std::string& err) {
    // 预检：.mxl 本质是 ZIP 压缩包，pugixml 只能解析纯 XML
    if (isZipFile(path)) {
        err = "不支持 .mxl 压缩格式(本质是 ZIP)。请用 MuseScore/OpenScore 将谱面另存为 .musicxml(纯 XML)后重试。";
        return false;
    }
    // 用宽字符接口打开，支持含中文/特殊字符的 UTF-8 路径
    pugi::xml_document doc;
    pugi::xml_parse_result res = doc.load_file(utf8ToWide(path).c_str());
    if (!res) {
        std::ostringstream os;
        os << "解析失败: " << res.description() << " (offset " << res.offset << ")";
        err = os.str();
        return false;
    }
    return parseDocument(doc, out, err);
}

bool MusicXMLParser::parseString(const std::string& xml, Score& out, std::string& err) {
    pugi::xml_document doc;
    pugi::xml_parse_result res = doc.load_string(xml.c_str());
    if (!res) {
        std::ostringstream os;
        os << "解析失败: " << res.description() << " (offset " << res.offset << ")";
        err = os.str();
        return false;
    }
    return parseDocument(doc, out, err);
}

bool MusicXMLParser::parseDocument(const pugi::xml_document& doc, Score& out, std::string& err) {
    pugi::xml_node root = doc.child("score-partwise");
    if (!root) {
        err = "根元素 <score-partwise> 缺失：当前只支持 score-partwise 组织方式";
        return false;
    }

    // 标题（可选）：movement-title 优先，否则 work/work-title
    if (pugi::xml_node titleNode = root.child("movement-title")) {
        out.title = titleNode.text().as_string();
    } else if (pugi::xml_node work = root.child("work")) {
        if (pugi::xml_node wt = work.child("work-title")) {
            out.title = wt.text().as_string();
        }
    }

    // 遍历所有 <part>
    for (pugi::xml_node partNode : root.children("part")) {
        parsePart(partNode, out);
    }

    // 阶段 2 前置：解析 <credit> 抬头行（标题/作者等），并优选主标题
    parseCredits(root, out);
    out.pickTitle();

    return true;
}

void MusicXMLParser::parseCredits(const pugi::xml_node& root, Score& out) {
    for (pugi::xml_node creditNode : root.children("credit")) {
        // 一个 <credit> 可能含多条 <credit-words>（如标题+副标题分行）
        for (pugi::xml_node cw : creditNode.children("credit-words")) {
            Credit c;
            c.text = cw.text().as_string();
            if (pugi::xml_node y = cw.child("default-y"))
                c.defaultY = y.text().as_int(0);
            if (pugi::xml_node j = cw.child("justify"))
                c.justification = j.text().as_string();
            // 仅保留有效行（非空），保持数据干净
            if (c.isValid()) out.credits.push_back(c);
        }
    }
}

void MusicXMLParser::parsePart(const pugi::xml_node& partNode, Score& out) {
    Part part;
    part.id = partNode.attribute("id").as_string();

    // 从 part-list/score-part 按 id 取名字
    pugi::xml_node root = partNode.parent();
    if (pugi::xml_node partList = root.child("part-list")) {
        for (pugi::xml_node sp : partList.children("score-part")) {
            if (std::string(sp.attribute("id").as_string()) == part.id) {
                if (pugi::xml_node pn = sp.child("part-name")) {
                    part.name = pn.text().as_string();
                }
                break;
            }
        }
    }

    // MVP：每部谱首次遇到 <attributes> 时读取一次
    //      （含 divisions / key / time / clef；多声部各自独立）
    attributesSeen_ = false;
    // 阶段 2 前置：时间游标随每个声部重新计时
    qcursor_ = 0.0;
    // P1-1：当前拍号随每个声部重新计时（首拍号将由首个含 <time> 的 <measure> 写入）
    currentBeats_ = 0;
    currentBeatType_ = 0;
    timeDefaultSeen_ = false;

    for (pugi::xml_node measureNode : partNode.children("measure")) {
        parseMeasure(measureNode, part);
    }

    out.parts.push_back(part);
}

void MusicXMLParser::parseMeasure(const pugi::xml_node& measureNode, Part& part) {
    Measure measure;
    measure.number = measureNode.attribute("number").as_int(0);

    // P1-1：不完全小节标记（repeat 末尾补白 / 弱起段等）。解析层只在真正标了
    //   implicit="yes" 时才置 true，不改变任何既有单声部单拍号行为。
    if (std::string(measureNode.attribute("implicit").as_string()) == "yes")
        measure.implicit = true;

    // P1-1 返工：结构性段落边界识别。出版谱中，反复段末尾 / Fine / 终止小节
    //   经常是合法的不完全小节（与弱起互补），其占拍天然小于拍号目标值。
    //   只读取【右侧】小节线（location 缺省即 "right"），避免把段落起始的
    //   正向反复记号误当作段落结束。
    for (pugi::xml_node bl : measureNode.children("barline")) {
        const std::string loc = bl.attribute("location").as_string("right");
        if (loc != "right") continue;
        if (bl.child("repeat") || bl.child("ending")) {
            measure.sectionEnd = true;
            break;
        }
        const std::string style = bl.child("bar-style").text().as_string("");
        if (style == "light-heavy" || style == "heavy-light" ||
            style == "light-light" || style == "heavy-heavy") {
            measure.sectionEnd = true;
            break;
        }
    }

    // P1-1：本小节先继承"当前生效拍号"（向后沿用上一个见到的值）。若该小节自身
    //   含 <time>，下方会在遍历子节点时更新 currentBeats_/currentBeatType_ 并覆盖这里。
    measure.beats = currentBeats_;
    measure.beatType = currentBeatType_;

    for (pugi::xml_node child : measureNode.children()) {
        std::string name = child.name();

        if (name == "attributes") {
            // —— 仅首块读取：divisions / key / clef（每部谱只读一次）——
            if (!attributesSeen_) {
                if (pugi::xml_node d = child.child("divisions"))
                    part.attributes.divisions = d.text().as_int(1);

                if (pugi::xml_node k = child.child("key")) {
                    if (pugi::xml_node f = k.child("fifths"))
                        part.attributes.fifths = f.text().as_int(0);
                    if (pugi::xml_node m = k.child("mode"))
                        part.attributes.mode = m.text().as_string();
                }

                if (pugi::xml_node c = child.child("clef")) {
                    if (pugi::xml_node s = c.child("sign"))
                        part.attributes.clefSign = s.text().as_string();
                    if (pugi::xml_node l = c.child("line"))
                        part.attributes.clefLine = l.text().as_int(2);
                }
                attributesSeen_ = true;
            }

            // —— 拍号：每个含 <time> 的 <attributes> 都更新"当前拍号"（支持曲中变拍号）——
            //   首拍号同时写入 part.attributes（作全局默认）；后续变拍号只更新当前值，
            //   不动全局默认，供后处理引擎逐小节精确对账。
            if (pugi::xml_node t = child.child("time")) {
                if (pugi::xml_node b = t.child("beats")) {
                    const int v = b.text().as_int(currentBeats_ > 0 ? currentBeats_ : 4);
                    currentBeats_ = v;
                    if (!timeDefaultSeen_) part.attributes.beats = v;  // 首拍号作全局默认
                    measure.beats = v;
                }
                if (pugi::xml_node bt = t.child("beat-type")) {
                    const int v = bt.text().as_int(currentBeatType_ > 0 ? currentBeatType_ : 4);
                    currentBeatType_ = v;
                    if (!timeDefaultSeen_) part.attributes.beatType = v;
                    measure.beatType = v;
                }
                timeDefaultSeen_ = true;  // 首 <time> 块已处理完，后续变拍号不再动全局默认
            }

        } else if (name == "note") {
            // 阶段 2 前置：传入当前游标，由 parseNote 填充 onset 并推进/回退游标
            parseNote(child, measure, part.attributes.divisions);

        } else if (name == "backup") {
            // 时间回退到上一层（多声部时声部2 重新开始）。游标回退备份的时长(换算为 quarterLength)。
            if (pugi::xml_node dur = child.child("duration"))
                qcursor_ -= static_cast<double>(dur.text().as_llong(0)) / part.attributes.divisions;
            if (qcursor_ < 0) qcursor_ = 0.0;

        } else if (name == "forward") {
            // 时间前进（占位，常用于小节开头对齐）。游标前进前进的时长(换算为 quarterLength)。
            if (pugi::xml_node dur = child.child("duration"))
                qcursor_ += static_cast<double>(dur.text().as_llong(0)) / part.attributes.divisions;
        }
        // 其余子元素（direction/sound 等）MVP 跳过
    }

    part.measures.push_back(measure);
}

void MusicXMLParser::parseNote(const pugi::xml_node& noteNode, Measure& measure,
                                int divisions) {
    // 阶段 2 前置：是否为和弦后续音 / 装饰音
    bool isChord = (bool)noteNode.child("chord");
    bool isGrace = (bool)noteNode.child("grace");

    // 解析基础音高
    Pitch p;
    p.hasValue = false;
    if (noteNode.child("rest")) {
        // 休止符：交给下方 note.isRest 处理
    } else if (pugi::xml_node pitch = noteNode.child("pitch")) {
        if (pugi::xml_node step = pitch.child("step")) {
            std::string s = step.text().as_string();
            if (!s.empty()) {
                p.step = s[0];
                p.hasValue = true;
            }
        }
        if (pugi::xml_node alt = pitch.child("alter"))
            p.alter = alt.text().as_int(0);
        if (pugi::xml_node oct = pitch.child("octave"))
            p.octave = oct.text().as_int(4);
    }

    // 和弦后续音：并入上一音的 chordPitches，不单独成事件、不推进时间轴
    if (isChord && !measure.notes.empty()) {
        measure.notes.back().chordPitches.push_back(p);
        return;
    }

    // 普通音符（含和弦首个音、休止符）
    Note note;
    note.isRest = (bool)noteNode.child("rest");
    note.pitch = p;
    note.isGrace = isGrace;

    // 阶段 2 前置：起始位置 = 当前游标(quarterLength)
    note.onset = qcursor_;

    // 声部/层编号（来自 <voice>，默认 1）
    if (pugi::xml_node v = noteNode.child("voice"))
        note.voice = v.text().as_int(1);

    // 时值（pugixml 新版以 as_llong 取代 as_long）；装饰音无 duration，按 0 处理
    long dur = 0;
    if (pugi::xml_node durNode = noteNode.child("duration"))
        dur = static_cast<long>(durNode.text().as_llong(0));
    note.duration = dur;
    // 时值换算为 quarterLength（与 onset 同量纲），基于当前生效的 divisions，
    // 即使后续 <divisions> 变更也不影响本音——节奏推导以此为准（更稳健于 <type>/<duration> 不一致）。
    note.quarterLength = isGrace ? 0.0 : static_cast<double>(dur) / divisions;

    // 阶段 2 前置：仅非装饰音推进时间游标(quarterLength = duration/divisions)
    if (!isGrace)
        qcursor_ += static_cast<double>(dur) / divisions;

    // 时值图形名
    if (pugi::xml_node type = noteNode.child("type"))
        note.type = type.text().as_string();

    // 连音组 <time-modification>：读取实际/常规音符数（选项 A：标注连音分组）。
    // 语料实测每个连音音符均自带 <time-modification>，故逐音符解析即可覆盖全部连音组，
    // 无需跨音符传播。解析器对多声部谱按声部独立解析，连音组不跨声部。
    if (pugi::xml_node tm = noteNode.child("time-modification")) {
        if (pugi::xml_node an = tm.child("actual-notes"))
            note.tupletActual = an.text().as_int(0);
        if (pugi::xml_node nn = tm.child("normal-notes"))
            note.tupletNormal = nn.text().as_int(0);
    }

    // 附点
    for (pugi::xml_node d : noteNode.children("dot")) {
        (void)d;
        ++note.dots;
    }

    // 延音线 <tie type="start|stop">
    for (pugi::xml_node tie : noteNode.children("tie")) {
        std::string t = tie.attribute("type").as_string();
        if (t == "start")      note.tieStart = true;
        else if (t == "stop")  note.tieStop = true;
    }

    measure.notes.push_back(note);
}

} // namespace pudu
