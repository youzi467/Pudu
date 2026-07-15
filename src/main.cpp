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
#include <windows.h>
#include <string>
#include <fstream>
#include <climits>

#include "musicxml_parser.hpp"
#include "score_model.hpp"
#include "jianpu_converter.hpp"   // 阶段 2：简谱转换（staffToJianpu / jianpuToL1）
#include "transpose.hpp"          // 阶段 2 边界：变调重算
#include "jianpu_to_staff.hpp"    // 阶段 3：简谱 -> 五线谱（jianpuToStaff / scoreToMusicXML）

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
    SetConsoleOutputCP(65001); // 设置控制台输出代码页为 UTF-8，消除中文乱码
    std::cout << "=== 谱渡 Pudu · MusicXML 解析骨架 ===" << std::endl;

    std::string path = (argc > 1) ? argv[1] : "data/sample_c_major.musicxml";

    // 调试模式：打印每个音符的 onset/voice，用于验证时间轴与声部字段
    bool debugMode = false;
    if (argc > 2 && std::string(argv[argc - 1]) == "--debug")
        debugMode = true;

    // 变调重算请求（阶段 2 边界）：--key <名>(移调) / --rekey <名>(改写调号)
    //   / --transpose <±半音>(字面移调)。三者互斥，重复以最后一次为准。
    bool hasTranspose = false;
    pudu::TransposeMode tMode = pudu::TransposeMode::Transpose;
    pudu::TransposeTarget tTarget;
    std::string tErr;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if ((a == "--key" || a == "--rekey") && i + 1 < argc) {
            try {
                auto [f, m] = pudu::parseKeyName(argv[i + 1], "major");
                tTarget = {f, m, INT_MIN};
                tMode = (a == "--rekey") ? pudu::TransposeMode::Rekey
                                         : pudu::TransposeMode::Transpose;
                hasTranspose = true;
            } catch (const std::exception& e) { tErr = e.what(); }
            ++i;
        } else if (a == "--transpose" && i + 1 < argc) {
            try {
                int semis = std::stoi(argv[i + 1]);
                tTarget = {pudu::semitonesToFifths(semis), "major", semis};
                tMode = pudu::TransposeMode::Transpose;
                hasTranspose = true;
            } catch (const std::exception& e) { tErr = e.what(); }
            ++i;
        }
    }
    if (!tErr.empty()) {
        std::cerr << "[错误] 变调参数：" << tErr << std::endl;
        return 1;
    }

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

    // 统一构建简谱文档：若请求变调则先变调再投影（不就地修改 score）。
    auto buildDoc = [&]() -> pudu::JianpuDoc {
        if (hasTranspose)
            return pudu::transposeStaffToJianpu(score, tTarget, tMode);
        return pudu::staffToJianpu(score);
    };

    // 阶段 2：简谱转换预览（L1 纯文本）。命中即输出简谱并退出，不打印五线谱明细。
    bool toJianpu = false;
    for (int i = 1; i < argc; ++i)
        if (std::string(argv[i]) == "--to-jianpu") { toJianpu = true; break; }
    if (toJianpu) {
        if (hasTranspose)
            std::cout << "[变调] " << (tMode == pudu::TransposeMode::Rekey ? "改写调号" : "移调")
                      << " -> 1=" << pudu::fifthsToTonicName(tTarget.fifths, tTarget.mode) << std::endl;
        pudu::JianpuDoc doc = buildDoc();
        std::cout << "\n=== 简谱预览 (L1) ===" << std::endl;
        std::cout << pudu::jianpuToL1(doc) << std::endl;
        return 0;
    }

    // 阶段 2：简谱 L2 二维渲染（HTML/Unicode），写出为自包含 .html
    bool toJianpuL2 = false;
    std::string l2OutPath = "jianpu_l2.html";
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--to-jianpu-l2") {
            toJianpuL2 = true;
            // 紧邻的非选项参数视为输出路径
            if (i + 1 < argc && std::string(argv[i + 1]).find('-') != 0)
                l2OutPath = argv[i + 1];
            break;
        }
    }
    if (toJianpuL2) {
        pudu::JianpuDoc doc = buildDoc();
        std::string html = pudu::jianpuToL2(doc);
        std::ofstream f(l2OutPath, std::ios::binary);
        if (!f) {
            std::cerr << "[错误] 无法写入文件: " << l2OutPath << std::endl;
            return 1;
        }
        f << html;
        std::cout << "\n=== 简谱 L2 (HTML) 已写出: " << l2OutPath << " ===" << std::endl;
        std::cout << "用浏览器打开即可查看二维简谱。" << std::endl;
        return 0;
    }

    // 阶段 2：简谱 L3 结构化 JSON 输出（无损，供 verify_jianpu_groundtruth.py 校验）
    bool toJianpuJson = false;
    std::string jsonOutPath = "jianpu.json";
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--to-jianpu-json") {
            toJianpuJson = true;
            if (i + 1 < argc && std::string(argv[i + 1]).find('-') != 0)
                jsonOutPath = argv[i + 1];
            break;
        }
    }
    if (toJianpuJson) {
        pudu::JianpuDoc doc = buildDoc();
        std::string json = pudu::jianpuToJson(doc);
        std::ofstream f(jsonOutPath, std::ios::binary);
        if (!f) {
            std::cerr << "[错误] 无法写入文件: " << jsonOutPath << std::endl;
            return 1;
        }
        f << json;
        std::cout << "\n=== 简谱 L3 (JSON) 已写出: " << jsonOutPath << " ===" << std::endl;
        std::cout << "供 ground-truth 校验器逐音比对。" << std::endl;
        return 0;
    }

    // 阶段 3：简谱 -> 五线谱（反向闭环演示）。
    //   读 MusicXML -> staffToJianpu -> jianpuToStaff -> 写出 .musicxml，
    //   演示"五线 -> 简 -> 五线"双向互转；可叠加 --key/--rekey/--transpose。
    bool toMusicXml = false;
    std::string mxlOutPath = "sample_back.musicxml";
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--to-musicxml") {
            toMusicXml = true;
            if (i + 1 < argc && std::string(argv[i + 1]).find('-') != 0)
                mxlOutPath = argv[i + 1];
            break;
        }
    }
    if (toMusicXml) {
        pudu::JianpuDoc doc = buildDoc();
        pudu::Score back = pudu::jianpuToStaff(doc);
        std::string xml = pudu::scoreToMusicXML(back);
        std::ofstream f(mxlOutPath, std::ios::binary);
        if (!f) {
            std::cerr << "[错误] 无法写入文件: " << mxlOutPath << std::endl;
            return 1;
        }
        f << xml;
        std::cout << "\n=== 阶段 3：简谱 -> 五线谱 MusicXML 已写出: " << mxlOutPath << " ===" << std::endl;
        std::cout << "声部数: " << back.parts.size()
                  << " / 调号 fifths=" << back.parts[0].attributes.fifths
                  << " / 拍号 " << back.parts[0].attributes.beats << "/"
                  << back.parts[0].attributes.beatType << std::endl;
        return 0;
    }

    std::cout << "标题: " << (score.title.empty() ? "(无)" : score.title) << std::endl;
    std::cout << "抬头行数(credit): " << score.credits.size() << std::endl;
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
                if (debugMode) {
                    // 调试模式：打印 onset(小节内起始) + voice(声部)，
                    // 用于核对时间轴与多声部字段是否填充正确。
                    std::cout << " [" << (n.isRest ? std::string("R")
                                : pitchLabel(n.pitch))
                              << "@o" << n.onset << "v" << n.voice << "]";
                } else {
                    if (n.isRest) {
                        std::cout << " 0";
                    } else {
                        std::string label = pitchLabel(n.pitch) + "/" + n.type;
                        if (!n.chordPitches.empty()) {
                            // 和弦：主音 + 括号内其余音（⊕ 标记和弦主音）
                            label = "⊕" + label;
                            for (const auto& cp : n.chordPitches)
                                label += "(" + pitchLabel(cp) + ")";
                        }
                        if (n.isGrace) label = "g" + label;  // g=装饰音
                        std::cout << " " << label;
                    }
                }
            }
            std::cout << std::endl;
        }
    }

    // 通用健全性检查（不再写死为某个样例的首音）
    // —— 解析器对任何合法 MusicXML 都应通过，而非只对 小星星 样例有效
    bool ok = true;
    std::string reason;
    if (score.isEmpty()) {
        ok = false; reason = "Score 为空（未解析到任何声部）";
    } else {
        bool hasAnyEvent = false;
        for (const auto& part : score.parts)
            for (const auto& m : part.measures)
                if (!m.notes.empty()) { hasAnyEvent = true; break; }
        if (!hasAnyEvent) { ok = false; reason = "未解析到任何音符/休止"; }
    }

    if (ok) {
        const auto& firstPart = score.parts[0];
        const auto& firstNote = (!firstPart.measures.empty()
            && !firstPart.measures[0].notes.empty())
            ? firstPart.measures[0].notes[0] : pudu::Note{};
        std::string firstLabel = firstNote.isRest ? "休止(全小节)"
            : pitchLabel(firstNote.pitch);
        std::cout << "=== 解析成功: 共 " << score.parts.size() << " 声部 / 首声部 "
                  << firstPart.measures.size() << " 小节 / 首音符 "
                  << firstLabel << " ===" << std::endl;
    } else {
        std::cerr << "=== 断言失败: " << reason << " ===" << std::endl;
        return 1;
    }
    return 0;
}
