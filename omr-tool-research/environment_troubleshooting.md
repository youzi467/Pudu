# 谱渡项目环境排错留档（环境搭建踩坑全记录）

> 适用机器特征（本机环境，换机/重装时重点对照）：
> - Windows 11 + Visual Studio Build Tools 2022（MSVC v143）
> - 网络存在 **HTTPS 拦截代理（自签 CA）**：git clone、vcpkg 自带下载器、curl 默认后端均会被拦
> - 系统代码页 **936（GBK）**：UTF-8 无 BOM 含中文的源码会被 MSVC 误读
> - vcpkg 单独装在 `D:\vcpkg`，环境变量 `VCPKG_ROOT=D:\vcpkg`
> - CMake 独立安装（4.4.0），不在 VS 自带目录

---

## 0. 速查决策表（出问题时先看这个）

| 你看到的现象 | 最可能原因 | 跳到 |
|---|---|---|
| VS Code 里搜不到 `CMake: Select Kit` / `Select Configure Preset` | 打开的文件夹没有 `CMakeLists.txt`，没被识别为 CMake 项目 | §3 |
| clone 报 `SSL certificate ... unable to get local issuer certificate (20)` | TLS 拦截代理，git 默认 OpenSSL 不信任 | §4 |
| clone 只有几十 KB/s、极慢 | 全量 clone 体积大 | §5 |
| `bootstrap-vcpkg.bat` 报 "command not found" / "不是内部或外部命令" | 在 Git Bash 用 `.\` 跑 .bat，或被嵌套目录坑 | §6 |
| `vcpkg version` 提示缺文件 / `libmusicxml2 does not exist` | vcpkg 官方无此端口 | §7 |
| `vcpkg install failed` + 日志说某 zip "has an incorrect hash" | 下载被代理拦截导致文件损坏/不完整 | §8 |
| 误点 `CMake: Select Package Preset` 没反应 | 那是 CPack 打包预设，不是我们要的 | §9 |
| 编译一堆 `error C2065 "xxx": 未声明的标识符` + `warning C4819` | UTF-8 无 BOM 中文注释被当 GBK 解析 | §10 |
| `cl` 不是内部或外部命令 | 普通终端没初始化 MSVC 环境 | §2 |

---

## 1. 核心认知：VS Code ≠ 编译器

VS Code 只是**编辑器**，不自带 C++ 编译器。必须另装 **Visual Studio Build Tools 2022（免费）** 提供 MSVC。
- 错误认知："我装了 VS Code + CMake Tools 就能编 C++" → 错，缺 MSVC 后端。
- 正解：**VS Code + VS Build Tools（免费）** 取代完整 Visual Studio IDE，编译器是同一套 MSVC。
- 本项目实测：光有偏旧的 MinGW 8.1.0 不够，正式工程用 MSVC 路线（vcpkg 默认 `x64-windows` 直兼容）。

## 2. MSVC 环境变量：不要手配 PATH

- ❌ 别往系统 PATH 手动加 `cl.exe`/`link.exe` 路径（MSVC 对环境变量极挑剔，易漏）。
- ✅ VS Code + CMake Tools：自动探测 MSVC，无需手动初始化。
- ✅ 终端手动编译：用开始菜单 "x64 Native Tools Command Prompt for VS 2022"，或 `call "…\vcvarsall.bat" x64`。
- 验证：`CMake: Select Kit` 能看到 `Visual Studio Build Tools 2022 - amd64` kit；`CMake: Configure` 不报 "compiler not found"。

## 3. `CMake: Select Kit / Configure Preset` 不出现

- **根因**：打开的 VS Code 文件夹里没有 `CMakeLists.txt` / `CMakePresets.json`，CMake Tools 没把它当 CMake 项目。
- **修复**：打开**含 `CMakeLists.txt` 的那个根文件夹**（本项目 `C:\Users\13157\WorkBuddy\Pudu`）。已加 `.vscode/settings.json`（`configureOnOpen: true` + toolchain），重开即识别。
- 选 **`CMake: Select Configure Preset`** → "Windows MSVC + vcpkg (Debug)"，别选带 "Package" 的。

## 4. Git clone 报 SSL 证书错误

- 现象：`fatal: unable to access '...github.com...': SSL certificate ... unable to get local issuer certificate (20)`
- 根因：TLS 拦截代理自签 CA，Git 默认 OpenSSL 后端不信任它。
- **修复（一劳永逸）**：`git config --global http.sslBackend schannel`（改用 Windows 系统证书库，已装好代理 CA）。重跑 clone。

## 5. clone 极慢（几十 KB/s）

- 原因：vcpkg 仓库全量历史体积大。
- **修复**：浅克隆 `git clone --depth 1 https://github.com/microsoft/vcpkg.git D:\vcpkg`（只取最新提交，体积小一个数量级）。
- 仍慢则设代理：`git config --global http.proxy http://代理host:端口`。

## 6. bootstrap-vcpkg.bat 各种失败

- **坑 A（Git Bash 语法）**：`.\bootstrap-vcpkg.bat` 在 Git Bash 里 `\b` 被转义 → "command not found"。
  - 修复：用 `cmd //c bootstrap-vcpkg.bat`，或切到 PowerShell / 系统 cmd 再跑。
- **坑 B（嵌套目录）**：第一次慢 clone 时 `D:\vcpkg` 已建，第二次浅克隆塞进了 `D:\vcpkg\vcpkg\`。
  - 修复：把内层内容提上来，让 `bootstrap-vcpkg.bat` 位于 `D:\vcpkg\`。
- **坑 C（下载器被拦）**：bootstrap 内部用 `tls12-download.exe` 从 github 下 `vcpkg.exe`，**不走系统证书库**，被代理拦死。
  - 修复：绕过它，用 Windows 自带 `curl.exe`（走系统证书库）手动下：
    `curl.exe -L --ssl-no-revoke -o D:\vcpkg\vcpkg.exe "https://github.com/microsoft/vcpkg-tool/releases/download/<tag>/vcpkg.exe"`
  - 版本标签见 `D:\vcpkg\scripts\vcpkg-tool-metadata.txt` 的 `VCPKG_TOOL_RELEASE_TAG`（本机 2026-05-27）。
  - 也可浏览器直接下该 URL 丢到 `D:\vcpkg\vcpkg.exe`。

## 7. `libmusicxml2 does not exist`（vcpkg 端口名错误）

- **关键事实**：vcpkg 官方 registry **没有 `libmusicxml2`**（实测 `libmusicxml`/`libmusicxml2`/`musicxml` 端口均不存在）。原骨架用它会报 `libmusicxml2 does not exist`。
- **修复**：MusicXML 本质就是 XML，MVP 只需读写 XML → 改用 **`pugixml`**（vcpkg 有，API 现代）。
  - `vcpkg.json`：`"dependencies": ["pugixml"]`
  - `CMakeLists.txt`：`find_package(pugixml CONFIG REQUIRED)` + `target_link_libraries(... pugixml::pugixml)`
- 备选：将来若需 libmusicxml2 高级功能，可 FetchContent 源码构建或 vcpkg overlay port。

## 8. `vcpkg install failed` + zip 哈希不匹配

- 现象：日志 `…downloads\PowerShell-7.6.2-win-x64.zip: error: … appears to be already downloaded, but has an incorrect hash`。
- 根因：vcpkg 内部要 PowerShell 7.6.2 跑端口脚本，下载被代理拦截→文件损坏/不完整。
- **修复**：手动下载正确文件覆盖到 `D:\vcpkg\downloads\PowerShell-7.6.2-win-x64.zip`。
  - 浏览器：`https://github.com/PowerShell/PowerShell/releases/download/v7.6.2/PowerShell-7.6.2-win-x64.zip`
  - 或 PowerShell：`curl.exe -L --retry 5 --ssl-no-revoke -o D:\vcpkg\downloads\PowerShell-7.6.2-win-x64.zip <url>`
  - 注意：含 `PowerShell`/下载关键词的 Bash 命令可能被安全策略拦截，用 **PowerShell 工具**执行更稳。
- **经验**：vcpkg 报 `vcpkg install failed` 常被误判为 Preset/CMake 配置错，实多为依赖下载/哈希问题，本机根因=TLS 拦截。

## 9. 不要选 `CMake: Select Package Preset`

- CMake 预设分多种：Configure（配置）/ Build / Test / **Package（CPack 打包）/ Workflow**。
- 我们要的是 **Configure Preset**（构建项目用）。Package Preset 是做安装包/分发包用的，现在用不到，选了也没用。
- 正确：`CMake: Select Configure Preset` → "Windows MSVC + vcpkg (Debug)"。

## 10. 编译报 C4819 + 一堆"未声明标识符"（编码坑）

- 现象：`main.cpp(1,1): warning C4819` + `error C2065 "attributes": 未声明的标识符` + `error C3536 … 初始化之前无法使用`。
- 根因：源码 **UTF-8 无 BOM + 含中文注释**，MSVC 默认按代码页 936(GBK) 解析，误读字节把标识符"切"坏 → 连锁误报。业务逻辑（pugixml API）其实是对的。
- **修复**：CMakeLists.txt 中 `add_executable` 之后加：
  ```cmake
  if(MSVC)
      target_compile_options(Pudu PRIVATE /utf-8)
  endif()
  ```
  改后需**重 Configure 再 Build**（`/utf-8` 要进生成的项目文件才生效）。
- **经验**：看到"诡异未声明标识符"报错，先找有没有 `C4819` warning，多半是编码而非真代码错。

---

## 11. 其它已验证的注意事项

- **vcpkg 与 VS 安装器捆绑版**：VS 安装器里勾的 "vcpkg 包管理器" 是捆绑版（受 VS 更新节奏控制、只支持 manifest 模式），**不等于**项目要用的独立版。本项目用 `D:\vcpkg` 独立 clone 版，两者共存不冲突。
- **VCPKG_ROOT 环境变量**：用 PowerShell 设最稳：
  `[Environment]::SetEnvironmentVariable("VCPKG_ROOT","D:\vcpkg","User")`
  （在 Git Bash 里 `cmd //c "setx ..."` 实测未真正执行。）设完**重启 VS Code** 让其继承。
- **不要 `vcpkg integrate install`**：全局集成会污染 VS 状态，项目用 manifest + toolchain 文件即可，干净可复现。
- **triplet 与编译器一致**：用 `x64-windows`（MSVC 动态 /MD），与 vcpkg 默认、VS x64 编译器一致；Debug/Release CRT 别混。
- **OpenCV 不要走 vcpkg 源码编译**：本机网络下编 OpenCV 极慢且反复被拦（几十组件+大量源码下载）。改用 **opencv.org 官方预编译包**（自解压 exe），CMake 里 `set(OpenCV_DIR "D:/opencv/build")` 指过去即可，免编译。
- **CMake 版本**：务必用独立装的新版（本机 4.4.0），VS 自带的可能太旧导致 Presets 特性不可用。

---

## 12. 当前项目已验证可跑通的链路

```
MSVC(Build Tools) + CMake(独立) + vcpkg(D:\vcpkg, pugixml)
  → CMakePresets(windows-msvc-vcpkg) → Configure → Build
  → Pudu.exe（写最小 MusicXML → 读回断言 C4 whole → 打印 Stage 0 passed）
```
这是阶段 0 的环境地基，已跑通。下一步见各阶段计划文档。
