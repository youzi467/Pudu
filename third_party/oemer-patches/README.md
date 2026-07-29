# oemer site-packages 防御补丁（Pudu P0 固化）

本目录存放 oemer 0.1.8 在 venv site-packages 中的 **6 处防御补丁**的 unified diff 文件、
版本锁 checksums 清单，以及再生成说明。补丁通过 `tools/install_oemer.py` 一键应用，
解决 `pip install --upgrade oemer` 覆盖 site-packages 导致补丁蒸发、oemer 在退化输入上
崩溃的回归问题。

## 文件清单

| 文件 | 说明 |
|------|------|
| `bbox.py.patch` | bbox.py 补丁（1 处：`find_lines` 退化线段跳过） |
| `staffline_extraction.py.patch` | staffline_extraction.py 补丁（5 处：空数组防御） |
| `oemer-0.1.8.checksums.json` | 版本锁 + 6 个 LF 归一化 sha256 + 6 处修改点清单 |

## 6 处补丁点（ground-truth 驱动，与 site-packages 完全一致）

| # | 文件 | 函数 / 位置 | 修改要点 |
|---|------|------------|---------|
| 1 | `bbox.py` | `find_lines` (~L123) | `np.asarray(line).ravel()` + `len(seg)<4` 跳过退化段 |
| 2 | `staffline_extraction.py` | `Staff.unit_size` (L237) | `... if gaps else 10.0` |
| 3 | `staffline_extraction.py` | `Staff.slope` (L250) | `... if self.lines else 0.0` |
| 4 | `staffline_extraction.py` | `extract` 内 `norm` lambda (L358-359) | `_mean` 空兜底 + `norm` 空兜底 |
| 5 | `staffline_extraction.py` | `filter_line_peaks` (L466-470) | `if len(peaks)==0: return empty` `[Pudu patch #5]` |
| 6 | `staffline_extraction.py` | `extract_line` (L429-432) | `if len(centers)==0: return empty` `[Pudu patch #6]` |

## 行尾铁律（⚠️ 必须遵守）

oemer wheel 内文件为 **LF**。现网 site-packages 中 `staffline_extraction.py` 被手工编辑成
**CRLF**（`bbox.py` 仍 LF）。`git apply` 默认 `core.autocrlf` 会把输出转 CRLF，导致 sha 校验
假阴性。三条铁律：

1. **patch 内容必须 LF**（本目录的 .patch 文件均为 LF）。
2. **apply 必须用** `git -c core.autocrlf=false apply -p1`（强制 LF 输出）。
3. **所有 sha 比较先 LF 归一化**（`bytes.replace(b"\r\n", b"\n")`）。

`oemer-0.1.8.checksums.json` 中的 4 个 sha 均为 **LF 归一化 sha256**。注意
`staffline_extraction.py` 的 `patched_sha256_lf` (`471782…`) **不等于** 现网 site-packages
的 raw sha（`81df88…`）——因为现网该文件是 CRLF。必须用 LF 归一化 sha 比较，否则会把
「已打补丁但 CRLF」误判为 drift。

## 应用方法

```bash
# 在 Pudu 根目录执行
python tools/install_oemer.py
```

- **幂等**：已打补丁的文件会被 SKIP，不会重复打。
- **安全**：版本漂移（sha 不匹配）会 ABORT 并打印重生成指引，绝不静默覆盖。
- **回滚**：apply 后 sha 校验失败会自动 `git apply --reverse` 回滚已应用的补丁。

## 再生成方法（oemer 升版或补丁变更时）

使用开发工具 `tools/_regen_oemer_patches.py`：

```bash
python tools/_regen_oemer_patches.py
```

该脚本会：
1. 从 PyPI 下载 oemer==0.1.8 wheel，解压取原版文件。
2. 与当前 site-packages 中的文件做 `difflib.unified_diff`，生成 LF patch。
3. 重算 4 个 LF 归一化 sha256，回填到 `oemer-0.1.8.checksums.json`。

> ⚠️ 此脚本仅供维护使用，不参与安装链路。详见 `docs/oemer-patch-strategy.md` §3.5。
