# 谱渡 Pudu · 阶段 3 行动计划：简谱 → 五线谱（反向转换）

> 依据：`omr-tool-research/results/research_report.md` §3 阶段 3  
> 前置状态（2026-07-15）：阶段 2 已完成（五线→简谱，100% 校验），代码已提交并打标签 `phase-2`。  
> 目标：实现 **简谱 → 五线谱** 反向闭环，使项目从“单向转换器”升级为“双向互转工具”，并完成 round-trip 音高守恒自测。

---

## 1. 当前进展 vs 整体规划（对照 research_report）

research_report 规划 6 阶段、总估时 16–23 周。截至 2026-07-15 实际进度：

| 阶段 | 规划目标 | 实际状态 | 与规划偏差 |
|---|---|---|---|
| 阶段 0 | 环境与 MusicXML 基础 | ✅ 完成 | 符合 |
| 阶段 1 | OMR 黑盒集成（PDF/JPG→MusicXML） | ✅ 完成（M2：oemer 黑盒集成 + 评测 harness + Plan A + H2） | 已超前（07-18 已完成，端到端跑通） |
| 阶段 2 | 五线谱→简谱（MVP v1） | ✅ 完成（已打 `phase-2`） | **超前**（规划文档状态仍为“未开始”，实际已 100% 校验） |
| 阶段 3 | 简谱→五线谱 | ✅ 完成（phase-3/3.1/3.2，双向闭环） | 已超前（07-17/18 已完成） |
| 阶段 4 | AI / 深度学习 | ⬜ 未开始 | 符合 |
| 阶段 5 | 工程化与 GUI | ⬜ 未开始 | 符合 |

**关键结论**：
- 项目的**核心产权层（双向转换逻辑）已完成一半**——正向（五线→简谱）已验证可靠。
- 阶段 3 不依赖阶段 1（OMR），它工作在 MusicXML 进出边界，**现在就能启动**，且是让工具“真正互转”的关键一步。
- 整体完成度（按工期权重）约 45–55%（阶段 0+1+2+3 已完成，核心“双脑”闭环已成，产品已成可用原型）；剩余阶段 4/5 与精度优化线（M2-opt-A2 等）。

---

## 2. 阶段 3 具体任务目标

research_report §3 阶段 3 原文目标：
> 实现 `jianpuToStaff`：解析数字简谱→相对度数→按调号换算绝对音高→生成 MusicXML `pitch`；增时线/下划线→`type`+dot。  
> 产出：双向转换闭环；自测往返一致性（五线→简→五线 音高守恒）。

结合本项目已建模型，拆解为以下**可验证目标**：

### G1（核心）`jianpuToStaff(const JianpuDoc&, Key) -> Score`
消费阶段 2 的 L0 `JianpuDoc`，反向生成 `Score`：
- **音级 → 绝对音高**：`degree + tonicPc(fifths)` → MIDI → `step/alter/octave`（即 `midiToJianpu` 的逆运算）；临时记号 `accidental` → `alter`（♯→+1，♭→-1，♮→0 且与调号冲突时还原）。
- **八度点 → octave**：`octave = tonicRefOctave + octaveDots`（与 `midiToJianpu` 的 `octaveDots = floor((M - tonicRefMidi)/12)` 严格互逆）。
- **时值 → type + duration**：`underlines/augmentDashes/dots` → 标准 `type`（whole/half/quarter/eighth…）+ `dot`；选定固定 `divisions`（建议 4 或沿用输入值）后 `duration = typeBase × divisions × dotFactor`。
- **全局属性**：`doc.tonicLabel/fifths/mode/beats/beatType` → `ScoreAttributes`。
- **多声部**：`JianpuLine` → `Part` 内 `voice`，按 `onset` 还原时间位置（用 `backup/forward` 或并行 onset，与阶段 2 解析器对称）。
- **休止/和弦/装饰音/延音线**映射回 `Note`（`isRest` / `chordPitches` / `isGrace` / `tieStart,tieStop`）。

### G2（序列化）`Score → MusicXML`（pugixml 写出）
当前仓库只有**解析**没有**写出**。`jianpuToStaff` 产出 `Score` 后必须序列化为 `.musicxml` 文件，才能完成“简谱→五线谱文件”端到端输出（即模块⑤的 MusicXML 导出）。  
输出结构：`<?xml?>` + `score-partwise` + `part-list/score-part` + `part/measure`（含 `attributes`：divisions/key/time/clef；`note`：pitch/duration/type/dot/tie/voice/chord/backup）。

### G3（质量）Round-trip 音高守恒自测
对 `data/` 样本（或其中单声部子集）跑 `staffToJianpu → jianpuToStaff →` 比较还原 `Score` 与原 `Score` 的**音高序列守恒**（允许时值表示/divisions 差异，但 step/alter/octave/onset/voice 应一致）。这是对阶段 2 的回归保护，也是阶段 3 的验收标准。

### G4（可选扩展）简谱文本输入解析器
research_report §3.4 与 `musicxml_mvp_tags.md` §5 提到“解析数字简谱”。若要让用户**直接输入简谱文本**（而非先经五线谱），需一个 L1/L2 文本或 JSON → `JianpuDoc` 的解析器。这是“纯简谱→五线谱”的独立输入模式，**优先级低于 G1–G3**（G1 已通过消费 L0 实现 round-trip，无需文本解析即可闭环）。

---

## 3. 优先级排序

| 优先级 | 任务 | 理由 |
|---|---|---|
| **P0** | G1 `jianpuToStaff` + G2 `Score→MusicXML` 序列化 | 反向转换核心，缺它则工具单向；G2 是 G1 的落地出口 |
| **P1** | G3 Round-trip 音高守恒自测 | 质量保险，保护阶段 2 不被反向改动破坏；验收标准 |
| **P2** | G4 简谱文本输入解析器 | 扩展输入模式，让“用户写简谱”可用；非闭环必需 |
| **P3** | 与阶段 2 已知限制对齐：变调段重算首调、小调“6=X”、和弦逐音八度点 | 反向同样需正确处理这些边界，建议在 G1 中一并设计或紧随其后 |

---

## 4. 实施步骤（建议顺序）

1. **S1 设计 `jianpuToStaff` 接口与单测 fixtures**  
   - 在 `jianpu_converter.hpp` 声明 `Score jianpuToStaff(const JianpuDoc& doc);`（必要时带 `Key`/`divisions` 参数）。  
   - 在 `jianpu_output_spec.md` 新增“反向（§6）”章节，明确映射表（degree→step/alter、octaveDots→octave、underlines/augmentDashes/dots→type+duration）。  
   - 建立 `test/test_jianpu_to_staff.cpp` 与 fixture（复用 `test_helpers.hpp`）。

2. **S2 实现音级→音高逆映射**  
   - 逆 `midiToJianpu`：由 `degree` 查大调模板反推 `semi`，加 `tonicPc` + `12×octave` 得 MIDI；`accidental` 决定 `alter` 与是否 ±12 修正。  
   - 覆盖 §5 反向用例：中音区/升八度/降八度、调外音 #4/b7 还原为正确 `alter`、各调号。

3. **S3 实现时值反向映射**  
   - `underlines/augmentDashes/dots` → `type` + `dot`；选 `divisions`（建议常量 `kReverseDivisions=4`，或沿用 `doc` 携带值）。  
   - 附点、`augmentDashes`（二分=1、全=3）、`underlines`（八分=1…）逆查表，与 `typeToDuration` 严格对称。

4. **S4 组装 Score**  
   - `ScoreAttributes` ← `doc`；`JianpuLine` → `Part`/`voice`；按 `onset` 用 `backup/forward` 还原并行时序（与阶段 2 解析器对称）。  
   - 休止/和弦（`chordPitches` → `<chord/>`）/装饰音（`isGrace`）/延音线（`tieStart/TieStop`）映射回 `Note`。

5. **S5 实现 `Score → MusicXML` 序列化**  
   - 新增 `musicxml_serializer.cpp`（或并入 `musicxml_parser.cpp` 的对称函数），用 pugixml 写出完整可解析的 `.musicxml`。  
   - 自检：写出后用**现有 `MusicXMLParser` 读回**应得到等价 `Score`（自洽性测试）。

6. **S6 写 `jianpuToStaff` 单元测试**  
   - 单音 / 八度点 / 附点 / 和弦 / 多声部 / 调号 / 休止 等反向用例（对照阶段 2 的 §5 九项边界做“逆”断言）。

7. **S7 Round-trip 自测（G3）**  
   - 在 `test_staff_to_jianpu.cpp` 或新测试中加入：`staffToJianpu(score) → jianpuToStaff(doc) →` 断言还原音高序列 == 原 `score`（取 `data/` 单声部子集，如 vivaldi/canon/summer）。  
   - 扩展 `verify_corpus.py` 或新增脚本做批量 round-trip 校验。

8. **S8 CLI 与产物**  
   - `main.cpp` 新增 `--to-musicxml [out.musicxml]`：读 MusicXML → staffToJianpu → jianpuToStaff → 写出 `.musicxml`（演示反向闭环）。  
   - 生成一份反向示例（如 `jianpu_l2_sample.html` 的简谱 → 回写 `sample_back.musicxml`）。

9. **S9（可选）简谱文本输入解析器（G4）**  
   - 解析 L1 文本或定义 JSON 简谱输入 → `JianpuDoc`，接 `jianpuToStaff`。  
   - 对应 CLI：`--from-jianpu-text "1 1 5 5 | ..."` 或读 `.jianpu.json`。

10. **S10 文档与收尾**  
    - 更新 `research_report.md` 阶段 3 状态为“进行中/完成”；新增 `jianpu_stage3_overview.md`。  
    - 提交并打标签 `phase-3`（遵循 Conventional Commits：`feat(jianpu): 阶段3 简谱→五线谱反向转换`）。  
    - 刷新 README“阶段与里程碑”“下一步”章节。

---

## 5. 风险与注意

- **divisions 选择**：反向生成需定一个 `divisions`；若与原谱不同，round-trip 时值表示会有差异，但**音高守恒**不受影响（验收只看音高）。
- **变调段**：阶段 2 取初始调号，反向若遇到多调号 `JianpuDoc` 同样需处理；建议在 G1 中预留 `attributes` 按小节切换能力，或阶段 3 先声明“单调号”约束。
- **和弦逐音八度点**：阶段 2 仅存音级，反向只能还原到主音八度点 + 成员音级，无法还原精确成员八度——与已知限制一致，需在文档标注。
- **小调“6=X”**：阶段 2 未实现，反向同样以相对大调法为准，保持前后一致。
- **不破坏阶段 2**：`jianpuToStaff` 为新增函数，对 `staffToJianpu` / 渲染器零侵入；单测须保证 117 个 gtest 用例（含阶段3 新增 9 项）全绿不回归。

---

## 6. 验收标准（Definition of Done）

- [x] `jianpuToStaff` 实现并通过单测（覆盖 §5 反向九项边界）。
- [x] `Score → MusicXML` 序列化可用，写出文件能被本仓库解析器读回且语义等价。
- [x] Round-trip `staffToJianpu → jianpuToStaff` 对样本集音高序列 100% 守恒（117 个 gtest 用例全绿无回归）。
- [x] CLI `--to-musicxml` 可演示端到端反向。
- [x] 提交并打 `phase-3` 标签；README / research_report 阶段 3 状态更新。

---

## 附：阶段 3 与阶段 1 的关系澄清

- 阶段 3 处理 **MusicXML ⇄ 简谱** 的“简谱出”侧，**不依赖** 阶段 1 的 OMR 识别。
- 完整端到端（PDF/JPG → 五线 → 简谱 → 五线 → 导出）需要阶段 1（输入）与阶段 3（反向）都完成；但阶段 3 可独立以 MusicXML 为输入先行交付，建议**优先于阶段 1** 实施（性价比最高、风险最低、直接补全核心产权）。
