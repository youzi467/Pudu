# 谱渡 Pudu · 打包分发方案与桌面化决策

> 生成：2026-08-13
> 定位：打包分发（当前网页应用形态）与桌面化改造（路径①②）的决策文档 + 分阶段执行计划。
> 相关：`docs/user-side-interface-design.md`（网页应用设计）、`docs/product-status.md`（产品状态）。
> 状态：**路线已拍板（2026-08-13）——打包分发 + 桌面化只做路径①（pywebview 壳），保留全部前端，不做 Qt 原生重写。**

---

## 0. 决策记录

| 决策项 | 结论 | 日期 |
| --- | --- | --- |
| 打包分发目标 | **绿色免安装 ZIP + Inno Setup 安装包双形态** | 2026-08-13 |
| 桌面化路线 | **路径① pywebview 壳套现有网页 UI**，前端 100% 复用 | 2026-08-13 |
| 明确否决 | 路径② Qt/C++ 原生重写（UI 全重写，2–4 周，投入产出比极低） | 2026-08-13 |
| Audiveris 再分发 | **随包再分发**（附 AGPL LICENSE + 源码链接；免费分发合规可接受，商业收费需另行评估） | 2026-08-13 |
| oemer 回退 | **不打包**，AV 缺失降级提示（fixture 演示兜底） | 2026-08-13 |

---

## 1. 现状盘点

当前软件本质 = **Python 本地 HTTP 服务（`tools/pudu_server.py`，127.0.0.1）+ 浏览器 UI（`tools/pudu_ui.html`）**。
已具备约 90% 的桌面功能（拖拽上传、进度、简谱预览、校对面板、MusicXML/简谱导出）。

识别核心 = 子进程引擎（Audiveris 默认 / oemer 回退 / fixture 演示）→ Pudu.exe（C++）L2/L3 渲染。
**桌面化只改变「外壳/呈现层」，识别核心两路线完全一致。**

| 组件 | 现状 | 桌面化缺口 |
| --- | --- | --- |
| Pudu.exe（C++ 核心） | Debug 构建（1.2MB），依赖仓库结构 | 需 Release 构建 + 脱离仓库独立部署 |
| pudu_server.py | 硬编码 `127.0.0.1:8765`，依赖 `build/` 路径 | 动态端口、路径重定位、单实例、设置持久化 |
| pudu_ui.html | 单文件网页，拖拽上传已支持 | 原生打开/保存对话框、菜单栏、桌面通知 |
| OMR 引擎 | Audiveris 5.11.0（82MB MSI）+ oemer | 随包分发（AGPL 合规决策） |

---

## 2. 打包分发方案（当前形态）

### 2.1 打包内容与体积

| 组件 | 内容 | 体积 |
| --- | --- | --- |
| 启动外壳 | PyInstaller 打包 `pudu_server.py` + `pudu_ui.html` + `geometric_pitch.py` + `omr_preprocess.py` + `omr_fixture.py` + 引擎运行脚本 | ~40–60MB（含 Python 运行时） |
| C++ 核心 | Pudu.exe（Release）+ `pugixml.dll` | ~2–3MB |
| OMR 引擎（默认） | Audiveris 5.11.0（MSI 已归档 `to_be_delete/build/_audiveris/`）安装后整套 + JRE | ~150–250MB |
| OMR 引擎（回退） | oemer + onnxruntime + 模型权重 —— **已拍板：不打包**，AV 缺失时降级提示 | 0（不随包） |
| **合计** | 全量离线版（AV 随包，oemer 不打包） | **约 250–300MB** |

> 体积大头全是第三方引擎；Pudu 自身代码仅几 MB。包体优化 = 引擎裁剪，与桌面化无关。

### 2.2 两种分发形态

| 形态 | 做法 | 适用 |
| --- | --- | --- |
| A. 绿色免安装版 | PyInstaller `--onedir` → 整个目录 zip（含 Audiveris 解包）→ 双击 Pudu.exe | 首发 / 个人分发 / 内测 |
| B. 安装包 | Inno Setup（或 MSIX）：开始菜单、文件关联、卸载清理 | 正式发布 / 商业分发 |

### 2.3 关键改造点（必须做的 3 项）

1. **路径重定位**——服务器从仓库根改为 `os.path.dirname(sys.executable)` 相对定位 `Pudu.exe`/引擎脚本。
2. **动态端口**——绑 `127.0.0.1:0` 系统分配，经 pywebview JS 桥把端口注入前端。
3. **单实例 + 优雅退出**——重复启动激活已有实例；关窗终止引擎子进程、清理作业目录。

---

## 3. 桌面化对比

| 维度 | 打包当前形态（网页） | 路径① 壳套网页 | 路径② 原生重写 |
| --- | --- | --- | --- |
| 工作量 | 0.5–2 天 | 3–5 天 | 2–4 周 |
| 前端复用率 | 100% | 100% | ~0%（全重写） |
| 用户体感 | 浏览器标签页 | 独立原生窗口 + 任务栏 + 托盘 | 独立原生窗口 |
| 包体增量 | 0（基准） | +20–60MB（壳） | +10–30MB |
| 更新分发 | 可热更新 HTML/脚本 | 需重新打包 | 需重新打包 |
| 跨平台 | 天然 | 壳各自适配 | 平台各自写 UI |
| 技术风险 | 最低（零改动） | 低（1 个新依赖） | 高（重写引入新 bug） |
| 商业化观感 | 「像个网页」 | 「是个软件」 | 「是个软件」 |
| 维护成本 | 最低 | 低 | 高 |

### 结论（诚实口径）

- 桌面化 **95% 的收益来自「软件观感」，不来自功能**——识别能力/性能/离线可用两路线完全相同。
- 免费个人工具：打包当前形态即可；**商业化 / 面向非技术用户：只做到路径①**，保留全部前端。
- 路径②（Qt 重写）只在 UI 需重度原生交互时才划算，本项目明确否决。

---

## 4. 分阶段执行计划（pywebview 路径①）

> 总量约 **4–7 天**。每阶段含验收标准，全部完成后交付「双击即用」的桌面应用。
> 原则：**识别核心与前端零改动**，只加壳；引擎缺省时降级，不阻塞主线。

### 阶段 P0 — 后端可移植化（0.5–1 天）✅ 完成（2026-08-13）

- [x] `tools/pudu_server.py` 路径重定位：双模式解析（开发态 `__file__` 相对仓库根；打包态 `sys.frozen` → `_MEIPASS`/exe 目录），`PUDU_EXE`/`UI_HTML`/`JOBS_ROOT` 智能发现（含扁平便携目录：脚本 + Pudu.exe 同目录）。
- [x] 动态端口：`--port 0` 绑 `127.0.0.1:0`，实际端口写入 `%APPDATA%/Pudu/port.txt`（供 pywebview 壳读取）。
- [x] 单实例互斥：`ctypes.CreateMutexW`（`Local\PuduServer.Singleton`），env `PUDU_SINGLETON=0` 可关闭。
- **验收 ✅**：开发态回归（GET / → 200）+ 脱离仓库扁平目录启动正常（随机端口落盘 + 页面响应）；重复启动只留一实例；`--help` 正常。**附带修复**：原 `PUDU_EXE` 指向 `build/Pudu.exe`（死路径，真实 exe 在 `build/windows-msvc-vcpkg/Debug/Pudu.exe`），开发态识别/渲染本会失败，现已自动发现。

### 阶段 P1 — pywebview 壳（1–2 天）

- [ ] `pip install pywebview`（Windows 自动用 EdgeChromium/WebView2，无 JRE 依赖）。
- [ ] 新建 `tools/desktop_main.py`：读端口 → `webview.create_window(..., http://127.0.0.1:<port>/)` → `webview.start()`。
- [ ] 原生打开：`create_file_dialog()` 选 PDF/图片 → 新增 `POST /api/open`（本地路径直投，免上传）。
- [ ] 原生保存：保存对话框 → MusicXML/简谱写用户指定路径（替代浏览器下载）。
- [ ] 关窗优雅退出：停 HTTP + 杀引擎子进程 + 清作业目录。
- **验收**：原生窗口内完成「选文件 → 识别 → 预览 → 校对 → 导出」全流程，无需开浏览器。

### 阶段 P2 — 设置持久化 + 引擎引导（1 天）

- [ ] `%APPDATA%/Pudu/settings.json`：默认引擎（AV/oemer）、`PUDU_AUDIVERIS_EXE`、oemer 模型目录、简谱默认调式/升调。
- [ ] 引擎缺失引导页（内嵌 HTML）：Audiveris/oemer 均不可用 → 提示装 AV 或切换 fixture 演示模式。
- [ ] 首次运行向导（可选）：检测引擎 → 落盘设置。
- **验收**：换机无 Python 环境下设置可读写；引擎缺失有明确引导而非报错。

### 阶段 P3 — PyInstaller 打包 + 安装包（1–2 天）

- [ ] Pudu.exe Release 构建（`--config Release`）+ `pugixml.dll` 随包。
- [ ] PyInstaller `--onedir` spec：desktop_main.py + 服务器 + UI + 前置处理 + fixture + Pudu.exe + 引擎脚本。
- [ ] Audiveris 解包目录随包（**已拍板：随包再分发**，附 AGPL LICENSE + 源码获取链接）。
- [ ] 绿色版 ZIP 产出；可选 Inno Setup：开始菜单、`.pdf/.png/.musicxml` 文件关联、卸载清理。
- **验收**：干净 Windows 机器（无 Python）解压/安装后双击即用，全链路识别正常。

### 阶段 P4 — 验证与发布（0.5–1 天）

- [ ] 冒烟：新装机器全链路（PDF/图片 → MusicXML → 简谱 L1/L2/L3 + 反向转换）。
- [ ] 回归：与现网识别基线对比无劣化（引擎未动，应零回归）。
- [ ] 包体/启动速度核对；清理 `%APPDATA%` 生命周期。
- **验收**：发布清单齐备，可分发。

---

## 5. 已拍板决策（2026-08-13）

1. **Audiveris 再分发**：✅ **随包再分发**。解包目录随包，附带 AGPL-3.0 LICENSE 与源码获取链接；免费分发合规可接受，若将来商业收费需另行法律评估。
2. **oemer 回退**：✅ **不打包**。AV 缺失时显示降级提示 + fixture 演示兜底，节省 50–100MB 包体。
3. **安装形态**：✅ **绿色 ZIP + Inno Setup 安装包双形态**（ZIP 供网盘/内测，安装包供正式发布）。

> 三个决策均已拍板，P0（后端可移植化）可按计划启动。
