#include <iostream>
#include <pugixml.hpp>

// ----------------------------------------------------------------------
// 用 pugixml 生成一个最小 MusicXML（score-partwise：单声部、一个小节、一个中央 C 全音符）
// 这就是谱渡（Pudu）识别流水线最终要"写出"的中间格式雏形。
// ----------------------------------------------------------------------
static bool writeMinimalMusicXML(const char* path)
{
    pugi::xml_document doc;

    // XML 声明
    auto decl = doc.append_child(pugi::node_declaration);
    decl.append_attribute("version") = "1.0";
    decl.append_attribute("encoding") = "UTF-8";

    // <score-partwise>
    auto score = doc.append_child("score-partwise");
    score.append_attribute("version") = "4.0";

    // <part-list><score-part id="P1"><part-name>Music</part-name>
    auto partList = score.append_child("part-list");
    auto scorePart = partList.append_child("score-part");
    scorePart.append_attribute("id") = "P1";
    scorePart.append_child("part-name").text() = "Music";

    // <part id="P1"><measure number="1">
    auto part = score.append_child("part");
    part.append_attribute("id") = "P1";
    auto measure = part.append_child("measure");
    measure.append_attribute("number") = "1";

    // <attributes>：divisions / key / time / clef（C 大调 4/4 高音谱号）
    auto attributes = measure.append_child("attributes");
    attributes.append_child("divisions").text() = "1";
    auto key = attributes.append_child("key");
    key.append_child("fifths").text() = "0";           // 0 个升降号 = C 大调
    auto time = attributes.append_child("time");
    time.append_child("beats").text() = "4";
    time.append_child("beat-type").text() = "4";
    auto clef = attributes.append_child("clef");
    clef.append_child("sign").text() = "G";
    clef.append_child("line").text() = "2";

    // <note>：中央 C 全音符
    auto note = measure.append_child("note");
    auto pitch = note.append_child("pitch");
    pitch.append_child("step").text() = "C";
    pitch.append_child("octave").text() = "4";
    note.append_child("duration").text() = "4";
    note.append_child("type").text() = "whole";

    return doc.save_file(path, "  ");
}

// ----------------------------------------------------------------------
// 用 pugixml 读回刚写的 MusicXML，取出第一个音符的音高，验证读取链路
// ----------------------------------------------------------------------
static bool readBackMusicXML(const char* path)
{
    pugi::xml_document doc;
    pugi::xml_parse_result result = doc.load_file(path);
    if (!result) {
        std::cerr << "Failed to parse " << path << ": " << result.description() << std::endl;
        return false;
    }

    auto note = doc.child("score-partwise").child("part").child("measure").child("note");
    auto pitch = note.child("pitch");
    std::string step = pitch.child("step").text().as_string();
    std::string octave = pitch.child("octave").text().as_string();
    std::string type = note.child("type").text().as_string();

    std::cout << "Read back first note: pitch=" << step << octave
              << ", type=" << type << std::endl;

    // MVP 断言：应为 C4 whole
    return (step == "C" && octave == "4" && type == "whole");
}

int main(int argc, char* argv[])
{
    std::cout << "=== 谱渡 Pudu · Stage 0 ===" << std::endl;

    // ------------------------------------------------------------------
    // 1. OpenCV 部分暂未启用（MVP 阶段先不编译 OpenCV，待网络稳定后用
    //    opencv.org 预编译包接入；届时取消 main.cpp 与 CMakeLists.txt 的注释）
    // ------------------------------------------------------------------
    if (argc > 1) {
        std::cout << "Image path argument ignored for now: " << argv[1] << std::endl;
    }

    // ------------------------------------------------------------------
    // 2. pugixml 读写 MusicXML 验证（写 -> 读回 -> 断言）
    // ------------------------------------------------------------------
    const char* xmlPath = "build/minimal.musicxml";
    if (writeMinimalMusicXML(xmlPath)) {
        std::cout << "Wrote minimal MusicXML to " << xmlPath << std::endl;
        if (readBackMusicXML(xmlPath)) {
            std::cout << "MusicXML round-trip OK (C4 whole note verified)." << std::endl;
        } else {
            std::cerr << "MusicXML round-trip assertion FAILED." << std::endl;
            return 1;
        }
    } else {
        std::cerr << "Failed to write MusicXML to " << xmlPath << std::endl;
        return 1;
    }

    std::cout << "=== Stage 0 environment check passed ===" << std::endl;
    return 0;
}
