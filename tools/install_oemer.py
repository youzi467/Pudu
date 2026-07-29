#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer 补丁安装入口

用法：
  python tools/install_oemer.py              # 安装 oemer + 应用全部补丁
  python tools/install_oemer.py --check-only # 只检查不修改文件

退出码：
  0 = 全部 APPLIED/SKIPPED（成功或幂等）
  非 0 = 有 ABORTED（版本漂移 / apply 失败 / 回验失败）

详见 docs/oemer-patch-strategy.md。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

# 确保能 import 同目录的 oemer_patch_lib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from oemer_patch_lib import run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="谱渡 Pudu · oemer site-packages 补丁安装器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python tools/install_oemer.py              # 安装 + 打补丁\n"
            "  python tools/install_oemer.py --check-only # 只检查不修改\n"
            "\n"
            "退出码: 0=成功/幂等, 非0=有失败\n"
            "\n"
            "详见 docs/oemer-patch-strategy.md"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        default=False,
        help="只检查补丁状态，不实际应用（不改任何文件）。",
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Pudu 仓库根目录（默认自动检测）。",
    )
    args = parser.parse_args(argv)

    repo_root: pathlib.Path | None = None
    if args.repo_root:
        repo_root = pathlib.Path(args.repo_root).resolve()

    return run(repo_root=repo_root, check_only=args.check_only)


if __name__ == "__main__":
    sys.exit(main())
