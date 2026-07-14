// ----------------------------------------------------------------------
// 谱渡 Pudu · MusicXML 解析器骨架实现（pugixml）
// 覆盖 MVP 标签集：score-partwise / part / measure / attributes / note
// 跳过项见 musicxml_mvp_tags.md §3（chord/voice/lyric/notations/...）
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
    return true;
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

    for (pugi::xml_node measureNode : partNode.children("measure")) {
        parseMeasure(measureNode, part);
    }

    out.parts.push_back(part);
}

void MusicXMLParser::parseMeasure(const pugi::xml_node& measureNode, Part& part) {
    Measure measure;
    measure.number = measureNode.attribute("number").as_int(0);

    for (pugi::xml_node child : measureNode.children()) {
        std::string name = child.name();

        if (name == "attributes" && !attributesSeen_) {
            if (pugi::xml_node d = child.child("divisions"))
                part.attributes.divisions = d.text().as_int(1);

            if (pugi::xml_node k = child.child("key")) {
                if (pugi::xml_node f = k.child("fifths"))
                    part.attributes.fifths = f.text().as_int(0);
                if (pugi::xml_node m = k.child("mode"))
                    part.attributes.mode = m.text().as_string();
            }

            if (pugi::xml_node t = child.child("time")) {
                if (pugi::xml_node b = t.child("beats"))
                    part.attributes.beats = b.text().as_int(4);
                if (pugi::xml_node bt = t.child("beat-type"))
                    part.attributes.beatType = bt.text().as_int(4);
            }

            if (pugi::xml_node c = child.child("clef")) {
                if (pugi::xml_node s = c.child("sign"))
                    part.attributes.clefSign = s.text().as_string();
                if (pugi::xml_node l = c.child("line"))
                    part.attributes.clefLine = l.text().as_int(2);
            }
            attributesSeen_ = true;

        } else if (name == "note") {
            parseNote(child, measure);
        }
        // 其余子元素（backup/forward/direction 等）MVP 跳过
    }

    part.measures.push_back(measure);
}

void MusicXMLParser::parseNote(const pugi::xml_node& noteNode, Measure& measure) {
    Note note;

    // 休止符：有 <rest> 子元素
    if (noteNode.child("rest")) {
        note.isRest = true;
    } else if (pugi::xml_node pitch = noteNode.child("pitch")) {
        if (pugi::xml_node step = pitch.child("step")) {
            std::string s = step.text().as_string();
            if (!s.empty()) {
                note.pitch.step = s[0];
                note.pitch.hasValue = true;
            }
        }
        if (pugi::xml_node alt = pitch.child("alter"))
            note.pitch.alter = alt.text().as_int(0);
        if (pugi::xml_node oct = pitch.child("octave"))
            note.pitch.octave = oct.text().as_int(4);
    }

    // 时值（pugixml 新版以 as_llong 取代 as_long）
    if (pugi::xml_node dur = noteNode.child("duration"))
        note.duration = static_cast<long>(dur.text().as_llong(0));

    // 时值图形名
    if (pugi::xml_node type = noteNode.child("type"))
        note.type = type.text().as_string();

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
