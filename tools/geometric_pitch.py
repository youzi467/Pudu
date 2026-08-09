# -*- coding: utf-8 -*-
"""
谱渡 Pudu · F3 几何感知音高校正器（重算核心，纯 stdlib）
==========================================================

本模块**只依赖 Python 标准库**（`json` / `math` / `xml.etree.ElementTree` /
`dataclasses` / `typing`），不引入 numpy / oemer / 任何第三方依赖。
这样可让评测 harness 与单元测试在无 oemer / 无 GPU 环境下直接跑纯重算逻辑。

职责边界（铁律，详见 docs/system_design.md §8）：
  * ``recompute_pitch_from_geometry`` 只重写每个非休止音符的 ``<step>`` / ``<octave>``，
    绝不碰 ``<alter>``、调号 ``<fifths>``、休止符、时值（duration/type）、连音、和弦结构。
  * 谱号类型（clef）**只读** sidecar，不重新识别谱号字形。
  * sidecar 缺失 / 解析失败 / 谱线数≠5 / cy 测量可疑时，退化为「只读不改」，
    返回已重算音数（缺失时返回 0），**非致命**。

几何约定（与 oemer decode_note 完全一致，仅重算 ``staff_line_pos`` 的几何来源）：
  * ``pos``：diatonic 位置，沿用 oemer 语义——G 谱号 pos=0 为 D4，向上 +1。
  * ``_geometric_pos``：由符头墨迹质心 y（cy）与「真实谱线几何」求 pos：
        y_bottom = max(line.y_center)               # 底线（图像坐标 y 最大）
        half     = staff.unit_size / 2.0            # 半音级间距（线到间）
        delta    = round_half_up((y_bottom - cy) / half)   # 上行（cy 更小）为正
        pos      = STAFF_ANCHOR[clef_type]["bottom_pos"] + delta
  * ``_pos_to_step_octave``：复用 oemer ``decode_note`` 的 step 词表与 octave 公式，
    保证 F3 产出的 (step, octave) 与 oemer 同口径，仅 pos 更准 → 改动最小、可解释。

验证（与 oemer 源码核对）：
  * G_CLEF_POS_TO_PITCH / F_CLEF_POS_TO_PITCH 常量值取自 oemer build_system.py:25-26。
  * octave 公式逐字对齐 oemer build_system.py decode_note:918-931。
"""

import sys
import os
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple

import xml.etree.ElementTree as ET


# ----------------------------------------------------------------------
# 数据类（sidecar 契约，详见 docs/f3-sidecar-schema.md）
# ----------------------------------------------------------------------

@dataclass
class LineGeom:
    """单条谱线的几何信息。"""
    y_center: float                       # 谱线中心 y（pixel_model 坐标系）
    thickness: float = 0.0                # 谱线厚度（px），由 ink 上下界推导


@dataclass
class StaffGeometry:
    """五线谱表几何。"""
    staff_id: int
    track: int                            # oemer track（0-based），MusicXML <staff>=track+1
    group: Optional[int]
    unit_size: float                      # 谱线间距（px），half_step = unit_size/2
    y_center: float                       # 谱表中心 y
    lines: List[LineGeom]                 # 5 条谱线（顺序无关，按 y 排序使用）

    def bottom_line_y(self) -> float:
        """底线 y（图像坐标 y 最大者）。"""
        return max((L.y_center for L in self.lines), default=self.y_center)

    def sorted_line_ys_top2bottom(self) -> List[float]:
        """自顶向下（y 升序）的谱线 y 列表。"""
        return sorted(L.y_center for L in self.lines)


@dataclass
class ClefGeometry:
    """谱号几何（F3 只读其 type 作为几何映射输入）。"""
    track: int
    type: str                             # "G" | "F" | "C" | "percussion"
    line: Optional[int] = None
    x_center: Optional[float] = None
    y_center: Optional[float] = None
    sign: Optional[str] = None


@dataclass
class NoteGeometry:
    """单个符头的几何信息（重算主输入）。"""
    id: int                               # oemer note id == 发射序索引
    track: int
    group: Optional[int]
    bbox: Tuple[float, float, float, float]      # [x1, y1, x2, y2]
    center: Tuple[float, float]                  # [cx, cy] bbox 中心
    ink_centroid: Tuple[float, float]            # [cx, cy] 墨迹像素质心（比 bbox 更稳）
    staff_line_pos: int                   # oemer 原猜 diatonic pos（A/B 用）
    sfn: Optional[str] = None             # "sharp" | "flat" | "natural" | None


@dataclass
class SidecarDoc:
    """F3 几何 sidecar 文档（与 <basename>.musicxml 同目录同名 .geometry.json）。"""
    schema_version: int
    source_image: str
    musicxml: str
    coordinate_space: str
    note_order: str
    staves: List[StaffGeometry]
    clefs: List[ClefGeometry]
    notes: List[NoteGeometry]
    unit_size_px: Optional[float] = None
    image_width_px: Optional[float] = None
    image_height_px: Optional[float] = None

    def clefs_by_track(self) -> Dict[int, ClefGeometry]:
        """{track: ClefGeometry}。"""
        return {c.track: c for c in self.clefs}

    def staves_by_track(self) -> Dict[int, StaffGeometry]:
        """{track: StaffGeometry}。

        注意：oemer 里同一页所有谱表的 track 几乎总是 0（单轨语料），此 dict
        会塌缩成 {0: 最后一个谱表}，**不能**用 track 作唯一键选谱表。谱表选择
        必须用 _nearest_staff_by_y()（镜像 oemer find_closest_staffs 的 y 距离）。
        """
        return {s.track: s for s in self.staves}

    def _nearest_staff_by_y(self, cy: float, group: Optional[int] = None,
                            track: Optional[int] = None) -> Optional[StaffGeometry]:
        """按「note.track/group 归属 + y 距离最近」选谱表（镜像 oemer 语义）。

        oemer 里 note.track / note.group 取自 ``st_master``（``find_closest_staffs``
        选中的谱表），因此 **track+group 精确匹配即定位到原谱表**——比裸 y 距离更准
        （同页同 y 的多谱表靠 track 区分；单轨语料 track 全 0 时退化为组内 y 最近，
        组内重复谱表线位相同，任取其一几何一致）。

        选择优先级：
          1) 同 group 且同 track（oemer 主语义）；
          2) 同 group（track 不匹配时的兜底）；
          3) 全页 y 最近（group 缺失）。
        """
        staves = self.staves
        if group is not None:
            same_grp = [s for s in staves if s.group == group]
            if track is not None:
                same_track = [s for s in same_grp if s.track == track]
                if same_track:
                    return min(same_track, key=lambda s: abs(s.y_center - cy))
            if same_grp:
                return min(same_grp, key=lambda s: abs(s.y_center - cy))
        if track is not None:
            same_track = [s for s in staves if s.track == track]
            if same_track:
                return min(same_track, key=lambda s: abs(s.y_center - cy))
        if not staves:
            return None
        return min(staves, key=lambda s: abs(s.y_center - cy))

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可 json.dump 的 dict（tuple 自动变 list，符合 schema）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SidecarDoc":
        """从 JSON dict 构建（tuple 还原）。容错缺失可选字段。"""
        staves = [
            StaffGeometry(
                staff_id=int(s.get("staff_id", i)),
                track=int(s.get("track", i)),
                group=s.get("group"),
                unit_size=float(s.get("unit_size", 0.0) or 0.0),
                y_center=float(s.get("y_center", 0.0) or 0.0),
                lines=[LineGeom(y_center=float(ln.get("y_center", 0.0)),
                                thickness=float(ln.get("thickness", 0.0) or 0.0))
                       for ln in s.get("lines", [])],
            )
            for i, s in enumerate(d.get("staves", []))
        ]
        clefs = [
            ClefGeometry(
                track=int(c.get("track", 0)),
                type=str(c.get("type", "G")),
                line=c.get("line"),
                x_center=c.get("x_center"),
                y_center=c.get("y_center"),
                sign=c.get("sign"),
            )
            for c in d.get("clefs", [])
        ]
        notes = [
            NoteGeometry(
                id=int(n.get("id", i)),
                track=int(n.get("track", 0)),
                group=n.get("group"),
                bbox=tuple(float(v) for v in n.get("bbox", [0.0, 0.0, 0.0, 0.0])),
                center=tuple(float(v) for v in n.get("center", [0.0, 0.0])),
                ink_centroid=tuple(float(v) for v in n.get("ink_centroid", [0.0, 0.0])),
                staff_line_pos=int(n.get("staff_line_pos", 0)),
                sfn=n.get("sfn"),
            )
            for i, n in enumerate(d.get("notes", []))
        ]
        return cls(
            schema_version=int(d.get("schema_version", 1)),
            source_image=str(d.get("source_image", "")),
            musicxml=str(d.get("musicxml", "")),
            coordinate_space=str(d.get("coordinate_space", "pixel_model")),
            note_order=str(d.get("note_order", "oemer_emission")),
            staves=staves,
            clefs=clefs,
            notes=notes,
            unit_size_px=d.get("unit_size_px"),
            image_width_px=d.get("image_width_px"),
            image_height_px=d.get("image_height_px"),
        )


# ----------------------------------------------------------------------
# 常量（与 oemer 同款词表 / anchor，保证 step 词表与 oemer 完全一致）
# ----------------------------------------------------------------------

# 与 oemer build_system.py:25-26 一致
G_CLEF_POS_TO_PITCH = ['D', 'E', 'F', 'G', 'A', 'B', 'C']
F_CLEF_POS_TO_PITCH = ['F', 'G', 'A', 'B', 'C', 'D', 'E']

# anchor：谱表底线音 ↔ staff_line_pos（与 decode_note 的 oct_offset/pitch_offset 对应）
#   G 谱号：底线 pos=1 = E4（pos=0 为 D4）
#   F 谱号：底线 pos=1 = G2（pos=0 为 F2）—— F3 v2 修正：F 谱底线的正确
#   diatonic pos 与 G 谱一样是 1（不是 0）。oemer decode_note F: pos=1 → G2，
#   旧 anchor 写 bottom_pos=0 会把所有 F 谱音符系统性地压低一个音级。
STAFF_ANCHOR = {
    "G": {"bottom_step": "E", "bottom_oct": 4, "bottom_pos": 1},
    "F": {"bottom_step": "G", "bottom_oct": 2, "bottom_pos": 1},
}


# ----------------------------------------------------------------------
# 私有工具
# ----------------------------------------------------------------------

def _local(tag: str) -> str:
    """取标签本地名（去掉 XML 命名空间前缀 ``{uri}``）。"""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _strip_ns(root: ET.Element) -> ET.Element:
    """清除所有标签上的 XML 命名空间，保证写回的标签干净可读。"""
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _round_half_up(x: float) -> int:
    """round-half-up（音符压线即判在线/间上），区别于 Python 银行家舍入。

    例：
        _round_half_up( 0.5) =  1
        _round_half_up(-0.5) = -1
        _round_half_up( 1.5) =  2
        _round_half_up(-1.5) = -2
        _round_half_up( 2.4) =  2
        _round_half_up( 2.6) =  3
    """
    if x >= 0:
        return math.floor(x + 0.5)
    return math.ceil(x - 0.5)


# ----------------------------------------------------------------------
# 几何重算核心
# ----------------------------------------------------------------------

def _pos_to_step_octave(pos: int, clef_type: str) -> Tuple[str, int]:
    """复用 oemer decode_note 的 step 词表与 octave 公式（pos 已由几何校正）。

    逐字对齐 oemer build_system.py decode_note:918-931：
        step = order[pos%7] if pos>=0 else order[pos%-7]
        if pos - pitch_offset >= 0:
            octave = floor((pos + pitch_offset)/7) + oct_offset
        else:
            octave = -ceil((pos + pitch_offset)/-7) + oct_offset
    """
    order = G_CLEF_POS_TO_PITCH if clef_type == 'G' else F_CLEF_POS_TO_PITCH
    # 与 oemer 一致：pos>=0 用 pos%7，pos<0 用 pos%-7（Python 负模结果为非正）
    step = order[pos % 7] if pos >= 0 else order[pos % -7]
    pitch_offset = 1 if clef_type == 'G' else 3
    oct_offset = 4 if clef_type == 'G' else 2
    if pos - pitch_offset >= 0:
        octv = math.floor((pos + pitch_offset) / 7) + oct_offset
    else:
        octv = -math.ceil((pos + pitch_offset) / -7) + oct_offset
    return step, octv


def _geometric_pos(staff: StaffGeometry, clef_type: str, cy: float,
                   rounding: str = "half_up") -> int:
    """由符头中心 y 与真实谱线几何求 diatonic pos（oemer 约定 pos=0=D4@G）。

    仅修正几何推导，不依赖 oemer 的 staff_line_pos。
    图像坐标 y 向下增大，故**底线 = max(y_center)**（设计文档伪代码误写为 ys[-1]，
    此处按正确语义实现）。

    Args:
        staff: 该音符所属谱表几何（含 5 条谱线 y 与 unit_size）。
        clef_type: "G" 或 "F"（其余类型调用方应跳过）。
        cy: 符头中心 y（墨迹质心或 bbox 中心，单位与谱线 y 同坐标系）。
        rounding: 取整策略，仅支持 "half_up"（其余退化为 half_up）。

    Returns:
        int: diatonic pos（G 谱号 pos=0→D4，向上 +1）。

    Raises:
        ValueError: 谱线为空、unit_size 非法、或 clef_type 不在 STAFF_ANCHOR。
    """
    if not staff.lines:
        raise ValueError("staff 无谱线，无法几何重算")
    ys = [L.y_center for L in staff.lines]
    y_bottom = max(ys)                    # 底线（图像坐标 y 最大）
    half = staff.unit_size / 2.0
    if half <= 0:
        raise ValueError("staff.unit_size 非法，无法几何重算")
    anchor = STAFF_ANCHOR.get(clef_type)
    if anchor is None:
        raise ValueError(f"未知谱号类型 {clef_type!r}，无法几何重算")
    delta = _round_half_up((y_bottom - cy) / half)   # 上行（cy 更小）为正
    return anchor["bottom_pos"] + delta


def recompute_pitch_from_geometry(musicxml_path: str, sidecar_path: str,
                                  *, use_ink_centroid: bool = True,
                                  rounding: str = "half_up") -> int:
    """读 sidecar + MusicXML，按发射序 1:1 重算每个非休止音符的 <step>/<octave> 并写回。

    返回重算音数。不动 <alter>（Plan A 职责）、不动休止、不动时值。
    若 sidecar 缺失/解析失败：返回 0 且不改文件（非致命，保旧行为）。

    对齐键（稳健，主键）：
        sidecar.notes[] 顺序 = MusicXML <note>（非休止）文档序 1:1。
    退化（B 计划，非致命）：
        * 谱表 lines 数 ≠ 5：跳过该 staff 的音（保留 oemer 原值）。
        * 谱号类型非 G/F：跳过（保留 oemer 原值）。
        * 几何 pos 超出合法音域（A0~C8，同 oemer 合法性检查）：跳过（保留原值）。
        * cy 测量相对 oemer 原猜 staff_line_pos 偏差过大（>16 半音级）：视为可疑，跳过。

    Args:
        musicxml_path: 待重算的 MusicXML 路径（就地写回；仅在有改动时写）。
        sidecar_path: 对应的 <basename>.geometry.json 路径。
        use_ink_centroid: True 用墨迹质心 y（更稳），False 用 bbox 中心 y。
        rounding: 取整策略（保留参数，仅 "half_up" 生效）。

    Returns:
        int: 实际被重算（覆盖 step/octave）的音符数。
    """
    # —— 非致命前置：sidecar 缺失/解析失败 → 返回 0 且不改文件 ——
    if not os.path.isfile(sidecar_path):
        sys.stderr.write(
            f"[F3] sidecar 缺失，跳过几何重算（保留原产出）: {sidecar_path}\n")
        return 0
    try:
        with open(sidecar_path, 'r', encoding='utf-8') as f:
            doc = SidecarDoc.from_dict(json.load(f))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[F3] sidecar 解析失败，跳过几何重算: {e}\n")
        return 0

    # —— 解析 MusicXML ——
    try:
        tree = ET.parse(musicxml_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[F3] MusicXML 解析失败，跳过几何重算: {e}\n")
        return 0
    root = tree.getroot()
    _strip_ns(root)

    clefs = doc.clefs_by_track()
    n_notes = len(doc.notes)

    count = 0
    i = 0  # sidecar.notes 索引（发射序 1:1）
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue  # 休止符无音高，跳过
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None:
            continue

        if i >= n_notes:
            # sidecar 已耗尽：剩余音符保留 oemer 原值（非致命）
            break
        ng = doc.notes[i]
        i += 1

        # 谱表选择：按 y 距离最近（镜像 oemer find_closest_staffs）。不能按 track——
        # 单轨语料所有谱表 track=0，staves_by_track() 会塌缩成最后一个谱表，
        # 导致整页音符被拿同一个（错误）谱表几何重算（prelude -14 回归根因）。
        cy0 = ng.ink_centroid[1] if use_ink_centroid else ng.center[1]
        staff = doc._nearest_staff_by_y(cy0, group=ng.group, track=ng.track)
        # B 计划：谱线数≠5 或找不到谱表 → 跳过（保留原值）
        if staff is None or len(staff.lines) != 5:
            continue
        clef = clefs.get(ng.track)
        clef_type = clef.type if (clef is not None) else 'G'
        # B 计划：非 G/F 谱号（C/percussion）→ 跳过（保留原值）
        if clef_type not in STAFF_ANCHOR:
            continue

        # B 计划：cy 可疑（几何 pos 相对 oemer 原猜偏差过大）→ 跳过
        try:
            pos = _geometric_pos(staff, clef_type, cy0, rounding)
        except Exception:  # noqa: BLE001
            continue
        if ng.staff_line_pos is not None and abs(pos - int(ng.staff_line_pos)) > 16:
            continue

        step, octave = _pos_to_step_octave(pos, clef_type)
        # B 计划：几何结果超出合法音域（A0~C8，同 oemer 合法性检查）→ 跳过
        if octave < 0 or octave > 8 or (octave == 0 and step != "A") \
                or (octave == 8 and step != "C"):
            continue

        step_el.text = step
        oct_el = pitch.find("octave")
        if oct_el is None:
            oct_el = ET.SubElement(pitch, "octave")
        oct_el.text = str(octave)
        count += 1

    # 仅在有改动时写回，避免无谓的文件改写（missing-sidecar 路径已提前 return）
    if count > 0:
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return count


# ----------------------------------------------------------------------
# R-geo：几何感知时值校正（只缩不伸，规避过检测回归）
# ----------------------------------------------------------------------

# 改写目标表：16 分倍数（class）→ quarterLength → MusicXML <type>
_RHYTHM_QL_TO_TYPE = {
    0.25: "16th",
    0.5: "eighth",
    1.0: "quarter",
    2.0: "half",
    4.0: "whole",
}
# 时值重写的合法 class（16 分倍数；点节奏等非整数倍保守跳过）
_RHYTHM_CLASSES = {1, 2, 4, 8, 16}
# 校准锚点下限（仅 oemer 读出的 16 分音符）：不足则跳过整页（非致命，镜像 F3 B 计划）。
# 2026-08-09 全量 A/B（13 页）归因：校准锚点 <40 的页面几何时值校正均净亏——
#   * the-swan（无 16 分锚点，靠 8 分/2 兜底）：-6
#   * swan-lake（仅 20 个 16 分锚点）：-23
# 而 8 个净胜页最低锚点数 = 66（badinerie），故 40 取在「最弱胜者之下、清晰亏损者之上」，
# 零误伤胜者。同时移除 8 分/32 分兜底校准（the-swan 坏校准来源）：无足量真 16 分锚点
# 即视为「该页不是 16 分主导谱面」，R-geo 无从可缩，跳过比猜更安全。
_MIN_RHYTHM_CALIBRATION = 40


def _note_ql(note: ET.Element, divisions: int) -> Optional[float]:
    """返回音符的 quarterLength（``<duration>/divisions``），无法解析返回 None。"""
    dur_el = note.find("duration")
    if dur_el is None or dur_el.text is None:
        return None
    try:
        return int(str(dur_el.text).strip()) / float(divisions)
    except (ValueError, ZeroDivisionError):
        return None


def _min_defined_gap(g_prev: Optional[float], g_next: Optional[float]) -> Optional[float]:
    """两邻侧间距中已定义者取小者；同 x 和弦（gap≤1px）视为无邻侧。"""
    gs = [g for g in (g_prev, g_next) if g is not None and g > 1.0]
    return min(gs) if gs else None


def _calibrate_unit(records, divisions: int) -> Optional[float]:
    """自校准 16 分间距（px），纯相对、无 ts 依赖。

    仅用 oemer 已正确读出的 16 分音符（quarterLength==0.25）的 min(邻隙) 中位数；
    不足 ``_MIN_RHYTHM_CALIBRATION`` 个返回 None（调用方跳过整页，非致命）。
    依据：sidecar onset 间距与时值成精确比例（16 分≈1 单位、8 分≈2、4 分≈4），
    且 oemer 的 duration 误读均为「读长」（16→4/8 分、8→4 分），故 quarterLength
    ==0.25 的音符即真 16 分，可作校准锚点。

    2026-08-09 修正（全量 A/B 归因）：移除 8 分/2、32 分×2 兜底。兜底会拿「真 8 分
    的间距/2」当 16 分单位，把整页几何时值定得偏小 → 真 8 分/4 分被误缩成 16 分
    （the-swan 靠 8 分兜底净亏 -6 的根因）。无足量真 16 分锚点 = 非 16 分主导谱面，
    R-geo 无从可缩，跳过更安全。
    """
    def _median(vals):
        s = sorted(vals)
        return s[len(s) // 2]

    samples = []
    for note, _x, g_prev, g_next in records:
        ql = _note_ql(note, divisions)
        if ql is not None and abs(ql - 0.25) < 1e-9:
            g = _min_defined_gap(g_prev, g_next)
            if g is not None:
                samples.append(g)
    if len(samples) >= _MIN_RHYTHM_CALIBRATION:
        return _median(samples)
    return None


def recompute_rhythm_from_geometry(musicxml_path: str, sidecar_path: str) -> int:
    """几何感知时值校正：只把「被 oemer 读长」的快音符缩回几何间距对应的时值。

    背景（2026-08-09 全量 A/B 归因，见 docs/f3-abtest.md）：oemer 的 duration 头
    在快速乐句上把 16 分读成 4/8 分（16分→4分 ×334、16分→8分 ×265、8分→4分 ×70，
    占 771 个 rhythm 失败的 87%），且 746/771 发生在时值混合小节——是**逐音符**
    误读，不是整小节塌缩（均匀小节仅 25 个）。sidecar 里符头 onset 间距与时值成
    精确比例，与 oemer 的误读完全解耦，故可按间距反推每个音符应有时值。

    校正规则（只缩不伸 + 双侧判定，规避过收缩与过检测回归）：
        class_i 由两侧间距各自量化后合并：
          * 两侧一致 → 该 class 可信；
          * 一侧 ≥4 倍级更大 → 快音符贴慢音符（[16分][4分] 边界），取快 class；
          * 其余不一致 → 保守取大 class（几何无法区分「8分邻16分」与「16分在
            8 分边界」，取大不会把真 8 分/4 分误缩成 16 分）。
        仅当 ``0.25*class_i < oemer 当前 ql`` 时改写（把读长的缩回几何间距）；
        绝不伸长（避免把「快段结尾 / 孤音」的大间距误缩成更短，也不改动正确音符）。
        量化下界 1（=16 分）使假音符劈开的半距（~0.49 单位 → round→0 → 钳到 1）
        不会把真 16 分误缩成 32 分（过检测回归）；代价是真实 32 分（语料仅 ~39 个）
        不在 v1 范围。

    校准（无 ts 依赖，纯相对）：见 :func:`_calibrate_unit`。

    边界（B 计划，非致命，镜像 ``recompute_pitch_from_geometry``）：
        * sidecar 缺失 / 解析失败 → 返回 0 不改文件。
        * 单音符小节 / 小节首末音符无邻侧时用另一侧；两侧均无效则跳过。
        * class 非 {1,2,4,8,16}（点节奏等）→ 跳过（保守，不猜点）。
        * 改写时同步更新 ``<duration>`` 与 ``<type>``（若存在）、移除 ``<dot>``，
          保持 MusicXML 自洽（Pudu 依 duration/divisions 投影，duration 即评测口径）。

    Args:
        musicxml_path: 待校正 MusicXML（就地写回；仅在有改动时写）。
        sidecar_path: 对应的 ``<basename>.geometry.json`` 路径。

    Returns:
        int: 实际被改写时值的音符数。
    """
    # —— 非致命前置：sidecar 缺失/解析失败 → 返回 0 ——
    if not os.path.isfile(sidecar_path):
        sys.stderr.write(
            f"[rhythm] sidecar 缺失，跳过几何时值校正（保留原产出）: {sidecar_path}\n")
        return 0
    try:
        with open(sidecar_path, 'r', encoding='utf-8') as f:
            doc = SidecarDoc.from_dict(json.load(f))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[rhythm] sidecar 解析失败，跳过几何时值校正: {e}\n")
        return 0

    try:
        tree = ET.parse(musicxml_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[rhythm] MusicXML 解析失败，跳过几何时值校正: {e}\n")
        return 0
    root = tree.getroot()
    _strip_ns(root)

    # divisions：取首处 attributes（oemer 只在 measure 1 写 divisions），默认 16
    divisions = 16
    for a in root.iter("attributes"):
        d = a.find("divisions")
        if d is not None and d.text:
            try:
                divisions = int(str(d.text).strip())
            except ValueError:
                pass
            if divisions > 0:
                break
    if divisions <= 0:
        divisions = 16

    n_notes = len(doc.notes)

    # —— 1:1 映射：sidecar.notes 发射序 ↔ MusicXML 非休止 <note> 文档序（镜像 F3）。
    #    每小节按 x 排序后求邻隙；跨小节不配对（小节末/首音符用另一侧邻隙）。 ——
    measures = []
    i = 0
    for m in root.iter("measure"):
        pairs = []
        for note in m.findall("note"):
            if note.find("rest") is not None:
                continue
            if note.find("duration") is None:
                continue
            if i >= n_notes:
                break
            ng = doc.notes[i]
            i += 1
            pairs.append((note, float(ng.center[0])))
        if pairs:
            measures.append(pairs)

    # 每小节组内按 x 排序，展平为 (note, x, g_prev, g_next)
    records = []
    for pairs in measures:
        pairs.sort(key=lambda t: t[1])
        n = len(pairs)
        for k, (note, x) in enumerate(pairs):
            g_prev = (x - pairs[k - 1][1]) if k > 0 else None
            g_next = (pairs[k + 1][1] - x) if k < n - 1 else None
            records.append((note, x, g_prev, g_next))

    unit = _calibrate_unit(records, divisions)
    if unit is None or unit <= 0:
        sys.stderr.write(
            "[rhythm] 无法校准 16 分间距，跳过几何时值校正（非致命）\n")
        return 0

    count = 0
    for note, _x, g_prev, g_next in records:
        old_ql = _note_ql(note, divisions)
        if old_ql is None:
            continue
        classes = []
        for g in (g_prev, g_next):
            if g is not None and g > 1.0:
                c = int(_round_half_up(g / unit))
                if c >= 1:
                    classes.append(c)
        if not classes:
            continue
        # 双侧判定（关键，2026-08-09 修过度收缩回归）：
        #   * 两侧一致（c 相等）→ 该 class 可信；
        #   * 一侧 4 倍级更大 → 是快音符贴慢音符（如 [16分][4分] 边界），取快 class；
        #   * 其余不一致（如一侧 16 分、一侧 8 分）→ 保守取大 class：几何无法区分
        #     「8分邻16分」与「16分在 8 分边界」——取大不会把真 8 分/4 分误缩成 16 分
        #     （swan-lake/canon/summer_p2 过收缩根因：oemer 已正确读出的 8 分/4 分
        #     常与 16 分相邻，min() 单侧判为 16 分被误缩）。
        if len(classes) >= 2:
            c_small, c_large = min(classes), max(classes)
            if c_large >= 4 * c_small:
                cls = c_small
            else:
                cls = c_large
        else:
            cls = classes[0]
        if cls not in _RHYTHM_CLASSES:
            continue  # 非标准倍数（点节奏等），保守跳过
        new_ql = 0.25 * cls
        if new_ql >= old_ql - 1e-9:
            continue  # 只缩不伸：几何不短于当前时值则不动
        new_dur = int(round(new_ql * divisions))
        dur_el = note.find("duration")
        dur_el.text = str(new_dur)
        type_el = note.find("type")
        new_type = _RHYTHM_QL_TO_TYPE.get(new_ql)
        if type_el is not None:
            type_el.text = new_type if new_type else type_el.text
        dot = note.find("dot")
        if dot is not None:
            note.remove(dot)
        count += 1

    # 仅在有改动时写回，避免无谓的文件改写
    if count > 0:
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return count


if __name__ == "__main__":
    # 轻量自测：验证核心几何/映射与 oemer decode_note 口径一致
    staff = StaffGeometry(staff_id=0, track=0, group=0,
                          unit_size=11.2, y_center=1234.0,
                          lines=[LineGeom(y_center=y)
                                 for y in (1256.0, 1244.8, 1233.6, 1222.4, 1211.2)])
    # 底线（cy=1256）→ E4；半音级上方（cy=1250.4）→ F4；一间上方（cy=1244.8）→ G4
    assert _geometric_pos(staff, 'G', 1256.0) == 1
    assert _pos_to_step_octave(1, 'G') == ('E', 4)
    assert _geometric_pos(staff, 'G', 1250.4) == 2
    assert _pos_to_step_octave(2, 'G') == ('F', 4)
    assert _geometric_pos(staff, 'G', 1244.8) == 3
    assert _pos_to_step_octave(3, 'G') == ('G', 4)
    # 加线下方（cy=1267.2 = 底线下 2 半音级）→ pos -1 → C4
    assert _geometric_pos(staff, 'G', 1267.2) == -1
    assert _pos_to_step_octave(-1, 'G') == ('C', 4)
    # 边界 A0 / C8（A0 在 F 谱号为 pos=-12；C8 在 G 谱号为 pos=27）
    assert _pos_to_step_octave(-12, 'F') == ('A', 0)
    assert _pos_to_step_octave(9, 'F') == ('A', 3)
    assert _pos_to_step_octave(27, 'G') == ('C', 8)
    assert _round_half_up(0.5) == 1 and _round_half_up(-0.5) == -1
    assert _round_half_up(2.6) == 3 and _round_half_up(-2.6) == -3
    print("[geometric_pitch] 自测通过")
