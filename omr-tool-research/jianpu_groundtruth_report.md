# 谱渡 Pudu · 简谱转换 Ground-Truth 校验报告

- 校验方式：music21 独立推导预期简谱，与 C++ 转换器(`staffToJianpu`)输出交叉比对
- 样本文件：9（成功 9，致命失败 0）
- 音符级通过率：**99.6%** （13500/13560）
- 字段级通过率：**99.4%** （92506/93083）

## 错误类型分布

| 类别 | 差异数 | 计入通过率 |
| --- | ---: | --- |
| event_count | 461 | 否（单列/未校验） |
| pitch_degree | 49 | 是 |
| rhythm_unresolvable | 46 | 否（单列/未校验） |
| rhythm | 40 | 是 |
| pitch_octave | 24 | 是 |
| rest | 3 | 是 |

## 边界覆盖

- 变调文件（检测到的调号变化）：4 个
- 休止符音符：549 个
- 和弦音符：231 个
- 装饰音音符：36 个
- 连音组音符（选项 A 起解析 time-modification 标注分组并进入校验）：821 个
- 致命失败文件：无

## 各文件明细

### badinerie-for-flute-by-js-bach.musicxml
- 音符通过率：100.0%（232/232）
- 无差异 ✅

### canon-in-d-violin-solo.musicxml
- 音符通过率：100.0%（269/269）
- 无差异 ✅

### cello-suite-no-1.musicxml
- 音符通过率：100.0%（2290/2290）
- ⚠️ 检测到调号变化（转换器取初始调号，变调段不参与逐音比对）
- 无差异 ✅

### concerto-in-a-minor-a-vivaldi.musicxml
- 音符通过率：100.0%（1933/1933）
- ⚠️ 检测到调号变化（转换器取初始调号，变调段不参与逐音比对）
- 无差异 ✅

### j-s-bach-cello-suite-n-1-bwv-1007-1-prelude.musicxml
- 音符通过率：100.0%（704/704）
- 无差异 ✅

### river_1.jpg.pudu.musicxml
- 音符通过率：11.8%（8/68）
- 差异明细（577 条，前 60 条）：

  | part | voice | measure | idx | 类别 | 字段 | 预期 | 实际 |
  | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
  | 0 | -1 | 1 | 0 | rhythm | rhythm | [0, 3, 0] | [0, 0, 0] |
  | 0 | -1 | 2 | 0 | rhythm | rhythm | [0, 3, 0] | [1, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 4 | 0 | pitch_degree | degree | 1 | 3 |
  | 0 | -1 | 4 | 0 | rhythm | rhythm | [0, 0, 0] | [0, 0, 1] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 3 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 4 | 0 | pitch_degree | degree | 3 | 1 |
  | 0 | -1 | 4 | 0 | rhythm | rhythm | [1, 0, 0] | [0, 0, 1] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 4 | 0 | pitch_degree | degree | 3 | 1 |
  | 0 | -1 | 4 | 0 | rhythm | rhythm | [1, 0, 0] | [0, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 4 | 0 | pitch_degree | degree | 6 | 1 |
  | 0 | -1 | 4 | 0 | pitch_octave | octaveDots | -1 | 0 |
  | 0 | -1 | 4 | 0 | rhythm | rhythm | [1, 0, 0] | [0, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 5 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 4 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | 5 | 0 | pitch_degree | degree | 1 | 5 |
  | 0 | -1 | 5 | 0 | pitch_octave | octaveDots | 0 | -1 |
  | 0 | -1 | 5 | 0 | rhythm | rhythm | [0, 0, 0] | [1, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 6 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 5 | 0 | event_count | event_count | paired event | only in gt |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 6 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 6 | 0 | pitch_degree | degree | 5 | 1 |
  | 0 | -1 | 6 | 0 | pitch_octave | octaveDots | -1 | 0 |
  | 0 | -1 | 6 | 0 | pitch_degree | degree | 1 | 2 |
  | 0 | -1 | 6 | 0 | rhythm | rhythm | [0, 0, 0] | [1, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 6 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | 6 | 0 | pitch_degree | degree | 1 | 5 |
  | 0 | -1 | 6 | 0 | rhythm | rhythm | [0, 0, 0] | [1, 0, 0] |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=0 | conv=1 |
  | 0 | -1 | 7 | 0 | event_count | event_count | paired event | only in conv |
  | 0 | -1 | -1 | -1 | event_count | event_count | gt=1 | conv=0 |
  | 0 | -1 | 6 | 0 | event_count | event_count | paired event | only in gt |
  | ... | | | | | | 其余 517 条见 JSON | |

### solo-violin-caprice-no-24-in-a-minor-n-paganini-op-1-no-24.musicxml
- 音符通过率：100.0%（1116/1116）
- ⚠️ 检测到调号变化（转换器取初始调号，变调段不参与逐音比对）
- 差异明细（46 条，前 60 条）：

  | part | voice | measure | idx | 类别 | 字段 | 预期 | 实际 |
  | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 138 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 140 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 153 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.14375 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |
  | 0 | -1 | 155 | 0 | rhythm_unresolvable | rhythm(tuplet) | unresolvable_ql | 0.11041666666666666 |

### solo-violin-partita-no-2-in-d-minor-j-s-bach-bwv-1004.musicxml
- 音符通过率：100.0%（5561/5561）
- ⚠️ 检测到调号变化（转换器取初始调号，变调段不参与逐音比对）
- 无差异 ✅

### summer-third-movement.musicxml
- 音符通过率：100.0%（1387/1387）
- 无差异 ✅
