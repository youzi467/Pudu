# 简谱渲染布局、空声部休止符填充与大谱表输出需求文档

> 生成：2026-09-21
> 状态：需求 / 可行性分析（未实施）
> 关联：`docs/product-status.md`、`docs/next-steps.md`

---

## 1. 背景与目标

当前简谱 L2 HTML 输出把所有小节塞进单个 `.line` 容器，依赖浏览器 `flex-wrap` 自动换行；行数、每行小节数不可控，也不显示小节号。多声部谱中，某些声部在小节内未识别到音符时，该小节在渲染上直接留空，视觉断层明显。此外，原以**大谱表**（钢琴等上下两行五线谱）呈现的谱面，转换后目前丢失高低音分组语义。

产品新需求：
1. 渲染出的简谱每行小节数固定为 **4 / 6 / 8 / 10**（可配置）；
2. 每行行首标注当前行**起始小节号**；
3. 对**没有识别到音符的声部（voice）**，以休止符 **0** 填充，保证各行小节对齐、视觉完整；
4. 对原大谱表谱面，转换后的简谱也以**大谱表形式**输出（上下两行 + 左侧花括号）。

目标是在不破坏现有识别精度、不改动 L1/L3 语义模型的前提下，把 L2 HTML 升级为「可分页、可校对、版面整齐、保留声部分组」的正式输出格式。

---

## 2. 范围与假设

### 2.1 范围

- **包含**：L2 HTML 渲染器（`jianpuToL2`）、CLI 参数、网页/桌面端透传。
- **不包含**：L1 纯文本换行、L3 JSON 结构变更、MusicXML 内容变更、识别引擎改进。

### 2.2 假设

- 固定每行小节数仅影响视觉排版，不改变音符语义。
- 行首小节号指该行**第一个小节的编号**（从 1 开始）。
- 空声部填充仅作用于**已存在的 voice**（即该 voice 在其他小节出现过）；整曲从未出现的 voice 不生成。
- 填充休止符的时值应匹配小节时长，保证节拍对齐。

---

## 3. 功能需求

| ID | 需求 | 优先级 | 描述 |
|---|---|---|---|
| FR-1 | 固定每行小节数 | P0 | L2 HTML 按 `4/6/8/10` 小节切行；最后一行可少于设定值。 |
| FR-2 | 行首小节号 | P0 | 每行最左侧标注起始小节号，**仅数字**，如 `5`。 |
| FR-3 | 空声部休止符填充 | P0 | 对 `notes` 为空的小节，渲染为等时值的休止符 `0`（弱起小节除外）。 |
| FR-4 | 可配置开关 | P1 | CLI 与网页端均可选择每行小节数；**网页端默认 4**，CLI 无参数时保持自动换行以兼容旧行为。 |
| FR-5 | 多声部系统分组 | P0 | 同一 measure 区间的多个 voice 行归为一个「系统」，**仅系统首行显示小节号**。 |
| FR-6 | 大谱表输入识别 | P1 | 覆盖大谱表两种 MusicXML 写法：**单一 part + 多 `<staff>`**、**两个平行 part**（左右手各一）。 |
| FR-7 | 大谱表渲染 | P1 | 上下两行谱（上行高音区、下行低音区）按小节对齐，**左侧花括号**连接，贴近原五线谱观感。 |
| FR-8 | 大谱表触发 | P1 | 单一 part+多 staff **自动识别**；两个平行 part **手动** `--grand-staff` 指定配对。 |
| FR-9 | 大谱表与系统关系 | P1 | 大谱表两行**同属一个系统**：共享每行 N 小节，行首节号仅标在上行，全程节号连续。 |

---

## 4. 非功能需求与约束

- **零识别回归**：不修改 `staffToJianpu` 语义，不污染 L1/JSON/eval。
- **零外部依赖**：继续用内联 CSS/SVG，不引入新库。
- **向后兼容**：CLI 无参数时输出与 v0.9.1 逐字节一致。
- **默认行为**：网页端默认每行 4 小节；CLI 默认自动换行。
- **可打印**：换行后仍适配 A4 打印，不溢出 `.score` 容器。

---

## 5. 可行性分析

### 5.1 固定每行小节数 —— 可行，改动集中

当前 `jianpuToL2` 把每个 `JianpuLine`（一条 voice）的全部 measures 输出到单个 `.line` div 中，靠 CSS `flex-wrap` 自动换行（[jianpu_converter.cpp:552](src/jianpu_converter.cpp#L552)）。

要固定每行小节数，只需在渲染前把 `line.measures` 按 `N` 切片，每片生成一个 `.line` div。CSS 无需大改，增加一个 `.line-number` 标签即可。

**复杂度**：低。

### 5.2 行首小节号 —— 可行，纯渲染逻辑

每片切好后，取 `measures[0].number` 生成行首标签。`JianpuMeasure` 已携带 `number` 字段（[jianpu_model.hpp:67](include/jianpu_model.hpp#L67)）。

**复杂度**：低。

### 5.3 空声部休止符填充 —— 可行，需处理边界

`staffToJianpu` 会为每个 voice 生成 `JianpuMeasure`；若该 voice 在小节内无音符，`notes` 为空（[jianpu_converter.cpp:130-220](src/jianpu_converter.cpp#L130-L220)）。渲染层检测到空 `notes` 后，可合成休止符 `JianpuNote`：

- `degree = 0`
- `augmentDashes / dots` 由小节时值反推（4/4 → 全休止 `augmentDashes=3`；3/4 → 附点二分 `augmentDashes=1, dots=1` 等）。
- 现有 `l2Digit` 已能把长休止拆成多个 `0`（[jianpu_converter.cpp:410-421](src/jianpu_converter.cpp#L410-L421)）。

**需要决策的边界**：
- **弱起 / 不完全小节**（`implicit=true`）：若该 voice 为空，填充「整小节休止」会虚增时长。**已确认跳过填充**，保持空白（见 §7.1）。
- **多声部同一 measure 区间**：每个 voice 行独立填充即可，未来可升级为「系统级」分组。

**复杂度**：中低。

### 5.4 大谱表支持 —— 可行，需先补 `<staff>` 解析与配对

**现状缺口**：解析器明确**未解析 `<staff>` 分层**，Note 无 staff 字段（[musicxml_parser.cpp:6](src/musicxml_parser.cpp#L6)、[score_model.hpp:76](include/score_model.hpp#L76)）。因此：
- **单一 part + 多 `<staff>`** 形式：两行的音符全被并入同一 `Measure.notes`，谱表归属丢失——必须补 `Note.staff` 解析才能区分上下行。
- **两平行 part** 形式：内核已把每个 part 解析为一个 `JianpuLine`，只需「配对成组」并加视觉连接。

**改动路径**：
1. `Note` 增加 `int staff`；解析器读 `<note><staff>`。
2. `JianpuLine` 增加 `staff`（透传 part 内谱表归属）与配对标识。
3. 单一 part 自动识别为 grand pair；两平行 part 由 `--grand-staff P1,P2` 配对。
4. 渲染：同一系统内按「上行谱行组 → 下行谱行组」堆叠，左侧花括号跨两行，行首节号仅上行。

**复杂度**：中高（涉及解析器 + 数据模型 + 渲染三处，但互不破坏既有单声部路径）。

---

## 6. 技术方案概述

### 6.1 新增渲染配置

在 `jianpu_converter.hpp` 增加：

```cpp
struct JianpuRenderConfig {
    int measuresPerLine = 0;      // 0=自动（现状）；4/6/8/10=固定
    bool fillEmptyVoiceRest = false; // 空声部是否补 0
    // 大谱表：手动指定的两平行 part 配对。格式 {上游 partIndex, 下游 partIndex}。
    std::vector<std::pair<int,int>> grandStaffPairs;
    // 若置 auto，则对单一 part+多 staff 自动合并成大谱表。
    bool autoGrandStaff = true;
};
std::string jianpuToL2(const JianpuDoc& doc, const JianpuRenderConfig& cfg = {});
```

默认 `measuresPerLine = 0` 保证与现网输出一致；`autoGrandStaff` 默认开（不影响非大谱表谱面）。

### 6.2 L2 渲染流程调整

1. 若 `cfg.measuresPerLine > 0`（设为 N），按小节号把 `doc.lines` 切成**系统**层：凡落在同一小节区间 `[k*N+1, (k+1)*N]` 内的各 voice 行归为一个「系统」；
2. 每个系统渲染为一个 `.system` div，内含若干 `.line` div（一个 voice 一行）：
   - 仅**该系统第一个 voice 行**开头插入 `<span class="line-number">k*N+1</span>`（其余 voice 行不重复显示）；
   - 该系统最后一行允许不足 N 小节；
3. 渲染每个 measure 前，若 `cfg.fillEmptyVoiceRest && m.notes.empty() && !m.implicit`，合成休止符 note 再渲染；
4. 单声部谱退化为单个 voice 行的系统，行为与多声部系统分组一致（自动经同一路径）。

### 6.3 CLI 参数

```text
--measures-per-line <4|6|8|10>   # 默认 0=自动
--fill-empty-voice-rest          # 开启空声部休止符填充
--grand-staff <a,b>              # 手动配对两个平行 part 为大谱表（可重复）
# --grand-staff-auto             # 单一 part+多 staff 自动识别（默认开）
```

### 6.4 网页 / 桌面端透传

- `pudu_server.py`：在 `/api/ocr` 或设置接口中接受 `measures_per_line`、`fill_empty_voice_rest`、`grand_staff`，拼进 `Pudu.exe` 命令行。
- `pudu_ui.html`：设置面板增加「每行小节数 / 空声部补 0 / 大谱表合并」控件，值存入 `%APPDATA%/Pudu/settings.json`。

### 6.5 大谱表数据模型与配对

1. **`<staff>` 解析**：`Note` 增加 `int staff`；`musicxml_parser.cpp` 的 `parseNote` 读 `<note><staff>`（缺省 0；单谱表恒 0/1 无影响）。`parsePart` 记录该 part 是否有 `staff 1|2`（含 `<staves>2</staves>` 或音符带 `<staff>`）。
2. **模型透传**：`JianpuLine` 增加 `staff` 与配对组号 `pair`；`staffToJianpu` 把 `Note.staff` 透传进对应 line。
3. **大谱表对识别**：
   - 单 part 含双谱表 → 自动形成 pair `(pi, staff1)+(pi, staff2)`；
   - 两平行 part → 依 `cfg.grandStaffPairs`（手动指定）配对；缺省启发式尝试配相邻同名校（Name 含「钢琴/Piano/手/hand」）。
4. **渲染（叠加到 §6.2）**：每个系统内，先按 `pair` 分组，组内先渲染上行谱（staff=1 的 voice 行）再下行谱（staff=2），两行以左侧花括号 `.system-brace` 相连；行首节号仅在上行。
5. **保守原则**：合成大谱表不影响 `Measure.notes` 与 L1/JSON 语义；取消大谱表合并时按普通多声部系统渲染。

---

## 7. 决策记录 / 开放问题

### 7.1 已确认（2026-09-21，产品拍板）

| 决策点 | 结论 |
|---|---|
| 默认每行小节数 | 网页端默认 **4**；CLI 无参数默认自动换行 |
| 行首小节号格式 | **仅数字**，如 `5` |
| 多声部小节号显示 | 同一系统**仅首行**显示；多声部系统分组纳入 P0 |
| 弱起/不完全小节（implicit）休止符填充 | **跳过填充**，保持空白 |
| 休止符填充与「需校对」关系 | **保留现有「需校对」面板**；填充仅视觉补全，不改识别结果 |
| 大谱表输入表示 | **单一 part+多 staff 与两平行 part 均支持** |
| 大谱表渲染形式 | **两行上下对齐 + 左侧花括号** |
| 大谱表触发 | **单一 part 自动识别；两平行 part 手动 `--grand-staff` 配对** |
| 大谱表与系统关系 | **两行同属一个系统，行首节号仅上行，节号连续** |

### 7.2 仍需注意

- 行首小节号默认从 **1** 开始；若未来需支持「起于非首小节」，再另立参数。
- 系统分组的行内 voice 顺序维持 `JianpuDoc.lines` 现有顺序（voice 升序）。
- 两平行 part 的自动启发式配对各相邻同名 part，但**同名不等于必为大谱表**；启发式仅作缺省，最终以手动 `--grand-staff` 为准。

---

## 8. 阶段执行计划

> 总工作量约 **5–7 天**。原则：默认行为不变，新能力通过参数打开。

### P0 — 需求确认与设计（0.5 天）✅ 决策已定（2026-09-21）

- [x] §7 决策点已拍板（默认 4 / 仅数字 / 系统首行 / 弱起跳过 / 保留需校对面板）。
- [ ] 冻结 `JianpuRenderConfig` 字段与 CLI 参数名。
- **DoD**：需求文档评审通过；接口签名确定。

### P1 — C++ L2 渲染器改造（1–2 天）

- [ ] `include/jianpu_converter.hpp`：新增 `JianpuRenderConfig`。
- [ ] `src/jianpu_converter.cpp`：
  - 按小节区间把 `doc.lines` 切分为**系统**（`measuresPerLine = N`）；
  - 每系统渲染 `.system` div，内含各 voice 行 `.line`；
  - 仅系统首 voice 行插入 `.line-number`（数字）；
  - 空 measure 合成休止符（`implicit` 跳过）；
  - 新增 `.system` / `.line-number` CSS。
- [ ] `src/main.cpp`：解析 `--measures-per-line`、`--fill-empty-voice-rest`，透传配置。
- **DoD**：
  - `--measures-per-line 4` 输出每系统 4 小节、仅系统首行显示小节号；
  - 无参数时与 v0.9.1 输出逐字节一致；
  - 空 voice 小节显示 `0`，弱起小节保持空白。

### P2 — 大谱表支持（1.5–2 天）

- [ ] `include/score_model.hpp`：`Note` 增加 `int staff`。
- [ ] `src/musicxml_parser.cpp`：`parseNote` 读 `<note><staff>`；`parsePart` 记录双谱表标志（`<staves>2</staves>` 或音符带 `<staff>`）。
- [ ] `include/jianpu_model.hpp`：`JianpuLine` 增加 `staff` 与配对组号 `pair`。
- [ ] `src/jianpu_converter.cpp`：`staffToJianpu` 透传 `Note.staff` → line.staff/pair。
- [ ] `jianpuToL2`：
  - 单 part 多 staff 自动识别大谱表（`autoGrandStaff`）；
  - 系统内按 pair 分组、先上行再下行渲染，左侧花括号 `.system-brace`；
  - `--grand-staff a,b` 手动配对两平行 part。
- [ ] `src/main.cpp`：解析 `--grand-staff`（可重复）、`--grand-staff-auto`。
- **DoD**：
  - 单一 part + `<staff>1/2` 的谱自动渲染为两行 + 花括号；
  - `--grand-staff 0,1` 将 part0/part1 合并为大谱表；
  - 非大谱表谱面（单 part 单谱表 / 无关多 part）不受影响，与 P1 输出一致。

### P3 — 单元测试与回归（0.5–1 天）

- [ ] 新增 Python/C++ 测试：固定切行、行首小节号、空声部填充、implicit 跳过、大谱表自动识别、手动配对。
- [ ] 跑通既有测试集，确认无回归。
- **DoD**：测试全绿；代码评审通过。

### P4 — 服务端与前端透传（0.5–1 天）

- [ ] `tools/pudu_server.py`：接口接收 `measures_per_line` / `fill_empty_voice_rest` / `grand_staff`。
- [ ] `tools/pudu_ui.html`：设置面板增加下拉框（4/6/8/10/自动）与复选框（空声部补 0、大谱表合并、手动配对），值持久化到 `settings.json`。
- [ ] 桌面端 `desktop_main.py` 冒烟验证。
- **DoD**：网页端切换设置后，预览简谱按新规则（含大谱表）渲染。

### P5 — 文档与发布（0.5 天）

- [ ] 更新 `docs/software-user-manual.md` §4.3 / §6.2（含大谱表）。
- [ ] 更新 `docs/next-steps.md` 待办状态。
- [ ] 打包发布（如有需要）。
- **DoD**：用户手册与行为一致；发布说明包含新功能。

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 默认参数改变破坏现有用户习惯 | 输出格式突变 | CLI 默认 0（自动）；UI 可单独默认 4 |
| 空声部填充掩盖识别 dropout | 用户误以为无错误 | 保留「需校对」面板；填充不改变识别结果，仅视觉补全 |
| 固定 N 导致宽谱溢出 | 打印被截断 | 限制 `.score` 最大宽度 + 横向滚动；提供 4/6/8/10 供选择 |
| 弱起小节填充错误 | 节拍虚增 | 对 `implicit` 小节跳过填充 |
| 多声部小节号重复 | 视觉冗余 | 已按「系统级仅首行」处理（P0） |
| 两平行 part 自动配对误判 | 非大谱表多 part 被误合并 | 启发式仅作缺省，重名不作为硬证据；最终以手动 `--grand-staff` 为准 |
| `<staff>` 上下文缺失 | 单 part 双谱表识别遗漏 | 以音符 `<staff>` 与 `<staves>2</staves>` 双重信号判定 |
| 单 part 双谱表与既有多声部混合 | 同一 part 既有双谱表又有多 voice | 谱表为最外层分组，voice 为组内行，两者正交 |

---

## 10. 验收标准

1. `Pudu.exe --to-jianpu-l2 --measures-per-line 4 out.html` 生成的 HTML 中，除最后一个系统外每系统恰好 4 小节。
2. 每个系统最上行首有清晰的小节号（仅数字），其余 voice 行不重复显示。
3. 某 voice 在某小节无音符时，该小节渲染为 `0`（时值匹配）；弱起小节保持空白。
4. 不带新参数时，输出与 v0.9.1 完全一致。
5. 网页端设置面板可切换每行小节数（默认 4）与空声部填充，预览实时生效。
6. 单一 part + `<staff>1/2` 的谱自动渲染为「两行 + 左侧花括号」的大谱表，行首节号仅上行。
7. `--grand-staff <a,b>` 将两个平行 part 合并为大谱表；其余多 part 谱面（手动关闭/未配对）按普通多声部系统渲染，输出与 P1 一致。
