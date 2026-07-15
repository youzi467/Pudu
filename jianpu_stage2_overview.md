# 谱渡 Pudu · 阶段 2 简谱转换实现（staffToJianpu 首版）

> 依据 `omr-tool-research/jianpu_output_spec.md`（2026-07-15 定稿）实现。
> 状态：**首版完成并已编译 + 实跑验证**。

## 交付物

| 文件 | 作用 |
|---|---|
| `include/jianpu_model.hpp` | L0 简谱数据模型（严格按规范 §1：JianpuNote / Measure / Line / Doc + Accidental 枚举） |
| `include/jianpu_converter.hpp` | 转换器 API：核心纯函数 + `staffToJianpu` + `jianpuToL1` 声明 |
| `src/jianpu_converter.cpp` | 转换实现（音高映射 / 调号 / 时值 / 多声部组织 + L1 预览渲染） |
| `CMakeLists.txt` | 挂接 `src/jianpu_converter.cpp` |
| `src/main.cpp` | 新增 `--to-jianpu` 开关，直接打印简谱预览 |

## 关键实现逻辑

- **音高映射 `midiToJianpu`**：`tonicPc = (fifths*7) % 12`；`semi` 命中大调模板
  `{0:1,2:2,4:3,5:4,7:5,9:6,11:7}` → 纯音级；调外音按源 `alter` 择优：
  `alter<0` 取 `(semi+1)` 音级 + Flat，否则取 `(semi-1)` 音级 + Sharp。
- **八度点**：以参考八度主音（`tonicPc + 60`，即第 4 组）为 0 点，用
  `std::floor((M-ref)/12)` 实现（避免整数除法对负数截断出错，规范 §2.2）。
- **时值 `typeToDuration`**：whole→增时3 / half→增时1 / quarter→0 /
  eighth→减1 / 16th→减2 / 32nd→减3 / 64th→减4；未知类型默认四分。
- **调号抬头 `fifthsToTonicName`**：小调走首调相对法（1 = 关系大调主音）。
- **多声部**：按出现的 `voice` 集合分行（每行一个 JianpuLine），同小节音符按
  `onset` 升序对齐。转换对 `Score` 只读、不回改。

## 验证结果（已编译 + 实跑）

- 构建：MSVC 2022 BuildTools + Ninja + vcpkg(pugixml)，0 错误 0 警告。
- 小星星（C 大调，内嵌样例）：`1=C 4/4`，`1 1 5 5 | 6 6 5 - ||` ✓
- 大提琴组曲 No.1（G 大调）：`1=G`，开头 `1,,__ 5,,__ 3,__ 2,__ …`（G2→`1,,`）✓
- 维瓦尔第 a 小调：按相对大调法显示 `1=C` ✓；和弦 `[1 3 1]`、装饰音 `g5`、延音 `~` 均正常渲染。

## 已知边界（规范已记录，非阻断）

1. **调外音 #/b 择向为启发式**：C 自然音（alter=0）在 D 大调会落为 `#6` 而非
   `b7`（等音异名边界，可行性分析已标记后置）。
2. **连音组 `tuplet` 未解析**：`Score` 模型无 `<time-modification>` 字段，暂置 0。
3. **和弦 `chordDegrees` 仅存音级**：逐音八度点（规范 §2.5 要求各自独立）为后续扩展点。
4. **小调 "6=X" 标法开关**后置。

## 下一步建议

- 按规范 §5 写 9 项边界单测（覆盖纯函数级，尤其调外音双向、各调号）。
- 扩展 `verify_corpus.py`，用 music21 `scaleDegree` 逐音比对 `degree/octaveDots`。
- L2 HTML/Unicode 二维渲染（真实八度点 / 减时线 / 连音弧）。
