# 谱渡 Pudu · 文件编码扫描与转换报告

> 生成时间：2026-07-13 10:11:00  
> 扫描根目录：`C:\Users\13157\WorkBuddy\omr`  
> 检测方式：BOM 识别 → UTF-8 严格解码 → GB18030 回退 → chardet 兜底（chardet=已启用）  
> 安全策略：跳过 `.git` 与二进制构建目录；二进制文件仅报告不转换；转换采用原子写并保留原始修改时间戳。

## 一、转换统计

| 指标 | 数值 |
|---|---|
| 扫描文件总数 | 21 |
| 已转换（非 UTF-8 → UTF-8 无 BOM） | 0 |
| 跳过（已是 UTF-8 / 二进制 / 链接） | 21 |
| 失败 / 无法识别 | 0 |

## 二、已转换文件清单

（无 —— 所有文本文件均已为 UTF-8 无 BOM）

## 三、已是 UTF-8（无 BOM）文件清单（跳过）

| # | 文件 | 大小(字节) |
|---|---|---|
| 1 | `.gitattributes` | 210 |
| 2 | `.gitignore` | 341 |
| 3 | `.vscode/launch.json` | 589 |
| 4 | `.vscode/settings.json` | 395 |
| 5 | `.workbuddy/memory/2026-07-11.md` | 1515 |
| 6 | `.workbuddy/memory/2026-07-12.md` | 11575 |
| 7 | `.workbuddy/memory/2026-07-13.md` | 1887 |
| 8 | `.workbuddy/memory/MEMORY.md` | 1458 |
| 9 | `CMakeLists.txt` | 2949 |
| 10 | `CMakePresets.json` | 789 |
| 11 | `data/.gitkeep` | 0 |
| 12 | `omr-tool-research/build_system_assessment.md` | 5727 |
| 13 | `omr-tool-research/cmake_vcpkg_learning_route.md` | 16134 |
| 14 | `omr-tool-research/environment_troubleshooting.md` | 9451 |
| 15 | `omr-tool-research/fields.yaml` | 1488 |
| 16 | `omr-tool-research/outline.yaml` | 1013 |
| 17 | `omr-tool-research/results/research_report.md` | 19129 |
| 18 | `omr-tool-research/stage0_plan.md` | 17652 |
| 19 | `README.md` | 3249 |
| 20 | `src/main.cpp` | 4696 |
| 21 | `vcpkg.json` | 176 |

## 四、二进制 / 链接文件（仅报告，未转换）

| # | 文件 | 识别结果 | 大小(字节) |
|---|---|---|---|
| — | （无） | — | — |

## 五、失败 / 无法识别文件（需人工处理）

（无 —— 全部文件均已成功识别并处理）

## 六、完整明细（按路径排序）

| 文件 | 大小 | 检测编码 | 处理动作 | 备注 |
|---|---|---|---|---|
| `.gitattributes` | 210 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.gitignore` | 341 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.vscode/launch.json` | 589 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.vscode/settings.json` | 395 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.workbuddy/memory/2026-07-11.md` | 1515 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.workbuddy/memory/2026-07-12.md` | 11575 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.workbuddy/memory/2026-07-13.md` | 1887 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `.workbuddy/memory/MEMORY.md` | 1458 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `CMakeLists.txt` | 2949 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `CMakePresets.json` | 789 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `data/.gitkeep` | 0 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/build_system_assessment.md` | 5727 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/cmake_vcpkg_learning_route.md` | 16134 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/environment_troubleshooting.md` | 9451 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/fields.yaml` | 1488 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/outline.yaml` | 1013 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/results/research_report.md` | 19129 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `omr-tool-research/stage0_plan.md` | 17652 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `README.md` | 3249 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `src/main.cpp` | 4696 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |
| `vcpkg.json` | 176 | UTF-8 | 跳过(已UTF-8) | 已是 UTF-8（无 BOM） |

## 七、方法与说明

- **UTF-8（无 BOM）为目标编码**：与项目 `.gitattributes`（`* text=auto eol=lf`）一致，避免 MSVC 中文路径/源码的 GBK 误报（C4819）。
- **二进制判定**：文件前 8 KB 含 NUL 字节，或控制字符占比 > 30% 即视为二进制，仅报告不修改。
- **编码识别顺序**：BOM 标记 → UTF-8 严格解码 → GB18030（覆盖 GBK/GB2312）→ chardet 兜底（置信度 ≥ 70% 才采用）。
- **完整性校验**：转换后以 UTF-8 重新解码并与原文逐字符比对（往返一致）方算成功。
- **时间戳保留**：转换使用临时文件 + 原子替换，并用 `os.utime` 还原原始访问/修改时间。
- **未扫描范围**：`.git/` 仓库内部对象被跳过（防止破坏 Git 对象寻址）；二进制产物目录（build/vcpkg_installed 等）若存在亦跳过。
