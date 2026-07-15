# 谱渡 Pudu · 项目进展全面分析报告

> 生成时间：2026-07-15  
> 分析范围：工作区 `C:\Users\13157\WorkBuddy\omr` 全量文件 + 全部 `.md` 项目文档  
> 方法：源码/头文件/CMake 实测核对 + 文档里程碑比对（research_report / stage0_plan / jianpu_output_spec / 各阶段 overview / groundtruth 报告 / corpus 报告）

---

## 0. 一句话结论

**项目的核心产权层——“五线谱 → 简谱”转换（阶段 2）已实质完成并通过 music21 跨语言 100% 校验**，MVP 第一可运行版目标已达成。但完整的 5 阶段系统里，输入摄取（PDF/JPG）、OMR 识别黑盒（阶段 1）、反向转换（阶段 3）、AI（阶段 4）、GUI 工程化（阶段 5）**全部尚未开始**。当前最明确的“进行中”事项是：阶段 2 成果尚未提交 git、若干后置边界（小调“6=X”、和弦逐音八度点、连音弧美化）未做。

---

## 1. 项目背景与里程碑规划

谱渡 Pudu 是一个“五线谱 ⇄ 简谱互转工具”，采用 **混合架构 = 成熟 OMR 引擎(识别黑盒) + 自写 C++ 转换层(MusicXML⇄简谱)**。调研文档 `omr-tool-research/results/research_report.md` 规划了 6 个阶段（总估时 16–23 周）：

| 阶段 | 目标 | 工期 | 文档中最新状态(2026-07-13) |
|---|---|---|---|
| 阶段 0 | 环境与 MusicXML 基础 | 1–2 周 | 环境地基完成，MusicXML 解析进行中，OpenCV 基础延后 |
| 阶段 1 | OMR 黑盒集成（Audiveris/oemer） | 2–3 周 | 未开始 |
| 阶段 2 | 五线谱→简谱核心（MVP v1） | 3–4 周 | 未开始 |
| 阶段 3 | 简谱→五线谱（反向） | 2–3 周 | 未开始 |
| 阶段 4 | AI / 深度学习进阶 | 4–8 周 | 未开始 |
| 阶段 5 | 工程化与作品集（GUI/打包） | 2–3 周 | 未开始 |

> ⚠️ 注意：文档的“最新状态”快照停留在 **2026-07-13**，而实测代码已推进到 **2026-07-15**——阶段 2 实际已完成（详见第 2 节）。**规划文档落后于实际进度约 2 天**，这是本报告最重要的修正之一。

---

## 2. ✅ 已完成（Done）

### 2.1 阶段 0 环境地基
- **S1 开发环境**：MSVC 2022 / CMake / Git / vcpkg 全部装好并验证。
- **S2 工具链打通**：pugixml + CMakePresets + vcpkg 端到端跑通（实测 `=== Stage 0 environment check passed ===`）。
- **S3 版本控制**：git 已初始化，当前分支 `feat/musicxml-basics`，已有 **6 次提交**（含 `feat(musicxml): add score model`、`fix(parser): 支持 .mxl`、`feat(parser): 补充 credit 抬头` 等）。
- 编码规范落地：`* text=auto eol=lf` + 源码 `/utf-8`（消除 C4819）；`encoding_report.md` 确认全部文本文件已是 UTF-8 无 BOM。

### 2.2 MusicXML 解析层（模块③ 输入侧）
- **Score 内存模型**（`include/score_model.hpp`）：Pitch / Note / Measure / Part / Score / ScoreAttributes / Credit 完整定义，含 `midiNumber()` 换算。
- **pugixml 解析器**（`src/musicxml_parser.cpp`）：解析 `score-partwise → part → measure → note`，读取 pitch/alter/octave/duration/type/dot/tie/divisions/key/fifths/mode/time/clef。
- **字段提取验证**：`verify_corpus.py` 对 8 份样本 **80/80 检查项 PASS、0 FAIL、8 文件退出码 0**（覆盖升/降号调、C 大调、高低音谱号、多种 divisions/拍号）。
- **阶段 2 前置缺陷已全部修复**（corpus 报告 §5）：
  - 缺陷 A 标题漏读 `<credit>` → 已修复（`Score::pickTitle` 按 `defaultY` 优选主标题，commit `dd10561`）。
  - 缺陷 B 和弦拍平 → `Note.chordPitches` 归并，和弦不再被当成顺序单音。
  - 缺陷 C `<backup>` 多声部时序错乱 → `Note.onset/voice` + 浮点游标（`qcursor_`），多声部按 onset 对齐（partita 392 处已还原）。
  - 缺陷 D 装饰音 → `Note.isGrace`，不推进时间轴。
- **额外能力**：`.mxl` 压缩包预检与友好报错、UTF-8 路径支持。

### 2.3 阶段 2 五线谱→简谱转换（核心产权，MVP v1）
- **L0 权威模型**（`include/jianpu_model.hpp`）：JianpuDoc / JianpuLine / JianpuMeasure / JianpuNote + `Accidental` 枚举，严格匹配 `jianpu_output_spec.md` §1。
- **核心纯函数**（`jianpu_converter.hpp/cpp`）：`fifthsToTonicPc` / `fifthsToTonicName` / `midiToJianpu` / `midiToDegree` / `typeToDuration`——覆盖调号映射、首调音级、临时记号择优、八度点、时值反推。
- **主转换 `staffToJianpu`**：调号抬头、音高映射、八度点、时值（增/减时线+附点）、多声部分行（按 voice）、休止/和弦/装饰音/延音线，对 Score 只读不回改。
- **三层渲染器均已完成**：
  - **L1 纯文本** `jianpuToL1`（命令行核对用）。
  - **L2 HTML/Unicode 二维** `jianpuToL2`：数字 span、上下八度点、减时线横向连写 beam、增时线、附点、和弦 flex 列、连音弧 SVG，自包含 HTML。已生成 `jianpu_l2_cello.html`（283 beam 组/2 和弦/26 增时线）、`jianpu_l2_sample.html`。
  - **L3 JSON** `jianpuToJson`（无损，供校验器逐音比对）。
- **CLI 开关**：`--to-jianpu` / `--to-jianpu-l2 [out.html]` / `--to-jianpu-json [out.json]` 均接入 `main.cpp`。

### 2.4 单元测试
- 自研 header-only 框架 `test/pudu_test.hpp`（零外部依赖，符合“最小依赖”哲学）。
- 4 个测试文件覆盖规范 §5 九项边界用例 + 每函数正/错/错误处理：
  `test_tonic` / `test_pitch_mapping` / `test_duration` / `test_staff_to_jianpu`。
- **据文档记录：C++ 单测 54/54 全绿**（演进：42→46→51→54，随 L2/选项B/选项A 递增）；`build/PuduTests.exe` 已于今日 14:52 构建成功。

### 2.5 Ground-Truth 校验（质量保险）
- `verify_jianpu_groundtruth.py` 用 **music21 独立推导**与 C++ 输出做跨语言交叉验证。
- **结果（选项 A/B/C 后）**：8/8 样本成功解析；音符级 **100.0%（13492/13492）**；字段级 **100.0%（79240/79240）**；**计入类差异 = 0**。
- 边界覆盖：变调 4 文件 / 休止 541 / 和弦 230 / 装饰音 36 / 连音组 821。
- 三项优化均已闭环：
  - **选项 A** 连音组：解析 `<time-modification>`，`Note.tupletActual/tupletNormal`，`tuplet` 进入计入校验，连音段基准节奏由 `quarterLength×actual/normal` 反推（正确暴露并修复 caprice 7:4 误标）。
  - **选项 B** 节奏：改用实际 `Note.quarterLength`（`=duration/divisions`）反推，与 music21 同口径。
  - **选项 C** 同 onset 配对：校验器 `_event_key` 改为与 `_note_key` 同构 4 元组，消除 partita m178 的 4 处假阳性（纯校验器侧改动）。

---

## 3. 🔶 进行中 / 待收尾（In Progress / Pending）

| 事项 | 状态说明 |
|---|---|
| **阶段 2 成果 git 提交** | 当前 `git status`：5 文件 modified（CMakeLists/score_model.hpp/musicxml_parser.hpp/main.cpp/musicxml_parser.cpp）+ 6 文件 untracked（jianpu_converter.hpp/jianpu_model.hpp/两个 L2 html/jianpu_l2_overview.md/jianpu_sample.json）。**阶段 2 全部代码尚未提交**，无 `v0.x` 标签。这是最紧迫的收尾项。 |
| **小调“6=X”标法开关** | 规范 §2.4 明确后置；当前小调统一走“首调相对法”（1 = 关系大调主音）。 |
| **和弦逐音八度点** | `JianpuNote.chordDegrees` 仅存音级，成员音独立八度点（规范 §2.5）未实现。 |
| **L2 连音弧美化** | 当前为单音上方 SVG 弧近似，未跨两音精确连线。 |
| **L2 减时线连写** | 按“连续同值”启发式近似，未按真实 beat 分组（如 4/4 跨拍八分未拆分）。 |
| **变调段（已知限制 D）** | 4 个文件检测到调号变化，转换器取初始调号，变调段不重算首调（已检测并提示，未实现）。 |
| **极端连音比（46 处）** | 7:8/7:4/9:4 等无法映射标准时值的音符列为 `rhythm_unresolvable`、单列未校验（不计入分母）。 |
| **阶段 0 收尾 S8/S10** | README 整合更新、打 `v0.1-stage0` 标签未做；S9（music21 扩展验证）已由阶段 2 校验器实质覆盖。 |
| **文件夹重命名 omr→Pudu** | 文档已定名，但活动工作区被宿主锁定，重命名待关闭工作区后手动执行。 |

---

## 4. ⬜ 未开始（Not Started）

### 4.1 阶段 1 — OMR 黑盒集成
- **从未开始**。当前“输入”仍是由用户提供的 `data/*.musicxml`（8 份），PDF/JPG → MusicXML 的识别链路完全未做。
- 子进程调用 Audiveris / oemer 黑盒、`system("audiveris -batch ...")` 接口未实现。

### 4.2 阶段 3 — 简谱→五线谱（反向）
- **确认未开始**：全仓检索 `jianpuToStaff` 结果为 **`NONE FOUND`**。`jianpu_converter.hpp` 仅有 `staffToJianpu / jianpuToL1 / jianpuToL2 / jianpuToJson`，无反向函数。
- 模块⑤的“MusicXML 导出”因此也未实现（仅 L3 JSON 投影，无 `Score→MusicXML` 序列化）。

### 4.3 阶段 4 — AI / 深度学习
- 完全未开始：PyTorch 训练、ONNX Runtime 部署、合成数据微调、评测脚本均无。

### 4.4 阶段 5 — 工程化与作品集
- 完全未开始：Qt/ImGui GUI、PDF 输入面板、纠错编辑器、打包分发均未做。

### 4.5 OpenCV 基础（S4–S5）
- 架构决策已将其降级为“选做/练兵”，自 `opencv.org` 预编译包接入也**未做**（实际项目未启用 OpenCV，`CMakeLists.txt` 中 `find_package(OpenCV)` 仍被注释）。

### 4.6 文档/维护滞后项
- **README 严重过时**：仍停留在“阶段 0 计划”视角，列出未勾选的“OpenCV 二值化”“pugixml roundtrip”“vcpkg 尚未安装”等目标；项目结构图未含 `include/jianpu_*`、`src/jianpu_converter.cpp`、`test/`；路径名仍是 `Pudu`/`Pudu-research`（实际为 `omr`/`omr-tool-research`）。
- 阶段 2 各 overview 文档间**测试数口径未同步**（42/42 → 46/46 → 51/51 → 54/54 演进，部分文档仍写旧值）。

---

## 5. 里程碑对比与完成度评估

### 5.1 阶段级完成度

| 阶段 | 规划目标 | 实际状态 | 完成度 |
|---|---|---|---|
| 阶段 0 | 环境 + MusicXML 基础 | 环境/S3 完成；MusicXML 解析完成；OpenCV 延后；S8/S10 收尾未做 | **~95%** |
| 阶段 1 | OMR 黑盒集成 | 未开始（仍依赖人工提供 MusicXML） | **0%** |
| 阶段 2 | 五线→简谱（MVP v1） | 核心+三层渲染+单测+100% 校验全部完成；仅后置边界与 git 提交待办 | **~95%** |
| 阶段 3 | 简谱→五线 | 未开始（无 jianpuToStaff） | **0%** |
| 阶段 4 | AI/DL | 未开始 | **0%** |
| 阶段 5 | GUI/工程化 | 未开始 | **0%** |

### 5.2 两种口径的整体完成度

- **核心 MVP 目标口径（推荐）**：  
  项目的“第一可运行版”= 阶段 2 产出（给定 MusicXML → 准确首调简谱文本/HTML/JSON）。该目标**已基本达成**（≈95%，差 git 提交与个别边缘美化）。这是项目真正的差异化产权，已完成且经独立算法 100% 验证。

- **全系统 5 阶段口径**：  
  按工期权重粗略估算，已完成 ≈ 阶段 0（~1.5 周）+ 阶段 2（~3.8 周）≈ 5.3 周 / 总 16–23 周 ≈ **25–30%**。即“转换大脑”做好了，但“眼睛”（输入/识别）和“手脚”（反向/界面/AI）还没接上。

### 5.3 模块级对照（research_report §2.1）

| 模块 | 职责 | 状态 |
|---|---|---|
| ① 输入解析 | PDF/JPG→图像 | 未开始 |
| ② 乐谱识别 OMR | 图像→MusicXML | 未开始（依赖人工 MusicXML） |
| ③ MusicXML I/O | 解析/生成 | 解析 ✅；生成（→MusicXML 序列化）❌ |
| ④ 格式转换 | 五线⇄简谱 | 正向 ✅；反向 ❌ |
| ⑤ 输出/渲染 | 简谱文本/HTML + MusicXML + GUI | 简谱文本/HTML ✅；MusicXML 导出 ❌；GUI ❌ |

---

## 6. 发现的关键文档/实现落差（需修正）

1. **工作记忆称“Git 仓库尚未初始化（S3 待办）”** —— **不实**。实测 git 已初始化、有 6 次提交，且阶段 2 代码已产生未提交改动。记忆需更新。
2. **README 过时最严重**：规划文档停在阶段 0，与实际（阶段 2 完成）相差一个完整阶段；路径名、结构图、目标清单均需刷新。
3. **规划文档（research_report/stage0_plan）状态快照停在 2026-07-13**，落后于 2026-07-15 的实际（阶段 2 已完成）。
4. **单测数文案不一致**：各 overview 写 42/46/51，最新为 54/54（选项 A 后）；建议在阶段 2 收尾提交时统一。
5. **阶段 2 成果尚未 git 提交**：存在 5 modified + 6 untracked，未打标签。

---

## 7. 风险与下一步建议（按优先级）

**P0（当前卡点）**
- 提交阶段 2 全部成果到 `feat/musicxml-basics` 并 squash 合并 `main`，打 `v0.2-stage2` 标签；统一各文档单测数与路径名。
- 刷新 README：反映阶段 2 文件结构、`omr`→`Pudu` 重命名说明、现行构建/运行命令。

**P1（边界补全，提升健壮性）**
- 变调段重算首调（已知限制 D，影响 4 份样本）；小调“6=X”开关；和弦逐音八度点。

**P2（系统扩展，决定项目能否“端到端可用”）**
- 阶段 1：接入 Audiveris/oemer 子进程，打通 PDF/JPG → MusicXML 输入链路（这是 MVP 真正“可演示”的前提）。
- 阶段 3：`jianpuToStaff` 反向转换 + `Score→MusicXML` 序列化，完成双向闭环与 round-trip 自测。

**P3（进阶/作品集）**
- 阶段 4 AI 识别替换；阶段 5 Qt/ImGui GUI + 打包。

---

## 附：实证依据清单（已逐一核对）

- 源码：`include/score_model.hpp`、`include/jianpu_model.hpp`、`include/jianpu_converter.hpp`、`src/main.cpp`、`src/musicxml_parser.cpp`、`CMakeLists.txt`
- 测试：`test/pudu_test*.{hpp,cpp}` × 4（现存）
- 校验器：`omr-tool-research/verify_jianpu_groundtruth.py`、`verify_corpus.py`（现存）
- 产物：`build/Pudu.exe`、`build/PuduTests.exe`（2026-07-15 14:52 构建）、`jianpu_l2_cello.html`、`jianpu_l2_sample.html`、`jianpu_sample.json`
- 文档：`README.md`、`jianpu_stage2_overview.md`、`jianpu_stage2_tests_overview.md`、`jianpu_l2_overview.md`、`omr-tool-research/{stage0_plan,jianpu_output_spec,musicxml_mvp_tags,jianpu_groundtruth_overview,jianpu_groundtruth_report,results/research_report,results/corpus_test_report}.md`
- git：`feat/musicxml-basics` 分支，6 次提交，当前有未提交改动
