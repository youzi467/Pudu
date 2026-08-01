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
#include <sstream>
#include <climits>

#include "musicxml_parser.hpp"
#include "score_model.hpp"
#include "jianpu_converter.hpp"   // 阶段 2：简谱转换（staffToJianpu / jianpuToL1）
#include "transpose.hpp"          // 阶段 2 边界：变调重算
#include "jianpu_to_staff.hpp"    // 阶段 3：简谱 -> 五线谱（jianpuToStaff / scoreToMusicXML）
#include "jianpu_text_parser.hpp" // G4：简谱文本输入解析（L1 文本 -> JianpuDoc）
#include "omr_adapter.hpp"          // 阶段1 OMR 黑盒集成适配层
#include "jianpu_postcorrect.hpp"   // P1-1：后处理音乐规则引擎（确定性自修/标记）

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

    // 阶段1 OMR 黑盒集成：--from-omr <input> [--omr-engine oemer|audiveris|fixture]
    //   经 omr_adapter 调子进程 OMR 引擎产出 MusicXML，再喂入既有解析器流水线。
    //   fixture 引擎为 C++ 原生（确定性、零外部依赖），用于 ctest 与沙箱演示；
    //   oemer 为默认真引擎目标（待用户环境具备 oemer 与乐谱图片时实跑）。
    bool fromOmr = false;
    std::string omrInput;
    std::string omrEngine = "oemer";
    std::string omrPythonPath;
    bool omrPythonExplicit = false;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--from-omr" && i + 1 < argc) {
            fromOmr = true;
            omrInput = argv[i + 1];
            ++i;
        } else if (a == "--omr-engine" && i + 1 < argc) {
            omrEngine = argv[i + 1];
            ++i;
        } else if (a == "--omr-python" && i + 1 < argc) {
            omrPythonExplicit = true;
            omrPythonPath = argv[i + 1];
            ++i;
        }
    }

    std::string path = "data/sample_c_major.musicxml";
    if (fromOmr) {
        pudu::OmrEngineConfig cfg;
        cfg.engine = omrEngine;
        cfg.python = "python";
#ifdef PUDU_TOOLS_DIR
        cfg.toolsDir = PUDU_TOOLS_DIR;
#endif
        if (omrPythonExplicit && !omrPythonPath.empty()) {
            cfg.python = omrPythonPath;
            cfg.pythonExplicit = true;
        }
        if (cfg.engine == "oemer")
            cfg.python = pudu::resolveOmerPython(cfg);
        std::string avail;
        if (!pudu::isOmrEngineAvailable(cfg, avail)) {
            std::cerr << "[错误] OMR 引擎不可用 (" << omrEngine << "): " << avail << std::endl;
            return 1;
        }
        std::string omrOut = omrInput + ".pudu.musicxml";
        std::string oerr;
        if (!pudu::runOmr(omrInput, omrOut, cfg, oerr)) {
            std::cerr << "[错误] OMR 识别失败: " << oerr << std::endl;
            return 1;
        }
        std::cout << "[OMR] 引擎 " << omrEngine << " 产出 MusicXML: " << omrOut << std::endl;
        path = omrOut;
    } else if (argc > 1 && std::string(argv[1]).find('-') != 0) {
        path = argv[1];
    }

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

    // G4：简谱文本输入解析（--from-jianpu-text <path>）+ 自定义 divisions（--divisions N）
    //   --from-jianpu-text：读取简谱文本文件，调 parseJianpuText 得到 JianpuDoc，
    //     供 --to-musicxml 分支使用（与 MusicXML 输入互斥共用同一出口）。
    //   --divisions N：反向生成的 divisions（1..16，默认 4），越界/非数字报错退出。
    //   两项均为新增选项，不改动任何既有分支逻辑。
    bool fromJianpuText = false;
    std::string jianpuTextPath;
    int userDivisions = 4;
    bool hasDivisions = false;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--from-jianpu-text" && i + 1 < argc) {
            fromJianpuText = true;
            jianpuTextPath = argv[i + 1];
            ++i;
        } else if (a == "--divisions" && i + 1 < argc) {
            try {
                int v = std::stoi(argv[i + 1]);
                if (v < 1 || v > 16) {
                    std::cerr << "[错误] --divisions 取值须为 1..16，收到: "
                              << v << std::endl;
                    return 1;
                }
                userDivisions = v;
                hasDivisions = true;
            } catch (const std::exception& e) {
                std::cerr << "[错误] --divisions 参数非法: " << e.what() << std::endl;
                return 1;
            }
            ++i;
        }
    }

    // P1-1：后处理音乐规则引擎开关
    //   --apply-postcorrect        在 staffToJianpu 之后挂一层确定性规则引擎，
    //                              对 OMR 常见错误做"高置信自修 / 低置信标记"。
    //                              默认关闭；不开启时 buildDoc 行为与此前逐字节一致
    //                              （守住"转换 100% 不变"这条红线）。
    //   --postcorrect-report <path>  把审计报告（JSON）写出到指定路径。
    bool applyPostCorrect = false;
    std::string postReportPath;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--apply-postcorrect") {
            applyPostCorrect = true;
        } else if (a == "--postcorrect-report" && i + 1 < argc) {
            postReportPath = argv[i + 1];
            ++i;
        }
    }
    pudu::PostCorrectConfig postCfg;
    postCfg.enabled = applyPostCorrect;
    postCfg.autoFixBeatOverflow = true;   // 节拍对账默认积极自修
    // flagOctaveJumps / enforceKeyConsistency / conservative 取结构体默认值：
    //   非节拍类规则保持保守（仅 trivially-safe 自修，其余仅标记）。

    // 若指定了 --from-jianpu-text，则读取并解析文本文件（失败即报错退出）。
    // 解析结果存入 jianpuTextDoc，供下方 --to-musicxml 分支使用。
    pudu::JianpuDoc jianpuTextDoc;
    if (fromJianpuText) {
        std::ifstream f(jianpuTextPath, std::ios::binary);
        if (!f) {
            std::cerr << "[错误] 无法打开简谱文本文件: " << jianpuTextPath << std::endl;
            return 1;
        }
        std::ostringstream ss;
        ss << f.rdbuf();
        std::string txt = ss.str();
        std::string perr;
        if (!pudu::parseJianpuText(txt, jianpuTextDoc, perr)) {
            std::cerr << "[错误] 简谱文本解析失败: " << perr << std::endl;
            return 1;
        }
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
    //   P1-1：末端可选挂载后处理规则引擎。buildDoc 会被多个输出分支调用，
    //   但每个分支命中后即 return，故实际每次运行只会执行一次；报告采取
    //   "每次调用都写出、末次覆盖"的策略，行为等价且无状态残留。
    auto buildDoc = [&]() -> pudu::JianpuDoc {
        pudu::JianpuDoc d = hasTranspose
            ? pudu::transposeStaffToJianpu(score, tTarget, tMode)
            : pudu::staffToJianpu(score);
        if (applyPostCorrect) {
            pudu::PostCorrectReport r;
            d = pudu::correctJianpuDoc(d, postCfg, r);
            std::cout << "[后处理] 自动修正 " << r.applied.size()
                      << " 处 / 标记 " << r.flagged.size()
                      << " 处 / 对账小节 " << r.measuresReconciled
                      << " / 涉及音符 " << r.notesTouched << std::endl;
            if (!postReportPath.empty()) {
                if (pudu::writePostCorrectReportFile(r, postReportPath))
                    std::cout << "[后处理] 审计报告已写出: " << postReportPath << std::endl;
                else
                    std::cerr << "[警告] 后处理报告写出失败: " << postReportPath << std::endl;
            }
        }
        return d;
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
        // G4：若指定 --from-jianpu-text，则使用解析得到的简谱文档；
        //     否则沿用既有 MusicXML 输入路径（buildDoc）。两者均受 --divisions 控制。
        pudu::JianpuDoc doc = fromJianpuText ? jianpuTextDoc : buildDoc();
        pudu::Score back = pudu::jianpuToStaff(doc, hasDivisions ? userDivisions : 4);
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
