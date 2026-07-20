# 谱渡 Pudu · 项目进展全面分析报告

> 生成/刷新时间：2026-07-18（刷新版，取代 2026-07-15 旧版）
> 分析范围：工作区全量 `.md` + 源码/头文件/Python 工具 + git 实测状态 + 远程仓库核查
> 参照基准：`SESSION_SUMMARY_OMR_2026-07-17_18.md`、`MEMORY.md`、`.workbuddy/memory/2026-07-18.md`、GitHub 远端核查（2026-07-18）

---

## 0. 一句话结论

**截至 2026-07-18，谱渡 Pudu 的「转换大脑 + 眼睛」双线已实质打通**：阶段 0/2/3（双向 MusicXML⇄简谱）与阶段 1（OMR 黑盒集成 + 评测 harness + Plan A 调号后处理 + H2 分维指标）全部完成，端到端链路 `乐谱图 → oemer → MusicXML → 简谱` 已在本机 GPU 跑通。当前唯一进入实质开发的优化项是 **F3 几何感知音高校正器**（主攻 `pitch_degree`，当前最弱 17.66%）。

**🔴 头号紧急项（2026-07-18 新发现）**：`git remote` 指向的 `https://github.com/youzi467/Pudu` **在 GitHub 上不存在/不可达**（owner `youzi467` 存在，但其下无 `Pudu`/`pudu` 仓库，均 404）。**本地全部提交与未提交工作没有任何可靠的远程备份**——本地机器若损坏即全损。须立即创建该仓库并推送。

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

### 4.1 已落地待提交（代码+文档，均未 git 跟踪，本地无远程备份）
- **Plan A 调号重推断**（`tools/omr_oemer.py`+`omr_eval_groundtruth.py`）：canon 单页 note_pass 1.6%→9.8%，`pitch_accidental` 归零。
- **H2 分维指标**（`tools/omr_eval_lib.py`+`omr_eval_groundtruth.py`）：`category_pass` + `octave_jump` 类别 + 逐音 diff 导出；QA 验证通过。
- 相关文档刷新（README/MEMORY/docs）已落盘但**未提交**。

### 4.2 下一步最高杠杆（F3 几何校正器，未启动）
- 根因：oemer 音高完全由几何 `staff_line_pos` 决定；`pitch_degree` 错=符头 bbox 中心对插值线/间中心 off-by-one。
- Plan A 只改 fifths+alter，**碰不到归因层**→ 对 degree/octave 无效（故 concerto 仍个位数）。
- 实施：oemer sidecar 补丁暴露符头 y/谱线坐标 → Pudu 侧用真实几何重算 step/octave/clef。主攻 `pitch_degree`（占失败音符 ~86%）。

### 4.3 未决待用户拍板
- **🔴 远程仓库缺失**：`git remote` 指向的 `youzi467/Pudu` 在 GitHub 不存在；本地工作**零远程备份**，须创建并推送。
- **Plan A 精度泄漏（待验证#2）**：`_apply_alters` 把 a 小调合法调外变化音误清零（29 个 `pitch_accidental` 失败 100% = "gt 有→pred 丢"）。需补「保留 gt 合法变化音」例外。决定在 F3 前/中/后修。

---

## 5. 关键量化数据（来自 harness 真实评测）

### 5.1 concerto（a 小调，单谱表 G 谱号，主测试集）
| 维度 | 通过率 | 说明 |
|---|---|---|
| `note_pass`（联立） | 4.6%（36/787） | 所有维度同时正确，非单维 |
| `pitch_degree` | **17.66%** | 最短板 = F3 靶心（占失败音符 ~86%） |
| `rhythm` | 36.98% | 时值线错判普遍 |
| `pitch_octave` | 59.34% | 加线整八度误计 |
| `octave_jump` | 96.95% | 大八度级跳变较少 |
| `pitch_accidental` | 96.32% | **受 Plan A 泄漏压低**（真实应更高） |

### 5.2 canon（D 大调，Plan A 验证对象）
- 单页 P1 note_pass：方案A 前 1.6%(2/122) → 方案A 后 **9.8%(12/122)**（+8.2pp），`pitch_accidental` 归零。

### 5.3 自洽基线
- `--no-oemr` 自洽：**100%**（concerto 11598/11598），证明比对管线正确，真实误差全来自 oemer OMR 阶段。

---

## 6. 风险与未决（按优先级）

| 优先级 | 风险/事项 | 说明 |
|---|---|---|
| **🔴 P0** | **远程仓库缺失，本地零备份** | `youzi467/Pudu` 在 GitHub 不存在（owner 存在但无此仓库，均 404）；本地提交+未提交工作全在单机，**须立即建仓并推送** |
| **P0** | oemer site-packages 补丁丢失 | 6 处防御补丁在 `pip install --upgrade oemer` 时会全丢；必须 fork 或随 Pudu 分发 |
| **P1** | Plan A 精度泄漏（待验证#2） | 小调/变化音曲目净负面，需补「gt 合法变化音保留」例外 |
| **P2** | 多页纵向拼接加剧八度错乱 | octave_jumps 69 vs 单页 5；真实评测须用单页分页 |
| **P2** | 近空白页 oemer 崩溃 | 非识别失败，是输入无内容；补丁 #5/#6 仍崩在零谱线 |
| **P2** | harness 非递归 | `os.listdir(corpus_dir)` 只扫一层，须直接指向 `concerto_pages/` 子目录 |
| **P3** | 阶段 4/5 未启动 | AI/DL 与 GUI 是作品集收尾关键，尚无排期 |

---

## 7. git 状态核对（实测 2026-07-18）

```
分支：main（本地 HEAD = 1286031 docs(eval): document real-sample submission spec）
远程：origin = https://github.com/youzi467/Pudu  ← ⚠️ GitHub 核查该仓库不存在(404)
推送历史：无证据表明已推送；本沙箱 HTTPS 无凭据无法 push/fetch（非交互 tty）

已提交关键里程碑：69b1c70(M2 OMR集成) / 7609710(harness) / 93ff33e(M1.5) / 1286031(eval规范)

未提交（modified，含 Plan A + H2 + 文档刷新）：
  README.md  data/omr_eval/README.md  docs/{jianpu-ocr-optimization-plan,m2-increment-prd,m2-real-run-guide}.md
  tools/omr_eval_groundtruth.py  tools/omr_eval_lib.py  tools/omr_oemer.py

未跟踪（评测语料 + 运行产物）：
  data/omr_eval/real/（6页 concerto 评测语料+产物）  data/oemer_out/  data/_omr_batch_out/
  data/river_1.pkl  data/oemer_traceback.txt  data/_oemer_trace.py
  river_1_jianpu.html  test_omr_fixture_out.musicxml  test_omr_pipeline.musicxml
  data/omr_eval/selfcheck/omr_eval_report.json  SESSION_SUMMARY_OMR_2026-07-17_18.md
```

> 提交纪律：运行产物（`data/oemer_out/`、`data/_omr_batch_out/`、`*.pkl`、`*_trace*`、`*_jianpu.html`、`test_omr_*.musicxml`）**不应提交**；`data/omr_eval/real/` 评测语料按 `data/omr_eval/README.md §5.6` 规范精确暂存。

---

## 8. 刷新后的优先级路线图

| 优先级 | 任务 | 理由 |
|---|---|---|
| **🔴 P0** | **创建 GitHub 仓库 `youzi467/Pudu` 并推送 main（含全部已提交+未提交工作）** | 本地零远程备份，防全损 |
| **P0** | 提交 Plan A + H2 + 文档刷新到 git（精确 `git add`，排除运行产物）；fork oemer 固化 6 补丁 | 防丢失 + 可复现底线 |
| **P1** | 修 Plan A 精度泄漏（待验证#2 例外） | 解除对变化音小调曲目的净负面 |
| **P2** | **F3 几何校正器**（oemer sidecar + Pudu 几何重算音高） | 主攻 `pitch_degree`，当前最高杠杆 |
| **P2** | P0-2 预处理脚本（A/B 由 harness 量化净收益后再决定） | 照片类输入鲁棒性 |
| **P3** | P1-1 后处理规则引擎（节拍对账/八度连续性/调内一致性） | 保 100% 不变量前提下攻 `rhythm`/`octave` |
| **P4** | 阶段 4 AI/DL、阶段 5 GUI | 作品集收尾，依赖前序量化结论 |

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
