# 谱渡 Pudu · 阶段 2 单元测试交付概览

> 依据 `omr-tool-research/jianpu_output_spec.md` §5「边界用例清单」补齐单元测试。
> 构建：MSVC 2022 / Ninja / vcpkg(pugixml)。**结果：42/42 通过，0 断言失败。**

## 1. 交付文件

| 文件 | 作用 |
|---|---|
| `test/pudu_test.hpp` | 极简 header-only 测试框架（TEST / EXPECT_* / EXPECT_NO_THROW），零外部依赖 |
| `test/pudu_test_main.cpp` | 测试入口，收集并运行全部 TEST，退出码反映成败 |
| `test/test_helpers.hpp` | fixture 构造辅助（mkPitch / mkNote / mkRest / mkScore），inline 无 ODR 问题 |
| `test/test_tonic.cpp` | `fifthsToTonicPc` / `fifthsToTonicName` 测试（§5 case 9 + 边界/错误） |
| `test/test_pitch_mapping.cpp` | `midiToJianpu` / `midiToDegree` 测试（§5 case 1/2 + 边界/错误） |
| `test/test_duration.cpp` | `typeToDuration` 测试（§5 case 3 + 边界/错误） |
| `test/test_staff_to_jianpu.cpp` | `staffToJianpu` / `jianpuToL1` 端到端测试（§5 case 3/4/5/6/7/8 + 错误） |
| `CMakeLists.txt` | 新增 `PuduTests` 目标（编译 `jianpu_converter.cpp` + 4 测试文件，不链 pugixml） |
| `src/jianpu_converter.cpp` | 顺带修正调外音 `alter==0` 分支（见 §3） |

运行：`build/PuduTests.exe`

## 2. 覆盖矩阵（§5 九项边界 + 每函数正/错用例）

| §5 用例 | 测试文件 | 关键断言 |
|---|---|---|
| ① 八度点 0/+1/-1 | test_pitch_mapping | C4→dot0、C5→dot+1、C3→dot-1 |
| ② D大调 #4(G#) / b7(C) | test_pitch_mapping | G#4→#4、C4→b7（记号方向） |
| ③ 时值全表+附点 | test_duration + staff | whole/half/quarter/eighth/16th/32nd/64th；附点经 `dots` |
| ④ 全休止 / 八分休止 | test_staff_to_jianpu | `0 - - -`、八分休止有减时线 |
| ⑤ 三和弦 | test_staff_to_jianpu | 主音+2 成员音级正确 |
| ⑥ 多声部分行对齐 | test_staff_to_jianpu | 2 行、各按 onset 升序 |
| ⑦ 装饰音 | test_staff_to_jianpu | `isGrace=true`、音级正确 |
| ⑧ 跨小节延音 | test_staff_to_jianpu | 起点 `tieToNext`、止点不画 |
| ⑨ 各调号 | test_tonic | C/G/D/A/E/F/Bb/Eb 字母+主音音级 |

**错误处理用例**：未知/空 `type`→四分默认；空 `Score`→空 doc 不崩；非法 `step` / 休止式 `Pitch`→不抛异常；调号越界→钳制到边界字母；空 `JianpuDoc` 渲染→不崩。

## 3. 顺带修复的规范冲突（§2.1 vs §5 case 2）

原 `midiToJianpu` 对调外音用「`alter<0`→Flat，否则→Sharp」，导致 **D 大调中的 C 自然音（alter==0）被渲染成 #6**，与 §5 case 2 要求的 **b7** 冲突。

修正：新增 `alter==0` 分支，取上方邻级 + Flat，得到 b7（符合 §5）。`alter>0`→#、`alter<0`→b 不变。
真实语料（data/ 8 份）复跑验证：调号抬头正确、无崩溃、b7 拼写正确、无回归。

## 4. 测试框架选型说明

项目当前仅依赖 pugixml，且环境存在 TLS 拦截导致 vcpkg 网络不稳。为避免为测试再引入外部依赖，自研 ~120 行 header-only 框架，与「最小依赖」哲学一致。若日后要切换 GoogleTest：把 `test/` 下用例改用 gtest 宏、CMake 中 `PuduTests` 链接 gtest 即可，测试逻辑无需改写。

## 5. 仍为后置扩展点（测试已覆盖已实现部分并标注限制）

- 和弦逐音八度点（§5 case 5 仅覆盖音级，逐音独立八度点未实现）
- `tuplet` 连音组（Score 暂无 `<time-modification>` 字段，暂置 0）
- 小调「6=X」标法开关
