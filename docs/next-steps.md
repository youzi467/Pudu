# 谱渡 Pudu · 下一步行动清单

> 生成：2026-07-29 14:34 · 重刷：2026-08-14（同步至分发/桌面化 P0–P4 完成 + AV 主引擎时代）
> 定位：聚焦「接下来做什么」的可执行路线图；历史全貌见 `product-status.md`，执行计划见 `distribution-plan.md`。
> git 基线：2026-08-14 本地 `main` 已推送到 `origin/main`（0 未推送），工作区仅剩未跟踪的 `docs/software-user-manual.md`（AI 生成软著手册，按约束永不提交）。

---

## 0. 当前位置（一句话）

核心转换（MusicXML⇄简谱双向 + 简谱文本直入 MusicXML）已达成；**识别引擎已从 oemer 迁移到 Audiveris（主引擎，基线 97.56%）**；**分发/桌面化 P0–P4 全部完成 + GitHub Release v0.9.0 已发布**——pywebview 桌面壳 + 绿色 ZIP（114MB）+ Inno 安装包（90MB）+ 回归零劣化验证 + 图标全链路落地（f318511）。剩余为「版权申报决策（暂停待拍板）」以及若干可选增强。

---

## 1. 已完成里程碑

| # | 模块 | 状态 | 关键指标 |
|---|---|---|---|
| 1 | 核心转换引擎（C++ 双向） | ✅ MVP | 117 gtest + 77 Python 单测全绿；music21 跨语言 100% |
| 2 | M2 OMR 黑盒集成 | ✅ | `--from-omr` CLI、oemer/fixture 引擎 |
| 3 | Plan A 调号后处理 + P2 无 gt alter 推断 | ✅ | 997b3aa；真实推理变音不再误清零 |
| 4 | F3 几何校正器 | ✅ 实验性保留 | 全量 A/B 证零效果，默认 OFF（P3 2026-07-29 拍板） |
| 5 | **AV 迁移**（2026-08-09） | ✅ | 主引擎 759290e；13 页 note_pass 84.5%→97.56%；keysig 13/13、节奏错 346→24 |
| 6 | AV 低分辨率自动放大重试 | ✅ | 0820afc；interline<8px 时 2x→3x 重试 |
| 7 | MusicXML 层差异检测工具 | ✅ | 937d40d；`omr_musicxml_diff.py`，25 单测 |
| 8 | 版权/合规基线 | ✅ 部分 | 22ff6da：MIT LICENSE + 分发方案；软著申报暂停 |
| 9 | **分发/桌面化 P0–P4**（2026-08-13~14） | ✅ | 943e5bc→4453166；pywebview 壳 + ZIP 107MB + Inno 86MB + 回归零劣化 |
| 10 | **应用图标全链路 + GitHub Release v0.9.0 发布**（2026-08-14） | ✅ | f318511（EXE/favicon/SetupIconFile 图标）+ 441266e/f318511 后资产已替换为图标构建（ZIP 114MB + Inno 90MB） |

---

## 2. 待办事项（按优先级）

### ✅ 发布动作（已完成 · 2026-08-14）

- **现状**：**GitHub Release v0.9.0 已发布**（`https://github.com/youzi467/Pudu/releases/tag/v0.9.0`）——tag 已推、双产物已上传（ZIP 114MB + 安装包 90MB，f318511 图标构建）、发布说明齐备（功能/依赖/已知限制：oemer 不随包、文件关联未做、干净机器实机未验）。
- **发布方式（非交互）**：`git credential fill` 取 GCM OAuth token → curl 打 Releases API；本机 curl 需 `--ssl-no-revoke`（schannel `CRYPT_E_NO_REVOCATION_CHECK`）。

### 🟡 版权申报决策（人拍板 · 暂停中）

- **现状**：2026-03-15 新规后暂停——本项目 AI 辅助开发与「未使用 AI 开发」承诺冲突，无法如实签署（见 `docs/copyright-application-checklist.md` §5.1）。
- **选项**：① 永久放弃申报（文档标记"不申报"）；② 咨询合规渠道后重新评估；③ 其他。
- **红线**：不伪造「未使用 AI 开发」承诺。本项由人决策，我不代签。

### 🟢 可选增强（我可做，按需排期）

1. **文件关联**：应用图标已全链路落地（f318511，EXE/favicon/SetupIconFile）；文件关联需先给桌面壳加 argv 传文件打开（`pudu_desktop.exe <image>` 直投）。
2. **M2-opt-C 后处理规则引擎扩展**：节拍对账/八度连续性已部分存在（Pudu.exe `--apply-postcorrect`），可按需扩展并接入桌面端。
3. **oemer 回退链路本机完整性**：AV 为主引擎 + oemer 不随包分发，此项优先级已大幅降低；仅当要保证本机 dev 回退可用时重装 venv + 预放权重。
4. **阶段 4 AI/DL**：自训/微调音符检测模型 + ONNX 部署（大工程，需 PyTorch + 合成数据基建，当前为零）。

---

## 3. 已关闭 / 不再做（避免重复劳动）

| 事项 | 结论 | 依据 |
|---|---|---|
| P1 octave run-to-run 波动 | **CLOSED（伪命题）** | 12 次复跑 std=0 |
| F3 作为音准改进上线 | **不做** | 全量 A/B 证零效果 |
| F3 代码/开关移除 | **不做（保留实验性）** | P3 2026-07-29 拍板 |
| Fork oemer 固化补丁 | **不需要** | P0 方案 B（patch 随包分发） |
| 向上游发 PR | **不做** | 补丁为 Pudu 特有防御 |
| 固定 seed / 多数投票修 octave | **不做** | octave 零波动 |
| 更强 OMR 评估（Audiveris vs oemer） | **✅ 已完成** | 2026-08-09 迁移 AV 为主引擎（759290e） |
| 阶段 5 GUI/工程化 | **✅ 已完成** | 2026-08-14 pywebview P0–P4（4453166） |

---

## 4. 风险与前置条件

| 风险 | 影响 | 缓解 |
|---|---|---|
| 打包产物未随源码同步 | 发布内容与源码不符 | 每次源码改动后重跑 PyInstaller + 7z + ISCC（本清单发布任务已覆盖） |
| 打包 app 残留进程锁 DLL | PyInstaller 重建失败 | 重建前 `Get-Process pudu_desktop | Stop-Process -Force` |
| oemer 升版（>0.1.8） | P0 patch context 失配 | `install_oemer.py` abort 告警，`_regen_oemer_patches.py` 重生成 |
| bach_p2/p3 可读不可再渲染 | 个别页 MusicXML 边界 | 已列 product-status §7 已知边界，不作默认修复 |
| 干净机器实机未验 | 发布前最大不确定项 | 已论证无系统 Python 依赖（embeddable 3.13.14 + CRT app-local + WebView2 内置） |

---

## 5. 推荐执行顺序

```
1. ✅ 发布动作（已完成 2026-08-14，v0.9.0）
   ↓
2. 版权申报决策（人拍板，暂停中）
   ↓
3. 可选增强按需排期（文件关联 / M2-opt-C / AI-DL）
```

> **关键路径**：当前无技术阻塞、无未发布产物；唯一悬挂的外部事项为版权申报决策（人拍板）。

---

## 附：本文档维护约定
- 每完成一项，在对应行标注 ✅ + 日期 + commit hash，并同步 `product-status.md`。
- 优先级变化时同步本节 §5。
- 新增待办项追加到 §2，保持「目标-为什么-任务-DoD-依赖-预计」六要素结构。
