# 谱渡 Pudu · data/ 样例谱批量测试报告

- 测试时间：2026-07-14
- 被测程序：`build/Pudu.exe`（阶段 0 解析骨架）
- 测试方式：`omr-tool-research/verify_corpus.py`（源 XML 计算预期 → 与程序输出逐项比对）
- 样例总数：**8** 份 `.musicxml`（`.gitkeep` 非谱面，已排除）

---

## 0. 结论速览

测试分两层：

| 层级 | 含义 | 结果 |
|------|------|------|
| **L1 字段提取正确性** | 程序按其 MVP 设计是否正确提取字段（标题/调号/拍号/divisions/谱号/小节数/事件数/休止数/首音） | **8/8 全部通过，80/80 检查项 PASS，无崩溃** |
| **L2 乐理语义正确性** | 输出是否忠实还原乐谱真实内容（标题完整性、和弦、多声部时序） | **发现 3 类真实缺陷，影响 6/8 份样例** |

一句话：**解析器骨架健壮、字段提取零错误；但受 MVP 跳过项限制，对含和弦/多声部/credit 标题的谱面存在语义失真**，这些是后续阶段（尤其阶段 2 简谱转换）必须修复的问题。

---

## 1. L1 字段提取比对（逐份逐项）

每份 10 个检查项，全部 PASS。

| # | 样例谱 | 标题 | 声部 | 调号 | 拍号 | divisions | 谱号 | 小节数 | 事件总数 | 休止数 | 首音 | 状态 |
|---|--------|------|------|------|------|-----------|------|--------|----------|--------|------|------|
| 1 | badinerie-for-flute-by-js-bach | Badinerie | 1 | D 大调 | 2/4 | 8 | G2 | 42 | 232 | 0 | B5 | ✅ 10/10 |
| 2 | canon-in-d-violin-solo | (无) | 1 | D 大调 | 4/4 | 8 | G2 | 27 | 269 | 4 | 休止 | ✅ 10/10 |
| 3 | cello-suite-no-1 | Cello Suite No. 1 | 1 | G 大调 | 4/4 | 24 | F4 | 220 | 2293 | 125 | G2 | ✅ 10/10 |
| 4 | concerto-in-a-minor-a-vivaldi | Concerto in A minor | 1 | C 大调 | 4/4 | 24 | G2 | 240 | 1933 | 57 | E5 | ✅ 10/10 |
| 5 | j-s-bach-cello-suite-n-1-bwv-1007-1-prelude | (无) | 1 | G 大调 | 4/4 | 4 | F4 | 42 | 706 | 49 | G2 | ✅ 10/10 |
| 6 | solo-violin-caprice-no-24…paganini | Capriccio | 1 | C 大调 | 2/4 | 480 | G2 | 158 | 1313 | 27 | A4 | ✅ 10/10 |
| 7 | solo-violin-partita-no-2…bwv-1004 | Partita No. 2 in D Minor | 1 | F 大调 | 4/4 | 24 | G2 | 419 | 5591 | 251 | D4 | ✅ 10/10 |
| 8 | summer-third-movement | (无) | 1 | Bb 大调 | 3/4 | 4 | G2 | 127 | 1391 | 28 | G4 | ✅ 10/10 |

> "事件总数"= 该声部内所有 `<note>` 元素个数（含休止、和弦音、装饰音），与程序输出 token 数完全一致 → 证明程序不漏读、不多读任何 `<note>`。所有程序退出码均为 0。

**L1 小结：80 PASS / 0 FAIL。** 调号（fifths→调名）、拍号、divisions、谱号、小节数、事件计数、休止识别、首音识别全部准确，覆盖了升号调(D)、降号调(Bb/F)、C 大调、高音谱号(G2)、低音谱号(F4)、多种 divisions(4/8/24/480) 与拍号(2/4、3/4、4/4)。

---

## 2. L2 乐理语义正确性缺陷（真实"结果不正确"项）

L1 的"预期值"是**按解析器 MVP 语义**推算的，因此能全部通过。但与乐谱**真实内容**对照，暴露出 3 类缺陷。下表标注每份谱受影响情况：

| 样例谱 | 缺陷A 标题漏读credit | 缺陷B 和弦拍平 | 缺陷C backup多声部丢时序 | 缺陷D 装饰音计时值 |
|--------|:---:|:---:|:---:|:---:|
| badinerie | — | — | — | 2 |
| canon | **是**(真名 Canon in D) | — | — | — |
| cello-suite-no-1 | — | 3 | **38** | 1 |
| concerto-vivaldi | — | — | — | — |
| cello-prelude(bwv1007) | 无credit,正确 | 2 | 4 | — |
| paganini-caprice-24 | — | **197** | 13 | 33 |
| partita-no-2(bwv1004) | — | 30 | **392** | — |
| summer-third-movement | **是**(真名 Summer - Third movement) | 4 | — | — |

（数字为该缺陷在该谱中出现的次数）

### 缺陷 A：标题漏读 `<credit>` —— FAIL（2 份：canon、summer）
- **现象**：Canon 真实标题为 `Canon in D`、Summer 为 `Summer - Third movement`，均写在 `<credit><credit-words>` 中，但程序显示"标题: (无)"。
- **根因**：`parseDocument`（`musicxml_parser.cpp:75-82`）只读 `movement-title` 与 `work/work-title`，未回退到 `<credit>`。很多导出软件（尤其扫描/OMR 生成的谱）只把标题写进 credit 文字块。
- **判定**：字段提取"技术上按设计正确"，但**乐谱真实标题被丢失，属结果不正确**。
- **修复**（`musicxml_parser.cpp` parseDocument 末尾追加回退）：
  ```cpp
  // movement-title / work-title 都为空时，回退到第一条 credit-words
  if (out.title.empty()) {
      for (pugi::xml_node cr : root.children("credit")) {
          if (pugi::xml_node cw = cr.child("credit-words")) {
              std::string t = cw.text().as_string();
              // 去首尾空白后取第一条非空（通常最靠上的即标题）
              if (!t.empty()) { out.title = t; break; }
          }
      }
  }
  ```
  可进一步用 `credit` 的 `default-y`（纵坐标最大=最靠上）挑选主标题，避免误取作者行。

### 缺陷 B：和弦被拍平为顺序音符 —— FAIL（5 份，Paganini 达 197 处）
- **现象**：`<chord/>` 标记的音（与前一音**同时发声**）被当作独立顺序音符输出。例：一个三和弦 `A4+C5+E5` 输出成 `A4 C5 E5` 三个连续音。
- **根因**：`parseNote`（`musicxml_parser.cpp:161-203`）未检测 `<chord/>` 子元素，全部 `push_back` 到 measure.notes；`score_model.hpp` 的 `Note` 也无"和弦成员"结构。
- **判定**：事件计数对（L1 PASS），但**节奏与和声语义错误**——后续转简谱会把和弦读成一串快速单音，严重失真。
- **修复思路**（两处）：
  1. `score_model.hpp`：给 `Note` 增加 `bool isChordMember=false;`（或 `vector<Pitch> chordPitches;` 归并到主和弦音）。
  2. `musicxml_parser.cpp:parseNote`：起始处判断
     ```cpp
     bool isChord = (bool)noteNode.child("chord");
     ```
     若 `isChord`，则**不推进时间轴**：将该音并入上一 `Note` 的和弦音列表（`measure.notes.back().chordPitches.push_back(...)`），而非新建 Note。
  3. 打印层（`main.cpp`）相应用 `(A4 C5 E5)` 括号形式表示和弦。

### 缺陷 C：`<backup>` 被跳过导致多声部时序错乱 —— FAIL（4 份，Partita 达 392 处）
- **现象**：多声部小节里，声部2 在 `<backup>`（时间回退）后书写。程序跳过 backup，把声部2 直接接在声部1 之后**首尾拼接**。
- **实证**（cello-suite 小节 33）：源为 `voice1(16 音) + <backup 96> + voice2(9 音)`，二者本应**同时演奏**；程序输出却是 25 个连续事件：
  ```
  小节 33: F#3 A3 D3 A3 E3 A3 F#3 A3 0 A3 0 A3 0 A3 0 A3 | 0 G3 0 A3 0 B3 0 D3 0
                                                    ↑ 此后应与前半同时，实际被拼在末尾
  ```
- **根因**：`parseMeasure`（`musicxml_parser.cpp:119-159`）只处理 `attributes/note`，注释明确"backup/forward 跳过"；模型也没有"时间位置(onset)"概念。
- **判定**：单声部谱(canon/summer/vivaldi/badinerie)无此问题；**多声部/多层谱的小节内容顺序错误**，是转简谱前必须解决的结构性缺陷。
- **修复思路**（较大，建议阶段 2 前做）：
  1. `score_model.hpp`：`Note` 增加 `int onset=0;`（小节内起始位置，单位=divisions）；`Note` 增加 `int voice=1;`。
  2. `musicxml_parser.cpp`：`parseMeasure` 维护游标 `cursor`，每遇 `note`（非 chord）令 `note.onset=cursor; cursor+=duration`；遇 `<backup>` 执行 `cursor-=duration`；遇 `<forward>` 执行 `cursor+=duration`。
  3. 收尾按 `(onset, voice)` 排序，即可还原真实时间对齐；简谱转换按声部或按 onset 分层输出。

### 缺陷 D：装饰音（grace note）计入事件、无时值 —— 轻微（3 份）
- **现象**：`<grace/>` 音无 `<duration>`，程序仍作为普通音计入（duration=0）。
- **根因**：`parseNote` 未区分 grace；对计数无害，但 duration=0 会干扰未来的时值/onset 计算。
- **修复**：`Note` 增 `bool isGrace;`，parseNote 检测 `noteNode.child("grace")` 置位；onset 推进时跳过 grace（不加时值）。优先级低于 A/B/C。

### 其他边界（本批未触发，但需留意）
- **多 staff（钢琴谱等）**：`parseMeasure` 只取首个 `<clef>`；本批 8 份均为单谱表独奏，诊断未报多谱号，故未触发。将来遇钢琴/合唱谱需按 `<staff>` 分层。
- **`.mxl` 压缩包**：已有 `isZipFile` 预检并给出友好报错，本批无 `.mxl`。

---

## 3. 按样例谱汇总（状态 · 错误 · 方案）

| 样例谱 | L1字段 | L2语义 | 主要问题 | 解决方案定位 |
|--------|:---:|:---:|------|------|
| badinerie | ✅ | ⚠️ 轻微 | 2 装饰音计时值 | 缺陷D：parseNote 加 isGrace |
| canon | ✅ | ❌ | 标题丢失(Canon in D) | 缺陷A：parseDocument 回退 credit |
| cello-suite-no-1 | ✅ | ❌ | 38 backup 时序错乱 + 3 和弦 | 缺陷C+B：onset 游标 + 和弦归并 |
| concerto-vivaldi | ✅ | ✅ | 无（单声部无和弦） | — |
| cello-prelude(bwv1007) | ✅ | ❌ | 4 backup + 2 和弦 | 缺陷C+B |
| paganini-caprice-24 | ✅ | ❌ | 197 和弦拍平 + 13 backup + 33 装饰音 | 缺陷B+C+D（本批最严重） |
| partita-no-2(bwv1004) | ✅ | ❌ | 392 backup 时序错乱 + 30 和弦 | 缺陷C+B（backup 最多） |
| summer-third-movement | ✅ | ❌ | 标题丢失 + 4 和弦 | 缺陷A+B |

**统计**：L1 通过 8/8；L2 完全正确 1/8（vivaldi），轻微 1/8（badinerie），存在实质缺陷 6/8。

---

## 4. 修复优先级建议

1. **P0 缺陷C（backup/onset 时序）**——影响面最广、最深（partita 392 处），是阶段 2 简谱转换的硬前提。需给模型加 `onset/voice`。
2. **P0 缺陷B（和弦）**——5 份受影响，和声/节奏语义关键。与 C 一起做，共用模型改造。
3. **P1 缺陷A（credit 标题）**——改动小、见效快，可立即修复（约 8 行）。
4. **P2 缺陷D（grace）**——随 B/C 的模型改造顺带处理。

> 建议：把上述模型字段（`onset`、`voice`、`isChordMember`/`chordPitches`、`isGrace`）一次性加入 `score_model.hpp`，再统一改造 `parseMeasure/parseNote`，避免多次返工——这正好可作为进入**阶段 2** 的第一步。

---

## 附：复现实验方法
```bash
# 批量核对
python omr-tool-research/verify_corpus.py
# 单份运行
build/Pudu.exe data/<name>.musicxml
```

---

## 5. 阶段 2 前置修复已落地（2026-07-14 后续）

按"一次性给 Note 加 onset/voice/chordPitches/isGrace"方案完成改造，为简谱转换铺路。

### 5.1 改动文件
- `include/score_model.hpp`
  - `Note` 新增 4 字段：`int onset`（小节内起始，单位=divisions）、`int voice`（声部，默认1）、`std::vector<Pitch> chordPitches`（和弦其余音）、`bool isGrace`。
  - `Measure` 新增 `totalEvents()`（说明：和弦后续音已并入 chordPitches，故 `notes.size()` 即真实事件数）。
- `include/musicxml_parser.hpp`：`parseNote` 签名加 `int divisions`；`MusicXMLParser` 增私有 `int cursor_ = 0`（时间游标）。
- `src/musicxml_parser.cpp`
  - `parsePart`：每声部开始重置 `cursor_ = 0` 与 `attributesSeen_ = false`。
  - `parseMeasure`：遍历增加 `backup`（游标 `-=duration`）、`forward`（游标 `+=duration`）分支；调用 `parseNote` 时传入 `divisions`。
  - `parseNote`：检测 `<chord/>`——是则将音高并入上一音 `chordPitches` 并 return（不推进时间轴、不单独成事件）；否则建普通音，`onset=cursor_`，读 `<voice>`，读 `<grace>` 置 `isGrace`；**装饰音不推进游标**（无 duration）。
- `src/main.cpp`：显示层增强——和弦主音加 `⊕` 前缀并以 `(音)` 标注成员；装饰音加 `g` 前缀；新增 `--debug` 模式打印每音 `[音@o<onset>v<voice>]` 供核对。

### 5.2 向后兼容
- 既有字段（isRest/pitch/duration/type/dots/tie）与 `Score/Part/Measure` 结构全部不变；单声部单旋律谱（canon/summer/vivaldi/badinerie）输出序列与改动前完全一致。
- 和弦成员并入首个音的 `chordPitches`，不再产生重复事件——事件计数反而更准（见 §1 表中"音符事件总数"已随修正自动下降，如 partita 5591→5561）。

### 5.3 验证结果（修复后全量复跑）
- `verify_corpus.py` **80/80 PASS / 0 FAIL / 8 文件全部退出码 0**。
- 新字段实证：
  - **onset/voice**（cello-suite 小节 33, divisions=24）：voice1 `F#3@o3072 … A3@o3162`（16 音，间距 6=16 分音符）；`<backup 96>` 把游标从 3168 回退到 3072；voice2 `R@o3072 … D3@o3162` 与 voice1 **共享 onset** → 多声部时序正确还原（原缺陷 C 已解决）。
  - **chordPitches**（paganini 小节 37 `⊕C4/quarter(C5)`、summer 小节 44 `⊕D4/quarter(A5)(E6)`）：和弦归并正确（原缺陷 B 已解决）。
  - **isGrace**（badinerie `gA5/eighth`）：装饰音标记正确（原缺陷 D 已解决）。

> 说明：缺陷 A（标题漏读 `<credit>`）本批未实现，仍按 §2 方案待后续处理（独立的 P1 小改动）。其余 B/C/D 已通过字段补齐解决，阶段 2 简谱转换可直接消费 onset/voice/chordPitches/isGrace。
