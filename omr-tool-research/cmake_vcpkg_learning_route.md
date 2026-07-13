# CMake 与 vcpkg 系统学习路线

> 适用对象：已学完 C++ STL、数据结构、离散数学，零 CMake/vcpkg 基础
> 学习目标：在真实项目中**独立用 CMake 管理构建流程**、**用 vcpkg 管理第三方库依赖**
> 配套项目：最终服务于 谱渡 Pudu（阶段 4 即接入 pugixml，OpenCV 为选做）

---

> [!NOTE]
> **本路线学习进度（更新于 2026-07-13）**
> - **已完成**：阶段 0（环境就绪，MSVC+CMake+vcpkg 已装并验证）/ 阶段 1（CMake 多文件构建，经 D:\cmaketest 与 Pudu 工程实践）/ 阶段 3（vcpkg 首个库：pugixml 经 vcpkg 接入并 `find_package`+`target_link` 跑通）。
> - **进行中**：阶段 5（CMakePresets 已用，ctest 待补）。
> - **未开始/待项目长大多模块**：阶段 2（多目标静态库拆分，当前 Pudu 为单目标）。
> - **调整**：阶段 4 的 `libmusicxml2` 已改为 **pugixml**（vcpkg 无 libmusicxml2）；OpenCV 接入降级为选做（识别端由 Audiveris/oemer 黑盒承担），将来若做则用 opencv.org 预编译包而非 vcpkg 源码编译。

## 1. 基础概念

### 1.1 一个 C++ 程序是怎么变成 exe 的

单文件 `g++ main.cpp` 就够了，但真实项目有几十上百个 `.cpp`、互相引用头文件、要链接第三方库（OpenCV、fmt…）。手动敲编译命令会崩溃。于是需要工具来**管理"编译谁、按什么顺序、去哪找头文件、链接哪些库"**——这就是构建系统的职责。

典型流程：

```
源代码(.cpp/.h) ──[预处理/编译]──▶ 目标文件(.obj) ──[链接]──▶ 可执行文件/库(.exe/.lib)
                                         ↑
                              第三方库的头文件 + .lib 由「依赖管理器」提供
```

### 1.2 CMake 是什么

- **定位：构建系统生成器（meta-build tool），不是构建系统本身。**
- 你写一份 `CMakeLists.txt` 描述"项目有哪些目标、怎么编译链接"，CMake 据此**生成**对应平台的原生构建文件：
  - Windows 上可生成 **Visual Studio 解决方案(.sln)**，也可生成 **Ninja** 构建文件；
  - Linux/macOS 上可生成 Makefiles / Ninja。
- 然后由**原生构建工具**（MSBuild、Ninja、make）真正去编译链接。
- 核心价值：**一份 CMakeLists.txt 跨平台**，你不用为 VS、Linux、macOS 各写一套工程文件。

### 1.3 vcpkg 是什么

- **定位：C/C++ 包（依赖）管理器**（微软出品，开源）。
- 作用：**下载 → 编译（或用预编译二进制）→ 安装**第三方库到本地一个统一目录，并**自动帮你解决头文件路径和库文件路径**。
- 你只需在 `vcpkg.json` 里声明"我要 fmt、opencv"，vcpkg 负责把库备好。
- 它和 CMake 通过**工具链文件（toolchain file）**集成：CMake 配置时加载 vcpkg 的 toolchain，就能用 `find_package(OpenCV)` 直接找到 vcpkg 装好的库。

### 1.4 两者关系与在构建流程中的定位

| 工具 | 回答的问题 | 在流程中的位置 |
|---|---|---|
| **vcpkg** | "第三方库从哪来？头文件/.lib 在哪？" | 配置**之前**，先把依赖装好并暴露路径 |
| **CMake** | "我的代码怎么组织、怎么编译链接这些依赖？" | 读取 `CMakeLists.txt` + vcpkg 提供的路径，**生成**构建系统 |
| 原生构建工具(Ninja/MSBuild) | "一条条命令去编译链接" | CMake 生成后，真正执行编译 |

一句话：**vcpkg 负责"喂库"，CMake 负责"搭构建"**。二者通过 toolchain 文件对接，`find_package` 是衔接点。

```
源代码 ──▶ [CMake 读 CMakeLists.txt + vcpkg toolchain] ──▶ 生成构建系统 ──▶ [Ninja/cl 编译链接，链接 vcpkg 的库] ──▶ exe
              ↑ vcpkg 提前把第三方库装到本地并注入路径
```

---

## 2. 分阶段学习步骤

> 通用约定：所有练习都用 **out-of-source build**（建一个 `build/` 目录放产物，不污染源码）；编译器用 **Visual Studio 2022 自带的 MSVC** 或 **Clang**；推荐同时装 **Ninja** 作生成器（快）。CMake 版本建议 ≥ 3.25。

### 阶段 0：环境准备与心智模型（约 2–3 天 · ★）

**学习目标**：装好工具，建立"CMake 生成器 / vcpkg 依赖管理器"的心智模型，理解为什么要它们。

**核心知识点**
- 安装：CMake（官网或 VS 组件勾选）、vcpkg（`git clone` + `bootstrap-vcpkg.bat`）、Visual Studio 2022（带"使用 C++ 的桌面开发"）。
- 概念：generator（VS2022 / Ninja）、triplet（如 `x64-windows` 表示 64 位 Windows）、out-of-source build。
- 手动用 `cl` 或 `g++` 编译一个多文件小程序，**亲身感受"没有构建工具"的痛苦**，建立动机。

**动手练习**
1. 装好后运行 `cmake --version` 与 `vcpkg version`，确认可用。
2. 写 `hello.cpp`，分别用 `cl hello.cpp`（MSVC）和 `g++ hello.cpp`（若有）手动编译，跑通。
3. `git clone https://github.com/microsoft/vcpkg` 后执行 `.\vcpkg\bootstrap-vcpkg.bat`。

**验证方式（阶段结束必须能）**
- 口述：CMake 与 vcpkg 各管什么、为什么需要它们。
- `cmake --version` 与 `vcpkg version` 均正常输出版本。

---

### 阶段 1：CMake 多文件构建基础（约 4–5 天 · ★★）

**学习目标**：不引入任何第三方库，用 CMake 把一个多文件小项目跑起来。

**核心知识点**
- `CMakeLists.txt` 最小三件套：`cmake_minimum_required(VERSION 3.25)`、`project(hello)`、`add_executable(app main.cpp utils.cpp)`。
- 配置与构建命令：`cmake -S . -B build`（生成）、`cmake --build build`（编译）。
- 变量：`set(CMAKE_CXX_STANDARD 17)`、源文件列表 `set(SRCS ...)`。
- 头文件路径基础：`target_include_directories(app PRIVATE include)`。

**动手练习**：做一个"迷你计算器"
```
calc/
  CMakeLists.txt
  src/main.cpp        // 调用 add/mul
  src/math_utils.cpp
  include/math_utils.h
```
`main.cpp` 调用 `add/mul`，CMakeLists 用 `add_executable(calc src/main.cpp src/math_utils.cpp)` 并 `target_include_directories(calc PRIVATE include)`。成功构建并运行。

**验证方式**
- 从空目录独立写出 `CMakeLists.txt` 使项目构建通过。
- 能解释"为什么用 `-B build` 而不是在源码目录直接生成"。

---

### 阶段 2：CMake 多目标与库（现代 target-based）（约 5–7 天 · ★★）

**学习目标**：用现代 CMake 的"目标"思维管理多目标，独立拆出静态库。

**核心知识点**
- `add_library(mylib STATIC lib.cpp)` 建静态库。
- **现代 CMake 核心**：`target_include_directories`、`target_link_libraries` 的 `PUBLIC/PRIVATE/INTERFACE` 语义：
  - `PRIVATE`：仅本目标用；`PUBLIC`：本目标及链接它的目标都用；`INTERFACE`：仅传给链接者（头文件库常用）。
- 多个可执行目标（如再加一个 `tests` 目标）。
- `add_subdirectory()` 组织子目录。
- 初识 `CMakePresets.json`（把生成器/配置固化，避免每次敲长命令）。

**动手练习**：把阶段 1 的 math 拆成静态库
```
calc/
  CMakeLists.txt          // add_subdirectory(src) + add_subdirectory(app)
  src/CMakeLists.txt      // add_library(calc_lib STATIC math_utils.cpp)
  app/CMakeLists.txt      // add_executable(calc main.cpp); target_link_libraries(calc PRIVATE calc_lib)
  tests/CMakeLists.txt    // add_executable(calc_test test.cpp); target_link_libraries(calc_test PRIVATE calc_lib)
```
体会 `PUBLIC` 与 `PRIVATE` 的区别（把 include 设成 PUBLIC 看链接者是否自动获得）。

**验证方式**
- 能正确拆出 `calc_lib` 静态库并被 app、tests 链接。
- 能说清 `PUBLIC` vs `PRIVATE` 的影响，并独立给新加的库配好 include。

---

### 阶段 3：vcpkg 入门——第一个第三方库（约 4–5 天 · ★★）

**学习目标**：用 vcpkg 取一个库并接入 CMake 项目，**跑通"依赖管理"全链路**。

**核心知识点**
- **清单模式（manifest mode，推荐）**：在项目根放 `vcpkg.json` 声明依赖，例：
  ```json
  { "name": "demo", "version": "0.1.0",
    "dependencies": [ "nlohmann-json", "fmt" ] }
  ```
- triplet：`x64-windows`；可设 `VCPKG_DEFAULT_TRIPLET=x64-windows`。
- 与 CMake 对接：`cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=.../vcpkg/scripts/buildsystems/vcpkg.cmake`（或写进 `CMakePresets.json` 的 `cacheVariables`，一劳永逸）。
- `find_package(fmt CONFIG REQUIRED)` + `target_link_libraries(app PRIVATE fmt::fmt)`（注意导入目标名带 `::`）。

**动手练习**：用 fmt 美化输出 + nlohmann-json 读写
```
demo/
  vcpkg.json
  CMakeLists.txt   // find_package(fmt) + find_package(nlohmann_json) + target_link_libraries(app PRIVATE fmt::fmt nlohmann_json::nlohmann_json)
  main.cpp         // 用 fmt::print 和 nlohmann::json 读一个配置
```
删除 `build/` 重新配置，确认 vcpkg 按 `vcpkg.json` 自动拉取依赖并构建通过。

**验证方式**
- 项目能 `find_package` 到 vcpkg 提供的库并链接运行。
- 删除 `build/` 后重新 `cmake` 配置，依赖按 `vcpkg.json` 自动还原（证明依赖可复现）。

---

### 阶段 4：组合实战——接入 OpenCV + pugixml 雏形（约 1–1.5 周 · ★★★）  `状态：pugixml 部分已完成，OpenCV 降级为选做`

> **进度（2026-07-13）**：`pugixml` 已作为首个真实依赖接入 Pudu 工程并跑通（对应阶段 3 本领的实战应用）；`OpenCV` 接入降级为选做（见下方说明），故本阶段"组合实战"的核心（依赖可复现 + CMakePresets 固化）**已完成**。

**学习目标**：把阶段 2–3 的本领用到 谱渡项目的真实依赖上，形成可复现的"空壳项目"。

**核心知识点**
- 在 `vcpkg.json` 增加 `pugixml`（MusicXML 解析用；原定的 `libmusicxml2` 不在 vcpkg，已改 pugixml）。
- 🔶 OpenCV（选做）：多组件库，链接用 `OpenCV::opencv_core`、`OpenCV::imgcodecs` 等导入目标；`find_package(OpenCV REQUIRED)`。**但本机不通过 vcpkg 源码编译**（网络下极慢且被拦），改用 **opencv.org 官方预编译包** + `set(OpenCV_DIR "D:/opencv/build")`；且手搓 CV 已降级为练兵（识别端由 Audiveris/oemer 黑盒承担）。
- `CMakePresets.json` 固化 `CMAKE_TOOLCHAIN_FILE`，团队/换机一键还原。
- 项目目录规范：`src/ include/ tests/`。

**动手练习**：谱渡 阶段 0 雏形（对应调研报告阶段 0）
```
omr_stage0/
  vcpkg.json              // dependencies: pugixml  (opencv 为选做)
  CMakePresets.json       // cacheVariables.CMAKE_TOOLCHAIN_FILE = ../../vcpkg/.../vcpkg.cmake
  CMakeLists.txt
  src/main.cpp            // 用 pugixml 写最小 score-partwise 并读回断言 C4 whole（OpenCV 读图为选做）
  include/...
```
目标：从干净克隆（`git clone` 后）只需 `cmake --preset=default && cmake --build build` 即可构建运行。

**验证方式**
- pugixml 程序构建并运行，且**整条链路可复现**（把 `vcpkg.json` + `CMakePresets.json` 提交后，换机器克隆即可还原）。
- （选做）OpenCV 程序：用 opencv.org 预编译包接入，能解释 opencv 各组件导入目标的区别。

---

### 阶段 5（进阶）：工程化——Presets / 多配置 / 测试（约 1 周 · ★★★）

**学习目标**：达到"生产级独立使用"——多配置、自动化测试、可维护的 CMake 工程。

**核心知识点**
- `CMakePresets.json`：`configurePreset`（Debug/Release）、`buildPreset`、`testPreset`。
- `enable_testing()` + `add_test()` + `ctest` 跑单元测试。
- `option()` 开关特性；`find_package` 失败时的友好提示（`message(FATAL_ERROR ...)`）。
- 可选：自定义 `FindXXX.cmake`、导出/安装目标（`install()`）。

**动手练习**：给阶段 4 项目加 Debug/Release 两套 preset，并用 `add_test` 写 1–2 个断言测试（如"读取示例 MusicXML 音符数 == 期望值"），用 `ctest` 跑通。

**验证方式**
- `cmake --preset debug` 与 `--preset release` 均能配置构建。
- `ctest` 跑出绿色结果；能独立为一个新库写接入（find_package + target_link_libraries）。

---

## 3. 常见踩坑点与注意事项

| 坑 | 现象 | 解决方案 |
|---|---|---|
| **CMake 版本太旧** | VS 自带 CMake 可能很老，新语法报错 | 单独安装新版 CMake，放入 PATH 置顶；或在 VS 设置里指定 CMake 路径 |
| **triplet 不匹配** | 链接报错"找不到 xxx.lib"或架构冲突 | 统一用 `x64-windows`（与 VS 的 x64 编译器一致）；设 `VCPKG_DEFAULT_TRIPLET=x64-windows` |
| **忘了设 CMAKE_TOOLCHAIN_FILE** | `find_package` 找不到 vcpkg 的库 | 写进 `CMakePresets.json` 的 `cacheVariables`，永久生效，不要每次手敲 |
| **Debug/Release 运行时混用** | 运行时崩溃 / MDd 与 MD 不匹配 | 构建类型与 vcpkg 编译的版本一致；vcpkg 默认同时编 Debug/Release，注意选对 |
| **用全局 include_directories** | 头文件路径"泄漏"到无关目标，难以维护 | 全程用 `target_include_directories(... PUBLIC/PRIVATE)`，目标级隔离 |
| **导入目标名写错** | `target_link_libraries` 报"目标不存在" | 注意带 `::`：如 `fmt::fmt`、`OpenCV::opencv_core`；查 vcpkg 的 `share/<pkg>/*-config.cmake` 看真实目标名 |
| **第一次 vcpkg 编译极慢** | opencv 等首次从源码编译几十分钟 | 正常；开启二进制缓存（`VCPKG_BINARY_SOURCES`），或接受首次慢 |
| **网络/代理问题（国内）** | vcpkg 下载失败 | 配置清华/中科大等镜像或代理；部分库可改用预编译二进制 triplet |
| **生成器不一致** | 有时用 VS 有时用 Ninja，缓存混乱 | 固定一种（推荐 Ninja 速度更快）；换生成器前删 `build/` 重配 |
| **在源码目录直接生成产物** | 源码树被 `.obj`/`.exe` 污染，git 难管 | 永远 `-B build` 做 out-of-source build；把 `build/` 加进 `.gitignore` |
| **CMakeLists 里写绝对路径** | 换机/换人路径失效 | 用 `CMAKE_CURRENT_SOURCE_DIR`、`PROJECT_SOURCE_DIR` 等变量 |
| **find_package 大小写敏感** | 找不到包 | 按库文档的大小写写，如 `find_package(OpenCV REQUIRED)` |

---

## 4. 推荐学习资源

- **CMake 官方 Tutorial**：https://cmake.org/cmake/help/latest/guide/tutorial/index.html （从简到难，必做）
- **Modern CMake（中文友好）**：https://cliutils.gitlab.io/modern-cmake/ 与 arne-mertz 的 Modern CMake 系列文章
- **《CMake Cookbook》**（书本，含大量可运行示例）
- **vcpkg 官方文档**：https://vcpkg.io/en/docs/ （manifest 模式、triplet、集成 CMake 讲得很清）
- **cmake-init 模板**：https://github.com/friendlyanon/cmake-init （现代 CMake 项目脚手架，照着学结构）
- **B 站/中文博客**：搜索"CMake 现代用法""vcpkg 入门"，配合官方文档交叉验证

---

## 总览时间线

| 阶段 | 主题 | 估时 | 难度 | 关键产出 | 状态（2026-07-13） |
|---|---|---|---|---|---|
| 0 | 环境+心智模型 | 2–3 天 | ★ | 工具就绪，能手动编译 | ✅ 完成 |
| 1 | CMake 多文件 | 4–5 天 | ★★ | 迷你计算器 CMake 工程 | ✅ 完成（经 cmaketest + Pudu 实践） |
| 2 | 多目标+库 | 5–7 天 | ★★ | 静态库拆分+tests 目标 | ⬜ 待项目长大多模块时练 |
| 3 | vcpkg 首个库 | 4–5 天 | ★★ | fmt/json 依赖可复现 | ✅ 完成（pugixml 已接入跑通） |
| 4 | 组合实战 | 1–1.5 周 | ★★★ | pugixml 空壳（OpenCV 选做） | 🔶 pugixml 部分完成 |
| 5 | 工程化 | 1 周 | ★★★ | Presets+ctest 可维护工程 | 🔶 Presets 已用，ctest 待补 |

合计约 **4–5 周课余时间**即可达到"在真实项目中独立使用 CMake + vcpkg"的目标，且阶段 4 直接对接你的谱渡项目。
