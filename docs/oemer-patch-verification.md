# 谱渡 Pudu · oemer 补丁验证策略与预期结果（QA 交接）

> 本文档定义 oemer site-packages 补丁固化的验证流程、预期结果与通过判据，
> 供 QA 按步骤执行。

---

## 1. 验证目标

确认 P0 交付的 oemer 补丁固化方案（方案 B：Patch 文件 + apply 脚本）满足：

1. **可应用**：patch 能 apply 到干净原版 oemer 0.1.8，apply 后 sha == patched_lf。
2. **幂等**：已打补丁的文件重复 apply 不会报错或重复打（SKIP）。
3. **可还原**：逆 apply 能还原为原版（sha == original_lf）。
4. **防漂移**：sha 不匹配时 ABORT，绝不静默覆盖。
5. **行尾无关**：CRLF 版补丁文件也能被正确识别为 ALREADY_PATCHED。
6. **OMR 不崩**：打补丁后 oemer 能正常跑 `data/river_1.jpg` 并产出 MusicXML。

---

## 2. 验证环境

| 项 | 值 |
|----|-----|
| venv Python | `C:\Users\13157\.workbuddy\binaries\python\envs\default\Scripts\python.exe` |
| oemer 版本 | 0.1.8 |
| 仓库根 | `C:\Users\13157\WorkBuddy\omr` |
| 补丁目录 | `third_party/oemer-patches/` |
| 测试图片 | `data/river_1.jpg` |

---

## 3. 验证步骤与预期结果

### 步骤 1：单元测试

```bash
"%PY%" tools\test_install_oemer.py
```

**预期结果**：
- 全部测试 PASS（约 15 个 test case）。
- 覆盖：LF 归一化 sha、三态判定（CLEAN/PATCHED/DRIFT）、apply→APPLIED、
  幂等→SKIP、CRLF 识别、DRIFT→ABORT、--check-only 不改文件、manifest 加载、
  patch 文件行尾 LF。

**通过判据**：`OK` 行数 == 测试数，无 `FAIL` / `ERROR`。

### 步骤 2：当前 venv 幂等检查

当前 venv 的 oemer 已打补丁，运行 install_oemer.py 应全部 SKIP：

```bash
"%PY%" tools\install_oemer.py
```

**预期输出**：
```
[oemer-patch] 汇总: APPLIED=0, SKIPPED=2, ABORTED=0
```

**通过判据**：exit code = 0，APPLIED=0，SKIPPED=2，ABORTED=0。

### 步骤 3：--check-only 不改文件

```bash
"%PY%" tools\install_oemer.py --check-only
```

**预期输出**：
- 不输出 "成功应用" 字样。
- 所有文件报告状态（CLEAN 或 PATCHED）。
- exit code = 0。

**通过判据**：文件 sha 在运行前后不变。

### 步骤 4：全自动 QA 冒烟

```bash
REM 方式一：一键 bat
tools\qa_oemer_patch_smoke.bat

REM 方式二：直接跑 Python
"%PY%" tools\verify_oemer_patch.py --py "%PY%"
```

**预期流程与结果**：

| 步骤 | 动作 | 预期 |
|------|------|------|
| 1 | 干净重装 oemer==0.1.8 | pip install 成功 |
| 2 | install_oemer.py | APPLIED=2, SKIPPED=0, ABORTED=0, exit=0 |
| 3 | 逆 apply 两个 patch | sha == original_lf |
| 4 | 再 apply 两个 patch | APPLIED=2, sha == patched_lf |
| 5 | omr_oemer.py data/river_1.jpg | exit=0, 产出非空 .musicxml |

**通过判据**：汇总显示 `ALL PASS`，exit code = 0。

### 步骤 5（可选）：跳过 OMR 的快速验证

若 OMR 实跑耗时过长（CPU 模式 ~4 分钟），可跳过步骤 5：

```bash
"%PY%" tools\verify_oemer_patch.py --skip-omr --py "%PY%"
```

**通过判据**：步骤 1–4 全 PASS。

---

## 4. 补丁点清单（6 处 ground-truth）

| # | 文件 | 函数 | sha 类型 | 值 |
|---|------|------|---------|-----|
| 1 | bbox.py | find_lines | original_lf | `ff72f4b0…` |
| 1 | bbox.py | find_lines | patched_lf | `126630fb…` |
| 2-6 | staffline_extraction.py | unit_size/slope/norm/filter_line_peaks/extract_line | original_lf | `ba60d544…` |
| 2-6 | staffline_extraction.py | 同上 | patched_lf | `47178282…` |

> 完整 sha 见 `third_party/oemer-patches/oemer-0.1.8.checksums.json`。

---

## 5. 失败排查

| 现象 | 可能原因 | 解决 |
|------|---------|------|
| 步骤2 ABORTED | oemer 版本不是 0.1.8 或文件被修改 | `pip install oemer==0.1.8` 后重跑 |
| 步骤2 git apply 失败 | git 不在 PATH | 确保 git 可用 |
| 步骤3 逆 apply 失败 | 补丁文件与 site-packages 版本不一致 | 重跑 `tools/_regen_oemer_patches.py` |
| 步骤5 OMR 崩溃 | 补丁未正确应用或权重缺失 | 检查步骤2输出，按 m2 指南 §1.3 准备权重 |
| 步骤5 超时 | CPU 模式慢 | 调大 timeout 或用 `--skip-omr` |
| sha 校验假阴性 | 行尾未归一化 | 确认使用 LF 归一化 sha（脚本已内置） |

---

## 6. 交付物清单

| 文件 | 说明 |
|------|------|
| `third_party/oemer-patches/bbox.py.patch` | bbox.py 补丁（LF） |
| `third_party/oemer-patches/staffline_extraction.py.patch` | staffline 补丁（LF） |
| `third_party/oemer-patches/oemer-0.1.8.checksums.json` | 版本锁 + sha + 补丁点清单 |
| `third_party/oemer-patches/README.md` | 补丁说明 |
| `requirements-oemer.txt` | oemer==0.1.8 依赖声明 |
| `tools/oemer_patch_lib.py` | 核心库（三态判定 + apply + 回验 + 回滚） |
| `tools/install_oemer.py` | 安装入口 |
| `tools/test_install_oemer.py` | 单元测试 |
| `tools/_regen_oemer_patches.py` | 补丁再生成工具（维护用） |
| `tools/verify_oemer_patch.py` | QA 验证脚本 |
| `tools/qa_oemer_patch_smoke.bat` | QA 一键脚本 |
| `docs/oemer-patch-strategy.md` | 架构设计文档 |
| `docs/oemer-patch-class.mermaid` | 类图 |
| `docs/oemer-patch-sequence.mermaid` | 时序图 |
| `docs/oemer-patch-verification.md` | 本文档 |
| `docs/m2-real-run-guide.md` | 运行指南（增补 §1.2.1） |
