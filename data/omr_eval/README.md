# data/omr_eval/ · oemer→简谱 评测语料目录

本目录存放 **oemer 图像识别误差**评测所需的 `(image, gt_musicxml)` 对，
由 `tools/omr_eval_groundtruth.py`（评测基座 P0-1）消费。

> 概念澄清（重要）：Pudu 自身只做 `MusicXML ⇄ 简谱` 的确定性转换（已 100% 准确）。
> 真正的「图像→乐谱」由第三方库 **oemer** 完成，且 oemer 识别的是
> **五线谱图片**（非简谱数字图）。这里的 `image` 是五线谱照片/扫描件，
> `gt_musicxml` 是该谱的 **ground-truth MusicXML**（五线谱）。harness 度量的是
> 「oemer 把五线谱图片识别成 MusicXML 后，再经 Pudu 投影成简谱」与「gt.musicxml
> 直接经 Pudu 投影成简谱」之间的差异分布。

---

## 1. 对配对约定（两种，自动识别）

### 约定 ①：同名约定（推荐，最直观）
在评测目录下放置成对文件：

```
foo.jpg              ← 五线谱图片（oemer 输入）
foo.gt.musicxml      ← 该谱的 ground-truth MusicXML
```

harness 扫描 `*.gt.musicxml`，取其文件名前缀 `foo` 找同名图片 `foo.<ext>`。
支持的图片扩展名：`.jpg .jpeg .png .bmp .tif .tiff .pdf`。

### 约定 ②：manifest.csv（适合批量/路径不规整）
在评测目录下放置 `manifest.csv`，列：`image,gt_musicxml`（表头可选）。
路径可为相对 corpus 目录或绝对路径：

```csv
image,gt_musicxml
scan_001.png,scan_001.gt.musicxml
/data/raw/scan_002.jpg,/data/raw/scan_002.gt.musicxml
```

> 约定 ② 优先于约定 ①。找不到 `gt_musicxml` 时该对会被跳过并告警；
> 约定 ① 下若找不到配对图片且未开 `--no-oemr`，该对跳过（oemer 需要图片）。

---

## 2. 如何跑 harness

环境要求：
- `build/Pudu.exe` 已构建（支持 `--to-jianpu-json`）。
- oemer 运行器 `tools/omr_oemer.py`（需含 CUDA/cuDNN 的 venv 解释器）。
- venv python：`C:\Users\13157\.workbuddy\binaries\python\envs\default\Scripts\python.exe`

### 完整评测（跑 oemer 真引擎）
```bash
<venv_python> tools/omr_eval_groundtruth.py <corpus_dir>
# 等价于显式加 --oemr
```
对每对：`oemer(image) → pred.musicxml` → `Pudu pred.musicxml --to-jianpu-json`
与 `Pudu gt.musicxml --to-jianpu-json` 比对，输出 `note_pass_rate` /
`field_pass_rate` / `category_distribution`，并写出 `omr_eval_report.json`。

### 自验（跳过 oemer，验证比对管线）
```bash
<venv_python> tools/omr_eval_groundtruth.py <corpus_dir> --no-oemr
```
直接用 `gt.musicxml` 同时充当 pred 与 gt（pred 与 gt 同源 → 零差异）。
此时 `note_pass_rate` 必为 **100%**，`category_distribution` 必为 **空**，
证明比对管线本身正确（不依赖 oemer / 不依赖真实样本）。

> 本目录已附 `selfcheck/`：含 2 份 ground-truth（来自 `data/`），可直接
> `python tools/omr_eval_groundtruth.py data/omr_eval/selfcheck --no-oemr` 复现自验。

---

## 3. 输出解读

`omr_eval_report.json` 结构：
```json
{
  "summary": {
    "mode": "oemer | no_oemer_selfcheck",
    "files_total": 0, "files_ok": 0,
    "notes_compared": 0, "notes_correct": 0,
    "note_pass_rate": 0.0,
    "field_checked": 0, "field_failed": 0,
    "field_pass_rate": 0.0,
    "category_distribution": {"pitch_octave": 12, "rhythm": 7, "...": 0},
    "edge_case": {"rests":0,"chords":0,"graces":0,"tuplets":0,"octave_jumps":0},
    "fatal_files": []
  },
  "per_file": [ { "file": "...", "notes_compared": 0, "notes_correct": 0, "diffs": [...], ... } ],
  "flagged_for_postcorrect": [ { "file":"...", "category":"rhythm", "expected":..., "actual":..., "part":0, "measure":3, "index":2 }, ... ]
}
```

错误类别（与 `verify_jianpu_groundtruth.py` 同口径）：
`pitch_degree` / `pitch_accidental` / `pitch_octave` / `rhythm` / `rest` /
`chord` / `grace` / `tie` / `key` / `mode` / `time_signature` / `tuplet` /
`tuplet_rhythm`。（`event_count` / `rhythm_unresolvable` 为单列/未校验类别。）

`flagged_for_postcorrect`：列出属于后处理规则引擎（P1-1）可修正/标记类别
（`rhythm` / `tuplet` / `tuplet_rhythm` / `pitch_octave` / `key` / `mode`）的差异，
供后续「前后对比」量化后处理收益。

---

## 4. 提供真实样本

用户稍后提供一批真实 `(image, gt.musicxml)` 对（五线谱照片/扫描件 + 对应
ground-truth MusicXML），按上述约定①或②放置到任意子目录（如 `data/omr_eval/real/`），
即可跑完整端到端评测：

```bash
<venv_python> tools/omr_eval_groundtruth.py data/omr_eval/real
```

若仅有图片、缺乏人工标注的 ground-truth MusicXML，可先用「合成闭环」思路：
把已知五线谱 MusicXML（如本仓库 `data/` 下 8 份）渲染成图片，再以该 MusicXML
作 gt——但这需 MuseScore/LilyPond/music21 渲染器（当前环境无，故暂跳过
`tools/render_musicxml_to_image.py`，详见方案 §3.3）。

---

## 5. 提交真实样本数据规范（数据 contributor 必读）

本节定义向本评测语料库贡献真实 `(image, gt_musicxml)` 对的完整规范。
遵循本规范可保证样本被 harness 正确消费、可复现、可纳入版本控制。

### 5.1 命名规则

- **图片（oemer 输入）**：`<base>.<ext>`，`<base>` 为不含空格/中文的 ASCII 标识，`<ext>` ∈ {`.jpg` `.jpeg` `.png` `.bmp` `.tif` `.tiff` `.pdf`}。
  例：`river_1.jpg`、`scan_002.png`。
- **Ground-truth MusicXML**：必须与图片**同名前缀 + 固定后缀 `.gt.musicxml`**，即 `<base>.gt.musicxml`。
  例：`river_1.jpg` 的 gt 为 `river_1.gt.musicxml`；`scan_002.png` 的 gt 为 `scan_002.gt.musicxml`。
- **约定 ② manifest**：若图片与 gt 不同目录或批量提交，使用 `manifest.csv`（`image,gt_musicxml` 两列，表头可选），路径可为相对 corpus 目录或绝对路径。manifest 优先于同名约定。
- **禁止**：`<base>.musicxml`（无 `.gt.` 标记会被 harness 误判为普通文件）、中文/空格文件名、大小写混用（`River_1.JPG` 与 `river_1.gt.musicxml` 配对会失败）。

### 5.2 目录结构组织

```
data/omr_eval/
├── README.md                 ← 本文件
├── selfcheck/                ← 内置自验样本（勿改、勿往里加真实样本）
│   ├── badinerie-for-flute-by-js-bach.gt.musicxml
│   └── canon-in-d-violin-solo.gt.musicxml
├── real/                     ← 真实样本区（推荐，可多级子目录）
│   ├── batch_2026Q3/
│   │   ├── river_1.jpg
│   │   ├── river_1.gt.musicxml
│   │   └── manifest.csv       ← 可选
│   └── ...
```

- 真实样本放入 `data/omr_eval/real/`（或任意 `data/omr_eval/` 下的子目录，便于按批次/来源分组）。
- `selfcheck/` 仅用于 CI/自验，保持纯净，真实样本不要放进去。
- harness 递归扫描 corpus 目录，子目录层级不限。
- `.gitignore` 仅忽略 `data/` **根级** `*.musicxml`/`*.png` 等；`data/omr_eval/` 下（含子目录）的图片与 gt 均**可纳入版本控制**。

### 5.3 文件格式标准

**图片**：
- 内容：必须是**五线谱**照片/扫描件（oemer 识别五线谱，不识简谱数字图）。
- 质量：建议扫描分辨率 ≥ 300 DPI；光照均匀、无严重阴影/透视畸变/折痕；谱线清晰、符头不过度粘连。
- 编码：`jpg/png` 主流格式均可；`pdf` 仅限单页乐谱页。
- 大小：单图建议 < 20 MB；过大请先压缩或切分。

**Ground-truth MusicXML (`<base>.gt.musicxml`)**：
- 必须是合法 **MusicXML 3.x**（或 2.x）文档，UTF-8 编码，根元素 `<score-partwise>`。
- 由人工标注或权威打谱软件（MuseScore/LilyPond/Finale）导出，**不是** oemer 识别产物（否则失去「ground-truth」意义）。
- 须与图片为**同一首谱**（音高、时值、调号、拍号一致）。

### 5.4 必填字段说明（gt.musicxml 必须包含）

harness 经 Pudu 投影成简谱后逐音比对，因此 gt 至少需提供以下信息（缺失会导致投影失败或字段不可比）：

| 层级 | 必填字段 | 说明 |
|---|---|---|
| `<score-partwise>` | 根 | 单根乐谱文档 |
| `<part-list>`/`<score-part>` | 至少 1 个声部 | 声部标识 `id` |
| `<measure>` | ≥ 1 小节 | 含音符/休止 |
| `<divisions>` | 必填 | 四分音符分割数，时值换算基准 |
| `<beats>`/`<beat-type>` | 必填 | 拍号（如 4/4 → beats=4, beat-type=4） |
| `<key>`/`<fifths>` | 强烈建议 | 调号（C 大调=0，G 大调=1，F 大调=−1）；缺失则调式判定退化为默认 |
| `<clef>` | 建议 | 谱号（高/低音谱号），影响音高推算 |
| `<note>`（音） | 必填 | `<step>`(CDEFGAB) + `<octave>`(数字) + 时值(`<duration>`+`<type>` 或 `<note>`/`<chord>`) |
| `<note>`（休止） | 允许 | `<rest/>` + 时值 |
| `<time-modification>` | 连音时填 | `<actual-notes>`/`<normal-notes>`（如三连音 3/2） |

> 最小可用 gt：含 1 个 `<part>`、1 个 `<measure>`、1 个带 `<step>+<octave>+<duration>` 的 `<note>`，且设好 `<divisions>` 与拍号。其余字段越全，可比维度越丰富（pitch_octave/rhythm/key/mode 等）。

### 5.5 数据校验规则（提交前必须自测）

1. **gt 可解析**：`build/Pudu.exe <base>.gt.musicxml --to-jianpu-json out.json` 必须退出码 0、无异常、产出合法简谱 JSON。
2. **同名自洽（最强校验）**：把 gt 同时当 pred 与 gt 跑 `--no-oemr`：
   ```
   <venv_python> tools/omr_eval_groundtruth.py <corpus> --no-oemr
   ```
   期望 `note_pass_rate = 100%`、`field_pass_rate = 100%`、`category_distribution = 空`。
   若非 100%，说明 gt 自身无法被 Pudu 投影或与自身比对有歧义 → **样本不合格**，先修 gt。
3. **配对完整**：每个 `*.gt.musicxml` 都有同名图片（约定①）或 manifest 中成对（约定②）；缺失图片的对在 `--oemr` 下会被跳过并告警。
4. **无 fatal 文件**：harness 输出的 `omr_eval_report.json` 中 `summary.fatal_files` 必须为空；非空表示某文件解析崩溃，需修复。
5. **oemer 端到端（可选，需 oemer 环境）**：有 GPU/oemer 环境时跑 `--oemr`，确认 `pred.musicxml` 能生成且 `note_pass_rate` 反映真实误差（非 100% 即正常——那正是要度量的 oemer 误差）。

### 5.6 提交流程（数据 PR）

1. **放置**：按 §5.1/§5.2 把 `(image, gt.musicxml)` 放入 `data/omr_eval/real/<batch>/`。
2. **自测**：跑 §5.5 的 `--no-oemr` 自洽校验，确认 100% 且无 fatal。
3. **（可选）真跑**：有 oemer 环境则跑 `--oemr` 取得真实误差分布，记录到 PR 说明。
4. **暂存（精确，勿用 `git add -A`）**：
   ```
   git add data/omr_eval/real/<batch>/
   ```
   仅暂存本次新增的图片 + gt（+ 可选 manifest）。**不要** `git add -A`（会带入 `data/oemer_out/` 等临时产物与 `__pycache__`）。
5. **提交**：约定式提交，示例：
   ```
   git commit -m "feat(eval): add real OMR corpus <batch> (N pairs)" -m "五线谱图片 + 人工标注 gt.musicxml；--no-oemr 自洽 100%。"
   ```
6. **推送/PR**：`git push` 或开 PR；大批量图片建议评估是否用 Git LFS（避免仓库膨胀）。

> 反例：不要把 oemer 识别产物（`<base>.musicxml` 无 `.gt.`）当 gt 提交；不要提交 `data/oemer_out/`、`*.pkl`、`river_1_jianpu.html` 等运行产物。
