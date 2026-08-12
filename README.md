# 谱渡 Pudu

五线谱与简谱互转工具（MVP 阶段）。

> 当前状态（2026-07-17）：已实现 **MusicXML ⇄ 简谱** 双向转换（阶段 2 + 阶段 3，MVP 达成），支持纯文本(L1)、二维 HTML(L2)、结构化 JSON(L3)，并通过 music21 跨语言 100% 校验。OMR 识别（阶段 1）已完成黑盒集成（oemer 接入 + 评测 harness + Plan A 调号后处理 + H2 分维指标），真引擎已在本机端到端跑通；**P1-1 后处理音乐规则引擎已交付并本地真机验收（2026-08-01）：150/150 用例全绿，含 7 份出版级 GT 谱 no-op 红线回归**。

## 阶段与里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| 阶段 0 | 环境与 MusicXML 解析基础 | ✅ 完成 |
| 阶段 1 | OMR 黑盒集成（PDF/JPG → MusicXML） | ✅ 完成（M2：oemer 黑盒接入 + 评测 harness + Plan A 调号后处理 + H2 分维指标） |
| 阶段 2 | 五线谱 → 简谱核心（MVP v1） | ✅ 完成（已打标签 `phase-2`） |
| 阶段 3 | 简谱 → 五线谱（反向） | ✅ 完成（phase-3 / 3.1 / 3.2，双脑转换闭环） |
| 阶段 4 | AI / 深度学习进阶 | ⬜ 未开始 |
| 阶段 5 | 工程化与 GUI | ⬜ 未开始 |

> 整体规划与 5 阶段路线见 `omr-tool-research/results/research_report.md`；阶段 3 具体行动计划见 `stage3_action_plan.md`。

## 功能概览（阶段 2 + 阶段 3）

- **输入**：MusicXML 文件（`data/*.musicxml`，仅接受未压缩的 `score-partwise`；`.mxl` 压缩包被显式拒绝，需另存为 `.musicxml`）。
- **转换** `staffToJianpu`：
  - 首调（movable-do）音级映射：`1` = 主音，按调号定位；调外音用临时升降记号。
  - 调号 / 调式 / 拍号识别；八度点（高低八度）；时值（增时线 / 减时线 / 附点）。
  - 多声部分行；休止、和弦、装饰音、延音线、连音组（`<time-modification>`）标注。
- **三种简谱呈现**：
  - **L1 纯文本**（`--to-jianpu`）：命令行核对用。
  - **L2 二维 HTML/Unicode**（`--to-jianpu-l2 [out.html]`）：自包含、可直接浏览器打开，含真实八度点、减时线横向连写、增时线、和弦列、连音弧。
  - **L3 结构化 JSON**（`--to-jianpu-json [out.json]`）：无损，供 `verify_jianpu_groundtruth.py` 逐音比对。
- **P1-1 后处理音乐规则引擎（`--apply-postcorrect`，默认关闭）**：挂接在 `staffToJianpu` 之后的**确定性音乐规则引擎**，对 OMR 常见错误做「高置信自修 / 低置信标记」，产出可审计的 `applied`/`flagged` 轨迹。
  - 开关：`--apply-postcorrect`（**默认关闭，需显式开启**）；`--postcorrect-report <path>` 将审计报告 JSON 写出（含每条 `applied`/`flagged` 详情）。
  - 五类规则：`BeatReconcile`（小节节拍对账，**唯一带积极自修**的规则）、`Accidental`（临时记号与调号一致性）、`OctaveDot`（八度点自洽与异常跳变）、`TupletGroup`（连音组完整性）、`RestFill`（占拍缺失标记，**绝不臆造音符**）。
  - **核心不变量：对干净输入必须 0 修正（no-op）**。已由 7 份出版级 ground-truth 乐谱（Bach Partita BWV1004 / Cello Suite BWV1007 / Vivaldi a 小调协奏曲 / Badinerie / Paganini Caprice 24 / Canon in D / Summer 3rd mvt）的语料级回归测试守护，断言 `applied` 与 `flagged` 皆空。
  - 已知边界（诚实交代）：
    - 多声部（`doc.lines.size() > 1`）文档整条跳过 `BeatReconcile` —— 因 `<forward>/<backup>` 不物化休止，稀疏声部小节天然不满拍，target 不可信。
    - `implicit`（不完全/续接）小节跳过。
    - 无法修复 `pitch_degree`（音名）错误 —— 转换后绝对音高已坍缩为首调音级，规则引擎看不到原始 step 名。
- **变调重算（阶段 2 边界补全 / 阶段 3 前置）**：
  - 在任一 `--to-jianpu*` 前追加 `--key <调名>`（移调）、`--rekey <调名>`（改写调号）、`--transpose <±半音>`（字面移调）。
  - 单一事实源 = canonical Score：变调在 Score 上平移音高（或仅改调号）后复用既有转换器，保证 L0↔Score 自洽，满足阶段 3 往返（G3）音高守恒前提。
  - `include/transpose.hpp` + `src/transpose.cpp`，纯函数 `parseKeyName` / `tonicNameToFifths` / `semitonesToFifths` / `transposeScore` 独立可单测。
- **阶段 3 反向转换（简谱 → 五线谱）`jianpuToStaff` + `scoreToMusicXML`**：
  - `jianpuToStaff(JianpuDoc) -> Score`：音级→绝对音高（逆 `midiToJianpu`，复用 `midiToPitch` 保证拼写口径一致）、八度点→octave、时值→`type`+`duration`（与 `typeToDuration` 严格互逆）、调号/拍号→`ScoreAttributes`、多声部按 `partIndex`/`voice` 还原、休止/和弦/装饰音/延音线映射回 `Note`。
  - `scoreToMusicXML(Score) -> .musicxml`：pugixml 写出 `score-partwise`；多声部用 `<backup>/<forward>` 还原并行时序、和弦用 `<chord/>`；写出的文件可被本仓库解析器读回且语义等价（G2 自洽测试）。
  - CLI `--to-musicxml [out.musicxml]`：演示「五线→简→五线」双向闭环，可叠加 `--key/--rekey/--transpose`。
  - 和弦逐音独立八度点已支持（M1.5-A：反向精确还原）；`tieStop` 反向还原已支持（M1.5-B）。
- **阶段 1 OMR 黑盒集成（`--from-omr`，M2）**：
  - `omr_adapter` 子进程分派 **audiveris（默认，`--omr-engine audiveris`）** / fixture（确定性，ctest 用）/**oemer（回退，`--omr-engine oemer`）**；产出 MusicXML 喂入既有 `MusicXMLParser → staffToJianpu` 流水线，端到端出简谱。
  - **Audiveris 默认引擎（2026-08-12 迁移落地）**：`tools/omr_audiveris.py` 调 `Audiveris.exe -batch -export`（自带 JRE），图像 glyph 检测 keysig/拍号/时值，支持多页 PDF 逐页拼接；基线 **97.56%**（13 共有页，见 docs/audiveris-ab-verdict.md）。
  - 评测 harness `tools/omr_eval_groundtruth.py` 量化引擎→简谱 误差分布（`run_oemer` / `run_audiveris` 双入口 + H2 分维指标）；真实 AV / oemer 路径均已本机端到端跑通。
- **P0-2 前置图像预处理增强（`--omr-preprocess`，默认关闭，仅 oemer 回退路径适用）**：
  - 在 oemer 识别**之前**插入一层 Python + OpenCV 图像增强（阴影抑制 → CLAHE 对比度归一 → 中值去噪 → 小角度纠偏 → 边框裁切 → 自适应/Otsu 二值化 → 缩放），改善**拍照/扫描/低对比度/轻微倾斜/带阴影**谱面的识别鲁棒性。Audiveris 引擎（默认）走 AV 自带预处理，不适用本开关。
  - **默认关闭，且是 no-op 红线**：不加该开关时 `runOmr` 仍直接调用 `tools/omr_oemer.py`（oemer 引擎下），子进程命令串与 P0-2 之前**逐字节一致**，不产生任何临时文件、不追加任何参数。
  - 打开后 `runOmr` 改调透明代理 `tools/omr_pipeline.py`——它把增强图写进临时目录再转发给 `omr_oemer.py`，**输出路径按原始输入推导**（与 oemer 口径一致），退出码原样透传；临时目录 `try/finally` + `atexit` 双保险清理（`--keep-temp` 可保留用于排查）。
  - **失败即降级（fail-open）**：OpenCV 缺失、读图失败、任一步异常，均自动回退到原图继续识别，绝不让预处理成为新的失败点。
  - 配置四级优先级：`--preprocess-config` > 环境变量 `PUDU_OMR_PREPROCESS_CONFIG` > `tools/omr_preprocess_config.json` > 代码内 `DEFAULTS`；内置 `default` / `scan` / `photo` / `low_contrast` 四套预设（`--preprocess-preset`）。
  - 每次运行旁写 `<out>.preprocess.json` 指标（schema `pudu.omr.preprocess.metrics/v1`：分步耗时、纠偏角与决策、墨迹占比、降级原因），便于 A/B 与调参。
  - 独立调参入口：`python tools/omr_preprocess.py <in> <out.png> [--preset photo]`，可脱离 C++ 直接查看增强效果。
- **质量保障**：
  - C++ 单元测试 **161 个用例（ctest `PuduTests` 入口全绿；含 P1-1 后处理规则引擎 33 例，Bug B/C 等扩展后由早期 117 → 161）+ 41 个 F3 Python 单测**全绿（header-only 自研测试框架，零外部依赖）。
  - music21 跨语言 ground-truth 校验：8/8 样本、音符 **100.0%**（13492/13492）、字段 **100.0%**（79240/79240）、计入类差异 = 0。

## 前置依赖

1. **Visual Studio Build Tools 2022**（已安装）— 勾选“使用 C++ 的桌面开发”。
2. **vcpkg**（已安装，`D:\vcpkg`，`VCPKG_ROOT` 已设）— 提供 `pugixml`。
3. **CMake** ≥ 3.25（已安装）。
4. **VS Code 扩展**：C/C++、CMake Tools（已安装）。

> OpenCV 自研已降级为选做/延后（识别端由 Audiveris/oemer 黑盒承担），MVP 阶段未接入。

## 构建

在 VS Code 中打开本文件夹，`Ctrl+Shift+P` → `CMake: Select Kit` → 选 “Visual Studio Build Tools 2022 Release - amd64”，再 `CMake: Configure` → `CMake: Build`。

或命令行：

```bash
cmake --preset windows-msvc-vcpkg
cmake --build build/windows-msvc-vcpkg --config Debug
```

构建产物：`build/Pudu.exe`（主程序）、`build/PuduTests.exe`（单元测试）。

## 运行

```bash
# 解析并打印 MusicXML 字段 / 音符序列
build/Pudu.exe data/cello-suite-no-1.musicxml

# 输出 L1 纯文本简谱
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu

# 输出 L2 二维 HTML 简谱（默认 jianpu_l2.html，可指定路径）
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu-l2 jianpu_l2_cello.html

# 输出 L3 结构化 JSON（默认 jianpu.json，可指定路径）
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu-json jianpu.json

# 阶段 3 反向闭环：MusicXML -> 简谱 -> 五线谱，写出 .musicxml（演示双向互转）
#   可叠加 --key/--rekey/--transpose 先变调再反向
build/Pudu.exe data/cello-suite-no-1.musicxml --to-musicxml sample_back.musicxml
build/Pudu.exe data/cello-suite-no-1.musicxml --key D --to-musicxml sample_back_D.musicxml

# 变调重算（阶段 2 边界补全 / 阶段 3 前置）：在任一 --to-jianpu* 前追加
#   --key <调名>    移调：实际音高平移，简谱数字不变（如歌手/乐器移调）
#   --rekey <调名>  改写调号：音高不变，数字相对新主音重算
#   --transpose <±半音>  字面移调（如 --transpose +2 整体升大二度）
# 调名支持大小调、升降号(#/b/♯/♭)与 "m"/"minor"/"小调" 后缀，大小写/空白容错。
build/Pudu.exe data/cello-suite-no-1.musicxml --key D --to-jianpu
build/Pudu.exe data/cello-suite-no-1.musicxml --rekey G --to-jianpu-l2 jianpu_l2_G.html
build/Pudu.exe data/cello-suite-no-1.musicxml --transpose -3 --to-jianpu-json jianpu.json

# P1-1 后处理音乐规则引擎：开启确定性自修并写出审计报告
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu --apply-postcorrect --postcorrect-report report.json

# 阶段 1 OMR：图片/PDF -> MusicXML -> 简谱（默认 Audiveris 引擎，需 AV 安装，见 build/_audiveris/）
build/Pudu.exe --from-omr data/score.jpg --to-jianpu
# 指定引擎：--omr-engine audiveris（默认）/ oemer（回退）/ fixture（演示）
build/Pudu.exe --from-omr data/score.pdf --omr-engine audiveris --to-jianpu-l2 out.html
build/Pudu.exe --from-omr data/score.jpg --omr-engine oemer   --to-jianpu
# AV exe 路径可用环境变量 PUDU_AUDIVERIS_EXE 覆盖（默认 build/_audiveris/extract/Audiveris/Audiveris.exe）

# P0-2 前置图像增强（默认关；加上开关才启用，适合拍照/低对比度/轻微倾斜的谱面）
build/Pudu.exe --from-omr data/photo.jpg --omr-preprocess --to-jianpu

# P0-2 独立调参：脱离 C++ 直接看增强效果 / 对比预设
python tools/omr_preprocess.py data/photo.jpg out_photo.png --preset photo
python tools/omr_preprocess.py data/scan.png  out_scan.png  --preset scan
```

> 不带路径参数时，`Pudu.exe` 回退到内嵌「小星星」样例。若提示找不到 `pugixml.dll`，将 vcpkg 的 bin 目录加入 `PATH`：
> ```powershell
> $env:PATH = "D:\vcpkg\installed\x64-windows\bin;" + $env:PATH
> ```

运行单元测试：

```bash
build/PuduTests.exe
```

### 本地网页应用（图片 → 简谱 + MusicXML + 需校对）

面向非开发者用户的浏览器入口（stdlib-only，零新依赖；设计见 `docs/user-side-interface-design.md`）：

```bash
# 启动（仅监听 127.0.0.1:8765；浏览器打开提示的地址即可）
C:/Users/13157/.workbuddy/binaries/python/envs/default/Scripts/python.exe tools/pudu_server.py

# 演示模式全链路秒级出稿（fixture 引擎，零 GPU）：界面右上角切「演示模式」→ 运行演示样例
```

- 上传乐谱图片 / PDF → 简谱 L2 预览（可打印）+ 下载 `final.musicxml`（music21 可读、可再渲染）+ 需校对面板；
- 识别链路 = **Audiveris（默认）→ 节拍校验打标 → L2 渲染**，交付态对齐 AV 基线 97.56%；右上角可切「oemer 回退」（84.5% 口径）或「演示模式」（fixture，秒级、零 GPU）；
- 多页 PDF 由 AV 逐页 `-sheets N` 拼接（坏页单独跳过不拖垮好页）；拍号校验对节拍不符小节打 `<footnote>`「需校对：小节节拍不符」；
- 作业目录 `build/_ui_jobs/`（gitignored）；取消/超时/失败一律显式报错，不留僵尸进程。

运行测试：`.../python.exe -m pytest tests/test_pudu_server.py -q`

## 项目结构

```
Pudu/  (工作区当前磁盘名为 omr/，规划重命名为 Pudu/)
├── CMakeLists.txt              # 构建配置（Pudu + PuduTests 目标）
├── CMakePresets.json           # VS Code / CMake 预设
├── vcpkg.json                  # 第三方依赖声明（pugixml）
├── README.md
├── src/
│   ├── main.cpp                # 入口 + CLI（--to-jianpu* / --to-musicxml / --key / --rekey / --transpose / --from-omr / --omr-preprocess / --from-jianpu-text / --apply-postcorrect）
│   ├── musicxml_parser.cpp     # MusicXML 解析（pugixml）
│   ├── jianpu_converter.cpp    # 阶段2 五线→简谱转换 + L1/L2/L3 渲染
│   ├── jianpu_postcorrect.cpp  # P1-1 后处理规则引擎（5 类规则 + 审计报告 JSON）
│   ├── transpose.cpp           # 变调重算（transposeScore / parseKeyName / midiToPitch / ...）
│   ├── jianpu_to_staff.cpp     # 阶段3 G1：JianpuDoc -> Score
│   ├── jianpu_text_parser.cpp  # 阶段3 G4：简谱 L1 文本 -> JianpuDoc
│   ├── musicxml_serializer.cpp # 阶段3 G2：Score -> MusicXML（scoreToMusicXML）
│   └── omr_adapter.cpp         # 阶段1 OMR 黑盒适配（oemer/fixture/audiveris 子进程分派）
├── include/
│   ├── score_model.hpp         # MusicXML 内存模型（Score/Note/.../Credit）
│   ├── musicxml_parser.hpp     # 解析器接口
│   ├── jianpu_model.hpp        # 阶段2 L0 简谱模型（JianpuDoc/...）
│   ├── jianpu_converter.hpp    # 转换器 API（staffToJianpu / jianpuToL1/L2/Json）
│   ├── jianpu_postcorrect.hpp  # P1-1 后处理 API（correctJianpuDoc / PostCorrectReport）
│   ├── transpose.hpp           # 变调重算 API（含 midiToPitch，阶段3 复用）
│   ├── jianpu_to_staff.hpp     # 阶段3 API（jianpuToStaff / scoreToMusicXML）
│   ├── jianpu_text_parser.hpp  # 阶段3 G4 API（parseJianpuText）
│   └── omr_adapter.hpp         # 阶段1 OMR 适配 API（OmrEngineConfig / runOmr）
├── tools/                      # Python 侧工具链（子进程调用，C++ 不直接依赖）
│   ├── omr_oemer.py            # 阶段1 oemer 识别脚本（P0-2 零改动，回退引擎）
│   ├── omr_audiveris.py        # 阶段1 Audiveris 识别适配层（默认引擎；调 Audiveris.exe -batch，PDF 逐页拼接）
│   ├── omr_pipeline.py         # P0-2 透明代理：预处理后转发 omr_oemer.py（默认不参与链路）
│   ├── omr_preprocess.py       # P0-2 增强核心库 + 独立调参 CLI（cv2 全部惰性导入）
│   ├── omr_preprocess_config.json  # P0-2 默认配置与 4 套预设（default/scan/photo/low_contrast）
│   ├── pudu_server.py          # 阶段5 本地网页应用后端（stdlib-only HTTP + 作业线程）
│   └── pudu_ui.html            # 阶段5 单页前端（上传/进度/简谱预览/MusicXML/需校对，零依赖）
├── test/                       # C++ 单元测试（header-only 自研框架 + 11 测试文件）
├── tests/                      # Python 单元测试（pytest；P0-2 新增 5 文件，不依赖 cv2/numpy）
├── data/                       # 测试 MusicXML 语料（8 份，.gitignore 已排除）
└── omr-tool-research/          # 调研文档（技术选型/架构/规范/校验报告/计划）
    ├── results/research_report.md        # 总路线与 5 阶段规划
    ├── jianpu_output_spec.md             # 阶段2 简谱输出规范
    ├── verify_jianpu_groundtruth.py      # music21 ground-truth 校验器
    ├── jianpu_groundtruth_report.md      # 校验报告（人读）
    └── ...
```

## 已知限制（阶段 2）

- 输入为 MusicXML 文本；PDF/JPG 输入链路（阶段 1 OMR）**已接入**：Audiveris 默认引擎 + oemer 回退 + 评测 harness，详见 `docs/m2-real-run-guide.md`、`docs/audiveris-ab-verdict.md` 与 `data/omr_eval/README.md`。
- 小调「6=X」标法开关未实现（当前小调走首调相对法）。
- 和弦成员逐音独立八度点已支持（M1.5-A）；若简谱未标注逐音八度点，反向按根音上方最近八度还原（音级守恒）。
- L2 连音弧为单音上方 SVG 弧近似；减时线连写按“连续同值”启发式（非真实 beat 分组）。
- 变调段不重算首调（取初始调号）；极端连音比（7:8/7:4/9:4，46 处）单列未校验。

## 下一步

- **阶段 3**：已完成（`jianpuToStaff` + `Score→MusicXML` 序列化 + round-trip 自测）。详见 `stage3_action_plan.md`。
- **阶段 1 OMR**：已完成黑盒集成（**Audiveris 默认引擎 + oemer 回退 + fixture** 引擎 + CLI `--from-omr`），并落地评测 harness（`run_audiveris` / `run_oemer` 双入口、Plan A 调号后处理、H2 分维指标）。**2026-08-12 引擎迁移落地**：Audiveris A/B 在 keysig/时值/小节三项全面胜出（note_pass 84.5% → **97.56%**），AV 升为默认，oemer 保留回退（其 F3 几何校正器对 oemer 0.1.8 零效果已证实，保留为实验性基础设施、不作上线）；详见 `docs/audiveris-ab-verdict.md`、`docs/jianpu-ocr-optimization-plan.md` 与 `docs/m2-real-run-guide.md`。

> [!NOTE]
> **准确性叙事更正（2026-08-06）**：本文此前若暗示"`pitch_degree`（音名）是 oemer 最弱短板、根因是 off-by-one 几何偏置"，该判断已被推翻。`pitch_degree` 13.6%（harness）是评测对齐在节奏漂移时退化为随机配对的**测量假象**，816 个失败音符音级偏移近似均匀分布（非 ±1 集中）；"off-by-one"归因不成立，F3 零效果正因此被解释。真实音名准确率**当前不可认证**（换序列对齐独立复算 step 38.4% / step+octave 25.7%，另 LCS 估计 ~91.6% / ~55%，三法发散证明标尺已坏）。须先修 `_merge_align` 为 Needleman–Wunsch 全局对齐（R1, ~1 人日）才能谈"80% 达标"。"真正短板是八度"属待证假设。详见 `docs/omr-engine-feasibility.md`。
- **阶段 4/5**：AI/深度学习进阶、工程化与 GUI（待启动）。

## 常见问题

### 为什么用 pugixml 而不是 libmusicxml2
`libmusicxml2` 未收录进 vcpkg 官方仓库；MusicXML 本质就是 XML，MVP 只需读写 XML，用轻量的 `pugixml`（MIT）更简单可控。

### `CMake: Select Kit` 不显示
确保打开的是项目根文件夹（含 `CMakeLists.txt`），且底部状态栏无红色错误；可尝试 `CMake: Delete Cache and Reconfigure`。

### 第一次 configure 极慢
vcpkg 需下载并编译 pugixml；网络不稳时可设置 vcpkg 资源镜像或代理后重试。
