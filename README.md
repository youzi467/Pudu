# 谱渡 Pudu

五线谱与简谱互转工具（MVP 阶段）。

## 前置依赖

1. **Visual Studio Build Tools 2022**（已安装）
   - 勾选"使用 C++ 的桌面开发"工作负载
2. **vcpkg**（尚未安装）
   - 克隆到 `D:\vcpkg`：
     ```bash
     git clone https://github.com/microsoft/vcpkg.git D:\vcpkg
     cd D:\vcpkg
     .\bootstrap-vcpkg.bat
     ```
   - 设置系统环境变量 `VCPKG_ROOT = D:\vcpkg`，然后重启 VS Code / 终端。
3. **CMake**（已安装 ≥3.25）
4. **VS Code 扩展**：C/C++、CMake Tools（已安装）

## 构建步骤

1. 在 VS Code 中打开 `C:\Users\13157\WorkBuddy\Pudu` 文件夹。
2. 按 `Ctrl+Shift+P` → `CMake: Select Kit` → 选择带 **"Visual Studio Build Tools 2022 Release - amd64"** 的 kit。
   - 如果仍然看不到 `CMake: Select Kit`，确保底部状态栏没有红色错误提示，并尝试 `CMake: Delete Cache and Reconfigure`。
3. 按 `Ctrl+Shift+P` → `CMake: Configure`。
   - 第一次会触发 vcpkg 自动下载并编译 pugixml（OpenCV 暂未接入，待网络稳定后用 opencv.org 预编译包接入）。
   - 这是正常现象，后续重开会快很多。
4. 按 `Ctrl+Shift+P` → `CMake: Build`。

或者用命令行：

```bash
cd C:\Users\13157\WorkBuddy\Pudu
cmake --preset windows-msvc-vcpkg
cmake --build build/windows-msvc-vcpkg --config Debug
```

## 运行

```bash
build\windows-msvc-vcpkg\Debug\Pudu.exe
```

如果报错提示找不到 `opencv_*.dll`，需要把 vcpkg 的 DLL 目录加进 PATH，或在 PowerShell 中：

```powershell
$env:PATH = "D:\vcpkg\installed\x64-windows\bin;" + $env:PATH
.\build\windows-msvc-vcpkg\Debug\Pudu.exe
```

## 项目结构

```
Pudu/
├── CMakeLists.txt          # 构建配置
├── CMakePresets.json       # VS Code / CMake 预设
├── vcpkg.json              # 第三方依赖声明
├── src/
│   └── main.cpp            # Stage 0 入口
├── data/                   # 测试图片 / MusicXML 文件
├── Pudu-research/          # 调研文档（技术选型/架构/学习路线/排错留档）
└── build/                  # 构建输出（不提交到 git）
```

## 常见问题

### 1. `CMake: Select Kit` 不显示
- 确保 VS Code 打开的是 `C:\Users\13157\WorkBuddy\Pudu` 这个文件夹，而不是 `Pudu-research` 子目录或 `D:\cmaketest`。
- 确保文件夹里有 `CMakeLists.txt` 或 `CMakePresets.json`。

### 2. 为什么用 pugixml 而不是 libmusicxml2
- **libmusicxml2 未收录进 vcpkg 官方仓库**（实测 `libmusicxml`/`libmusicxml2`/`musicxml` 均不存在），且用 MSVC 从源码编译较麻烦。
- MusicXML 本质就是 XML 文本，MVP 只需读写 XML，用轻量的 `pugixml` 更简单可控。
- 如果将来确实需要 libmusicxml2 的高级功能，可改为 FetchContent 从源码构建，或用 vcpkg overlay port。

### 3. 第一次 configure 极慢
- OpenCV 及其依赖会从源码编译，耐心等待。
- 如果网络超时，可设置 vcpkg 资源镜像或代理后重试。

## 阶段 0 目标

- [x] 项目骨架可配置
- [ ] OpenCV 可读取并二值化图像（Otsu）
- [ ] pugixml 可写出最小 MusicXML
- [ ] pugixml 可读回并断言音符正确（C4 whole 往返验证）
