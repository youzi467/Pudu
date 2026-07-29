# F3 几何感知音高校正器 · A/B 评测接入说明

> 配套：`tools/omr_eval_groundtruth.py`（已透传 `--f3-geometric`）、
> `tools/omr_oemer.py`（F3 开关与 sidecar）、`docs/system_design.md` §6 T05。
> 本说明面向 QA：如何用现有 harness 做 F3 的 on/off A/B 量化。
> **工程侧仅做开关透传，不实际跑昂贵的 oemer GPU 评测**（那是 QA 的活）。
>
> ⚠️ **全量 A/B 实测结论（oemer 0.1.8，6 页真实语料）**：F3 开/关（ON==OFF）输出**逐字节相同**，`summary.category_pass` 全维度一致（pitch_octave 46.08% 等），41 个 Python 单测全绿。**F3 对 oemer 0.1.8 零效果**，保留为实验性基础设施、默认 OFF、不作音准改进上线。下文「预期/量化断言」为最初假设，已被本次 A/B 证伪，仅作历史对照。

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
F3 设计靶心本是 `pitch_degree` / `pitch_octave`（下文的「预期」为最初假设，已被全量 A/B 证伪，见顶部结论），顺带观察：

| 维度 | 含义 | F3 预期（最初假设，已证伪） | 全量 A/B 实测 |
|------|------|------|------|
| `pitch_degree` | 音级（首调数字） | 主提升项（修正 argmin/round 偏置导致的 off-by-one） | **无变化**（ON==OFF 逐字节相同） |
| `pitch_octave` | 八度点 | 主提升项（修正加线整八度误计；`octave_jump` 应下降） | **无变化**（category_pass 全维度一致，含 octave_jump） |
| `pitch_accidental` | 变音记号 | 不应回退（F3 不碰 alter；方案A 负责） | 不变（F3 不碰 alter） |
| `rhythm` / `rest` / `chord` / `tie` | 时值/休止/和弦/延音 | **不变**（F3 不动这些字段） | 不变 |
| `note_pass_rate` | 联立通过率 | 随 pitch_degree/octave 提升而提升 | **无变化**（OFF==ON 全维度一致） |

量化断言（最初假设，供 QA 写回归门禁；实测已被证伪）：
- ~~`pitch_degree` 与 `pitch_octave` 的 `category_pass`（B 组） ≥ （A 组）~~ → 实测 B==A（ON==OFF 逐字节相同）；
- `pitch_accidental` / `rhythm` / `rest` / `chord` / `tie` 的 `category_pass`（B 组） ==
  （A 组）（F3 不碰这些字段，实测成立）；
- ~~`note_pass_rate`（B 组） > （A 组）~~ → 实测 B==A。

## 4. 逐音符 diff 账本核对（可选）

`omr_eval_note_diffs.csv` 每行含 `exp_step/exp_octave/exp_alter` 与
`act_step/act_octave/act_alter` 及 `failed_categories`。可按 `failed_categories`
含 `pitch_degree` / `pitch_octave` 过滤，直接对照 A/B 两组的 `act_*` 变化，确认
（**全量 A/B 实测：A/B 两组 `act_*` 完全一致，OFF==ON 逐字节相同，F3 未改变 oemer 输出、无修正收益**）。

## 5. 已知约束 / 风险（与 system_design.md §9 一致）

- **sidecar 必须随 oemer 产出**：B 组命令默认即产出 `.geometry.json`（除非显式
  `--no-f3-sidecar`，那样 F3 无几何数据可用，会跳过并告警）。A 组默认也产出 sidecar，
  但无害（仅多一个文件）。
- **退化 B 计划**：谱表 `lines != 5` 或谱号非 G/F 或 cy 测量可疑（|几何 pos − oemer 原猜|
  > 16 半音级）时，F3 退化为「只读不改」，保 oemer 原值（非致命）。A/B 中这类音符不计入
  F3 未产生修正收益（全量 A/B 中 OFF==ON 无差异，退化兜底逻辑未触发实际修正），属预期行为。
- **不重新识别谱号**：F3 只读 sidecar 里的 oemer 谱号作映射输入（Q3 已拍板）。
- **昂贵 GPU 评测不在本工程范围**：本说明仅描述如何接入；实际大规模语料跑评测由 QA 完成。
