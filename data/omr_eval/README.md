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
