# M2 阶段1 OMR 黑盒集成 · 增量 PRD

> 作者：主理人齐活林（Lead-direct 接管，因 software-product-manager 子代理在当前会话不可用）
> 日期：2026-07-16
> 关联：阶段0/2/3/G4/M1.5 已完成；本 PRD 仅描述在既有内核之上**增量扩展适配层**，不改动任何数据模型。

> **实施状态（2026-07-17）**：M2-1/2/3 已全部完成——`omr_adapter` 黑盒集成 + oemer/fixture 引擎 + CLI `--from-omr` 已落地，ctest 117/117 全绿；**真实 oemer 已在本机端到端跑通**（权重手动放置 + CUDA/cuDNN PATH 注入启用 GPU）。后续已追加评测 harness（P0-1）、Plan A 调号后处理、H2 分维指标；下一优化方向为 F3 几何校正器。见 `docs/m2-real-run-guide.md` 与 `data/omr_eval/README.md`。

## 1. 产品目标
黑盒接入 OMR（光学乐谱识别）：用户丢一个 PDF / 图片乐谱进 `--from-omr`，工具经子进程调用 OMR 引擎识别出 MusicXML，再喂入既有 `MusicXMLParser → staffToJianpu` 流水线，端到端产出简谱。OMR 引擎对 Pudu 是**黑盒**——Pudu 只消费其产出的 MusicXML。

## 2. 用户故事
- 作为用户，我执行 `Pudu --from-omr score.pdf --to-jianpu`，工具自动识别并输出简谱。
- 作为测试者，我跑 `ctest` 即验证「OMR 产出 → 解析 → 简谱」全链路（确定性，不依赖重引擎）。
- 作为维护者，我换 OMR 引擎只需改配置（`--omr-engine` / 命令模板），不动 C++ 内核。

## 3. 环境可行性（实测结论）
| 引擎 | 结论 | 依据 |
|---|---|---|
| **Audiveris** | ❌ 不可用 | 沙箱 `java: command not found`，无 JRE；Audiveris 为 Java 应用 |
| **oemer** | ✅ 可安装 | `pip install oemer`（清华镜像，39MB/s）解析成功：oemer-0.1.8 + onnxruntime-gpu(213MB) + opencv/scipy/sklearn |
| 网络 | ⚠️ 分裂 | PyPI(清华镜像)通且快；**GitHub 不可达**（schannel 吊销检查失败）→ oemer 运行时若从 GitHub 下权重将失败 |
| 输入素材 | ⚠️ 缺 | 沙箱仅有 MusicXML，**无乐谱图片/PDF** 可喂真 OMR |

**推论**：真引擎实跑在本沙箱受三重限制（无 JRE / GitHub 权重不可达 / 无输入图片），无法在此完整验证 M2-1 的"真引擎产出"。因此架构必须**与具体引擎解耦**，并提供确定性 fixture 引擎兜底。

## 4. 引擎选型决策
- **Audiveris 出局**（无 Java）。
- **oemer 为唯一可行真引擎**：适配器默认目标引擎；其运行器 `tools/omr_oemer.py` 已就绪，待用户环境具备（oemer 权重 + 一个乐谱图片）即可实跑。
- **fixture 引擎（C++ 原生，确定性）**：适配器内置，写出内嵌样例 MusicXML，**不依赖任何外部进程/网络**。用于 ctest 与 CLI 即时演示，证明全链路契约正确。

## 5. 需求池（优先级 + 零模型改动边界）
### P0
- `omr_adapter` 模块（新文件，不碰 `score_model`/`jianpu_model`/`musicxml_parser`）
  - `runOmr(input, outMusicXml, cfg, err)`：按 `cfg.engine` 分派；`fixture` 走 C++ 原生写内嵌样例；`oemer`/`audiveris` 走 `CreateProcess` 子进程调用命令模板。
  - `isOmrEngineAvailable(cfg, detail)`：检测引擎是否可启动（oemer→`python -c import oemer`；fixture→恒 true）。
  - 子进程调用：Windows `CreateProcess` + 超时 + stdout/stderr 捕获；命令模板含 `{input}`/`{output}` 占位。
- CLI：`--from-omr <pdf|image>` + `--omr-engine <oemer|audiveris|fixture>`（默认 `oemer`）；OMR 分支把产出 MusicXML 喂给既有 `MusicXMLParser`，再接 `--to-jianpu`/`--to-jianpu-json`/`--to-musicxml`/默认打印。
- M2-1：引擎可用性检查（`isOmrEngineAvailable` + 真引擎实跑留待用户环境）。
- M2-2：`tools/omr_validate.py` 用 music21 对产出 MusicXML 做结构/语义校验（解析成功、含 part/measure/note、调号拍号存在）。
- M2-3：新增 ctest 集成用例 `test_omr_adapter.cpp`，经 fixture 引擎跑通「OMR 产出 → MusicXMLParser → staffToJianpu → 断言简谱结果」全链路。

### P1
- 错误兜底：引擎未安装时清晰报错（非崩溃）；子进程超时处理（M2-1 不挂死）；非乐谱输入优雅失败。
- `tools/omr_fixture.py`：subprocess 版 fixture（复制 `tools/omr_fixture_sample.musicxml`），供手动验证子进程路径。

### P2（后续）
- 多页 PDF / 多声部 OMR 输出处理；输出质量评估；真 oemer 在用户环境实跑回归。

## 6. 适配层契约（接口草稿）
```cpp
namespace pudu {
struct OmrEngineConfig {
    std::string engine = "oemer";   // "oemer" | "audiveris" | "fixture"
    std::string python = "python";  // 子进程解释器（oemer/fixture 脚本）
    std::string audiverisJar;       // audiveris 预设的 jar 路径
    std::string toolsDir;           // omr_oemer.py / omr_fixture.py 所在目录（CMake 注入）
    int timeoutMs = 120000;
};
bool runOmr(const std::string& input, const std::string& outMusicXml,
            const OmrEngineConfig& cfg, std::string& err);
bool isOmrEngineAvailable(const OmrEngineConfig& cfg, std::string& detail);
}
```
- 子进程命令模板（oemer）：`"{python}" "{toolsDir}/omr_oemer.py" "{input}" "{output}"`
- subprocess fixture（演示）：`"{python}" "{toolsDir}/omr_fixture.py" "{input}" "{output}"`
- C++ 原生 fixture：直接写内嵌 `kOmrFixtureMusicXml` 到 `output`（确定性）。

## 7. 验收标准（对应 M2-1/2/3）
- **M2-1 引擎可用性**：`isOmrEngineAvailable` 对 fixture 返回 true；对 oemer 在「oemer 已 pip 安装」时返回 true（本沙箱权重/图片缺，真引擎实跑留待用户环境，适配器与契约已就绪）。
- **M2-2 music21 校验**：`tools/omr_validate.py <musicxml>` 退出码 0，报告 parts/measures/notes 数且调号拍号存在。
- **M2-3 全链路 ctest**：`runOmr(fixture)` 成功 → `MusicXMLParser::loadFromFile` 成功 → `staffToJianpu` 产出非空 `JianpuDoc` 且首音为 `1`(C 大调 do)、音符数==7。确定性、不依赖外部进程。

## 8. 风险与待确认（R1..R4）
- **R1（环境）**：本沙箱无法实跑真 OMR（无 JRE / GitHub 权重不可达 / 无图片）。已用 fixture 引擎兜底面，适配器 + 契约 + 全链路已验证；**真引擎路径已在用户本机实跑通过**（权重手动放置 + CUDA/cuDNN PATH 注入启用 GPU）。
- **R2（质量）**：oemer 输出 MusicXML 质量参差，可能触发既有解析器边界——属后续 P2 硬化，不在本阶段。
- **R3（零模型改动）**：本阶段只新增 `omr_adapter` 模块与 CLI 分支，**不修改** `Score`/`JianpuDoc`/`MusicXMLParser` 等既有模型，硬约束。
- **R4（默认引擎）**：CLI 默认 `oemer`（真目标）；沙箱演示/ctest 用 `--omr-engine fixture`。若希望开箱即用默认 fixture，可改默认——待用户拍板（本 PRD 维持默认 oemer，符合"真集成"意图）。
