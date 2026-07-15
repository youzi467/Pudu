# 谱渡 Pudu · 项目进度状态与时间线规划

> 生成时间：2026-07-15  
> 依据：`omr-tool-research/results/research_report.md`（总路线/架构/6 阶段）、`stage3_action_plan.md`、`learning_path.md`、`project_progress_analysis.md`、`README.md`、以及本会话 git 实测状态。  
> 时间基准：今天 **2026-07-15（周三）**；下文工期以"课余并行、每天 2–3 小时"为假设，可按实际投入等比缩放。总工期估算 **≈18 周（约 4.5 个月）**，落在 research_report 的 16–23 周区间内。

---

## 0. 当前进度速览（一句话）

**核心产权层的一半已完成**：正向"五线谱→简谱"（阶段 2）已 100% 校验并合并到 `main`（本地提交 `12849dd`），仅差**推送到 `origin/main`**；反向转换（阶段 3）、输入识别（阶段 1）、AI（阶段 4）、GUI（阶段 5）**全部未启动**。

---

## 1. 进度状态三分（已完成 / 进行中 / 未开始）

### 1.1 ✅ 已完成（Done）

| 模块 | 交付物 | 验收证据 |
|---|---|---|
| **阶段 0 · 环境地基** | MSVC2022 / CMake / vcpkg / Git 全链路；编码规范（`/utf-8`、`*.text=auto`）；`encoding_report.md` 确认全仓 UTF-8 无 BOM | 构建 0 错 0 警；`=== Stage 0 environment check passed ===` |
| **MusicXML 解析层（模块③ 输入侧）** | `include/score_model.hpp`（Score 模型）+ `src/musicxml_parser.cpp`（pugixml 解析）；`.mxl`/UTF-8 路径/多声部时序/和弦/装饰音全部处理 | `verify_corpus.py` 8/8 样本、80/80 检查项 PASS；4 项历史缺陷（credit/和弦/backup/装饰音）已闭环 |
| **阶段 2 · 五线→简谱（核心产权，MVP v1）** | `jianpu_model.hpp`（L0 权威模型）+ `jianpu_converter`（纯函数 + `staffToJianpu`）+ L1 文本 / L2 二维 HTML / L3 JSON 三渲染器 + CLI（`--to-jianpu` / `--to-jianpu-l2` / `--to-jianpu-json`） | 单测 **54/54 全绿**；music21 跨语言校验 **音符 100%(13492/13492)、字段 100%(79240/79240)、计入差异=0** |
| **阶段 2 · 版本控制（本地）** | `feat` squash 合并 `main`（`088d52f`）→ 合并 `origin/main`（`12849dd`）；`phase-2` 标签落在 `11998bb`；README 已刷新 | `git log` 可见 `12849dd` 为 merge 提交，`origin/main` 为其祖先，工作树干净、无冲突标记 |

### 1.2 🔶 进行中 / 待收尾（In Progress / Pending）

| 事项 | 状态 | 优先级 |
|---|---|---|
| **阶段 2 推送到远程** | 本地 `main=12849dd` 已含全部阶段 2 + 合并；`origin/main=299e742` 待快进。本环境无 GitHub 凭据，需用户在**交互终端**执行 `git push origin main`（快进、无需 force） | **P0（当前卡点）** |
| **research_report 状态刷新** | 规划文档阶段 2 仍标"未开始"、阶段 3 未标进行中；需把实际状态（2026-07-15）回填 | P1 |
| **阶段 2 边界补全（硬化）** | 小调"6=X"开关、和弦逐音八度点、变调段重算首调、L2 连音弧跨音精确连线、减时线按真实 beat 分组、极端连音比（7:8/7:4/9:4，46 处）单列项 | P2 |
| **文件夹重命名 `omr`→`Pudu`** | 文档已定名，但活动工作区被宿主锁定，需关闭工作区后手动执行（非阻塞） | P3 |
| **OpenCV 基础（S4–S5）** | 架构决策已降级为"选做/练兵"，`find_package(OpenCV)` 仍注释；接入未做 | 选做 |

### 1.3 ⬜ 尚未启动（Not Started）

| 阶段 | 目标 | 关键缺口 |
|---|---|---|
| **阶段 1 · OMR 黑盒集成** | PDF/JPG → MusicXML 输入链路 | 子进程调 Audiveris/oemer 未实现；当前输入仍依赖人工 `data/*.musicxml` |
| **阶段 3 · 简谱→五线谱（反向）** | `jianpuToStaff` + `Score→MusicXML` 序列化 + round-trip 自测 | 全仓检索 `jianpuToStaff` = NONE FOUND；模块⑤"MusicXML 导出"未实现 |
| **阶段 4 · AI / 深度学习** | 自训/微调识别模型 + ONNX 部署 + 评测 | PyTorch/ONNX Runtime/合成数据/评测脚本均无 |
| **阶段 5 · 工程化与 GUI** | Qt/ImGui 应用 + 打包 + 作品集 | GUI/输入面板/纠错编辑器/打包均未做 |

---

## 2. 结构化时间线规划

### 2.1 总体时间线表

| 里程碑 | 阶段内容 | 起止日期 | 工期 | 关键交付 / 里程碑节点 | 优先级 | 依赖 |
|---|---|---|---|---|---|---|
| **M0** | 阶段 2 收尾与上线 | 2026-07-15 → 07-17 | ~3 天 | `git push origin main` 完成；research_report 状态回填；可选文件夹重命名 | P0 | 阶段 2 ✅ |
| **M1** | 阶段 3 简谱→五线谱 | 2026-07-18 → 08-10 | ~3 周 | G1 `jianpuToStaff` → G2 `Score→MusicXML` → G3 round-trip 100% 守恒 → `phase-3` 标签 + `--to-musicxml` CLI | P1 | 阶段 2 ✅ |
| **M1.5** | 阶段 2 边界补全（与 M1 并行） | 2026-07-18 → 08-10 | 并行 | 小调 6=X / 和弦八度点 / 变调重算 / L2 美化 等边界闭合 | P2 | 阶段 2 ✅ |
| **M2** | 阶段 1 OMR 黑盒集成 | 2026-08-11 → 09-01 | ~3 周 | 装 Audiveris/oemer → music21 验证 → C++ 流水线 `PDF→Score→控制台音高` | P3 | 阶段 0 ✅ |
| **M3** | 阶段 4 AI / 深度学习 | 2026-09-02 → 10-28 | ~8 周 | PyTorch 入门 → 合成数据微调/适配预训练 → ONNX 部署 → 评测报告（precision/recall） | P4 | M1,M2（识别链路）+ 阶段 2/3（MusicXML 表示） |
| **M4** | 阶段 5 工程化与 GUI | 2026-10-29 → 11-19 | ~3 周 | Qt GUI（开谱/显简谱/导出）→ 打包 → 技术报告 + GitHub 仓库整理 | P5 | M1,M2（核心闭环，M3 可选） |

> **推荐顺序说明**：M1（阶段 3）建议**先于** M2（阶段 1）——它是纯 C++、风险最低、直接补全核心"双脑"产权，且不依赖 OMR 黑盒；M2 需装 Java/Python 引擎、受本机 TLS 拦截影响风险更高。若你更想先看到"PDF→简谱"前向 Demo，可把 M2 与 M1 对调（二者都只依赖阶段 0/2，互不阻塞）。

### 2.2 里程碑节点详表（带验收标准 DoD）

| 节点 | 日期 | 验收标准（Definition of Done） |
|---|---|---|
| **M0-1 推送完成** | 2026-07-17 | `git push origin main` 成功；GitHub `origin/main` = `12849dd`；CI/构建可复现 |
| **M0-2 文档回填** | 2026-07-17 | `research_report.md` 阶段 2 标"✅ 完成"、阶段 3 标"🔶 进行中"；单测数统一为 54/54 |
| **M1-1 G1 `jianpuToStaff`** | 2026-07-25 | 实现并通过反向九项边界单测（中/高低八度、#4/b7、各调号、附点、和弦、多声部、休止、装饰音） |
| **M1-2 G2 序列化** | 2026-08-01 | `Score→MusicXML` 写出 `.musicxml`，能被本仓库解析器读回且语义等价 |
| **M1-3 G3 round-trip** | 2026-08-07 | `staffToJianpu→jianpuToStaff` 对 `data/` 单声部子集音高序列 100% 守恒；阶段 2 的 54/54 单测无回归 |
| **M1-4 `phase-3` + CLI** | 2026-08-10 | 打 `phase-3` 标签；`--to-musicxml [out]` 可演示端到端反向；README/overview 更新 |
| **M2-1 引擎可用** | 2026-08-15 | 本地 Audiveris 或 oemer 对一个 PDF 跑出 `.musicxml` |
| **M2-2 music21 验证** | 2026-08-22 | Python 脚本读该 MusicXML 打印音高/调号，人工核对一致 |
| **M2-3 C++ 流水线** | 2026-09-01 | `PDF → system("audiveris…") → MusicXML → Score → 控制台音高` 串通 |
| **M3-1 训练闭环** | 2026-10-01 | 最小音符检测模型在 MVP 测试集输出 precision/recall |
| **M3-2 ONNX 部署** | 2026-10-15 | 导出 ONNX，C++ 用 ONNX Runtime 推理，替换 Audiveris 作识别引擎 |
| **M3-3 评测报告** | 2026-10-28 | 自训模型 vs Audiveris 准确率对比报告 |
| **M4-1 GUI 可用** | 2026-11-12 | Qt 应用：打开 MusicXML/PDF → 显示简谱 → 导出 |
| **M4-2 交付** | 2026-11-19 | 安装包 + 技术报告 + GitHub 仓库（README/CI/示例/标签）整理完成 |

### 2.3 依赖关系（DAG）

```
L0 环境/MusicXML ──┬──▶ L2 五线→简谱 ✅ ──▶ L3 简谱→五线 ──┐
                   │        (阶段2 完成)      (阶段3/M1)    │
                   │                            │            │
                   └──▶ L1 OMR 黑盒 (阶段1/M2) ─┤            │
                                                │            │
                                                └──▶ L4 AI ──┴──▶ L5 工程化/GUI
                                                      (M3)        (M4)
```

- **硬依赖**：`L0→L2→L3`；`L0→L1`；`L1→L4`；`L2/L3→L4`；`L2/L3→L5`。
- **可并行**：M1（阶段 3）与 M2（阶段 1）互不依赖，可互换顺序；M1.5 边界补全与 M1 并行。
- **可选依赖**：L4（AI）对 L5 为可选后端（M4 可先接 Audiveris 黑盒）。

---

## 3. 任务优先级排序（全局 P0–P5）

| 优先级 | 任务 | 理由 |
|---|---|---|
| **P0** | M0：推送阶段 2 + 文档回填 | 当前唯一卡点；不推送则远程缺失精炼阶段 2，且无法基于远程协作/备份 |
| **P1** | M1：阶段 3 反向转换 | 核心产权闭环，使工具"真正互转"；风险低、纯 C++、不阻塞其他线 |
| **P2** | M1.5：阶段 2 边界补全 | 提升健壮性（小调/和弦八度/变调/极端连音比），是 M1 验收与产品可信度基础 |
| **P3** | M2：阶段 1 OMR 输入 | 决定能否"端到端可演示"（PDF→简谱）；需装外部引擎，风险中等 |
| **P4** | M3：阶段 4 AI/DL | 转 AI 主战场、简历高价值产出；最重、最晚，依赖前序 MusicXML 表示 |
| **P5** | M4：阶段 5 GUI/工程化 | 作品集收尾；可先用 CLI 验证功能，GUI 最后叠加 |

> 阶段内优先级见 `stage3_action_plan.md`：G1+G2(P0) → G3(P1) → G4 文本输入(P2) → 边界对齐(P3)。

---

## 4. 各阶段任务拆解（指向详细计划）

- **M1 阶段 3**：严格按 `stage3_action_plan.md` 的 S1–S10 执行（接口设计→音级逆映射→时值逆映射→组装 Score→序列化→单测→round-trip→CLI→可选文本输入→文档收尾）。
- **M2 阶段 1**：按 `learning_path.md` L1 里程碑——装引擎、music21 验证、C++ 串流水线。
- **M3 阶段 4**：按 `learning_path.md` L4——PyTorch 入门、合成数据/预训练微调、ONNX Runtime 部署、评测脚本。
- **M4 阶段 5**：按 `learning_path.md` L5——Qt/ImGui GUI、打包、文档。

---

## 5. 风险提示与进度跟踪建议

1. **M0 推送受凭据限制**：本非交互 shell 无 GitHub 凭据助手，推送须在你本机交互终端完成；推送前可 `ctest` 复跑 54/54 确认合并无回归。
2. **M2 受网络/TLS 拦截影响**：装 Audiveris(Java)/oemer(Python) 与下载语料可能遇本机 TLS 自签 CA；优先用矢量/印刷 PDF 规避扫描件噪声。
3. **进度跟踪机制**：每个里程碑结束必须有一个"可验证物"——构建通过（`cmake --build` 0 错）、单测全绿（`PuduTests.exe`）、标签（`phase-N`）、文档状态回填。建议用本文件的 §2.2 节点表做周检清单。
4. **文档一致性**：阶段状态、单测数（54/54）、路径名（`omr`/`Pudu`）在各 overview/README/research_report 间需同步，避免再次落后实际 2 天。
5. **不要手搓 CV**：识别端坚持用成熟引擎黑盒，精力集中在"转换逻辑 + AI"两块真正产权上。

---

## 附：当前 git 状态快照（2026-07-15）

```
main        = 12849dd  (merge: 整合 origin/main 早期阶段2 + 本地精炼阶段2)
phase-2 tag = 11998bb  (祖先 of 12849dd，有效)
origin/main = 299e742  (Pending: 待 git push origin main 快进)
working tree: clean, 无冲突标记
```

> 下一步动作（用户交互终端）：`git push origin main` → 随后按本时间线启动 **M1 阶段 3**。
