# 谱渡 Pudu · 项目进度状态与时间线规划

> 刷新时间：2026-07-18（取代 2026-07-15 旧版）
> 依据：`README.md`、`MEMORY.md`、`SESSION_SUMMARY_OMR_2026-07-17_18.md`、`project_progress_analysis.md`(本刷新版)、`docs/jianpu-ocr-optimization-plan.md`、`docs/m2-*.md`、git 实测 + GitHub 远端核查（2026-07-18）。
> 时间基准：今天 **2026-07-18（周六）**。总工期估算 **≈18 周（约 4.5 个月）** 区间（research_report 16–23 周），已消耗约 1.5 周。

---

## 0. 当前进度速览（一句话）

**核心双线已完成**：双向 `MusicXML ⇄ 简谱`（阶段 2+3）与 OMR 黑盒集成（阶段 1，含评测 harness + Plan A + H2）全部落地，端到端 `乐谱图→简谱` 已在本机 GPU 跑通。剩余为 **阶段 4（AI/DL）与阶段 5（GUI）**，以及 M2 的精度优化线（F3 几何校正等）。**🔴 头号风险：本地 git 无任何远程备份**（`youzi467/Pudu` 仓库在 GitHub 不存在），须立即建仓推送。

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
| **阶段 1 · OMR 黑盒集成（M2）** | `omr_adapter` + oemer/fixture 引擎 + CLI `--from-omr`；真实 oemer 本机 GPU 端到端跑通 | ctest **117/117**；M2-3 fixture 全链路；真实评测 harness 已量化 oemer 误差 |
| **评测 harness + Plan A + H2** | `tools/omr_eval_*` + `omr_oemer.py` 调号重推断 + 分维指标 | QA 独立验证全 PASS；concerto 分维数据已产出 |

### 1.2 🔶 进行中 / 待收尾（In Progress / Pending）

| 事项 | 状态 | 优先级 |
|---|---|---|
| **🔴 建 GitHub 仓库 `youzi467/Pudu` 并推送** | `git remote` 指向的仓库在 GitHub 不存在（404）；本地提交+未提交工作**零远程备份** | **P0（头号紧急）** |
| **提交 Plan A+H2+文档刷新** | 8 文件 modified + 评测语料 untracked，均未提交（运行产物须排除） | **P0** |
| **Plan A 精度泄漏修复（待验证#2）** | `_apply_alters` 过度清零小调合法变化音；需「gt 保留白名单」 | P1（待定 F3 前/中/后） |
| **F3 几何感知音高校正器** | 需 oemer sidecar 补丁暴露几何信息 → Pudu 侧几何重算音高；主攻 `pitch_degree`(17.66%) | P2（最高杠杆优化） |
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
| **M0-紧急** | 🔴 建仓 + 推送 + 提交本地工作 | 立即（2026-07-18） | ~0.5 天 | GitHub `youzi467/Pudu` 创建；`git push -u origin main` 成功；本地零丢失风险 | **P0** |
| **M0-收尾** | 提交 Plan A+H2+文档；fork oemer 固化补丁 | 2026-07-18 → 07-20 | ~2 天 | 全部本地改动入 git；oemer fork/补丁分发方案 | P0 |
| **M2-opt-A** | Plan A 精度泄漏修复（待验证#2） | 待用户拍板（F3 前/中/后） | ~0.5 天 | 小调/变化音曲目 `pitch_accidental` 不再误清零 | P1 |
| **M2-opt-B** | **F3 几何校正器** | 接 M0 后 ~2–3 周 | ~3 周 | sidecar 暴露几何 + Pudu 几何重算；`pitch_degree` 通过率显著提升（靶心 17.66%→更高） | P2（最高杠杆） |
| **M2-opt-C** | P0-2 预处理 + P1-1 后处理（A/B 量化后） | F3 后 | ~2 周 | 预处理/后处理增益数字；默认开关建议 | P2/P3 |
| **M3** | 阶段 4 AI / 深度学习 | F3 证明确为瓶颈后 | ~8 周 | PyTorch 入门 → fork oemer 微调/适配预训练 → ONNX 部署 → 评测报告（条件触发） | P4 |
| **M4** | 阶段 5 工程化与 GUI | M3 后或并行 | ~3 周 | Qt GUI（开谱/显简谱/导出）→ 打包 → 技术报告 + 仓库整理 | P5 |

> **推荐顺序修正（相对 07-15）**：阶段 3 与 OMR 已提前完成，故"下一步"不再是 M1/M2，而是 **先M0 救火（备份）→ 再 M2-opt（精度优化线，F3 为主）**。M3(阶段4)/M4(阶段5) 顺序不变，仍以 F3 量化结论 gate。

### 2.2 里程碑节点详表（带验收标准 DoD）

| 节点 | 日期（建议） | 验收标准（Definition of Done） |
|---|---|---|
| **M0-紧急 建仓推送** | 2026-07-18 | GitHub 创建 `youzi467/Pudu`；本地 `main` 全量推送成功；`git ls-remote` 可见 HEAD=本地 1286031 之后；无运行产物入库 |
| **M0-收尾 提交** | 2026-07-20 | `git status` 干净（除运行产物 gitignore）；oemer fork/补丁分发方案落文档 |
| **M2-opt-A Plan A 修复** | 用户拍板后 | concerto `pitch_accidental` 不再 100%="gt 有→pred 丢"；`--no-oemr` 自洽仍 100% |
| **M2-opt-B F3 几何校正** | +3 周 | oemer sidecar 暴露符头/谱线几何；Pudu 重算 `pitch_degree`；concerto `pitch_degree` 通过率显著提升 |
| **M2-opt-C 预处理/后处理** | +5 周 | harness A/B 出净收益数字；默认开关建议；干净输入后处理 0 修正（保 100%） |
| **M3-1 训练闭环** | +8 周 | 最小音符检测/微调在测试集出 precision/recall（条件触发） |
| **M4-1 GUI 可用** | +11 周 | Qt 应用：打开 MusicXML/PDF → 显示简谱 → 导出 |
| **M4-2 交付** | +12 周 | 安装包 + 技术报告 + GitHub 仓库整理完成 |

### 2.3 依赖关系（DAG，刷新）

```
L0 环境/MusicXML ──┬──▶ L2 五线→简谱 ✅ ──▶ L3 简谱→五线 ✅ ──┐
                   │                                          │
                   └──▶ L1 OMR 黑盒 ✅(M2) ──▶ F3几何校正 ──┤
                                                (M2-opt-B)    │
                                                │            │
                                          P0-2/P1-1后处理 ──┤
                                                │            │
                                                └──▶ L4 AI ──┴──▶ L5 工程化/GUI
                                                      (M3)        (M4)
```

> **硬依赖**：`L0→L2→L3` ✅；`L0→L1` ✅；`F3→L4`（harness 证明显为瓶颈才动模型）；`L2/L3→L5`。
> **🔴 新阻塞**：M0（建仓推送）是**一切安全前提**——未推送前，任何本地灾难=全损，优先于所有功能开发。
> **可并行**：F3 几何校正 与 P0-2 预处理 互不依赖；M4(GUI) 可先接现有 CLI 验证功能。

---

## 3. 任务优先级排序（全局 P0–P5）

| 优先级 | 任务 | 理由 |
|---|---|---|
| **🔴 P0** | M0：建 GitHub 仓库 `youzi467/Pudu` + 推送 + 提交本地工作 | **本地零远程备份，全损风险最高** |
| **P0** | M0-收尾：提交 Plan A+H2+文档；fork oemer 固化 6 补丁 | 防丢失 + 可复现底线 |
| **P1** | M2-opt-A：Plan A 精度泄漏修复 | 解除对变化音小调曲目的净负面 |
| **P2** | M2-opt-B：F3 几何校正器 | 最高杠杆优化，攻 `pitch_degree` 最短板 |
| **P2** | M2-opt-C：P0-2 预处理 + P1-1 后处理（A/B 后） | 照片鲁棒性 + 节拍/八度纠错 |
| **P4** | M3：阶段 4 AI/DL | 转 AI 主战场；条件触发于 F3 结论 |
| **P5** | M4：阶段 5 GUI/工程化 | 作品集收尾 |

---

## 4. 各阶段任务拆解（指向详细计划）

- **M0 建仓推送**：GitHub 网页创建空仓库 `youzi467/Pudu`（默认分支 `main`，勿自动生成 README 以免冲突）→ 本地 `git push -u origin main`；运行产物加 `.gitignore`。
- **M2-opt-B F3**：按 `docs/jianpu-ocr-optimization-plan.md` §3 + SESSION_SUMMARY §1.9 路线——架构师出 sidecar JSON schema → 工程师 oemer 暴露几何 + Pudu 侧重算 step/octave/clef。
- **M3 阶段 4**：按 `learning_path.md` L4——PyTorch 入门、合成数据/预训练微调、ONNX Runtime 部署、评测脚本。
- **M4 阶段 5**：按 `learning_path.md` L5——Qt/ImGui GUI、打包、文档。

---

## 5. 风险提示与进度跟踪建议

1. **🔴 远程备份缺失（最高风险）**：`git remote` 指向的 `youzi467/Pudu` 在 GitHub 核查不存在（owner 存在但无此仓库，404）。本沙箱 HTTPS 无凭据无法 push/fetch。须用户在 GitHub 网页建仓后于**本机交互终端**推送。推送前用 `git status` 确认运行产物不入库。
2. **M2 受网络/TLS 拦截影响**：装 Audiveris(Java)/oemer(Python) 与下载权重曾遇本机 TLS 自签 CA；当前 oemer 已手动放置权重跑通。
3. **oemer 补丁脆弱**：6 处 site-packages 补丁在 `pip upgrade` 时丢失，必须 fork 或随 Pudu 分发（阶段4 计划）。
4. **文档一致性**：阶段状态、单测数（117/117）、路径名（`omr`/`Pudu`）在各文档间已在本刷新版统一；后续改动须同步 `README.md`/`project_progress_analysis.md`/`project_timeline.md`。
5. **进度跟踪机制**：每个里程碑结束须有可验证物——构建通过、单测全绿（117/117）、标签（`phase-N`）、文档状态回填。

---

## 附：当前 git 状态快照（2026-07-18）

```
本地 HEAD = 1286031  docs(eval): document real-sample submission spec
远程 origin = https://github.com/youzi467/Pudu  ← ⚠️ GitHub 核查不存在(404)，须创建
working tree: 8 modified (Plan A+H2+文档) + 评测语料/运行产物 untracked
ctest: 117/117 全绿
```
