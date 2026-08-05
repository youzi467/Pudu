# -*- coding: utf-8 -*-
"""谱渡 Pudu · P1-2 轨 B 退化增广语料生成器（``omr_degrade_corpus.py``）。

背景（设计 §0 核心洞察 2 / §8-U3）
--------------------------------
现有 6 页 concerto 是**出版级干净扫描件**。在干净图上测图像增强，结论天然
趋向「无收益甚至负收益」——那不证明预处理无用，只证明**语料与被测能力不匹配**
（预处理的设计目标是救**拍照 / 低对比 / 阴影**退化图）。因此 P1-2 分两轨：

* 轨 A（现有 6 页）：回答「会不会伤害干净图」（守护性，决定能否默认开）。
* **轨 B（本脚本，合成退化增广）：回答「在困难图上能不能救」（收益性，
  决定推荐哪套 preset）**。

本脚本对同 6 页做**可控、可复现**的 5 种退化（gt 保持不变），把 6 页扩成
``6 × (1 + 5) = 36`` 页困难语料，供 A/B 驱动在轨 B 语料上重跑。

5 种退化（与设计 §8-U3 一致）
----------------------------
1. ``gblur``   高斯模糊（核 5×5，σ=1.5）——模拟失焦 / 扫描虚。
2. ``jpeg40``  JPEG 质量 40 重编码——模拟有损压缩伪影。
3. ``shadow``  侧向阴影——模拟扫描阴影 / 拍照遮挡。
4. ``rot15``   +1.5° 旋转——模拟摆放倾斜（与 oemer 内部 dewarp 形成对照）。
5. ``lowc``    对比度压缩（围绕中灰压到 0.6）——模拟低对比扫描件。

命名与可发现性（SK-3）
---------------------
输出的退化语料**沿用 harness 约定①**——``<stem>.jpg`` + ``<stem>.gt.musicxml``
同名配对，因此 A/B 驱动 ``discover_pairs`` 可直接消费，无需任何特殊分支：

* 原页：``<base>.jpg`` + ``<base>.gt.musicxml``（gt 原样拷贝）。
* 退化页：``<base>__<deg>.jpg`` + ``<base>__<deg>.gt.musicxml``（gt 原样拷贝）。

gt **永远不变**——退化增广只动图像侧，参照系保持权威。

依赖
----
本脚本是 P1-2 工具链里**唯一**顶层 ``import cv2 / numpy`` 的文件（设计 §9：
其余纯函数层/编排层刻意零重依赖）。请在装有 ``opencv-python`` 的 oemer venv
中运行；沙箱纯函数单测**不** import 本文件，故不受影响。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

import cv2  # noqa: E402  —— 全工具链唯一顶层 cv2 import（U3 / 设计 §9）
import numpy as np  # noqa: E402

# —— 5 种退化 + 各自的中文标签（进产物清单与日志）——
DEGRADATIONS = ("gblur", "jpeg40", "shadow", "rot15", "lowc")
DEGRADATION_LABELS = {
    "gblur": "高斯模糊(σ=1.5)",
    "jpeg40": "JPEG质量40重编码",
    "shadow": "侧向阴影",
    "rot15": "+1.5°旋转",
    "lowc": "对比度压缩(0.6)",
}

GT_SUFFIX = ".gt.musicxml"
OUT_PREFIX = "__"  # 退化页 stem = <base>__<deg>


# ----------------------------------------------------------------------
# 退化原语（输入/输出均为 BGR numpy 数组，与 cv2.imread 一致）
# ----------------------------------------------------------------------

def deg_gblur(img: np.ndarray) -> np.ndarray:
    """高斯模糊：核 5×5，σ=1.5。"""
    return cv2.GaussianBlur(img, (5, 5), 1.5)


def deg_jpeg40(img: np.ndarray) -> np.ndarray:
    """JPEG 质量 40 重编码（经内存缓冲，模拟有损压缩伪影）。"""
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
    if not ok:
        raise RuntimeError("JPEG 重编码失败")
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def deg_shadow(img: np.ndarray) -> np.ndarray:
    """侧向阴影：叠加一道从左上到右下的线性暗化梯度（最低压到 55%）。"""
    h, w = img.shape[:2]
    # 梯度系数：0.55（暗）-> 1.0（亮），沿对角线
    gx = np.linspace(0.55, 1.0, w, dtype=np.float32)
    gy = np.linspace(0.55, 1.0, h, dtype=np.float32)
    grad = np.minimum(gx.reshape(1, w), gy.reshape(h, 1))
    grad = np.repeat(grad.reshape(h, w, 1), 3, axis=2)
    return np.clip(img.astype(np.float32) * grad, 0, 255).astype(img.dtype)


def deg_rot15(img: np.ndarray) -> np.ndarray:
    """+1.5° 旋转，边缘用白底填充（避免黑边被误判为音符）。"""
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    rot = cv2.getRotationMatrix2D(center, 1.5, 1.0)
    return cv2.warpAffine(img, rot, (w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(255, 255, 255))


def deg_lowc(img: np.ndarray) -> np.ndarray:
    """对比度压缩：围绕中灰(128)压到 0.6 倍。"""
    return np.clip((img.astype(np.float32) - 128.0) * 0.6 + 128.0,
                   0, 255).astype(img.dtype)


_DEG_FUNCS = {
    "gblur": deg_gblur,
    "jpeg40": deg_jpeg40,
    "shadow": deg_shadow,
    "rot15": deg_rot15,
    "lowc": deg_lowc,
}


# ----------------------------------------------------------------------
# 语料发现与生成
# ----------------------------------------------------------------------

def discover_pairs(corpus_dir: str) -> list:
    """按 harness 约定①发现 ``<base>.jpg`` + ``<base>.gt.musicxml`` 同名对。"""
    if not os.path.isdir(corpus_dir):
        raise FileNotFoundError("语料目录不存在: %s" % corpus_dir)
    bases = []
    for name in sorted(os.listdir(corpus_dir)):
        if not name.endswith(GT_SUFFIX):
            continue
        base = name[: -len(GT_SUFFIX)]
        jpg = base + ".jpg"
        if os.path.isfile(os.path.join(corpus_dir, jpg)):
            bases.append(base)
        else:
            print("[warn] 缺少同名图像，跳过: %s" % name, file=sys.stderr)
    return bases


def augment_one(src_jpg: str, deg: str) -> np.ndarray:
    """对单张图施加指定退化，返回退化后的 BGR 数组。"""
    img = cv2.imread(src_jpg, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("无法读取图像: %s" % src_jpg)
    return _DEG_FUNCS[deg](img)


def generate(in_dir: str, out_dir: str, degradations=DEGRADATIONS,
             keep_original=True, dry_run=False, verbose=True):
    """生成退化增广语料。

    Args:
        in_dir: 源语料目录（干净图 + gt）。
        out_dir: 输出目录（不存在则创建）。
        degradations: 要施加的退化种类元组。
        keep_original: 是否保留原页（设计默认 6×(1+5)=36，含原页）。
        dry_run: 只打印将要生成的清单，不读写图像。
        verbose: 是否打印进度。

    Returns:
        Tuple[int, int]: (生成的 image 文件数, 生成的 gt 文件数)。
    """
    bases = discover_pairs(in_dir)
    if not bases:
        raise RuntimeError("在 %s 未发现任何 (jpg + gt.musicxml) 配对" % in_dir)
    if dry_run:
        for base in bases:
            plan = []
            if keep_original:
                plan.append(base + ".jpg (原页)")
            for deg in degradations:
                plan.append("%s%s%s.jpg (%s)"
                            % (base, OUT_PREFIX, deg,
                               DEGRADATION_LABELS.get(deg, deg)))
            print("[dry-run] %s ->\n  %s" % (base, "\n  ".join(plan)))
        return (0, 0)

    os.makedirs(out_dir, exist_ok=True)
    n_img = n_gt = 0
    for base in bases:
        src_jpg = os.path.join(in_dir, base + ".jpg")
        src_gt = os.path.join(in_dir, base + GT_SUFFIX)

        # —— 原页：gt 原样拷贝 ——
        if keep_original:
            shutil.copyfile(src_jpg, os.path.join(out_dir, base + ".jpg"))
            shutil.copyfile(src_gt, os.path.join(out_dir, base + GT_SUFFIX))
            n_img += 1
            n_gt += 1

        # —— 退化页：图像施加退化，gt 原样拷贝 ——
        for deg in degradations:
            out_base = base + OUT_PREFIX + deg
            out_jpg = os.path.join(out_dir, out_base + ".jpg")
            out_gt = os.path.join(out_dir, out_base + GT_SUFFIX)
            degraded = augment_one(src_jpg, deg)
            cv2.imwrite(out_jpg, degraded)
            shutil.copyfile(src_gt, out_gt)  # gt 永不变
            n_img += 1
            n_gt += 1
            if verbose:
                print("[ok] %s (%s)" % (out_base, DEGRADATION_LABELS.get(deg, deg)))

    if verbose:
        per_page = (1 + len(degradations)) if keep_original else len(degradations)
        print("[done] 源 %d 页 × %d 变体/页 -> 输出 %d 图 / %d gt（含原页=%s）"
              % (len(bases), per_page, n_img, n_gt, keep_original))
    return (n_img, n_gt)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="P1-2 轨 B 退化增广语料生成器（合成 5 种退化，gt 不变）")
    p.add_argument("--in", dest="in_dir", required=True,
                   help="源语料目录（干净 .jpg + .gt.musicxml）")
    p.add_argument("--out", dest="out_dir", required=True,
                   help="输出退化语料目录")
    p.add_argument("--degradations", nargs="+", default=list(DEGRADATIONS),
                   choices=DEGRADATIONS,
                   help="要施加的退化种类（默认全部 5 种）")
    p.add_argument("--no-original", dest="keep_original", action="store_false",
                   help="不保留原页（仅输出退化页）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印将生成的清单，不读写图像")
    p.add_argument("--quiet", action="store_true", help="减少输出")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        generate(in_dir=args.in_dir, out_dir=args.out_dir,
                 degradations=tuple(args.degradations),
                 keep_original=args.keep_original,
                 dry_run=args.dry_run, verbose=not args.quiet)
    except (FileNotFoundError, RuntimeError) as exc:
        print("[error] %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
