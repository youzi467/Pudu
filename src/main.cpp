// ----------------------------------------------------------------------
// 谱渡 Pudu · MusicXML 解析骨架演示
//
// 演示 MusicXMLParser 的基本流程：
//   加载(文件或内嵌样例) -> 遍历关键节点 -> 填充 Score -> 打印 -> 断言首音
//
// 构建：cmake --preset windows-msvc-vcpkg && cmake --build build
// 运行：build/Pudu.exe  [可选: 自定义 .musicxml 路径]
// ----------------------------------------------------------------------

#include <iostream>
#include <string>

#include "musicxml_parser.hpp"
#include "score_model.hpp"

namespace {

// fifths(五度圈步数) -> 调名（MVP 仅覆盖 ≤2 升降号）
std::string keyName(int fifths, const std::string& mode) {
    static const std::string majorPos[] = {"C", "G", "D", "A", "E", "B", "F#", "C#"};
    static const std::string majorNeg[] = {"C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"};
    static const std::string minorPos[] = {"a", "e", "b", "f#", "c#", "g#", "d#", "a#"};
    static const std::string minorNeg[] = {"a", "d", "g", "c", "f", "bb", "eb", "ab"};
    const std::string* table;
    int idx;
    if (mode == "minor") { table = (fifths >= 0) ? minorPos : minorNeg; }
    else                 { table = (fifths >= 0) ? majorPos : majorNeg; }
    idx = (fifths >= 0) ? fifths : -fifths;
    if (idx > 7) idx = 7;
    return std::string(table[idx]) + (mode == "minor" ? " 小调" : " 大调");
}

std::string pitchLabel(const pudu::Pitch& p) {
    if (!p.hasValue) return "rest";
    std::string s(1, p.step);
    if (p.alter == 1)      s += "#";
    else if (p.alter == -1) s += "b";
    s += std::to_string(p.octave);
    return s;
}

// 内嵌样例（文件缺失时回退，保证 demo 始终可运行）
const char* kEmbeddedSample = R"(<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <movement-title>小星星 (内嵌样例)</movement-title>
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths><mode>major</mode></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>)";

} // anonymous namespace

int main(int argc, char* argv[]) {
    std::cout << "=== 谱渡 Pudu · MusicXML 解析骨架 ===" << std::endl;

    std::string path = (argc > 1) ? argv[1] : "data/sample_c_major.musicxml";

    pudu::Score score;
    pudu::MusicXMLParser parser;
    std::string err;

    // 优先从文件加载；失败则回退到内嵌样例
    bool loaded = parser.loadFromFile(path, score, err);
    if (!loaded) {
        std::cerr << "[warn] 文件加载失败 (" << err << ")，改用内嵌样例。" << std::endl;
        if (!parser.parseString(kEmbeddedSample, score, err)) {
            std::cerr << "内嵌样例解析失败: " << err << std::endl;
            return 1;
        }
    }

    std::cout << "标题: " << (score.title.empty() ? "(无)" : score.title) << std::endl;
    std::cout << "声部数: " << score.parts.size() << std::endl;

    for (const auto& part : score.parts) {
        const auto& a = part.attributes;
        std::cout << "声部[" << part.id << "] " << part.name << ": "
                  << keyName(a.fifths, a.mode) << ", "
                  << "拍号 " << a.beats << "/" << a.beatType << ", "
                  << "divisions=" << a.divisions << ", "
                  << "谱号 " << a.clefSign << a.clefLine << std::endl;
        std::cout << "  小节数: " << part.measures.size() << std::endl;

        for (const auto& m : part.measures) {
            std::cout << "    小节 " << m.number << ":";
            for (const auto& n : m.notes) {
                if (n.isRest)
                    std::cout << " 0";
                else
                    std::cout << " " << pitchLabel(n.pitch) << "/" << n.type;
            }
            std::cout << std::endl;
        }
    }

    // MVP 断言：首音应为 C4 quarter
    bool ok = false;
    if (!score.parts.empty() && !score.parts[0].measures.empty()
        && !score.parts[0].measures[0].notes.empty()) {
        const auto& first = score.parts[0].measures[0].notes[0];
        ok = (!first.isRest && first.pitch.step == 'C' && first.pitch.octave == 4
              && first.type == "quarter");
    }
    if (ok)
        std::cout << "=== 解析骨架验证通过 (首音 C4 quarter 断言 OK) ===" << std::endl;
    else {
        std::cerr << "=== 断言失败: 首音非预期的 C4 quarter ===" << std::endl;
        return 1;
    }
    return 0;
}
