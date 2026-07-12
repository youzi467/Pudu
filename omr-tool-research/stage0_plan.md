# 阶段 0 细化学习计划：环境与 CV/音乐表示基础

> 定位：谱渡项目启动的第一步（对应总路线"阶段 0"），约 2 周课余时间，10 个半周(session)推进
> 目标产出：① OpenCV 小程序（载入图片→二值化→Hough 检测谱线并绘制）② 用 libmusicxml2 读取示例 MusicXML
> 难度标 ★ 易 / ★★ 中 / ★★★ 较难；优先级：高 = 关键路径，必须完成；中 = 建议完成

---

## 0. 总览时间线（按半周 / session 粒度）

| Session | 时间 | 主题 | 核心产出 | 难度 | 优先级 | 耗时 |
|---|---|---|---|---|---|---|
| S1 | 第1周·上 | 开发环境搭建 | VS/CMake/Git/vcpkg 装好并验证版本 | ★ | 高 | 0.5–1 天 |
| S2 | 第1周·上 | 工具链打通 | fmt + CMakePresets 端到端跑通（验证 toolchain） | ★ | 中 | 0.5 天 |
| S3 | 第1周·中 | 版本控制 | 仓库初始化 + .gitignore + 分支策略 + 首次提交 | ★ | 高 | 0.5 天 |
| S4 | 第1周·中 | OpenCV 基础(1) | imread + 灰度 + Otsu 二值化小程序 | ★★ | 高 | 1 天 |
| S5 | 第1周·下 | OpenCV 基础(2) | contours + Hough 检测谱线并绘制 → **产出①** | ★★ | 高 | 1–1.5 天 |
| S6 | 第2周·上 | MusicXML 规范 | 通读 Tutorial 重点章节，建立结构心智 | ★ | 中 | 1 天 |
| S7 | 第2周·上 | libmusicxml2 | 解析示例 MusicXML 打印音符序列 → **产出②** | ★★ | 高 | 1–1.5 天 |
| S8 | 第2周·中 | 整合与文档 | 两个小程序并入项目结构 + README + 提交 | ★ | 中 | 0.5 天 |
| S9 | 第2周·中 | 扩展验证 | 用 Python music21 对照解析结果（可选） | ★★ | 中 | 0.5–1 天 |
| S10 | 第2周·下 | 缓冲/补完 | 处理卡点、补缺、打 `v0.1-stage0` 标签 | — | 中 | 灵活 |

> 若时间紧，S2/S8/S9 可压缩；S1/S3/S4/S5/S7 为关键路径不可省。

---

## 1. 开发环境搭建（S1–S2）

### 1.1 组件与版本选择

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| Visual Studio 2022 | 17.x（社区版免费） | 勾选工作负载"**使用 C++ 的桌面开发**"；含 MSVC v143、Windows 10/11 SDK |
| CMake | **≥ 3.25**（建议装最新稳定 3.30+） | **单独从 cmake.org 安装并加入 PATH**，不要用 VS 自带的老版本 |
| Ninja | 1.11+（可选但推荐） | 作为生成器比 MSBuild 快；可用 scoop 或官方 zip 安装 |
| Git | 2.4x 最新 | 安装时选"Checkout as-is, commit Unix-style"；默认分支设为 `main` |
| vcpkg | 最新 master | manifest 模式管理依赖 |
| OpenCV | 4.10.x（经 vcpkg 安装） | 不必手动下载 |
| libmusicxml2 | 最新（经 vcpkg 安装） | MPL-2.0，C++ MusicXML 库 |

### 1.2 配置流程（S1）

1. 安装 VS2022 → 工作负载"使用 C++ 的桌面开发" → 确认 MSVC + SDK 已勾选。
2. 安装 CMake（独立版），安装时勾选"Add CMake to PATH"。
3. 安装 Git，配置：
   ```bash
   git config --global user.name  "你的名字"
   git config --global user.email "you@example.com"
   git config --global init.defaultBranch main
   ```
4. 安装 vcpkg（建议放在仓库**外**，避免污染 git）：
   ```bash
   git clone https://github.com/microsoft/vcpkg.git D:/tools/vcpkg
   D:/tools/vcpkg/bootstrap-vcpkg.bat
   ```
   设置默认 triplet：`setx VCPKG_DEFAULT_TRIPLET x64-windows`（重启终端生效）。
5. **验证**：`cmake --version`、`git --version`、`ninja --version`、`D:/tools/vcpkg/vcpkg version` 均正常输出。

### 1.3 依赖管理策略（贯穿）

- **manifest 模式**：在项目根放 `vcpkg.json` 声明依赖，提交进 git；`vcpkg_installed/` 目录 gitignore（可随时重建）。
- **triplet 固定**：统一 `x64-windows`，与 VS 的 x64 编译器一致。
- **与 CMake 对接**：用 `CMakePresets.json` 把 `CMAKE_TOOLCHAIN_FILE` 写成 `cacheVariables`，一劳永逸（见 S2/S3）。
- **二进制缓存（可选）**：设 `VCPKG_BINARY_SOURCES` 加速重复安装。

### 1.4 工具链打通（S2，先验证再写真代码）

建最小项目验证整条链：
```
stage0_hello/
  vcpkg.json            # { "dependencies": ["fmt"] }
  CMakePresets.json     # cacheVariables.CMAKE_TOOLCHAIN_FILE = D:/tools/vcpkg/scripts/buildsystems/vcpkg.cmake
  CMakeLists.txt        # find_package(fmt) + target_link_libraries(app PRIVATE fmt::fmt)
  src/main.cpp          # fmt::print("hello from toolchain\n");
```
命令：`cmake --preset default` → `cmake --build build` → 运行。跑通即证明"vcpkg 供库 + CMake 接入 + 编译器"全链路 OK，再去写 OpenCV 代码，心里有底。

---

## 2. 版本控制（S3）

### 2.1 仓库与忽略规则

- 在项目根 `git init`（或在 GitHub 建空仓后 clone）。
- `.gitignore`（关键条目）：
  ```
  build/
  out/
  vcpkg_installed/
  .vs/
  *.user
  ipch/
  *.obj
  *.exe
  *.pdb
  ```
  > vcpkg 本身在仓库外，不进 git；其产物 `vcpkg_installed/` 也不进 git（由 `vcpkg.json` 重建）。

### 2.2 分支策略（单人项目，轻量但规范）

- `main`：稳定主线，每个里程碑合并进来。
- `feat/xxx`：每个子任务开短生命周期分支，完成并自测后 squash 合并回 `main`。
- 推荐分支：`feat/opencv-basics`（S4–S5）、`feat/musicxml-basics`（S6–S7）。
- 操作闭环：`git switch -c feat/opencv-basics` → 提交 → `git switch main` → `git merge --squash feat/opencv-basics` → 删分支。

### 2.3 提交规范（Conventional Commits）

格式：`type(scope): 简述`（简述 ≤50 字，祈使句）。
- 类型：`feat`(新功能) / `fix`(修复) / `docs`(文档) / `chore`(杂务) / `refactor` / `test` / `build`(构建/依赖)。
- 示例：
  ```
  build: add vcpkg.json with opencv and libmusicxml2
  feat(opencv): imread + Otsu threshold demo
  feat(musicxml): parse sample score and print notes
  docs: stage0 README and build instructions
  ```
- **验证（S3 完成标准）**：`git log --oneline` 历史清晰；能 `git checkout <旧提交>` 后 `cmake --build` 重建成功。

---

## 3. OpenCV 基础（S4–S5，渐进式）

> 每一步都给：核心概念 → 代码任务 → 验证方式。建议用真实乐谱扫描图 + 合成图交替测试。

### Step A：imread → 灰度 → 像素访问（S4 前半）
- **核心概念**：`cv::Mat` 内存布局（行/列/通道）、`imread` 的 `IMREAD_COLOR/GRAYSCALE`、BGR 顺序、`cv::cvtColor(BGR2GRAY)`、`Mat::at<>` 访问像素、ROI。
- **任务**：载入一张 JPG，转灰度，打印 `rows/cols/channels`，保存灰度图；用 `at<uchar>` 读一个像素值。
- **验证**：输出尺寸/通道正确；保存的灰度图能用看图器打开且确实是灰度。

### Step B：threshold → Otsu 二值化（S4 后半）
- **核心概念**：二值化目的（把乐谱转黑白，去噪利于后续）；`cv::threshold(..., THRESH_BINARY)` 全局阈值；`THRESH_OTSU` 自动选阈值；`cv::adaptiveThreshold` 局部阈值（扫描件光照不均时有用）。
- **任务**：对灰度图做 Otsu 二值化，保存；打印前景（黑）像素占比。
- **验证**：二值图黑白分明；前景占比在合理区间（乐谱通常 5%–25% 为墨）；与人工目测一致。

### Step C：findContours → 绘制轮廓（S5 前半）
- **核心概念**：轮廓是"同种颜色连通边界"；`cv::findContours(image, contours, hierarchy, RETR_EXTERNAL/RETR_TREE, CHAIN_APPROX_SIMPLE)`；`cv::drawContours`；`cv::contourArea`、`cv::boundingRect`。
- **任务**：用一张合成图（几个矩形/圆）做阈值，找轮廓并绘制；打印轮廓数量与面积。
- **验证**：检测到的轮廓数 == 绘制的图形数；面积与预期一致。

### Step D：HoughLines → 检测水平谱线（S5 后半，汇成产出①）
- **核心概念**：Hough 变换把"图像空间直线"映射到"参数空间(ρ,θ)投票"；`cv::HoughLines(edges, lines, rho, theta, threshold)` 返回 `(rho,theta)`；`cv::HoughLinesP` 返回线段端点；谱线是近似水平的直线（θ≈0）。
- **任务**：在二值谱线上检测水平直线，在原图叠加绘制红线，保存；打印检测到的线条数。
- **验证**：叠加图里红线大致贴合谱线；检测数量与人工目测一致（误差 ±2 条以内）。

**产出① = Step A→D 串联**：载入真实/合成谱图 → 灰度 → Otsu → Hough 检测水平谱线 → 叠加绘制保存。

---

## 4. MusicXML 规范学习（S6–S7）

### 4.1 MusicXML Tutorial 阅读顺序（重点章节标注）

按此顺序读官方 Tutorial PDF（https://wpmedia.musicxml.com/wp-content/uploads/2017/12/musicxml-tutorial.pdf）：

1. **Overview / What is MusicXML**（必读）：理解 `score-partwise`（按小节组织，最常用）vs `timewise`（按时间组织）。**本项目用 score-partwise。**
2. **Document Structure**：`score-partwise → part → measure → note` 的嵌套关系（核心骨架）。
3. **Pitch & Duration（重点）**：
   - `pitch` = `step`(A–G) + `alter`(±半音，如 -1=降号) + `octave`(4=中央C所在八度)；
   - `divisions`（每四分音符细分分辨率）+ `duration`(整数) 决定时值；`type`(whole/half/quarter…) 与附点。
4. **Attributes（重点）**：`key/fifths`（五度圈：0=C,1=G,-1=F,2=两升号）、`clef`、`time`、`divisions`。
5. **Rests / Chords / Accidentals**：`rest` 替代 pitch；`chord` 同音开始多音；`accidental` 临时记号。
6. **可跳过（现阶段）**：`sound`/`print`/排版相关、`direction`/`ornaments`（MVP 无装饰音）、多重谱号切换等。

> 划重点：MVP 只需关心 `partwise / part / measure / note / pitch / divisions / duration / type / key / clef / rest`，其余暂不管。

### 4.2 libmusicxml2 API 关键数据结构（S7）

- 库是 **DOM 树 + Visitor** 模型。解析入口：`TScoreReader::readScore(std::istream&)` 得到 `TScore*`。
- 导航路径（类名以实际安装头文件为准，安装后在 `vcpkg_installed/x64-windows/include/libmusicxml/` 下 grep 确认）：
  - `TScore` → `parts()` / `measures()`
  - `TPart` → `measures()`
  - `TMeasure` → `notes()`、`attributes()`
  - `TNote` → `pitch()`、`duration()`、`type()`、`isRest()`
  - `TPitch` → `step()` / `alter()` / `octave()`
  - `TKey` → `fifths()`
  - `TClef` → `sign()` / `line()`
- **实践建议**：装好后直接 `grep -r "class TNote" vcpkg_installed/x64-windows/include/libmusicxml/` 看真实方法签名，比死记文档可靠。
- 最小解析骨架（示意）：
  ```cpp
  #include <musicxml.h>          // 实际头文件名以安装为准
  #include <iostream>
  #include <fstream>
  int main() {
      std::ifstream is("sample.musicxml");
      auto* score = TScoreReader::readScore(is);   // 伪签名，按真实 API 调整
      for (auto* part : score->parts())
        for (auto* m : part->measures())
          for (auto* n : m->notes()) {
              if (n->isRest()) continue;
              auto* p = n->pitch();
              std::cout << p->step() << (p->alter()? "#":"") << p->octave()
                        << " dur=" << n->duration() << "\n";
          }
      return 0;
  }
  ```
- **验证（S7 完成标准）**：读入已知小谱（如 C 大调音阶），打印每个音的 `step/alter/octave/duration` 与全局 `key fifths`，与谱面对照完全一致。

---

## 5. 阶段产出验证（拆为可独立验证的子任务）

### 产出①：OpenCV 小程序（载入→二值化→Hough 谱线→绘制）

| 子任务 | 完成标准（可独立验证） |
|---|---|
| ST1.1 载入+灰度 | 程序读入指定路径 JPG，输出灰度 `Mat`，打印 `rows/cols/channels`，保存灰度图；保存文件可正常打开 |
| ST1.2 Otsu 二值化 | 输出二值图黑白分明；打印前景像素占比在合理区间（5%–25%）；与目测一致 |
| ST1.3 Hough 检测+绘制 | 在二值图检测水平直线，原图叠加红线保存；打印检测线条数，与人工目测误差 ≤2 条 |

> 每个 ST 都能单独 `cmake --build && run` 验证，不必等全部写完。

### 产出②：libmusicxml2 读取示例 MusicXML

| 子任务 | 完成标准（可独立验证） |
|---|---|
| ST2.1 编译链接通过 | `CMakeLists.txt` 中 `find_package(musicxml)` + `target_link_libraries(app PRIVATE <musicxml::target>)`；空 `main` 编译运行成功 |
| ST2.2 解析并打印音符 | 读入示例 `.musicxml`，遍历 measures/notes，打印每个 note 的 `step/alter/octave/duration/type` 及全局 `key fifths`；与谱面对照一致 |
| ST2.3 固定样例断言 | 用 C 大调音阶样例，断言打印输出 == 预期序列（可手算对照），证明解析正确 |

### 阶段 0 总验收
- [ ] 两个小程序均能 `cmake --preset && cmake --build build` 一键构建运行
- [ ] `git log` 历史规范，关键路径分支已合并 `main`
- [ ] README 写明环境要求与构建命令
- [ ] 打标签 `git tag v0.1-stage0`

---

## 6. 风险与提示

- **OpenCV 首次 vcpkg 编译很慢**（几十分钟），属正常，S1 就触发，别慌。
- **Hough 对真实扫描件噪声敏感**：谱线可能断、或检出误线。MVP 先用合成/印刷清晰图验证，扫描件降噪留到后面阶段。
- **libmusicxml2 API 以安装头为准**：不要盲信网上的旧签名，装好后 grep 头文件最稳。
- **CMake 版本**：务必用单独装的新版，VS 自带的可能太旧导致 `CMakePresets` 特性不可用。
