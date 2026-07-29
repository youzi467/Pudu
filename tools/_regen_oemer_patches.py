#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer 补丁再生成工具（开发维护用，不进安装链路）

用途：当 oemer 升版或 site-packages 补丁变更时，从 wheel 重新生成 patch 文件并
回填 LF 归一化 sha256 到 checksums.json。

流程：
  1. pip download oemer==<version> --no-deps → 解压取原版文件
  2. 与 site-packages 现版做 difflib.unified_diff → 生成 LF patch
  3. 重算 4 个 LF 归一化 sha256，回填 checksums.json

使用：
  python tools/_regen_oemer_patches.py [--version 0.1.8] [--py <python.exe>]

⚠️ 本脚本仅供维护使用，不参与 install_oemer.py 安装链路。
   详见 docs/oemer-patch-strategy.md §3.5。

依赖：仅 Python 标准库（difflib, hashlib, json, pathlib, subprocess, zipfile, tempfile, sys, argparse）。
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import zipfile


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHES_DIR = REPO_ROOT / "third_party" / "oemer-patches"
CHECKSUMS_FILE = PATCHES_DIR / "oemer-0.1.8.checksums.json"

# 需要生成 patch 的文件列表（相对 oemer 包根）
PATCH_FILES = ["bbox.py", "staffline_extraction.py"]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def lf_normalized_sha256(path: pathlib.Path) -> str:
    """读 bytes → replace(b'\\r\\n', b'\\n') → sha256。行尾无关比较。"""
    raw = path.read_bytes()
    norm = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(norm).hexdigest()


def read_lines_lf(path: pathlib.Path) -> list[str]:
    """读文件，LF 归一化后返回带换行符的行列表。"""
    raw = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    return raw.splitlines(keepends=True)


def locate_oemer_pkg() -> pathlib.Path:
    """定位当前 Python 环境中 oemer 包目录。"""
    try:
        import oemer  # type: ignore
        return pathlib.Path(oemer.__file__).resolve().parent
    except ImportError as exc:
        raise RuntimeError(
            "无法 import oemer，请确保在已安装 oemer 的 venv 中运行本脚本。\n"
            f"  Python: {sys.executable}\n"
            f"  错误: {exc}"
        ) from exc


def download_and_extract_wheel(
    version: str, py: str, dest: pathlib.Path
) -> pathlib.Path:
    """pip download oemer==version --no-deps → 解压 wheel → 返回 oemer 包目录。"""
    dest.mkdir(parents=True, exist_ok=True)
    whl_dir = dest / "whl"

    # pip download
    cmd = [
        py, "-m", "pip", "download",
        f"oemer=={version}", "--no-deps",
        "-d", str(dest / "download"),
    ]
    print(f"[regen] 下载 wheel: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"pip download 失败 (rc={result.returncode}):\n{result.stderr}"
        )

    # 找 wheel 文件
    whl_files = list((dest / "download").glob("oemer-*.whl"))
    if not whl_files:
        raise RuntimeError(f"未找到 oemer wheel 文件于 {dest / 'download'}")
    whl_path = whl_files[0]
    print(f"[regen] wheel: {whl_path.name}")

    # 解压
    if whl_dir.exists():
        import shutil
        shutil.rmtree(whl_dir)
    whl_dir.mkdir(parents=True)
    with zipfile.ZipFile(whl_path, "r") as zf:
        zf.extractall(whl_dir)

    oemer_pkg = whl_dir / "oemer"
    if not oemer_pkg.is_dir():
        raise RuntimeError(f"wheel 解压后未找到 oemer 包目录: {oemer_pkg}")
    return oemer_pkg


def generate_patch(
    orig_path: pathlib.Path, patched_path: pathlib.Path, filename: str
) -> str:
    """用 difflib.unified_diff 生成 patch 文本（LF 行尾）。"""
    orig_lines = read_lines_lf(orig_path)
    patched_lines = read_lines_lf(patched_path)
    diff = difflib.unified_diff(
        orig_lines,
        patched_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="oemer 补丁再生成工具（开发维护用）"
    )
    parser.add_argument(
        "--version", default="0.1.8",
        help="oemer 版本（默认 0.1.8）"
    )
    parser.add_argument(
        "--py", default=sys.executable,
        help="Python 解释器路径（默认当前解释器）"
    )
    args = parser.parse_args(argv)

    print(f"[regen] 版本: {args.version}")
    print(f"[regen] Python: {args.py}")
    print(f"[regen] patches_dir: {PATCHES_DIR}")

    # 1. 定位 site-packages oemer 包
    site_pkg = locate_oemer_pkg()
    print(f"[regen] site-packages oemer: {site_pkg}")

    # 2. 下载并解压 wheel 取原版
    with tempfile.TemporaryDirectory(prefix="oemer-regen-") as tmpdir:
        orig_pkg = download_and_extract_wheel(
            args.version, args.py, pathlib.Path(tmpdir)
        )
        print(f"[regen] wheel 原版 oemer: {orig_pkg}")

        # 3. 逐文件生成 patch + 计算 sha
        results: dict[str, dict] = {}
        for fn in PATCH_FILES:
            orig_path = orig_pkg / fn
            patched_path = site_pkg / fn

            if not orig_path.exists():
                print(f"[regen] 警告: wheel 中无 {fn}，跳过")
                continue
            if not patched_path.exists():
                print(f"[regen] 警告: site-packages 中无 {fn}，跳过")
                continue

            orig_lf = lf_normalized_sha256(orig_path)
            patched_lf = lf_normalized_sha256(patched_path)
            patch_text = generate_patch(orig_path, patched_path, fn)

            # 写 patch 文件（强制 LF）
            patch_file = PATCHES_DIR / f"{fn}.patch"
            patch_file.write_bytes(patch_text.encode("utf-8"))
            print(f"[regen] 写入 {patch_file.name} ({len(patch_text)} bytes)")

            results[fn] = {
                "patch_file": f"{fn}.patch",
                "original_sha256_lf": orig_lf,
                "patched_sha256_lf": patched_lf,
            }

            print(f"  original_lf: {orig_lf}")
            print(f"  patched_lf:  {patched_lf}")

        # 4. 回填 checksums.json（保留 points 清单，只更新 sha）
        manifest = json.loads(CHECKSUMS_FILE.read_text(encoding="utf-8"))
        manifest["oemer_version"] = args.version

        for fn, info in results.items():
            if fn in manifest["files"]:
                manifest["files"][fn]["original_sha256_lf"] = info["original_sha256_lf"]
                manifest["files"][fn]["patched_sha256_lf"] = info["patched_sha256_lf"]
                manifest["files"][fn]["patch_file"] = info["patch_file"]
            else:
                manifest["files"][fn] = {
                    "patch_file": info["patch_file"],
                    "original_sha256_lf": info["original_sha256_lf"],
                    "patched_sha256_lf": info["patched_sha256_lf"],
                    "points": [],
                }

        CHECKSUMS_FILE.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[regen] 回填 checksums: {CHECKSUMS_FILE}")

    # 5. 验证生成的 patch 可 apply 到干净原版
    print("\n[regen] 验证 patch 可 apply...")
    with tempfile.TemporaryDirectory(prefix="oemer-verify-") as tmpdir:
        orig_pkg = download_and_extract_wheel(
            args.version, args.py, pathlib.Path(tmpdir)
        )
        for fn in PATCH_FILES:
            patch_file = PATCHES_DIR / f"{fn}.patch"
            if not patch_file.exists():
                continue
            cmd = [
                "git", "-c", "core.autocrlf=false", "apply",
                "-p1", str(patch_file),
            ]
            result = subprocess.run(
                cmd, cwd=str(orig_pkg),
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"  [FAIL] {fn}: git apply 失败\n{result.stderr}")
                return 1

            # 校验 apply 后 sha == patched_lf
            applied_sha = lf_normalized_sha256(orig_pkg / fn)
            expected_sha = results[fn]["patched_sha256_lf"]
            if applied_sha != expected_sha:
                print(f"  [FAIL] {fn}: sha 不匹配\n  期望: {expected_sha}\n  实际: {applied_sha}")
                return 1
            print(f"  [OK] {fn}: apply + sha 校验通过")

    print("\n[regen] 全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
