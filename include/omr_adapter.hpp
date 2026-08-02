#ifndef PUDU_OMR_ADAPTER_HPP
#define PUDU_OMR_ADAPTER_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段1 OMR 黑盒集成 · 适配层 (omr_adapter)
//
// 职责（零模型改动）：把"外部 OMR 引擎产出的 MusicXML"接进既有
//   MusicXMLParser -> staffToJianpu 流水线。OMR 引擎对 Pudu 是黑盒，
//   Pudu 只消费其产出的 MusicXML 文件。
//
// 设计要点：
//   - runOmr() 按 OmrEngineConfig.engine 分派：
//       * "fixture"  : C++ 原生，写出内嵌样例 MusicXML（确定性、零外部依赖），
//                       用于 ctest 与 CLI 即时演示，证明全链路契约正确。
//       * "oemer"    : 子进程调用 tools/omr_oemer.py（真引擎，待用户环境实跑）。
//       * "audiveris": 子进程调用 `java -jar <jar>`（Java 应用，本沙箱无 JRE）。
//   - 子进程统一用 Windows CreateProcess + 超时 + stdout/stderr 捕获，
//     命令模板含 {input}/{output} 占位，与具体引擎解耦。
//   - 不修改任何既有数据模型（Score / JianpuDoc / MusicXMLParser）。
// ----------------------------------------------------------------------

#include <string>

namespace pudu {

// OMR 引擎配置（适配层契约）
struct OmrEngineConfig {
    std::string engine = "oemer";   // "oemer" | "audiveris" | "fixture"
    std::string python = "python";  // 子进程解释器（oemer / fixture 脚本）
    bool pythonExplicit = false;    // 用户是否通过 --omr-python 显式指定了解释器
    std::string audiverisJar;       // audiveris 预设的 jar 路径（engine=="audiveris" 时使用）
    std::string toolsDir;           // omr_oemer.py / omr_fixture.py 所在目录（CMake 注入 PUDU_TOOLS_DIR）
    int timeoutMs = 120000;         // 子进程超时（毫秒）
    // P0-2：oemer 前置图像增强（默认关）。true 时 runOmr 改调 tools/omr_pipeline.py，
    //       该脚本是 omr_oemer.py 的透明代理；false 时命令串与 P0-2 之前逐字节一致。
    bool preprocess = false;
};

// 解析可用于 oemer 的 python 解释器（自动选址）：
//   1) 显式指定（--omr-python）直接采用；
//   2) 环境变量 PUDU_OMR_PYTHON；
//   3) PATH 上的 python；
//   4) 由 USERPROFILE 推导的托管 venv（managed runtime 约定 envs/default）。
// 返回第一个能 import oemer 的解释器路径；都不行则兜底返回 cfg.python。
std::string resolveOmerPython(const OmrEngineConfig& cfg);

// 运行 OMR：把 input(图片/PDF) 识别为 MusicXML，写到 outMusicXml。
// 成功返回 true；失败 err 含诊断。fixture 引擎为 C++ 原生写内嵌样例。
bool runOmr(const std::string& input,
            const std::string& outMusicXml,
            const OmrEngineConfig& cfg,
            std::string& err);

// 检测指定引擎是否可用（可启动并产出）。
//   fixture  : 恒 true（C++ 原生）。
//   oemer    : 测 `python -c "import oemer"` 退出码 0。
//   audiveris: 测 java 可用且 audiverisJar 存在。
// detail 返回可读说明；不可用返回 false。
bool isOmrEngineAvailable(const OmrEngineConfig& cfg, std::string& detail);

} // namespace pudu

#endif // PUDU_OMR_ADAPTER_HPP
