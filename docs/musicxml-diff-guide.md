# MusicXML 差异检测工具 · 使用教程

> 工具：`tools/omr_musicxml_diff.py`
> 用途：直接对比两个 MusicXML（**识别输出 pred** vs **样本/GT**），在 MusicXML 字段层报告差异。
> 依赖：纯 Python stdlib（`xml.etree` / `argparse` / `json`）+ 复用 `omr_eval_lib` 对齐内核。
> 不依赖 Pudu.exe / oemer / music21 / Java。

---

## 1. 它是做什么的

给定两个 MusicXML 文件，本工具在 **MusicXML 字段层**逐音符对比并报告差异：

- 文档级：调号 `key`（fifths）、拍号 `time_signature`
- 音符级：音高 `pitch`（step / alter / octave / midi）、时值 `rhythm`（duration→quarterLength + type）、
  休止符 `rest`、装饰音 `grace`、和弦 `chord`、延音线 `tie`（start/stop 两端）
- 未配对音符：`event_count`（单列，不计入通过率分母）

### 与现有评测的区别（互补，不重复）

| | 简谱层评测（`omr_eval_groundtruth.py`） | **本工具（MusicXML 层）** |
|---|---|---|
| 输入 | 图片 + GT | 两个 MusicXML |
| 投影 | Pudu.exe → 简谱 JSON | 直接解析 MusicXML |
| 比什么 | degree / octaveDots / underlines | pitch / qlen / type / rest / tie… |
| 测什么 | Pudu 投影精度 | MusicXML 一等输出精度 |

一句话：**想看 AV/oemer 识别出的 MusicXML 和"标准答案"差在哪，用本工具；**想看 Pudu 把 MusicXML 转简谱投影准不准，用 `omr_eval_groundtruth.py`。

---

## 2. 基本用法

```bash
# 用仓库 venv 的 python 调用（路径按你环境改）
C:/Users/13157/.workbuddy/binaries/python/envs/default/Scripts/python.exe tools/omr_musicxml_diff.py \
    build/_av_eval13/canon-in-d-violin-solo_p1.pred.musicxml \
    build/_av_eval13/canon-in-d-violin-solo_p1.gt.musicxml
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `pred_musicxml` | ✅ | 识别输出的 MusicXML（AV/oemer 产物） |
| `gt_musicxml` | ✅ | 样本/GT 的 MusicXML |
| `--limit N` | 可选 | 差异明细最多显示 N 条（缺省全部） |
| `--json OUT` | 可选 | 把机器可读账本写入 OUT 文件 |

### 退出码

| 码 | 含义 |
|---|---|
| `0` | 正常完成（**有差异 ≠ 失败**，工具是检测差异） |
| `1` | 文件不存在 / 解析失败 / 参数错误 |

---

## 3. 输出解读

以 canon_p1 为例（AV 识别输出 vs GT）：

```
============================================================
pred: build/_av_eval13/canon-in-d-violin-solo_p1.pred.musicxml
gt  : build/_av_eval13/canon-in-d-violin-solo_p1.gt.musicxml
============================================================
音符比对: 262  全对: 260  note_pass: 99.24%        ← 联立通过率：262 个配对音符里 260 个所有维度全对
字段比对: 2332  失败: 7  field_pass: 99.70%        ← 字段级通过率：所有被校验字段（音高/时值/tie 等逐项计）
逐维通过率: chord=100.0%  grace=100.0%  pitch=99.62%  rest=100.0%  rhythm=99.24%  tie=100.0%
类别分布: pitch=3  rhythm=2  event_count=2
--- 差异明细（共 7 条，显示前 5 条）---
  [rhythm] part=P1 measure=11 qlen: gt=0.25 pred=0.375
  [pitch] part=P1 measure=11 step: gt=C pred=D
  [pitch] part=P1 measure=11 alter: gt=1 pred=0
  [pitch] part=P1 measure=11 midi: gt=61 pred=62
  [rhythm] part=P1 measure=11 qlen: gt=0.25 pred=0.375
```

**字段速查：**

| 输出行 | 含义 |
|---|---|
| `音符比对` | 对齐后的配对音符总数（NW 对齐，容增删） |
| `全对` / `note_pass` | 所有被计类别同时正确的音符数及百分比 |
| `字段比对` / `field_pass` | 逐字段校验（一个音符可能多个字段失败），字段级通过率 |
| `逐维通过率` | 每个类别的独立通过率（与 note_pass 互补，看各自短板） |
| `类别分布` | 各类别失败次数（`event_count` 单列、不进分母） |
| 差异明细 | 每条 `[类别] part 小节 字段: gt=期望 pred=实际` |

**差异明细字段：**
- `[rhythm] qlen: gt=0.25 pred=0.375` —— 该音符 GT 是十六分音符（0.25 拍），pred 识别成附点十六分（0.375）
- `[pitch] step: gt=C pred=D` —— GT 是 C，pred 识别成 D（同小节常伴随 `alter`、`midi` 差异，属同一音高错）
- `[event_count] gt-only` —— 该音符 GT 有、pred 漏检（未配对，NW 对齐后的剩余）

---

## 4. 常见场景

### 4.1 快速对比一个识别结果和 GT
```bash
py tools/omr_musicxml_diff.py build/_av_eval13/summer-third-movement_p2.pred.musicxml \
    build/_av_eval13/summer-third-movement_p2.gt.musicxml --limit 30
```

### 4.2 只关心类别分布（看全貌，不看明细）
```bash
py tools/omr_musicxml_diff.py a.pred.musicxml b.gt.musicxml --limit 0
```
`--limit 0` 不显示差异明细，只看汇总区。

### 4.3 生成机器可读账本，供脚本/CI 消费
```bash
py tools/omr_musicxml_diff.py a.pred.musicxml b.gt.musicxml --json build/diff.json
```
`diff.json` 结构（顶层键）：
```
pred_musicxml / gt_musicxml
notes_compared / notes_correct / note_pass
field_checked / field_failed / field_pass
category_counts / category_note_fail / category_pass
diffs    ← [{part, measure, field, expected, actual, category}, ...]
```

### 4.4 对比不同引擎的输出（AV vs oemer，都不是 GT）
两个参数都是 pred 也完全合法——工具只比字段，不关心谁是"标准"：
```bash
py tools/omr_musicxml_diff.py build/_av_eval13/x.pred.musicxml oemer_out/x.musicxml
```

### 4.5 检查多个对（循环）
```bash
for f in build/_av_eval13/*.pred.musicxml; do
  gt="${f%.pred.musicxml}.gt.musicxml"
  [ -f "$gt" ] && py tools/omr_musicxml_diff.py "$f" "$gt" --limit 0 | grep -E "note_pass|field_pass"
done
```

---

## 5. 内置评测语料（冒烟用）

| 路径 | 内容 |
|---|---|
| `build/_av_eval13/*.pred.musicxml` | Audiveris 识别输出（14 个） |
| `build/_av_eval13/*.gt.musicxml` | 同 base 的 GT（优先） |
| `data/omr_eval/real/mvp_2026Q3/`、`rerun_2026Q3/` | GT 备份目录 |

> ⚠️ `build/` 已被 `.gitignore` 忽略。`tests/test_omr_musicxml_diff.py` 里的真实语料冒烟
> 用 `@skipUnless(os.path.isdir(...))` 守卫——语料缺失时自动跳过，不报错。

---

## 6. 实现要点与边界（读源码前先看这里）

- **对齐**：不能按小节号硬对齐（实测 bach_p1 GT 20 小节 vs pred 18）。复用
  `omr_eval_lib._nw_align`（Needleman–Wunsch 全局保序，容增删），midi 作唯一音高锚；
  未配对音符记为 `event_count`。
- **跳过 `<mode>`**：Audiveris 的 `<key>` 只写 `<fifths>` 不写 `<mode>`，文档级比对
  跳过 mode 避免全页假阳。
- **divisions 按小节继承**：小节无 `<attributes>` 时沿用上一小节（缺省 8）。
- **类别词表与简谱层区分**：本工具用 `pitch`（含 step/alter/octave/midi 字段），
  简谱层用 `pitch_degree`/`pitch_octave`/`underlines`。**不要混用两个词表。**
- 单元测试：`tests/test_omr_musicxml_diff.py`（25 个，含真实语料冒烟）。

---

## 7. 回归验证

```bash
C:/Users/13157/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pytest \
    tests/test_omr_musicxml_diff.py tests/test_omr_audiveris.py \
    tests/test_omr_eval_groundtruth_wiring.py tests/test_cpp_preprocess_switch.py -q
```
预期：全部通过（红线 `test_cpp_preprocess_switch` 不受影响——本工具只加 Python 文件，
不碰 C++ / FROZEN 三件套）。
