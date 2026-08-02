#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · P0-2 · oemer 前置图像预处理增强（核心库）。

目标
----
在 oemer 识别之前，为拍照 / 扫描 / 低对比 / 轻微倾斜 / 带阴影的五线谱图片
提供一层**可开关、可配置、可逆**的确定性图像增强，提升 oemer 的鲁棒性。

三条设计红线
------------
1. **默认关**：本模块只有在上游 ``omr_pipeline.py`` 明确启用时才会被执行；
   ``tools/omr_oemer.py`` 完全不感知本模块的存在（零 diff）。
2. **cv2 / numpy 延迟导入**：模块顶层**禁止** ``import cv2`` / ``import numpy``。
   所有像素级操作统一经 :func:`_lazy_cv2` 在函数内部导入，保证
   ``import omr_preprocess`` 后 ``"cv2" not in sys.modules``。
   这样在没有 opencv 的环境（CI / 沙箱）里，配置解析、决策纯函数、
   指标构建等逻辑依然可被单测覆盖。
3. **fail-open**：任何一步失败都不得阻断主流程；``cfg.fail_open`` 为真时
   返回 ``ok=False / degraded=True / degrade_reason=...``，由调用方回退原图。

模块结构
--------
* :data:`DEFAULTS` / :data:`PRESETS` —— 配置单一真源（与
  ``tools/omr_preprocess_config.json`` 的 ``default`` 段逐字段一致）。
* :class:`PreprocessConfig` —— 配置 dataclass（``to_dict`` / ``from_dict`` /
  ``sanitize``）。
* :func:`load_config` —— 四级优先级配置加载，全程容错不抛异常。
* :func:`decide_deskew` —— **纯函数**（无 cv2）：是否纠偏 / 纠偏多少度。
* :func:`build_metrics` —— **纯函数**（无 cv2/numpy）：产出 metrics sidecar。
* :func:`is_supported_input` / :func:`is_noop_config` —— 纯判定。
* :func:`preprocess_for_omr` —— **唯一真正触碰 cv2 的入口**。

独立调参
--------
本文件可直接执行（不调 oemer），用于本机快速调参::

    python tools/omr_preprocess.py in.jpg out.png --preprocess-preset photo
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "TOOL_VERSION",
    "METRICS_SCHEMA",
    "DEFAULTS",
    "PRESETS",
    "TIMING_STEPS",
    "IMAGE_EXTENSIONS",
    "CONFIG_ENV_VAR",
    "PreprocessConfig",
    "DeskewDecision",
    "default_config_path",
    "load_config",
    "decide_deskew",
    "build_metrics",
    "is_supported_input",
    "is_noop_config",
    "preprocess_for_omr",
]

# 工具版本号（写入 metrics，便于回溯是哪一版预处理产生的产物）
TOOL_VERSION: str = "p0-2.1"

# metrics sidecar 的 schema 标识（与 .geometry.json 同命名族的独立 schema）
METRICS_SCHEMA: str = "pudu.omr.preprocess.metrics/v1"

# 受支持的图像输入扩展名（小写，含点）。PDF 等一律保守跳过预处理、原样转发。
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
)

# 配置文件环境变量名（第二优先级）
CONFIG_ENV_VAR: str = "PUDU_OMR_PREPROCESS_CONFIG"

# 默认配置文件名（与本文件同目录）
DEFAULT_CONFIG_FILENAME: str = "omr_preprocess_config.json"

# metrics.steps_timing_ms 的固定键集合（键恒在，未执行的步骤写 0.0）
TIMING_STEPS: Tuple[str, ...] = (
    "read",
    "gray",
    "shadow",
    "contrast",
    "denoise",
    "skew_estimate",
    "deskew",
    "crop",
    "binarize",
    "resize",
    "write",
)

# 二值化后墨迹占比的合理区间；越界仅告警（写入 metrics.warnings），不阻断。
INK_RATIO_WARN_MIN: float = 0.002
INK_RATIO_WARN_MAX: float = 0.450

# ---------------------------------------------------------------------------
# 配置单一真源
# ---------------------------------------------------------------------------

#: 所有可配置项的默认值。**这是唯一真源**：
#: ``PreprocessConfig`` 的字段默认值、``tools/omr_preprocess_config.json``
#: 的 ``default`` 段都必须与本字典逐字段一致（由单测把关）。
DEFAULTS: Dict[str, Any] = {
    # --- 对比度归一（CLAHE） ---
    "enable_contrast_norm": True,
    "clahe_clip_limit": 2.0,
    "clahe_tile_grid": 8,
    # --- 阴影抑制（形态学闭运算估计背景后相除） ---
    "enable_shadow_suppress": True,
    "shadow_kernel_px": 31,
    # --- 去噪（中值滤波；0 表示关闭） ---
    "denoise_strength": 3,
    # --- 二值化 ---
    "binarize_method": "adaptive",
    "block_size": 25,
    "C": 10,
    # --- 纠偏（默认关：宁可不转，也不能把好图转坏） ---
    "enable_deskew": False,
    "max_deskew_deg": 2.0,
    "min_deskew_deg": 0.15,
    # --- 边框裁切 ---
    "enable_border_crop": False,
    "border_margin_px": 8,
    # --- 输出 ---
    "output_format": "png",
    "max_long_side_px": 0,
    "upscale_min_long_side_px": 0,
    # --- 行为开关 ---
    "fail_open": True,
    "emit_metrics_sidecar": True,
    "preset": "default",
}

#: 内置档位。只列出与 ``DEFAULTS`` 不同的键（增量覆盖语义）。
#: ``tools/omr_preprocess_config.json`` 的 ``presets`` 段应与此保持一致。
PRESETS: Dict[str, Dict[str, Any]] = {
    # 平板扫描：光照均匀、无阴影、基本不倾斜 -> 关阴影抑制、直接 Otsu
    "scan": {
        "enable_shadow_suppress": False,
        "binarize_method": "otsu",
        "denoise_strength": 3,
        "enable_deskew": False,
    },
    # 手机拍照：光照不均 + 轻微倾斜 -> 大核阴影抑制 + 自适应阈值 + 纠偏
    "photo": {
        "enable_shadow_suppress": True,
        "shadow_kernel_px": 41,
        "binarize_method": "adaptive",
        "block_size": 31,
        "C": 12,
        "enable_deskew": True,
        "max_deskew_deg": 2.0,
    },
    # 淡墨 / 复印件：整体对比度不足 -> 提高 CLAHE clip、缩小自适应窗口
    "low_contrast": {
        "enable_contrast_norm": True,
        "clahe_clip_limit": 3.0,
        "binarize_method": "adaptive",
        "block_size": 21,
        "C": 6,
    },
}


# ---------------------------------------------------------------------------
# 类型安全转换 & 钳制工具（纯函数，无第三方依赖）
# ---------------------------------------------------------------------------

_TRUE_TOKENS = frozenset({"true", "1", "yes", "on", "y", "t"})
_FALSE_TOKENS = frozenset({"false", "0", "no", "off", "n", "f"})


def _warn(warnings: Optional[List[str]], message: str) -> None:
    """向告警列表追加一条消息（``warnings`` 为 None 时静默丢弃）。"""
    if warnings is not None:
        warnings.append(message)


def _coerce_bool(value: Any, default: bool, name: str,
                 warnings: Optional[List[str]] = None) -> bool:
    """把任意值安全转成 bool；无法安全转换时取 ``default`` 并告警。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    _warn(warnings, f"配置项 {name} 期望 bool，收到 {value!r}，已用默认值 {default!r}")
    return default


def _coerce_int(value: Any, default: int, name: str,
                warnings: Optional[List[str]] = None) -> int:
    """把任意值安全转成 int；无法安全转换时取 ``default`` 并告警。"""
    if isinstance(value, bool):
        _warn(warnings, f"配置项 {name} 期望 int，收到 bool {value!r}，已用默认值 {default!r}")
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            _warn(warnings, f"配置项 {name} 收到非有限数 {value!r}，已用默认值 {default!r}")
            return default
        return int(round(value))
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            pass
    _warn(warnings, f"配置项 {name} 期望 int，收到 {value!r}，已用默认值 {default!r}")
    return default


def _coerce_float(value: Any, default: float, name: str,
                  warnings: Optional[List[str]] = None) -> float:
    """把任意值安全转成 float；无法安全转换时取 ``default`` 并告警。"""
    if isinstance(value, bool):
        _warn(warnings, f"配置项 {name} 期望 float，收到 bool {value!r}，已用默认值 {default!r}")
        return default
    if isinstance(value, (int, float)):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            _warn(warnings, f"配置项 {name} 收到非有限数 {value!r}，已用默认值 {default!r}")
            return default
        return v
    if isinstance(value, str):
        try:
            v = float(value.strip())
            if math.isnan(v) or math.isinf(v):
                raise ValueError(value)
            return v
        except (TypeError, ValueError):
            pass
    _warn(warnings, f"配置项 {name} 期望 float，收到 {value!r}，已用默认值 {default!r}")
    return default


def _coerce_str(value: Any, default: str, name: str,
                warnings: Optional[List[str]] = None) -> str:
    """把任意值安全转成 str；非字符串一律取 ``default`` 并告警。"""
    if isinstance(value, str):
        return value
    _warn(warnings, f"配置项 {name} 期望 str，收到 {value!r}，已用默认值 {default!r}")
    return default


def _clamp_int(value: int, low: int, high: int, name: str,
               warnings: Optional[List[str]] = None) -> int:
    """把 int 钳制到 ``[low, high]``，越界告警。"""
    if value < low:
        _warn(warnings, f"配置项 {name}={value} 低于下界 {low}，已钳制")
        return low
    if value > high:
        _warn(warnings, f"配置项 {name}={value} 高于上界 {high}，已钳制")
        return high
    return value


def _clamp_float(value: float, low: float, high: float, name: str,
                 warnings: Optional[List[str]] = None) -> float:
    """把 float 钳制到 ``[low, high]``，越界告警。"""
    if value < low:
        _warn(warnings, f"配置项 {name}={value} 低于下界 {low}，已钳制")
        return low
    if value > high:
        _warn(warnings, f"配置项 {name}={value} 高于上界 {high}，已钳制")
        return high
    return value


def _force_odd(value: int) -> int:
    """把偶数向上取到相邻奇数（OpenCV 的核尺寸/窗口必须为奇数）。"""
    return value if value % 2 == 1 else value + 1


# ---------------------------------------------------------------------------
# 配置对象
# ---------------------------------------------------------------------------


@dataclass
class PreprocessConfig:
    """预处理配置。

    字段顺序、名称、默认值必须与 :data:`DEFAULTS` 逐字段一致（单测把关）。
    所有取值范围校验集中在 :meth:`sanitize`，保证不管配置从哪来，
    进入像素流水线的一定是合法值。
    """

    # 对比度归一
    enable_contrast_norm: bool = True
    clahe_clip_limit: float = 2.0
    clahe_tile_grid: int = 8
    # 阴影抑制
    enable_shadow_suppress: bool = True
    shadow_kernel_px: int = 31
    # 去噪
    denoise_strength: int = 3
    # 二值化
    binarize_method: str = "adaptive"
    block_size: int = 25
    C: int = 10
    # 纠偏
    enable_deskew: bool = False
    max_deskew_deg: float = 2.0
    min_deskew_deg: float = 0.15
    # 边框裁切
    enable_border_crop: bool = False
    border_margin_px: int = 8
    # 输出
    output_format: str = "png"
    max_long_side_px: int = 0
    upscale_min_long_side_px: int = 0
    # 行为
    fail_open: bool = True
    emit_metrics_sidecar: bool = True
    preset: str = "default"

    # -- 序列化 ------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """导出为普通 dict（键顺序与 :data:`DEFAULTS` 一致）。"""
        return {name: getattr(self, name) for name in DEFAULTS}

    @classmethod
    def from_dict(cls, data: Any,
                  warnings: Optional[List[str]] = None) -> "PreprocessConfig":
        """从任意 dict 安全构造配置。

        缺字段取默认；类型不符时做安全转换，转换失败取默认并告警。
        本方法**不做**取值范围校验，请在其后调用 :meth:`sanitize`。
        """
        if not isinstance(data, dict):
            _warn(warnings, f"配置不是 JSON object（收到 {type(data).__name__}），已使用内置默认值")
            data = {}
        kwargs: Dict[str, Any] = {}
        for name, default in DEFAULTS.items():
            raw = data.get(name, default)
            if isinstance(default, bool):          # bool 必须先于 int 判断
                kwargs[name] = _coerce_bool(raw, default, name, warnings)
            elif isinstance(default, int):
                kwargs[name] = _coerce_int(raw, default, name, warnings)
            elif isinstance(default, float):
                kwargs[name] = _coerce_float(raw, default, name, warnings)
            else:
                kwargs[name] = _coerce_str(raw, default, name, warnings)
        return cls(**kwargs)

    # -- 校验 --------------------------------------------------------------

    def sanitize(self) -> List[str]:
        """就地钳制所有字段到合法区间，返回告警列表（不抛异常）。"""
        w: List[str] = []

        # --- CLAHE ---
        self.clahe_clip_limit = _clamp_float(
            self.clahe_clip_limit, 0.5, 8.0, "clahe_clip_limit", w)
        self.clahe_tile_grid = _clamp_int(
            self.clahe_tile_grid, 2, 32, "clahe_tile_grid", w)

        # --- 阴影抑制：奇数核，[3, 201] ---
        self.shadow_kernel_px = _clamp_int(
            self.shadow_kernel_px, 3, 201, "shadow_kernel_px", w)
        odd = _force_odd(self.shadow_kernel_px)
        if odd != self.shadow_kernel_px:
            w.append(f"配置项 shadow_kernel_px={self.shadow_kernel_px} 必须为奇数，已调整为 {odd}")
        self.shadow_kernel_px = min(odd, 201)

        # --- 去噪：0 表示关；否则奇数且落在 [3, 9] ---
        if self.denoise_strength <= 0:
            if self.denoise_strength < 0:
                w.append(f"配置项 denoise_strength={self.denoise_strength} 为负，已按 0（关闭）处理")
            self.denoise_strength = 0
        else:
            clamped = _clamp_int(self.denoise_strength, 3, 9, "denoise_strength", w)
            odd = _force_odd(clamped)
            if odd != clamped:
                w.append(f"配置项 denoise_strength={clamped} 必须为奇数，已调整为 {odd}")
            self.denoise_strength = min(odd, 9)

        # --- 二值化方法 ---
        if self.binarize_method not in ("adaptive", "otsu", "none"):
            w.append(f'配置项 binarize_method="{self.binarize_method}" 非法'
                     f'（可选 adaptive/otsu/none），已回落为 "adaptive"')
            self.binarize_method = "adaptive"

        # --- 自适应阈值窗口：奇数且 >=3，钳 [3, 151] ---
        self.block_size = _clamp_int(self.block_size, 3, 151, "block_size", w)
        odd = _force_odd(self.block_size)
        if odd != self.block_size:
            w.append(f"配置项 block_size={self.block_size} 必须为奇数，已调整为 {odd}")
        self.block_size = min(odd, 151)

        self.C = _clamp_int(self.C, -50, 50, "C", w)

        # --- 纠偏阈值：先定 max，再定 min（min 必须严格小于 max） ---
        if self.max_deskew_deg <= 0.0:
            w.append(f"配置项 max_deskew_deg={self.max_deskew_deg} 必须为正，"
                     f"已回落为默认值 {DEFAULTS['max_deskew_deg']}")
            self.max_deskew_deg = float(DEFAULTS["max_deskew_deg"])
        self.max_deskew_deg = _clamp_float(
            self.max_deskew_deg, 1e-6, 15.0, "max_deskew_deg", w)

        if self.min_deskew_deg < 0.0:
            w.append(f"配置项 min_deskew_deg={self.min_deskew_deg} 为负，已钳制为 0.0")
            self.min_deskew_deg = 0.0
        if self.min_deskew_deg >= self.max_deskew_deg:
            new_min = round(self.max_deskew_deg / 2.0, 6)
            w.append(f"配置项 min_deskew_deg={self.min_deskew_deg} 必须小于 "
                     f"max_deskew_deg={self.max_deskew_deg}，已钳制为 {new_min}")
            self.min_deskew_deg = new_min

        # --- 边框裁切 ---
        self.border_margin_px = _clamp_int(
            self.border_margin_px, 0, 200, "border_margin_px", w)

        # --- 输出 ---
        if self.output_format != "png":
            w.append(f'配置项 output_format="{self.output_format}" 暂不支持'
                     f'（P0-2 仅支持 png），已回落为 "png"')
            self.output_format = "png"
        self.max_long_side_px = _clamp_int(
            self.max_long_side_px, 0, 8000, "max_long_side_px", w)
        self.upscale_min_long_side_px = _clamp_int(
            self.upscale_min_long_side_px, 0, 8000, "upscale_min_long_side_px", w)

        return w


@dataclass(frozen=True)
class DeskewDecision:
    """纠偏决策结果。

    Attributes:
        apply: 是否执行旋转。
        angle_deg: 传给 ``cv2.getRotationMatrix2D`` 的角度（逆时针为正）。
            不执行时恒为 ``0.0``。
        reason: 决策依据，取值 ``disabled`` / ``no_angle`` / ``below_min``
            / ``above_max`` / ``apply``。
    """

    apply: bool
    angle_deg: float
    reason: str


# ---------------------------------------------------------------------------
# 配置加载（四级优先级 + 全程容错）
# ---------------------------------------------------------------------------


def default_config_path() -> str:
    """返回仓库内置配置文件路径（与本文件同目录，不依赖 CWD）。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        DEFAULT_CONFIG_FILENAME)


def _filter_known(section: Dict[str, Any], where: str,
                  warnings: List[str]) -> Dict[str, Any]:
    """丢弃配置节里的未知键（记告警），返回只含已知键的新 dict。"""
    known: Dict[str, Any] = {}
    for key, value in section.items():
        if key in DEFAULTS:
            known[key] = value
        elif key in ("active_preset", "presets", "default", "$schema", "_comment"):
            continue  # 结构性键，不是配置项
        else:
            warnings.append(f'配置节 {where} 含未知键 "{key}"，已忽略')
    return known


def _read_config_file(path: str, explicit: bool,
                      warnings: List[str]) -> Optional[Dict[str, Any]]:
    """读取一个配置文件；任何异常都只记告警并返回 None（绝不抛）。"""
    if not path:
        return None
    try:
        if not os.path.isfile(path):
            if explicit:
                warnings.append(f"预处理配置文件不存在，已回落到下一优先级: {path}")
            return None
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        warnings.append(f"预处理配置文件读取/解析失败（{type(exc).__name__}: {exc}），"
                        f"已回落到下一优先级: {path}")
        return None
    except Exception as exc:  # noqa: BLE001 - 配置加载绝不抛
        warnings.append(f"预处理配置文件异常（{type(exc).__name__}: {exc}），"
                        f"已回落到下一优先级: {path}")
        return None
    if not isinstance(raw, dict):
        warnings.append(f"预处理配置文件顶层不是 JSON object（收到 "
                        f"{type(raw).__name__}），已回落到下一优先级: {path}")
        return None
    return raw


def load_config(path: Optional[str] = None,
                env_var: str = CONFIG_ENV_VAR,
                preset: Optional[str] = None
                ) -> Tuple[PreprocessConfig, str, List[str]]:
    """按四级优先级加载预处理配置。

    优先级（高 -> 低）::

        --preprocess-config <path>   (本函数的 path 形参)
        环境变量 env_var
        tools/omr_preprocess_config.json
        内置 DEFAULTS

    支持两种 JSON 形态：

    * **扁平形态**：顶层直接是配置项键值对，等价于 ``{"default": {...}}``。
    * **结构化形态**：含 ``default`` / ``presets`` / ``active_preset`` 段。

    合并顺序（后者覆盖前者）::

        DEFAULTS  <-  json.default  <-  PRESETS[active]  <-  json.presets[active]

    档位 ``active`` 的确定顺序：``preset`` 形参 > ``json.active_preset`` > ``"default"``。

    Args:
        path: 显式配置文件路径（对应 CLI 的 ``--preprocess-config``）。
        env_var: 环境变量名；传空串可禁用环境变量这一级。
        preset: 显式档位名（对应 CLI 的 ``--preprocess-preset``）。

    Returns:
        ``(cfg, config_source, warnings)``。``config_source`` 形如
        ``"cli:<path>"`` / ``"env:<path>"`` / ``"repo:<path>"`` /
        ``"builtin-defaults"``。本函数**永不抛异常**。
    """
    warnings: List[str] = []

    candidates: List[Tuple[str, str, bool]] = []
    if path:
        candidates.append(("cli", str(path), True))
    if env_var:
        env_path = os.environ.get(env_var) or ""
        if env_path:
            candidates.append(("env", env_path, True))
    candidates.append(("repo", default_config_path(), False))

    data: Optional[Dict[str, Any]] = None
    config_source = "builtin-defaults"
    for label, candidate, explicit in candidates:
        raw = _read_config_file(candidate, explicit, warnings)
        if raw is not None:
            data = raw
            config_source = f"{label}:{candidate}"
            break

    merged: Dict[str, Any] = dict(DEFAULTS)
    file_presets: Dict[str, Any] = {}
    file_active: str = ""

    if data is not None:
        if "default" in data or "presets" in data or "active_preset" in data:
            # 结构化形态
            base = data.get("default", {})
            if isinstance(base, dict):
                merged.update(_filter_known(base, "default", warnings))
            elif base is not None:
                warnings.append('配置节 "default" 不是 object，已忽略')
            raw_presets = data.get("presets")
            if raw_presets is None:
                file_presets = {}
            elif isinstance(raw_presets, dict):
                file_presets = raw_presets
            else:
                warnings.append('配置节 "presets" 不是 object，已忽略')
                file_presets = {}
            file_active = _coerce_str(data.get("active_preset", ""), "",
                                      "active_preset", warnings)
        else:
            # 扁平形态：整份文件等价于 default 段
            merged.update(_filter_known(data, "<root>", warnings))

    requested = (preset or file_active or "default").strip() or "default"
    active = requested
    if requested != "default":
        code_layer = PRESETS.get(requested)
        file_layer = file_presets.get(requested)
        if code_layer is None and not isinstance(file_layer, dict):
            warnings.append(f'未知的 preset "{requested}"（可选 '
                            f'{"/".join(["default"] + sorted(PRESETS))}），已回落到 default')
            active = "default"
        else:
            if isinstance(code_layer, dict):
                merged.update(_filter_known(code_layer, f"PRESETS[{requested}]", warnings))
            if isinstance(file_layer, dict):
                merged.update(_filter_known(file_layer, f"presets.{requested}", warnings))
            elif file_layer is not None:
                warnings.append(f'配置节 presets.{requested} 不是 object，已忽略')

    merged["preset"] = active

    cfg = PreprocessConfig.from_dict(merged, warnings)
    warnings.extend(cfg.sanitize())
    cfg.preset = active  # sanitize 不改 preset，这里兜底保证一致
    return cfg, config_source, warnings


# ---------------------------------------------------------------------------
# 纯函数：纠偏决策 / 指标构建 / 输入判定
# ---------------------------------------------------------------------------


def decide_deskew(angle_deg: Optional[float],
                  cfg: PreprocessConfig) -> DeskewDecision:
    """根据估计倾角与配置决定是否纠偏（**纯函数，不依赖 cv2**）。

    规则（按序短路）：

    1. ``cfg.enable_deskew`` 为假 -> ``(False, 0.0, "disabled")``
    2. ``angle_deg`` 为 None / 非数 / NaN / inf -> ``(False, 0.0, "no_angle")``
    3. ``abs(angle) < cfg.min_deskew_deg`` -> ``(False, 0.0, "below_min")``
       （小于噪声阈值，转了反而引入插值损失）
    4. ``abs(angle) > cfg.max_deskew_deg`` -> ``(False, 0.0, "above_max")``
       （**超限绝不强扭**：多半是测角失败，强转会毁掉好图）
    5. 其余 -> ``(True, -angle, "apply")``（取反：把图转回水平）

    边界：恰等于 ``min_deskew_deg`` / ``max_deskew_deg`` 均**允许**纠偏。

    Args:
        angle_deg: 估计出的倾斜角（度，顺时针为正）；无法估计时为 None。
        cfg: 预处理配置。

    Returns:
        :class:`DeskewDecision`。
    """
    if not bool(getattr(cfg, "enable_deskew", False)):
        return DeskewDecision(False, 0.0, "disabled")

    if angle_deg is None or isinstance(angle_deg, bool):
        return DeskewDecision(False, 0.0, "no_angle")
    try:
        angle = float(angle_deg)
    except (TypeError, ValueError):
        return DeskewDecision(False, 0.0, "no_angle")
    if math.isnan(angle) or math.isinf(angle):
        return DeskewDecision(False, 0.0, "no_angle")

    magnitude = abs(angle)
    if magnitude < float(cfg.min_deskew_deg):
        return DeskewDecision(False, 0.0, "below_min")
    if magnitude > float(cfg.max_deskew_deg):
        return DeskewDecision(False, 0.0, "above_max")
    return DeskewDecision(True, -angle, "apply")


def _as_size(value: Any) -> List[int]:
    """把任意尺寸表示规整成 ``[w, h]`` 的 int 列表。"""
    if value is None:
        return [0, 0]
    try:
        width, height = value[0], value[1]
        return [int(width), int(height)]
    except (TypeError, ValueError, IndexError, KeyError):
        return [0, 0]


def _as_opt_float(value: Any) -> Optional[float]:
    """把任意值转成 float 或 None（NaN/inf 视作 None）。"""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def build_metrics(*,
                  ok: bool = True,
                  degraded: bool = False,
                  degrade_reason: str = "",
                  src: str = "",
                  dst: str = "",
                  config: Optional[Dict[str, Any]] = None,
                  config_source: str = "builtin-defaults",
                  preset: str = "default",
                  size_in: Any = None,
                  size_out: Any = None,
                  mean_intensity_in: Any = None,
                  mean_intensity_out: Any = None,
                  mean_contrast_in: Any = None,
                  mean_contrast_out: Any = None,
                  binarize_method: str = "none",
                  bin_thresh: Any = None,
                  ink_ratio_out: Any = None,
                  deskew_angle_est_deg: Any = None,
                  deskew_applied_deg: Any = 0.0,
                  deskew_decision: str = "disabled",
                  steps_timing_ms: Optional[Dict[str, Any]] = None,
                  total_ms: Any = 0.0,
                  warnings: Optional[List[str]] = None,
                  tool_version: str = TOOL_VERSION) -> Dict[str, Any]:
    """构建 metrics sidecar 字典（**纯函数，不依赖 cv2/numpy**）。

    产出的 schema 为 :data:`METRICS_SCHEMA`。所有键**恒存在**，
    ``steps_timing_ms`` 的 11 个步骤键也恒存在（未执行的步骤为 ``0.0``），
    方便下游做无分支的表格化对比。

    Returns:
        可直接 ``json.dump(..., ensure_ascii=False, indent=2)`` 的 dict。
    """
    warn_list: List[str] = [str(item) for item in (warnings or [])]

    timing: Dict[str, float] = {step: 0.0 for step in TIMING_STEPS}
    for key, value in (steps_timing_ms or {}).items():
        if key in timing:
            parsed = _as_opt_float(value)
            timing[key] = round(parsed, 3) if parsed is not None else 0.0
        else:
            warn_list.append(f"steps_timing_ms 含未知步骤键 \"{key}\"，已忽略")

    ink = _as_opt_float(ink_ratio_out)
    if ink is not None and not (INK_RATIO_WARN_MIN <= ink <= INK_RATIO_WARN_MAX):
        warn_list.append(
            f"二值化后墨迹占比 ink_ratio_out={ink:.4f} 越出合理区间 "
            f"[{INK_RATIO_WARN_MIN}, {INK_RATIO_WARN_MAX}]，"
            f"增强参数可能不适合此图（建议换 preset 或关闭预处理）")

    applied = _as_opt_float(deskew_applied_deg)

    return {
        "schema": METRICS_SCHEMA,
        "ok": bool(ok),
        "degraded": bool(degraded),
        "degrade_reason": str(degrade_reason or ""),
        "src": str(src or ""),
        "dst": str(dst or ""),
        "config": dict(config) if isinstance(config, dict) else dict(DEFAULTS),
        "config_source": str(config_source or ""),
        "preset": str(preset or "default"),
        "size_in": _as_size(size_in),
        "size_out": _as_size(size_out),
        "mean_intensity_in": _as_opt_float(mean_intensity_in),
        "mean_intensity_out": _as_opt_float(mean_intensity_out),
        "mean_contrast_in": _as_opt_float(mean_contrast_in),
        "mean_contrast_out": _as_opt_float(mean_contrast_out),
        "binarize_method": str(binarize_method or "none"),
        "bin_thresh": _as_opt_float(bin_thresh),
        "ink_ratio_out": ink,
        "deskew_angle_est_deg": _as_opt_float(deskew_angle_est_deg),
        "deskew_applied_deg": 0.0 if applied is None else applied,
        "deskew_decision": str(deskew_decision or "disabled"),
        "steps_timing_ms": timing,
        "total_ms": round(_as_opt_float(total_ms) or 0.0, 3),
        "warnings": warn_list,
        "tool_version": str(tool_version or TOOL_VERSION),
    }


def is_supported_input(path: Optional[str]) -> bool:
    """判断输入是否是本模块能处理的位图（**纯函数**）。

    只按扩展名判断（不读文件头）：这是**保守**策略——PDF / 未知扩展名
    一律返回 False，上游据此跳过预处理、把原始文件原样交给 oemer。
    """
    if not path:
        return False
    return os.path.splitext(str(path))[1].lower() in IMAGE_EXTENSIONS


def is_noop_config(cfg: PreprocessConfig) -> bool:
    """判断配置是否等价于"什么都不做"（**纯函数**）。

    若所有增强步骤都关闭（含二值化 ``none`` 与不缩放），执行流水线只会
    白白多写一张 PNG，还会引入编码损失。此时上游应直接跳过预处理。
    """
    return (not cfg.enable_contrast_norm
            and not cfg.enable_shadow_suppress
            and not cfg.enable_deskew
            and not cfg.enable_border_crop
            and cfg.denoise_strength == 0
            and cfg.binarize_method == "none"
            and cfg.max_long_side_px == 0
            and cfg.upscale_min_long_side_px == 0)


# ---------------------------------------------------------------------------
# 像素流水线（唯一触碰 cv2 的区域，全部延迟导入）
# ---------------------------------------------------------------------------


def _lazy_cv2():
    """延迟导入 cv2 + numpy。

    **本模块顶层严禁 import cv2 / numpy**，一切像素操作必须经由此函数拿模块。
    这样在无 opencv 的环境里，纯逻辑部分依然可 import、可单测。

    Returns:
        ``(cv2, numpy)`` 模块二元组。

    Raises:
        ImportError: 当前解释器没装 opencv-python / numpy。
    """
    import cv2  # noqa: PLC0415 - 有意延迟导入
    import numpy  # noqa: PLC0415 - 有意延迟导入
    return cv2, numpy


def _imread_unicode(cv2, numpy, path: str):
    """读图（兼容中文/非 ASCII 路径；``cv2.imread`` 在 Windows 上会失败）。

    Returns:
        BGR ndarray；读取失败返回 None。
    """
    try:
        buffer = numpy.fromfile(path, dtype=numpy.uint8)
    except OSError:
        return None
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _imwrite_unicode(cv2, numpy, path: str, image, ext: str = ".png") -> bool:
    """写图（兼容中文/非 ASCII 路径）。成功返回 True。"""
    ok, buffer = cv2.imencode(ext, image)
    if not ok:
        return False
    try:
        buffer.tofile(path)
    except OSError:
        return False
    return True


def _estimate_skew_angle(gray, cfg: PreprocessConfig) -> Optional[float]:
    """估计五线谱的整体倾斜角（度，顺时针为正）。

    做法：内部临时 Otsu 反二值化 -> ``HoughLinesP`` 抽近水平长线段 ->
    取角度**中位数**（对离群线段稳健）。样本不足返回 None。

    注意：这里的临时二值图**只用于测角，不进入主链**，主链仍在灰度图上
    继续做后续处理，避免测角用的粗暴阈值污染最终产物。

    Args:
        gray: 单通道灰度 ndarray。
        cfg: 预处理配置（用 ``max_deskew_deg`` 圈定候选角度范围）。

    Returns:
        倾角（度）或 None。
    """
    cv2, _numpy = _lazy_cv2()
    _thresh, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    height, width = binary.shape[:2]
    min_line_length = max(40, int(width * 0.30))
    hough_threshold = max(60, int(width * 0.12))
    max_line_gap = max(4, int(width * 0.01))
    lines = cv2.HoughLinesP(binary, 1, math.pi / 180.0,
                            threshold=hough_threshold,
                            minLineLength=min_line_length,
                            maxLineGap=max_line_gap)
    if lines is None or len(lines) == 0:
        return None

    # 只收集"近水平"线段：候选窗口略放宽到 max_deskew_deg 的 3 倍 + 1 度，
    # 这样既能测出略超限的角（供 decide_deskew 判 above_max 并放弃），
    # 又不会把竖直的小节线 / 符干混进来。
    limit = float(cfg.max_deskew_deg) * 3.0 + 1.0
    angles: List[float] = []
    for line in lines:
        x1, y1, x2, y2 = (float(v) for v in line[0][:4])
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-6:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        if abs(angle) <= limit:
            angles.append(angle)

    if len(angles) < 5:      # 样本太少不足以稳健定角，宁可不纠偏
        return None
    angles.sort()
    count = len(angles)
    if count % 2 == 1:
        return float(angles[count // 2])
    return float(0.5 * (angles[count // 2 - 1] + angles[count // 2]))


def _gray_stats(gray) -> Tuple[float, float]:
    """返回灰度图的 ``(均值, 标准差)``，标准差即"对比度"的粗略度量。"""
    return float(gray.mean()), float(gray.std())


def preprocess_for_omr(src: str, dst: str,
                       cfg: Optional[PreprocessConfig] = None
                       ) -> Dict[str, Any]:
    """把 ``src`` 增强后写到 ``dst``，返回 metrics 字典。

    **这是本模块唯一真正 import cv2 的入口**，其余函数皆为纯逻辑。

    固定处理顺序（顺序本身即契约，改动需同步改设计文档）::

        读图 -> 灰度 -> 阴影抑制 -> 对比度归一(CLAHE) -> 去噪(中值)
             -> 测角 -> decide_deskew -> 旋转(borderValue=255)
             -> 边框裁切 -> 二值化 -> 缩放 -> GRAY2BGR -> 写 PNG

    Args:
        src: 输入图片路径。
        dst: 增强图输出路径（PNG）。
        cfg: 预处理配置；None 表示用内置默认值。

    Returns:
        :func:`build_metrics` 产出的 dict。成功时 ``ok=True``；
        失败且 ``cfg.fail_open`` 为真时返回 ``ok=False / degraded=True``
        并附 ``degrade_reason``（由调用方回退原图）。

    Raises:
        Exception: 仅当 ``cfg.fail_open`` 为 False 时向上抛出原始异常。
    """
    cfg = cfg or PreprocessConfig()
    warnings: List[str] = []
    timing: Dict[str, float] = {step: 0.0 for step in TIMING_STEPS}
    started = time.perf_counter()

    size_in: List[int] = [0, 0]
    mean_in: Optional[float] = None
    contrast_in: Optional[float] = None
    angle_est: Optional[float] = None
    decision = DeskewDecision(False, 0.0, "disabled")
    bin_thresh: Optional[float] = None

    def _fail(reason: str) -> Dict[str, Any]:
        """构造降级 metrics（保留已采集到的输入侧统计）。"""
        return build_metrics(
            ok=False, degraded=True, degrade_reason=reason,
            src=src, dst=src,
            config=cfg.to_dict(), config_source="", preset=cfg.preset,
            size_in=size_in, size_out=[0, 0],
            mean_intensity_in=mean_in, mean_contrast_in=contrast_in,
            binarize_method=cfg.binarize_method,
            deskew_angle_est_deg=angle_est,
            deskew_applied_deg=0.0, deskew_decision=decision.reason,
            steps_timing_ms=timing,
            total_ms=(time.perf_counter() - started) * 1000.0,
            warnings=warnings)

    try:
        cv2, numpy = _lazy_cv2()

        # --- 1. 读图 ---
        step_started = time.perf_counter()
        image = _imread_unicode(cv2, numpy, src)
        timing["read"] = (time.perf_counter() - step_started) * 1000.0
        if image is None:
            raise RuntimeError(f"无法解码图像（格式不支持或文件损坏）: {src}")
        size_in = [int(image.shape[1]), int(image.shape[0])]

        # --- 2. 灰度 ---
        step_started = time.perf_counter()
        if image.ndim == 3 and image.shape[2] >= 3:
            gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
        else:
            gray = image if image.ndim == 2 else image[:, :, 0]
        timing["gray"] = (time.perf_counter() - step_started) * 1000.0
        mean_in, contrast_in = _gray_stats(gray)

        # --- 3. 阴影抑制：闭运算估背景后相除，压掉不均匀光照 ---
        if cfg.enable_shadow_suppress:
            step_started = time.perf_counter()
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (cfg.shadow_kernel_px, cfg.shadow_kernel_px))
            background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
            gray = cv2.divide(gray, background, scale=255)
            timing["shadow"] = (time.perf_counter() - step_started) * 1000.0

        # --- 4. 对比度归一（CLAHE，局部直方图均衡） ---
        if cfg.enable_contrast_norm:
            step_started = time.perf_counter()
            clahe = cv2.createCLAHE(
                clipLimit=float(cfg.clahe_clip_limit),
                tileGridSize=(int(cfg.clahe_tile_grid), int(cfg.clahe_tile_grid)))
            gray = clahe.apply(gray)
            timing["contrast"] = (time.perf_counter() - step_started) * 1000.0

        # --- 5. 去噪（中值滤波，对椒盐噪声友好且保边） ---
        if cfg.denoise_strength > 0:
            step_started = time.perf_counter()
            gray = cv2.medianBlur(gray, int(cfg.denoise_strength))
            timing["denoise"] = (time.perf_counter() - step_started) * 1000.0

        # --- 6. 测角 + 7. 纠偏决策 + 8. 旋转 ---
        if cfg.enable_deskew:
            step_started = time.perf_counter()
            try:
                angle_est = _estimate_skew_angle(gray, cfg)
            except Exception as exc:  # noqa: BLE001 - 测角失败不致命
                angle_est = None
                warnings.append(f"测角失败（跳过纠偏）: {type(exc).__name__}: {exc}")
            timing["skew_estimate"] = (time.perf_counter() - step_started) * 1000.0

        decision = decide_deskew(angle_est, cfg)
        if decision.apply:
            step_started = time.perf_counter()
            height, width = gray.shape[:2]
            matrix = cv2.getRotationMatrix2D(
                (width / 2.0, height / 2.0), decision.angle_deg, 1.0)
            gray = cv2.warpAffine(
                gray, matrix, (width, height),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=255)          # 补白，不能补黑（否则被当成墨迹）
            timing["deskew"] = (time.perf_counter() - step_started) * 1000.0

        # --- 9. 边框裁切：去掉扫描/拍照带进来的黑边与大片空白 ---
        if cfg.enable_border_crop:
            step_started = time.perf_counter()
            _t, mask = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            coords = cv2.findNonZero(mask)
            if coords is not None:
                height, width = gray.shape[:2]
                bx, by, bw, bh = cv2.boundingRect(coords)
                margin = int(cfg.border_margin_px)
                x0 = max(0, bx - margin)
                y0 = max(0, by - margin)
                x1 = min(width, bx + bw + margin)
                y1 = min(height, by + bh + margin)
                # 裁得过小说明前景检测失败，保守放弃裁切
                if (x1 - x0) >= 32 and (y1 - y0) >= 32:
                    gray = gray[y0:y1, x0:x1]
                else:
                    warnings.append("边框裁切结果过小，已放弃裁切（保留原尺寸）")
            else:
                warnings.append("边框裁切未检测到前景，已放弃裁切")
            timing["crop"] = (time.perf_counter() - step_started) * 1000.0

        # --- 10. 二值化 ---
        if cfg.binarize_method != "none":
            step_started = time.perf_counter()
            if cfg.binarize_method == "otsu":
                thresh_value, gray = cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                bin_thresh = float(thresh_value)
            else:  # adaptive
                gray = cv2.adaptiveThreshold(
                    gray, 255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    int(cfg.block_size), int(cfg.C))
            timing["binarize"] = (time.perf_counter() - step_started) * 1000.0

        # --- 11. 缩放（先看是否需要降采样，再看是否需要升采样） ---
        step_started = time.perf_counter()
        height, width = gray.shape[:2]
        long_side = max(height, width)
        scale = 1.0
        if cfg.max_long_side_px > 0 and long_side > cfg.max_long_side_px:
            scale = float(cfg.max_long_side_px) / float(long_side)
        elif (cfg.upscale_min_long_side_px > 0
              and long_side < cfg.upscale_min_long_side_px):
            scale = float(cfg.upscale_min_long_side_px) / float(long_side)
        if abs(scale - 1.0) > 1e-6:
            new_width = max(1, int(round(width * scale)))
            new_height = max(1, int(round(height * scale)))
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            gray = cv2.resize(gray, (new_width, new_height),
                              interpolation=interpolation)
            timing["resize"] = (time.perf_counter() - step_started) * 1000.0

        # --- 出口统计（在灰度域算，转 BGR 前） ---
        mean_out, contrast_out = _gray_stats(gray)
        ink_ratio = float((gray < 128).sum()) / float(max(1, gray.size))
        size_out = [int(gray.shape[1]), int(gray.shape[0])]

        # --- 12. GRAY2BGR + 写 PNG（oemer 期望三通道输入） ---
        step_started = time.perf_counter()
        output = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        dst_dir = os.path.dirname(os.path.abspath(dst))
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)
        if not _imwrite_unicode(cv2, numpy, dst, output, ".png"):
            raise RuntimeError(f"增强图写出失败: {dst}")
        timing["write"] = (time.perf_counter() - step_started) * 1000.0

        return build_metrics(
            ok=True, degraded=False, degrade_reason="",
            src=src, dst=dst,
            config=cfg.to_dict(), config_source="", preset=cfg.preset,
            size_in=size_in, size_out=size_out,
            mean_intensity_in=mean_in, mean_intensity_out=mean_out,
            mean_contrast_in=contrast_in, mean_contrast_out=contrast_out,
            binarize_method=cfg.binarize_method, bin_thresh=bin_thresh,
            ink_ratio_out=ink_ratio,
            deskew_angle_est_deg=angle_est,
            deskew_applied_deg=decision.angle_deg if decision.apply else 0.0,
            deskew_decision=decision.reason,
            steps_timing_ms=timing,
            total_ms=(time.perf_counter() - started) * 1000.0,
            warnings=warnings)

    except ImportError as exc:
        if not cfg.fail_open:
            raise
        return _fail(f"opencv/numpy 不可用（请 pip install opencv-python）: {exc}")
    except Exception as exc:  # noqa: BLE001 - fail-open 是本模块的核心契约
        if not cfg.fail_open:
            raise
        return _fail(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 独立调参 CLI（不调 oemer，只出增强图 + metrics）
# ---------------------------------------------------------------------------


def _build_cli_parser():
    """构造独立调参 CLI 的参数解析器（延迟到调用时才 import argparse）。"""
    import argparse  # noqa: PLC0415 - 仅 CLI 路径需要

    parser = argparse.ArgumentParser(
        prog="omr_preprocess.py",
        description="谱渡 Pudu · oemer 前置图像增强（独立调参用，不调 oemer）")
    parser.add_argument("input", help="输入图片路径")
    parser.add_argument("output", nargs="?", default=None,
                        help="增强图输出路径（默认 <input_stem>.pre.png，与输入同目录）")
    parser.add_argument("--preprocess-config", dest="config_path", default=None,
                        help="预处理配置 JSON 路径")
    parser.add_argument("--preprocess-preset", dest="preset", default=None,
                        help="档位名: " + "/".join(["default"] + sorted(PRESETS)))
    parser.add_argument("--metrics", dest="metrics_path", default=None,
                        help="把 metrics 另存为 JSON 的路径（默认只打印到 stdout）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """独立调参入口：读图 -> 增强 -> 写 PNG -> 打印 metrics。

    Returns:
        0 成功；1 输入不存在或增强降级；2 参数错误（由 argparse 直接退出）。
    """
    args = _build_cli_parser().parse_args(
        sys.argv[1:] if argv is None else argv)

    if not os.path.exists(args.input):
        sys.stderr.write(f"[错误][preprocess] 输入不存在: {args.input}\n")
        return 1

    output = args.output
    if not output:
        in_abs = os.path.abspath(args.input)
        stem = os.path.splitext(os.path.basename(in_abs))[0]
        output = os.path.join(os.path.dirname(in_abs), stem + ".pre.png")

    cfg, config_source, cfg_warnings = load_config(
        args.config_path, preset=args.preset)
    for message in cfg_warnings:
        sys.stderr.write(f"[警告][preprocess] {message}\n")

    if not is_supported_input(args.input):
        sys.stderr.write(f"[警告][preprocess] 非位图输入（不做增强）: {args.input}\n")
        return 1

    metrics = preprocess_for_omr(args.input, output, cfg)
    metrics["config_source"] = config_source
    for message in cfg_warnings:
        if message not in metrics["warnings"]:
            metrics["warnings"].append(message)

    sys.stdout.write(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    if args.metrics_path:
        try:
            metrics_dir = os.path.dirname(os.path.abspath(args.metrics_path))
            if metrics_dir:
                os.makedirs(metrics_dir, exist_ok=True)
            with open(args.metrics_path, "w", encoding="utf-8") as handle:
                json.dump(metrics, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            sys.stderr.write(f"[警告][preprocess] metrics 写出失败: {exc}\n")

    if not metrics["ok"]:
        sys.stderr.write(
            f"[错误][preprocess] 增强降级: {metrics['degrade_reason']}\n")
        return 1
    sys.stderr.write(f"[preprocess] 增强图已写出: {output}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
