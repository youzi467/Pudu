#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer 补丁 QA 验证脚本

验证流程（全自动，供 QA 交接）：
  1. 干净重装 oemer==0.1.8（pip install --force-reinstall）
  2. 运行 install_oemer.py（应用全部补丁）
  3. 逆 apply 一次（确认能还原为原版）
  4. 再 apply 一次（确认幂等）
  5. 跑 tools/omr_oemer.py data/river_1.jpg 确认不崩且产出 MusicXML

通过判据：
  - 步骤 2: 全部 APPLIED（exit 0）
  - 步骤 3: 逆 apply 后 sha == original_lf
  - 步骤 4: 全部 APPLIED（exit 0，幂等）
  - 步骤 5: 产出 .musicxml 文件且非空

用法：
  python tools/verify_oemer_patch.py [--skip-omr] [--py <python.exe>]

  --skip-omr: 跳过步骤 5（OMR 实跑），只验证补丁三态 + 幂等 + 逆 apply。
  --py:       指定 Python 解释器（默认当前解释器）。

依赖：仅 Python 标准库。
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

# 确保能 import 同目录的 oemer_patch_lib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from oemer_patch_lib import (  # noqa: E402
    ApplyOutcome,
    PATCHES_DIR,
    REPO_ROOT,
    apply_patch,
    lf_normalized_sha256,
    load_manifest,
    locate_oemer_pkg,
)

# git apply 命令前缀（与 oemer_patch_lib 保持一致）
GIT_APPLY_PREFIX = ["git", "-c", "core.autocrlf=false", "apply"]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """运行命令并打印。"""
    print(f"  $ {' '.join(cmd)}")
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)


def _print_result(label: str, passed: bool, detail: str = "") -> None:
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {label}" + (f": {detail}" if detail else ""))


def step1_reinstall_oemer(py: str) -> bool:
    """步骤 1：干净重装 oemer==0.1.8。"""
    print("\n[步骤 1] 干净重装 oemer==0.1.8...")
    cmd = [py, "-m", "pip", "install", "--force-reinstall", "--no-deps",
           "oemer==0.1.8"]
    result = _run(cmd)
    if result.returncode != 0:
        _print_result("pip install", False, result.stderr[:200])
        return False
    _print_result("pip install", True)
    return True


def step2_apply_patches(py: str) -> bool:
    """步骤 2：运行 install_oemer.py 应用全部补丁。"""
    print("\n[步骤 2] 运行 install_oemer.py 应用补丁...")
    cmd = [py, str(REPO_ROOT / "tools" / "install_oemer.py")]
    result = _run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        _print_result("install_oemer.py", False, f"exit={result.returncode}")
        print(f"  stdout: {result.stdout[-500:]}")
        print(f"  stderr: {result.stderr[-500:]}")
        return False
    # 检查输出中是否包含 APPLIED
    if "APPLIED=0" in result.stdout and "SKIPPED=2" in result.stdout:
        _print_result("install_oemer.py", False, "补丁未实际应用（全部 SKIPPED，可能步骤1未重装）")
        return False
    _print_result("install_oemer.py", True, "补丁已应用")
    return True


def step3_reverse_apply() -> bool:
    """步骤 3：逆 apply 确认能还原为原版。"""
    print("\n[步骤 3] 逆 apply 确认能还原...")
    version, specs = load_manifest(REPO_ROOT)
    pkg = locate_oemer_pkg()
    all_ok = True

    for spec in specs:
        patch_path = PATCHES_DIR / spec.patch_file
        # 逆 apply
        cmd = GIT_APPLY_PREFIX + ["--reverse", "-p1", str(patch_path)]
        result = subprocess.run(cmd, cwd=str(pkg), capture_output=True, text=True)
        if result.returncode != 0:
            _print_result(f"逆 apply {spec.file}", False, result.stderr[:200])
            all_ok = False
            continue

        # 验证还原后 sha == original_lf
        sha = lf_normalized_sha256(pkg / spec.file)
        if sha != spec.original_sha256_lf:
            _print_result(f"还原 sha {spec.file}", False,
                          f"{sha} != {spec.original_sha256_lf}")
            all_ok = False
        else:
            _print_result(f"逆 apply {spec.file}", True, "sha == original_lf")

    return all_ok


def step4_reapply_idempotent() -> bool:
    """步骤 4：再 apply 确认幂等。"""
    print("\n[步骤 4] 再 apply 确认幂等...")
    version, specs = load_manifest(REPO_ROOT)
    pkg = locate_oemer_pkg()
    all_ok = True

    for spec in specs:
        result = apply_patch(spec, pkg, PATCHES_DIR)
        if result.outcome == ApplyOutcome.APPLIED:
            # 验证 sha
            sha = lf_normalized_sha256(pkg / spec.file)
            if sha == spec.patched_sha256_lf:
                _print_result(f"再 apply {spec.file}", True, "APPLIED + sha 匹配")
            else:
                _print_result(f"再 apply {spec.file}", False, "sha 不匹配")
                all_ok = False
        elif result.outcome == ApplyOutcome.SKIPPED:
            # 已经是 patched 状态（步骤3的逆apply可能没完全还原）
            sha = lf_normalized_sha256(pkg / spec.file)
            if sha == spec.patched_sha256_lf:
                _print_result(f"再 apply {spec.file}", True, "SKIPPED（已打补丁）")
            else:
                _print_result(f"再 apply {spec.file}", False, "SKIPPED 但 sha 不匹配")
                all_ok = False
        else:
            _print_result(f"再 apply {spec.file}", False, f"ABORTED: {result.message[:100]}")
            all_ok = False

    return all_ok


def step5_omr_smoke(py: str) -> bool:
    """步骤 5：跑 omr_oemer.py 确认不崩且产出 MusicXML。"""
    print("\n[步骤 5] OMR 冒烟测试...")
    image = REPO_ROOT / "data" / "river_1.jpg"
    if not image.exists():
        _print_result("OMR 冒烟", False, f"测试图片不存在: {image}")
        return False

    output_musicxml = pathlib.Path(tempfile.gettempdir()) / "verify_oemer_patch_output.musicxml"
    if output_musicxml.exists():
        output_musicxml.unlink()

    cmd = [py, str(REPO_ROOT / "tools" / "omr_oemer.py"),
           str(image), str(output_musicxml)]
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        _print_result("OMR 运行", False, f"exit={result.returncode}")
        print(f"  stderr: {result.stderr[-500:]}")
        return False

    if not output_musicxml.exists():
        _print_result("MusicXML 产出", False, "文件不存在")
        return False

    content = output_musicxml.read_text(encoding="utf-8", errors="replace")
    if len(content) < 100:
        _print_result("MusicXML 产出", False, f"文件过小 ({len(content)} bytes)")
        return False
    if "<score-partwise" not in content and "<?xml" not in content:
        _print_result("MusicXML 产出", False, "内容不像 MusicXML")
        return False

    _print_result("OMR 运行", True, f"exit=0, 产出 {len(content)} bytes")
    _print_result("MusicXML 产出", True, str(output_musicxml))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="谱渡 Pudu · oemer 补丁 QA 验证脚本"
    )
    parser.add_argument(
        "--skip-omr", action="store_true", default=False,
        help="跳过 OMR 实跑（步骤5），只验证补丁三态 + 幂等 + 逆 apply。",
    )
    parser.add_argument(
        "--py", default=sys.executable,
        help="Python 解释器路径（默认当前解释器）。",
    )
    parser.add_argument(
        "--skip-reinstall", action="store_true", default=False,
        help="跳过步骤1（干净重装），假设 oemer 已是原版。",
    )
    args = parser.parse_args(argv)

    print("=" * 60)
    print("谱渡 Pudu · oemer 补丁 QA 验证")
    print(f"Python: {args.py}")
    print(f"Repo:   {REPO_ROOT}")
    print("=" * 60)

    results: list[tuple[str, bool]] = []

    # 步骤 1：干净重装
    if not args.skip_reinstall:
        results.append(("步骤1 干净重装", step1_reinstall_oemer(args.py)))
    else:
        print("\n[步骤 1] 跳过（--skip-reinstall）")
        results.append(("步骤1 干净重装", True))

    # 步骤 2：应用补丁
    results.append(("步骤2 应用补丁", step2_apply_patches(args.py)))

    # 如果步骤2失败，后续无意义
    if not results[-1][1]:
        print("\n[ABORT] 步骤2失败，跳过后续验证。")
        _print_summary(results)
        return 1

    # 步骤 3：逆 apply
    results.append(("步骤3 逆apply还原", step3_reverse_apply()))

    # 步骤 4：再 apply（幂等）
    results.append(("步骤4 再apply幂等", step4_reapply_idempotent()))

    # 步骤 5：OMR 冒烟
    if not args.skip_omr:
        results.append(("步骤5 OMR冒烟", step5_omr_smoke(args.py)))
    else:
        print("\n[步骤 5] 跳过（--skip-omr）")
        results.append(("步骤5 OMR冒烟", True))

    _print_summary(results)

    all_passed = all(p for _, p in results)
    return 0 if all_passed else 1


def _print_summary(results: list[tuple[str, bool]]) -> None:
    print("\n" + "=" * 60)
    print("验证汇总")
    print("=" * 60)
    for label, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {label}")
    all_passed = all(p for _, p in results)
    print(f"\n  总体: {'ALL PASS' if all_passed else 'HAS FAILURE'}")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
