# 谱渡 Pudu · MVP 范围 / 验收 PRD

| 项 | 内容 |
| --- | --- |
| 文档类型 | MVP 范围 PRD（**简单版**，需求侧定义，不含技术实现 / 架构） |
| 作者 | 许清楚（产品经理） |
| 日期 | 2026-08-06 |
| 关联版本 | MVP(phase-3) / M2 / P0-1 / P0-2 / P1-1 / P1-2 / M2-opt-A2 已达成 |
| 交付物 | 本文件：`docs/mvp-scope-prd.md` |
| 缺口背景 | 当前仓库**无任何 MVP 范围文档**，本文件把含糊的"MVP 阶段"具象为可验收清单 |

> 说明：本 PRD 为**简单 PRD**，默认不引入竞品分析。所有验收口径均锚定已核验的仓库事实（`build/Testing/Temporary/LastTest.log`、`p0-2-preprocess-design.md` R-P0-02、`omr_abtest_lib.py` `INVARIANT_EXPECTED_GT`、README CLI）。

---

## 1. 产品目标与定位

谱渡 Pudu 是 C++20 实现的 **MusicXML ⇄ 简谱双向转换器**，并带一条 **OMR 管线**（以外部 `oemer` 0.1.8 模型为黑盒，将印刷谱图像识别为 MusicXML 后转简谱）。本 MVP 的目标不是"全功能乐谱软件"，而是交付一个**可信、可验收、CLI 优先**的命令行工具：在明确约束（**单声部 / ≤2 个升号或降号 / 印刷谱**）下稳定完成双向转换与"图 → 简谱"端到端链路，并把所有易错增强（预处理 / 后处理 / 调参）做成**默认关闭的 opt-in 能力**——确保关开关时行为逐字节等价于基础内核，让"忠于内核"成为可机器验证的不变量，而非口头承诺。

---

## 2. 目标用户与用户故事

| # | 角色 | 用户故事（作为 …，我希望 …，以便 …） |
| --- | --- | --- |
| U1 | 音乐爱好者 / 教师 | 作为用户，我希望丢一个 MusicXML 或印刷谱图片进 CLI，得到可读的简谱（L1 文本 / L2 HTML / L3 JSON），以便快速把五线谱教材转成简谱讲义。 |
| U2 | 开发者 / 维护者 | 作为维护者，我希望 `ctest` 与 `pytest` 即证明双向转换与 OMR 链路契约正确、且默认开关不影响基础产物，以便无回归地迭代。 |
| U3 | 评测者 / 研究员 | 作为评测者，我希望用评测 harness 在 MVP 语料上量化 oemer 识别质量与增强增益，以便基于数据决策是否开启预处理 / 后处理。 |
| U4 | 长尾输入处理者（照片类 / 低对比度谱） | 作为用户，我可显式加 `--omr-preprocess` 让拍照 / 低对比度 / 轻微倾斜谱面获得增强（默认关、字节透明），以便在不破坏基础产物契约前提下获得更稳的识别；该能力为 opt-in，MVP 验收语料仍以印刷谱为准。 |
| U5 | 简谱作者 | 作为用户，我希望把简谱文本 / JSON 反向生成五线谱 MusicXML（阶段 3 反向闭环），以便双向编辑与互校。 |

---

## 3. MVP 范围边界

### 3.1 IN（纳入 MVP）

| 编号 | 能力 | 状态 / 约束 |
| --- | --- | --- |
| IN-1 | CLI 双向转换 MusicXML ⇄ 简谱（L1 文本 / L2 HTML / L3 JSON / 反向 MusicXML） | 核心内核 phase-3 已完成 |
| IN-2 | OMR 管线：`oemer` 0.1.8 黑盒 → MusicXML → 简谱 | 限**单声部 / ≤2 升号或降号 / 印刷谱**；M2 已完成 |
| IN-3 | 评测 harness（P0-1）：量化 oemer 识别质量与增强增益 | 已完成 |
| IN-4 | 图像预处理 P0-2（`--omr-preprocess`）：opt-in，**默认 OFF** | 已完成；字节透明（R-P0-02） |
| IN-5 | 后处理音乐规则引擎 P1-1（`--apply-postcorrect`）：opt-in，**默认 OFF** | 已完成；干净 GT 零修正红线 |
| IN-6 | 预处理 A/B 研究 P1-2（默认 OFF，置信度仅 directional-only） | 已完成 |
| IN-7 | 无 GT 调号推断 M2-opt-A2（Plan A 生产路径补全） | 已完成 |
| IN-8 | MVP 验证语料约束：**单声部 / ≤2 升降号 / 印刷谱** | 语料与验收约束，**非架构硬上限** |

**MVP 已达成里程碑 → IN 映射（核验）**

| 里程碑 | 对应 IN | 核验依据 |
| --- | --- | --- |
| MVP(phase-3) 核心转换内核 | IN-1 / U5 | README §双向互转；`jianpuToStaff` + `scoreToMusicXML` |
| M2 OMR 集成 | IN-2 | `omr_adapter` + CLI `--from-omr`；真实 oemer 本机 GPU 跑通 |
| P0-1 评测 harness | IN-3 | `tools/omr_eval_groundtruth.py` 等 |
| P0-2 图像预处理（默认 OFF） | IN-4 | `omr_pipeline.py` / `--omr-preprocess`；R-P0-02 |
| P1-1 后处理规则引擎（默认 OFF） | IN-5 | `jianpu_postcorrect` / `--apply-postcorrect`；13-GT 红线 |
| P1-2 预处理 A/B 研究（默认 OFF） | IN-6 | `omr_abtest_p1_2.py`；directional-only |
| M2-opt-A2 无 GT 调号推断 | IN-7 | commit `997b3aa`；`tests/test_omr_oemer_altinfer.py` 8 passed |

### 3.2 OUT（不纳入 MVP · 标为未来 / 后续阶段）

| 编号 | 排除项 | 归属阶段 / 备注 |
| --- | --- | --- |
| OUT-1 | 多声部鲁棒性 | `concerto_pages` 为两声部 demo；oemer 在其上 staffline 提取崩溃属 **oemer 脆弱性**，非我方 bug，不计入 MVP 验收 |
| OUT-2 | 真实拍摄样本（U4） | MVP 阶段**延后**；MVP 验收语料为印刷谱 |
| OUT-3 | GUI / Web UI | MVP 以 CLI 优先；Web UI（Vite+React+MUI+Tailwind）非 MVP |
| OUT-4 | oemer 模型微调 / fork 固化 6 处 site-packages 补丁 | P0 风险项，属阶段 4 / 后续部署工程 |
| OUT-5 | 打包 / 发布自动化（CI/CD、安装包、release artifact） | 后续工程化阶段 |
| OUT-6 | F3 几何校正器上线 | 全量 A/B 证实对 oemer 0.1.8 **零效果**，保留为默认 OFF 实验性基础设施，不作音准改进上线 |

---

## 4. 验收标准（具体、可勾选）

| 编号 | 验收标准 | 可检验定义 | 优先级 |
| --- | --- | --- | --- |
| **AC-1** | `ctest` 全绿 | `ctest`（单一入口 `PuduTests`）运行 **161/161** 通过、0 断言失败（以 `build/Testing/Temporary/LastTest.log` 最新为准：`运行 161 个测试` / `161/161 通过`）。 | P0 |
| **AC-2** | harness / Python 单测全绿 | `pytest`（评测 harness P0-1 + F3 Python 单测 + P1-2 不变量守卫等）全绿，无失败 / 错误。 | P0 |
| **AC-3** | CLI 双向转换产出合法 | 对 MVP 语料，`./Pudu <x.musicxml> --to-jianpu` / `--to-jianpu-l2` / `--to-jianpu-json` / `--to-musicxml` 均退出码 0，产出可被本仓库解析器 / 校验器读回的合法结构（music21 校验通过）。 | P0 |
| **AC-4** | CLI OMR 链路在 MVP 语料产出合法 | `./Pudu --from-omr <printed_single_voice.musicxml\|image> --to-jianpu` 在 **fixture 引擎**（确定性、不依赖外网）下产出非空合法简谱；真实 oemer 在用户本机 GPU 环境已端到端跑通。 | P0 |
| **AC-5** | 默认 OFF 字节透明（R-P0-02） | 预处理默认关：同一样张「不加 `--omr-preprocess`」与「P0-2 前旧命令」产出 MusicXML **逐字节相同**、工作区零新增文件；关闭路径**不经** `omr_pipeline.py`（见 `p0-2-preprocess-design.md` D4 / R-P0-02）。 | P0 |
| **AC-6** | 后处理干净 GT 零修正（P1-1 红线） | **13 份干净 GT**（6 页 concerto GT + 7 份 P1-1 语料，即 `INVARIANT_EXPECTED_GT = 13`）跑 `--apply-postcorrect`，`applied == 0`；Stage-3 不变量守护覆盖恰为 13 份、不被 `--limit` 截断静默绕过（真空为真漏洞已堵）。 | P0 |
| **AC-7** | MVP 验证边界守住 | faith 验收仅用**单声部 / ≤2 升降号 / 印刷谱**；`concerto_pages` 两声部 demo 不计入 MVP 工程验收（oemer staffline 崩溃归 oemer 脆弱性）。 | P0 |
| **AC-8** | 已知模型瓶颈不作为工程验收门槛 | oemer 基础识别质量（a 小调 concerto 语料 `pitch_degree`≈13.6% / `rhythm`≈46.7%）属**模型问题、非工程问题**（注：该 `pitch_degree` 数字 2026-08-06 复核为**不可信**——是评测对齐退化为随机配对的假象，见 `docs/omr-engine-feasibility.md` 附录 A；但不影响本 AC 结论，因其本就不计入工程验收）；MVP 不要求达标；U4 真实拍摄样本不在 MVP 验收内。 | P0 |
| **AC-9** | 默认 OFF 的 MusicXML→简谱 100% 不变 | 关闭所有增强（预处理 / 后处理 / 调参）时，MusicXML→简谱投影与基础内核**逐字节 / 逐字段一致**（红线契约，SK-7）。 | P1 |
| **AC-10** | opt-in 增强可独立验证 | `--omr-preprocess` / `--apply-postcorrect` 各自有可构造输入样本 + 可判定断言；开启 / 关闭互不影响基础产物契约。 | P1 |

**验收门禁总览（P0 必过）**：AC-1 + AC-2 + AC-3 + AC-4 + AC-5 + AC-6 + AC-7 + AC-8 全绿 ⇒ MVP 工程验收通过。AC-9 / AC-10 为增强层契约加固（P1）。

---

## 5. 待确认问题 / 需用户拍板项

| # | 待确认项 | 选项 / 建议 | 影响 |
| --- | --- | --- | --- |
| **Q1** | 打包形式 | (a) 仅交付 `Pudu.exe` + 依赖 DLL（PATH 注入 vcpkg bin）；(b) 随 oemer 分发（需 fork / 固化 6 处 site-packages 补丁）；(c) 单文件便携包 | 决定 MVP 交付形态与可复现性 |
| **Q2** | 是否发布 / 发布到哪 | `origin/main` 已推送、0/0 同步（private）；是否打 release tag？是否对外？ | 发布范围 |
| **Q3** | oemer 补丁固化策略（P0 风险） | fork oemer 仓库 vs 随 Pudu 分发补丁（`pip install --upgrade oemer` 会丢失 6 处防御补丁） | 部署可复现性 |
| **Q4** | 默认开关在 `--from-omr` 入口的最终默认 | P1-2 建议：仅 `--from-omr` 入口默认开（配 `--no-postcorrect` 逃生舱），纯 MusicXML 转换保持默认关。MVP 验收以"默认 OFF + 字节透明"为准，最终默认待拍板 | 用户体验 / 红线契约 |
| **Q5** | F3 几何校正器处置 | 保留为默认 OFF 实验性基础设施（已证零效果）or 移除 | 代码体积 / 维护 |
| **Q6** | 真实拍摄样本（U4）确认延后 | 确认 MVP 验收语料维持**印刷谱**，U4 不纳入 | 验收边界 |
| **Q7** | 多声部是否进入下阶段范围 | `concerto_pages` 两声部为已知 oemer 脆弱点；是否启动多声部鲁棒性（OUT-1） | 路线图 |
