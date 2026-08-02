#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · P0-2 · oemer 预处理透明代理（omr_pipeline）。

定位
----
本脚本是 ``tools/omr_oemer.py`` 的**透明前置代理**：先对输入图做一层可配置的
图像增强，再把增强图（或降级后的原图）交给 ``omr_oemer.py`` 处理。

上游（C++ ``omr_adapter``）在 ``cfg.preprocess == true`` 时把子进程脚本从
``omr_oemer.py`` 换成本文件，其余命令串构造逐字节不变::

    python omr_pipeline.py <input> <output.musicxml>

**omr_oemer.py 零改动**：它完全不知道本文件的存在。

四条不可违反的约束
------------------
1. **透明**：除 input 位置的路径外，转发给 ``omr_oemer.py`` 的 argv
   与用户给本脚本的 argv 顺序/取值完全一致；私有 flag 绝不外泄。
2. **显式 out_path**（R-P0-04 陷阱）：``omr_oemer.py`` 用 *input 的 basename*
   推导产出名与 sidecar 名。若只把 input 换成临时 PNG 而不显式指定输出，
   产物会落到临时目录并改名。故本脚本**永远**按**原始 input** 推导 out_path
   （逻辑与 ``omr_oemer.py:754-765`` 逐字对齐），并作为第 2 位置参数下传。
3. **stdout 纯净**：下游 stdout/stderr 原样透传；本脚本自身的诊断
   **全部走 stderr**（前缀 ``[preprocess]`` / ``[警告][preprocess]``）。
4. **零残留**：临时目录 ``try/finally`` + ``atexit`` 双保险清理；
   并兜底清扫下游可能遗留在 out_dir 的 ``<stem>.pre.musicxml`` /
   ``<stem>.pre.geometry.json``。

退出码
------
====  ==========================================================
 rc   含义
====  ==========================================================
 *    下游 ``omr_oemer.py`` 的退出码（原样透传）
 2    本脚本自身参数错误
 1    输入文件不存在
====  ==========================================================

预处理失败**不改变** rc：降级用原图继续，仅在 stderr 告警。
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# 让本脚本无论从哪个 CWD 启动，都能 import 同目录的 omr_preprocess
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import omr_preprocess  # noqa: E402  - 必须在 sys.path 修正之后

__all__ = [
    "ArgError",
    "PRIVATE_VALUE_FLAGS",
    "PRIVATE_BOOL_FLAGS",
    "DOWNSTREAM_VALUE_FLAGS",
    "DOWNSTREAM_SCRIPT",
    "TEMP_DIR_PREFIX",
    "split_args",
    "parse_args",
    "resolve_out_path",
    "build_downstream_cmd",
    "downstream_script_path",
    "should_preprocess",
    "metrics_sidecar_path",
    "run",
    "main",
]

#: 下游脚本文件名（与本文件同目录）
DOWNSTREAM_SCRIPT: str = "omr_oemer.py"

#: 临时目录前缀（便于人工识别与批量清理）
TEMP_DIR_PREFIX: str = "pudu_omr_pre_"

#: 增强图文件名后缀。用 ``.pre.png`` 而非 ``.png``，避免与 out_dir 里
#: 同 stem 的下游产物撞名（也让兜底清扫有稳定的匹配模式）。
ENHANCED_SUFFIX: str = ".pre.png"

#: **私有·带值** flag：本脚本吸收，绝不转发给下游。
#: 同时支持 ``--x v`` 与 ``--x=v`` 两种写法；缺值 -> rc 2。
PRIVATE_VALUE_FLAGS: Dict[str, str] = {
    "--preprocess-config": "config_path",
    "--preprocess-preset": "preset",
    "--preprocess-metrics": "metrics_path",
}

#: **私有·布尔** flag：本脚本吸收，绝不转发给下游。
PRIVATE_BOOL_FLAGS: Dict[str, str] = {
    "--keep-temp": "keep_temp",
    "--no-preprocess": "no_preprocess",
}

#: **下游·带值** flag：登记它们**只为正确跳过取值 token**
#: （否则 ``--gt path`` 里的 path 会被误当成位置参数），本身原样转发。
DOWNSTREAM_VALUE_FLAGS = frozenset({"--gt"})

_USAGE = (
    "用法: python omr_pipeline.py <input> [<output.musicxml>]\n"
    "      [--preprocess-config <path>] [--preprocess-preset <name>]\n"
    "      [--preprocess-metrics <path>] [--keep-temp] [--no-preprocess]\n"
    "      [--gt <gt_path>] [--f3-geometric] [--no-f3-sidecar] [...]\n"
    "  说明: 除私有 --preprocess-* / --keep-temp / --no-preprocess 外，\n"
    "        所有 flag 原样转发给 tools/omr_oemer.py（顺序不变）。\n"
)


class ArgError(Exception):
    """命令行参数错误（对应退出码 2）。"""


# ---------------------------------------------------------------------------
# stderr 诊断（stdout 全部留给下游）
# ---------------------------------------------------------------------------


def _info(message: str) -> None:
    """输出一条普通诊断到 stderr。"""
    sys.stderr.write(f"[preprocess] {message}\n")


def _warn(message: str) -> None:
    """输出一条告警到 stderr。"""
    sys.stderr.write(f"[警告][preprocess] {message}\n")


# ---------------------------------------------------------------------------
# 临时目录生命周期（try/finally + atexit 双保险）
# ---------------------------------------------------------------------------

_TEMP_DIRS: set = set()
_ATEXIT_HOOKED: bool = False


def _remove_temp_dir(path: Optional[str]) -> None:
    """删除临时目录（幂等，失败静默）。"""
    if not path:
        return
    _TEMP_DIRS.discard(path)
    shutil.rmtree(path, ignore_errors=True)


def _atexit_cleanup() -> None:
    """进程退出兜底：清掉所有还没删掉的临时目录。"""
    for path in list(_TEMP_DIRS):
        _remove_temp_dir(path)


def _register_temp_dir(path: str) -> None:
    """登记临时目录，并（首次）挂上 atexit 兜底钩子。"""
    global _ATEXIT_HOOKED
    _TEMP_DIRS.add(path)
    if not _ATEXIT_HOOKED:
        atexit.register(_atexit_cleanup)
        _ATEXIT_HOOKED = True


def _release_temp_dir(path: str) -> None:
    """取消登记（``--keep-temp`` 时用，避免 atexit 把它删掉）。"""
    _TEMP_DIRS.discard(path)


# ---------------------------------------------------------------------------
# 参数拆分
# ---------------------------------------------------------------------------


def _new_private() -> Dict[str, Any]:
    """私有参数的初始值。"""
    return {
        "config_path": None,
        "preset": None,
        "metrics_path": None,
        "keep_temp": False,
        "no_preprocess": False,
    }


def split_args(argv: Sequence[str]
               ) -> Tuple[List[str], Dict[str, Any], List[str]]:
    """把 argv 拆成 ``(positional, private, passthrough)``。

    三集合语义：

    * ``private``   —— 本脚本私有（吸收，**绝不**出现在下游 argv）。
    * ``passthrough`` —— 下游 flag，**原样、按原顺序**转发；
      包含已登记的 ``--gt <v>``、``--gt=v``、``--f3-geometric``、
      ``--no-f3-sidecar``，以及**任何未知的 ``-`` 开头 token**（前向兼容：
      ``omr_oemer.py`` 以后新增 flag 无需改本文件）。
    * ``positional`` —— 非 ``-`` 开头且未被 flag 吃掉的 token。

    Args:
        argv: 通常是 ``sys.argv[1:]``。

    Returns:
        ``(positional, private, passthrough)``。

    Raises:
        ArgError: 私有/下游带值 flag 缺少取值。
    """
    positional: List[str] = []
    private = _new_private()
    passthrough: List[str] = []

    index = 0
    total = len(argv)
    while index < total:
        token = argv[index]

        # 1) 私有·带值（空格分隔形式）
        if token in PRIVATE_VALUE_FLAGS:
            if index + 1 >= total:
                raise ArgError(f"{token} 需要一个取值")
            private[PRIVATE_VALUE_FLAGS[token]] = argv[index + 1]
            index += 2
            continue

        # 2) 私有·带值（等号形式）
        equals_matched = False
        for flag, key in PRIVATE_VALUE_FLAGS.items():
            if token.startswith(flag + "="):
                value = token.split("=", 1)[1]
                if value == "":
                    raise ArgError(f"{flag} 需要一个非空取值")
                private[key] = value
                equals_matched = True
                break
        if equals_matched:
            index += 1
            continue

        # 3) 私有·布尔
        if token in PRIVATE_BOOL_FLAGS:
            private[PRIVATE_BOOL_FLAGS[token]] = True
            index += 1
            continue

        # 4) 下游·带值：连 flag 带取值一起原样转发
        if token in DOWNSTREAM_VALUE_FLAGS:
            if index + 1 >= total:
                raise ArgError(f"{token} 需要一个取值")
            passthrough.append(token)
            passthrough.append(argv[index + 1])
            index += 2
            continue

        # 5) 其它 flag：一律原样转发（前向兼容未知 flag）
        if token.startswith("-"):
            passthrough.append(token)
            index += 1
            continue

        # 6) 位置参数
        positional.append(token)
        index += 1

    return positional, private, passthrough


def parse_args(argv: Sequence[str]
               ) -> Tuple[List[str], Dict[str, Any], List[str]]:
    """:func:`split_args` 的包装：额外校验位置参数个数。

    Raises:
        ArgError: 参数非法（调用方应据此返回 rc 2）。
    """
    positional, private, passthrough = split_args(argv)
    if not positional:
        raise ArgError("缺少输入文件（至少需要 1 个位置参数）")
    if len(positional) > 2:
        raise ArgError(f"位置参数过多（最多 2 个: input / output），收到 {positional!r}")
    return positional, private, passthrough


# ---------------------------------------------------------------------------
# 路径推导
# ---------------------------------------------------------------------------


def resolve_out_path(positional: Sequence[str]) -> str:
    """按**原始 input** 推导输出 MusicXML 路径。

    本函数与 ``tools/omr_oemer.py:754-765`` **逐字对齐**：

    * ``len(positional) >= 2`` -> 直接取 ``positional[1]``；
    * 否则 -> ``dirname(abspath(input)) / (stem(input) + ".musicxml")``。

    这样即便下游拿到的是临时目录里的增强图，产物依然落在
    "与原始输入同目录、同 stem" 的位置，与不开预处理时完全一致。

    Raises:
        ArgError: ``positional`` 为空。
    """
    if not positional:
        raise ArgError("缺少输入文件")
    if len(positional) >= 2:
        return positional[1]
    in_abs = os.path.abspath(positional[0])
    stem = os.path.splitext(os.path.basename(in_abs))[0]
    return os.path.join(os.path.dirname(in_abs), stem + ".musicxml")


def downstream_script_path() -> str:
    """返回 ``omr_oemer.py`` 的绝对路径（与本文件同目录，不依赖 CWD）。"""
    return os.path.join(_TOOLS_DIR, DOWNSTREAM_SCRIPT)


def build_downstream_cmd(python_exe: str, script: str, in_path: str,
                         out_path: str,
                         passthrough: Sequence[str]) -> List[str]:
    """构造下游命令 argv。

    **永远显式给 2 个位置参数**（input + output），这是规避 R-P0-04 陷阱的关键。

    Args:
        python_exe: 解释器（生产环境恒为 ``sys.executable``，保证与本脚本同环境）。
        script: ``omr_oemer.py`` 绝对路径。
        in_path: 增强临时 PNG（成功）或原始输入（降级/跳过）。
        out_path: 按原始 input 推导出的 MusicXML 路径。
        passthrough: 需原样转发的下游 flag（顺序不变）。

    Returns:
        ``[python, script, in_path, out_path, *passthrough]``
    """
    return [python_exe, script, in_path, out_path] + list(passthrough)


def metrics_sidecar_path(out_path: str) -> str:
    """metrics sidecar 落点：与 ``.geometry.json`` 同命名族。

    ``x/y.musicxml`` -> ``x/y.preprocess.json``
    """
    suffix = ".musicxml"
    base = out_path[:-len(suffix)] if out_path.endswith(suffix) else out_path
    return base + ".preprocess.json"


# ---------------------------------------------------------------------------
# 决策
# ---------------------------------------------------------------------------


def should_preprocess(input_path: str,
                      cfg: "omr_preprocess.PreprocessConfig",
                      no_preprocess_flag: bool = False) -> bool:
    """判断本次是否真的要跑图像增强。

    返回 False 的三种情形（都意味着"原图原样转发给 oemer"）：

    1. 显式 ``--no-preprocess``；
    2. 输入不是受支持的位图（PDF 等，保守跳过）；
    3. 配置等价于 no-op（所有增强步骤都关闭），跑了只会多一次 PNG 编码损失。
    """
    if no_preprocess_flag:
        return False
    if not omr_preprocess.is_supported_input(input_path):
        return False
    if omr_preprocess.is_noop_config(cfg):
        return False
    return True


def _skip_reason(input_path: str, cfg: "omr_preprocess.PreprocessConfig",
                 no_preprocess_flag: bool) -> str:
    """给出跳过预处理的机器可读原因（写进 metrics.degrade_reason）。"""
    if no_preprocess_flag:
        return "skipped:no_preprocess_flag"
    if not omr_preprocess.is_supported_input(input_path):
        return "skipped:unsupported_input"
    if omr_preprocess.is_noop_config(cfg):
        return "skipped:noop_config"
    return "skipped:unknown"


# ---------------------------------------------------------------------------
# 子进程执行（runner 可注入，便于单测替身）
# ---------------------------------------------------------------------------


def _default_runner(cmd: Sequence[str]) -> Tuple[int, str, str]:
    """默认 runner：真跑子进程并捕获 stdout/stderr。

    ``subprocess`` 在此延迟 import，保持模块顶层依赖最小。

    Returns:
        ``(returncode, stdout, stderr)``
    """
    import subprocess  # noqa: PLC0415 - 仅执行路径需要

    completed = subprocess.run(list(cmd), capture_output=True, text=True)
    return completed.returncode, completed.stdout or "", completed.stderr or ""


# ---------------------------------------------------------------------------
# 残留清扫 & metrics 写出
# ---------------------------------------------------------------------------


def _protected_outputs(out_path: str,
                       metrics_path: Optional[str] = None) -> set:
    """本次运行的**正式产物**绝对路径集合——清扫时必须绕开。

    包含三类：

    * ``out_path`` 本身；
    * 下游 geometry sidecar。命名口径**逐字照抄** ``omr_oemer.py:816``
      的 ``out_path.replace('.musicxml', '.geometry.json')``，保证我们保护的
      正是下游真正会写出的那个文件名；顺带把「仅剥尾缀」的变体也纳入，
      两者在 out_path 含多个 ``.musicxml`` 时会分叉，多护无害；
    * metrics sidecar（用户可用 ``--preprocess-metrics`` 指定任意名字，
      理论上能撞进清扫目标）。

    宁可多护一个（后果：极端情况下少删一个残留文件），
    也不能少护一个（后果：静默删掉用户的最终产物）。
    """
    candidates = [out_path, out_path.replace(".musicxml", ".geometry.json")]
    if out_path.endswith(".musicxml"):
        candidates.append(out_path[:-len(".musicxml")] + ".geometry.json")
    if metrics_path:
        candidates.append(metrics_path)
    return {os.path.abspath(p) for p in candidates if p}


def _sweep_residue(out_path: str, enhanced_stem: Optional[str],
                   metrics_path: Optional[str] = None) -> None:
    """兜底清扫下游可能遗留在 out_dir 的临时 stem 产物。

    正常情况下 ``omr_oemer.py`` 会把 ``<stem>.pre.musicxml`` 重命名到
    out_path、把 ``<stem>.pre.geometry.json`` 重命名到 out 的 sidecar；
    但若它中途崩溃，这些文件会留在 out_dir 污染工作区。此处兜底删除。

    **陷阱（P3-1）**：当 out_path 的 basename 恰好等于 ``<stem>.pre.musicxml``
    时（例如手工执行 ``omr_pipeline.py foo.png foo.pre.musicxml``），
    "残留"与"正式产物"会指向同一个文件——若不加保护，这里会把下游刚写出的
    MusicXML 静默删掉，而 rc 仍是 0。故清扫前先排除本次运行的正式产物。
    """
    if not enhanced_stem:
        return
    try:
        out_dir = os.path.dirname(os.path.abspath(out_path))
        protected = _protected_outputs(out_path, metrics_path)
        for suffix in (".musicxml", ".geometry.json"):
            residue = os.path.join(out_dir, enhanced_stem + suffix)
            if os.path.abspath(residue) in protected:
                continue            # 是本次的正式产物，不是残留
            if os.path.isfile(residue):
                os.remove(residue)
                _info(f"已清理临时残留: {residue}")
    except OSError as exc:
        _warn(f"临时残留清理失败（不影响结果）: {exc}")


def _write_metrics(path: str, metrics: Dict[str, Any]) -> None:
    """写 metrics sidecar（失败仅告警，绝不影响 rc）。"""
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(metrics, handle, ensure_ascii=False, indent=2)
        _info(f"预处理指标已写出: {path}")
    except (OSError, TypeError, ValueError) as exc:
        _warn(f"预处理指标写出失败（不影响识别）: {exc}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(argv: Sequence[str],
        runner: Optional[Callable[[Sequence[str]], Tuple[int, str, str]]] = None
        ) -> int:
    """执行一次"预处理 + 转发"。

    Args:
        argv: 通常是 ``sys.argv[1:]``。
        runner: 可注入的下游执行器，签名
            ``(cmd: List[str]) -> (rc, stdout, stderr)``；
            None 时用真子进程（:func:`_default_runner`）。单测据此完全脱离
            cv2 与真 oemer。

    Returns:
        退出码（见模块文档）。
    """
    # ---- 1. 参数 ----
    try:
        positional, private, passthrough = parse_args(argv)
    except ArgError as exc:
        sys.stderr.write(f"[错误][preprocess] {exc}\n")
        sys.stderr.write(_USAGE)
        return 2

    in_path = positional[0]
    if not os.path.exists(in_path):
        sys.stderr.write(f"[错误][preprocess] 输入不存在: {in_path}\n")
        return 1

    out_path = resolve_out_path(positional)

    # ---- 2. 配置 ----
    cfg, config_source, cfg_warnings = omr_preprocess.load_config(
        private["config_path"], preset=private["preset"])
    for message in cfg_warnings:
        _warn(message)

    temp_dir: Optional[str] = None
    enhanced_stem: Optional[str] = None
    downstream_in = in_path
    metrics: Dict[str, Any]

    try:
        # ---- 3. 预处理（或跳过） ----
        if not should_preprocess(in_path, cfg, bool(private["no_preprocess"])):
            reason = _skip_reason(in_path, cfg, bool(private["no_preprocess"]))
            _info(f"跳过图像增强（{reason}），原图直送 oemer")
            metrics = omr_preprocess.build_metrics(
                ok=False, degraded=True, degrade_reason=reason,
                src=in_path, dst=in_path,
                config=cfg.to_dict(), config_source=config_source,
                preset=cfg.preset, binarize_method=cfg.binarize_method,
                warnings=list(cfg_warnings))
        else:
            temp_dir = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
            _register_temp_dir(temp_dir)
            stem = os.path.splitext(os.path.basename(os.path.abspath(in_path)))[0]
            enhanced_stem = stem + ".pre"
            enhanced = os.path.join(temp_dir, stem + ENHANCED_SUFFIX)

            try:
                metrics = omr_preprocess.preprocess_for_omr(in_path, enhanced, cfg)
            except Exception as exc:  # noqa: BLE001 - 预处理绝不阻断主流程
                metrics = omr_preprocess.build_metrics(
                    ok=False, degraded=True,
                    degrade_reason=f"{type(exc).__name__}: {exc}",
                    src=in_path, dst=in_path,
                    config=cfg.to_dict(), config_source=config_source,
                    preset=cfg.preset, binarize_method=cfg.binarize_method,
                    warnings=list(cfg_warnings))

            produced_ok = (bool(metrics.get("ok"))
                           and os.path.isfile(enhanced)
                           and os.path.getsize(enhanced) > 0)
            if produced_ok:
                downstream_in = enhanced
                _info(f"图像增强完成: {in_path} -> {enhanced} "
                      f"(preset={cfg.preset}, {metrics.get('total_ms', 0.0)}ms)")
            else:
                downstream_in = in_path
                enhanced_stem = None      # 没有增强图，就不会有 .pre.* 残留
                metrics["degraded"] = True
                metrics["dst"] = in_path
                if not metrics.get("degrade_reason"):
                    metrics["degrade_reason"] = "enhanced_output_missing"
                _warn(f"图像增强降级，改用原图: {metrics['degrade_reason']}")

        # ---- 4. 统一补齐 metrics 的上下文字段 ----
        metrics["config_source"] = config_source
        metrics["preset"] = cfg.preset
        existing = metrics.setdefault("warnings", [])
        for message in cfg_warnings:
            if message not in existing:
                existing.append(message)
        for message in existing:
            if message not in cfg_warnings:
                _warn(message)

        # ---- 5. 转发下游（永远显式 2 个位置参数） ----
        cmd = build_downstream_cmd(sys.executable, downstream_script_path(),
                                   downstream_in, out_path, passthrough)
        _info("转发下游: " + " ".join(cmd))
        execute = runner or _default_runner
        returncode, stdout_text, stderr_text = execute(cmd)
        if stdout_text:
            sys.stdout.write(stdout_text)
        if stderr_text:
            sys.stderr.write(stderr_text)

        # ---- 6. metrics sidecar ----
        # P3-2：CLI 显式 --preprocess-metrics 压过配置里的 emit_metrics_sidecar。
        #       命令行是"这一次"的明确指令，配置文件只是默认策略；用户既然点名
        #       要指标文件，就不该被配置静默吞掉。
        if cfg.emit_metrics_sidecar or private["metrics_path"]:
            target = private["metrics_path"] or metrics_sidecar_path(out_path)
            if private["metrics_path"] and not cfg.emit_metrics_sidecar:
                _info("配置 emit_metrics_sidecar=false，但 --preprocess-metrics "
                      "为显式指定，仍写出指标")
            _write_metrics(target, metrics)

        return int(returncode)

    finally:
        # 无论成败：先清 out_dir 里的 .pre.* 残留，再处理临时目录
        _sweep_residue(out_path, enhanced_stem, private["metrics_path"])
        if temp_dir:
            if private["keep_temp"]:
                _release_temp_dir(temp_dir)
                _info(f"--keep-temp 生效，保留临时目录: {temp_dir}")
            else:
                _remove_temp_dir(temp_dir)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """脚本入口。"""
    return run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
