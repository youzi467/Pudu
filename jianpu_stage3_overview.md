# 谱渡 Pudu · 阶段 3 简谱 → 五线谱 实施概览

> 依据 `stage3_action_plan.md`。状态（2026-07-15）：G1 + G2 + G3 核心已实现并通过单测。

## 已实现

### G1 `jianpuToStaff(const JianpuDoc&, int divisions=4) -> Score`
- 音级 → 绝对音高：逆 `midiToJianpu`，复用 `transpose::midiToPitch` 保证升/降号拼写口径与变调重算一致（`fifths>=0` 用 ♯，否则用 ♭）。
- 八度点 → octave：与 `midiToJianpu` 的 `octaveDots` 严格互逆（`M = tonicPc+60 + 12*octaveDots + (scaleSemi+accidentalDelta)`）。
- 时值 → `type`+`duration`：`underlines/augmentDashes/dots` 逆查节律表，与 `typeToDuration` 对称；`duration = round(quarterLength × divisions)`。
- 全局属性 → `ScoreAttributes`；多声部按 `line.partIndex`/`voice` 还原到同一 Part 的不同 voice（序列化时用 `<backup>/<forward>` 对齐）。
- 休止 / 和弦 / 装饰音 / 延音线：映射回 `Note.isRest` / `chordPitches` / `isGrace` / `tieStart`。

### G2 `scoreToMusicXML(const Score&) -> std::string`
- pugixml 写出完整 `score-partwise`（含 `<?xml?>` + `movement-title` + `part-list` + `part/measure`）。
- `<attributes>`：divisions / key(fifths+mode) / time / clef（每个 Part 首小节）。
- 多声部用 `<backup>/<forward>` 还原并行时序；和弦后续音用 `<chord/>`。
- 自洽测试 `test_serializer.cpp`：写出 → `MusicXMLParser::parseString` 读回 → 音高序列等价。

### G3 Round-trip 音高守恒
- `test_jianpu_to_staff.cpp::jianpu_to_staff_roundtrip_pitch_conservation`：单声部旋律 `staffToJianpu → jianpuToStaff`，还原音高序列（step/alter/octave）与原谱 100% 一致。
- 本地 g++ 9/9 通过；G2 序列化自洽 1 项随 MSVC 构建运行。

## 已知限制（与阶段 2 边界项对齐）
- **和弦逐音八度点**：阶段 2 仅存音级(1-7)，反向按「根音上方最近八度」还原，音级（pitch class）守恒，精确成员八度不保。
- **`tieStop` 不还原**：阶段 2 仅存 `tieStart`（= `tieToNext`），反向只写 `<tie type="start">`，连音线终点记号丢失（不影响音高）。
- **`divisions` 选择**：反向默认 `divisions=4`；与原谱不同仅影响 duration 整数粒度，音高守恒不受影响。

## 待办（按计划 P2/P3）
- **G4 简谱文本输入解析器**（`--from-jianpu-text` / `.jianpu.json` → `JianpuDoc`）：让"用户直接写简谱"可用，非闭环必需。
- CLI 与数据/标题：反向输出目前写 `movement-title`，元信息（author/copyright）未回写（MVP 跳过）。
- 提交并打 `phase-3` 标签；刷新 `research_report.md` 阶段 3 状态（交给用户在其交互终端 `git push` 后执行）。

## 与前期成果的衔接
- 复用 `fifthsToTonicPc` / `midiToJianpu` / `typeToDuration`（阶段 2）与 `midiToPitch` / `parseKeyName`（变调重算），零新增音级算法。
- 对 `staffToJianpu` / L1/L2/L3 渲染器**零侵入**（纯新增函数 + 新文件）。
- 变调重算已确保「L0 的 fifths/tonicLabel 与实际 pitch 自洽」→ 本阶段 G3 前置已具备。
