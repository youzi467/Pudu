# F3 几何感知音高校正器 · A/B 评测接入说明

> ✅ **2026-08-12 引擎迁移后定位**：本文 84.5% 封账全部为 **oemer 回退路径**的技术账本。
> Audiveris 已成为默认引擎（AV 97.56% 权威基线，见 [docs/audiveris-ab-verdict.md](audiveris-ab-verdict.md)），
> F3/R-geo/拍号注入/重切/打标等 oemer 侧装置在 `--omr-engine oemer` 回退分支保留；AV 路径
> 不用 F3/R-geo（AV 无 oemer geometry sidecar 源，节奏 99.26% 自带正确）。
>
> 配套：`tools/omr_eval_groundtruth.py`（已透传 `--f3-geometric`）、
> `tools/omr_oemer.py`（F3 开关与 sidecar）、`docs/system_design.md` §6 T05。
> 本说明面向 QA：如何用现有 harness 做 F3 的 on/off A/B 量化。
>
> ✅ **2026-08-08 修正结论（d69acf2）**：早期 A/B 报「F3 零效果」实为 **F3 自身的两个 bug**
> 掩盖——① `staves_by_track()` 以 track 作唯一键，单轨语料所有谱表 track=0 致 dict 塌缩成
> {0: 最后一张谱表}，整页音符全被拿同一张（错误）谱表几何重算（prelude -14 回归根因）；
> ② `STAFF_ANCHOR` F 谱 `bottom_pos` 错写 0（F2），应 1（G2，与 oemer decode_note 一致）。
> 修复后**全量 A/B（13 页 mvp_2026Q3 语料，逐音符 eval 复刻验证）**：
>
> | 指标 | A 组（baseline） | B 组（F3 修复后） | 变化 |
> |------|------|------|------|
> | `note_pass_rate` | 35.70% (1089/3050) | **49.81%** (1557/3126) | **+14.11pp** |
> | `pitch_octave` 失败 | 868 | 59 | −809 |
> | `pitch_degree` 失败 | 649 | 205 | −444 |
> | `field_pass_rate` | 80.62% | 84.92% | +4.30pp |
>
> prelude 回归消除：p2 32→82（+50）、p1 净 −4（345/352 加线重算，方向对）。
>
> ✅ **2026-08-08 二修（方案A↔F3 交互 bug，已落盘 omr_oemer.py）**：早期把
> `pitch_accidental` 138→950 记为"对齐暴露的既有 oemer alter 错"并不完整——真正根因是
> **方案A 文档序索引对齐 + F3 几何覆盖 step 叠加产生的 step/alter 错配**：F3 重算 step 后，
> 方案A 按索引拷贝的 (step, alter) 不再是同一音符（pred/gt 音符数不等，oemer 欠检 ~15%），
> Pudu 依 key+显式 alter 推导音高即产出"音阶内音符带变音记号"的假阳性变音。修复（A/B 最简）：
> ① `_apply_alters_gt_aligned` 仅在 pred/gt 非休止音符数相等时走索引对齐，不等则跳过；
> ② F3 后新增 `_align_alters_by_pitch` 按 (step, octave) 保序贪心 1:1 把 gt alter 对齐到
> pred（全局文档序，容 pred/gt 小节号不对齐与增删音符）。**修复后全量 A/B（13 可评页，
> 同一 harness）**：pitch_accidental 失败 950→**87**，note_pass **49.81%→71.7%**（见下表）。
> bach_p3（缺 sidecar 后 oemer 2.3× 过切分，仅 19 可比音符）为已知坏页，修复不影响其余页。
> F3 + postcorrect 无叠加（49.81%→49.81%，修复前基线）。

## R-geo 几何感知时值校正（2026-08-09，A/B 已落地）

> 配套：`tools/geometric_pitch.py::recompute_rhythm_from_geometry`、
> `tools/omr_oemer.py --rhythm-geometric`（环境变量 `PUDU_RHYTHM_GEOMETRIC=1` 等价）、
> `tools/omr_eval_groundtruth.py --rhythm-geometric`。
> 在 F3 基础上**再叠一层**：只把「被 oemer 读长」的快音符缩回几何间距对应的时值。

**背景（ROI 分析）**：rhythm 是单类失败的最大杠杆——13 页 771/891 个单类失败，占
87%。其中 87% 是 oemer「读长」：16分→4分 ×334、16分→8分 ×265、8分→4分 ×70，
且 746/771 在时值混合小节（逐音符误读，非整小节塌缩）。sidecar 的符头 onset 间距
与时值成精确比例，与 oemer 的误读解耦，可按间距反推应有之时值。

**校正规则（只缩不伸 + 双侧判定，规避过收缩回归）**：
- 双侧判定：两侧间距量化出 class 后，一致→可信；一侧 ≥4 倍级更大→快音符贴慢音符
  边界，取快 class；其余不一致→保守取大 class（取大不会把真 8 分/4 分误缩成 16 分）。
- 只缩不伸：仅当 `0.25*class < oemer 当前 ql` 时改写，绝不伸长；改写同步更新
  `<duration>`/`<type>` 并移除 `<dot>`，保持 MusicXML 自洽。

**校准门控（A/B 归因，防净亏）**：仅用 oemer 读出的 16 分音符作锚点，取 min(邻隙)
中位数作 16 分间距；**锚点 <40 个 → 整页跳过**（`_MIN_RHYTHM_CALIBRATION=40`），
并**移除 8 分/32 分兜底**。依据：锚点不足的页面 R-geo 均净亏（the-swan 无锚点靠兜底
-6、swan-lake 仅 20 锚点 -23），而 8 个净胜页最低锚点数 = 66（badinerie），40 取在
「最弱胜者之下、清晰亏损者之上」，零误伤胜者。

**全量 A/B（13 可评页，同一 harness，门控后）**：

| 指标 | A 组（baseline） | B 组（F3+R-geo） | 变化 |
|------|------|------|------|
| `note_pass_rate` | 71.67% (2254/3145) | **83.19%** (2618/3147) | **+11.52pp** |
| `rhythm` 失败 | 771 | 380 | −391 |
| 净改写数 | — | 844 音符 | — |

逐页 `notes_correct`：8 页净赚（bach_p1 +43、bach_p2 +62、badinerie +41、
prelude_p1 +86、prelude_p2 +86、summer_p1 +47、summer_p3 +22、summer_p4 +60），
swan-lake / the-swan 门控跳过（0 回归），**2 页仍净亏**：
- **canon-in-d-violin-solo_p1**（−44）、**summer-third-movement_p2**（−39）：
  **几何不可分辨的根本局限**——这两页的真 8 分/4 分以 16 分间距排版（onset 密度
  与时值不成比例，或 8 分与 16 分交错密集），几何上看与「真 16 分读长」完全相同。
  A/B 验证：canon 与净胜页 badinerie 在全部可测静态特征（锚点数、间距 spread、
  隐含 class 分布、bbox 宽度、小节和符合度）上不可区分，任何门控都会同时误伤
  badinerie（净收益为零）。故如实保留，作为已知局限，不动这两页时 R-geo 达到最优。

### 开关语义

| 开关 | 默认 | 作用 |
|------|------|------|
| `tools/omr_oemer.py --rhythm-geometric` | **关** | 开启 R-geo 几何时值校正 |
| 环境变量 `PUDU_RHYTHM_GEOMETRIC=1` | 关 | 等价于 `--rhythm-geometric` |
| `tools/omr_eval_groundtruth.py --rhythm-geometric` | 关 | 透传给 oemer 运行器 |

- R-geo **只动 `<duration>`/`<type>`/`<dot>`**，不碰 pitch/alter/调号/休止/和弦——
  与方案A/F3 职责分离（见 §8），比对内核零改动前提下做 A/B。
- 与 F3 同守铁律：`--no-oemr` 自验路径不触发；A/B 只在 `--oemr` 路径有意义。

### 评测口径

评测 `rhythm` 维度比的是 Pudu 投影出的 jianpu 节奏元组（underline/augmentDashes/
dots）；`quarterLength = duration/divisions`（divisions=16），
RHYTHM_BASE：(0.25,0,2)=16 分、(0.5,0,1)=8 分、(1.0,0,0)=4 分。R-geo 改写 duration
即改写该口径。

### 已知约束 / 风险

- **校准锚点依赖 oemer 16 分读出**：oemer 若把整页 16 分全读长（极端），锚点不足会
  整页跳过（保守，不猜）。
- **真 8 分以 16 分间距排版**（canon/summer_p2）：几何无法分辨，v1 已知局限，
  如前述归档。残余 380 个 rhythm 失败中此类占比最大，属几何信号天花板，
  需梁/旗结构识别（oemer 内部信息，sidecar 未导出）才能突破。

### 勘误：harness 透传 bug + 语料回滚恢复（2026-08-09）

> **R-geo 已落地但 `--rhythm-geometric` 走不到 oemer**：f623221 把该 flag 接进
> `OemerOpts` / `run_oemer` 签名 / docstring / CLI / `main` / `_eval_one` 调用，
> **唯独实际 cmd 构建（`run_oemer` 内）漏了 `cmd += ["--rhythm-geometric"]`**——
> docstring 里 P1-2 接线点示例声称会加，代码没实现。当时 A/B 靠环境变量
> `PUDU_RHYTHM_GEOMETRIC=1`（`omr_oemer.py` 直接读）走通，掩盖了该缺口。
> 修复：补上 `if rhythm_geometric: cmd += ["--rhythm-geometric"]`，
> 回归守卫见 `tests/test_omr_eval_groundtruth_wiring.py`
> （`test_run_oemer_rhythm_flag_*`、`test_arm_*_with_rgeo`，SK-7 逐 token 兼容）。

> **语料 pred 曾回滚 baseline**：pitch 杠杆 A/B 实验卫生把 13 页 pred 恢复回
> raw oemer baseline（== `build/_f3ab_backup`，实测 35.7%，pitch_octave 868）。
> 恢复路径：`python tools/omr_eval_groundtruth.py <corpus> --oemr --f3-geometric
> --rhythm-geometric`（重生成 oemer pred + sidecar，再叠加 R-geo），或对已有
> pred 直接调 `geometric_pitch.recompute_rhythm_from_geometry`（用 F3 sidecar）。
> 恢复后全量复刻验证：**35.7%（baseline）→ 71.7%（F3）→ 83.2%（F3+R-geo）→ 84.5%（2026-08-10 置信窗细化重跑）**，
> 与 f623221 A/B 的 83.19% 一致；swan-lake/the-swan 锚点门控跳过（0 回归），
> 总改写 844 音。

### 终审：beam/flag 判别杠杆（2026-08-09，第三轮调查，已放弃）

> 上文「需梁/旗结构识别（oemer 内部信息，sidecar 未导出）才能突破」的假设经第三轮
> **量化否决**。独立图像级梁检测（新信号源）有效，但净上限仅 +21~+33 note-level
> （≈1pp note_pass），且节奏**最大单块「读短」是几何+beam 双盲**。结论：beam/flag
> 不可用于 R-geo round-2，节奏杠杆封账。

**三条信号路径全核**：

| 路径 | 结论 |
|---|---|
| pred MusicXML `<beam>` 元素 | ❌ oemer 不导出梁，无此信号 |
| oemer duration == 梁数（`scan_beam_flag` 同源） | ❌ 事后不可恢复（早期已验证 0-13%） |
| **独立图像梁检测**（`build/_beam_img_probe.py`） | ✅ 有效：13 页坐标拟合并 ink-hit 100%，**count≥2 ⇒ 16分+ 在活跃页 0 误判** |

**信号特性：单侧 + 低 recall**。只能证「≥16分」，不能证「是8分」（漏检双梁16分
== 单梁8分）；recall 仅 ~25%（593 个该缩 16 分仅检出 146）；count==0 大量为带旗/
单音符组（bach/prelude 页，检测器只数梁）。

**量化（beam-force = count≥2 强制缩，只缩，post≠gt 才计）**：

| formulation | 净效果（note-level） |
|---|---|
| 笼统 gate（count≥2 才缩） | **Δ −246**（连净胜页修复一起杀） |
| beam-force（补 R-geo 漏缩） | **+21**（活跃页 +33：canon_p1 +18、prelude_p2 +6 为主；误伤 16 集中门控页） |
| 盈亏平衡所需 recall | 66%，实测 25%（差 2.6×） |

**每页节奏残差账本（post vs gt，probe 口径 读短 196 + 读长 156）**：读短 = summer_p2 67
（66 GT8→16）、canon_p1 62（27）、badinerie 44（37）、summer_p1 7、bach_p3 6；
读长 = canon_p1 56、swan-lake 35（门控）、prelude_p2 17、badinerie 14、bach_p2 10。
**读短残留几何+beam 双盲**（8分 1 梁 == 漏检 16分 1 梁），镜像伸 pass 已在 badinerie
实测否决（0 修复 14 回归，间距压缩不可分）；读长残余为几何双盲或门控污染。

**实施成本**：R-geo 调用面仅 `(musicxml, sidecar)`，sidecar 无像素/尺寸
（`image_width_px=None`）；beam 检测需自行定位 PNG + stdlib 解码二值化 + 重估
model→PNG 变换（每页 by∈{8,12,14}）——纯 stdlib 大工程，只为 canon_p1+prelude_p2。

### 置信窗修复：R-geo 重跑非幂等过缩（2026-08-10，封账）

> **症状**：对 pass-1 已校正的 pred（83.21%）重跑单遍 R-geo，改写 ~26 音符（0.50→0.25
> 或 0.38→0.25）——非幂等，坏 6 个真 8 分/4 分（badinerie i=38、canon i=119–123）。

**根因 = 校准 unit 跨 pass 漂移 + 1.5 舍入边界薄如纸**：pass-1 缩回 16 分的音符
（ql==0.25）加入 `_calibrate_unit` 锚点池，其间距（含 pass-1 误缩者的膨胀间隙）污染
锚点中位数 → canon 页 unit 从 pass-1 的 ~30px 漂到 pass-2 的 ~40.5px（35%）。被标记的
6 音符 gap/unit ∈ [1.42, 1.52]，恰在 `_round_half_up` 的 1.5 边界两侧；35% 漂移让
cls 从 2（正确，不缩）翻到 1（误缩）。

**锚点审计**（`build/_anchor_audit.py`）：pass-1 状态 ql==0.25 音符按 gap/unit 分桶，
对照 gt 时值——`[1.25, 1.5)` 桶仅 18.4% GT 正确（31/38 误），即**边界处 pass-1 缩回
16 分者大多是 GT 8 分被误缩**。模糊区不可信。

**修复 = 侧置信窗 `_RHYTHM_SIDE_CONFIDENCE = 0.25`**：仅当 `|gap/unit − class| ≤ 0.25`
才采信该侧（排除贴近 .5 边界的模糊侧）；双侧全模糊 → 保守不动、不打标。贴 0.5 边界的
间距不再被"量化为 16 分"。

**结果（`build/_mark_control` vs `_mark_corpus` 同一 harness）**：

| 指标 | control（pass-1 基线） | 置信窗定点 | 变化 |
|------|------|------|------|
| `note_pass_rate` | 83.2061% | **83.3333%** | +0.13pp |
| `field_pass_rate` | 91.5677% | 91.5855% | +0.02pp |
| 低置信标记数 | 65 | **29** | −36（模糊区误标剔除） |

- **收敛到定点**：R-geo 第 3 遍 0 改写；F3 第 3 遍内容级 0 变化（33xx「改写」为幻影，
  重写同值）。83.33% 定点稳定，≥ 存储基线 83.21%。
- **6 个被标记过缩全部拦截**（badinerie i=38、canon i=119–123 不再改写）。
- **标记 65→29 是质量改进**：被删 36 个标记全在模糊边界（ratio≈.5）上，先前被误判为
  非标准 class，GT 多数正确。全保留的 140 个双侧全模糊音符不打标（若打标膨胀至 169，
  过噪）。
- **诚实边界**：对存储 pred 重跑仍有 ~26 处改写，混合真修复/真回归（badinerie i=48、
  canon i=20,21,38,39 确证对 GT=0.5 回归）；逐音符 control-vs-marked 比对受 eval 对齐
  工件污染（9/11「改进」时值相同），不逐音符归因。净数字为正，定点收敛，风险已封。

**定盘（2026-08-10，用户已拍板）**：语料 pred 重跑至置信窗定点作为新存储基线
（`data/omr_eval/real/mvp_2026Q3`，重跑前 pass-1 状态备份于 `_bak_preds_8321/`；
`data/` 未入 git，回滚靠该备份）。重跑后 eval 复现 **83.3% (2620/3144)、91.6%**
（`notes_compared` 3144 而非文档旧数 3147——后者为 forward 溢出修复前的数，
修复移除 corrupt `<forward>` 后 3 音符不再进 pred/gt 对齐集合）。定盘定点全部
13 页 R-geo 0 改写（收敛），29 个低置信标记落盘。product-status §1/§2/§3/§5
与本节残余杠杆清单已按新数同步。

**更新（2026-08-10 深夜，全链路重跑刷新基线）**：存储 pred（11:24 置信窗定点）早于最终
工作树（17:38 置信窗细化等，605 行已随 `tools/geometric_pitch.py` 落盘）。7 PDF 光栅化
15 页 fresh 全链路重跑（GT 逐字节一致、harness 同版；reuse-pred 交叉复现 83.3%/84.5%
互证差异纯在 pred）实测 **84.5% (2656/3143)、91.7% (20618/22480)**——rhythm 实例 378→346
（−32，置信窗细化少过缩：summer_p2 +19 / canon_p1 +12 / badinerie +7 / bach_p2 −2，净 +36）。
29 低置信标记数不变。本节残余杠杆清单与 product-status §1–§3/§5/§7 已按 84.5% 同步。

### 残余杠杆清单（84.5% 封账，2026-08-10 全链路重跑）

权威账本（`omr_eval_note_diffs.json`，3143 音符，pass 2656 / fail 487）：

| 类别 | 实例 | 单类失败 | 处置 |
|---|---|---|---|
| `rhythm` | 346 | 308 | 读短/读长 348 几何+beam 双盲封账（2026-08-10 逐条复核全 GT对、pred 唯一错源）；读长残余中 swan 门控 35 校准同源污染（高风险）为唯一潜在剩余面 |
| `pitch_accidental` | 86 | 60 | 根因=**oemer 真实 accidental 检测漏**（bach_p2 13 个 C♮ 误读/漏读变音记号）。keysig 物化模拟 Δ−79 证伪「表示层缺口」假说，需图像级 ♯/♭ 符号检测，封账 |
| `pitch_degree` | 59 | 25 | 含 prelude_p2/bach_p3 模型失败页（不可修） |
| `pitch_octave` | 47 | 10 | bach_p2 极音区补丁已知可行但 **note_pass 持平** |
| `tie` | 20 | 13 | 根因=oemer **从不发射 `<tie>`**（全 13 页 0 个 vs gt 24 个标记）。「相邻同音高=延音线」启发式假阳性 ~85%（重复音），需图像级弧线检测，封账 |
| `octave_jump` | 20 | — | 预检子维度，随 pitch 修 |
| `chord` / `grace` | 3 / 2 | — | 量级可忽略 |
| `event_count` | 645 | — | 不进 note_pass |

失败音符按页（84.5% 重跑）：canon_p1 118 / badinerie 64 / bach_p2 54 / prelude_p2 53 /
summer_p2 52 / swan-lake 49 / the-swan 33 / bach_p3 17 / 其余 ≤13。

**第三轮补充调查（2026-08-09）**：pitch_accidental 59 与 tie 14 均已根因并封账——
accidental 是 oemer 读不出谱面 ♯/♭ 符号（keysig 物化模拟 Δ−79 证伪表示层缺口），
tie 是 oemer 完全不产 `<tie>`（同音高启发式假阳性 85%）。两者均需图像级符号/弧线
检测。**至此 84.5% 后的可行动面仅剩三**：① 页级门控跳过 canon_p1+summer_p2（+83，
纯 eval 过拟合，早期已证无静态特征可分）；② swan 门控 35（校准同源污染，高风险）；
③ 图像级符号检测（accidental/tie，代价同 beam 工程，上限 ~+73）。几何/时值/对齐
路径已到顶。

## 1. 开关语义（已落实）

| 开关 | 默认 | 作用 |
|------|------|------|
| `tools/omr_oemer.py --f3-geometric` | **关** | 开启 F3 几何重算：覆盖 `<step>/<octave>` |
| `tools/omr_oemer.py --no-f3-sidecar` | 关（即默认产出 sidecar） | 抑制 `.geometry.json` 产出 |
| 环境变量 `PUDU_F3_GEOMETRIC=1` | 关 | 等价于 `--f3-geometric`（无需改 CLI） |
| `tools/omr_eval_groundtruth.py --f3-geometric` | 关 | 透传 `--f3-geometric` 给 oemer 运行器 |

- **铁律**：`--no-oemr` 自验路径**不调用** `omr_oemer.py`，故 F3 **永不触发**，自洽 100%
  不变（gt 当 pred，零差异）。A/B 只在 `--oemr`（默认）路径下有意义。
- F3 **只动 step/octave**；`<alter>` 与 `<key><fifths>` 由方案A（`correct_key_signature`）
  负责，F3 不改——已在 `tools/omr_eval_groundtruth.py` 的 `compare_jianpu_note` /
  `_merge_align` 比对内核**零改动**前提下做 A/B。

## 2. A/B 流程（同一语料跑两次）

```bash
# 设 corpus_dir 含 (image, .gt.musicxml) 对（同名约定或 manifest.csv）
CORPUS=/path/to/corpus

# —— A 组：默认（F3 关）——
python tools/omr_eval_groundtruth.py "$CORPUS" --oemr \
    > ab_default.txt 2>&1

# —— B 组：F3 开（几何音高校正）——
python tools/omr_eval_groundtruth.py "$CORPUS" --oemr --f3-geometric \
    > ab_f3.txt 2>&1
# 或等价地用环境变量：
#   PUDU_F3_GEOMETRIC=1 python tools/omr_eval_groundtruth.py "$CORPUS" --oemr
```

两次运行分别写出 `omr_eval_report.json` / `omr_eval_note_diffs.json(.csv)`；
为避免互相覆盖，建议分目录运行或重命名产物（harness 当前写于 `corpus_dir`，
QA 可复制/改名留存）。

## 3. 对比口径（关注这些维度）

评测报告 `summary.category_pass` 与 `summary.category_distribution` 直接给出各维度独立通过率。
F3 设计靶心是 `pitch_degree` / `pitch_octave`（修复后两者均大幅提升，见顶部结论）：

| 维度 | 含义 | F3 修复后实测（13 页） |
|------|------|------|
| `pitch_degree` | 音级（首调数字） | 失败 649→205（通过率 78.72%→93.44%） |
| `pitch_octave` | 八度点 | 失败 868→59（通过率 71.54%→98.11%） |
| `pitch_accidental` | 变音记号 | 失败 138→950（方案A↔F3 交互 bug，已修）→修复后 **87** |
| `rhythm` / `rest` / `chord` / `tie` | 时值/休止/和弦/延音 | 基本不变（F3 不动这些字段） |
| `note_pass_rate` | 联立通过率 | 35.70%→49.81%（+14.11pp） |

回归门禁建议：
- `pitch_octave` 失败数（B 组）< 150（修复后 59，给回归余量）；
- `note_pass_rate`（B 组）≥ 45%（修复后 49.81%）；

## 4. 逐音符 diff 账本核对（可选）

`omr_eval_note_diffs.csv` 每行含 `exp_step/exp_octave/exp_alter` 与
`act_step/act_octave/act_alter` 及 `failed_categories`。可按 `failed_categories`
含 `pitch_degree` / `pitch_octave` 过滤，直接对照 A/B 两组的 `act_*` 变化：
修复后 B 组的 `act_*` 覆盖全页音符的 step/octave（F3 重算），且 pitch_octave 失败数
从 868 降到 59（见顶部结论）。`pitch_accidental` 失败在方案A↔F3 交互 bug 修复后从 950
降到 87（见顶部结论），残余多为 F3 几何 step/octave 尚未到位页面的连带误差
（如 bach_p2/prelude_p2），非索引错位产物。

## 5. 已知约束 / 风险（与 system_design.md §9 一致）

- **sidecar 必须随 oemer 产出**：B 组命令默认即产出 `.geometry.json`（除非显式
  `--no-f3-sidecar`，那样 F3 无几何数据可用，会跳过并告警）。A 组默认也产出 sidecar，
  但无害（仅多一个文件）。
- **退化 B 计划**：谱表 `lines != 5` 或谱号非 G/F 或 cy 测量可疑（|几何 pos − oemer 原猜|
  > 16 半音级）时，F3 退化为「只读不改」，保 oemer 原值（非致命）。修复后语料
  **0 音符因谱表/谱号退化跳过**（`_nearest_staff_by_y` 按 track/group 精确命中原谱表，
  cy 与 oemer 原猜一致），仅有 `bach-cello-suite-no-1-for-violin_p3` 因缺 sidecar 跳过
  （oemer 未产出几何数据，非 F3 可控）。
- **不重新识别谱号**：F3 只读 sidecar 里的 oemer 谱号作映射输入（Q3 已拍板）。
- **昂贵 GPU 评测不在本工程范围**：本说明仅描述如何接入；实际大规模语料跑评测由 QA 完成。
