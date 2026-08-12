# Audiveris A/B 定论：三投诉全面胜出，已实施迁移 · 2026-08-12

> 承接 docs/p0-analysis-canon-2026q3.md §4「换引擎 A/B 评估」。
> 用户决策闸门（原话）：**「若 Audiveris A/B 在 keysig/时值/小节三项明显胜出，再谈迁移」**。
> 本文为 15 页全量 A/B 的实测数据与判定。

> ✅ **2026-08-12 实施状态**：本文 §6 建议已落地为生产迁移——AV 成为默认引擎，
> oemer 保留为回退。实施物：`tools/omr_audiveris.py`（适配层，stdlib only）、
> `src/omr_adapter.cpp` audiveris 薄分支（净增 ≈0，红线不破）、
> `tools/pudu_server.py` 引擎分派（AV 默认）+ `tools/pudu_ui.html` 三引擎开关、
> `tools/omr_eval_groundtruth.py::run_audiveris`（评估入口）。基线已重立：
> AV 97.56%（13 共有页）为权威基线，oemer 84.5% 降为 fallback 口径。
> 多页 PDF 走 **AV 逐页 `-sheets N` 拼接**（整册 Book 模式因坏页拖垮弃用），
> 见 [omr-engine-feasibility.md](omr-engine-feasibility.md) §2.2 与实施计划
> `sorted-twirling-gizmo`。

---

## 0. 一句话结论

**Audiveris 5.11.0 在 keysig/时值/小节三项全部明显胜出**，决策闸门通过。

| 投诉 | 现状管线（无 GT） | Audiveris 5.11.0 | 判定 |
|---|---|---|---|
| #1 升降号未识别 | 9/13 页对（4 页欠数一个升降号） | **13/13 页全对** | AV 完胜 |
| #2 四分音符→十六分音符 | 节奏错误 346 处（rhythm pass 88.99%） | **节奏错误 24 处（rhythm pass 99.26%）** | AV 完胜（-93%） |
| #3 每小节总时值与拍号不符 | 拍号零输出（全靠下游注入）；ts 差异 6 页 | **7 页检测出拍号且全对**（含 2/4、3/4、6/4）；ts 差异 3 页（多页后继页无符号） | AV 完胜 |

**note_pass（13 共有页公平对比）：Audiveris 97.56% (3119/3197) vs 现状 84.5% (2656/3143)，+13.1pp。**

---

## 1. 实验设置（15 页全量，公平对比）

| 项 | 现状管线 | Audiveris |
|---|---|---|
| 语料 | `data/omr_eval/real/rerun_2026Q3`（当前工作树 fresh v2 preds，84.5% 定盘态） | `build/_av13`（15 页 PNG）→ `build/_av_eval13`（评估语料） |
| 引擎 | oemer + F3 + R-geo + 置信窗 v2 + 拍号注入（6de4bda 定盘） | Audiveris 5.11.0 `-batch -export`（内置 JRE，无 GT 注入） |
| 评测 | `tools/omr_eval_groundtruth.py --reuse-pred`（同 GT、同 harness、同口径） | 同上 |
| 成功率 | 13/15（canon_p2、summer_p5 fatal） | **14/15（仅 canon_p2 fatal；summer_p5 跑通 100%）** |

公平对比基准 = 13 共有页（两引擎都成功的页）。

---

## 2. 三投诉逐项对账

### #1 keysig：AV 13/13 vs 现状 9/13

| 页 | GT | 现状无GT | AV | 页 | GT | 现状无GT | AV |
|---|---|---|---|---|---|---|---|
| bach_p1 | 2 | 1 ✗ | 2 ✓ | summer_p1 | −2 | −2 ✓ | −2 ✓ |
| bach_p2 | 2 | 2 ✓ | 2 ✓ | summer_p2 | −2 | −1 ✗ | −2 ✓ |
| bach_p3 | 2 | 1 ✗ | 2 ✓ | summer_p3 | −2 | −2 ✓ | −2 ✓ |
| badinerie | 2 | 2 ✓ | 2 ✓ | summer_p4 | −2 | −2 ✓ | −2 ✓ |
| canon_p1 | 2 | 1 ✗ | 2 ✓ | swan-lake | 1 | 1 ✓ | 1 ✓ |
| prelude_p1 | 1 | 1 ✓ | 1 ✓ | the-swan | 1 | 1 ✓ | 1 ✓ |
| prelude_p2 | 1 | 1 ✓ | 1 ✓ | | | | |

- **现状 4 处错全为「欠数一个升降号」**（note-content 推断的信息论极限，见 p0-analysis §2）。
- **AV 通过图像 glyph 检测直接读取谱面键号**，13/13 全对——用户 PDF（canon_p1）从 1 升(G) 修回 2 升(D)。

### #2 时值：节奏错误 346 → 24（-93%）

| 页 | AV rhythm 错 | 现状 rhythm 错 | 页 | AV | 现状 |
|---|---|---|---|---|---|
| bach_p1 | 2 | 7 | summer_p1 | 1 | 13 |
| bach_p2 | 0 | 15 | summer_p2 | 11 | 52 |
| bach_p3 | 0 | 2 | summer_p3 | 2 | 9 |
| badinerie | 0 | 51 | summer_p4 | 0 | 3 |
| canon_p1（用户PDF） | **2** | **109** | swan-lake | 2 | 38 |
| prelude_p1 | 0 | 1 | the-swan | 4 | 25 |
| prelude_p2 | 0 | 21 | **合计** | **24** | **346** |

- canon_p1（用户投诉 PDF）**109 → 2**——R-geo 过缩塌缩页在 AV 下不复现。
- AV 节奏分布实测 canon_p1 181/40/37 ≈ GT 182/41/37（无塌缩）。

### #3 拍号与每小节时值

| 维度 | 现状 | AV |
|---|---|---|
| pred 内 `<time>` 输出 | **13/13 页零输出**（拍号靠 Pudu 下游 `inject_time_signature` 注入） | 7/13 页输出（badinerie 2/4、summer_p1 3/4、the-swan 6/4 等**非 4/4 页全对**） |
| ts 差异页数 | 6（badinerie、summer_p1-4、the-swan——恰全为非 4/4 页） | 3（summer_p2/3/4——多页 PDF 后继页图像无拍号符号，诚实缺省） |
| 小节时值总和 | 靠 R-geo + 拍号注入 + `mark_meter_constraint_failures` 打标兜底 | **时值本身正确（rhythm 99.26%）→ 小节总时值与拍号天然自洽** |

- 现状的 6 页 ts 差异全发生在**非 4/4 拍**（2/4、3/4、6/4）——注入逻辑对非 4/4 页失效。
- AV 的 3 页 ts 差异是「后继页无符号」而非「识别错误」——若用整谱多页输入（AV 原生支持整册 Book），第一页拍号即可继承。

---

## 3. note_pass 明细（13 共有页）

| 页 | AV | 现状 | 页 | AV | 现状 |
|---|---|---|---|---|---|
| bach_p1 | 96.1% (269/280) | 97.5% (272/279) | summer_p1 | 99.6% (274/275) | 95.2% (258/271) |
| bach_p2 | 100.0% (286/286) | 78.6% (198/252) | summer_p2 | 94.5% (292/309) | 83.6% (265/317) |
| bach_p3 | 100.0% (19/19) | 10.5% (2/19) | summer_p3 | 99.3% (302/304) | 97.0% (288/297) |
| badinerie | 100.0% (230/230) | 71.7% (162/226) | summer_p4 | 100.0% (324/324) | 96.2% (307/319) |
| canon_p1 | 99.2% (260/262) | 53.2% (134/252) | swan-lake | 94.4% (169/179) | 72.0% (126/175) |
| prelude_p1 | 100.0% (351/351) | 98.3% (345/351) | the-swan | 88.7% (118/133) | 75.2% (100/133) |
| prelude_p2 | 91.8% (225/245) | 79.0% (199/252) | **合计** | **97.56% (3119/3197)** | **84.5% (2656/3143)** |

- **AV 13 页全部 ≥88.7%**；现状 6 页 <85%（bach_p2 78.6、bach_p3 10.5、badinerie 71.7、canon_p1 53.2、prelude_p2 79、summer_p2 83.6、swan-lake 72、the-swan 75.2）。
- 现状仅 2 页（bach_p1、prelude_p1）微高于 AV，且差距 ≤1.7pp。
- 现状每页 `notes_compared` 明显低于 AV（bach_p2 252 vs 286、badinerie 226 vs 230、canon_p1 252 vs 262）——**oemer 漏读音符，AV 检出声量更大**。
- 另：summer_p5 现状 fatal、AV 100% (25/25)——AV 把一张 oemer 崩溃页救回。

---

## 4. AV 附带优势（对产品有价值的信号）

1. **检测声量更大**：多数页 AV 音符数 ≥ 现状（bach_p2 +34、prelude_p2 +30 等），漏读更少。
2. **fatal 页救回**：summer_p5 现状 oemer 崩溃 → AV 100%。仅 canon_p2 两引擎都失败（`No system found`，疑似图像本身不可读）。
3. **原生整谱 Book 支持**：多页 PDF 可整体处理，拍号/键号在全书传播（现状需逐页拼）。
4. **拍号识别**：非 4/4 拍（2/4、3/4、6/4）直接读出，无需下游注入。

---

## 5. 迁移代价（与 84.5% 定盘态比较，重述 p0-analysis §4）

| 维度 | 现状管线 | Audiveris 路线 |
|---|---|---|
| 引擎 | oemer（C++ + onnx，FROZEN） | Audiveris（Java，需重编译/adapter） |
| note_pass | 84.5% | **97.6%** |
| 键号 | 无 GT 时 9/13（统计 fallback） | **13/13 图像检测** |
| 时值 | R-geo 净正但 3 页塌缩 | **无塌缩** |
| 拍号 | 下游注入 + 打标兜底 | **图像检测** |
| 验收 | MusicXML 一等（music21 可读可再渲染） | MusicXML 原生（Audiveris 直接产 .mxl） |
| 成本 | — | adapter 重写 + Pudu 集成重建 + 基线重立（1-2 周级） |

**风险点（诚实列出）**：
- FROZEN 三件套（CMakeLists/vcpkg/omr_oemer.py）虽可零 diff 保留，但 adapter（`omr_adapter.cpp`）与 `omr_oemer.py` 的交互需重写为 `Audiveris.exe -batch` 子进程调用。
- 现状管线已验证的拍号注入/重切/打标/低置信兜底需在 AV 输出侧重实现（AV 已含大部分，但「需校对」标注体系是新工作）。
- 84.5%/91.7% 基线归零重立；测试套件（test_geometric_pitch 等）需适配 AV 输出。
- AV 在多页后继页不输出拍号——若产品保留逐页处理，需 AV 的整谱 Book 模式或拍号注入兜底。

---

## 6. 建议（决策闸门通过）→ 已实施

**判定：Audiveris A/B 在 keysig/时值/小节三项全部明显胜出（13/13 vs 9/13、24 vs 346、拍号检测正确率 100%），note_pass +13.1pp。按用户决策闸门 → 谈迁移。**

迁移建议路径 → **已落地（2026-08-12）**：
1. **保留现状管线为 fallback** ✅ —— `--omr-engine oemer` 分支零改动，84.5% 语料回归保留。
2. **搭 AV 集成骨架** ✅ —— `src/omr_adapter.cpp` audiveris 分支改调 `tools/omr_audiveris.py`
   （`Audiveris.exe -batch -export` 子进程，自带 JRE），`.mxl → .musicxml` 解包在适配层。
3. **补「需校对」标注** ✅ —— 沿用 `mark_meter_constraint_failures` 拍号校验打标
   （`<footnote>`「需校对：小节节拍不符」），无 sidecar 依赖；AV 低置信概念由拍号校验兜底。
4. **整谱 Book 优先 → 修正为逐页** ⚠️ —— AV 整册 Book 模式实测**坏页拖垮整本 export**
   （canon_p2 `No system found`），改走 **PDF 逐页 `-sheets N` + 顺序重编号拼接**：
   坏页单独 skip 不拖垮好页；页 2+ 首小节 attributes 保留使拍号继承/更新均正确。
   多页拼接验收用 bach（3 页全有 mxl）/ summer（5 页），canon 只覆盖「坏页跳过」分支。
5. 基线重立 ✅ —— AV 97.56%（13 共有页）为权威基线；oemer 84.5% 保留为 fallback 口径。

**验证物**：`build/_av13/out/*.mxl`（14 页）、`build/_av_eval13/omr_eval_report.json`（AV 97.58% 14页 / 97.56% 13页）、`data/omr_eval/real/rerun_2026Q3/omr_eval_report.json`（现状 84.5%）。

**实施产物**：`tools/omr_audiveris.py`（21 单测）、`tests/test_omr_audiveris.py`、
`src/omr_adapter.cpp` / `include/omr_adapter.hpp` / `src/main.cpp`（C++ 薄分支，净增 ≈0）、
`tools/pudu_server.py` + `tools/pudu_ui.html`（引擎分派 + 三引擎开关）、
`tools/omr_eval_groundtruth.py::run_audiveris`（评估入口 + wiring 单测）。

---

## 附：产物清单

- `build/_av13/`：15 页 PNG 输入 + `out/` 14 个 .mxl + .omr + 日志。
- `build/_av_eval13/`：评估语料（image+gt+AV pred）→ `omr_eval_report.json`（97.58%/94.43%）。
- `build/_audiveris/`：Audiveris 5.11.0 安装（含内置 JRE）与 5 页早期 A/B 验证。
- `docs/audiveris-ab-verdict.md`（本文）。
