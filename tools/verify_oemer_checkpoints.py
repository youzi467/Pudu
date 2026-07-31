#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer 模型权重（checkpoints）完整性校验工具

背景（真实踩坑）：
  oemer 0.1.8 首次运行时会从 GitHub Releases 自动下载 4 个模型权重到
  ``site-packages/oemer/checkpoints/`` 下。但 oemer 的 ``ete.py`` 判断
  “权重是否就绪”**只检查 ``checkpoints/unet_big/model.onnx`` 是否存在**，
  既不校验大小也不校验其余 3 个文件。实际下载常被网络中断/进程回收打断，
  留下**残片**（例如 ``seg_net/model.onnx`` 只下了 1,386,822 字节，而完整
  应为 38,448,467 字节，仅 3.6%）。此时 oemer 会误判“权重已齐” → 跳过下载
  → 推理阶段加载残片崩溃，且报错信息完全无法指向真正原因，极难排查。

本工具独立于 oemer，可在任何时候运行，按**预期字节数逐一对账**，明确报出
「完整 / 残片（含完成百分比）/ 超大 / 缺失」，并给出可直接复制执行的
``curl`` 续传修复命令。

用法：
  python tools/verify_oemer_checkpoints.py
  python tools/verify_oemer_checkpoints.py --checkpoints <dir>
  python tools/verify_oemer_checkpoints.py --python <venv_python.exe>
  python tools/verify_oemer_checkpoints.py --json

环境变量：
  PUDU_OEMER_CHECKPOINTS  显式指定 checkpoints 目录
  PUDU_OMR_PYTHON         指定装有 oemer 的解释器（用于推断目录）

目录定位为**严格模式**：一旦通过 ``--checkpoints`` 或 ``PUDU_OEMER_CHECKPOINTS``
显式指定，该目录必须存在，否则直接报错退出（退出码 2），**不会**静默回落到
默认 venv 路径——避免用户拼错路径时校验了另一个目录却毫不知情。只有在未显式
指定时，才会依次推断解释器路径 / 当前进程 oemer / 默认 venv 兜底。

退出码：
  0 = 4 个权重全部完整
  1 = 存在 残片 / 缺失 / 超大（校验不通过）
  2 = 使用性错误（无法定位 checkpoints 目录）

约束：纯标准库实现，不引入第三方依赖，不联网。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# oemer 权重下载源基址（GitHub Releases 的 checkpoints tag）。
DOWNLOAD_BASE_URL = "https://github.com/BreezeWhite/oemer/releases/download/checkpoints"

# ---------------------------------------------------------------------------
# 权重期望表
#
# 数据来源：oemer 0.1.8 对应的 GitHub Releases 资产，实测 HTTP HEAD 返回的
# Content-Length（精确字节数）。升级 oemer 版本时**集中修改此表**即可。
#
# 每项字段：
#   remote : 远端资产文件名（拼在 DOWNLOAD_BASE_URL 之后）
#   path   : 落盘相对路径（相对 checkpoints/ 目录，用 POSIX 斜杠书写）
#   size   : 预期精确字节数
#
# 注意：``checkpoints/*/arch.json`` 与 ``metadata.pkl`` 是随 oemer 包分发的
# 脚手架文件（非下载权重），**不在校验范围**，其存在与否不影响判定。
# ---------------------------------------------------------------------------
CHECKPOINT_FILES = (
    {"remote": "1st_model.onnx", "path": "unet_big/model.onnx", "size": 70767752},
    {"remote": "1st_weights.h5", "path": "unet_big/weights.h5", "size": 70977288},
    {"remote": "2nd_model.onnx", "path": "seg_net/model.onnx", "size": 38448467},
    {"remote": "2nd_weights.h5", "path": "seg_net/weights.h5", "size": 38570576},
)

# 状态常量（全 ASCII，避免 Windows GBK 控制台 UnicodeEncodeError）。
STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_OVERSIZE = "OVERSIZE"
STATUS_MISSING = "MISSING"

# checkpoints 目录定位结果的原因码，供调用方打印精确的失败文案。
REASON_OK = "ok"                              # 成功定位
REASON_EXPLICIT_MISSING = "explicit_missing"  # --checkpoints 指定的目录不存在
REASON_ENV_MISSING = "env_missing"            # 环境变量指定的目录不存在
REASON_NOT_FOUND = "not_found"                # 全部推断候选均落空

# 兜底默认 checkpoints 路径（WorkBuddy 托管 venv），与 C++ 侧
# ``resolveOmerPython()`` 的选址思路保持一致。
DEFAULT_CHECKPOINTS_SUBPATH = os.path.join(
    ".workbuddy", "binaries", "python", "envs", "default",
    "Lib", "site-packages", "oemer", "checkpoints",
)


def _oemer_checkpoints_from_interpreter(python_exe: str) -> str | None:
    """用子进程询问指定解释器中 oemer 的 checkpoints 目录。

    Args:
        python_exe: 解释器可执行文件路径。

    Returns:
        checkpoints 目录绝对路径；解释器不可用 / 未装 oemer 时返回 ``None``。
    """
    if not python_exe:
        return None
    code = "import oemer, os; print(os.path.dirname(oemer.__file__))"
    try:
        proc = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    pkg_dir = (proc.stdout or "").strip().splitlines()
    if not pkg_dir:
        return None
    return os.path.join(pkg_dir[-1].strip(), "checkpoints")


def _oemer_checkpoints_from_current_process() -> str | None:
    """在当前解释器内 ``import oemer`` 推断 checkpoints 目录。

    Returns:
        checkpoints 目录路径；当前解释器未装 oemer 时返回 ``None``。
    """
    try:
        import oemer  # noqa: F401  # 仅用于定位安装路径
    except Exception:
        return None
    pkg_file = getattr(oemer, "__file__", None)
    if not pkg_file:
        return None
    return os.path.join(os.path.dirname(pkg_file), "checkpoints")


def default_checkpoints_path() -> str:
    """返回兜底默认 checkpoints 路径（基于用户主目录拼接，跨平台安全）。"""
    return os.path.join(os.path.expanduser("~"), DEFAULT_CHECKPOINTS_SUBPATH)


def _resolve_strict_candidate(
    raw: str, tried: list[str], fail_reason: str
) -> tuple[str | None, list[str], str]:
    """处理一个**严格模式**候选（显式指定的目录）。

    严格模式的承诺是：用户一旦显式指定，就必须能用，否则立即失败，绝不
    静默回落。因此这里只有"成功"与"失败"两种出口，没有"跳过"。

    空字符串（或纯空白）被视为**显式指定了一个非法值**而非"未指定"——
    注意不能对其调用 ``os.path.abspath``，否则会被解析成当前工作目录，
    导致错误信息指向一个用户根本没提过的路径。故此处原样记入 ``tried``，
    由调用方据此打印"为空字符串"的精确文案。

    Args:
        raw: 用户给出的原始字符串（命令行参数或环境变量取值）。
        tried: 已尝试路径列表，就地追加。
        fail_reason: 失败时返回的原因码。

    Returns:
        与 :func:`resolve_checkpoints_dir` 相同的三元组。
    """
    if not raw.strip():
        # 原样记录，避免 abspath("") 变成 cwd 而误导用户。
        tried.append(raw)
        return None, tried, fail_reason

    path = os.path.abspath(os.path.expanduser(raw))
    tried.append(path)
    if os.path.isdir(path):
        return path, tried, REASON_OK
    # 路径不存在、或存在但不是目录（如指向了一个文件），均为严格失败。
    return None, tried, fail_reason


def describe_invalid_path(given: str) -> str:
    """把一个非法的显式路径描述成精确的中文短语。

    区分三种情形，避免"指向文件"或"空串"被笼统报成"目录不存在"：

    * 空字符串 / 纯空白 -> ``指定的目录为空字符串``
    * 路径存在但不是目录 -> ``不是有效目录（路径存在但不是目录）: <path>``
    * 其余（真的不存在） -> ``指定的目录不存在: <path>``

    Args:
        given: 记录在 ``tried`` 中的原始值或绝对路径。

    Returns:
        可直接拼接在 ``--checkpoints`` / 环境变量名之后的描述短语。
    """
    if not given.strip():
        return "指定的目录为空字符串"
    if os.path.exists(given) and not os.path.isdir(given):
        return "不是有效目录（路径存在但不是目录）: %s" % given
    return "指定的目录不存在: %s" % given


def resolve_checkpoints_dir(
    explicit: str | None = None,
    python_exe: str | None = None,
    env: dict | None = None,
) -> tuple[str | None, list[str], str]:
    """按优先级定位 checkpoints 目录。

    优先级：
      1. ``--checkpoints`` 显式指定；            <- 严格模式
      2. 环境变量 ``PUDU_OEMER_CHECKPOINTS``；   <- 严格模式
      3. ``--python`` / 环境变量 ``PUDU_OMR_PYTHON`` 指定的解释器推断；
      4. 当前解释器 ``import oemer`` 推断；
      5. 兜底默认 venv 路径。

    定位语义分两段：

    * **第 1/2 级是严格模式**——用户一旦显式指定（命令行参数或环境变量），
      该目录就**必须是一个存在的目录**；否则立即失败返回，**绝不**静默回落
      到后续推断候选。否则用户拼错路径时会"莫名其妙"校验到默认 venv 而不
      自知。失败涵盖三种情形：路径不存在、路径存在但不是目录、取值为空串。
    * **第 3/4/5 级是推断回落**——用户没有明确指定时才逐个尝试，命中第一个
      **存在的目录**即返回，全部落空才失败。

    "是否显式指定"以 ``is not None`` 判定而非真值判定：``--checkpoints ""``
    与 ``PUDU_OEMER_CHECKPOINTS=""`` 都算**指定了一个非法值**（严格失败），
    只有参数为 ``None`` / 环境变量未设置才算"未指定"（继续推断）。

    Args:
        explicit: 命令行显式指定的目录；``None`` 表示未指定，空串表示指定
            了非法值。
        python_exe: 命令行显式指定的解释器路径，可为 ``None``。
        env: 环境变量字典，默认取 ``os.environ``。

    Returns:
        ``(checkpoints_dir, tried, reason)`` 三元组：

        * ``checkpoints_dir``：命中的目录，失败时为 ``None``；
        * ``tried``：已尝试过的候选路径列表（用于报错提示）；
        * ``reason``：结果原因码，取值为 :data:`REASON_OK` /
          :data:`REASON_EXPLICIT_MISSING` / :data:`REASON_ENV_MISSING` /
          :data:`REASON_NOT_FOUND`，供调用方打印精确的错误文案。
    """
    environ = os.environ if env is None else env
    tried: list[str] = []

    # --- 第 1 级：命令行显式指定（严格模式，非法即失败，不回落）---
    # 用 ``is not None`` 而非真值判断：空串是"指定了非法值"，不是"未指定"。
    if explicit is not None:
        return _resolve_strict_candidate(explicit, tried, REASON_EXPLICIT_MISSING)

    # --- 第 2 级：环境变量指定（严格模式，非法即失败，不回落）---
    # 未设置该变量时 get 返回 None -> 继续推断；设置为空串则严格失败。
    env_dir = environ.get("PUDU_OEMER_CHECKPOINTS")
    if env_dir is not None:
        return _resolve_strict_candidate(env_dir, tried, REASON_ENV_MISSING)

    # --- 第 3/4/5 级：推断回落（命中第一个存在的目录即用）---
    candidates: list[str] = []

    interp = python_exe or environ.get("PUDU_OMR_PYTHON")
    if interp:
        inferred = _oemer_checkpoints_from_interpreter(os.path.expanduser(interp))
        if inferred:
            candidates.append(os.path.abspath(inferred))

    from_current = _oemer_checkpoints_from_current_process()
    if from_current:
        candidates.append(os.path.abspath(from_current))

    candidates.append(os.path.abspath(default_checkpoints_path()))

    for cand in candidates:
        if cand in tried:
            continue
        tried.append(cand)
        if os.path.isdir(cand):
            return cand, tried, REASON_OK

    return None, tried, REASON_NOT_FOUND


def verify_checkpoints(checkpoints_dir: str, expected=CHECKPOINT_FILES) -> dict:
    """逐一对账 checkpoints 目录下的权重文件（纯函数，不打印、不退出）。

    Args:
        checkpoints_dir: checkpoints 目录路径。
        expected: 期望表，默认为 :data:`CHECKPOINT_FILES`；单测可注入自定义
            小体积期望表，避免真写 70MB 文件。

    Returns:
        结构化结果字典::

            {
              "checkpoints_dir": str,
              "ok": bool,              # 是否全部 OK
              "total": int,
              "ok_count": int,
              "problem_count": int,
              "files": [
                {"remote", "rel_path", "path", "expected", "actual",
                 "status", "percent", "url"}, ...
              ],
            }

        ``actual`` 在文件缺失时为 ``None``；``percent`` 为完成百分比
        （float，缺失时 0.0，预期大小为 0 时按 100.0 处理）。
    """
    files: list[dict] = []
    ok_count = 0

    for item in expected:
        rel_path = item["path"]
        exp_size = int(item["size"])
        abs_path = os.path.join(checkpoints_dir, *rel_path.split("/"))

        if os.path.isfile(abs_path):
            actual = os.path.getsize(abs_path)
            if actual == exp_size:
                status = STATUS_OK
            elif actual < exp_size:
                status = STATUS_PARTIAL
            else:
                status = STATUS_OVERSIZE
        else:
            actual = None
            status = STATUS_MISSING

        if exp_size > 0:
            percent = round((actual or 0) * 100.0 / exp_size, 1)
        else:
            percent = 100.0 if status == STATUS_OK else 0.0

        if status == STATUS_OK:
            ok_count += 1

        files.append(
            {
                "remote": item["remote"],
                "rel_path": rel_path,
                "path": abs_path,
                "expected": exp_size,
                "actual": actual,
                "status": status,
                "percent": percent,
                "url": "%s/%s" % (DOWNLOAD_BASE_URL, item["remote"]),
            }
        )

    total = len(files)
    return {
        "checkpoints_dir": checkpoints_dir,
        "ok": ok_count == total and total > 0,
        "total": total,
        "ok_count": ok_count,
        "problem_count": total - ok_count,
        "files": files,
    }


def build_fix_commands(result: dict) -> list[str]:
    """为每个非 OK 文件生成可直接复制执行的 curl 修复命令。

    残片（PARTIAL）使用 ``curl -L -C -`` 续传；缺失（MISSING）与超大
    （OVERSIZE）使用 ``curl -L`` 重新下载（超大通常意味着文件损坏或版本
    不符，需覆盖重下）。

    Args:
        result: :func:`verify_checkpoints` 的返回值。

    Returns:
        命令字符串列表；全部 OK 时为空列表。
    """
    commands: list[str] = []
    for info in result.get("files", []):
        status = info["status"]
        if status == STATUS_OK:
            continue
        resume = "-C - " if status == STATUS_PARTIAL else ""
        commands.append(
            'curl -L %s-o "%s" "%s"' % (resume, info["path"], info["url"])
        )
    return commands


def format_report(result: dict) -> str:
    """把校验结果渲染为人类可读的纯 ASCII 标记报告（不含 emoji）。

    Args:
        result: :func:`verify_checkpoints` 的返回值。

    Returns:
        多行报告文本。
    """
    lines: list[str] = []
    lines.append("oemer checkpoints 完整性校验")
    lines.append("目录: %s" % result.get("checkpoints_dir", "<unknown>"))
    lines.append("-" * 72)

    for info in result.get("files", []):
        status = info["status"]
        rel = info["rel_path"]
        exp = info["expected"]
        act = info["actual"]
        if status == STATUS_OK:
            lines.append("[OK]       %-22s %d 字节" % (rel, exp))
        elif status == STATUS_PARTIAL:
            lines.append(
                "[PARTIAL]  %-22s %d/%d 字节 (%.1f%%) - 残片，下载未完成"
                % (rel, act, exp, info["percent"])
            )
        elif status == STATUS_OVERSIZE:
            lines.append(
                "[OVERSIZE] %-22s %d/%d 字节 - 超出预期，可能损坏或版本不符"
                % (rel, act, exp)
            )
        else:
            lines.append("[MISSING]  %-22s 期望 %d 字节 - 文件不存在" % (rel, exp))

    lines.append("-" * 72)
    lines.append(
        "汇总: 共 %d 个, OK %d 个, 问题 %d 个"
        % (result.get("total", 0), result.get("ok_count", 0), result.get("problem_count", 0))
    )

    if result.get("ok"):
        lines.append("结论: 全部权重完整，oemer 可正常推理。")
    else:
        lines.append("结论: 校验未通过，oemer 会误判『权重已齐』并在推理时崩溃。")
        lines.append("")
        lines.append("修复建议（逐条复制执行，PARTIAL 用 -C - 续传）:")
        for cmd in build_fix_commands(result):
            lines.append("  " + cmd)
        lines.append("")
        lines.append("提示: 若有下载进程正在运行，请等其结束后再重跑本工具。")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """命令行入口：解析参数、定位目录、校验、打印、返回退出码。

    Args:
        argv: 参数列表，默认取 ``sys.argv[1:]``。

    Returns:
        0 = 全部完整；1 = 校验不通过；2 = 无法定位 checkpoints 目录。
    """
    parser = argparse.ArgumentParser(
        description="谱渡 Pudu · oemer 模型权重完整性校验（按预期字节数逐一对账）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python tools/verify_oemer_checkpoints.py\n"
            "  python tools/verify_oemer_checkpoints.py --checkpoints D:/x/oemer/checkpoints\n"
            "  python tools/verify_oemer_checkpoints.py --python C:/venv/Scripts/python.exe\n"
            "  python tools/verify_oemer_checkpoints.py --json\n"
            "\n"
            "退出码: 0=全部完整, 1=残片/缺失/超大, 2=无法定位目录\n"
        ),
    )
    parser.add_argument(
        "--checkpoints",
        type=str,
        default=None,
        help="显式指定 oemer checkpoints 目录（最高优先级）。",
    )
    parser.add_argument(
        "--python",
        dest="python_exe",
        type=str,
        default=None,
        help="装有 oemer 的解释器路径，用于推断 checkpoints 目录。",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        default=False,
        help="以 JSON 格式输出结果（便于程序消费）。",
    )
    args = parser.parse_args(argv)

    checkpoints_dir, tried, reason = resolve_checkpoints_dir(
        explicit=args.checkpoints, python_exe=args.python_exe
    )

    if checkpoints_dir is None:
        # 严格模式失败时 tried 里只有那一个用户指定的路径，直接取用。
        given = tried[0] if tried else "<unknown>"
        if args.as_json:
            if reason == REASON_EXPLICIT_MISSING:
                error = "invalid checkpoints directory specified by --checkpoints"
            elif reason == REASON_ENV_MISSING:
                error = "invalid checkpoints directory specified by PUDU_OEMER_CHECKPOINTS"
            else:
                error = "checkpoints directory not found"
            payload = {
                "ok": False,
                "reason": reason,
                "error": error,
                "tried": tried,
            }
            if reason in (REASON_EXPLICIT_MISSING, REASON_ENV_MISSING):
                payload["detail"] = describe_invalid_path(given)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif reason == REASON_EXPLICIT_MISSING:
            print("[ERROR] --checkpoints %s" % describe_invalid_path(given))
            print("已显式指定目录，不会回落到默认路径。请检查路径拼写是否正确。")
        elif reason == REASON_ENV_MISSING:
            print(
                "[ERROR] 环境变量 PUDU_OEMER_CHECKPOINTS %s"
                % describe_invalid_path(given)
            )
            print("已显式指定目录，不会回落到默认路径。请检查该环境变量的取值。")
        else:
            print("[ERROR] 无法定位 oemer checkpoints 目录。已尝试:")
            for cand in tried:
                print("  - " + cand)
            print("")
            print("请用以下任一方式指定:")
            print("  python tools/verify_oemer_checkpoints.py --checkpoints <目录>")
            print("  python tools/verify_oemer_checkpoints.py --python <装有oemer的python.exe>")
            print("  set PUDU_OEMER_CHECKPOINTS=<目录>   (或 PUDU_OMR_PYTHON=<python.exe>)")
        return 2

    result = verify_checkpoints(checkpoints_dir)

    if args.as_json:
        payload = dict(result)
        payload["fix_commands"] = build_fix_commands(result)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
