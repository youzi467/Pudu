# 谱渡 Pudu · MVP 所需 MusicXML 标签清单

> 用途：作为 `score_model.hpp` / `musicxml_parser` 的标签取舍依据，以及后续扩展时的维护清单。
> 范围：本项目 MVP（单声部、印刷谱、≤2 升降号、无装饰音/无歌词、输出首调简谱、采用 `score-partwise`）。
> 来源：官方 [MusicXML Tutorial](https://wpmedia.musicxml.com/wp-content/uploads/2017/12/musicxml-tutorial.pdf)（已通读，48 页）。
> 维护说明：每个标签一行一条，新增/裁剪标签请同步更新 `score_model.hpp` 字段与解析器逻辑，并在本文件留痕。

---

## 0. 选取标准（一个标签能进 MVP，当且仅当「首调简谱」输出离不开它）

首调简谱需要四类信息，凡不服务这四件事的标签一律不碰：

1. **主音是谁**（定 do）→ 来自调号
2. **每个音的音高**（算简谱数字 + 八度点 + 临时升降）→ 来自 pitch
3. **每个音的时值**（算下划线/增时线/附点）→ 来自 duration/type/dot
4. **小节怎么分**（画小节线、拍号分组）→ 来自 measure/time

---

## 1. MVP 标签树（骨架）

```
score-partwise                根元素（本项目固定用 score-partwise，不用 score-timewise）
├── movement-title            乐曲标题（可选，仅展示用）
├── part-list
│   └── score-part           声部登记（id + part-name）
│       └── part-name        声部名（简谱用不到，但要能跳过）
└── part  (id 对应 score-part)
    └── measure  (number=小节号)
        ├── attributes       全局属性（通常仅首小节出现一次）
        │   ├── divisions    时值标尺：1 个四分音符 = divisions 个 duration 单位
        │   ├── key
        │   │   ├── fifths   调号（五度圈步数）→ 决定主音(do)
        │   │   └── mode     大调/小调（major/minor）
        │   ├── time
        │   │   ├── beats    拍号分子
        │   │   └── beat-type 拍号分母
        │   └── clef
        │       ├── sign     谱号（G/F/C）
        │       └── line     谱号线
        └── note             音符 / 休止（MVP 核心，可重复）
            ├── pitch
            │   ├── step     音名字母 A–G
            │   ├── alter    变音：1=升 / -1=降 / 缺省=还原
            │   └── octave   八度组号（中央 C = 4）
            ├── rest         存在即表示休止符（无 pitch）
            ├── duration     时值整数（单位由 divisions 定义）
            ├── type         whole/half/quarter/eighth/16th…
            ├── dot         附点（可重复，单附点出现一次）
            ├── tie         延音线（type=start|stop）
            └── accidental  临时记号显示符号（MVP 以 alter 为准，可忽略）
```

---

## 2. 标签逐条说明

### 2.1 容器 / 骨架（无音乐内容，但解析必须穿过）

| 标签 | 作用 | MVP 必要性 |
|---|---|---|
| `score-partwise` | 根元素，按「声部→小节」组织 | **必须**；解析器只认此根，遇到 `score-timewise` 直接报错 |
| `part-list` / `score-part` | 声部登记表（id + 名字） | **必须**（结构强制）；单声部下只有一个 `score-part` |
| `part-name` | 声部名 | 需能**跳过**；简谱不依赖，但要从 `part-list` 按 id 取出来填 `Part.name` |
| `part` | 装音乐数据的容器（id 对应 `score-part`） | **必须**；对应 `Score::parts` 中的一个 `Part` |
| `measure` | 小节，`number` 属性标小节号 | **必须**；遍历基本单位，也是 `attributes` 的位置 |

### 2.2 `<attributes>` 全局属性（决定「简谱怎么算」的全局规则）

| 标签 | 作用 | 与简谱关联 |
|---|---|---|
| `divisions` | 时值标尺 | **时值分母**：`duration / divisions` = 几个四分音符 |
| `key › fifths` | 调号（五度圈步数：0=C,1=G,-1=F,2=D,-2=B♭…） | **首调简谱命根子**，直接决定主音(do)。MVP 约束 ≤2 升降号 ⇒ `fifths ∈ [-2,+2]` |
| `key › mode` | 大调/小调 | 影响主音定位；MVP 可先只做 major，但须读到此字段以便判断/告警 |
| `time › beats` / `beat-type` | 拍号（如 4/4） | 决定每小节拍数与「一拍=几分音符」，用于拍/小节校验与下划线分组 |
| `clef › sign` / `line` | 谱号（如 G2 高音谱号） | 识别端用它换算音高；**消费端 pitch 已是绝对音高**，MVP 仅用于「读入不报错 + 将来回写」 |

### 2.3 `<note>` 音符 / 休止（MVP 绝对核心，90% 解析代码在此）

| 标签 | 作用 | 与简谱关联 |
|---|---|---|
| `pitch › step` | 音名字母 A–G | 与 `key` 一起换算成**首调音级**（简谱 1234567） |
| `pitch › alter` | 变音：1=升 / -1=降 / 0或缺失=还原 | 超出调号既定音 ⇒ **临时记号** ⇒ 简谱数字前加 ♯/♭ |
| `pitch › octave` | 八度组号（中央 C=4） | 决定简谱数字上/下的**高低八度点** |
| `rest` | 休止符标记（此时无 `pitch`） | 简谱的 `0`；解析用「有无 `rest` 子元素」区分音符/休止 |
| `duration` | 时值整数（单位=divisions） | **时值原始数据**，配合 `divisions` 得到真实时值 |
| `type` | 时值图形名（whole/half/quarter/eighth/16th） | 直观的时值来源；MVP 可优先用 `type`，以 `duration/divisions` 交叉校验 |
| `dot` | 附点（可重复） | 简谱附点「·」，时值 ×1.5 |
| `tie` | 延音线（`type=start/stop`），跨小节/相邻同高音连成一个时值 | 简谱用增时线/连音表达；注意区分 `<tie>`（发声时值）与 notations 里的 `<tied>`（视觉记号），MVP 用 `<tie>` |
| `accidental` | 临时记号**显示**符号（sharp/flat/natural） | 与 `alter` 语义重叠；**MVP 以 `alter` 为准**，`accidental` 仅作校验 |

---

## 3. MVP 明确**跳过**的标签（解析时安全地 `continue`）

| 跳过标签 | 原因 |
|---|---|
| `chord` / `backup` / `voice` | 多声部/和弦机制；MVP 单声部单音，遇 `chord` 告警并跳过 |
| `lyric` / `syllabic` / `text` | MVP「无歌词」 |
| `notations` / `ornaments` / `technical` / `articulations` | 装饰音、演奏法、指法——MVP「无装饰音」 |
| `direction` / `harmony` / `frame` | 力度/表情文字、和弦标记、吉他和弦框——非本项目范畴 |
| `stem` / `beam` | 纯视觉（符干、符尾连接）；时值已由 `type`/`duration` 决定 |
| `unpitched` / `staff-tuning` / `midi-*` | 打击乐/多谱表/MIDI 播放——用不到 |

---

## 4. 最小可运行示例（C 大调，4/4，可写断言）

```xml
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>              <!-- 1 个 duration = 1 个四分音符 -->
        <key><fifths>0</fifths><mode>major</mode></key>   <!-- C 大调 → do=C -->
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>   <!-- 无 alter=还原 -->
        <duration>1</duration>
        <type>quarter</type>
      </note>
      <note>
        <rest/>
        <duration>1</duration>
        <type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>
```

解析预期：主音 do=C（`fifths=0`）；第 1 音 = 简谱 `1`（C 相对 C 是第 1 级）、中八度、四分音符；第 2 音 = 休止 `0`。**可作 T4 固定样例断言**。

---

## 5. 扩展维护指引（后续阶段）

- **阶段 2（五线谱→简谱）**：在 `fifths` 基础上实现「绝对音高 → 首调音级」换算；临时记号由 `alter` 与调号比较得出；八度点由 `octave` 决定；时值由 `duration/divisions` + `type` + `dot` 决定。
- **阶段 3（简谱→五线谱）**：反向——解析数字简谱后，按 `fifths` 把首调音级还原为 `step/alter/octave`，生成 `<note>`。
- **多声部 / 和弦**：届时再启用 `voice`/`chord`，并扩展 `Part`/`Note` 模型。
- **演奏法 / 歌词**：阶段 5 工程化时按需读取 `notations`/`lyric`，不影响核心音高/时值解析。
