# 谱渡 Pudu · 项目进度状态与时间线规划

> 刷新时间：2026-07-21（取代 2026-07-18 旧版）
> 依据：`README.md`、`MEMORY.md`、`SESSION_SUMMARY_OMR_2026-07-17_18.md`、`project_progress_analysis.md`(本刷新版)、`docs/jianpu-ocr-optimization-plan.md`、`docs/m2-*.md`、git 实测 + GitHub 远端核查（2026-07-18）。
> 时间基准：今天 **2026-07-21（周二）**。总工期估算 **≈18 周（约 4.5 个月）** 区间（research_report 16–23 周），已消耗约 1.5 周。

---

## 0. 当前进度速览（一句话）

**核心双线已完成**：双向 `MusicXML ⇄ 简谱`（阶段 2+3）与 OMR 黑盒集成（阶段 1，含评测 harness + Plan A + H2 + 对齐 fallback）全部落地并**已推送 private 远端（07-20，0/0 同步）**，端到端 `乐谱图→简谱` 已在本机 GPU 跑通。剩余为 **阶段 4（AI/DL）与阶段 5（GUI）**，以及 M2 的精度优化线——**F3 几何校正器已落地并经全量 A/B 证实对 oemer 0.1.8 零效果（OFF==ON 逐字节相同），保留为实验性基础设施、不作上线**；**下一步精度优化焦点为 M2-opt-A2（Plan A 生产路径补全：无 gt 也正确推断 a 小调 alter）**；octave run-to-run 波动排查（P1）经受控复跑证伪已关闭（std=0，伪命题）。

---

## 1. 进度状态三分（已完成 / 进行中 / 未开始）

### 1.1 ✅ 已完成（Done）

| 模块 | 交付物 | 验收证据 |
|---|---|---|
| **阶段 0 · 环境地基** | MSVC2022 / CMake / vcpkg / Git 全链路；编码规范（`/utf-8`、`*.text=auto`）；`encoding_report.md` 确认全仓 UTF-8 无 BOM | 构建 0 错 0 警；`=== Stage 0 environment check passed ===` |
| **MusicXML 解析层（模块③ 输入侧）** | `include/score_model.hpp` + `src/musicxml_parser.cpp`；`.mxl`/UTF-8/多声部时序/和弦/装饰音全部处理 | `verify_corpus.py` 8/8 样本、80/80 检查项 PASS；4 项历史缺陷（credit/和弦/backup/装饰音）已闭环 |
| **阶段 2 · 五线→简谱（核心产权，MVP v1）** | `jianpu_model.hpp` + `jianpu_converter`（纯函数 + `staffToJianpu`）+ L1/L2/L3 三渲染器 + CLI | 单测 54/54；music21 跨语言校验 音符 100%(13492/13492)、字段 100%(79240/79240) |
| **阶段 3 · 简谱→五线（反向）** | `jianpuToStaff` + `scoreToMusicXML` + round-trip 自洽 + CLI `--to-musicxml` | 阶段3 新增 9 项单测 + G2 序列化自洽；phase-3/3.1/3.2 已打标 |
| **M1.5 边界硬化** | 和弦逐音八度点 / tieStop 反向还原 / 极端连音比容错 / 变调重算 | 15 项单测；ground-truth 8/8 100% |
| **阶段 1 · OMR 黑盒集成（M2）** | `omr_adapter` + oemer/fixture 引擎 + CLI `--from-omr`；真实 oemer 本机 GPU 端到端跑通 | **117 个 gtest 用例（经 1 个 ctest 入口 `PuduTests` 运行）全绿 + 41 个 F3 Python 单测全绿**；M2-3 fixture 全链路；真实评测 harness 已量化 oemer 误差 |
| **评测 harness + Plan A + H2 + 对齐 fallback** | `tools/omr_eval_*` + `omr_oemer.py` 调号重推断 + 分维指标 + `_merge_align` 同小节音序对齐 | QA 独立验证全 PASS；concerto 分维数据已产出；对齐后 event_count 未配对 2197→1926(−12.3%) |

### 1.2 🔶 进行中 / 待收尾（In Progress / Pending）

| 事项 | 状态 | 优先级 |
|---|---|---|
| ✅ 建 GitHub 仓库 `youzi467/Pudu` 并推送 | 仓库为 **private**（沙箱误报 404）；已于 2026-07-20 推送 `1286031..6e5bf5e`，0/0 同步 | **DONE** |
| ✅ 提交 Plan A+H2+对齐+文档+`.gitignore` | 已提交并推送（2c53f44/bbfa420/a4e4e96/6e5bf5e）；运行产物 gitignore 排除 | **DONE** |
| **Plan A 生产路径缺口（M2-opt-A2）** | gt 对齐法已修评测期泄漏；但无 gt 真实推理仍回退原 `_apply_alters` 误清零 a 小调变化音 | **P2（下一优先）** |
| **F3 几何感知音高校正器（已落地）** | 全量 A/B 证实对 oemer 0.1.8 零效果（OFF==ON 逐字节相同），保留实验性基础设施、默认 OFF | **P3（已证伪，待处置拍板）** |
| **octave run-to-run 波动排查（已关闭）** | 受控复跑 12 次 std=0（伪命题），无需再做 | **P1（CLOSED）** |
| **P0-2 预处理脚本** | oemer 输入前图像增强；需 harness A/B 量化净收益后决定 | P2 |
| **P1-1 后处理规则引擎** | 节拍对账/八度连续性/调内一致性（仅 Plan A 调号子集落地） | P3 |
| **文件夹重命名 `omr`→`Pudu`** | 文档已定名，活动工作区锁定，需关闭后手动执行 | P3（非阻塞） |

### 1.3 ⬜ 尚未启动（Not Started）

| 阶段 | 目标 | 关键缺口 |
|---|---|---|
| **阶段 4 · AI / 深度学习** | 自训/微调识别模型 + ONNX 部署 + 评测 | PyTorch/ONNX Runtime/合成数据/评测脚本均无；依赖 harness 先证明确为 oemer 瓶颈 |
| **阶段 5 · 工程化与 GUI** | Qt/ImGui 应用 + 打包 + 作品集 | GUI/输入面板/纠错编辑器/打包均未做 |

---

## 2. 结构化时间线规划（刷新）

> 阶段 0/1/2/3 已提前完成，与 07-15 旧排期相比大幅超前。下方按"剩余工作 + 新发现风险"重排。

### 2.1 总体时间线表

| 里程碑 | 阶段内容 | 起止日期（建议） | 工期 | 关键交付 / 验收 | 优先级 |
|---|---|---|---|---|---|
| ✅ **M0-紧急** | 建仓 + 推送 + 提交本地工作 | 2026-07-18 → 07-20 | ~0.5 天 | GitHub `youzi467/Pudu`(private) 推送 `1286031..6e5bf5e` 成功；0/0 同步 | **DONE** |
| ✅ **M0-收尾** | 提交 Plan A+H2+对齐+`.gitignore`；fork oemer 固化补丁方案 | 07-20 | ~2 天 | 全部本地改动入 git；运行产物排除 | **DONE** |
| **M2-opt-A** | Plan A 生产路径补全（M2-opt-A2） | **下一优先（接续当前）** | ~0.5 天 | 无 gt 真实推理 a 小调变化音不再误清零 | P2 |
| **M2-opt-B** | **F3 几何校正器（已落地·零效果·实验性）** | 已落地 | — | sidecar 暴露几何 + Pudu 几何重算；全量 A/B 证实 OFF==ON 逐字节相同、`pitch_degree` 无提升（零效果），保留实验性基础设施、不作上线 | **P3（已证伪，待处置拍板）** |
| **M2-opt-C** | P0-2 预处理 + P1-1 后处理（A/B 量化后） | F3 后 | ~2 周 | 预处理/后处理增益数字；默认开关建议 | P2/P3 |
| **M3** | 阶段 4 AI / 深度学习 | 依 M2-opt-A2 结果定（条件触发） | ~8 周 | PyTorch 入门 → fork oemer 微调/适配预训练 → ONNX 部署 → 评测报告（条件触发） | P4 |
| **M4** | 阶段 5 工程化与 GUI | M3 后或并行 | ~3 周 | Qt GUI（开谱/显简谱/导出）→ 打包 → 技术报告 + 仓库整理 | P5 |

> **推荐顺序修正（相对 07-15）**：阶段 3 与 OMR 已提前完成，故"下一步"不再是 M1/M2，而是 **先M0 救火（备份）→ 再 M2-opt（精度优化线，下一优先 M2-opt-A2）**。M3(阶段4)/M4(阶段5) 顺序不变，以 M2-opt-A2 结果 gate（F3 全量 A/B 已证实零效果，不作为瓶颈 gate）。

### 2.2 里程碑节点详表（带验收标准 DoD）

| 节点 | 日期（建议） | 验收标准（Definition of Done） |
|---|---|---|
| ✅ **M0-紧急 建仓推送** | 2026-07-20 | GitHub `youzi467/Pudu`(private) 推送 `1286031..6e5bf5e` 成功；0/0 同步；无运行产物入库 |
| ✅ **M0-收尾 提交** | 2026-07-20 | `git status` 干净（运行产物 gitignore）；Plan A/H2/对齐/`.gitignore` 已入 git |
| **M2-opt-A Plan A 生产补全** | **下一优先（接续当前）** | 无 gt 真实推理 concerto `pitch_accidental` 不再误清零；`--no-oemr` 自洽仍 100% |
| **M2-opt-B F3 几何校正（已落地·零效果）** | 已完成 | oemer sidecar 暴露符头/谱线几何；Pudu 重算 `pitch_degree`；全量 A/B 证实 OFF==ON 逐字节相同、`pitch_degree` 无提升（零效果） |
| **M2-opt-C 预处理/后处理** | +5 周 | harness A/B 出净收益数字；默认开关建议；干净输入后处理 0 修正（保 100%） |
| **M3-1 训练闭环** | +8 周 | 最小音符检测/微调在测试集出 precision/recall（条件触发） |
| **M4-1 GUI 可用** | +11 周 | Qt 应用：打开 MusicXML/PDF → 显示简谱 → 导出 |
| **M4-2 交付** | +12 周 | 安装包 + 技术报告 + GitHub 仓库整理完成 |

### 2.3 依赖关系（DAG，刷新）

```
L0 环境/MusicXML ──┬──▶ L2 五线→简谱 ✅ ──▶ L3 简谱→五线 ✅ ──┐
                   │                                          │
                   └──▶ L1 OMR 黑盒 ✅(M2) ──▶ F3几何校正 ✅(零效果·实验性) ──┤
                                                (M2-opt-B)    │
                                                │            │
                                          P0-2/P1-1后处理 ──┤
                                                │            │
                                                └──▶ L4 AI ──┴──▶ L5 工程化/GUI
                                                      (M3)        (M4)
```

> **硬依赖**：`L0→L2→L3` ✅；`L0→L1` ✅；`M2-opt-A2→L4`（M2-opt-A2 结果 gate 阶段4 是否启动）；`L2/L3→L5`。F3 全量 A/B 已证实零效果，不作为阶段4 gate。
> **✅ 安全前提已闭环**：M0（建仓推送）已于 2026-07-20 完成（private 仓库，0/0 同步），本地全损风险已解除；后续开发可放心推进。
> **可并行**：F3 几何校正 与 P0-2 预处理 互不依赖；M4(GUI) 可先接现有 CLI 验证功能。

---

## 3. 任务优先级排序（全局 P0–P5）

| 优先级 | 任务 | 理由 |
|---|---|---|
| **P0** | M0-收尾：fork oemer 固化 6 补丁 | 防丢失 + 可复现底线（pip upgrade 即丢） |
| **P1** | octave run-to-run 波动排查 | **已关闭（CLOSED）**：受控复跑 12 次 std=0，伪命题，无需再做 |
| **P2** | **M2-opt-A2：Plan A 生产路径补全（下一优先）** | 解除真实推理 a 小调变化音净负面 |
| **P3** | **M2-opt-B：F3 几何校正器处置拍板** | 全量 A/B 证实零效果，保留实验性（默认 OFF）或移除，待拍板 |
| **P3** | M2-opt-C：P0-2 预处理 + P1-1 后处理（A/B 后） | 照片鲁棒性 + 节拍/八度纠错 |
| **P4** | M3：阶段 4 AI/DL | 转 AI 主战场；条件触发于 M2-opt-A2 结果 |
| **P5** | M4：阶段 5 GUI/工程化 | 作品集收尾 |

---

## 4. 各阶段任务拆解（指向详细计划）

- **M0 建仓推送**：GitHub 网页创建空仓库 `youzi467/Pudu`（默认分支 `main`，勿自动生成 README 以免冲突）→ 本地 `git push -u origin main`；运行产物加 `.gitignore`。
- **M2-opt-B F3（已落地·零效果）**：已按 `docs/jianpu-ocr-optimization-plan.md` §3 路线落地（sidecar JSON schema + oemer 暴露几何 + Pudu 几何重算 step/octave/clef），全量 A/B 证实对 oemer 0.1.8 零效果（OFF==ON 逐字节相同），保留为实验性基础设施、不作上线；待拍板「保留实验性标注 or 移除」。
- **M3 阶段 4**：按 `learning_path.md` L4——PyTorch 入门、合成数据/预训练微调、ONNX Runtime 部署、评测脚本。
- **M4 阶段 5**：按 `learning_path.md` L5——Qt/ImGui GUI、打包、文档。

---

## 5. 风险提示与进度跟踪建议

1. ~~**远程备份缺失**~~ ✅ **已解除（2026-07-20）**：`youzi467/Pudu` 为 private 仓库（沙箱无权限误报 404），已成功推送 `1286031..6e5bf5e`，0/0 同步。后续只需 `git config http.schannelCheckRevoke false` 绕过沙箱 schannel 吊销检查即可正常 push。
2. **M2 受网络/TLS 拦截影响**：装 Audiveris(Java)/oemer(Python) 与下载权重曾遇本机 TLS 自签 CA；当前 oemer 已手动放置权重跑通。
3. **oemer 补丁脆弱**：6 处 site-packages 补丁在 `pip upgrade` 时丢失，必须 fork 或随 Pudu 分发（阶段4 计划）。
4. **文档一致性**：阶段状态、单测口径（**117 个 gtest 用例经 1 个 ctest 入口 `PuduTests` 运行全绿 + 41 个 F3 Python 单测全绿**）、路径名（`omr`/`Pudu`）在各文档间已在本刷新版统一；后续改动须同步 `README.md`/`project_progress_analysis.md`/`project_timeline.md`。
5. **进度跟踪机制**：每个里程碑结束须有可验证物——构建通过、单测全绿（117 gtest + 41 F3 Python）、标签（`phase-N`）、文档状态回填。

---

## 附：当前 git 状态快照（2026-07-21）

```
本地 HEAD = origin/main = 0736c92  chore: F3 几何校正器（已推送）
远程 origin = https://github.com/youzi467/Pudu  ← ✅ private，已推送，无未推送提交（含 F3 6 提交 aac9408..0736c92）
working tree: 干净（运行产物已 gitignore）
测试：117 个 gtest 用例（经 1 个 ctest 入口 PuduTests 运行）全绿 + 41 个 F3 Python 单测全绿
```
