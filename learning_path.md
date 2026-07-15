# 谱渡 Pudu · 从零到掌握 · 渐进式学习路径

> 适用对象：具备 C++ 基础、乐理扎实、希望借本项目转向 AI 方向的学习者（数字媒体技术相关）。
> 目标：把"谱渡 Pudu"本身当教材，按项目 6 阶段，从环境搭建一路学到可交付的作品集。
> 依据：`omr-tool-research/results/research_report.md`（总路线/架构/学习路线）、`stage0_plan.md`、`jianpu_output_spec.md`、本项目源码与 `stage3_action_plan.md`。
> 用法：每个阶段都是"可运行/可展示"的里程碑，完成后再进下一阶段；卡住时先跑测试 + 看校验报告，理解"正确长什么样"。

---

## 0. 总览与时间线

| 阶段 | 主题 | 预估耗时 | 依赖 | 里程碑产出 |
|---|---|---|---|---|
| **L0** | 环境与 MusicXML 基础 | 1–2 周 | 无 | 环境可用；能读 MusicXML 并打印音符序列 |
| **L1** | OMR 黑盒集成（PDF/JPG→MusicXML） | 2–3 周 | L0 | 端到端输入链路：PDF→MusicXML→控制台音高 |
| **L2** | 五线→简谱核心（MVP v1） | 3–4 周 | L0 | 给定 MusicXML 输出准确简谱（文本/HTML/JSON） |
| **L3** | 简谱→五线（反向） | 2–3 周 | L2 | 双向闭环 + round-trip 音高守恒 |
| **L4** | AI / 深度学习进阶 | 4–8 周 | L1、L2、L3 | 自训识别模型 + 评测报告 |
| **L5** | 工程化与作品集 | 2–3 周 | L2、L3（L4 可选） | 可演示 Windows 应用 + GitHub 仓库 + 技术报告 |

- **总估时**：约 **16–23 周**（课余并行，每天 2–3 小时）。
- **依赖关系（DAG）**：`L0 → L1`、`L0 → L2`、`L2 → L3`、`L1 → L4`、`L2/L3 → L4`、`L2/L3 → L5`、`L4 → L5`。
- **关键策略**：先垂直打通 `L0→L2` 最快拿到 MVP 正反馈；`L1/L3/L4/L5` 是在核心上加厚度。本项目当前 **L0 ✅、L2 ✅（已打标签 `phase-2`）、L1/L3/L4/L5 ⬜**，新人可从 L1 或 L3 切入练手。

---

## 1. L0 — 环境与 MusicXML 基础

**核心模块（要掌握）**
- 工具链：Visual Studio Build Tools 2022 / CMake（≥3.25）/ vcpkg（manifest 模式）/ Git（看 `stage0_plan.md` S1–S3）。
- **pugixml** 读写 XML（项目因 `libmusicxml2` 不在 vcpkg 而选它；见 `README.md` 常见问题）。
- **MusicXML 格式**：`score-partwise → part → measure → note` 嵌套；关键标签 `pitch(step/alter/octave)`、`divisions`、`duration`、`type`、`key/fifths`、`time`、`clef`（看 `musicxml_mvp_tags.md`）。
- 编码规范：源码 UTF-8 无 BOM + MSVC `/utf-8`（防 C4819）。

**预估耗时**：1–2 周（课余）。

**实践任务 / 里程碑**
- [ ] 配好 VS2022 + CMake + vcpkg，跑通 pugixml 端到端小程序，打印 `=== Stage 0 environment check passed ===`。
- [ ] 用 pugixml 解析一份示例 MusicXML，打印每个音的 `step/alter/octave/duration/type` 与全局调号 `fifths`。
- [ ] 建立 `Score` 内存模型（`include/score_model.hpp`），用《小星星》样例断言解析正确。
- [ ] 通读官方 MusicXML Tutorial 重点章节（Tutorial PDF 链接见 `stage0_plan.md` S6）。
- **产出**：阶段 0 完成（项目已交付；学习者目标是能独立重建 `MusicXMLParser`）。

---

## 2. L1 — OMR 黑盒集成（项目当前未做）

**核心模块（要掌握）**
- 子进程调用 **Audiveris / oemer** 出 MusicXML（架构见 `research_report.md` §2.3；识别端作为黑盒，不手搓 CV）。
- **music21（Python）** 探索解析已知谱：打印 `pitch/key/measure`，建立对 MusicXML 语义的直觉。
- 语料获取：从 OpenScore / IMSLP 下载 5–10 份 MVP 约束谱（单声部、≤2 升降号、无装饰音/歌词）。

**预估耗时**：2–3 周。

**依赖**：L0（解析层已就绪）。

**实践任务 / 里程碑**
- [ ] 本地装 Audiveris 或 oemer，对一个 PDF 跑出 `.musicxml`。
- [ ] 写 Python 脚本用 music21 读该 MusicXML，打印音高序列与调号，人工核对。
- [ ] 在 C++ 串成流水线：`PDF → system("audiveris ...") → MusicXML → 解析为 Score → 控制台打印音高`。
- **产出**：端到端输入链路——这是 MVP 真正"可演示"的前提（项目目前还依赖人工提供 MusicXML）。

---

## 3. L2 — 五线→简谱核心（MVP v1，项目已完成，作为精读+复刻练习）

**核心模块（精读本项目源码）**
- `include/jianpu_model.hpp`：L0 简谱权威模型 `JianpuDoc/JianpuNote`。
- `include/jianpu_converter.hpp` + `src/jianpu_converter.cpp`：纯函数 `fifthsToTonicPc` / `fifthsToTonicName` / `midiToJianpu` / `midiToDegree` / `typeToDuration`，主流程 `staffToJianpu`。
- 三种渲染：`jianpuToL1`（纯文本）/ `jianpuToL2`（二维 HTML/Unicode）/ `jianpuToJson`（L3）。
- 测试：`test/`（header-only 自研框架）+ `omr-tool-research/verify_jianpu_groundtruth.py`（music21 跨语言校验）。

**预估耗时**：3–4 周；若作为"复刻练习"精读，可压缩到 1–2 周。

**依赖**：L0（解析层）。

**实践任务 / 里程碑（建议复刻以真正掌握，而非只读）**
- [ ] 不抄代码，自行实现 `staffToJianpu`：主音计算、pitch→首调音级、临时记号择优、八度点、时值反推。
- [ ] 写规范 §5 九项边界单测（`test_tonic` / `test_pitch_mapping` / `test_duration` / `test_staff_to_jianpu`）。
- [ ] 实现 L1/L2 渲染，用 `data/` 8 份语料跑通，对照 `jianpu_l2_cello.html` 等预览。
- [ ] 运行 `verify_jianpu_groundtruth.py`，弄懂"用独立算法做 ground-truth 交叉验证"的方法论。
- **产出**：MVP v1（项目已交付并 100% 校验；学习者目标是"能独立重写并逐行解释"）。

---

## 4. L3 — 简谱→五线（项目已规划、未实现 → 优秀练手）

**核心模块（见 `stage3_action_plan.md`）**
- `jianpuToStaff(const JianpuDoc&) -> Score`：音级逆映射（degree→step/alter/octave）、时值逆映射（underlines/augmentDashes/dots→type+duration）、组装 `Score`（多声部/休止/和弦/装饰音/延音线）。
- **`Score → MusicXML` 序列化**：项目当前只有"解析"没有"写出"，这是模块⑤ MusicXML 导出的前置。
- **round-trip 音高守恒自测**：`staffToJianpu → jianpuToStaff` 比较音高序列。

**预估耗时**：2–3 周。

**依赖**：L2。

**实践任务 / 里程碑**
- [ ] 实现 `jianpuToStaff`，覆盖反向九项边界（对照 L2 的 §5 做"逆"断言）。
- [ ] 实现 `Score → MusicXML` 写出，写出的文件能被本项目解析器读回且语义等价。
- [ ] round-trip：对 `data/` 单声部子集，还原音高序列 100% 守恒（阶段 2 的 54/54 单测无回归）。
- [ ] `main.cpp` 新增 `--to-musicxml [out.musicxml]` 演示端到端反向。
- **产出**：双向转换闭环（建议打标签 `phase-3`）。

---

## 5. L4 — AI / 深度学习进阶（转 AI 主战场）

**核心模块（要掌握）**
- PyTorch 入门（`d2l.ai` / `CS231n`）。
- 用 **DeepScores / DoReMi** 合成数据微调小模型做单声部音符检测；或适配 **LEGATO / Clarity-OMR** 预训练权重。
- **ONNX Runtime** 在 C++ 部署（Python 训练 → `torch.onnx.export` → C++ 推理）。
- 评测脚本：在 MVP 测试集上算 precision / recall。

**预估耗时**：4–8 周（最重、价值最高）。

**依赖**：L1（识别链路）、L2/L3（MusicXML 表示）、对 CV 原理有基础。

**实践任务 / 里程碑**
- [ ] 训一个最小音符检测模型，在 MVP 测试集上输出 precision/recall。
- [ ] 导出 ONNX，在 C++ 用 ONNX Runtime 推理，替换 Audiveris 作识别引擎。
- [ ] 写评测报告，对比自训模型 vs Audiveris 准确率。
- **产出**：可写进简历的高价值产出（"数据→模型→评测"闭环）。

---

## 6. L5 — 工程化与作品集

**核心模块（要掌握）**
- **Qt / ImGui** Windows GUI：PDF/简谱输入、简谱渲染、纠错编辑器。
- 文档与打包（安装包 / CI）。

**预估耗时**：2–3 周。

**依赖**：L2/L3（核心转换）、L4（可选 AI 后端）。

**实践任务 / 里程碑**
- [ ] 用 Qt 做简单 GUI：打开 MusicXML/PDF → 显示简谱 → 导出。
- [ ] 写技术报告，整理 GitHub 仓库（README / CI / 示例 / 标签）。
- **产出**：可演示 Windows 应用 + 考研 AI 方向作品集。

---

## 7. 学习节奏与工程习惯建议

- **节奏**：课余并行，每天 2–3 小时，周末集中攻坚；每个阶段结束必须有"可运行/可展示物"才进下一阶段。
- **读码方法**：代码读不懂 → 先跑 `build/PuduTests.exe` 看单测，再跑 `verify_jianpu_groundtruth.py` 看"正确长什么样"，最后对照 `jianpu_output_spec.md` 的字段定义。
- **版本控制（沿用本项目实践）**：每个阶段开 `feat/xxx` 分支；完成自测后 **squash 合并到 `main`** 并打 `phase-N` 标签；提交信息用 Conventional Commits（`feat`/`fix`/`docs`/`test`/`build`）。
- **先深后广**：L0→L2 最快拿到正反馈；L1/L3/L4/L5 是在核心上加厚度，可按兴趣/目标取舍（想转 AI 就重点投 L4）。
- **不要手搓 CV**：架构已决定识别端用成熟引擎黑盒，自研 CV 降级为选做练兵——把精力放在"转换逻辑"和"AI"这两块真正有产权的部分。

---

## 附：本项目当前进度（你的学习起点）

| 阶段 | 状态 | 你可从这里切入 |
|---|---|---|
| L0 环境/MusicXML | ✅ 完成 | 精读 `score_model.hpp` / `musicxml_parser.cpp` 复刻 |
| L1 OMR 黑盒 | ⬜ 未开始 | 直接动手做（见 L1 里程碑） |
| L2 五线→简谱 | ✅ 完成（标签 `phase-2`） | 复刻 `staffToJianpu` + 跑通校验 |
| L3 简→五线 | ⬜ 未开始（有 `stage3_action_plan.md`） | 直接动手做，练反向映射 |
| L4 AI/DL | ⬜ 未开始 | 后期重点 |
| L5 工程化 | ⬜ 未开始 | 收尾 |

> 最快的正反馈路径：**L0（复刻解析）→ L2（复刻转换，已验证可 100% 通过）→ L3（实现反向，填补空白）→ L1（接输入）→ L4/L5（厚度与作品集）**。
