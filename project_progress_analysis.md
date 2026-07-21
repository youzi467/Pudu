# 谱渡 Pudu · 项目进展全面分析报告

> 生成/刷新时间：2026-07-21（刷新版，取代 2026-07-18 旧版）
> 分析范围：工作区全量 `.md` + 源码/头文件/Python 工具 + git 实测状态 + 远程仓库核查
> 参照基准：`SESSION_SUMMARY_OMR_2026-07-17_18.md`、`MEMORY.md`、`.workbuddy/memory/2026-07-18.md`、GitHub 远端核查（2026-07-18）

---

## 0. 一句话结论

**截至 2026-07-21，谱渡 Pudu 的「转换大脑 + 眼睛」双线已实质打通并已完成提交/推送**：阶段 0/2/3（双向 MusicXML⇄简谱）与阶段 1（OMR 黑盒集成 + 评测 harness + Plan A 调号后处理 + H2 分维指标 + 对齐 fallback）全部完成，端到端链路 `乐谱图 → oemer → MusicXML → 简谱` 已在本机 GPU 跑通，全部工作已推送至 private `origin/main`（0/0 同步）。当前唯一进入实质开发的优化项是 **F3 几何感知音高校正器**（主攻 `pitch_degree`，当前最弱 14.0%）。

**✅ 远程备份已闭环（2026-07-20 修正）**：`git remote` 指向的 `https://github.com/youzi467/Pudu` 实为 **private** 仓库（沙箱无访问权限，WebFetch 误报 404），已于 2026-07-20 成功推送 `1286031..6e5bf5e main -> main`，本地与 `origin/main` **0/0 同步**，零丢失风险已解除。当前最高杠杆优化项是 **F3 几何感知音高校正器**（主攻 `pitch_degree`，当前最弱 14.0%）。

> 注：本文件为权威进度文档。旧的 `project_progress_analysis.md`(07-15) 结论已作废并由此文件取代；`PROJECT_PROGRESS_ANALYSIS_2026-07-18.md` 为本次刷新前的临时快照，可删除。

---

## 1. ⚠️ 与 2026-07-15 旧版的关键偏差（本次已修正）

| 旧版结论（07-15） | 实际状态（07-18） | 影响 |
|---|---|---|
| 阶段 1 OMR「0% 未开始」 | ✅ **已完成**（M2：adapter+oemer+harness+Plan A+H2） | 重大偏差 |
| 阶段 3 反向「0% 未开始 / `jianpuToStaff` NONE FOUND」 | ✅ **已完成**（phase-3/3.1/3.2，双脑闭环） | 重大偏差 |
| ctest「54/54」「79/79」 | ✅ **117/117**（54+16+10+18+15+4） | 计数口径偏差 |
| 时间线预测 M1(阶段3) 07-18→08-10、M2(OMR) 08-11→09-01 | 两者**均已提前在 07-17/18 完成** | 项目**显著超前**于 07-15 排期 |
| 「阶段 2 成果未提交」 | 阶段 2 早已提交；但**本会话 Plan A+H2+文档改动未提交** | 部分有效 |

---

## 2. 阶段完成度矩阵（刷新）

| 阶段 | 目标 | 实际状态 | 完成度 |
|---|---|---|---|
| 阶段 0 | 环境 + MusicXML 解析 | ✅ 完成；编码规范/UTF-8/多声部/和弦/装饰音全处理 | ~95% |
| 阶段 1 | OMR 黑盒集成（PDF/JPG→MusicXML） | ✅ 完成：omr_adapter + oemer/fixture 引擎 + CLI `--from-omr`；真实 oemer 端到端跑通（GPU）；评测 harness + Plan A + H2 | **100%**（含可量化评测） |
| 阶段 2 | 五线→简谱核心（MVP v1） | ✅ 完成：L0/L1/L2/L3 + CLI + 单测 + music21 100% 校验；已打 `phase-2` | ~95%（后置美化） |
| 阶段 3 | 简谱→五线（反向） | ✅ 完成：`jianpuToStaff` + `scoreToMusicXML` + round-trip 自洽；phase-3/3.1/3.2 | ~95% |
| 阶段 4 | AI / 深度学习进阶 | ⬜ 未开始 | 0% |
| 阶段 5 | 工程化与 GUI | ⬜ 未开始 | 0% |

**两种口径整体完成度**
- **核心 MVP（双向转换 + OMR 输入）**：≈ 95%，差 git 提交/推送与个别边缘美化。
- **全 6 阶段系统口径**：阶段 0+1+2+3 ≈ 已完成 4/6 阶段；按工期权重（阶段4/5 合计占比极大）粗估 ≈ **45–55%**，较 07-15 的 25–30% 显著提升。

---

## 3. 模块级状态（research_report §2.1 对照）

| 模块 | 职责 | 状态 |
|---|---|---|
| ① 输入解析 | PDF/JPG→图像 | ✅ oemer 黑盒承担（M2） |
| ② 乐谱识别 OMR | 图像→MusicXML | ✅ oemer 0.1.x 集成 + 6 处 site-packages 补丁 |
| ③ MusicXML I/O | 解析/生成 | 解析 ✅；生成 ✅（阶段3 G2 序列化自洽） |
| ④ 格式转换 | 五线⇄简谱 | 正向 ✅；反向 ✅（双向闭环） |
| ⑤ 输出/渲染 | 简谱文本/HTML + MusicXML + GUI | 简谱文本/HTML/JSON ✅；MusicXML 导出 ✅；GUI ❌ |

---

## 4. 当前进行中 / 焦点事项

### 4.1 已落地并已于 2026-07-20 提交（含推送 private 远端）
- **Plan A 调号重推断（gt 对齐法）**（`tools/omr_oemer.py`+`omr_eval_groundtruth.py`）：commit `2c53f44`。真实 concerto `pitch_accidental` 82.7%（a 小调不再清零泄漏）。⚠️ 注：gt 对齐法**仅在有 gt 时生效**；真实推理（无 gt）仍回退原 `_apply_alters`，a 小调泄漏仍在 → 见 4.3 的 M2-opt-A2 生产缺口。
- **H2 分维指标 + 评测 harness 修正 + gt 按页切分**（`tools/omr_eval_lib.py`/`omr_eval_groundtruth.py`/`_split_gt_per_page.py`）：commit `bbfa420`。
- **`_merge_align` 同小节音序对齐 fallback**（`tools/omr_eval_lib.py`）：commit `a4e4e96`。真实数据 A/B：event_count 未配对 2197→1926（−12.3%），notes_compared 808→944（+16.8%），note_pass 2.48%→2.65%。
- **`.gitignore` 排除 OMR 运行产物**：commit `6e5bf5e`。12 项运行产物本地保留、不入库。
- 上述全部已推送至 private `origin/main`（`1286031..6e5bf5e`，0/0 同步）。

### 4.2 下一步最高杠杆（F3 几何校正器，下一焦点·启动中）
- 根因：oemer 音高完全由几何 `staff_line_pos` 决定；`pitch_degree` 错=符头 bbox 中心对插值线/间中心 off-by-one。
- Plan A 只改 fifths+alter，**碰不到归因层**→ 对 degree/octave 无效（故 concerto 仍个位数）。
- 实施：oemer sidecar 补丁暴露符头 y/谱线坐标 → Pudu 侧用真实几何重算 step/octave/clef。主攻 `pitch_degree`（占失败音符 ~86%）。

### 4.3 未决 / 待办（按优先级）
- **P1 · Plan A 生产路径缺口（M2-opt-A2，待修）**：gt 对齐法已修评测期泄漏，但**真实推理无 gt 时回退原 `_apply_alters` 仍把 a 小调合法变化音误清零**。需改用 oemer 检测的调号 + 符头拼写推断 alter（不依赖 gt）。决定在 F3 之后做。
- **P0 · oemer site-packages 补丁固化**：6 处防御补丁在 `pip install --upgrade oemer` 时丢失；必须 fork oemer 或随 Pudu 分发（阶段4 计划）。

---

## 5. 关键量化数据（来自 harness 真实评测）

### 5.1 concerto（a 小调，单谱表 G 谱号，主测试集，2026-07-20 最新评测）
| 维度 | 通过率 | 说明 |
|---|---|---|
| `note_pass`（联立） | 2.65%（post 对齐；pre 对齐 2.48%） | 所有维度同时正确，非单维 |
| `pitch_degree` | **14.0%** | 🔴 最短板 = F3 靶心（占失败音符 ~86%，无方向性 升329/降366） |
| `rhythm` | 45.3% | 时值线漂移普遍 |
| `pitch_octave` | 59.2% | 加线整八度误计 |
| `octave_jump` | 95.4% | 大八度级跳变较少 |
| `pitch_accidental` | 82.7% | **Plan A(gt 对齐) 修复后**达标 |
| `rest` | 97.0% | 健康 |

> 注：旧版 5.1 的 17.66%/36.98%/96.32% 来自 pre-alignment/不同口径评测，已以上表 07-20 最新数据为准。`event_count` 未配对 1926（对齐前 2197）。

### 5.2 canon（D 大调，Plan A 验证对象）
- 单页 P1 note_pass：方案A 前 1.6%(2/122) → 方案A 后 **9.8%(12/122)**（+8.2pp），`pitch_accidental` 归零。

### 5.3 自洽基线
- `--no-oemr` 自洽：**100%**（concerto 11598/11598），证明比对管线正确，真实误差全来自 oemer OMR 阶段。

---

## 6. 风险与未决（按优先级）

| 优先级 | 风险/事项 | 说明 |
|---|---|---|
| **P0** | oemer site-packages 补丁丢失 | 6 处防御补丁在 `pip install --upgrade oemer` 时会全丢；必须 fork 或随 Pudu 分发 |
| **P1** | Plan A 生产路径缺口（M2-opt-A2） | gt 对齐法已修评测期泄漏，但无 gt 真实推理仍回退原 `_apply_alters` 误清零 a 小调变化音 |
| **P2** | **F3 几何校正器（下一焦点·启动中）** | oemer 音高纯几何决定；sidecar 暴露符头 y/谱线 → Pudu 几何重算 step/octave/clef，主攻 `pitch_degree` 14.0% |
| **P2** | 多页纵向拼接加剧八度错乱 | octave_jumps 69 vs 单页 5；真实评测须用单页分页 |
| **P2** | 近空白页 oemer 崩溃 | 非识别失败，是输入无内容；补丁 #5/#6 仍崩在零谱线 |
| **P2** | harness 非递归 | `os.listdir(corpus_dir)` 只扫一层，须直接指向 `concerto_pages/` 子目录 |
| **P3** | 阶段 4/5 未启动 | AI/DL 与 GUI 是作品集收尾关键，尚无排期 |

---

## 7. git 状态核对（实测 2026-07-21）

```
分支：main（本地 HEAD = 6e5bf5e chore: .gitignore 排除 OMR 运行产物）
远程：origin = https://github.com/youzi467/Pudu  ← ✅ private 仓库，已于 2026-07-20 推送 1286031..6e5bf5e，0/0 同步
工作树：干净（运行产物已被 .gitignore 排除，不入库）

已提交关键里程碑（近期）：
  6e5bf5e(.gitignore) / a4e4e96(对齐 fallback) / bbfa420(eval harness+切分+文档) / 2c53f44(Plan A gt 对齐)
  69b1c70(M2 OMR集成) / 7609710(harness) / 93ff33e(M1.5) / 1286031(eval规范)

运行产物（本地保留，已 gitignore，不提交）：
  data/omr_eval/real/  data/omr_eval/_abtest/  data/omr_eval/selfcheck/
  data/oemer_out/  data/_omr_batch_out/  data/*.pkl  *_trace*  *_jianpu.html
  test_omr_*.musicxml  SESSION_SUMMARY_*.md
```

> 提交纪律：运行产物（见上）**已写入 `.gitignore` 排除**；`data/omr_eval/real/` 评测语料按 `data/omr_eval/README.md §5.6` 规范精确暂存。

---

## 8. 刷新后的优先级路线图（2026-07-21 更新）

| 优先级 | 任务 | 状态 | 理由 |
|---|---|---|---|
| ✅ 已完成 | 推送 private 远端 + 提交 Plan A/H2/对齐/.gitignore | **DONE 07-20** | 零丢失风险已解除，口径已入 git |
| **P0** | fork oemer 固化 6 防御补丁（或随 Pudu 分发） | 待办 | pip upgrade 即丢，须固化 |
| **P1** | **M2-opt-A2 Plan A 生产路径补全**（无 gt 也正确推断 alter） | 待办 | 解除真实推理 a 小调泄漏 |
| **P2** | **F3 几何校正器**（oemer sidecar + Pudu 几何重算音高） | **下一焦点（启动中）** | 主攻 `pitch_degree` 14.0%，当前最高杠杆 |
| **P2** | P0-2 预处理脚本（A/B 由 harness 量化净收益后再决定） | 待办 | 照片类输入鲁棒性 |
| **P3** | P1-1 后处理规则引擎（节拍对账/八度连续性/调内一致性） | 待办 | 保 100% 不变量前提下攻 `rhythm`/`octave` |
| **P4** | 阶段 4 AI/DL、阶段 5 GUI | 未启动 | 作品集收尾，依赖 F3 量化结论 |

> 战略已定（见 `docs/jianpu-ocr-optimization-plan.md`）：短期只做 Pudu 可控三招（预处理/后处理/错误分析 harness），**先量后训**；fork/finetune oemer 仅作条件触发选项。

---

## 附：文档信源可信度评级

| 文档 | 时效 | 可信度 | 备注 |
|---|---|---|---|
| `SESSION_SUMMARY_OMR_2026-07-17_18.md` | 07-18 | ★★★★★ | 最新、含根因/数据/文件清单 |
| `MEMORY.md` / `.workbuddy/memory/2026-07-18.md` | 07-18 | ★★★★★ | 长期记忆+当日日志，与 git/实测一致 |
| `README.md` / `docs/m2-*.md` / `data/omr_eval/README.md` | 07-17 | ★★★★☆ | 已刷新，细节充分 |
| `docs/jianpu-ocr-optimization-plan.md` | 07-17（含 §8 落地更新） | ★★★★☆ | 设计+部分落地，F3 路线清晰 |
| `project_progress_analysis.md` | **本文件 07-18 刷新** | ★★★★★ | 取代 07-15 旧版，权威源 |
| `project_timeline.md` | **07-18 刷新** | ★★★★☆ | 反映阶段1/3 已完成，重排阶段4/5 |
