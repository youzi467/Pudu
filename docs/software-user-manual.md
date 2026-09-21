# 谱渡 Pudu 乐谱识别转换软件 用户操作手册

版本：v0.9.0
适用平台：Windows（x64）

---

## 目录

1. 软件简介
2. 运行环境与安装
3. 快速开始
4. 命令行参考（主程序 Pudu.exe）
5. OMR 乐谱识别引擎
6. 简谱输出详解（L1 / L2 / L3）
7. 反向转换与简谱文本输入
8. 本地网页应用
9. 评测与校验工具
10. 常见问题（FAQ）
11. 版权与许可

---

## 1. 软件简介

### 1.1 产品定位

谱渡 Pudu 是一款 Windows 平台「五线谱 ⇄ 简谱互转」工具，核心能力是把乐谱图片或 PDF
通过光学乐谱识别（OMR）转换为 MusicXML，再解析、转换、渲染为简谱，支持多种输出格式；
同时支持从简谱文本反向生成 MusicXML，实现双向转换闭环。

软件由「谱渡（Pudu）」项目团队独立开发完成，属于自研软件，不含第三方闭源代码片段。

### 1.2 功能总览

本软件提供三条主要功能链路：

链路一：OMR 光学乐谱识别（图片 / PDF → MusicXML）

- 支持 PNG、JPG、PDF 等常见格式输入；
- 默认使用 Audiveris 识别引擎，识别失败自动回退 oemer 引擎；
- 支持低分辨率图片自动放大重试、多页 PDF 逐页拼接；
- 输出标准 MusicXML 文件（.musicxml）。

链路二：五线谱 → 简谱（MusicXML → 简谱）

- 解析标准 MusicXML 文件；
- 首调简谱转换，支持纯文本（L1）、二维 HTML（L2）、结构化 JSON（L3）三种输出；
- 支持可选的音乐规则后处理（拍号规整、升降号、八度点、连音组、休止符补全）；
- 支持移调（--key / --rekey / --transpose）。

链路三：简谱 → 五线谱（简谱文本 → MusicXML）

- 解析简谱文本输入（--from-jianpu-text）；
- 反向生成标准 MusicXML 文件（--to-musicxml）；
- 与链路二配合实现五线谱与简谱的双向互转。

### 1.3 附加工具

本软件随附以下工具，均位于 tools/ 目录：

- pudu_server.py + pudu_ui.html：本地网页应用（浏览器上传乐谱 → 识别 → 简谱预览 →
  MusicXML 下载）；桌面端由 desktop_main.py（pywebview 壳）承载同一套前端；
- omr_preprocess.py / omr_pipeline.py：图片预处理增强管道；
- geometric_pitch.py：几何音高与节奏校正（F3 / R-geo，oemer 回退路径）。

> 评测与版权工具（omr_eval_groundtruth.py / omr_musicxml_diff.py / omr_abtest_lib.py /
> gen_copyright_materials.py）已随 2026-08-13 仓库清理**归档至 `to_be_delete/tools/`**
> （评测仅开发使用，版权工具随软著申报暂停而搁置），不随发布包分发。

### 1.4 版本信息

- 软件名称：谱渡 Pudu 乐谱识别转换软件
- 版本号：0.9.0
- 构建方式：C++20（MSVC / utf-8）+ Python 3 工具链（内核）+ pywebview 桌面壳
- 发布形态：绿色免安装 ZIP（pudu-desktop-win64.zip）+ Inno Setup 安装包（PuduSetup-0.9.0-win64.exe）
- 开发完成日期：2026 年 8 月

---

## 2. 运行环境与安装

### 2.1 系统要求

- 操作系统：Windows 10 / 11（x64）
- 内存：4 GB 及以上（OMR 识别建议 8 GB）
- 磁盘：预留 2 GB 空间（含 Audiveris 引擎与 oemer 模型）
- 软件依赖：.NET Framework 4.8（Audiveris 自带 JRE，无需单独安装 Java）

### 2.2 组件清单

| 组件 | 用途 | 必需性 |
| --- | --- | --- |
| Pudu.exe | 主程序（转换内核） | 必需 |
| Audiveris 5.11 | OMR 识别引擎（默认） | 必需（图片/PDF 识别） |
| oemer 0.1.8 | OMR 回退引擎 | 可选 |
| Python 3 + 若干库 | 工具链 | 可选（网页应用/评测） |
| music21 | 校验工具（仅评测时使用） | 可选 |

### 2.3 构建 Pudu.exe

在项目根目录执行：

```
cmake --preset windows-msvc-vcpkg
cmake --build build/windows-msvc-vcpkg --config Debug
```

构建产物位于 build/ 目录：

- build/Pudu.exe：主程序（开发构建）

若运行提示找不到 pugixml.dll，请将 vcpkg 的 bin 目录加入系统 PATH 环境变量。
终端用户无需自行构建——请直接下载发布产物（绿色 ZIP 或安装包，见 §2.5）。

### 2.4 安装 OMR 识别引擎

> 说明：本节为**开发态（源码构建）**指引。发布包（ZIP / 安装包）已内置 Audiveris 引擎
> （随包再分发，附 AGPL-3.0 LICENSE 与源码链接声明），无需另行安装。

Audiveris 引擎（默认）：将 Audiveris.exe 放入以下任一位置即可被自动识别：

- 环境变量 PUDU_AUDIVERIS_EXE 指向的路径；
- 项目 build/_audiveris/extract/Audiveris/Audiveris.exe；
- 系统 PATH 中的 Audiveris.exe。

oemer 引擎（回退）：通过 Python 虚拟环境安装 oemer 0.1.8 及依赖，并确保可通过
Python 解释器导入。本软件对 oemer 运行时打防御补丁（版本锁定 + 校验 + 自动回滚），
无需手工修改其安装文件。**注意：发布包不随带 oemer**，Audiveris 不可用时软件给出
降级提示。

### 2.5 发布形态与安装（终端用户）

本软件提供两种发布形态（GitHub Releases v0.9.0）：

| 形态 | 文件 | 安装方式 |
| --- | --- | --- |
| 绿色免安装版 | pudu-desktop-win64.zip（约 114MB） | 解压后双击 `pudu_desktop.exe` 即可运行 |
| 安装包 | PuduSetup-0.9.0-win64.exe（约 90MB） | 双击安装（per-user，免管理员）；可选创建桌面/开始菜单快捷方式 |

- 两种形态内容一致，均内置 Audiveris 引擎与 Python 运行时（embeddable），**无需安装
  Python / Java / 其他依赖**（WebView2 为 Windows 10/11 自带）；
- 启动后为独立桌面窗口（pywebview 原生窗口），操作方式与网页版一致（见 §8）；
- 日志与作业数据存放于 `%APPDATA%/Pudu/`（desktop.log 1MB 轮转，作业目录 7 天自动清理）；
- 应用图标已内置（EXE 图标 / 安装包图标 / 浏览器标签页 favicon）。

### 2.6 Python 环境（仅开发态）

本软件随附的 Python 工具链要求 Python 3.9+，依赖库包括 numpy、opencv（可选）、
Pillow、music21（仅评测）。未安装 cv2 时预处理功能自动降级，不影响核心转换。
终端用户无需关心本节。

---

## 3. 快速开始

以下示例为**开发态**（已构建 Pudu.exe，当前目录为项目根目录）；终端用户直接使用
发布包桌面端即可，无需命令行。

### 3.1 五线谱 → 简谱（L1 纯文本）

```
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu
```

程序读取 data/cello-suite-no-1.musicxml，输出首调简谱纯文本到命令行。这是最快的
体验方式。不指定任何 --to-* 参数时，默认也输出简谱文本。

### 3.2 五线谱 → 简谱（L2 二维 HTML）

```
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu-l2 jianpu_l2_cello.html
```

生成自包含的 HTML 文件，用浏览器直接打开即可查看二维简谱（含八度点、减时线横向连写、
增时线、和弦列、连音弧），并可直接打印。

### 3.3 五线谱 → 简谱（L3 结构化 JSON）

```
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu-json jianpu.json
```

生成无损的结构化 JSON，供程序化比对与二次处理。

### 3.4 简谱 → 五线谱（反向转换）

```
build/Pudu.exe data/cello-suite-no-1.musicxml --to-musicxml sample_back.musicxml
```

把 MusicXML 转换为简谱语义后，再反向序列化为 MusicXML，验证双向闭环。

### 3.5 图片 → MusicXML（OMR 识别）

```
build/Pudu.exe --from-omr data/score.jpg --to-jianpu
```

识别乐谱图片并输出简谱。识别过程默认使用 Audiveris 引擎。

```
build/Pudu.exe --from-omr data/score.pdf --omr-engine audiveris --to-jianpu-l2 out.html
```

识别 PDF 乐谱，输出二维简谱 HTML。

### 3.6 网页应用快速体验

```
C:/Users/13157/.workbuddy/binaries/python/envs/default/Scripts/python.exe tools/pudu_server.py
```

浏览器访问 http://127.0.0.1:8765，即可上传乐谱图片/PDF、在线识别并预览简谱。

---

## 4. 命令行参考（主程序 Pudu.exe）

### 4.1 参数总表

| 参数 | 说明 |
| --- | --- |
| 无参数 | 使用内嵌样例（「小星星」）演示简谱转换 |
| 输入文件 | 作为第一个位置参数传入 MusicXML 或（配合 --from-omr）图片/PDF |
| --to-jianpu | L1 纯文本简谱输出 |
| --to-jianpu-l2 [out.html] | L2 二维 HTML 简谱输出 |
| --to-jianpu-json [out.json] | L3 结构化 JSON 简谱输出 |
| --to-musicxml [out.musicxml] | 反向输出 MusicXML |
| --from-omr <input> | 启用 OMR 识别，输入为图片/PDF |
| --omr-engine <引擎> | 选择识别引擎：audiveris / oemer / fixture |
| --omr-python <path> | 指定 oemer 使用的 Python 解释器 |
| --omr-preprocess | 打开识别前图像增强（默认关） |
| --key <调名> | 移调（改音高不改调号） |
| --rekey <调名> | 改写调号 |
| --transpose <±半音> | 字面移调 |
| --from-jianpu-text <path> | 从简谱文本文件输入 |
| --divisions N | 反向生成的 divisions（1..16，默认 4） |
| --apply-postcorrect | 应用后处理音乐规则引擎 |
| --postcorrect-report <path> | 输出后处理审计报告 JSON |
| --debug | 追加在最后，开启调试输出 |

### 4.2 输入参数详解

- 无参数：程序加载内嵌「小星星」示例乐谱，便于快速试用与自测。
- 位置参数（MusicXML）：如 data/cello-suite-no-1.musicxml，指定五线谱输入。
- --from-omr <input>：指定待识别图像或 PDF。此时主程序调用 OMR 适配层，先识别为
  MusicXML，再进入转换链路。识别引擎由 --omr-engine 决定。
- --from-jianpu-text <path>：指定简谱文本文件。读取并解析简谱，供 --to-musicxml
  反向输出使用。与 MusicXML 输入互斥，共用同一输出出口。
- --divisions N：控制反向生成的 MusicXML 每四分音符的 divisions（1..16，默认 4）。

### 4.3 输出参数详解

- --to-jianpu：在命令行输出 L1 纯文本简谱。适合快速核对。
- --to-jianpu-l2 [out.html]：输出自包含 HTML（二维简谱）。未给路径时使用默认文件名。
- --to-jianpu-json [out.json]：输出结构化 JSON（无损语义）。
- --to-musicxml [out.musicxml]：输出反向生成的 MusicXML。未给路径时使用默认文件名。
- --apply-postcorrect：在转换后挂载音乐规则后处理引擎。
- --postcorrect-report <path>：把后处理的 applied / flagged 审计轨迹写入 JSON。

### 4.4 变调重算

本软件支持三种变调方式，三者在任一 --to-jianpu* 输出前追加即可，互斥使用：

```
build/Pudu.exe data/cello-suite-no-1.musicxml --key D --to-jianpu
build/Pudu.exe data/cello-suite-no-1.musicxml --rekey G --to-jianpu-l2 jianpu_l2_G.html
build/Pudu.exe data/cello-suite-no-1.musicxml --transpose -3 --to-jianpu-json jianpu.json
```

- --key <调名>：把整曲移调至指定调（如 D 大调），同时更新调号。
- --rekey <调名>：仅改写调号，不改动音符本身。
- --transpose <±半音>：按指定半音数整体移调（支持负数）。

三种方式也可与 --to-musicxml 组合，输出移调后的 MusicXML：

```
build/Pudu.exe data/cello-suite-no-1.musicxml --key D --to-musicxml sample_back_D.musicxml
```

### 4.5 后处理音乐规则引擎

本软件内置 P1-1 后处理规则引擎，包含 5 类确定性音乐规则：

1. BeatReconcile：按拍号规整小节内节拍；
2. Accidental：升降号规整；
3. OctaveDot：八度点合理性校正；
4. TupletGroup：连音组规整；
5. RestFill：休止符补全。

启用方法与审计：

```
build/Pudu.exe data/cello-suite-no-1.musicxml --to-jianpu --apply-postcorrect --postcorrect-report report.json
```

规则引擎对干净输入保持「零修正」的 no-op 行为；对可疑输入产出可审计的
applied（已修正）与 flagged（已标记）轨迹，写入 --postcorrect-report 指定的 JSON。

### 4.6 调试参数

- --debug：置于命令行末尾，开启调试信息输出。

---

## 5. OMR 乐谱识别引擎

### 5.1 引擎选择与切换

本软件支持三种识别引擎，通过 --omr-engine 指定：

| 引擎 | 说明 | 适用场景 |
| --- | --- | --- |
| audiveris | 默认引擎，识别精度最高 | 日常使用 |
| oemer | 回退引擎 | audiveris 不可用时 |
| fixture | 调试用固定输出 | 开发者调试链路 |

示例：

```
build/Pudu.exe --from-omr data/score.jpg --omr-engine audiveris --to-jianpu
build/Pudu.exe --from-omr data/score.jpg --omr-engine oemer --to-jianpu
```

### 5.2 Audiveris 默认引擎

Audiveris 为默认识别引擎，具备以下能力：

- 图像与 PDF 识别，输出标准 MusicXML；
- 低分辨率图片自动放大重试（见 5.4）；
- 多页 PDF 逐页识别与拼接（见 5.5）；
- 拍号校验与「需校对」标记。

### 5.3 oemer 回退引擎

当 Audiveris 不可用或识别失败时，可切换到 oemer 引擎：

- 通过 --omr-python 指定 oemer 使用的 Python 解释器；
- 识别过程中自动应用几何音高校正（F3）与节奏几何校正（R-geo）；
- 自动注入拍号并保守重切小节；
- 对 oemer 运行时打防御补丁，防止空数组 / 退化段导致的崩溃。

### 5.4 低分辨率自动放大

当输入图片分辨率过低（五线谱行距过小）导致识别失败时，软件自动使用 LANCZOS
算法将图片放大 2 倍后重试；仍失败则放大 3 倍再次重试。此过程对用户透明，
成功时会在日志中提示「低分辨率检测，N 倍放大重试成功」。

### 5.5 PDF 多页处理

对多页 PDF，软件逐页调用识别引擎（-sheets N 模式）。某页识别失败时单独跳过，
不影响其余页面；成功页按顺序拼接为连续小节编号的 MusicXML，并处理 divisions
一致性。

### 5.6 图像预处理（--omr-preprocess）

可选的识别前图像增强管道，包括：

- 阴影抑制
- CLAHE 对比度增强
- 去噪
- 纠偏（旋转校正）
- 裁切
- 二值化
- 缩放

开启方式：

```
build/Pudu.exe --from-omr data/photo.jpg --omr-preprocess --to-jianpu
```

每次运行在输出旁生成 <out>.preprocess.json 指标文件，记录分步耗时、纠偏角与
决策、墨迹占比、降级原因，便于调参与 A/B 对比。

---

## 6. 简谱输出详解（L1 / L2 / L3）

### 6.1 L1 纯文本格式

L1 为命令行纯文本简谱，用于快速核对。示例：

```
1=D 4/4
1 2 3 4 5 6 7 1'
```

说明：1-7 表示音阶唱名，上标点表示高八度，下标点表示低八度，横线表示时值
（减时线/增时线），数字后圆点表示附点等。具体符号约定以软件输出为准。

### 6.2 L2 二维 HTML / Unicode

L2 输出自包含 HTML 文件，用浏览器打开即可查看：

- 真实八度点（上/下标点）
- 减时线横向连写
- 增时线
- 和弦列
- 连音弧

L2 适合直接阅读与打印，也是向非技术用户展示的推荐格式。

### 6.3 L3 结构化 JSON

L3 输出无损的结构化 JSON，保留简谱全部语义字段，供程序化比对与二次处理。
评测工具（omr_eval_groundtruth.py，已归档 `to_be_delete/tools/`）即基于 L3 JSON 与
标准答案逐音比对。

---

## 7. 反向转换与简谱文本输入

### 7.1 简谱文本输入

本软件支持从简谱文本文件反向生成五线谱 MusicXML（「简谱 → 五线谱」数据链）：

```
build/Pudu.exe --from-jianpu-text jianpu.txt --to-musicxml out.musicxml
```

简谱文本按软件约定格式书写，由三种行组成：

1. **标题行**（可选）：任意非空文本，作为 MusicXML 的 `<movement-title>`；
2. **调号头行**：`1=<调名> [beats/beatType] [(mode)]`，如 `1=C 4/4 (major)`、
   `1=G`（缺省 4/4 大调）；
3. **声部行**：`voiceN:` 开头（多声部依次 `voice1:` `voice2:`…），后跟空格分隔的
   音符序列，`|` 与 `||` 为小节分隔符。

音符写法：

| 符号 | 含义 | 示例 |
| --- | --- | --- |
| `0-7` | 音级（0=休止，1=主音） | `1 2 3` |
| `'` / `,` | 高八度 / 低八度点（可累计） | `1'`（高八度） |
| `-` | 增时线（`--`=全音符、`-`=二分，无=四分） | `5 -` |
| `_` | 减时线（`_`=八分、`__`=十六分、`___`=三十二分、`____`=六十四分） | `6 5 _ 3 5 _` |
| `.` | 附点（可累计） | `6 .` |
| `[1 3 5]` | 和弦（主音固定括号内第一个） | `[1 3 5]` |

示例（小星星首句）：

```
小星星反向样例
1=C 4/4 (major)
voice1: 1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 - ||
```

反向转换还支持 `--divisions N`（1..16，默认 4）控制输出 MusicXML 的 divisions 粒度。

### 7.2 MusicXML 反向输出

--to-musicxml 输出的 MusicXML 符合标准（`score-partwise` 4.0），含
divisions/key/time/clef/pitch/voice，多声部 <backup>/<forward>、和弦 <chord/> 等元素，
可被 music21 / MuseScore 等主流音乐软件读取与**再渲染为五线谱图像**。已在 8 份样本上
通过 music21 逐音校验（13492/13492 音符、79240/79240 字段，100%）。

> **形态边界（诚实）**：本软件输出的是五线谱的**标准数据文件（MusicXML）**，不直接
> 渲染五线谱图像/PDF。需要看到五线谱画面时，请用任意五线谱软件（如 MuseScore、
> 打谱/DAW 软件）打开输出的 .musicxml 文件。

---

## 8. 本地网页应用

### 8.1 启动

```
C:/Users/13157/.workbuddy/binaries/python/envs/default/Scripts/python.exe tools/pudu_server.py
```

启动后浏览器访问 http://127.0.0.1:8765。

### 8.2 使用流程

1. 打开网页，点击上传按钮，选择乐谱图片（PNG/JPG）或 PDF；
2. 等待识别完成，页面显示识别进度；
3. 识别完成后，页面展示简谱 L2 预览，可打印；
4. 点击下载，获取 final.musicxml 文件（music21 可读、可再渲染）；
5. 「需校对」面板列出系统标记的可疑小节，供人工核对。

### 8.3 多页 PDF

多页 PDF 由识别引擎逐页处理并拼接，坏页单独跳过并在面板中提示。

---

## 9. 评测与校验工具

### 9.1 简谱层评测

tools/omr_eval_groundtruth.py（已归档 `to_be_delete/tools/`）提供简谱层评测，
把图片 + 标准答案（GT）输入，经 Pudu.exe 投影为简谱 JSON 后逐音比对，输出
note_pass / field_pass 与分维指标（rhythm / pitch_degree / pitch_octave /
pitch_accidental / tie / rest / chord / octave_jump）。

### 9.2 MusicXML 层差异检测

tools/omr_musicxml_diff.py（已归档 `to_be_delete/tools/`）直接对比识别输出的
MusicXML 与标准答案 MusicXML，在 MusicXML 字段层（音高 pitch / 时值 rhythm /
休止 rest / 装饰音 grace / 和弦 chord / 延音线 tie / 调号 key / 拍号
time_signature）逐音符报告差异。详细用法见 docs/musicxml-diff-guide.md。

### 9.3 单元测试

- C++ 单元测试：PuduTests 目标已随仓库清理下线（历史 161 个用例，自研 header-only 框架，
  零外部依赖）；
- Python 单元测试：运行
  `python -m pytest tests/ -q`（覆盖预处理、识别适配、评测、A/B、网页应用等）。

---

## 10. 常见问题（FAQ）

Q1：运行提示找不到 pugixml.dll？
A1：将 vcpkg 的 bin 目录加入系统 PATH 环境变量后重试。

Q2：图片识别失败，提示分辨率过低？
A2：软件已自动尝试 2 倍、3 倍放大重试。若仍失败，请提供更高分辨率（建议 300 DPI）
的原图。

Q3：PDF 某些页识别失败？
A3：软件逐页识别，失败页单独跳过，成功页正常拼接。可核对「需校对」面板。

Q4：--omr-engine 有哪些可选值？
A4：audiveris（默认）、oemer、fixture。

Q5：如何查看后处理到底改了什么？
A5：使用 --apply-postcorrect --postcorrect-report report.json，审计轨迹写入 JSON。

Q6：变调会改变调号吗？
A6：--key 会同时移调与改调号；--rekey 只改调号；--transpose 只按半音移调。

Q7：music21 能否读取输出的 MusicXML？
A7：能。输出为标准 MusicXML，music21 可读可再渲染，校验 100% 通过。

Q8：网页应用无法启动？
A8：确认 Python 3.9+ 环境可用，且端口 8765 未被占用。

---

## 11. 版权与许可

谱渡 Pudu 乐谱识别转换软件 v0.9.0 由谱渡项目团队独立开发完成。本软件部分识别功能
依赖第三方开源 OMR 引擎（Audiveris、oemer），相关引擎版权归其各自作者所有；本软件
自研部分为 MusicXML 解析与双向转换内核、简谱渲染、后处理规则引擎、几何校正、评测
体系与引擎工程适配层。

第三方开源组件许可：

- pugixml（MIT License）：C++ XML 解析库；
- Audiveris（AGPL-3.0）：OMR 识别引擎（随包再分发，附 LICENSE 与源码链接声明；外部
  调用不构成衍生作品）；
- oemer（Apache-2.0）：OMR 识别引擎（外部调用，不随发布包分发）；
- music21（BSD）：校验工具（仅评测时使用）。

本软件使用 MIT License 开源。

> **软件著作权登记状态（诚实）**：登记申报已**暂停**。自 2026-03-15 起登记要求申报人
> 承诺「未使用 AI 开发」，而本项目为 AI 辅助开发，无法如实签署该承诺，故暂停申报
> （详见 `docs/copyright-application-checklist.md` §5.1）。本手册为 AI 生成的操作文档，
> 仅用于产品说明，不作为著作权登记材料。
