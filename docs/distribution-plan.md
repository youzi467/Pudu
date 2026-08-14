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

### 阶段 P1 — pywebview 壳（1–2 天）✅ 完成（2026-08-13）

- [x] `pip install pywebview`（venv 6.2.1，自动装 pythonnet/clr-loader → edgechromium/WebView2）。
- [x] 新建 `tools/desktop_main.py`：进程内起 HTTP（127.0.0.1:0）→ 端口落盘 → `webview.create_window(url)` → `webview.start(gui="edgechromium")`；`js_api` 暴露原生对话框；`--check` 无头验收模式；`PUDU_TEST_CLOSE_MS` 自动关窗（自动化用）。
- [x] 原生打开：`create_file_dialog(OPEN_DIALOG)` → 新增 `POST /api/open`（本地路径直投，复制进作业目录走同一 worker 管线）。
- [x] 原生保存：`create_file_dialog(SAVE_DIALOG)` 把作业结果（jianpu.html / final.musicxml / review.json）复制到用户选择路径。
- [x] 关窗优雅退出：`webview.start()` 返回后 `httpd.shutdown()` + `mgr.shutdown()`（取消作业/终止子进程）。
- [x] 前端桥（pudu_ui.html 保留原前端，仅加条件分支）：`isDesktop` 检测 → 上传区点击改走原生打开；结果区加「保存到本地…」原生条。
- **验收 ✅**：`--check` 无头（服务+端口+GET 200，exit 0）；`/api/open` 无效路径 400、真实 PNG 直投 200+job_id、引擎缺失正确 error 态；真实窗口 5s 自动关闭退出码 0。

### 阶段 P2 — 设置持久化 + 引擎引导（1 天）✅ 完成（2026-08-14）

- [x] `%APPDATA%/Pudu/settings.json`：默认引擎（audiveris/oemer）、`audiveris_exe`（→ `PUDU_AUDIVERIS_EXE` 注入子进程）、`oemer_model_dir`；GET/POST `/api/settings` + 服务端校验（非法引擎/坏 JSON → 400 明确错误）。
- [x] 引擎缺失引导横幅（前端内嵌）：所选引擎不可用 → 显示原因 + 「打开设置…」+「切换演示模式」；`GET /api/engines` 全引擎可用性报告（fixture 恒可用兜底）。
- [x] 设置面板（header 齿轮 ⚙）：默认引擎下拉 + Audiveris.exe 路径输入，桌面端原生 `.exe` 浏览（`pick_exe` js_api），保存即落盘生效。
- [ ] 首次运行向导：**（可选）跳过**——引擎检测已内置于引导横幅，等价覆盖该需求。
- **验收 ✅**：设置读写落盘往返（含反斜杠路径）、非法值 400、`_engine_env()` 注入 `PUDU_AUDIVERIS_EXE` 验证、`desktop_main.py --check` exit 0、真实窗口冒烟（页面加载即自动 `GET /api/settings`，即前端 bootstrap 拉取真实触发）。

### 阶段 P3 — PyInstaller 打包 + 安装包（1–2 天）✅ 完成（2026-08-14）

- [x] Pudu.exe Release 构建（`--config Release`，312KB）+ `pugixml.dll` 随包（VC++ CRT app-local 部署：msvcp140×3 + concrt140 + vccorlib140 一并打入）。
- [x] PyInstaller `--onedir` spec（`packaging/pudu_desktop.spec`）：desktop_main.py + 服务器 + UI + Pudu.exe + 引擎脚本（omr_audiveris.py / omr_oemer.py 以纯数据随包，由 **embeddable python** `runtime/python.exe` 子进程执行，不依赖系统 Python）；`console=False`（日志重定向 `%APPDATA%/Pudu/desktop.log`）。
- [x] Audiveris 解包目录随包（`audiveris/Audiveris/`，含打包 JRE；附 AGPL-3.0 LICENSE `AV_LICENSE.txt` + 源码链接声明 `AV_NOTICE.txt`）。
- [x] 绿色版 ZIP（`build/_pkg/dist/pudu-desktop-win64.zip`，107MB）+ Inno Setup 安装包（`build/_pkg/dist/PuduSetup-0.9.0-win64.exe`，86MB；`packaging/pudu_setup.iss` + 简体中文翻译）。**文件关联暂不做**——桌面壳尚不支持 argv 传文件打开（后续可加）。
- **验收 ✅**：打包产物 `--check` exit 0 + GET / 200；真实窗口（console=False）页面加载/设置拉取/自动关窗干净退出；**全链路识别**（POST /api/open → AV 引擎 → final.musicxml 98KB + jianpu.html 876 简谱数字，embeddable python→AV→Pudu.exe 在 frozen 环境端到端可用）；**fixture 演示**（/api/ocr demo=1 → done）；Inno 安装包静默安装到干净目录 → 主程序 `--check` exit 0 → 卸载器全清。注：真·干净机器（无 Python）未能实机验证，但引擎脚本走 embeddable python、CRT 随包、WebView2 为 Win11 自带，无系统 Python 依赖。

### 阶段 P4 — 验证与发布（0.5–1 天）✅ 完成（2026-08-14）

- [x] 冒烟：正向全链路（打包 app /api/open → AV → final.musicxml 98KB + jianpu.html 876 简谱数字，P3 已验证）；**反向转换**（打包 Pudu.exe `--from-jianpu-text` → `--to-musicxml` 产出 3738B MusicXML，调号/拍号/标题全对）；fixture 演示（demo=1 → done）。
- [x] 回归：**打包 frozen 环境 vs dev 逐字节一致（零劣化）**——同一 PDF 走 /api/open（打包，embeddable python→AV）与 dev omr_audiveris.py 双管道对比，262 音符/26 小节完全相同，唯一差异为 `<source>`/`source-file` 输入路径元数据（app 复制输入进作业目录属预期）。附带发现：`data/canon-in-d-violin-solo - 1.png` 该单张 PNG 在 AV 下报 "Error in export"（打包与 dev 行为一致，非打包回归，语料正主走 PDF）。
- [x] 包体/启动速度核对；清理 `%APPDATA%` 生命周期：
  - 包体：ZIP 107MB / 安装包 86MB（原始 217MB）；启动 headless 全流程 807ms。
  - **%APPDATA% 生命周期**：作业目录新增 7 天保留策略（`sweep_old_jobs`，启动时清扫超期 UUID 作业目录，防无限累积）+ desktop.log 1MB 轮转（.old）。现状：jobs 5 个共 ~972KB，port.txt/settings.json 均小文件。
- **验收 ✅**：发布清单齐备，可分发（见下）。

#### P4 发布清单（2026-08-14）

| 项 | 值 | 状态 |
| --- | --- | --- |
| 绿色 ZIP | `build/_pkg/dist/pudu-desktop-win64.zip`（107MB） | ✅ |
| 安装包 | `build/_pkg/dist/PuduSetup-0.9.0-win64.exe`（86MB，per-user 免 UAC） | ✅ |
| 合规 | AV 随包附 AGPL-3.0 LICENSE + 源码链接声明（随包 `audiveris/AV_LICENSE.txt` + `AV_NOTICE.txt`） | ✅ |
| 依赖 | 无系统 Python（embeddable 3.13.14 跑引擎脚本）；CRT app-local 随包；WebView2 为 Win11 自带 | ✅ |
| 启动 | headless 全流程 807ms | ✅ |
| 全链路 | 正向 AV 识别 + 反向简谱→MusicXML + fixture 演示 | ✅ |
| 回归 | 与 dev 输出逐字节一致（零劣化） | ✅ |
| 生命周期 | %APPDATA%/jobs 7 天保留 + desktop.log 1MB 轮转 | ✅ |
| 已知限制 | oemer 不随包（AV 缺失降级提示）；文件关联未做（壳不支持 argv 传文件）；干净机器实机未验（已论证无系统 Python 依赖） | 记录在案 |
| **发布** | **GitHub Release v0.9.0 已发布**（2026-08-14）：`https://github.com/youzi467/Pudu/releases/tag/v0.9.0`，双产物已上传（ZIP 107MB + 安装包 86MB）+ 发布说明（功能/依赖/已知限制） | ✅ 已发布 |

> **可分发条件齐备。** 发布动作（传网盘/打 release tag）由人执行；若需 `pudu.ico` 应用图标/文件关联可作后续增强。

---

## 5. 已拍板决策（2026-08-13）

1. **Audiveris 再分发**：✅ **随包再分发**。解包目录随包，附带 AGPL-3.0 LICENSE 与源码获取链接；免费分发合规可接受，若将来商业收费需另行法律评估。
2. **oemer 回退**：✅ **不打包**。AV 缺失时显示降级提示 + fixture 演示兜底，节省 50–100MB 包体。
3. **安装形态**：✅ **绿色 ZIP + Inno Setup 安装包双形态**（ZIP 供网盘/内测，安装包供正式发布）。

> 三个决策均已拍板，P0（后端可移植化）可按计划启动。
