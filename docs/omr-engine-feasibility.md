# 谱渡 Pudu · OMR 引擎替换可行性分析

> 作者：高见远（架构师）｜日期：2026-08-06｜性质：**纯分析文档，不含任何代码改动**
> 议题：把现有 OMR 引擎从 `oemer 0.1.8` 换成更强引擎，是否可行、代价几何、能否摸到 80%。
> 代码基线：`70391ab`（docs: 新增 MVP 范围 / 验收 PRD）

---

## 0. 执行摘要（先给结论）

| 问题 | 结论 |
|---|---|
| **集成成本** | **低**（换 Python 系引擎 ≈ 1.5～2.5 人日）｜**中**（换 Audiveris ≈ 3～5 人日，因现有分支是**错的**） |
| **最推荐候选** | **homr**（cairn-labs/liebharc）—— oemer 的直系强化版，CLI 契约几乎逐字兼容，同一 Python+onnxruntime+CUDA 栈 |
| **单换引擎能否到 80%** | **音名口径已达标**（R1 后可信基线 `pitch_degree` 99.94%）；**真实短板是八度 64.4% 与节奏 52.1%**——需攻这两项，而非为音名换引擎（见 §1/§4/§6 的 R1 更新） |
| **最关键前置依赖** | ✅ **已解决（R1，2026-08-08）**：`_merge_align` 已改整 part Needleman–Wunsch 全局对齐，可信基线已产出 |

> [!WARNING]
> **本文最重要的发现不是"换哪个引擎"，而是：立项依据（`pitch_degree` 13.6%）大概率是评测 harness 的测量假象，不是 oemer 的真实音名能力。**
> 若不先修标尺就换引擎，新引擎会被同一把坏尺子量出同样的 ~14%，从而得出"新引擎也不行"的错误结论，白白浪费 2～4 周。

> [!CAUTION]
> **主理人独立核验更新（2026-08-06，齐活林）：本文 §1.4 的 91.6% / 55.0% 未能独立复现。**
> 用 `difflib` 序列对齐对同批 6 页语料独立重算：step **38.4%** / step+octave **25.7%**；随机打乱对照 step 31.8% / step+octave 23.1%（对齐与打乱几乎无差，无强有序信号）。
> 同一批数据，harness 给 13.6%、本独立重算给 25.7%、本文 LCS 估计给 55%——**三法差距巨大，恰恰证明评测标尺本身已坏**。
> **结论修订**：在 `_merge_align` 改为 Needleman–Wunsch 全局对齐（R1, ~1 人日）之前，**任何准确率数字（13.6% / 25.7% / 55% / 91.6%）都不可采信**。"oemer 真实音名已 ~90%、真正短板是八度"目前属**待证假设**，而非已证实结论。详见文末附录 A。

> [!NOTE]
> **R1 已完成（2026-08-08）**：`_merge_align` 已改为整 part Needleman–Wunsch 全局保序对齐（以音高为锚、容增删；`tools/omr_eval_lib.py`）。6 页 concerto 语料重算可信基线（`--reuse-pred`，pred/gt 与 §1.4 同批）：
> **`pitch_degree` 13.56% → 99.94%**（notes_compared 944→1723、event_count 1926→368）、`pitch_octave` 60.3% → 64.4%、`pitch_accidental` 84.2% → 100%、`rhythm` 46.7% → 52.1%。
> 两套独立锚（绝对 degree / 相对音程轮廓）交叉验证收敛 ~99.9%、随机打乱对照 ~26%，排除评分循环论证。**"oemer 真实音名已 ~90%"假设被证实（实为 99.9%）**；**"真正短板是八度"被证实**（`pitch_octave` 64.4% + `rhythm` 52.1%）。本文 §4/§6 中所有"R1 后重测"的结论按此基线更新。

---

## 1. 核心发现：`pitch_degree` 13.6% 是测量假象

这是本次分析的头号产出，优先级高于引擎选型本身。

### 1.1 疑点：13.56% ≈ 随机猜测

现基线（`data/omr_eval/real/concerto_pages/omr_eval_report.json`，已核验）：

```
notes_compared = 944,  note_pass_rate = 2.65%,  field_pass_rate = 32.04%
category_pass: pitch_degree 13.56 | rhythm 46.72 | pitch_octave 60.28
               pitch_accidental 84.22 | octave_jump 95.76 | rest 97.35 | tie 99.58
```

七个自然音级（C D E F G A B）随机猜测的期望命中率是 **1/7 = 14.3%**。
实测 `pitch_degree` = **13.56%**——**恰好落在随机基线上，且略低于它**。

一个能把休止符认对 97%、连音线认对 99.6%、临时记号认对 84% 的引擎，不可能在最基础的"符头在第几线"上退化到掷骰子水平。这个数字组合在物理上自相矛盾。

### 1.2 证伪原有归因：不是 off-by-one 几何偏置

项目既有归因是"符头中心对插值中心 `argmin`/`round` 系统偏置 → off-by-one"（见 `SESSION_SUMMARY_OMR_2026-07-17_18.md:85`、`docs/system_design.md:19`）。若成立，错误应**高度集中在 ±1 级**。

实测 816 个 `pitch_degree` 失败音符的音级偏移分布（`(actual - expected) mod 7`）：

| 偏移 | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| 计数 | 4 | 147 | **164** | 120 | 120 | 116 | 145 |

**近乎均匀分布**，偏移 2（164）甚至多于偏移 1（147）。全音阶位置差（含八度）同样宽泛铺开：`-1:91, +2:90, +1:85, -2:63, -3:61, +3:58, -5:49 …`

> **这不是 off-by-one 的形状，这是随机配对的形状。** 这也解释了为什么 F3 几何校正器全量 A/B 是 `OFF == ON` 逐字节相同、零效果——**F3 打的靶子从一开始就不存在**。

### 1.3 定位根因：positional fallback 对齐

阅读 `tools/omr_eval_lib.py:182 _merge_align()`：

- **阶段 1**：按 `(part, onset)` 容差（`tol=0.03`）合并。
- **阶段 2 fallback**：docstring 自陈——"oemer 的时值识别会漂移，使 pred 音符的 onset 相对 gt 偏移超过 tol（**极端时整页 onset 爬到 ~2298 而非 ~96**）"，于是把所有"孤独音符"按 `(part, measure)` 内**序列位置** i 对 i 强行 1:1 配对，并注明"**该 fallback 是启发式**"。

因果链清楚了：

```
rhythm 只有 46.72%  →  onset 大幅漂移  →  阶段 1 onset 匹配大面积失败
                    →  绝大多数音符落入阶段 2 positional fallback
                    →  同一小节内 pred/gt 音符数不等时，按位置 i 对 i 配对的是「不相干的两个音符」
                    →  音级比对退化为随机  →  pitch_degree ≈ 1/7
```

实测每页音符数确实不等（小节数除 p6 外均对齐）：

| 页 | GT 音符 | PRED 音符 | GT 小节 | PRED 小节 |
|---|---|---|---|---|
| p1 | 280 | 302 | 28 | 28 |
| p2 | 249 | 270 | 24 | 24 |
| p3 | 327 | 303 | 24 | 24 |
| p4 | 319 | 309 | 40 | 40 |
| p5 | 285 | 345 | 50 | 50 |
| p6 | 416 | 292 | **74** | **48** |

每小节只要有 1 个增/漏音符，其后所有音符的配对就整体错位——这正是"逐音随机错"的成因。

### 1.4 决定性实验：换成序列对齐后重新测量

用**保序、容忍增删**的序列对齐（LCS / difflib）替代 positional 配对，对同一批 pred/gt 文件重算（只读分析，未改动任何项目文件）：

| 口径 | 序列对齐 recall | 随机打乱对照 | 提升 |
|---|---|---|---|
| **step only**（== `pitch_degree` 口径） | **91.6%** | 20.3% | **+71.3 pp** |
| **step + octave**（更严格） | **55.0%** | 14.6% | **+40.4 pp** |

分页 step+octave recall：p1 68.6% / p2 49.4% / p3 36.1% / p4 **72.7%** / p5 65.6% / p6 43.0%

**"随机打乱对照"是关键**：把 pred 序列随机打乱后重测，step 口径只剩 20.3%、step+octave 只剩 14.6%。真实值远高于对照，证明 oemer 输出中存在**强有序真实信号**，不是运气。

> [!IMPORTANT]
> **harness 报告"13.56% 的音符 step 对"；序列对齐显示"55.0% 的音符 step 和 octave 同时对"。**
> 后者是**更严格**的判据却给出**高 4 倍**的结果——这在逻辑上只可能有一个解释：**13.56% 测的不是 oemer 的音名能力，测的是 harness 的配对能力。**

**诚实的方法学说明**：LCS 是保序对齐下匹配数的**上界**（它可以"挑着匹配"），因此 91.6% / 55.0% 偏乐观，不能直接当作最终准确率。严谨做法是 Needleman–Wunsch 全局对齐 + 替换罚分（即建议 §6.1 的 1 人日任务）。但**结论的方向是稳健的**：真实音名准确率显著高于 13.6%，量级在 50%～90% 之间而非随机水平。

> [!NOTE]
> **独立核验（2026-08-06，主理人）**：上述 91.6% / 55.0% 用 `difflib` 序列对齐独立重算**未能复现**。同批 6 页语料重算得 step **38.4%** / step+octave **25.7%**；随机打乱对照 step 31.8% / step+octave 23.1%。对齐结果与打乱对照差距很小（38.4% vs 31.8%），说明该 LCS 方法未提取到强有序信号。三法（harness 13.6% / difflib 25.7% / 本文 55%）结果发散，**唯一稳健结论是评测标尺已坏**，详见 §附录 A 与 §6.1。

### 1.5 推论：真正的短板是八度，不是音名

step 口径 91.6% 而 step+octave 只有 55.0% —— 差距几乎全部由**八度**贡献。这与 harness 自己的 `pitch_octave 60.28%` 交叉印证（0.916 × 0.60 ≈ 0.55 ✓，三个独立数字自洽）。

> [!WARNING]
> **上述推论依赖 91.6% 这个未独立复现的数字（见 §1.4 注记与附录 A）。** 主理人独立重算 step 仅 38.4%（step+octave 25.7%），因此"真实短板是八度、音名已 ~90%"目前只能作为**强假设**，不能在标尺修好（R1）前作为已证实结论使用。

**这直接推翻了项目当前的核心假设。** 现有文档（`README.md:38`、`docs/jianpu-ocr-optimization-plan.md:383`、`docs/system_design.md:7`）一致把 `pitch_degree`（音名）列为"最弱短板 / 优化靶心"，并据此设计了 F3 几何校正器（零效果）与 M2-opt-C 规则引擎（待做）。实际短板是**八度归属**（加线区判定、clef/track 归属）。

顺带解释了另一个长期困惑：`README.md:38` 记载"P1-1 后处理规则引擎无法修复 `pitch_degree`，因为转换后绝对音高已坍缩为首调音级"。如果音名本来就有 ~90% 正确，那这条限制的实际影响远小于预估。

---

## 2. 集成可行性评估：接缝有多好用？

### 2.1 现有接缝盘点（已读码核验）

`src/omr_adapter.cpp` / `include/omr_adapter.hpp` 的设计是**干净的**，替换引擎的架构准备确实到位：

| 设计点 | 现状 | 对换引擎的价值 |
|---|---|---|
| `runOmr()` 按 `cfg.engine` 字符串分派 | ✅ 已实现（`fixture` / `oemer` / `audiveris`） | 加分支即可，不动调用方 |
| 子进程统一封装 `runCommand()` | ✅ CreateProcess + 超时 + stdout/stderr 捕获 | 新引擎直接复用，零成本 |
| `isOmrEngineAvailable()` 可用性探测 | ✅ 每引擎独立实现 | 新引擎照抄模式 |
| 产物校验 `outputLooksValid()` | ✅ 只检查 `<score-partwise\|timewise>` 根 | **引擎无关**，核心有利前提 |
| 下游耦合 | ✅ 仅通过**文件系统**交付 MusicXML，不 include 任何数据模型头 | **零模型改动**，真正的黑盒边界 |
| CLI `--omr-engine <name>` | ✅ 泛型透传（`main.cpp:104`） | 新引擎名无需改 CLI 解析 |

**结论：接缝设计本身值满分。** 下游 `MusicXMLParser` 只读标准元素（`pitch/step/alter/octave`、`duration`、`type`、`time-modification`、`tie`、`rest`、`chord`、`grace`、`key/fifths/mode`、`clef`、`time`、`divisions`、`barline`），全部是任何合规 OMR 引擎都会输出的 MusicXML 子集。**下游解析器预计零改动。**

### 2.2 但是：`audiveris` 分支是**不可达的死代码，且命令行是错的**

任务书假设"audiveris 分支已经写好了，只是没配 jar"。**核验结果：比这更糟——它从未被执行过，且即使配了 jar 也跑不通。**

**问题 A：`audiverisJar` 无任何赋值路径 → 分支 100% 不可达**

`main.cpp:98-114` 的 CLI 循环只解析 4 个参数：`--from-omr` / `--omr-engine` / `--omr-python` / `--omr-preprocess`。**没有 `--audiveris-jar`**。全库 grep 确认 `audiverisJar` 仅出现在 `omr_adapter.{hpp,cpp}` 与文档中，无任何写入点。

因此 `cfg.audiverisJar` 恒为空 → `isOmrEngineAvailable()` 在 `main.cpp:132` 处必然返回 false（`omr_adapter.cpp:238`）→ 程序在 `runOmr` 之前就退出。**该分支自诞生起从未被执行过一次。**

**问题 B：命令行模板与 Audiveris 真实 CLI 不符（5 处错误）**

现有代码（`omr_adapter.cpp:188`）：
```cpp
cmd = "java -jar \"" + cfg.audiverisJar + "\" \"" + input + "\" -o \"" + outMusicXml + "\"";
```

对照 Audiveris 官方 CLI 文档（`Audiveris/audiveris` wiki 与 `docs/_pages/advanced/cli.md`）：

| # | 错误 | 后果 |
|---|---|---|
| 1 | **缺 `-batch`** | 启动 **GUI**，子进程永不退出 → 撞 120 s 超时，返回 `-2` |
| 2 | **缺 `-export`**（或 `-transcribe`） | 根本不导出 MusicXML |
| 3 | **`-o` 不是合法选项** | Audiveris 只认 `-output`；args4j 会报 unknown option 并失败 |
| 4 | **`-output` 是「目录」不是「文件」** | 产物路径由引擎按 `<output>/<bookname>/<bookname>.mxl` 自行拼装，不会落在 `outMusicXml` |
| 5 | **默认导出 `.mxl`（ZIP 压缩包）** | `outputLooksValid()` 按纯文本搜 `<score-partwise` → **必然失败**。需 `-option org.audiveris.omr.sheet.BookManager.useCompression=false` 才出明文 `.xml` |

**问题 C：`java -jar` 这个调用形态本身已过时**

Audiveris **自 5.5 起改为 jpackage 原生安装包（Windows `.msi`），自带 JRE，不再提供可直接 `java -jar` 运行的 fat jar**。当前版本为 **5.7.0 / 5.8.1**（winget 显示 5.8.1）。正确形态是调用安装后的 `Audiveris.exe`（CLI 场景建议装 `windowsConsole` 变体以便回显错误）。

> ⚠️ **安全提示**：`audiveris.com` 是**钓鱼站**（官方 README 明确警告：链接跳转加密货币/博彩页面）。正版仅在 GitHub `Audiveris/audiveris` 的 Releases。

**修正后的正确命令形态**（示意，非落地代码）：
```
"<AudiverisDir>\Audiveris.exe" -batch -export ^
  -option org.audiveris.omr.sheet.BookManager.useCompression=false ^
  -output "<tempDir>" -- "<input>"
```
再由适配层在 `<tempDir>/<basename>/` 下定位 `<basename>.xml` 并移动/改名到 `outMusicXml`。

### 2.3 Python 侧后处理的引擎耦合度

| 后处理 | 位置 | 耦合度 | 换引擎影响 |
|---|---|---|---|
| **Plan A 调号推断** `correct_key_signature(out_path, gt_path)` | `omr_oemer.py:376` | **引擎无关** —— 直接对输出 MusicXML 做 ElementTree 操作 | ✅ 可直接复用 |
| **F3 几何 sidecar** `_patch_oemer_for_sidecar()` | `omr_oemer.py:552` | **强耦合** —— `import oemer.ete` / `oemer.build_system` / `from oemer import layers`，monkey-patch oemer 内部 | ❌ 换引擎即失效 |
| **P0-2 图像预处理** | `omr_pipeline.py`（`omr_oemer.py` 的透明代理） | **引擎无关** —— 只在输入侧增强图像后转发 | ✅ 可直接复用 |
| **P1-1 后处理规则引擎** | `src/jianpu_postcorrect.cpp` | **引擎无关** —— 作用在 Score/JianpuDoc 层 | ✅ 可直接复用 |

> **好消息**：唯一与 oemer 强耦合的是 **F3**，而 F3 已被全量 A/B 证实**零效果、默认 OFF、未上线**（`docs/f3-abtest.md`）。§1.5 更进一步说明 F3 的靶子本来就不存在。**换引擎时直接放弃 F3 即可，无实质损失。**

### 2.4 改动量量化

**方案甲：换 Python 系引擎（homr / Clarity-OMR）**

| 文件 | 改动 | 估计 |
|---|---|---|
| `include/omr_adapter.hpp` | 注释 + 可选新增配置字段 | ~5 行 |
| `src/omr_adapter.cpp` | `runOmr` 加分支 + `isOmrEngineAvailable` 加分支 | ~25 行 |
| `src/main.cpp` | 复用/推广 `resolveOmerPython` 的解释器选址 | ~5 行 |
| `tools/omr_<engine>.py` | **新增**驱动脚本，照抄 `omr_oemer.py` 的 out_path 契约 + 复用 `correct_key_signature` | ~80～150 行（新文件） |
| `tests/` | ctest / pytest 用例 | ~50 行 |

⚠️ **注意暗礁**：`tests/test_cpp_preprocess_switch.py:210` 会**正则截取 `runOmr` 中 `if (cfg.engine == "oemer")` 的分支体做逐字节比对**。新增分支时若不慎改动 oemer 分支的格式，该测试会红。这是个容易踩的坑。

**合计：≈ 1.5～2.5 人日**（不含评测与调参）。

**方案乙：修复并启用 Audiveris**

在方案甲基础上额外需要：新增 `--audiveris-path` CLI 参数、重写命令模板、实现"从 book 目录定位产物并搬运"、处理 `.mxl` 解压兜底、Tesseract OCR 语言包安装（Audiveris 自 5.5 起 OCR 语言不预装）。

**合计：≈ 3～5 人日。**

### 2.5 MusicXML 兼容性风险

| 风险 | 等级 | 说明 |
|---|---|---|
| 根元素 | **低** | `musicxml_parser.cpp:72` 只接受 `score-partwise`，而 `outputLooksValid` 也接受 `timewise` → 存在不一致缝隙。三个候选引擎均输出 partwise，实际不触发 |
| MusicXML 版本 | **低** | Audiveris 输出 4.0 子集、homr/Clarity 输出 3.x/4.x；解析器按元素名读取，不校验版本号 |
| `.mxl` 压缩包 | **中**（仅 Audiveris） | 见 §2.2 问题 B-5 |
| 命名空间 | **低** | `omr_oemer.py:86` 已有 `_strip_ns()` 处理；C++ 侧 pugixml 按裸标签名查找 |
| 多声部 / `backup`/`forward` | **中** | 更强的引擎可能输出 Pudu 目前跳过的多声部结构；`jianpu_postcorrect` 的 BeatReconcile 对多声部整条跳过（已知边界） |

---

## 3. 候选引擎清单与逐项可行性

### 3.1 homr（cairn-labs / liebharc）— **首选**

| 维度 | 评估 |
|---|---|
| **可用性** | **高** |
| **许可** | 开源（GitHub），持续活跃：最近提交 2026-03/04，300+ stars，3 名贡献者 |
| **技术路线** | 两阶段：① **复用 oemer 的 UNet 分割**做结构分析；② **Polyphonic-TrOMR Transformer** 做语义符号序列识别；**关键：音高信息与分割模型的符头数据交叉校验** |
| **运行环境** | Python 3.11 + Poetry，可选 NVIDIA CUDA 12.1，**onnxruntime**（2026-03 刚更新）→ 与本机 RTX 5060 + CUDA 13.3 + 现有 oemer 栈**同源** |
| **输出契约** | `poetry run homr <image>` → MusicXML 落在输入同目录，**与 oemer 逐字同构** |
| **集成动作** | 新增 `tools/omr_homr.py`（可 ~90% 复制 `omr_oemer.py`）+ adapter 加分支 |
| **周估** | **1.5～2 人日** |
| **对 pitch/octave 的提升潜力** | **高**。oemer 的音高是**纯几何**推断（`staff_line_pos` + clef/track），这正是八度错误的根源；homr 用 Transformer **语义**识别 + 符头交叉校验，**恰好打在 §1.5 定位的真实短板（八度）上** |
| **第三方佐证** | 首个独立开源 OMR 横评中 **homr 夺冠**（基准集偏重复杂钢琴谱，非其主场仍胜出） |
| **已知短板** | 聚焦高低音谱号的音高/节奏，忽略力度、演奏法、重升重降 —— 对 Pudu 的 MVP 域（单声部、≤2 升降号、无装饰音）**完全够用** |
| **关键风险** | Poetry 依赖管理需并入现有 venv 方案；Blackwell（sm_120）架构的 onnxruntime-gpu 兼容需实测（但 oemer 已跑通 GPU，风险可控） |

### 3.2 Audiveris 5.7 / 5.8 — 稳健对照组

| 维度 | 评估 |
|---|---|
| **可用性** | **中**（Windows 可用性高，但现有代码分支需重写） |
| **许可** | **AGPL-3.0** —— 子进程调用属独立进程，一般不触发传染；但**若未来随 Pudu 分发打包，需法务确认** |
| **运行环境** | Windows `.msi` 安装包**自带 JRE**（免装 Java）；亦可 `winget install Audiveris`。**注意：自 5.5 起无 fat jar，`java -jar` 形态失效** |
| **输出契约** | MusicXML **4.0** 子集，默认 `.mxl`（ZIP）；需 `useCompression=false` 出明文 |
| **集成动作** | 见 §2.2，需**重写**而非"配个 jar" |
| **周估** | **3～5 人日** |
| **对 pitch/octave 的提升潜力** | **中**。规则/模板 + 神经网络混合，谱线与符头几何处理成熟，对**干净印刷谱的八度/加线**判定通常比纯几何外推稳；但第三方横评显示其在干净谱上得分 **25.9**，明显低于 Clarity-OMR 的 69.5 |
| **已知短板** | OCR 语言包不预装（首次需下载 Tesseract 语料）；官方自陈"100% 识别率不可达，依赖人工编辑器纠错"；`audiveris.com` 为**钓鱼站** |
| **关键风险** | 工程量被严重低估（原以为"配个 jar"，实为重写）；AGPL 分发合规 |

### 3.3 Clarity-OMR（clquwu）— 高上限、低稳定性

| 维度 | 评估 |
|---|---|
| **可用性** | **中低** |
| **许可** | 代码 **GPL-3.0**，权重 **CC-BY-SA-4.0**（分发合规需注意） |
| **技术路线** | YOLO 检测谱表区域 + **DaViT-Base + DoRA** 微调解码，487-token 音乐词表 + Grammar FSA 约束解码 |
| **运行环境** | PyTorch + CUDA；**0.2B 参数**，显存需求低，**RTX 5060 Laptop 可跑**；作者实测 RTX 3080 约 **10 s/页**（比 Audiveris 快 3 倍） |
| **输出契约** | `python omr.py score.pdf -o output.musicxml` → **直接支持显式输出路径**，drop-in 契合度极高 |
| **集成动作** | 新增驱动脚本；需确认图片（非 PDF）输入支持 |
| **周估** | **2～3 人日** |
| **对 pitch/octave 的提升潜力** | **高但方差极大**。干净谱评分 **69.5 vs Audiveris 25.9**（代际差距）；但**全体均值 42.8 反而略低于 Audiveris 44.0** |
| **已知短板** | 作者自陈："模型按 staff-by-staff 训练，**排版不整齐时表现急剧下降**"；仅 6 次提交、单人学生项目、资源受限 |
| **关键风险** | 成熟度低、维护不确定；性能高度依赖输入谱的排版规整度 |

### 3.4 LEGATO（UW / AI2）— **硬件不可行，排除**

| 维度 | 评估 |
|---|---|
| **可用性** | **低（对本项目不可用）** |
| **许可** | MIT（模型），但依赖 `meta-llama/Llama-3.2-11B-Vision`，需接受 Llama 3.2 协议 |
| **运行环境** | **显存 ~15～20 GB+（FP32），FP16 亦需 ~10 GB+** → **RTX 5060 Laptop（8 GB）装不下**。这是**硬阻断** |
| **输出契约** | 输出 **ABC notation 而非 MusicXML**；转 MusicXML 需 **MuseScore 可执行文件 + `DISPLAY=:0` GUI 环境** → Windows 本地 CLI 场景极别扭且脆弱 |
| **精度** | SOTA：OMR-NED 绝对误差降 47.6%，支持整页/多页 |
| **结论** | 精度虽强，但**显存 + ABC 中转 + GUI 依赖**三重阻断，与"本地离线 C++ CLI 工具"定位冲突。**不建议纳入本轮** |

### 3.5 商业 / 云 API（PhotoScore、SmartScore、Soundslice 等）

| 维度 | 评估 |
|---|---|
| **准确率天花板** | 标称 >99.5%（厂商口径，通常在理想印刷谱上） |
| **成本** | 授权费或按页计费 |
| **离线/隐私** | ❌ **与 Pudu 定位直接冲突**。Pudu 是本地 C++ CLI 工具，云依赖意味着：断网不可用、用户乐谱上传第三方、按量计费、API 变更即失效 |
| **学习价值** | ❌ 闭源黑盒，对"转 AI"的项目目标零贡献 |
| **结论** | **不建议**。仅可作为"准确率天花板"的参照基准，不作为集成目标 |

### 3.6 候选横向对比

| 引擎 | 可用性 | 集成周估 | pitch/octave 提升潜力 | 许可 | 本机可跑 | 关键风险 |
|---|---|---|---|---|---|---|
| **homr** | **高** | **1.5～2 d** | **高**（正打八度短板） | 开源 | ✅ 同栈 | Poetry 集成、Blackwell 兼容待实测 |
| Audiveris 5.7+ | 中 | 3～5 d | 中 | AGPL-3.0 | ✅ 自带 JRE | 现有分支需重写；AGPL 分发 |
| Clarity-OMR | 中低 | 2～3 d | 高但方差大 | GPL-3.0 | ✅ 0.2B | 成熟度低；排版敏感 |
| LEGATO | **低** | — | 高 | MIT+Llama | ❌ **显存不足** | ABC 中转 + GUI 依赖 |
| 商业云 API | — | — | 最高 | 闭源 | ❌ 需联网 | 违背离线定位 |

---

## 4. 达到 80% 的现实路径判断

### 4.1 先厘清口径

用户验收线"≥80%"目前有两个未定维度，必须先拍板，否则无法判断可达性：

| 口径 | 当前值（harness） | 当前值（序列对齐估计） | 难度 |
|---|---|---|---|
| `pitch_degree`（音名） | 13.56% → **99.94%**（R1 后可信基线，见 §1 顶部） | **~91.6%（上界，未独立复现，见附录 A）** | **R1 已修（2026-08-08）：真实值 99.94% ≫ 80%，音名口径达标，无需为音名换引擎** |
| `pitch_octave`（八度） | 60.28% | — | 中 |
| step + octave 联立 | — | **~55.0%（上界）** | 高 |
| `field_pass`（字段级） | 32.04% | — | 高 |
| `note_pass`（整音符全对） | 2.65% | — | **极高** |

**建议口径**：以 **`field_pass` ≥ 80%** 作为上线线（字段级通过率，兼顾音高/时值/八度），并在 **MVP 单声部域**（`docs/mvp-scope-prd.md` 定义的单声部、≤2 升降号、无装饰音）而非 concerto 难域上验收。理由：`note_pass`（整音符全对）在 OMR 领域是极严苛指标，商业软件在真实扫描件上也难破 80%；concerto 是六页 Vivaldi 小提琴协奏曲，属难域，不应作为 MVP 验收基准。

### 4.2 单换引擎能否摸到 80%？

**分层回答：**

**① 在音名（`pitch_degree`）口径上：R1 后已证实达标。**
序列对齐估计 oemer 真实 step 准确率 ~91.6%（本文 LCS）或 ~38.4%（主理人 difflib 独立重算，见附录 A）——两者差距巨大，说明当前对齐方法不可信。**R1（2026-08-08）修好标尺后重测：`pitch_degree` = 99.94% ≫ 80%，音名口径已达标，无需为音名换引擎**（两套独立锚交叉验证 + 随机对照 ~26% 排除循环论证）。

**② 在八度 / step+octave 口径上：单换引擎有机会，但没有把握。**
当前 step+octave ~55%，到 80% 需 +25 pp。homr 的 Transformer 语义识别 + 符头交叉校验正对八度短板，有望拿下其中一大截，但**没有公开数据能保证 ≥80%**。需实测。

**③ 在 `field_pass` / `note_pass` 口径上：单换引擎（不微调）大概率不够。**
`rhythm` 只有 46.72%，是 `field_pass` 的第二大拖累。节奏识别（符干/符杠/附点/连音）是所有开源 OMR 的共同弱项，换引擎能改善但难到 80%。

**④ 在 concerto 难域上：单换引擎（不微调）基本不可能到 80%。**
六页多系统的巴洛克协奏曲，密集十六分音符 + 加线区，是开源 OMR 的极限区。p6 甚至出现 74 小节 → 48 小节的结构性漏检。

### 4.3 换引擎 vs 微调（#2）/ 合成数据（#3）的关系

**换引擎是"底座精度"，是 #2/#3 的前提，不是并列选项。** 理由：

1. **微调需要一个可微调的底座。** oemer 的音高是**纯几何后处理**推断出来的（`staff_line_pos` + clef/track 的 `argmin`/`round`），**不是神经网络输出的**——这意味着"微调 oemer 让音高更准"在架构上不成立，你能微调的只有它的 UNet 分割模型，而音高错误发生在分割**之后**的几何代码里。**这是 oemer 作为底座的根本缺陷。**
2. **homr / Clarity-OMR 把音高放进了神经网络的输出**（Transformer 语义序列 / token 解码），因此它们**天然可微调**。换到这类引擎，才第一次让 #2（在正确 GT 上微调）与 #3（合成数据训练）成为**技术上可执行**的选项。
3. 因此建议的依赖顺序是：**修标尺 → 换可微调底座 → 再谈微调**。

> 一句话：**换引擎不只是为了那几个百分点，更是为了让"微调"这条路第一次真正打开。**

---

## 5. 风险与前置依赖

| # | 项目 | 等级 | 说明与建议 |
|---|---|---|---|
| **R1** | **评测标尺不可信** | ✅ **已解决（2026-08-08）** | §1 已论证。`_merge_align` 已改整 part NW 全局对齐。新可信基线：`pitch_degree` 13.56%→99.94%、`event_count` 1926→368、`notes_compared` 944→1723。后续引擎对比可用此标尺 |
| **R2** | GT 质量瑕疵（Bug B 拍号） | 🟠 高 | 项目已记为待办 A。GT 拍号错 → `rhythm` 误判 → onset 漂移 → 加剧 R1。与 R1 是同一条因果链，**建议合并处理** |
| **R3** | p6 结构性错位（74 vs 48 小节） | 🟠 高 | 该页 pred 少 26 个小节，属结构级漏检。评测前应单独核查该页 GT 与图片是否匹配，否则拉低全局统计 |
| **R4** | 评测集需重建 | 🟡 中 | 换引擎后 `.pred.musicxml` / `.pred.geometry.json` 全部作废需重跑；geometry sidecar 为 oemer 专有，新引擎无此产物 → 依赖它的 F3 基础设施同步失效（可接受，F3 本就零效果） |
| **R5** | 真实拍摄样本（U4）缺失 | 🟡 中 | 现语料为**扫描/渲染印刷谱**。homr 主打"相机拍摄照片"场景，若不引入真实拍摄样本，无法验证其主场优势；同时 MVP 验收域也需明确是否含拍摄件 |
| **R6** | MusicXML 兼容性 | 🟢 低 | 见 §2.5。主要风险是 Audiveris 的 `.mxl` 压缩包与多声部结构 |
| **R7** | 后处理需重调 | 🟡 中 | Plan A（调号推断）引擎无关可复用，但其**统计推断阈值**（`_infer_fifths_statistical`）是按 oemer 的错误分布调的，换引擎后需重新标定；F3 直接弃用 |
| **R8** | 测试暗礁 | 🟡 中 | `tests/test_cpp_preprocess_switch.py:210` 逐字节比对 oemer 分支体，新增分支时易误伤（§2.4） |
| **R9** | 许可合规 | 🟡 中 | Audiveris AGPL-3.0 / Clarity-OMR GPL-3.0。子进程调用一般安全，**但若打包分发需法务确认** |
| **R10** | Blackwell GPU 兼容 | 🟢 低 | RTX 5060 为 sm_120，onnxruntime-gpu / PyTorch 需较新版本。oemer 已跑通 GPU，风险可控，但换引擎后需回归验证 |

---

## 6. 结论与建议第一步

### 6.1 结论

**换引擎在工程上完全可行，集成成本低（换 Python 系引擎 1.5～2.5 人日）——架构接缝设计得很好，下游解析器预计零改动。**

**但"立即换引擎"不是正确的第一步。** 因为立项依据（`pitch_degree` 13.6%）经核验大概率是评测 harness 的 positional-fallback 对齐产生的测量假象，而非 oemer 的真实能力。在坏标尺下换引擎，会得到同样的 ~14% 并误判新引擎无效。

同时需修正一个流传已久的判断：原以为"音名（pitch_degree）是最弱短板、根因是 off-by-one 几何偏置"——这一判断已被推翻（`pitch_degree` 13.6% 是坏标尺的随机配对假象，816 个失败音符音级偏移近似均匀分布，非 ±1 集中；F3 几何校正器零效果也正因此被解释）。至于"真正短板是八度（step+octave）"——**R1（2026-08-08）后已被证实**：6 页语料可信基线 `pitch_octave` = 64.4%、`rhythm` = 52.1%，音名 99.94%。F3 零效果本身成立（靶子本不存在）。

### 6.2 建议的执行顺序

| 步骤 | 内容 | 工作量 | 产出 |
|---|---|---|---|
| **第一步 ✅（2026-08-08）** | **修评测对齐**：`_merge_align` 已换成整 part Needleman–Wunsch 全局保序对齐（见 `tools/omr_eval_lib.py`）。~~顺带修 GT Bug B 拍号~~（待办 A，独立项，未并入 R1）；~~核查 p6 结构错位~~（独立项，未并入 R1） | ~1 人日 ✅ | **oemer 的真实基线已产出**：`pitch_degree` 99.94% / `pitch_octave` 64.4% / `rhythm` 52.1% |
| **第二步** | 拍板验收口径：`field_pass` 还是 `pitch_degree`？MVP 单声部域还是 concerto 难域？ | 0.5 人日（决策） | 明确的 80% 定义。注：音名口径已 99.94% 达标，口径拍板可更聚焦 octave/rhythm |
| **第三步** | 以真实基线为对照，**做 homr 的 spike**（不改 C++，先在 Python 侧直接跑 homr 对同一批 6 页语料，用修好的标尺对比） | **~1 人日** | homr vs oemer 的可信 A/B 数据 |
| **第四步** | 若 homr 显著胜出 → 正式集成（adapter 加分支 + `tools/omr_homr.py`） | 1.5～2 人日 | 引擎替换落地 |
| **备选** | 若 homr 不够 → 再评估 Clarity-OMR / Audiveris；若均不够 → 进入 #2 微调路径（此时底座已可微调） | — | — |

> **核心建议（R1 已完成，2026-08-08）：先修标尺再决定换引擎——这一建议已兑现。**
> R1 用 ~1 人日修好标尺并直接告诉你：**音名已经 99.94%，80% 目标在音名口径上已达成**。项目的优化重心应从"换引擎救音名"转向"攻八度（64.4%）和节奏（52.1%）"——那是完全不同的一套打法。

### 6.3 若必须现在就选一个引擎

**选 homr。** 理由按权重排序：
1. **CLI 契约与 oemer 逐字同构**，集成成本最低（1.5～2 人日）
2. **同一 Python + onnxruntime + CUDA 栈**，本机环境已就绪
3. **技术路线正打真实短板**：用 Transformer 语义识别 + 符头交叉校验替代 oemer 的纯几何外推，而八度错误正是纯几何外推的产物
4. **让微调（#2/#3）第一次成为可能**——oemer 的音高不经过神经网络，根本无法微调
5. 首个独立开源 OMR 横评冠军，2026 年仍活跃维护

---

## 7. Anything UNCLEAR

1. **验收口径未定**：`field_pass` vs `pitch_degree` vs `note_pass`，以及 MVP 单声部域 vs concerto 难域。本文按四种口径分别讨论，但最终需用户拍板。
2. **§1.4 的 91.6% / 55.0% 是 LCS 上界**，非最终准确率。真实值需 Needleman–Wunsch + 替换罚分重算（即 §6.2 第一步）。方向结论稳健，具体数值待精确化。
3. **p6 的 74 → 48 小节错位**成因未查清：是 oemer 漏识别整个系统，还是该页 GT 与图片本身不匹配（GT 切页 Bug）？需人工核对。
4. **U4 真实拍摄样本是否纳入验收域**未定。homr 的主场是相机拍摄照片，若验收域只含扫描件，其相对优势可能被低估。
5. **Clarity-OMR 是否支持图片（非 PDF）直接输入**未核实，README 示例均为 PDF。
6. **AGPL / GPL 分发合规**：若 Pudu 未来打包分发（而非仅本地调用），需法务确认 Audiveris（AGPL-3.0）与 Clarity-OMR（GPL-3.0）的边界。

---

## 附录 A：主理人独立核验（2026-08-06，齐活林）

§1.4 的 91.6% / 55.0% 由架构师用一份 LCS 估计得出。主理人独立复核，结论：**该数字不可复现，且评测标尺本身已坏，任何准确率数字当前都不能采信。**

### A.1 复核方法
- **输入**：与 §1.4 同批 6 页 concerto 语料（`data/omr_eval/real/concerto_pages/` 的 `.pred.musicxml` / `.gt.musicxml`），经 `Pudu.exe --to-jianpu-json` 投影为简谱序列。
- **对齐**：按"页内小节位置序号"分组（绕过 oemer 每页从 1 重置、GT 全局连续的小节编号错位），组内切分 pred/gt 音符序列后用 `difflib.SequenceMatcher` 算 LCS recall（保序、容增删）。
- **对照**：pred 序列随机打乱后重测，作为"无有序信号"基线。
- **口径**：step only（== `pitch_degree` 口径）、step+octave（更严格）。

### A.2 复核结果
| 口径 | 序列对齐 recall | 随机打乱对照 | 与打乱差 |
|---|---|---|---|
| step only | **38.4%**（742/1933） | 31.8% | +6.6 pp |
| step+octave | **25.7%**（496/1933） | 23.1% | +2.6 pp |

分页 step+octave recall：p1 30.6% / p2 33.2% / p3 24.7% / p4 25.1% / p5 32.0% / p6 14.8%。
交叉验证：38.4% × 60.28%（harness `pitch_octave`）≈ 23.1%，与实测 25.7% 基本自洽。

### A.3 与 §1.4 的分歧
| 方法 | step | step+octave | 打乱对照 (step) | 结论信号 |
|---|---|---|---|---|
| harness positional fallback（§1） | 13.6% | — | — | 随机配对 |
| 本复核 difflib LCS | 38.4% | 25.7% | 31.8% | **弱**（对齐≈打乱） |
| §1.4 LCS 估计 | 91.6% | 55.0% | 20.3% | 强 |

三种方法给出 13.6% / 38.4% / 91.6% 三个量级，**跨度过大、且本复核的对齐与打乱对照几乎无差**——这本身即证明 `_merge_align` 的对齐质量不可信，而非 oemer 真实能力有 5 倍差异。

### A.4 修订后的结论（2026-08-08 已按 R1 完成更新）
1. **`pitch_degree` 13.6%（harness）不可信**：是 positional-fallback 随机配对的假象，不是 oemer 的音名准确率。**R1 已证实**。
2. **"oemer 真实音名已 ~90%、真正短板是八度"——R1 后被证实**：整 part NW 对齐重测 `pitch_degree` = **99.94%**（两套独立锚交叉验证 + 随机对照 ~26%），`pitch_octave` = 64.4%、`rhythm` = 52.1%。"八度为真正短板"已由可信基线确认。
3. **唯一稳健结论：评测标尺已坏（R1）** —— **已修复（2026-08-08）**：`_merge_align` 改为整 part Needleman–Wunsch 全局对齐 + 音高锚定罚分，6 页 concerto 语料可信基线重算为 `pitch_degree` 99.94% / `event_count` 368 / `notes_compared` 1723。旧数字（13.6% / 25.7% / 55% / 91.6%）作废，新基线可作为决策依据。
4. **F3 零效果结论仍然成立**，且"off-by-one 几何偏置"根因已被证伪（816 失败音符音级偏移近似均匀分布）——两者相互自洽。
5. **80% 验收决策不再被 R1 阻断**：可信基线已就绪（音名 99.94% 已达标），下一步是拍板口径（field_pass / note_pass、MVP 单声部域 vs concerto 难域），再谈是否需要换引擎攻八度/节奏。

---

*本文档为可行性分析，未修改任何项目代码。§1.4 的序列对齐实验为只读分析，未写入任何项目文件；附录 A 的复核为只读分析，临时脚本已删除。*
