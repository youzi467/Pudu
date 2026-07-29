#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer site-packages 补丁应用核心库

按 docs/oemer-patch-strategy.md §3.3 实现。纯 Python 标准库（hashlib, subprocess,
json, pathlib, dataclasses, enum, sys, importlib.metadata）。

核心职责：
  1. 加载 checksums manifest（版本锁 + sha + 补丁点清单）。
  2. 定位 venv 中的 oemer 包目录。
  3. 三态判定（CLEAN / ALREADY_PATCHED / DRIFT），主判据 = LF 归一化 sha256。
  4. apply patch（git -c core.autocrlf=false apply -p1），apply 后回验 sha，失败回滚。
  5. 编排全部补丁，汇总报告。

行尾铁律：patch 内容 LF；apply 用 core.autocrlf=false；所有 sha 先 LF 归一化。
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import pathlib
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Optional


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

OEMER_VERSION = "0.1.8"
GIT_APPLY_OPTS = ["git", "-c", "core.autocrlf=false", "apply"]
GIT_APPLY_CHECK_OPTS = ["git", "-c", "core.autocrlf=false", "apply", "--check"]

# 仓库根 = 本文件向上两级（tools/ → repo_root）
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHES_DIR = REPO_ROOT / "third_party" / "oemer-patches"
CHECKSUMS_FILE = PATCHES_DIR / "oemer-0.1.8.checksums.json"


# ---------------------------------------------------------------------------
# 数据类与枚举
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class PatchSpec:
    """单个补丁规格（从 checksums.json 的 files 条目构建）。"""
    file: str                    # 相对 oemer 包根的路径，如 "bbox.py"
    patch_file: str              # third_party/oemer-patches/ 下的 patch 名
    original_sha256_lf: str      # 原版文件的 LF 归一化 sha256
    patched_sha256_lf: str       # 补丁后文件的 LF 归一化 sha256


class FileState(enum.Enum):
    """文件三态（主判据 = LF 归一化 sha256）。"""
    CLEAN = "clean"                # == original_lf sha → 需要 apply
    ALREADY_PATCHED = "patched"    # == patched_lf sha → 跳过（幂等）
    DRIFT = "drift"                # 两者都不是 → 版本漂移，abort


class ApplyOutcome(enum.Enum):
    """单次 apply 的结果。"""
    APPLIED = "applied"      # 成功应用
    SKIPPED = "skipped"      # 已打补丁，跳过
    ABORTED = "aborted"      # 失败（drift / apply 失败 / 回验失败）


@dataclasses.dataclass
class PatchResult:
    """单个补丁的处理结果。"""
    spec: PatchSpec
    state: FileState
    outcome: ApplyOutcome
    message: str = ""


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def load_manifest(repo_root: Optional[pathlib.Path] = None) -> tuple[str, list[PatchSpec]]:
    """读 oemer-0.1.8.checksums.json → (oemer_version, [PatchSpec...])。

    Args:
        repo_root: Pudu 仓库根目录。None 时用模块级 REPO_ROOT。

    Returns:
        (oemer_version, patches) —— oemer 版本字符串与补丁规格列表。

    Raises:
        FileNotFoundError: checksums.json 不存在。
        KeyError / ValueError: manifest 格式错误。
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    manifest_path = root / "third_party" / "oemer-patches" / "oemer-0.1.8.checksums.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"checksums manifest 不存在: {manifest_path}\n"
            f"请确保你在 Pudu 仓库根目录下运行，或检查 third_party/oemer-patches/ 目录。"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    oemer_ver = manifest["oemer_version"]

    patches: list[PatchSpec] = []
    for file_name, info in manifest["files"].items():
        patches.append(PatchSpec(
            file=file_name,
            patch_file=info["patch_file"],
            original_sha256_lf=info["original_sha256_lf"],
            patched_sha256_lf=info["patched_sha256_lf"],
        ))

    return oemer_ver, patches


def locate_oemer_pkg() -> pathlib.Path:
    """import oemer; return Path(oemer.__file__).parent。

    失败时抛带明确指引的 RuntimeError。

    Returns:
        oemer 包目录的绝对路径。

    Raises:
        RuntimeError: oemer 未安装或无法 import。
    """
    try:
        import oemer  # type: ignore
        return pathlib.Path(oemer.__file__).resolve().parent
    except ImportError as exc:
        raise RuntimeError(
            "无法 import oemer，请先安装 oemer：\n"
            f"  {sys.executable} -m pip install oemer=={OEMER_VERSION}\n"
            f"  原始错误: {exc}"
        ) from exc


def oemer_version() -> str:
    """importlib.metadata.version('oemer')。

    Returns:
        已安装的 oemer 版本字符串。

    Raises:
        RuntimeError: oemer 未安装（metadata 不可用）。
    """
    try:
        return _pkg_version("oemer")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"无法获取 oemer 版本（importlib.metadata 未找到 'oemer' 包）。"
            f"请确认已安装 oemer=={OEMER_VERSION}。"
        ) from exc


def lf_normalized_sha256(path: pathlib.Path) -> str:
    """读 bytes → replace(b'\\r\\n', b'\\n') → sha256。

    行尾无关比较：无论文件是 LF 还是 CRLF，归一化后 sha 一致。

    Args:
        path: 文件路径。

    Returns:
        LF 归一化后的 sha256 十六进制字符串。
    """
    raw = path.read_bytes()
    norm = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(norm).hexdigest()


def decide_state(spec: PatchSpec, pkg: pathlib.Path) -> FileState:
    """三态判定（主判据 = LF 归一化 sha256）。

    判定逻辑：
      - sha == patched_lf → ALREADY_PATCHED（幂等跳过）
      - sha == original_lf → CLEAN（需要 apply）
      - 其它 → DRIFT（版本漂移，abort）

    Args:
        spec: 补丁规格。
        pkg: oemer 包目录。

    Returns:
        FileState 枚举值。
    """
    target = pkg / spec.file
    if not target.exists():
        # 文件不存在也是一种 drift（oemer 可能已重构目录）
        return FileState.DRIFT

    sha = lf_normalized_sha256(target)
    if sha == spec.patched_sha256_lf:
        return FileState.ALREADY_PATCHED
    elif sha == spec.original_sha256_lf:
        return FileState.CLEAN
    else:
        return FileState.DRIFT


def git_available() -> bool:
    """检测 git 命令是否可用。

    Returns:
        True 如果 `git --version` 成功执行。
    """
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _git_apply(
    patch_path: pathlib.Path,
    cwd: pathlib.Path,
    reverse: bool = False,
    check_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    """执行 git apply 命令（内部辅助函数）。

    Args:
        patch_path: .patch 文件路径。
        cwd: 工作目录（oemer 包目录）。
        reverse: 是否反向 apply（回滚）。
        check_only: 是否只检查不实际 apply。

    Returns:
        subprocess.CompletedProcess。
    """
    cmd = list(GIT_APPLY_OPTS)
    if check_only:
        cmd.append("--check")
    if reverse:
        cmd.append("--reverse")
    cmd.extend(["-p1", str(patch_path)])

    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )


def apply_patch(
    spec: PatchSpec,
    pkg: pathlib.Path,
    patches_dir: pathlib.Path,
    check_only: bool = False,
) -> PatchResult:
    """三态判定 → APPLY/SKIP/ABORT。

    流程：
      1. decide_state → ALREADY_PATCHED → SKIP
      2. decide_state → DRIFT → ABORT（打印重生成指引）
      3. decide_state → CLEAN →
         a. git apply --check（二次 sanity，失败则 ABORT）
         b. git apply -p1（实际应用）
         c. 回验 lf sha == patched_lf，失败则 git apply --reverse 回滚 → ABORT
         d. 成功 → APPLIED
      4. check_only=True 时，只判定不实际 apply（CLEAN 报告为「需要 apply」但不执行）

    Args:
        spec: 补丁规格。
        pkg: oemer 包目录。
        patches_dir: patch 文件所在目录。
        check_only: 只检查不修改文件。

    Returns:
        PatchResult（spec + state + outcome + message）。
    """
    patch_path = patches_dir / spec.patch_file
    state = decide_state(spec, pkg)

    if state == FileState.ALREADY_PATCHED:
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.SKIPPED,
            message="已打补丁，跳过（幂等）。",
        )

    if state == FileState.DRIFT:
        target = pkg / spec.file
        actual_sha = lf_normalized_sha256(target) if target.exists() else "<file missing>"
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.ABORTED,
            message=(
                f"版本漂移（DRIFT）：文件 {spec.file} 的 LF 归一化 sha256\n"
                f"  实际:   {actual_sha}\n"
                f"  原版:   {spec.original_sha256_lf}\n"
                f"  补丁后: {spec.patched_sha256_lf}\n"
                f"  两者都不匹配 → oemer 可能已升版或文件被手工修改。\n"
                f"  解决方法：\n"
                f"    1. 确认 oemer 版本: python -c \"import importlib.metadata; print(importlib.metadata.version('oemer'))\"\n"
                f"    2. 若版本不是 {OEMER_VERSION}，锁版本: pip install oemer=={OEMER_VERSION}\n"
                f"    3. 重新生成补丁: python tools/_regen_oemer_patches.py\n"
                f"    4. 重新运行: python tools/install_oemer.py"
            ),
        )

    # state == CLEAN → 需要 apply
    if check_only:
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.SKIPPED,
            message="文件为原版（CLEAN），需要打补丁（--check-only 模式未实际应用）。",
        )

    if not patch_path.exists():
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.ABORTED,
            message=f"patch 文件不存在: {patch_path}",
        )

    # 二次 sanity: git apply --check
    check_result = _git_apply(patch_path, pkg, check_only=True)
    if check_result.returncode != 0:
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.ABORTED,
            message=(
                f"git apply --check 失败（patch context 可能不匹配）:\n"
                f"  {check_result.stderr.strip()}\n"
                f"  请重新生成补丁: python tools/_regen_oemer_patches.py"
            ),
        )

    # 实际 apply
    apply_result = _git_apply(patch_path, pkg, reverse=False)
    if apply_result.returncode != 0:
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.ABORTED,
            message=f"git apply 失败:\n  {apply_result.stderr.strip()}",
        )

    # 回验 sha
    target = pkg / spec.file
    applied_sha = lf_normalized_sha256(target)
    if applied_sha != spec.patched_sha256_lf:
        # 回滚
        rollback = _git_apply(patch_path, pkg, reverse=True)
        rollback_status = "成功" if rollback.returncode == 0 else "失败"
        rollback_detail = f": {rollback.stderr.strip()}" if rollback.stderr.strip() else ""
        rollback_msg = f"回滚{rollback_status}{rollback_detail}"
        return PatchResult(
            spec=spec, state=state, outcome=ApplyOutcome.ABORTED,
            message=(
                f"apply 后 sha 校验失败（回验不匹配）:\n"
                f"  期望: {spec.patched_sha256_lf}\n"
                f"  实际: {applied_sha}\n"
                f"  {rollback_msg}\n"
                f"  请重新生成补丁: python tools/_regen_oemer_patches.py"
            ),
        )

    return PatchResult(
        spec=spec, state=state, outcome=ApplyOutcome.APPLIED,
        message="成功应用补丁。",
    )


def ensure_oemer_installed(version: str, py: Optional[str] = None) -> None:
    """若 oemer_version() != version → pip install oemer==version。幂等。

    Args:
        version: 期望的 oemer 版本。
        py: Python 解释器路径（None 时用 sys.executable）。

    Raises:
        RuntimeError: pip install 失败。
    """
    interpreter = py if py is not None else sys.executable
    try:
        current = oemer_version()
    except RuntimeError:
        current = "<not installed>"

    if current == version:
        print(f"[oemer] 版本匹配: {current}，无需安装。")
        return

    print(f"[oemer] 版本不匹配: 当前={current}, 期望={version}，执行 pip install...")
    cmd = [interpreter, "-m", "pip", "install", f"oemer=={version}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"pip install oemer=={version} 失败 (rc={result.returncode}):\n"
            f"{result.stderr}"
        )
    print(f"[oemer] 安装完成: oemer=={version}")


def run(
    repo_root: Optional[pathlib.Path] = None,
    check_only: bool = False,
) -> int:
    """编排：ensure_oemer_installed → 遍历 manifest → apply_patch → 汇总报告。

    Args:
        repo_root: Pudu 仓库根目录。None 时用模块级 REPO_ROOT。
        check_only: 只检查不实际 apply（不改文件）。

    Returns:
        退出码：0 = 全部 APPLIED/SKIPPED；非 0 = 有 ABORTED。
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    patches_dir = root / "third_party" / "oemer-patches"

    # 1. 加载 manifest
    try:
        version, specs = load_manifest(root)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"[oemer-patch] 目标版本: oemer=={version}")
    print(f"[oemer-patch] 补丁数: {len(specs)}")
    print(f"[oemer-patch] 模式: {'检查（--check-only）' if check_only else '应用'}")
    print()

    # 2. 检测 git 可用性
    if not check_only and not git_available():
        print("[ERROR] git 不可用，无法执行 git apply。", file=sys.stderr)
        print("  请确保 git 在 PATH 中，或手动应用补丁。", file=sys.stderr)
        return 1

    # 3. 确保 oemer 已安装且版本正确
    if not check_only:
        try:
            ensure_oemer_installed(version)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    # 4. 定位 oemer 包目录
    try:
        pkg = locate_oemer_pkg()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"[oemer-patch] oemer 包目录: {pkg}")
    print()

    # 5. 遍历补丁
    results: list[PatchResult] = []
    for spec in specs:
        print(f"--- {spec.file} ---")
        result = apply_patch(spec, pkg, patches_dir, check_only=check_only)
        results.append(result)
        state_label = {
            FileState.CLEAN: "CLEAN(原版)",
            FileState.ALREADY_PATCHED: "PATCHED(已打补丁)",
            FileState.DRIFT: "DRIFT(版本漂移)",
        }[result.state]
        outcome_label = {
            ApplyOutcome.APPLIED: "APPLIED",
            ApplyOutcome.SKIPPED: "SKIPPED",
            ApplyOutcome.ABORTED: "ABORTED",
        }[result.outcome]
        print(f"  状态: {state_label}")
        print(f"  结果: {outcome_label}")
        if result.message:
            print(f"  详情: {result.message}")
        print()

    # 6. 汇总报告
    applied = sum(1 for r in results if r.outcome == ApplyOutcome.APPLIED)
    skipped = sum(1 for r in results if r.outcome == ApplyOutcome.SKIPPED)
    aborted = sum(1 for r in results if r.outcome == ApplyOutcome.ABORTED)

    print("=" * 60)
    print(f"[oemer-patch] 汇总: APPLIED={applied}, SKIPPED={skipped}, ABORTED={aborted}")
    print("=" * 60)

    if aborted > 0:
        print(f"\n[oemer-patch] 有 {aborted} 个补丁失败，请按上述指引修复后重试。")
        return 1

    if check_only:
        if applied == 0 and skipped == len(specs):
            print("[oemer-patch] 所有补丁已就位（已打补丁），无需操作。")
        else:
            print(f"[oemer-patch] 有 {len(specs) - skipped} 个文件需要打补丁。")
    else:
        if applied > 0:
            print(f"[oemer-patch] 成功应用 {applied} 个补丁。")
        if skipped > 0:
            print(f"[oemer-patch] {skipped} 个补丁已就位（跳过）。")

    return 0
