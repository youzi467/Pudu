# -*- coding: utf-8 -*-
"""纯净性探针：判定「导入某模块」这一动作本身是否会拉入重型第三方库。

背景（harness pytest 隔离债）
-----------------------------
早期的纯净性断言写成 ``self.assertNotIn("numpy", sys.modules)``。它检查的是
**当前进程的全局状态**，而不是「被测模块有没有引入 numpy」。

* 单独跑这些用例 → 全过；
* 在全量 ``pytest tests/`` 的同一个 session 里 → 误报。因为前置用例（例如走
  cv2 的预处理集成测试）早就把 numpy / cv2 装进了 ``sys.modules``，后续这些
  「纯净性」用例读到的是**别人留下的污染**，与被测代码无关。

正确口径是**增量断言**：把被测模块连同重型库一起从 ``sys.modules`` 里摘掉，
重新真正执行一次被测模块的顶层代码，再看这次导入**新增**了哪些模块。探针在
``finally`` 里原样还原 ``sys.modules``，对同 session 的其它用例零副作用。

注意：本模块只做「运行期增量」这一层护栏。各测试文件里基于**源码文本**的静态
检查（顶层 ``import cv2`` 扫描）是互补的第二层，两层都要保留。
"""

from __future__ import annotations

import importlib
import sys
from typing import Iterable, List, Sequence, Set, Tuple, Union

#: 各测试文件共用的「重型第三方库」清单（沿用 P0-2 规则）。
HEAVY_MODULES: Tuple[str, ...] = (
    "cv2", "numpy", "scipy", "pandas", "matplotlib",
)

#: ``targets`` 既接受单个模块名，也接受模块名序列。
TargetSpec = Union[str, Sequence[str]]


def _as_tuple(names: TargetSpec) -> Tuple[str, ...]:
    """把 ``str`` 或字符串序列统一成元组，便于后续处理。"""
    if isinstance(names, str):
        return (names,)
    return tuple(names)


def _purge_from_sys_modules(prefixes: Iterable[str]) -> None:
    """从 ``sys.modules`` 摘掉这些模块及其全部子模块（就地修改）。

    Args:
        prefixes: 模块名前缀集合，例如 ``("cv2", "omr_preprocess")``。
            ``"cv2"`` 会同时摘掉 ``"cv2.gapi"`` 之类的子模块。
    """
    prefix_tuple: Tuple[str, ...] = tuple(prefixes)
    for key in list(sys.modules):
        for prefix in prefix_tuple:
            if key == prefix or key.startswith(prefix + "."):
                del sys.modules[key]
                break


def modules_added_by_import(
    targets: TargetSpec,
    watched: Sequence[str] = HEAVY_MODULES,
) -> Set[str]:
    """重新导入 ``targets``，返回这次导入**新增**进 ``sys.modules`` 的模块名。

    实现要点（三步，缺一不可）：

    1. 先备份整张 ``sys.modules``；
    2. 把 ``targets`` 与 ``watched`` 一并摘掉——摘 ``watched`` 是关键，否则
       重型库若已被前置用例缓存，本次导入即使真的 ``import numpy`` 也命中缓存、
       不会体现在增量里，护栏会**假通过**；
    3. 真正执行一次 ``targets`` 的顶层代码，快照差集即为「本次导入拉进来的」。

    无论导入成功与否，``finally`` 都把 ``sys.modules`` 还原成备份，因此不会给
    同一个 pytest session 里的其它用例留下副作用。

    Args:
        targets: 待探测的模块名（单个字符串或字符串序列），按给定顺序导入。
        watched: 需要重点观察的重型库清单，默认 :data:`HEAVY_MODULES`。

    Returns:
        本次导入相对探测起点新增的模块名集合（含间接依赖）。

    Raises:
        ImportError: ``targets`` 中任一模块导入失败时向上抛出（还原动作已在
            ``finally`` 中完成，不会污染 ``sys.modules``）。
    """
    target_tuple: Tuple[str, ...] = _as_tuple(targets)
    watched_tuple: Tuple[str, ...] = _as_tuple(watched)
    saved = dict(sys.modules)
    try:
        _purge_from_sys_modules(target_tuple + watched_tuple)
        before = frozenset(sys.modules)
        for name in target_tuple:
            importlib.import_module(name)
        return set(sys.modules) - before
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def heavy_modules_pulled_by_import(
    targets: TargetSpec,
    watched: Sequence[str] = HEAVY_MODULES,
) -> List[str]:
    """返回「导入 ``targets`` 会新增引入」的重型库清单（已排序，空表示纯净）。

    Args:
        targets: 待探测的模块名（单个字符串或字符串序列）。
        watched: 需要重点观察的重型库清单，默认 :data:`HEAVY_MODULES`。

    Returns:
        被本次导入拉进来的重型库名，按字典序排序；纯净时为空列表。
    """
    watched_tuple: Tuple[str, ...] = _as_tuple(watched)
    added = modules_added_by_import(targets, watched_tuple)
    return sorted(name for name in watched_tuple if name in added)


def assert_import_is_pure(
    case,
    targets: TargetSpec,
    watched: Sequence[str] = HEAVY_MODULES,
) -> None:
    """便捷断言：导入 ``targets`` 不得**新增**引入 ``watched`` 中的任何库。

    Args:
        case: 调用方的 :class:`unittest.TestCase` 实例（用其断言与报错格式）。
        targets: 待探测的模块名（单个字符串或字符串序列）。
        watched: 需要重点观察的重型库清单，默认 :data:`HEAVY_MODULES`。
    """
    target_tuple: Tuple[str, ...] = _as_tuple(targets)
    offenders = heavy_modules_pulled_by_import(target_tuple, watched)
    case.assertEqual(
        offenders, [],
        "导入 %s 时新增引入了重型库 %s（顶层 import 泄漏，"
        "无 cv2/numpy 的沙箱会直接崩）" % ("/".join(target_tuple), offenders),
    )
