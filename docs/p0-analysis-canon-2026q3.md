# P0 修复实证分析：用户 canon PDF 三问题 · 2026-08-12

> 承接 2026-08-09~10 三问题根因（docs/product-status.md §3/§6、docs/f3-abtest.md）。
> 本次（2026-08-12）按用户指令「先落 P0 两条修复 + 量化无 GT keysig」，对 P0-1（keysig）
> 与 P0-2（时值塌缩）做了**全量实证**：两条修复按定义均**不可在 Python 几何层修复**，
> 本文给出证据链与最终判定。原语料 84.5%/91.7%（e21267a）保持不变。
> 无 GT keysig 量化完成：**4/13 错（31%）**。

> ✅ **后续定论（2026-08-12 同日）**：本文指出的两条真修复通道之一——**Audiveris A/B**——
> 已在三投诉全面胜出（note_pass 84.5%→**97.56%**、keysig 13/13、节奏错 346→24）并**完成迁移**
> （AV 默认引擎 + oemer 回退）。用户三问题在 AV 默认路径全部修复。本文为迁移前的
> Python 层证伪记录，迁移证据与实施见 [docs/audiveris-ab-verdict.md](audiveris-ab-verdict.md)。

---

## 0. 一句话结论

| 用户投诉 | 现状 | P0 实证结论 |
|---|---|---|
| #1 升降号未识别（D 大调识别错） | 无 GT 路径 keysig **4/13 错（31%）**，all 欠数一个升降号 | note-content 推断**数学上不可行**（9/13 封顶，bach_p3 无二次证据）；唯一真修复=图像级键号检测（C 路线，跨 FROZEN） |
| #2 大量四分音符识别为十六分音符 | 3 页过缩（canon_p1 +17.8pp、summer_p2 +14pp、bach_p3 +19.3pp 但为 oemer 原产） | R-geo 在 canon_p1 **净正收益**（rhythm 48.8→56.75%）；页级门控**被证伪**（会回归语料）；塌缩=oemer 检测层，Python 不可修 |
| #3 每小节总时值与拍号不符 | 已修复并落盘（6de4bda/e21267a） | 方案1+方案4+方案2 已闭环，beatOK 100→171 |

**P0 两条修复（keysig 重推断 / R-geo 页级门控）按原定义均不可行**，不是实现问题，是
证据层面证伪。真正的修复通道 = C 路线图像符号检测（已立项为迭代主线）或 Audiveris A/B
（用户已授权，需装 Java）。

---

## 1. 无 GT keysig 全语料量化（batch `build/_nogtv/` 13 页，当前工作树完整管线）

| 页 | 无 GT keysig | GT | 判定 |
|---|---|---|---|
| bach_p1 | 1 | 2 | ✗ 欠 1 |
| bach_p2 | 2 | 2 | ✓ |
| bach_p3 | 1 | 2 | ✗ 欠 1 |
| badinerie | 2 | 2 | ✓ |
| canon_p1 | 1 | 2 | ✗ 欠 1（用户 PDF 页） |
| prelude_p1 | 1 | 1 | ✓ |
| prelude_p2 | 1 | 1 | ✓ |
| summer_p1 | −2 | −2 | ✓ |
| summer_p2 | −1 | −2 | ✗ 欠 1 |
| summer_p3 | −2 | −2 | ✓ |
| summer_p4 | −2 | −2 | ✓ |
| swan-lake | 1 | 1 | ✓ |
| the-swan | 1 | 1 | ✓ |

**9/13 ✓，4/13 ✗，全部「欠数一个升降号」**（1 升 vs 2 升、1 降 vs 2 降）。canon_p1
（用户实测 PDF）确认 1 升（G 大调）vs 真 2 升（D 大调）——投诉 #1 属实。

---

## 2. P0-1 keysig 修复：note-content 推断全方案实测（结论：数学上不可行）

对 13 页无 GT 输出（oemer 音符内容 + 已校正音高）做 keysig 重推断，四种方案对比：

| 方案 | 机制 | 结果 | 失败模式 |
|---|---|---|---|
| **statistical（当前 fallback）** | 逐 (step,alter) 对 accidental_map 匹配计数 | **9/13** | 4 页欠数 1（oemer 漏读谱面升降号） |
| KK（Krumhansl-Kessler） | 音高频率 vs 大/小调 tonal profile 相关 | **0/13** | 稠密半音织体不符 KK 模型；对 GT 自己的 D 大调音符也判错（Bb 大调 corr 0.902） |
| Occam 升降号覆盖 | λ∈[2,8] 覆盖率极小化 | 4–8/13 | 谱面升降号噪声高 |
| prevalence | 出现频次阈值 | 2/13 | oemer 升降号偏差大 |

**关键反证（bach_p3）**：其输出中第二升降号（C♯ 证据）为 0%——note-content 层面
**不存在可恢复的信号**，任何推断器在信息缺失下都无法补数。note-content keysig 推断
在此语料上封顶 9/13，已到信息论极限。

**真修复 = 图像级键号 glyph 检测**（C 路线）：
- 可行性已确认：canon_p1 图 5 线谱（线距 21px），clef x~121–157，两个升号 glyph x~183–240
  （相邻，间距 ~24px≈线距），首音符 x~263——键号区清晰可见、与首音符区间隔离。
- 计数原型尚不可靠：2–4 glyph vs 期望 1–2（zone 合并 / 首音簇混入 / clef 残余）。
- **结论**：C 路线工程（需 zone-clustering + 键号窗细化 + 升/降判别），**跨 FROZEN 边界**
  （omr_oemer.py 才有图像路径），按 product-status §3 属「C 迭代主线」立项范围，非 P0 可落。

---

## 3. P0-2 时值塌缩：R-geo 页级门控「设计→实测→证伪」

### 3.1 现象定量（no-GT 输出 vs GT，16 分占比）

| 页 | pre（oemer 原） | post（R-geo） | GT | 差(pp) | 判定 |
|---|---|---|---|---|---|
| bach_p3 | 92.0% | 92.0% | 72.7% | **+19.3** | oemer 原产（R-geo 未改） |
| canon_p1 | 51.2% | 87.8% | 70.0% | **+17.8** | R-geo 过缩 |
| summer_p2 | 68.4% | 92.0% | 78.0% | **+14.0** | R-geo 过缩 |
| prelude_p2 | 57.2% | 92.9% | 98.5% | −5.6 | R-geo **正确**（还欠缩） |
| badinerie | 34.2% | 69.3% | 66.1% | +3.2 | R-geo 正确 |
| prelude_p1 | 75.0% | 100.0% | 99.7% | +0.3 | R-geo 正确 |
| 其余 7 页 | — | — | — | ≤±6 | 正常 |

> bach_p3 的过 16 分是 **oemer 原产**（pre 已 92%），与 R-geo 无关；R-geo 造成的过缩
> 仅 canon_p1、summer_p2 两页。

### 3.2 塌缩机制（canon_p1 铁证）

canon_p1 三段状态 vs GT：`oemer 原 quarter=63 / 8th=61 / 16th=130`，`R-geo 后 7/24/223`，
`GT 37/41/182`。**GT 恰在两者之间**——oemer 把真 16 分读长（130→需 182），R-geo 又把
真四分/八分读成 16 分（63→7）。sidecar 几何 gap 直方图 canon_p1 **几乎全 42px 均匀
（q1=32.5/med=41.5/q3=47.5，无 2×/4× gap）**——与 prelude_p1（39±1，真 16 分页）签名
相同。即：canon_p1 的 note 位置被 oemer 幻影音符/漏读污染成「全 16 分间距」，几何层
**无 8 分/四分结构可恢复**。

### 3.3 页级门控被证伪（三连实证）

1. **门控误伤**：按 `拟改写≥10 且占比≥0.2` 设计，对 13 页 pre-R-geo 状态实测，**11/13
   页命中**（badinerie 100/228、prelude_p1 88/352 等全在 fast 页正确触发）——因为 R-geo
   的本职就是把 oemer 读长音符缩回几何间距，fast 页本就该改几十个。
2. **门控回退有害**：对 canon_p1 单独回退 R-geo 用 eval harness 实测——rhythm pass
   **48.80%（原）→ 56.75%（R-geo）**。R-geo 在塌缩页也是净正收益，回退反而更差。
3. **无分隔信号**：过缩页 {canon_p1, summer_p2} 与正确缩页 {prelude_p2, badinerie} 的
   (pre,post) 16 分签名**同构**（57.2→92.9 vs 68.4→92），从节奏/几何数据无法区分
   ——post≥85%∧pre<65% 打标会误报 prelude_p2（GT 98.5%，本应全 16 分）。

### 3.4 最终判定

- **塌缩=oemer 检测层**（幻影音符 + 读长 + 漏读 → 均匀 16 分几何），Python 几何层不可修。
- **R-geo v2（已提交 6de4bda）已是该层最优状态**；任何「更保守」调参或页级回退都会
  在 metric 上更差（已实测）。
- **塌缩在用户路径已被兜底呈现**：Pudu.exe（pudu_server）定点阶段跑
  `inject_time_signature → re_slice_measures → mark_meter_constraint_failures`
  （pudu_server.py:495-506），塌缩小节会打「需校对：小节节拍不符」——用户可见、诚实。
- **真修复** = 图像级 note 检测（C 路线）或引擎切换。

---

## 4. 换引擎（Audiveris）A/B 评估更新

**前置**：本机 **无 Java**（`java: command not found`），Audiveris A/B 需先装 JRE。
A/B 成本不再是纯半天，需 +Java 安装（~10 分钟，无管理员权限可能受阻）。

**Audiveris 理论优势**（对三投诉）：内置键号 glyph 检测（直接修 #1）、beam-aware 时值
（修 #2）、小节/拍号校验（修 #3）、成熟 OMR。**迁移代价**：adapter 重写 + Pudu 集成重建、
84.5%/91.7% 基线归零重立、F3/R-geo/拍号注入/重切/打标全链需在 Audiveris 侧重实现。

**决策闸门（用户原话）**：A/B 在 keysig/时值/小节三项明显胜出再谈迁移。鉴于 P0 两条已
证伪，A/B 现在是 keysig/时值两投诉的**最直接实验**——建议执行（需先确认 Java 安装）。

---

## 5. 建议下一步（按性价比）

1. **Audiveris A/B**（用户已授权）：先确认 Java 安装，跑 3–5 页（含 canon_p1/bach_p3/
   summer_p2 三个塌缩页 + prelude_p1 正常页）对照 keysig/时值/小节三项。**直接回答
   「换引擎能否同时修 #1+#2」**。
2. **C 路线图像符号检测**（已立项迭代主线）：键号 glyph 检测原型已证明图像可行，计数
   细化是纯工程；同时补 ♯/♭ 与 note 检测（canon_p1 幻影音符根因）。
3. **维持现状收尾**：D 默认收尾（84.5%/91.7%），塌缩页由既有「小节节拍不符」打标兜底。
4. 本文档数字如需对外，同步 product-status §1/§7（keysig 无 GT 31% 错 / 塌缩 3 页）。

---

## 附：本次改动清单

- `tools/geometric_pitch.py`：P0-2 页级门控**已实现并回退**（零 diff，`git status` 干净）。
  门控被实证证伪后撤销，不引入回归。
- 新增 `docs/p0-analysis-canon-2026q3.md`（本文）。
- 验证脚本（已清理 or 保留在 build/ 未跟踪）：`_p02_gate_verify.py`、`_p02_eval/`。
