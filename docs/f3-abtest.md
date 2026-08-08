# F3 几何感知音高校正器 · A/B 评测接入说明

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
> `pitch_accidental` 失败 138→950 为**对齐暴露**的既有 oemer alter 错（NW 以音高为锚，
> 修复八度后音符对到真正 gt 伙伴，暴露原本被错误八度掩盖的 alter 误差；F3 逐字节不碰
> `<alter>`，已验证 0 改动）。F3 + postcorrect 无叠加（49.81%→49.81%）。

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
| `pitch_accidental` | 变音记号 | 失败 138→950：**对齐暴露**既有 oemer alter 错（F3 不碰 alter，验证 0 改动） |
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
从 868 降到 59（见顶部结论）。`pitch_accidental` 失败多为 A/B 两组 `act_alter` **相同**
但 `expected_alter` 不同——即对齐伙伴因八度修复而改变，暴露既有 alter 误差。

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
