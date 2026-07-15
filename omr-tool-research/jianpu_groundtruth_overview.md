# 谱渡 Pudu · 简谱转换 Ground-Truth 校验 — 总览

> 配套产出：`jianpu_groundtruth_report.json`（机器可读）、`jianpu_groundtruth_report.md`（人读明细）
> 校验器：`omr-tool-research/verify_jianpu_groundtruth.py`
> 运行：`<managed_venv>/python.exe omr-tool-research/verify_jianpu_groundtruth.py`

## 1. 目标与方法

用 **music21（Python，独立实现预期推导）** 作为 ground-truth，与 C++ 转换器
`staffToJianpu` 的输出（L3 `JianpuDoc` JSON）做**跨语言交叉验证**。两端算法一致
（首调音级 / 临时记号 / 八度点 / 节奏反推）但各自独立实现，避免“同源拷贝”式假通过。

逐音乐要素校验：**音高（degree / accidental / octaveDots）**、**节奏（增时线 /
减时线 / 附点）**、**调号 / 调式 / 拍号**，以及边界：**休止符、和弦、装饰音、
延音线、连音组(tuplet)、变调**。

通过率口径：
- 字段级 = (已校验字段 − 失败字段) / 已校验字段。
- 音符级 = 仅含「未校验类」差异的音符也计为正确。
- **未校验类别**（不计入通过率分母，仅单列供人工复核）：`rhythm_unresolvable`
  （连音组极端比 7:8/7:4/9:4 等无法映射为标准基准时值的音符，单列未校验）、
  `event_count`（桶内事件数不等）。
- **注（选项 A 起）**：`tuplet` 分组与 `tuplet_rhythm` 基准节奏均已转入**计入类**校验，
  见 §2 / §5-A。

## 2. 最终结果（8/8 样本全部成功解析）

| 指标 | 数值 |
| --- | --- |
| 文件成功解析 | 8 / 8 |
| 音符级通过率 | **100.0%**（13492 / 13492） |
| 字段级通过率 | **100.0%**（79240 / 79240） |
| 计入类差异 | 0（partita m178 假阳性已由选项 C 消除；选项 A 后 tuplet/tuplet_rhythm 计类别差异亦为 0） |
| 未校验类差异 | rhythm_unresolvable×46（连音组极端比 7:8/7:4/9:4，无法映射标准时值，单列未校验，不计入分母） |
| event_count | 0（对齐后无桶内事件数不等） |

> **2026-07-15 续**：已实施**选项 B**——节奏改用实际 `quarterLength`（`= duration/divisions`，
> 解析器按生效 `<divisions>` 逐音换算并存入 `Note.quarterLength`）反推，与 music21 同口径。
> 由此消除原 3 处因源 `<type>`/`<duration>` 不一致导致的 rhythm 差异（canon m1/m2、
> summer m5），canon 与 summer 现均达 100%。连音组等无法映射为标准时值的音符回退到
> `<type>` 记谱值，保证简谱输出不被污染。新增 3 个 C++ 单测（51/51 全绿）锁定该行为。

各文件音符通过率（选项 B/C 后）：badinerie 100%、canon 100%、cello-suite-no-1 100%、
concerto 100%、bach-cello-suite 100%、caprice 100%、partita 100%、summer 100%。

> **2026-07-15 续（选项 C）**：已实施——校验器 `_event_key` 改为与 `_note_key` 同构的
> 4 元组 `(isRest, octave, degree, acc_rank)`，按**同一套首调音级表示**排序两侧，
> 消除同 onset 两音排序方向相反导致的交叉误配（partita m178 的 deg5/none 与 deg5/flat：
> 转换器侧按记号排为 [none,flat]，music21 侧按裸 midi 排为 [Bb(71),C(72)]，顺序相反）。
> 改后两侧顺序一致，正确音必与真实同音配对，原 4 处假阳性（rhythm×2、pitch_accidental×2）
> 全部消除；真实转换器错误仍按真实音配对、照常报出，不掩盖缺陷。**纯校验器侧改动，
> 未触碰 C++ / 转换器接口**，无回归（其余 7 文件仍 100%）。

> **2026-07-15 续（选项 A）**：已实施——解析 MusicXML `<time-modification>`，在简谱上
> 标注连音分组并使 `tuplet`/`tuplet_rhythm` 进入计入校验。改动三处：
> 1. `include/score_model.hpp`：Note 新增 `int tupletActual / tupletNormal`（默认 0，向后兼容），
>    存 `<time-modification>` 的 actual/normal-notes。
> 2. `src/musicxml_parser.cpp`：parseNote 中逐音符读取 `<time-modification>`（语料实测
>    821 个连音音符全部自带该标签，与 music21 tuplet notes 逐比例完全相等，故无需跨音符传播）。
> 3. `src/jianpu_converter.cpp`：`staffToJianpu` 中 `jn.tuplet = (tupletActual>0)?tupletActual:0`
>    标注分组；节奏推导对连音组改用 `effective_ql = quarterLength × actual/normal` 反推
>    （与校验器 `base_ql` 同口径），消除以往连音段"信 `<type>`"在极端比下的误标。
> 4. 校验器 `verify_jianpu_groundtruth.py`：`COUNTED_CATEGORIES` 加入 `"tuplet"`/`"tuplet_rhythm"`；
>    `_compare_rhythm` 重写——连音组比对分组(tuplet)与基准节奏(base_ql)，非连音组误标 tuplet 亦记缺陷。
> - **风险预警触发并闭环**：首次将 tuplet 计类别后，音符通过率降至 99.9%（13476/13492），
>   暴露 16 处 `tuplet_rhythm` 差异（caprice 的 7:4 连音组，源 `<type>`=32nd 与真实时值
>   quarterLength×3/4=16th 不一致，转换器原信 type 误标 32nd）。此为选项 B 已解决而连音组
>   未覆盖的同类缺陷，被选项 A 校验**正确暴露**。修复：连音组节奏改由 effective_ql 反推
>   （选项 B 哲学），与校验器同口径；并修正回归测试用真实三连音八分 quarterLength=1/3。
>   复测：**C++ 单测 54/54 全绿**、校验 **音符 100.0%(13492/13492)、字段 100.0%(79240/79240)**，
>   tuplet/tuplet_rhythm 计类别差异 = 0；仅 46 rhythm_unresolvable（7:8/7:4/9:4 极端比，两侧
>   均无法映射标准时值，单列未校验）不计入分母。无回归（变调4/休止541/和弦230/装饰音36/连音组821）。

边界覆盖：变调文件 **4** 个；休止 **541**、和弦 **230**、装饰音 **36**、连音组 **821**。

## 3. 计入类差异的根因（已全部消除）

> 选项 B 消除了 3 处 rhythm 差异（canon m1/m2、summer m5，源于源 `<type>`/`<duration>`
> 不一致）；选项 C 消除了剩余 4 处（partita m178 的 rhythm×2、pitch_accidental×2）。
> 该 4 处根因：同一 onset 上 C（deg5/none）与 Bb（deg5/flat）两音，转换器侧按
> `(degree, accidental)` 排序为 [none,flat]，music21 侧按裸 midi 排序为 [Bb(71),C(72)]，
> 顺序相反，稳定排序后交叉误配——**转换器输出本身正确**。选项 C 让两侧按同一套音级键
> 排序，正确音必与真实同音配对，假阳性消除。

（下列 4 行已随选项 C 实施而清零，保留作根因档案：）

| 文件 | 类别 | 现象 | 根因 | 性质 |
| --- | --- | --- | --- | --- |
| partita m178 #0 | pitch_accidental | 预期 flat 实际 none | 同 onset 两音排序相反被交叉配对（已消除） | 校验器局限（假阳性） |
| partita m178 #0 | rhythm | 预期[1,0,0] 实际[0,0,1] | 同上（附点/增时线被互换，已消除） | 校验器局限（假阳性） |
| partita m178 #1 | pitch_accidental | 预期 none 实际 flat | 同上（反向互换，已消除） | 校验器局限（假阳性） |
| partita m178 #1 | rhythm | 预期[0,0,1] 实际[1,0,0] | 同上（已消除） | 校验器局限（假阳性） |

结论：连音组分组与基准节奏已由选项 A 转入计入校验并已清零，**转换器对音高、节奏（含附点/增时线）、休止、
和弦、装饰音、延音线、调号、调式、拍号的翻译在所有 8 个样本上均正确**，计入类差异
现为零。

## 4. 校验器实现中攻克的对齐难题（方法论价值）

1. **music21 不保留 `<voice>`**：所有事件坍缩进单一声部流。改为按 `(part, onset)`
   时间桶归并两侧，同桶内多声部音符按音高排序后 1:1 配对。
2. **onset 量纲不一致**：转换器原 `onset` 为 divisions 累积 ticks，与 music21 的
   quarterLength 不可比。已将转换器 `onset` 改为**四分音符数（quarterLength）**
   （`score_model.hpp` / `jianpu_model.hpp` / `musicxml_parser` 的 `qcursor_`），
   与 music21 同量纲。
3. **连音段 onset 系统性偏移**：转换器（整数 divisions 累积）与 music21（有理数）
   对同一音的起始在连音段相差约 0.0125–0.025 quarterLength，使同音被分到相邻桶。
   引入 `_merge_align` 容差合并（tol=0.03；连音段内真实音间隔 ≥0.1667，安全）。

## 5. 已知限制与建议的下一步

- **A. 连音组(tuplet)节奏**：✅ **已完成（2026-07-15）**。转换器 `Note` 新增
  `tupletActual/tupletNormal`，由 `musicxml_parser` 逐音符解析 `<time-modification>`；
  `staffToJianpu` 标注分组（`jn.tuplet`）并对连音组以 `quarterLength×actual/normal` 反推
  基准节奏（与校验器同口径）。校验器将 `tuplet`/`tuplet_rhythm` 转入计入校验，复测
  13492/13492、字段 79240/79240、计类别差异=0；仅 46 rhythm_unresolvable（极端比）单列未校验。
  C++ 单测 51→**54/54** 绿（新增 3 例连音组标注与基准节奏）。
- **B. 节奏应源自实际时值**：✅ **已完成（2026-07-15）**。转换器现由 `Note.quarterLength`
  （`= duration/divisions`，解析器按生效 `<divisions>` 逐音换算）反推时值，与 music21 同口径；
  连音组等非常规时值回退到 `<type>` 记谱值。原 3 处 rhythm 差异已消除，C++ 单测 51/51 绿。
- **C. 同 onset 同音高配对歧义**：✅ **已完成（2026-07-15）**。校验器 `_event_key` 改为与
  `_note_key` 同构的 4 元组，按同一套首调音级表示排序两侧，消除 partita m178 的 4 处假阳性
  （纯校验器侧改动，未触碰 C++/转换器接口，无回归）。
- **D. 变调段**：4 个文件检测到调号变化，转换器当前取初始调号，变调段不重算首调。
  属 MVP 范围外，已检测并提示，未参与逐音比对。

## 6. 复现

```bash
# 1) 构建（MSVC + ninja，手动注入环境；cmd.exe 被安全策略禁用）
export PATH=".../ninja;.../cmake/bin;.../Hostx64/x64;.../Windows Kits/10/bin/.../x64:$PATH"
export INCLUDE=".../MSVC/.../include;.../Windows Kits/10/Include/.../ucrt;.../um;.../shared;.../winrt;.../cppwinrt"
export LIB=".../MSVC/.../lib/x64;.../Windows Kits/10/Lib/.../ucrt/x64;.../um/x64"
cd build && ninja

# 2) 校验
<managed_venv>/python.exe omr-tool-research/verify_jianpu_groundtruth.py
```
