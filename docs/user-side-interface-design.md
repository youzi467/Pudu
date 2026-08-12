# 用户侧界面 · 可行性调研与方案设计

> 日期：2026-08-10
> 状态：方案文档（未立项）。用户侧内容方向调研——引擎已就绪，缺一层 UI 壳。
> 关联：`docs/product-status.md`（对外口径 83.3%）、`docs/f3-abtest.md`（技术账本）、
> `docs/next-steps.md` §2 阶段5「GUI/工程化」、`docs/m2-increment-prd.md`（OMR 黑盒集成）。

---

## 1. 产品目标

给**非开发者用户**一个可交付入口：丢一张乐谱图片进去，得到**可打印的简谱 HTML + 标准 MusicXML**
（产品一等输出）+ 可见的「需校对」提示。同时服务两个场景：

- **真实使用**：乐手/老师把五线谱图片转成简谱和 MusicXML，供打谱软件/DAW/教学消费；
- **作品集演示**：不依赖 GPU、秒级出稿的演示路径（fixture 引擎）。

**当前唯一入口是命令行**（`Pudu.exe --from-omr <图> --to-jianpu-l2`），非开发者不可用——
本方案是给这条引擎补一层薄 UI 壳，**不碰 FROZEN 管线**（CMakeLists/vcpkg/omr_oemer.py 零改动）。

## 2. 现状盘点（2026-08-10 实测）

| 层 | 状态 | 依据 |
|---|---|---|
| OMR 引擎 | ✅ 可跑 | venv oemer 0.1.8 + 权重在位（seg_net/unet_big）；F3/R-geo 定盘 83.3% |
| 转换内核 | ✅ 已编译 | `build/Pudu.exe` 全参数可用（--to-jianpu* / --to-musicxml / --from-omr） |
| 简谱渲染 | ✅ 现成 | **L2 自包含 HTML**（浏览器直接打开，含八度点/减时线/连音弧）；真实谱例 406KB `jianpu_l2_cello.html` |
| 演示路径 | ✅ 零 GPU | `--omr-engine fixture`（C++ 原生确定性）→ 已实测秒出 L2 HTML |
| 需校对标记 | ⚠️ 仅 XML 内 | 定盘 29 个 `<footnote>需校对：几何时值未校正`，用户侧不可见 |
| UI 工具链 | ⚠️ 受限 | tkinter 仅系统 python（8.6，venv 无）；无 flask/PySide；**stdlib `http.server`+`webbrowser`+`threading` 可用** |

**推论**：引擎是成品，缺的是壳。**能，而且现在就能做用户侧内容。**

## 3. 用户故事

- 作为**非开发者**，我把乐谱图片拖进界面，等识别完成后拿到可打印简谱 + 标准 MusicXML，无需碰命令行；
- 作为**乐手**，我下载 MusicXML 导入打谱软件，同时看到一个「需校对：N 处」面板，知道哪些音几何校正跳过了；
- 作为**演示者**，我用 fixture 模式秒出稿，离线零 GPU 演示全链路；
- 作为**维护者**，我加一个 UI 壳而不改内核——FROZEN_PATHS 零 diff，端口本地绑定不暴露外网。

## 4. 方案选项与选型

| 方案 | 形态 | 依赖 | 工作量 | 适合 |
|---|---|---|---|---|
| **A. 本地网页应用** | 浏览器上传 → 简谱预览 + MusicXML 下载 + 需校对面板 | **零新依赖**（stdlib） | 小 | **推荐**：复用 L2 渲染，作品集天然可展示，跨平台 |
| B. 桌面 GUI | tkinter 文件选择 + 进度 + 内嵌预览 | 系统 python（venv 无 tkinter），跨解释器 shell out | 中 | 需要原生窗口/离线分发的场景 |
| C. 一键 CLI 包装 | 图片拖进 .bat/py 即出 HTML | 零 | 最小 | 给自己/技术用户用，非产品形态 |
| D. 只出演示页 | 整理既有 L2 HTML + 报告成作品集页 | 零 | 最小 | 纯展示，无交互 |

**选型：A（推荐）**。理由：
1. **复用最多**——L2 渲染器、CLI、footnote 解析全现成，只写薄壳；
2. **零安装零依赖**——`http.server` 是 stdlib，浏览器人人有；纯本地 `127.0.0.1` 不暴露外网；
3. **作品集友好**——浏览器即产品形态，演示和交付是同一条路；
4. **规避 tkinter 跨解释器难题**——服务器跑在 venv python（有 oemer 依赖），子进程调 Pudu.exe，无系统/venv 双 python 撕裂。

## 5. 推荐方案 A 详细设计

### 5.1 架构总览

```
┌───────────── 浏览器（127.0.0.1:PORT）─────────────┐
│ 上传区 → 进度条 → 页签[简谱预览|MusicXML+需校对|报告] │
└────────────────────┬──────────────────────────────┘
                     │ HTTP (fetch, 轮询)
┌────────────────────▼──────────────────────────────┐
│  tools/pudu_server.py  （venv python, stdlib only） │
│   http.server + threading + json + subprocess       │
│  · POST /api/ocr        起后台线程识别              │
│  · GET  /api/status/<id> 轮询进度/错误              │
│  · GET  /api/result/<id>/jianpu.html  简谱预览      │
│  · GET  /api/result/<id>/<name>.musicxml  下载      │
│  · GET  /api/result/<id>/review.json   需校对面板   │
│  作业目录 build/_ui_jobs/<id>/  (gitignored)        │
└───────────────┬─────────────────┬─────────────────┘
                │ 子进程/import    │ 子进程
                ▼                  ▼
   tools/omr_oemer.py <img>   build/Pudu.exe <mx>
   (oemer 识别 + F3/R-geo，   (L2 简谱 HTML + MusicXML
    --f3-geometric --rhythm-   成品，几何/标记已落盘)
    geometric --preprocess)
```

### 5.2 识别管线（后台线程，一次作业）

1. `POST /api/ocr` 接收图片 → 落盘到作业目录，起 worker 线程；
2. 子进程 `venv python tools/omr_oemer.py <img> --f3-geometric --rhythm-geometric` →
   产出 `<base>.pred.musicxml` + `.geometry.json`（此即识别 + F3/R-geo 校正 + 需校对 footnote）；
3. import `geometric_pitch`：`repair_forward_overflow` + 定点重跑一遍（复用定盘逻辑，见 `build/_rerun_fixedpoint.py`），
   保证交付态与定盘 83.3% 口径一致；
4. 子进程 `build/Pudu.exe <pred.musicxml> --to-jianpu-l2 <out.html>` 出简谱；
5. 解析 `<footnote>` → `review.json`（按 measure/音符位置归并）；
6. 状态置 done，前端轮询拿到结果。

> **fixture 演示模式**：URL 参数 `?demo=1` 走 `--omr-engine fixture`（零 GPU，秒级），同一套 UI 全链路可演示。

### 5.3 前端（单 HTML，原生 JS，零依赖）

```
┌──────────────────────────────────────────────────────┐
│  谱渡 Pudu · 图片转简谱/MusicXML            [引擎: 真实│demo] │
├──────────────────────────────────────────────────────┤
│  ╔══════════════════════════════════════════╗         │
│  ║  [拖拽乐谱图片到这里，或点击选择]          ║         │
│  ║  PNG / JPG · 单页 · 最高约 4000×4000       ║         │
│  ╚══════════════════════════════════════════╝         │
│  [识别中… ▓▓▓▓▓▓░░░░ 62%]  识别 + 几何校正 + 简谱渲染    │
├──────────────────────────────────────────────────────┤
│  简谱预览 │ MusicXML │ 需校对         ←页签            │
│  ┌──────────────────┐  ┌────────────────────────────┐ │
│  │  <iframe: 简谱L2>  │  │ ① 下载 final.musicxml      │ │
│  │  可直接打印        │  │ ② 需校对 2 处：            │ │
│  │                   │  │    · 小节 12 第 3 音 时值未校正│ │
│  └──────────────────┘  │    · 小节 17 第 1 音 时值未校正│ │
│  【下载 MusicXML】【打印】└────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 5.4 需校对面板（MVP 形态）

footnote 不注入简谱内（改 C++ `jianpuToL2` 成本高），MVP 用侧栏面板：
- 从 `final.musicxml` 解析 `<notations><footnote>`，按 measure/音符序归并；
- 面板列出「需校对：几何时值未校正 ×2」，附所在小节；
- 下载的 MusicXML 即含 footnote（一等输出的保真承诺不变）。

完整版（P2）：改 C++ 渲染器在简谱 HTML 里给被标记音符打角标——高成本，见 §8。

### 5.5 契约（HTTP API 草稿）

| 方法 | 路径 | 入参 | 返回 |
|---|---|---|---|
| GET | `/` | — | 单页 HTML |
| POST | `/api/ocr` | multipart 图片 + `?demo=1` 可选 | `{job_id}` |
| GET | `/api/status/<job_id>` | — | `{state: queued|running|done|error, progress, message, error}` |
| GET | `/api/result/<job_id>/jianpu.html` | — | 简谱 L2 HTML（内嵌，预览） |
| GET | `/api/result/<job_id>/final.musicxml` | — | MusicXML 下载（`Content-Disposition: attachment`） |
| GET | `/api/result/<job_id>/review.json` | — | `{total, items: [{measure, index, reason}]}` |

## 6. 需求池（优先级）

### P0（MVP，~0.5–1 天）
- `tools/pudu_server.py`：stdlib HTTP 服务 + 作业目录 + 后台线程 + 进度轮询；
- 识别管线：oemer + F3/R-geo + forward 修复 + 定点重跑 + L2 渲染（全部走既有 CLI/模块）；
- 前端单页：上传 → 进度 → 简谱预览 iframe + MusicXML 下载；
- **需校对面板**（解析 footnote）；
- **fixture 演示模式**（`?demo=1`，零 GPU）；
- 错误兜底：oemer 不可用 / 超时 / 非图片 → 明确报错（对齐 product-status §5「失败页明确报错」）；
- 端口本地绑定 `127.0.0.1`，作业目录 `build/_ui_jobs/`（gitignored）。

### P1（增强，~0.5 天）
- `--omr-preprocess` 前置增强对照预览（拍照/低对比度谱面）；
- 多图批量排队；
- 识别报告页（含 83.3% 口径、29 个需校对的解释文案）。

### P2（深度集成，~1–2 天，需 C++ 改动）
- 简谱 HTML 内注「需校对」角标（改 `jianpuToL2` + `score_model` 透传）；
- 多页 PDF 按页切分识别（oemer 单图输入，需分页预处理）；
- 页级失败降级展示（canon_p2/summer_p5 类）。

## 7. 验收标准（对应 P0）

- **fixture 模式**：上传 → <3s 出简谱 HTML + MusicXML，离线可演示；
- **oemer 模式**：真实图片端到端产出可下载 `final.musicxml`（music21 可读可再渲染）+ 简谱 HTML（浏览器无 JS 错误可打印）；
- **需校对面板**与语料定盘态一致（29 处、全「几何时值未校正」），下载的 MusicXML 含 footnote；
- **零新依赖**：仅 stdlib + 既有 venv/Pudu.exe；`CMakeLists.txt`/`vcpkg.json`/`tools/omr_oemer.py` 零 diff；
- 端口仅监听 `127.0.0.1`；服务崩溃/取消不留僵尸进程（作业线程 join + 超时 kill）。

## 8. 风险与边界

| 风险/边界 | 影响 | 缓解 |
|---|---|---|
| oemer 每页分钟级（GPU 依赖） | 长等待 | 进度轮询 + 可取消；fixture 演示秒级兜底 |
| 多页 PDF 非 MVP | 用户一次只能传一页 | UI 明示「单页」；P2 按页切分 |
| 需校对高亮在简谱内需改 C++ | MVP 做不到角标 | MVP 用侧栏面板；P2 改渲染器 |
| 服务与 venv 耦合 | 换环境要重建 venv | 启动脚本检测 venv python 缺失时明确报错 |
| 大图内存 | 4000×4000+ 可能 OOM | 前端限制尺寸 + 服务端报错兜底 |
| GitHub 不可达 | 不影响 | 纯本地工具，无外网调用 |

## 9. 结论与下一步

**可行性已实测确认**：引擎全链路可跑（含真实 oemer），L2 HTML 渲染现成，fixture 零 GPU 演示路径已通，
stdlib 足以支撑浏览器 UI——用户侧内容**现在就能做**。

推荐路径：**A 本地网页应用**，P0 单文件 `tools/pudu_server.py` + 单页前端，0.5–1 天完成「图片 → 简谱 + MusicXML + 需校对」闭环。
不碰 FROZEN 管线，作品集演示与真实交付同一条路。
