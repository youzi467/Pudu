# 五线谱 ⇄ 简谱互转工具：技术选型 · 系统架构 · 学习路线

> 调研时间范围：2024–2026（含稳定经典方案）｜用户画像：数字媒体技术准大二 / C++ 基础 / 乐理扎实 / 目标借项目转 AI
> MVP 约束：Windows｜输入 PDF(矢量+扫描)/JPG 印刷体｜单声部｜≤2 升降号｜无装饰音/无歌词｜经 MusicXML 中转

---

> [!NOTE]
> **项目状态与关键决策（更新于 2026-07-13；核心转换里程碑补充于 2026-07-16）**
> - **项目定名：谱渡 / Pudu**（对外显示名"谱渡"，CMake 工程名/可执行名 `Pudu`，vcpkg 包名 `pudu`）。
> - **已完成**：阶段 0 环境地基（S1 环境 / S2 工具链 pugixml 端到端 / S3 Git 入库，含 `.gitattributes` 与忽略 `.workbuddy/`）。
> - **关键决策变更**：① `libmusicxml2` 不在 vcpkg registry → 改用 **pugixml**（MVP 只需读写 XML）；② 架构决定将"手搓 OpenCV"降级为**选做/练兵**，识别端由 **Audiveris/oemer 黑盒**承担（见 §1.3 与 §4）。
> - **已完成**：MusicXML 规范通读 + 用 pugixml 解析示例并建立 Score 内存模型（原 S6–S7，已并入阶段 0/2 收尾）。
> - **下一步**：核心双向转换（阶段 2/3）已闭合；下阶段接①阶段 3 边界硬化（和弦逐音八度点 / tieStop 反向还原 / 极端连音比）+ ②阶段 1 OMR 黑盒（Audiveris/oemer：PDF/JPG→MusicXML）打通端到端；随后阶段 4 AI / 5 工程化。
> - **已完成**：阶段 0（环境地基）/ 2（五线→简谱核心）/ 3（简谱→五线，含 G1 jianpuToStaff / G2 scoreToMusicXML / G3 往返音高守恒 / G4 简谱文本输入解析器）/ 1（OMR 黑盒集成：oemer + 评测 harness + Plan A + 权重校验）；MSVC 实测 **150 个用例（1 个 ctest 入口）全绿 + 77 个 Python 单测全绿**。
- **未开始**：阶段 4（AI·DL）/ 5（工程化）。
> - 磁盘文件夹仍名为 `omr` / `omr-tool-research`（重命名为 `Pudu` / `Pudu-research` 待关闭工作区后执行）。

## 0. 执行摘要（先给结论）

**Q1 选型结论**：MVP 阶段**不要从零手搓 OpenCV**，而是采用"成熟 OMR 引擎做识别黑盒 + 自写 MusicXML⇄简谱转换层"的混合架构。把 OpenCV 自研降格为"理解原理的练兵"，把真正的 AI 学习投入点放在**后期用预训练/微调的深度学习模型替换识别引擎**上。理由：

- 你最看重"学习价值（转 AI）"和"上手速度"——手搓 CV 在这两个维度上都不占优（慢、准确率有限、且传统 CV 技巧对"转大模型"边际收益低）。
- 本项目真正的差异化产权在**五线谱⇄简谱转换逻辑**（音高↔数字、调号换算、时值映射），这一层必须自己写、价值最高、也最贴合乐理优势。
- 所有开源/商业 OMR **都不处理简谱**，只输出五线谱语义的 MusicXML——简谱互转只能你自己在 MusicXML 层实现，这恰好是"别人没有、能写进作品集"的部分。

**一句话路线**：先集成 Audiveris/oemer 出 MVP（几周），再把识别端换成你自己训练/微调的 DL 模型（转 AI 的主战场）。

---

## 1. 技术选型对比

### 1.1 候选方案与五维对比

| 方案 | 开发难度 | MVP 准确率(估计) | 学习价值(转AI) | 维护成本 | 上手速度 |
|---|---|---|---|---|---|
| ① OpenCV 传统 CV 自研 | 高 | 干净印刷 70–90%；扫描 50–70% | 中高(传统CV/图像)但偏离前沿 | 高(全自写) | 慢(数周+) |
| ② Audiveris(调/改) | 低 | 印刷单声部 85–95% | 中(读 CV+NN 混合源码) | 低(社区维护) | **快(装即用)** |
| ② oemer / homr(DL 调包) | 低 | 80–95% | 中高(NN 推理) | 低 | **快** |
| ③ 端到端 DL 自训练(SMT++/Zeus/LEGATO) | 极高 | 干净排版 TEDn≈1.6–1.8%；真实扫描≈18–30% | **最高(Transformer/CV SOTA)** | 高 | 慢(环境+数据) |
| ④ 商业对标(PhotoScore 等) | — | 标称 >99.5% | 无(闭源) | — | — |

> 注：TEDn = Tree Edit Distance normalized（越低越好）。干净"渲染排版"与"真实扫描件"准确率差距极大，是 OMR 的核心难点。

### 1.2 关键事实（2024–2026）

- **Audiveris**：最新提交 2026-04，仍在积极维护（GitHub `jostle/audiveris`），AGPL 许可证。**明确内置导出器，输出 MusicXML 4.0（子集）**。引擎混用形态学(谱线/符杠)+模板匹配(符头)+外部 OCR+**神经网络(定尺寸符号)**。官方承认 100% 识别率不可达，依赖编辑器纠错。⚠️ `audiveris.com` 是钓鱼站，正版在 GitHub。
- **端到端 DL SOTA（印刷体）**：
  - **Zeus/OLiMPiC**(ICDAR 2024)：渲染干净排版 GrandStaff-LMX **TEDn 1.6–1.8%**；真实扫描 **TEDn 18.4%**。
  - **Sheet Music Transformer++**(IJCV 2025)：全页钢琴谱端到端，零样本/微调均超越商业 PhotoScore。
  - **LEGATO**(NeurIPS 2025)：首个大规模预训练 OMR（214K 图，输出 ABC），IMSLP 钢琴谱 **TEDn 29.7**，绝对值误差较旧 SMT++ 降约 68%，**权重可下载**，是当前最强公开模型。
  - **Clarity-OMR**(2025–26)：DaViT-Base+DoRA，仅 MusicXML，CUDA；干净排版评分 69.5 vs Audiveris 25.9。
  - **homr**(cairn-labs)：oemer 强力改进版，UNet 分割+Transformer 语义，2025 活跃。
- **传统 CV 现实区间**：符号分类(符头/谱号)在 DeepScores/MUSCIMA++ 上 CNN >95%，但**整条流水线(音高+节奏分组)自研**实测通常 70–90%(理想干净印刷)，扫描件降至 50–70%，且需大量启发式规则与人工调参。
- **核心约束**：所有方案**均不处理简谱**——五线谱↔简谱互转必须由你在 MusicXML 层自行实现。

### 1.3 维度分析与 MVP 推荐

- **开发难度/上手速度（你列为高优先）**：自研 OpenCV 全链路（谱线 Hough + 模板匹配 + 音高推断 + 节奏分组 + MusicXML 生成）工程量最大、调试最苦、最快也要数周才出勉强可用的结果；而集成 Audiveris/oemer 几天即可出可用 MVP。**这一维度压倒性指向"用成熟引擎"。**
- **识别准确率**：成熟引擎在 MVP 约束（单声部/印刷体/≤2 升降号）下 85–95%，自研通常 70–90% 且上限受限于调参；深度学习方法在干净排版上可达 SOTA，但工程落地与数据门槛高。**MVP 用成熟引擎即可达标。**
- **学习价值（你列为最高优先）**：这是最微妙的一点。表面看"自研 OpenCV"学习最多，但**传统 CV 技巧（Hough/轮廓/模板匹配）对"转 AI/大模型"边际收益低**，且会把你锁在调参苦海里、推迟真正接触深度学习。更优的学习路径是：
  1. **MVP 阶段**：通过集成引擎 + 自写转换层，快速掌握"完整系统思维 + MusicXML + 音乐表示"；
  2. **AI 阶段**：用 DeepScores/DoReMi 合成数据**微调一个小模型做单声部音符检测**（或适配 LEGATO/Clarity-OMR 预训练权重），用 ONNX Runtime 在 C++ 中部署，写评测脚本——形成"数据→模型→评测"闭环，**这是能写进简历、直接服务考研 AI 方向的高价值产出**。
- **维护成本**：自研全链路依赖全在自己身上；Audiveris/oemer 有社区维护、AGPL/开源，且 MVP 阶段只当黑盒调用，维护负担最低。

**推荐方案（MVP）**：
> **混合架构 = 成熟 OMR 引擎(PDF/JPG→MusicXML) + 自写 C++ 转换层(MusicXML⇄简谱)**，核心转换逻辑用 C++ 写（契合你的基础、形成产权）。识别引擎 MVP 用 **Audiveris 或 oemer/homr**，AI 进阶阶段替换为**自训/微调的 DL 模型**。

---

## 2. 系统设计架构

### 2.1 模块划分与职责

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐
│ ① 输入解析   │──▶│ ② 乐谱识别OMR │──▶│ ③ MusicXML I/O│──▶│ ④ 格式转换    │──▶│ ⑤ 输出/渲染  │
│ InputParser │   │ Recognizer   │   │ MusicXMLRepo │   │ Converter    │   │ Presenter  │
└─────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └─────────────┘
       ▲                 │                    │  Score 对象           │ JianpuDoc            │
       │           归一化图像/矢量        MusicXML 文件/字符串   首调简谱文本/MusicXML
   PDF/JPG 矢量或扫描
```

| 模块 | 职责 | MVP 实现 | AI 进阶实现 |
|---|---|---|---|
| ① 输入解析 | 区分矢量/扫描 PDF；栅格化或提矢量；图像预处理（灰度/二值化/去噪/纠斜） | MuPDF/Poppler 栅格化 + OpenCV 预处理 | 同左 |
| ② 乐谱识别 | 图像→MusicXML | 调 Audiveris/oemer 子进程 | DL 模型推理(ONNX Runtime/LibTorch) |
| ③ MusicXML I/O | 解析/生成 MusicXML，提供内存 Score 对象 | **pugixml**(C++)（注：原定 libmusicxml2 不在 vcpkg，已改 pugixml） | 同左（Python 端用 music21 做测试对照） |
| ④ 格式转换 | 五线↔简谱双向映射（**核心产权**） | C++ 自写映射逻辑 | 同左 |
| ⑤ 输出/渲染 | 输出首调简谱文本 + MusicXML | 文本/HTML + MusicXML 导出 | Qt GUI + 简谱字体渲染 |

### 2.2 核心数据结构（模块间接口契约，C++）

```cpp
struct Pitch   { char step; int alter; int octave; };      // step:A-G, alter:-2..2(重降~重升), octave:4=中央C
struct Duration{ int divisions; int ticks; bool dotted; }; // ticks = divisions × 拍数
struct Note    { Pitch pitch; Duration dur; Accidental acc;
                 bool isRest; bool isChord; };
struct Measure { vector<Note> notes; };
struct Part    { Key key; Clef clef; vector<Measure> measures; }; // key.fifths: 0=C,1=G,-1=F,2=两升号
struct Score   { int divisions; vector<Part> parts; };     // MVP: parts.size()==1

// 简谱文档（首调）
struct JianpuNote { int degree;      // 1-7 调内音级
                    int accidental;  // -1降 0自然 +1升
                    int octaveShift; // 八度点：相对主音中央八度
                    Duration dur; };
struct JianpuDoc  { Key key; vector<JianpuNote> notes; };
```

### 2.3 关键接口（API 契约）

- `Recognizer::recognize(const Image& page) -> MusicXML` ：输入归一化页面，返回 MusicXML 字符串/文件。MVP 内部 `system("audiveris -batch ...")`；进阶内部 `OmrModel::infer(page)`。
- `MusicXMLRepo::parse(const string& xml) -> Score` / `serialize(const Score&) -> string` ：MusicXML 与 Score 双向。
- `Converter::staffToJianpu(const Score&) -> JianpuDoc` ：**核心**。主音 = `(key.fifths × 7) mod 12`；每个音相对主音求自然音级→数字 1–7；色彩差→升/降记号；八度点以主音中央八度为基准；时值由 `duration/divisions` 反推 `type`+附点。
- `Converter::jianpuToStaff(const JianpuDoc&, Key) -> Score` ：数字→相对主音度数；用调号定主音绝对音高，换算 `step+alter+octave` 写入 `pitch`；下划线/增时线映射 `type`+dot。
- `Presenter::renderJianpu(const JianpuDoc&) -> string` / `Presenter::exportMusicXML(const Score&) -> file`。

### 2.4 数据流向

```
正向(五线→简谱):
  PDF/JPG →[①]→ 页面图像 →[②]→ MusicXML →[③]→ Score
           →[④]→ JianpuDoc →[⑤]→ 首调简谱文本 + MusicXML

反向(简谱→五线):
  简谱文本 →[④]→ JianpuDoc(+调号) →[④]→ Score →[③]→ MusicXML →[⑤]→ 五线谱(可经MuseScore渲染)
```

### 2.5 技术栈边界（C++ vs Python）

- **C++ 核心（你的代码，Windows/VS + CMake/vcpkg）**：MusicXML I/O（**pugixml**，原定 libmusicxml2 不在 vcpkg）、④转换逻辑、⑤GUI（Qt/ImGui）。保持纯 C++ 体验，形成产权。
- **Python 辅助（学习/AI）**：PyTorch 训练、music21 做 MusicXML 解析测试对照、调用 oemer/Audiveris。
- **DL 推理在 C++**：Python 训练 → `torch.onnx.export` → C++ 用 **ONNX Runtime**（轻量、跨平台、最友好，推荐）或 **LibTorch** 部署。
- **PDF 处理**：矢量 PDF 用 MuPDF `get_drawings()`/Poppler 提取；扫描件用 OpenCV 二值化+去噪。**MVP 建议先用矢量/印刷 PDF 或 Audiveris 输出，规避扫描件噪声难题。**

> 关于"第一版直接输出 MusicXML"：MusicXML 是五线谱导向的中间格式，简谱需经"首调→固定调映射"表达。建议 v1 既输出**首调简谱文本/HTML**（用户真正要的结果），也保留 MusicXML 作为 canonical 中间产物；若严格只输出 MusicXML，简谱只能以 `lyric` 或自定义指令承载，可读性差——不推荐。

---

## 3. 学习路线规划

> 总估时约 **16–23 周（4–6 个月，课余并行）**。难度 ★~★★★★★。每阶段"产出目标"即该阶段的可运行/可展示物。

### 阶段 0：环境与 CV/音乐表示基础（1–2 周 · ★★）  `状态：环境地基完成，MusicXML 解析进行中，OpenCV 基础延后`

> **进度（2026-07-13）**：S1 环境 / S2 工具链（pugixml 端到端）/ S3 Git 入库 均已完成；OpenCV 基础（S4–S5）按架构决策降级为选做、延后（见 §4）；MusicXML 规范与解析（S6–S7，库改 pugixml）**已完成**（阶段 2/3 转换层已在其上构建）。

- **技术点**：Visual Studio + CMake + vcpkg；Git；OpenCV 基础（imread/threshold/contours/Hough，**选做/延后**）；通读 MusicXML 规范。
- **资源**：[MusicXML Tutorial PDF](https://wpmedia.musicxml.com/wp-content/uploads/2017/12/musicxml-tutorial.pdf)｜[OpenCV 文档](https://docs.opencv.org/)
- **产出**：环境就绪；C++ 小程序：用 **pugixml** 读一个示例 MusicXML 并打印音符序列（OpenCV 谱线检测小程序为选做，待网络稳定后用 opencv.org 预编译包实现）。

### 阶段 1：OMR 黑盒集成 + MusicXML 吃透（2–3 周 · ★★）  `状态：✅ 完成（M2：oemer 黑盒接入 + 评测 harness + Plan A 调号后处理 + H2 分维指标 + 权重完整性校验；真 oemer 本机 GPU 端到端跑通）`

> **进度（MVP 已达成）**：✅ 完成。oemer 黑盒接入 + 评测 harness（Plan A 调号后处理 + H2 分维指标）+ 6 处补丁固化 + 权重完整性校验均已落地，真 oemer 本机 GPU 端到端跑通。

- **技术点**：子进程调用 Audiveris/oemer 出 MusicXML；用 music21(Python) 探索解析已知谱（打印 pitch/key/measure），建立 Score 内存模型。
- **资源**：[Audiveris GitHub](https://github.com/jostle/audiveris)｜[oemer](https://github.com/BreezeWhite/oemer)｜[music21 文档](https://web.mit.edu/music21/doc/index.html)
- **产出**：流水线——给定 PDF → 解析为内存 `Score` → 控制台打印音高序列。

### 阶段 2：五线谱→简谱核心（3–4 周 · ★★★）← MVP 第一可运行版  `状态：✅ 完成（2026-07-15，含变调重算）`

> **进度（2026-07-15）**：✅ 完成。`staffToJianpu`（主音计算 / pitch→音级 / 临时记号 / 八度点 / 时值→音符类型+附点）+ 变调重算模块全部实现；music21 ground-truth 校验 8/8 样本 100% 通过（音符 + 字段），C++ 单测 80/80（含变调 16）；`phase-2` 标签落在 feat 分支。

- **技术点**：实现 `staffToJianpu`：主音计算、pitch→音级、临时记号映射、八度点、时值→音符类型+附点；覆盖 ≤2 升降号、单声部、无装饰音/歌词。
- **资源**：[Jianpu 首调映射参考(Flutter notemus)](https://zread.ai/alessonqueirozdev-hub/flutter_notemus/16-jianpu-numbered-notation)｜music21 做 ground-truth 对照
- **产出**：**MVP v1**——输入 MVP 约束 PDF，输出首调简谱文本 + MusicXML。

### 阶段 3：简谱→五线谱（2–3 周 · ★★★）  `状态：✅ 完成（2026-07-16，比 plan 提前约一周；含原"可选 P2"的 G4）`

> **进度（2026-07-16）**：✅ 完成。G1 `jianpuToStaff`（JianpuDoc→Score）/ G2 `scoreToMusicXML`（Score→MusicXML，pugixml）/ G3 往返音高守恒（五线→简→五线 音高守恒）/ G4 简谱文本输入解析器（`parseJianpuText` 严格逆 `renderJianpuNote`，文本→JianpuDoc）全部实现；MSVC 实测 **150 个用例全绿**（header-only 自研框架，1 个 ctest 入口），`phase-3` 标签含 G1–G3、G4 纳入 `phase-3.1`。

- **技术点**：实现 `jianpuToStaff`：解析数字简谱→相对度数→按调号换算绝对音高→生成 MusicXML `pitch`；增时线/下划线→`type`+dot。
- **产出**：双向转换闭环；自测往返一致性（五线→简→五线 音高守恒）。

### 阶段 4：AI / 深度学习进阶（4–8 周 · ★★★★）← 转 AI 主战场  `状态：未开始`

> **进度（2026-07-13）**：未开始。前置：阶段 1–3 完成、测试谱集就绪、对 MusicXML 与 CV 原理有基础。

- **技术点**：PyTorch 入门；用 DeepScores/DoReMi **合成数据微调小模型做单声部音符检测**（或适配 LEGATO/Clarity-OMR 预训练权重）；ONNX Runtime 在 C++ 部署；写**评测脚本**（MVP 测试集上 precision/recall）。
- **资源**：[动手学深度学习 d2l.ai](https://d2l.ai/)｜[小土堆 PyTorch B站](https://www.bilibili.com/)｜[CS231n](http://cs231n.github.io/)｜[DeepScoresV2](https://zenodo.org/record/4012193)｜[LEGATO arXiv:2506.19065](https://arxiv.org/abs/2506.19065)｜[Clarity-OMR](https://github.com/)
- **产出**：自训 OMR 组件 + 评测报告；用自训模型替换 Audiveris 作识别引擎，对比准确率。**可写进简历的高价值产出。**

### 阶段 5：工程化与作品集（2–3 周 · ★★★）  `状态：未开始`

> **进度（2026-07-13）**：未开始。前置：MVP 双向转换闭环（阶段 2–3）可用。

- **技术点**：Qt/ImGui Windows GUI；PDF 输入、简谱渲染、纠错编辑器；文档与打包。
- **产出**：可演示 Windows 应用 + GitHub 仓库 + 技术报告——服务考研 AI 方向作品集。

---

## 4. 风险与下一步

- **扫描件噪声**是 OMR 最大误差源，MVP 先用矢量/印刷 PDF，扫描件留到阶段 4 用 DL 改善。
- **简谱无标准 MusicXML 表达**，务必自定清晰的内部 `JianpuDoc` 模型，不要硬塞 `lyric`。
- **下一步建议（2026-07-13）**：环境地基已完成。当前聚焦**吃透 MusicXML（用 pugixml 解析）+ 建立 Score 内存模型**（阶段 0 收尾，对应原 S6–S7），并下载 5–10 份 MVP 约束内公开印刷谱（OpenScore/IMSLP：单声部、≤2 升降号、无装饰音）作测试集；完成后即进入阶段 1，接 Audiveris/oemer 黑盒跑通"PDF→MusicXML→Score→控制台音高"。OpenCV 谱线检测（原 S4–S5 产出①）降级为选做，待网络稳定后用 opencv.org 预编译包实现，不阻塞主线。

---

## 参考来源（节选）

- [Audiveris GitHub（活跃维护，输出 MusicXML 4.0）](https://github.com/jostle/audiveris)
- [oemer 端到端 OMR](https://github.com/BreezeWhite/oemer) ｜ [homr（oemer 改进版）](https://github.com/cairn-labs/homr)
- [Sheet Music Transformer++ (IJCV 2025)](https://arxiv.org/abs/2405.12105)
- [Zeus/OLiMPiC 端到端 OMR (ICDAR 2024)](https://arxiv.org/abs/2403.13763)
- [LEGATO 大规模预训练 OMR (NeurIPS 2025)](https://arxiv.org/abs/2506.19065)
- [Sheet Music Benchmark + OMR-NED (ISMIR 2025)](https://arxiv.org/abs/2506.10488)
- [MusicXML 官方文档与 Tutorial](https://www.musicxml.com/?p=769) ｜ [MusicXML 4.0 note/pitch 参考(W3C)](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/note)
- [pugixml (C++ XML 库, MIT，本项目用于读写 MusicXML)](https://github.com/zeux/pugixml)｜[libmusicxml2 (原候选，vcpkg 无端口，作参考)](https://github.com/grame-cncm/libmusicxml)
- [music21 (Python 音乐分析库)](https://web.mit.edu/music21/doc/index.html)
- [DeepScoresV2 数据集](https://zenodo.org/record/4012193) ｜ [MUSCIMA++](https://github.com/OMR-Research/muscima-pp)
- [动手学深度学习 d2l.ai](https://d2l.ai/) ｜ [CS231n](http://cs231n.github.io/)
- [OMR 技术综述(2026)](https://blog.csdn.net/Harrytutu_ZuiYue/article/details/157996413) ｜ [Clarity-OMR vs Audiveris 实测](https://aibytes.blog/comparisons/clarity-omr-vs-audiveris-5-omr-accuracy-tests)
