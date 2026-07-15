# 谱渡 Pudu

五线谱与简谱互转工具（MVP 阶段）。

> 当前状态（2026-07-15）：已实现 **MusicXML → 简谱** 的核心转换（阶段 2，MVP v1），支持纯文本(L1)、二维 HTML(L2)、结构化 JSON(L3) 三种简谱呈现，并通过 music21 跨语言 100% 校验。反向转换（简谱→五线谱，阶段 3）与 OMR 识别（阶段 1）尚未开始。

## 阶段与里程碑

| 阶段 | 目标 | 状态 |
|---|---|---|
| 阶段 0 | 环境与 MusicXML 解析基础 | ✅ 完成 |
| 阶段 1 | OMR 黑盒集成（PDF/JPG → MusicXML） | ⬜ 未开始 |
| 阶段 2 | 五线谱 → 简谱核心（MVP v1） | ✅ 完成（已打标签 `phase-2`） |
| 阶段 3 | 简谱 → 五线谱（反向） | ⬜ 未开始 |
| 阶段 4 | AI / 深度学习进阶 | ⬜ 未开始 |
| 阶段 5 | 工程化与 GUI | ⬜ 未开始 |

> 整体规划与 5 阶段路线见 `omr-tool-research/results/research_report.md`；阶段 3 具体行动计划见 `stage3_action_plan.md`。

## 功能概览（阶段 2 + 阶段 3）

- **输入**：MusicXML 文件（`data/*.musicxml`，支持 `score-partwise` 与 `.mxl`）。
- **转换** `staffToJianpu`：
  - 首调（movable-do）音级映射：`1` = 主音，按调号定位；调外音用临时升降记号。
  - 调号 / 调式 / 拍号识别；八度点（高低八度）；时值（增时线 / 减时线 / 附点）。
  - 多声部分行；休止、和弦、装饰音、延音线、连音组（`<time-modification>`）标注。
- **三种简谱呈现**：
  - **L1 纯文本**（`--to-jianpu`）：命令行核对用。
  - **L2 二维 HTML/Unicode**（`--to-jianpu-l2 [out.html]`）：自包含、可直接浏览器打开，含真实八度点、减时线横向连写、增时线、和弦列、连音弧。
  - **L3 结构化 JSON**（`--to-jianpu-json [out.json]`）：无损，供 `verify_jianpu_groundtruth.py` 逐音比对。
- **变调重算（阶段 2 边界补全 / 阶段 3 前置）**：
  - 在任一 `--to-jianpu*` 前追加 `--key <调名>`（移调）、`--rekey <调名>`（改写调号）、`--transpose <±半音>`（字面移调）。
  - 单一事实源 = canonical Score：变调在 Score 上平移音高（或仅改调号）后复用既有转换器，保证 L0↔Score 自洽，满足阶段 3 往返（G3）音高守恒前提。
  - `include/transpose.hpp` + `src/transpose.cpp`，纯函数 `parseKeyName` / `tonicNameToFifths` / `semitonesToFifths` / `transposeScore` 独立可单测。
- **阶段 3 反向转换（简谱 → 五线谱）`jianpuToStaff` + `scoreToMusicXML`**：
  - `jianpuToStaff(JianpuDoc) -> Score`：音级→绝对音高（逆 `midiToJianpu`，复用 `midiToPitch` 保证拼写口径一致）、八度点→octave、时值→`type`+`duration`（与 `typeToDuration` 严格互逆）、调号/拍号→`ScoreAttributes`、多声部按 `partIndex`/`voice` 还原、休止/和弦/装饰音/延音线映射回 `Note`。
  - `scoreToMusicXML(Score) -> .musicxml`：pugixml 写出 `score-partwise`；多声部用 `<backup>/<forward>` 还原并行时序、和弦用 `<chord/>`；写出的文件可被本仓库解析器读回且语义等价（G2 自洽测试）。
  - CLI `--to-musicxml [out.musicxml]`：演示「五线→简→五线」双向闭环，可叠加 `--key/--rekey/--transpose`。
  - 已知限制：和弦逐音八度点在阶段 2 仅存音级，反向按「根音上方最近八度」还原（音级守恒，精确八度不保）；`tieStop` 反向不还原（仅 `tieStart`）。
- **质量保障**：
  - C++ 单元测试 **79/79 全绿**（header-only 自研框架，零外部依赖；含阶段 2 共 54、变调重算 16、阶段 3 新增 9 项 G1+G3；G2 序列化自洽 1 项随 MSVC 构建一并运行，合计 80）。
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
```

> 不带路径参数时，`Pudu.exe` 回退到内嵌「小星星」样例。若提示找不到 `pugixml.dll`，将 vcpkg 的 bin 目录加入 `PATH`：
> ```powershell
> $env:PATH = "D:\vcpkg\installed\x64-windows\bin;" + $env:PATH
> ```

运行单元测试：

```bash
build/PuduTests.exe
```

## 项目结构

```
Pudu/  (工作区当前磁盘名为 omr/，规划重命名为 Pudu/)
├── CMakeLists.txt              # 构建配置（Pudu + PuduTests 目标）
├── CMakePresets.json           # VS Code / CMake 预设
├── vcpkg.json                  # 第三方依赖声明（pugixml）
├── README.md
├── src/
│   ├── main.cpp                # 入口 + CLI（--to-jianpu* / --to-musicxml / --key / --rekey / --transpose）
│   ├── musicxml_parser.cpp     # MusicXML 解析（pugixml）
│   ├── jianpu_converter.cpp    # 阶段2 五线→简谱转换 + L1/L2/L3 渲染
│   ├── transpose.cpp           # 变调重算（transposeScore / parseKeyName / midiToPitch / ...）
│   ├── jianpu_to_staff.cpp     # 阶段3 G1：JianpuDoc -> Score
│   └── musicxml_serializer.cpp # 阶段3 G2：Score -> MusicXML（scoreToMusicXML）
├── include/
│   ├── score_model.hpp         # MusicXML 内存模型（Score/Note/.../Credit）
│   ├── musicxml_parser.hpp     # 解析器接口
│   ├── jianpu_model.hpp        # 阶段2 L0 简谱模型（JianpuDoc/...）
│   ├── jianpu_converter.hpp    # 转换器 API（staffToJianpu / jianpuToL1/L2/Json）
│   ├── transpose.hpp           # 变调重算 API（含 midiToPitch，阶段3 复用）
│   └── jianpu_to_staff.hpp     # 阶段3 API（jianpuToStaff / scoreToMusicXML）
├── test/                       # 单元测试（header-only 框架 + 6 测试文件）
├── data/                       # 测试 MusicXML 语料（8 份，.gitignore 已排除）
└── omr-tool-research/          # 调研文档（技术选型/架构/规范/校验报告/计划）
    ├── results/research_report.md        # 总路线与 5 阶段规划
    ├── jianpu_output_spec.md             # 阶段2 简谱输出规范
    ├── verify_jianpu_groundtruth.py      # music21 ground-truth 校验器
    ├── jianpu_groundtruth_report.md      # 校验报告（人读）
    └── ...
```

## 已知限制（阶段 2）

- 输入为 MusicXML 文本；PDF/JPG 输入链路（阶段 1 OMR）未接入。
- 小调「6=X」标法开关未实现（当前小调走首调相对法）。
- 和弦成员仅存音级，逐音独立八度点未实现。
- L2 连音弧为单音上方 SVG 弧近似；减时线连写按“连续同值”启发式（非真实 beat 分组）。
- 变调段不重算首调（取初始调号）；极端连音比（7:8/7:4/9:4，46 处）单列未校验。

## 下一步

- **阶段 3**：简谱 → 五线谱反向转换（`jianpuToStaff` + `Score→MusicXML` 序列化 + round-trip 自测）。详见 `stage3_action_plan.md`。
- **阶段 1**：接入 Audiveris/oemer 黑盒，打通 PDF/JPG 输入。

## 常见问题

### 为什么用 pugixml 而不是 libmusicxml2
`libmusicxml2` 未收录进 vcpkg 官方仓库；MusicXML 本质就是 XML，MVP 只需读写 XML，用轻量的 `pugixml`（MIT）更简单可控。

### `CMake: Select Kit` 不显示
确保打开的是项目根文件夹（含 `CMakeLists.txt`），且底部状态栏无红色错误；可尝试 `CMake: Delete Cache and Reconfigure`。

### 第一次 configure 极慢
vcpkg 需下载并编译 pugixml；网络不稳时可设置 vcpkg 资源镜像或代理后重试。
