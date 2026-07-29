# 谱渡 Pudu · 阶段1 OMR 真引擎实跑指南（oemer 真实路径）

> 本文档对应需求：在本机环境安装 oemer + 权重，准备乐谱图，执行
> `Pudu --from-omr score.png --to-jianpu` 走真实 OMR 路径，确认简谱输出。
> 适用版本：M2 阶段1 集成（omr_adapter + CLI `--from-omr`，零模型改动）。

---

## 0. 一句话原理

`Pudu --from-omr <图> --to-jianpu` 的真实路径是：

```
<乐谱图片>
  └─ omr_adapter（子进程调用）
       └─ tools/omr_oemer.py  →  oemer.ete.main()（深度学习识别，产出 MusicXML）
            └─ MusicXMLParser（既有解析器，零改动）
                 └─ staffToJianpu（既有转换）
                      └─ 简谱（jianpu）输出
```

适配器只消费 oemer 产出的 MusicXML，不关心其内部——这就是"黑盒集成"。

---

## 1. 环境准备（前置依赖）

### 1.1 Python 虚拟环境
Pudu 的校验/OMR 脚本需要带 `music21` + `oemer` 的 Python。本项目已建好 venv：

```
VENV = C:\Users\13157\.workbuddy\binaries\python\envs\default
PY   = C:\Users\13157\.workbuddy\binaries\python\envs\default\Scripts\python.exe
```

> 若你自建环境：`python -m venv venv && venv\Scripts\activate && pip install music21`

### 1.2 安装 oemer 及其依赖
```bat
"%PY%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple oemer
```
- 会装上 oemer-0.1.8 + onnxruntime-gpu + opencv-headless + scipy + scikit-learn。
- **⚠️ 已知坑（oemer 未声明依赖）**：oemer 0.1.8 的 `import oemer` 会间接 `import augly`，
  但 `augly` 不在 oemer 的依赖列表里，`pip install oemer` **不会**自动装。首次运行会报
  `ModuleNotFoundError: No module named 'augly'`。必须手动补装：
  ```bat
  "%PY%" -m pip install augly
  ```

### 1.2.1 打 Pudu 防御补丁（必做，幂等）

oemer 0.1.8 在退化输入（空数组、退化线段）上会崩溃，Pudu 在 site-packages 中打了 6 处
防御补丁。`pip install --upgrade oemer` 会覆盖 site-packages 导致补丁蒸发，因此安装 oemer
后**必须**运行补丁安装器：

```bat
"%PY%" tools\install_oemer.py
```

- **幂等**：已打补丁的文件会被 SKIP，重复运行安全。
- **安全**：版本漂移（oemer 升版或文件被修改）会 ABORT 并打印修复指引，绝不静默覆盖。
- **只检查不改文件**：`"%PY%" tools\install_oemer.py --check-only` 可查看补丁状态。

> 补丁清单与行尾铁律详见 `third_party/oemer-patches/README.md`，
> 设计文档见 `docs/oemer-patch-strategy.md`。

### 1.3 权重文件（首次运行自动下载）
oemer 权重托管在 **GitHub Releases**（`BreezeWhite/oemer/releases/download/checkpoints/`），
共 4 个文件：
```
checkpoints/unet_big/model.onnx      (~67 MB)
checkpoints/unet_big/weights.h5
checkpoints/seg_net/model.onnx
checkpoints/seg_net/weights.h5
```
- **首次**执行 oemer 时，`oemer.ete.main()` 检测到权重缺失会**自动下载**到
  `oemer/checkpoints/...`（走 Python urllib，不依赖系统 curl）。
- 若你网络到 GitHub 正常，自动下载即可；若想预下载避免首次命令超时，可先单独跑一次
  `tools/omr_oemer.py <图> <输出.musicxml>` 把权重缓存下来。
- ⚠️ **沙箱限速提示**：本开发沙箱到 GitHub Releases 实测带宽极低（~25 KB/s），
  4 个权重 ~150MB 需 1.5h+。在你本机（GitHub 正常速度）通常几十秒到几分钟。
- 💡 **本机实操（推荐）**：本机已采用「手动放置权重」方式——把 4 个权重直接放到
  venv 的 `Lib/site-packages/oemer/checkpoints/{unet_big,seg_net}/`，首次运行即跳过下载，
  规避 GitHub 限速。权重可从其他可达源预下载后拷贝。

---

## 2. 准备乐谱图片

任意一张**单页**乐谱照片/扫描图（jpg/png）即可，例如从 oemer 仓库取示例图：
```bat
"%PY%" - <<'PY'
import urllib.request
url = "https://github.com/BreezeWhite/oemer/raw/main/docs/images/chihiro_3.jpg"
urllib.request.urlretrieve(url, "data/score.png")
PY
```
> 命名为 `score.png`（与下面命令一致）；扩展名不影响 oemer 读取。
> 也可用你自己拍/扫的乐谱图，放到项目 `data/` 下。

---

## 3. 执行真实 OMR 命令

**Python 解释器选址（已修复）**：早期 `omr_adapter` 写死用 `python` 命令字，需手动把
venv 的 `Scripts` 放到 PATH 最前。现已改为 `resolveOmerPython()` 自动选址——按
`--omr-python` → 环境变量 `PUDU_OMR_PYTHON` → PATH `python` →
`%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
的顺序，命中第一个能 `import oemer` 的解释器。因此**通常无需手调 PATH**；若想强制某解释器，
用 `Pudu.exe --from-omr <图> --to-jianpu --omr-python <path>`。

**GPU 加速（关键）**：oemer 推理默认首选 CUDA（`oemer/inference.py` 已写
`CUDAExecutionProvider`）。要让 GPU 生效，**必须在本会话注入 CUDA/cuDNN 的 PATH**（Windows 下
CUDA 13 把运行时 dll 放在 `bin/x64`，cuDNN 9 放在 `bin\<cuda版本>\x64`，且 PATH 不递归子目录）：

```bash
# Git Bash（推荐，本机实测用此）
export PATH="/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.3/bin/x64:/c/Program Files/NVIDIA/CUDNN/v9.24/bin/13.3/x64:$PATH"
# 进入构建目录（Pudu.exe 在此）
cd /c/Users/13157/WorkBuddy/omr/build
# 真实 OMR 路径（默认引擎即 oemer）
./Pudu.exe --from-omr ../data/score.png --to-jianpu
```

> ⚠️ **改完系统 PATH 后必须关闭并重新打开终端**——Windows 环境变量只对新建进程生效，
> 运行中进程仍用旧 PATH，会出现 `cublasLt64_13.dll missing` / `cudnn64_9.dll missing` 回退 CPU。
> 注入正确层级后，可用 `nvidia-smi -l 1` 观察 python 进程是否占用 GPU。CPU 回退下整图推理
> 约 4 分钟，6 页评测会超时；GPU 下秒级。

### 预期输出
- 首次运行：先打印 oemer 权重下载进度（若未缓存），随后 oemer 识别日志，
  最后 Pudu 输出**简谱**（如 `1=C 4/4` 头 + 数字简谱行）。
- 非首次（权重已缓存）：直接识别 + 简谱输出，通常数十秒。

示例（fixture 引擎对照，真实 oemer 输出结构相同、内容取决于图片）：
```
=== 谱渡 Pudu · MusicXML 解析骨架 ===
1=C 4/4
1 1 5 5 | 6 6 5 -
```

---

## 4. 验证转换结果正确性

### 4.1 M2-2：music21 结构/语义校验（推荐）
对 oemer 产出的中间 MusicXML 做校验（适配器内部已落地，也可单独跑）：
```bat
"%PY%" ..\tools\omr_validate.py <oemer产出的.musicxml>
```
输出应包含：Part 数、Measure 数、Note 数、拍号（如 4/4）、调号 fifths 等。
这些都是 oemer 识别是否合理的硬指标。

### 4.2 往返自洽（M2-3 思想）
简谱行应与 MusicXML 的音高/节奏一致：取 oemer 产出的 MusicXML，用
`Pudu --to-jianpu-json` 得到结构化简谱，核对音级数、八度、时值。
可再用 `verify_jianpu_groundtruth.py`（需 ground-truth 样本）做跨语言交叉验证。

### 4.3 人工核对
把输出的数字简谱与原始乐谱图对照：调号（1=X）、拍号、各音级与连线是否吻合。

---

## 5. 常见问题与解决

| 现象 | 根因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'augly'` | oemer 未声明该依赖 | `pip install augly` |
| `from oemer import OMR` 失败 / `OMR` 不存在 | oemer 0.1.x 是**函数式 API**，无 `OMR` 类 | 用 `oemer.ete.main()`（本项目 `tools/omr_oemer.py` 已修正） |
| `python` 不是 oemer 所在解释器 / `ModuleNotFoundError: No module named 'oemer'` | 旧版写死 `python` 命令字 | 现已自动选址（见 §3）；若仍报，用 `--omr-python <venv>/Scripts/python.exe` 强制指定 |
| `cublasLt64_13.dll missing` / `cudnn64_9.dll missing`，回退 CPU 且极慢 | CUDA/cuDNN PATH 没指到 `bin/x64` / `bin\<cuda版本>\x64`，或改 PATH 后未重开终端 | 注入 CUDA v13.3 `bin/x64` 与 cuDNN `bin\13.3\x64` 到 PATH，关闭终端重开后再跑（见 §3） |
| 6 页评测超时 / 单图推理 ~4 分钟 | CPU 回退（GPU 未生效） | 按 §3 注入 CUDA/cuDNN PATH 启用 GPU；或临时调大 `omr_adapter.hpp` 的 `timeoutMs` 并重编 |
| 首次运行报 `引擎超时(120000ms)` | 权重下载 > 120s 子进程超时 | **预下载权重**：先单独跑一次 `omr_oemer.py`；或调大 `omr_adapter.hpp` 的 `timeoutMs` 并重编 |
| 权重下载极慢 / 卡住 | 到 GitHub Releases 带宽受限 | 换到你本机（GitHub 正常）跑；或手动把 4 个权重放到 `oemer/checkpoints/{unet_big,seg_net}/` |
| 输出简谱为空/乱 | 输入图非单页乐谱、质量差 | 用清晰单页乐谱图；oemer 对照片类输入更敏感 |

---

## 6. 里程碑与验证标准对应

- **M2-1 引擎可用性**：oemer 子进程可启动并产出 MusicXML（本指南第 3 步）。
- **M2-2 结构语义校验**：`tools/omr_validate.py` 对产出做 music21 校验（第 4.1 步）。
- **M2-3 全链路 ctest**：`test/test_omr_adapter.cpp` 用 **fixture 引擎**（C++ 原生确定性）
  跑通 `OMR→MusicXMLParser→staffToJianpu` 全链路（已纳入 ctest，117 个 gtest 用例 + 41 个 F3 Python 单测全绿）；
  真实 oemer 路径因依赖外部引擎/权重/图片，由本文档的手动实跑验证。

> 设计取舍：M2-3 的 ctest 用 fixture 引擎保证 CI 确定性；真实 oemer 路径通过本文档
> 在本机手动实跑验证，二者共用同一 `omr_adapter` 子进程契约，真引擎按配置无缝接入。

---

## 7. 评测 harness 与 Plan A（进阶，批量量化 oemer 误差）

本指南聚焦「单图 `Pudu --from-omr` 实跑」。要**批量量化 oemer→简谱 的误差分布**（而非单张核对），用评测 harness：

- **harness**：`tools/omr_eval_groundtruth.py <corpus_dir>`（见 `data/omr_eval/README.md`）。
  对每对 `(image, gt.musicxml)` 跑 oemer→Pudu→逐音比对，输出 `note_pass_rate` / `field_pass_rate` /
  `category_pass`（H2 分维通过率）/ `omr_eval_note_diffs.json`（逐音差异）。
  ⚠️ harness **非递归**，必须直接指向含样本的叶子目录（如 `data/omr_eval/real/concerto_pages`）。
- **Plan A 调号后处理**：harness 会自动把同对 gt 经 `--gt` 注入 `tools/omr_oemer.py` 的
  `correct_key_signature`，做调号重推断（已知会过度清零小调临时记号，见 `data/omr_eval/README.md` §6.2）。
- **GPU 同样适用**：跑 harness 前按 §3 注入 CUDA/cuDNN PATH，否则 6 页评测在 CPU 下会超时。
