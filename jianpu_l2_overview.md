# 谱渡 Pudu · 阶段 2 L2 HTML/Unicode 二维渲染器

> 状态：已实现并验证（2026-07-15）。遵循 `omr-tool-research/jianpu_output_spec.md` §3.2。
> 流程维持：**MusicXML 进 → 简谱出**，MusicXML 仅作中间格式。

## 交付内容

| 文件 | 作用 |
|---|---|
| `include/jianpu_converter.hpp` | 新增 `jianpuToL2(const JianpuDoc&)` 声明 |
| `src/jianpu_converter.cpp` | L2 渲染实现（匿名命名空间辅助 + `jianpuToL2`），严格按规范 §3.2 |
| `src/main.cpp` | 新增 `--to-jianpu-l2 [out.html]` 开关，写出自包含 HTML |
| `test/test_staff_to_jianpu.cpp` | 新增 4 个 L2 单元测试 |
| `jianpu_l2_sample.html` | 预览：内嵌「小星星」C 大调 MVP 样例 |
| `jianpu_l2_cello.html` | 预览：大提琴组曲 No.1（G 大调，展示低八度点/和弦/增时线） |

## 核心要素（均已实现）

- **数字 `span.jp-num`**：首调音级，临时记号用 Unicode ♯♭♮。
- **高低八度点**：`jp-up`/`jp-down`，`·` 逐点纵向堆叠于数字上/下（绝对定位）。
- **减时线横向连写**：小节层把**连续同值**（underlines 相同）音符连成 `beam` 组，
  减时线渲染为一条/多条**贯穿横线**（`repeating-linear-gradient`，每 5px 一线）；
  不成组的孤立短音符各自画减时线。
- **增时线 `—`**：`jp-aug`，置于数字右侧，数量 = `augmentDashes`（二分=1、全=3）。
- **附点 `·`**：置于数字右侧，数量 = `dots`。
- **和弦**：纵向 flex 列（主音 + 其余音级）。
- **连音弧**：内联 SVG 弧线，位于数字上方（`tieToNext` 触发）。
- **自包含 HTML**：含最小内联 CSS（浅色主题卡片），可直接浏览器打开。

## 用法

```bash
build\Pudu.exe data\cello-suite-no-1.musicxml --to-jianpu-l2 jianpu_l2_cello.html
build\Pudu.exe --to-jianpu-l2        # 默认输出 jianpu_l2.html（内嵌小星星样例）
```

## 验证

- 构建：MSVC 2022 / Ninja / vcpkg(pugixml)，**0 错误 0 警告**。
- 测试：`PuduTests` **46/46 全绿**（含 4 个新增 L2 用例）。
- 产物核验：cello 谱含 **283 个 beam 连写组**、**2 个和弦**、**26 处增时线**、
  大量低八度点（G 大调低音区）；sample 谱为纯净 MVP 样例（附点/八度点符合预期）。

## 已知限制（非阻断，与 L1 一致）

1. **tuplet 恒为 0**：`Score` 未解析 `<time-modification>`，连音组暂按近似时值。
2. **和弦逐音八度点未实现**：仅主音八度点 + 成员音级（规范 §2.5 的逐音独立八度点后置）。
3. **连音弧为单音上方 SVG 弧近似**：未跨两音精确连线。
4. **减时线连写按"连续同值"启发式近似**：非按真实 beat 分组（如 4/4 中跨拍的八分未拆分）。
5. **小调「6=X」标法未实现**：仍走相对大调法（1=关系大调主音）。

## 建议下一步

1. 接 `verify_corpus.py`，用 music21 `scaleDegree` 逐音校验 `degree/octaveDots`。
2. L2 美化：按真实 beat 分组连线、连音弧跨音、和弦逐音八度点。
3. OMR 前端（PDF/JPG 输入）与阶段 3 反向转换（简谱 → 五线谱）。
