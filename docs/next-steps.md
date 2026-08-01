# 谱渡 Pudu · 下一步行动清单

> 生成：2026-07-29 14:34
> 定位：聚焦「接下来做什么」的可执行路线图，与 `project_progress_analysis.md`（综合进度分析）、`project_timeline.md`（时间线）互补——后者描述已发生的全貌，本文档描述待办与执行顺序。
> git 基线：本地 `HEAD` 已与 `origin/main` 同步（文档修正已提交并推送），工作区干净。

---

## 0. 当前位置（一句话）

核心双线（MusicXML⇄简谱双向转换 + OMR 黑盒集成）已打通并 MVP 达成；近期完成 P1（octave 波动证伪关闭）、全量文档审计、P0（oemer 补丁固化）、**P2 真实推理变音修复**（无 gt alter 推断，997b3aa）；**P3 F3 已拍板保留实验性**（2026-07-29）；剩余为环境遗留修复、以及 P4 条件项评估。

---

## 1. 已完成里程碑（起点基线）

| # | 模块 | 状态 | 关键指标 |
|---|---|---|---|
| 1 | 核心转换引擎（C++ 双向） | ✅ MVP | 117 gtest + 77 Python 单测（含 41 F3）全绿；music21 跨语言 100% |
| 2 | M2 OMR 黑盒集成 | ✅ | `--from-omr` CLI、oemer/fixture 引擎、python 自动选址 |
| 3 | Plan A 调号后处理（gt 对齐法） | ✅ | accidental 82.7%（评测期） |
| 4 | 评测 harness（_merge_align） | ✅ | event_count 未配对 2197→1926 |
| 5 | F3 几何校正器 | ✅ 零效果 | 实验性、默认 OFF、不作上线；**P3 拍板保留实验性**（2026-07-29） |
| 6 | P0 oemer 补丁固化（07-29） | ✅ | 方案 B，6 处补丁随仓库分发，`tools/install_oemer.py` |
| 7 | 全量文档审计（07-28） | ✅ | 13 个 .md 准确性同步 |

---

## 2. 待办事项（按优先级）

### ✅ P0 · 本机推送 2 提交（2026-08-01 完成）
- **目标**：把 `a1ed452` + `127838a` 推到 `origin/main`，消除本地丢失风险。
- **为什么**：沙箱无 GitHub 凭据（GCM 需 GUI 认证），推不出去；2 提交已 commit 但未同步。
- **怎么做**：
  ```bash
  cd C:\Users\13157\WorkBuddy\omr
  git push origin main
  ```
  本机 GCM 弹窗认证或已缓存凭据；`http.schannelCheckRevoke=false` 已设。
- **完成标准**：`git rev-list --count origin/main..HEAD` = 0；GitHub 网页可见 2 新提交。
- **预计**：2 分钟。

---

### ✅ P2 · M2-opt-A2：Plan A 生产路径补全（2026-07-29 · 997b3aa）

- **目标**：让 Plan A 在**无 gt 真实推理**时也正确推断 a 小调 alter，不再把合法变化音误清零。
- **背景/为什么**：
  - Plan A 的 gt 对齐法**仅在评测期**（有 ground truth）生效——它从 gt 读 alter 贴回 pred，所以评测时 accidental 82.7%。
  - 但**真实推理无 gt** 时，`tools/omr_oemer.py` 回退到原始 `_apply_alters`，仍把 a 小调（1#，G#）的合法变化音误判为调外而清零 → 真实使用场景下简谱变音记号丢失。
  - 这是当前**唯一能提升真实使用场景准确度**的可控改动（F3 已证零效果、octave 无波动、P0 只防补丁丢失不提升准确度）。
- **具体任务**：
  1. 定位 `tools/omr_oemer.py` 中 `_apply_alters` 的无 gt 分支，分析它如何误清零 a 小调变化音。
  2. 设计无 gt alter 推断逻辑：用 **oemer 检测的调号 `<key><fifths>`** + **符头 `<step>` 拼写**推断 alter（如 a 小调 fifths=1，遇到 G 且无临时记号 → 应为 G#；遇到 G 且有还原记号 → G♮）。
  3. 实现 + 单测（覆盖 a 小调、C 大调、≤2 升降号边界）。
  4. 真实 concerto 语料 A/B：无 gt 推理后 `pitch_accidental` 不再误清零。
- **完成标准（DoD）**：
  - 无 gt 真实推理 concerto `pitch_accidental` 显著提升（目标 ≥ 70%，基线为误清零后的低值）。
  - `--no-oemr` 自洽仍 100%。
  - 既有 117 gtest + 41 F3 Python 单测无回归。
  - 新增 alter 推断单测全绿。
- **依赖**：无（Plan A 代码已就绪，只改 `_apply_alters` 无 gt 分支）。
- **预计**：0.5–1 天。
- **验证检查点**：①单测绿 ②concerto 无 gt 推理 accidental 提升 ③`--no-oemr` 自洽 100%。

---

### ✅ P3 · F3 几何校正器处置拍板（2026-07-29 · 决策：保留实验性）

- **目标**：已决定——**保留实验性标注（选项 A）**，并确保 CLI/文档一致；无代码改动，仅文档定稿。
- **背景**：F3 全量 A/B 证实对 oemer 0.1.8 **零效果**（OFF==ON 逐字节相同），已标为实验性、默认 OFF、不作音准改进上线。
- **决策（2026-07-29）**：选 **A. 保留实验性**。理由：零效果结论本身是工程价值（证明我们做过严谨 A/B 验证），移除反而丢失「做过严谨验证」的证据；`tools/geometric_pitch.py` + `--f3-geometric` 开关 + sidecar schema 全保留，文档继续标注「零效果·实验性·默认 OFF」。无代码改动，仅本文档定稿。
- **选项（记录备查）**：
  - **A. 保留实验性**（已选）：保留代码 + `--f3-geometric` 开关 + sidecar schema + 文档标注「零效果·实验性」；作为「我们验证过几何重算无收益」的记录，有简历/作品集价值。
  - **B. 移除**：删 `tools/geometric_pitch.py`、F3 相关单测、`docs/f3-*.md`、sidecar 导出；简化代码库（未采纳）。
- **完成标准**：CLI `--help`、README、`docs/m2-real-run-guide.md` 描述与实际一致（默认 OFF + 实验性标注已就位）。✅ 满足。
- **依赖**：无。
- **预计**：0.5 天（保留）。✅ 实际为文档定稿，零代码改动。
- **结论**：✅ 已选 A（保留实验性）。无需后续动作，本项关闭。

---

### 🟡 环境遗留 · venv 完整性修复

- **目标**：恢复 venv 到能实跑 oemer OMR 的状态。
- **背景**：QA 在 P0 验证时发现 venv 里 cv2/cycler/dateutil/contourpy 的 dist-info 存在但模块文件缺失（环境腐败，非补丁引起），已临时修复；但 oemer 权重需从 GitHub 下载（~5KB/s，无法在合理时间内完成）。
- **具体任务**：
  1. `pip install oemer==0.1.8`（**带 deps**，不带 `--no-deps`）完整重装，确认 cv2/cycler/dateutil 等齐全。
  2. 重装后跑 `python tools/install_oemer.py` 恢复 6 处补丁（pip 重装会覆盖补丁）。
  3. 预放 oemer 权重到 `site-packages/oemer/checkpoints/`（从本机已有备份拷贝，避免重新下载）。
  4. 跑 `python tools/omr_oemer.py data/river_1.jpg` 确认端到端不崩且产出 MusicXML。
- **完成标准**：oemer 提取 river_1.jpg 成功产出 .musicxml，不抛 IndexError/empty-slice。
- **依赖**：无（可随时做，不阻塞 P2）。
- **预计**：0.5 天（权重已有备份则快）。

---

### 🟢 P4 · 条件项（依 P2 结果定开关）

- **M2-opt-C 后处理规则引擎**：节拍对账 / 八度连续性 / 调内一致性规则。若 P2 后 `pitch_degree`（14%）仍是瓶颈再做。
- **更强 OMR 评估**：评估 Audiveris 5.x 或其他引擎 vs oemer，选准确度更高的。若 oemer 基础识别质量无法突破则考虑。
- **阶段 4 AI/DL**：自训/微调音符检测模型 + ONNX 部署。这是转 AI 方向的高价值产出，但依赖 P2 先解除「真实推理变音丢失」硬伤，且需 PyTorch/合成数据基建（当前为零）。
- **阶段 5 GUI/工程化**：Qt 应用 + 打包 + 作品集收尾。

---

## 3. 已关闭 / 不再做（避免重复劳动）

| 事项 | 结论 | 依据 |
|---|---|---|
| P1 octave run-to-run 波动 | **CLOSED（伪命题）** | 12 次复跑 std=0，历史 ~14pt 为跨批次聚合误读 |
| F3 作为音准改进上线 | **不做** | 全量 A/B 证零效果（OFF==ON 逐字节相同） |
| F3 代码/开关移除 | **不做（保留实验性）** | P3 2026-07-29 拍板：保留作严谨 A/B 证据，零代码改动 |
| Fork oemer 固化补丁 | **不需要** | P0 方案 B 已解决（patch 文件随 Pudu 分发） |
| 向上游发 PR | **不做** | 补丁是 Pudu 特有防御，未必符合上游意图 |
| 固定 seed / 多数投票修 octave | **不做** | octave 零波动，无随机性可修 |

---

## 4. 风险与前置条件

| 风险 | 影响 | 缓解 |
|---|---|---|
| venv 环境腐败未彻底修复 | OMR 实跑受阻，P2 验证依赖真实 oemer 输出 | 先做「环境遗留」修复，或 P2 用 fixture 引擎验证逻辑 |
| oemer 权重下载超时 | 实跑 OMR 不可行 | 用本机已有权重备份，不重新下载 |
| GitHub 推送需本机操作 | 沙箱无法 push | 每次 commit 后提醒本机推；或配置 GH_TOKEN 给沙箱 |
| oemer 升版（>0.1.8） | P0 patch context 失配 | `install_oemer.py` 会 abort 告警，跑 `_regen_oemer_patches.py` 重生成 |

---

## 5. 推荐执行顺序

```
1. 本机推送 2 提交（P0，2 分钟）
   ↓
2. P2 M2-opt-A2（无 gt alter 推断，0.5–1 天）⭐ 核心
   ↓
3. 环境遗留修复（venv 完整重装 + 预放权重，0.5 天，可与 P2 并行）
   ↓
4. P3 F3 处置拍板 ✅ 已决议保留实验性（2026-07-29）
   ↓
5. P4 条件项评估（依 P2 结果）
```

> **关键路径**：P2 是当前最大真实杠杆。完成后真实推理场景的变音记号不再丢失，作品集演示质量显著提升，且为阶段 4 AI/DL 扫清前置障碍。

---

## 附：本文档维护约定
- 每完成一项，在对应行标注 ✅ + 日期 + commit hash，并更新 `project_progress_analysis.md` §8 路线图。
- 优先级变化时同步 `project_timeline.md` §3 优先级表。
- 新增待办项追加到 §2，保持「目标-为什么-任务-DoD-依赖-预计」六要素结构。
