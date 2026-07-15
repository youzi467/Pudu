// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 3 反向转换（G2）：Score -> MusicXML（score-partwise）
// 用 pugixml 写出，与 MusicXMLParser 对称；写出文件可被本仓库解析器读回且语义等价。
//   - 多声部用 <backup>/<forward> 还原并行时序；和弦后续音用 <chord/>；
//   - <attributes> 含 divisions / key(fifths+mode) / time / clef。
// 不写 lyric / notations / 多谱号等（MVP，与解析器一致）。
// ----------------------------------------------------------------------

#include "jianpu_to_staff.hpp"

#include <pugixml.hpp>

#include <algorithm>  // std::sort（显式 include：MSVC 不隐式带入，g++ 靠传递性 include 通过）
#include <sstream>
#include <vector>     // std::vector（本文件直接使用，显式 include 保证跨编译器一致）

namespace pudu {

namespace {

// 写出单条 <note>（实音/休止）。和弦后续音(chordPitches)作为同级 <note><chord/> 追加到 parent。
void appendNote(pugi::xml_node parent, const Note& n, int divisions) {
    pugi::xml_node note = parent.append_child("note");
    if (n.isGrace) note.append_child("grace");

    if (n.isRest) {
        note.append_child("rest");
    } else {
        pugi::xml_node pitch = note.append_child("pitch");
        pitch.append_child("step").text() = std::string(1, n.pitch.step).c_str();
        if (n.pitch.alter != 0)
            pitch.append_child("alter").text() = n.pitch.alter;
        pitch.append_child("octave").text() = n.pitch.octave;
    }

    note.append_child("duration").text() = n.duration;
    if (!n.type.empty())
        note.append_child("type").text() = n.type.c_str();
    for (int i = 0; i < n.dots; ++i) note.append_child("dot");
    if (n.tieStart) { auto t = note.append_child("tie"); t.append_attribute("type") = "start"; }
    if (n.tieStop)  { auto t = note.append_child("tie"); t.append_attribute("type") = "stop"; }
    note.append_child("voice").text() = n.voice;

    // 和弦成员：作为同级 <note><chord/> 追加，解析器会并入上一音的 chordPitches
    for (const auto& cp : n.chordPitches) {
        pugi::xml_node cn = parent.append_child("note");
        cn.append_child("chord");
        pugi::xml_node cpitch = cn.append_child("pitch");
        cpitch.append_child("step").text() = std::string(1, cp.step).c_str();
        if (cp.alter != 0)
            cpitch.append_child("alter").text() = cp.alter;
        cpitch.append_child("octave").text() = cp.octave;
        cn.append_child("duration").text() = n.duration;
        if (!n.type.empty())
            cn.append_child("type").text() = n.type.c_str();
        if (n.tieStart) { auto t = cn.append_child("tie"); t.append_attribute("type") = "start"; }
        cn.append_child("voice").text() = n.voice;
    }
}

// 时间占位：<forward>（前进）/<backup>（回退），duration 单位 = divisions。
void appendForward(pugi::xml_node parent, long dur) {
    if (dur <= 0) return;
    pugi::xml_node f = parent.append_child("forward");
    f.append_child("duration").text() = dur;
}
void appendBackup(pugi::xml_node parent, long dur) {
    if (dur <= 0) return;
    pugi::xml_node b = parent.append_child("backup");
    b.append_child("duration").text() = dur;
}

} // anonymous namespace

std::string scoreToMusicXML(const Score& score) {
    pugi::xml_document doc;

    auto decl = doc.prepend_child(pugi::node_declaration);
    decl.append_attribute("version") = "1.0";
    decl.append_attribute("encoding") = "UTF-8";

    pugi::xml_node root = doc.append_child("score-partwise");
    root.append_attribute("version") = "4.0";

    if (!score.title.empty())
        root.append_child("movement-title").text() = score.title.c_str();

    // part-list / score-part
    pugi::xml_node partList = root.append_child("part-list");
    for (const auto& part : score.parts) {
        pugi::xml_node sp = partList.append_child("score-part");
        sp.append_attribute("id") = part.id.c_str();
        sp.append_child("part-name").text() = part.name.c_str();
    }

    // 各声部
    for (const auto& part : score.parts) {
        pugi::xml_node partNode = root.append_child("part");
        partNode.append_attribute("id") = part.id.c_str();

        bool attrEmitted = false;
        double cursor = 0.0;   // 绝对 onset 游标（quarterLength），跨小节连续，与解析器 qcursor_ 对称

        for (const auto& measure : part.measures) {
            pugi::xml_node mNode = partNode.append_child("measure");
            mNode.append_attribute("number") = std::to_string(measure.number).c_str();

            if (!attrEmitted) {
                pugi::xml_node attr = mNode.append_child("attributes");
                attr.append_child("divisions").text() = part.attributes.divisions;
                pugi::xml_node key = attr.append_child("key");
                key.append_child("fifths").text() = part.attributes.fifths;
                key.append_child("mode").text() = part.attributes.mode.c_str();
                pugi::xml_node time = attr.append_child("time");
                time.append_child("beats").text() = part.attributes.beats;
                time.append_child("beat-type").text() = part.attributes.beatType;
                pugi::xml_node clef = attr.append_child("clef");
                clef.append_child("sign").text() = part.attributes.clefSign.c_str();
                clef.append_child("line").text() = part.attributes.clefLine;
                attrEmitted = true;
            }

            // 本小节音符按 (onset, voice) 排序后发出；用 backup/forward 对齐并行时序
            std::vector<const Note*> ordered;
            for (const auto& n : measure.notes) ordered.push_back(&n);
            std::sort(ordered.begin(), ordered.end(),
                      [](const Note* a, const Note* b) {
                          if (std::fabs(a->onset - b->onset) > 1e-9) return a->onset < b->onset;
                          return a->voice < b->voice;
                      });

            for (const auto* np : ordered) {
                const Note& n = *np;
                double ql = n.isGrace ? 0.0
                                     : static_cast<double>(n.duration) / part.attributes.divisions;
                if (n.onset > cursor + 1e-9) {
                    appendForward(mNode, static_cast<long>(std::llround((n.onset - cursor) * part.attributes.divisions)));
                    cursor = n.onset;
                } else if (n.onset < cursor - 1e-9) {
                    appendBackup(mNode, static_cast<long>(std::llround((cursor - n.onset) * part.attributes.divisions)));
                    cursor = n.onset;
                }
                appendNote(mNode, n, part.attributes.divisions);
                if (!n.isGrace) cursor += ql;
            }
        }
    }

    std::ostringstream os;
    doc.save(os, "  ");
    return os.str();
}

} // namespace pudu
