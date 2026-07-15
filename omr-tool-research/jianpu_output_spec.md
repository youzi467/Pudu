# 谱渡 Pudu · 阶段 2 简谱输出规范（JianpuDoc）

> 状态：设计定稿（2026-07-15），阶段 2 `staffToJianpu` 实现依据。
> 关系：消费 `include/score_model.hpp` 的 `Score`（含 onset/voice/chordPitches/isGrace/tie）。

---

## 0. 设计原则

1. **一份数据、三种呈现**：内部权威模型 `JianpuDoc`（L0）+ 纯文本渲染（L1）+ HTML/Unicode 渲染（L2），并保留原 MusicXML/`Score` 作 canonical 中间产物（L3）。
2. **L0 存语义字段，不存字符**：简谱是二维记号（数字居中、八度点上下、减时线在下、增时线在右），纯文本无法真实堆叠。L0 只存"音级/八度/时值/记号"等语义，渲染器各自投影，阶段 3 反向转换直接消费 L0，互不绑死。
3. **首调（movable-do）**：1 = 主音，按调号定位；调外音用临时升降记号表示，不移调。
4. **与现有模型对齐**：`JianpuNote` 字段与 `Note.onset/voice/chordPitches/isGrace/tieStart/tieStop` 一一对应，转换不回改 `Score`。

---

## 1. 数据结构（L0）

```cpp
namespace pudu {

enum class Accidental { None, Sharp, Flat, Natural, DoubleSharp, DoubleFlat };

struct JianpuNote {
    int degree = 0;             // 0=休止, 1-7=首调音级(do..si)
    int octaveDots = 0;         // +n=上方点(升八度), -n=下方点(降八度), 0=中音区
    Accidental accidental = Accidental::None;  // 临时记号(数字左侧)

    int underlines = 0;         // 减时线: 0=四分,1=八分,2=十六分,3=三十二分...
    int augmentDashes = 0;      // 增时线: 数字右"-"数(二分=1, 全音符=3)
    int dots = 0;               // 附点数(×1.5 / ×1.75)

    bool tieToNext = false;     // 连音线连向下一音
    bool isGrace = false;       // 装饰音(小音符, 不占基本时值)
    int tuplet = 0;             // 连音组: 0=常规,3=三连音,5=五连音...
    std::vector<int> chordDegrees;  // 和弦其余音级(主音在 degree)
};

struct JianpuMeasure {
    int number = 0;
    std::vector<JianpuNote> notes;  // 按 onset 升序
};

struct JianpuLine {
    int voice = 1;
    std::vector<JianpuMeasure> measures;
};

struct JianpuDoc {
    std::string title;
    std::string tonicLabel;     // "1=D"
    std::string mode = "major"; // major/minor
    int beats = 4;
    int beatType = 4;
    std::vector<JianpuLine> lines;  // 多声部→多行
};

} // namespace pudu
```

---

## 2. 五大要素编码

### 2.1 音级：绝对音高 → 首调数字
- 调号 `fifths → tonicPc`（主音音级 0-11）：
  `C=0 G=7 D=2 A=9 E=4 B=11 F#=6 Bb=10 Eb=3 Ab=8 ...`
  （即 `tonicPc = (fifths * 7) mod 12`，取正模。）
- 对音 M（MIDI）：`semi = (M - tonicPc + 120) % 12`。
- 大调模板 `MAJOR = {0:1, 2:2, 4:3, 5:4, 7:5, 9:6, 11:7}`：
  - `semi` 命中 → 纯音级，`accidental=None`。
  - 未命中（调外音）→ 取 `semi-1` 的音级 + `Sharp`；若源 `alter<0` 则取 `semi+1` 的音级 + `Flat`（按谱面记号择优）。
- 休止：`degree=0`。

### 2.2 八度点
- `octaveDots = floor((M - tonicRefMidi) / 12)`
  `tonicRefMidi` = 主音在参考八度（默认第 4 组，即 `tonicPc + 12*(4+1)`）的 MIDI。
- >0 上方点，<0 下方点，绝对值=点数。可按声部音域整体平移参考八度，减少极端点数（配置项）。

### 2.3 时值（type → 减时/增时/附点）
| type | augmentDashes | underlines |
|---|---|---|
| whole | 3 | 0 |
| half | 1 | 0 |
| quarter | 0 | 0 |
| eighth | 0 | 1 |
| 16th | 0 | 2 |
| 32nd | 0 | 3 |
| 64th | 0 | 4 |
- `dots` 直接取 `Note.dots`。
- 校验：`duration ≈ (4/2^underlines) * divisions * (1+dashes) * dotFactor`，与 `Note.duration` 交叉核对（容差处理连音）。

### 2.4 调号抬头
- `fifths → 字母名`：0=C,1=G,2=D,3=A,4=E,5=B,6=F#,-1=F,-2=Bb,-3=Eb,-4=Ab,-5=Db,-6=Gb。
- 输出 `tonicLabel = "1=" + 字母`。小调默认首调相对法（1 落关系大调主音）；可选 `6=X` 标法开关。

### 2.5 休止/和弦/延音/装饰音/连音组
- 休止 `0`，时值编码同 2.3（`0 - - -` = 全休止）。
- 和弦：主音 `degree` + 其余 `chordDegrees`（来自 `Note.chordPitches` 各自换算音级/八度）。
- 延音：`tieToNext = Note.tieStart`（并结合下一音 `tieStop`）。
- 装饰音：`isGrace = Note.isGrace`。
- 连音组：`tuplet`（阶段 2 可先按近似时值处理，后续读 `<time-modification>` 精化）。

---

## 3. 渲染格式

### 3.1 L1 纯文本（ASCII-first）
| 语义 | 约定 | 示例 |
|---|---|---|
| 升/降八度 | 尾缀 `'`(上)/`,`(下) | `5'` `1,,` |
| 减时线 | 尾缀 `_` | `3_` `3__` |
| 增时线 | 空格 `-` | `1 - - -` |
| 附点 | 尾缀 `.` | `1.` |
| 临时记号 | 前缀 `#`/`b`/`n` | `#4` `b7` |
| 小节线/终止 | ` \| ` / ` \|\|` | `1 2 3 5 \|` |
| 和弦/装饰音/连音组 | `[135]` / `g1` / `(3:...)` | |

抬头：`标题` 换行 `1=D 4/4` 换行，多声部各占一 `voiceN:` 行。

### 3.2 L2 HTML/Unicode（真实二维）
- 数字 `<span class="jp-num">`；八度点绝对定位 `·` 于上/下；减时线用嵌套 `border-bottom`（每线一层）；增时线 `—`；附点 `·`；和弦纵向 flex 列；连音弧用内联 SVG。
- 输出自带最小 CSS 的独立 `.html`，可直接浏览器查看。

---

## 4. 转换主流程（伪代码）

```
staffToJianpu(Score) -> JianpuDoc:
  doc.title = Score.title; doc.tonic/mode/beats/beatType = 首声部 attributes
  tonicPc = fifthsToTonicPc(fifths)
  for part in Score.parts:
    for voice in 该 part 出现的 voice 集合:
      line{voice}
      for measure in part.measures:
        jm{number}
        for note in measure.notes (仅该 voice, 已按 onset 升序):
          if note.isRest: jn.degree=0
          else: (jn.degree, jn.accidental, jn.octaveDots) = midiToJianpu(note.pitch, tonicPc)
          (jn.underlines, jn.augmentDashes) = typeToDuration(note.type)
          jn.dots=note.dots; jn.isGrace=note.isGrace; jn.tieToNext=note.tieStart
          for cp in note.chordPitches: jn.chordDegrees.push(midiToDegree(cp))
          jm.notes.push(jn)
        line.measures.push(jm)
      doc.lines.push(line)
  return doc
```

---

## 5. 边界用例清单（阶段 2 单测覆盖）
1. 中音区/升八度/降八度（0/+1/-1 点）——各调主音落点正确。
2. 调外音：D 大调中的 `#4`(G#)、`b7`(C)——记号方向正确。
3. 时值：全/二分/四分/八分/十六分/附点四分/附点八分。
4. 全休止 `0 - - -` 与半拍休止。
5. 和弦：三和弦主音+2 成员，八度点各自独立。
6. 多声部：backup 后 voice2 与 voice1 onset 对齐，各成一行。
7. 装饰音：不占基本拍，标记正确。
8. 跨小节延音线。
9. 各调号：C/G/D/A/E/F/Bb/Eb（覆盖现有 8 份语料）。

## 6. 校验方法
- **music21 做 ground-truth**：对同一 `.musicxml`，用 music21 计算每音的 `scaleDegree`（相对主音）与八度，与 Pudu 的 `degree/octaveDots` 逐音对比，输出差异清单。
- 复用 `verify_corpus.py` 框架扩展"简谱层"核对项。
- round-trip（阶段 3）：`staffToJianpu` → `jianpuToStaff` → 音高序列与原 `Score` 一致。
