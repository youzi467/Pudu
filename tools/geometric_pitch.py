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
import collections
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple, Sequence

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

    @staticmethod
    def _nearest_clef_by_y(clefs: Sequence["ClefGeometry"],
                           staff_y: float) -> Optional["ClefGeometry"]:
        """按 y 距离取距谱表最近的有效谱号（y_center 缺失的跳过）。

        替代 per-track 塌缩：单轨语料所有谱表 track=0，``clefs_by_track()`` 会把
        整页谱号折叠成最后一个，遇 F 谱（含假阳性）即整页错锚点。每个系统左缘恰好
        一个谱号，取距该谱表 y 最近者即定位到该系统自身谱号。
        """
        cand = [c for c in clefs if c.y_center is not None]
        if not cand:
            return None
        return min(cand, key=lambda c: abs(c.y_center - staff_y))

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
# 低置信度标记（需校对 footnote 写回，MVP 兜底体验）
# ----------------------------------------------------------------------

_MARK_PREFIX = "需校对："
_REASON_PITCH_SKIP = "几何音高未验证"            # F3 B 计划跳过
_REASON_RHYTHM_SKIP = "几何时值未校正"            # R-geo B 计划跳过
# （读短嫌疑曾以 _REASON_RHYTHM_READ_SHORT 打标，2026-08-10 实测语料抓到 0 个真读短
#   ——196 读短簇几何+beam 双盲不可分，见 docs/f3-abtest.md，已按决策丢弃该标记。）


def _mark_needs_review(note: ET.Element, reason: str) -> bool:
    """为音符追加 <notations><footnote>需校对：{reason}</footnote>（幂等去重）。

    仅作「需校对」标记，不改任何音符内容；C++ 投影器（Pudu）按名分发 measure
    子元素、忽略 <notations>，故不影响简谱投影与 eval；music21 解析无错、再渲染
    时静默丢弃，验收②「可读 + 可再渲染」由构造保持。

    去重/幂等规则：
        * 每音符至多一个 <footnote>：已存在时以「；」追加新原因（合并），避免
          F3 先写、R-geo 重读同一文件时产生双 footnote；
        * 若新原因已包含在现有文本中（同一原因被二次调用）→ 不重复，返回 False。
    <footnote> 按 MusicXML 3.1 序插为 <notations> 首子元素（须在 tuplet 等之前）；
    <notations> 在 <note> 内插于 <lyric> 之前（无 lyric 则追加到末尾）。

    Args:
        note: <note> ET 元素。
        reason: 不含前缀的原因串（见 _REASON_*）。

    Returns:
        bool: 本次调用是否产生了标记变动（调用方据此决定是否写回文件）。
    """
    notations = note.find("notations")
    if notations is None:
        notations = ET.Element("notations")
        lyric = note.find("lyric")
        if lyric is not None:
            note.insert(list(note).index(lyric), notations)
        else:
            note.append(notations)
    fn = notations.find("footnote")
    if fn is None:
        fn = ET.Element("footnote")
        fn.text = _MARK_PREFIX + reason
        notations.insert(0, fn)
        return True
    cur = (fn.text or "").strip()
    if reason in cur:
        return False
    fn.text = cur + "；" + reason
    return True


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


# ----------------------------------------------------------------------
# forward/backup 溢出修复（兼容层：oemer writer voice-bridge 的 16-bit 回卷）
# ----------------------------------------------------------------------

# 溢出判据：corrupt 值恒 ≥65520（= 65536-{4..16}，无符号 16-bit 回卷），
# 而全语料合法 forward/backup 最大仅 16（= divisions16 下的整小节 rest）。
# 200 远高于任何合法值、远低于 corrupt 区，可安全区分。
_FORWARD_CORRUPT_MIN = 200


def repair_forward_overflow(musicxml_path: str) -> int:
    """移除 oemer voice-2 bridge 写出的 16-bit 溢出 <forward>/<backup>（就地写回）。

    背景（2026-08-09 发现）：oemer build_system.py 的 voice-2 bridge 用
    ``last_pos - cur_pos`` 作差值，跨 voice 时差值经无符号 16-bit 回卷后写出
    65520~65532（=65536-X）的 <forward>。music21 读入后把每个当成约 4095 拍的
    跨度，整小节被拉成 131100 拍，导致 MusicXML 回写挂起（验收项② 6/13 失败）。

    修复语义：corrupt forward 的真实间距是 **0** —— v1/v2 音符在 XML 里本就
    交错紧邻（实测 measure 内 v2 音符后紧跟下一音符，无 forward 需填充的空隙），
    <backup> 已单独负责 v2 回卷。故正确修复是**移除**而非钳值：钳值会无中生有
    拉开 v1/v2 间隙。幂等：二次调用无 corrupt 元素，返回 0 且不改文件。

    Args:
        musicxml_path: 待修复 MusicXML（就地写回；仅在有改动时写）。

    Returns:
        int: 移除的 corrupt 元素数。
    """
    try:
        tree = ET.parse(musicxml_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[repair] MusicXML 解析失败，跳过溢出修复: {e}\n")
        return 0
    root = tree.getroot()
    _strip_ns(root)

    # <forward>/<backup> 恒为 <measure> 的直接子元素（MusicXML 规范），
    # 逐 measure 检查直接子元素即可覆盖全部，无需 parent 指针。
    removed = 0
    for part in root.iter("part"):
        for measure in part.iter("measure"):
            for el in list(measure):
                if el.tag not in ("forward", "backup"):
                    continue
                dur_el = el.find("duration")
                if dur_el is None or dur_el.text is None:
                    continue
                try:
                    dur = int(str(dur_el.text).strip())
                except ValueError:
                    continue
                if dur > _FORWARD_CORRUPT_MIN:
                    measure.remove(el)
                    removed += 1

    if removed > 0:
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
        sys.stderr.write(
            f"[repair] 移除 {removed} 个 16-bit 溢出 forward/backup: {musicxml_path}\n")
    return removed


def recompute_pitch_from_geometry(musicxml_path: str, sidecar_path: str,
                                  *, use_ink_centroid: bool = True,
                                  rounding: str = "half_up") -> int:
    """读 sidecar + MusicXML，按发射序 1:1 重算每个非休止音符的 <step>/<octave> 并写回。

    返回重算音数。不动 <alter>（Plan A 职责）、不动休止、不动时值。
    若 sidecar 缺失/解析失败：返回 0 且不改文件（非致命，保旧行为）；
    但**前置的 forward 溢出修复仍会执行**（见 :func:`repair_forward_overflow`，
    与 F3 可算性无关，任何调用路径都应先清理 corrupt forward）。

    对齐键（稳健，主键）：
        sidecar.notes[] 顺序 = MusicXML <note>（非休止）文档序 1:1。
    退化（B 计划，非致命）：
        * 谱表 lines 数 ≠ 5：跳过该 staff 的音（保留 oemer 原值）。
        * 谱号类型非 G/F：跳过（保留 oemer 原值）。
        * 几何 pos 超出合法音域（A0~C8，同 oemer 合法性检查）：跳过（保留原值）。
        * cy 测量相对 oemer 原猜 staff_line_pos 偏差过大（>16 半音级）：视为可疑，跳过。
    被跳过的音符打 ``<notations><footnote>需校对：几何音高未验证</footnote>``
    （MVP 兜底体验；仅在有 sidecar 且跑过本函数时写回，见 :func:`_mark_needs_review`）。

    Args:
        musicxml_path: 待重算的 MusicXML 路径（就地写回；仅在有改动时写）。
        sidecar_path: 对应的 <basename>.geometry.json 路径。
        use_ink_centroid: True 用墨迹质心 y（更稳），False 用 bbox 中心 y。
        rounding: 取整策略（保留参数，仅 "half_up" 生效）。

    Returns:
        int: 实际被重算（覆盖 step/octave）的音符数。
    """
    # —— 前置兼容修复：oemer voice-2 bridge 的 16-bit 溢出 forward（与 F3 可算性
    #    无关，先清理，否则 music21 回写挂起）。幂等，无 corrupt 则不动文件。 ——
    repair_forward_overflow(musicxml_path)

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

    n_notes = len(doc.notes)

    count = 0
    marked = False  # 低置信度标记（footnote 写回）
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
        # B 计划：谱线数≠5 或找不到谱表 → 跳过（保留原值），打「需校对」标记
        if staff is None or len(staff.lines) != 5:
            marked |= _mark_needs_review(note, _REASON_PITCH_SKIP)
            continue
        # 谱号按「该谱表 y 最近的谱号」选，替代 per-track 全局塌缩。
        # 单轨语料所有 clef.track=0，clefs_by_track() 塌缩成最后一个谱号；若页末
        # 恰有 F 谱（含假阳性，实测 system-D 区检出 y=788 F 谱），整页都被 bass
        # 锚点重算（统一低 2 个八度）。每系统左缘恰一个谱号，按 |y_center - staff.y_center|
        # 取最近即定位到该系统谱号（G/F 同型时与旧行为一致）。
        clef = doc._nearest_clef_by_y(doc.clefs, staff.y_center)
        clef_type = clef.type if (clef is not None) else 'G'
        # B 计划：非 G/F 谱号（C/percussion）→ 跳过（保留原值），打「需校对」标记
        if clef_type not in STAFF_ANCHOR:
            marked |= _mark_needs_review(note, _REASON_PITCH_SKIP)
            continue

        # B 计划：cy 可疑（几何 pos 相对 oemer 原猜偏差过大）→ 跳过，打「需校对」标记
        try:
            pos = _geometric_pos(staff, clef_type, cy0, rounding)
        except Exception:  # noqa: BLE001
            marked |= _mark_needs_review(note, _REASON_PITCH_SKIP)
            continue
        if ng.staff_line_pos is not None and abs(pos - int(ng.staff_line_pos)) > 16:
            marked |= _mark_needs_review(note, _REASON_PITCH_SKIP)
            continue

        step, octave = _pos_to_step_octave(pos, clef_type)
        # B 计划：几何结果超出合法音域（A0~C8，同 oemer 合法性检查）→ 跳过，
        # 打「需校对」标记
        if octave < 0 or octave > 8 or (octave == 0 and step != "A") \
                or (octave == 8 and step != "C"):
            marked |= _mark_needs_review(note, _REASON_PITCH_SKIP)
            continue

        step_el.text = step
        oct_el = pitch.find("octave")
        if oct_el is None:
            oct_el = ET.SubElement(pitch, "octave")
        oct_el.text = str(octave)
        count += 1

    # 仅在有改动时写回，避免无谓的文件改写（missing-sidecar 路径已提前 return）
    if count > 0 or marked:
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
# 侧置信窗（2026-08-10）：间距比值距其 class 理想值 ≤ 此值才采信该侧。
# 贴近 0.5 边界（如 1.44/1.52）的间距属「16 分 vs 8 分」模糊区——重跑校准漂移会把
# pass-1 正确判为 8 分/4 分的音符推到 16 分侧导致非幂等过缩（实测 6 音符 + 锚点审计
# [1.25,1.5) 区间 81.6% 在 GT 本非 16 分），故模糊侧弃用、双侧全模糊则保守不动。
_RHYTHM_SIDE_CONFIDENCE = 0.25
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
    被跳过的音符打 ``<footnote>需校对：几何时值未校正</footnote>``（MVP 兜底体验，
    见 :func:`_mark_needs_review`）。仅缩守卫拦下而不打标的音符即「几何一致或更短」，
    无嫌疑标记（读短簇几何+beam 双盲，实测抓 0 真读短，2026-08-10 已按决策不标）。

    Args:
        musicxml_path: 待校正 MusicXML（就地写回；仅在有改动时写）。
        sidecar_path: 对应的 ``<basename>.geometry.json`` 路径。

    Returns:
        int: 实际被改写时值的音符数。
    """
    # —— 前置兼容修复：oemer voice-2 bridge 的 16-bit 溢出 forward（与 R-geo 可算性
    #    无关，先清理，否则 music21 回写挂起）。幂等，无 corrupt 则不动文件。 ——
    repair_forward_overflow(musicxml_path)

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
    marked = False  # 低置信度标记（footnote 写回）
    for note, _x, g_prev, g_next in records:
        old_ql = _note_ql(note, divisions)
        if old_ql is None:
            marked |= _mark_needs_review(note, _REASON_RHYTHM_SKIP)
            continue
        side_ratios = []
        for g in (g_prev, g_next):
            if g is not None and g > 1.0:
                side_ratios.append(g / unit)
        if not side_ratios:
            # 无有效邻隙（单音小节 / 两侧均为同 x 和弦）：B 计划跳过，打标
            marked |= _mark_needs_review(note, _REASON_RHYTHM_SKIP)
            continue
        # 置信量化：仅采信距 class 理想值 ≤ _RHYTHM_SIDE_CONFIDENCE 的侧（见常量注释）。
        classes = []
        for r in side_ratios:
            c = int(_round_half_up(r))
            if c >= 1 and abs(r - c) <= _RHYTHM_SIDE_CONFIDENCE:
                classes.append(c)
        if not classes:
            continue  # 有邻隙但全部模糊（贴近 .5 边界）：保守不动、不打标
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
            marked |= _mark_needs_review(note, _REASON_RHYTHM_SKIP)
            continue  # 非标准倍数（点节奏等），保守跳过
        new_ql = 0.25 * cls
        if new_ql >= old_ql - 1e-9:
            # 只缩不伸：几何不短于当前时值则不动（也不伸长，避免把快段结尾/孤音的
            # 大间距误缩成更短）。读短嫌疑（几何远超当前、被此守卫拦住）曾在语料上
            # 实测抓到 0 个真读短（196 读短簇几何+beam 双盲），故不打标，见上 docstring。
            continue
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
    if count > 0 or marked:
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return count


# ----------------------------------------------------------------------
# 拍号推断 + <time> 注入（方案1，2026-08-10）
# ----------------------------------------------------------------------
# 背景：oemer 不检测拍号 → pred MusicXML 无 <time> → C++ 渲染器回退默认 4/4
# （jianpu_postcorrect.cpp BeatReconcile 的 target = beats×4/beatType）。语料 15 页中
# 7 页拍号非 4/4（badinerie 2/4、summer×5 3/4、the-swan 6/4），导致标题拍号标签错 +
# 每小节节拍对账目标错。本模块用「几何 span + 时值 fill」双信号推断拍数，
# 把 <time><beats>N</beats><beat-type>4</beat-type></time> 注入首 <attributes>。
#
# 信号优先级与投票规则（2026-08-10 全量 15 页定稿，见 build/_meter_proto*.py）：
#   * span 信号（几何优先）：每小节非休止音符 x 极差 / 16 分单位 → 量化到
#     {2,3,4,6} 拍。sidecar↔MusicXML 映射完好的 9/11 有单位页全对；canon_p1 映射损坏
#     呈 8:5 vs 24:5 平票，被「top 必须严格 > 次票」拦下。
#   * fill 信号（时值兜底）：每小节每声部 ql 和（含 <forward>，不含 <chord>）→
#     就近整数拍。仅当 span 完全不可得（无单位/无 sidecar：swan-lake、the-swan）时采信。
#   * span 可得但不相干 → 直接弃判（映射可能损坏，fill 此时同样不可信），保留默认。
# 只推断 X/4 拍号（beats ∈ {2,3,4,6}）；语料无 8 分分母拍，非 X/4 拍不在 v1 范围。

_METER_SPAN_TO_BEATS = {8: 2, 12: 3, 16: 4, 24: 6}   # 16 分单位 span → 每拍
_METER_BEATS = frozenset(_METER_SPAN_TO_BEATS.values())
_METER_SPAN_TOL = 0.18          # span→拍量化相对容差
_METER_SPAN_MIN_VOTES = 3       # span 票下限（防极小页噪声）
_METER_FILL_MIN_VOTES = 3       # fill 票下限


def _first_divisions(root: ET.Element) -> int:
    """取首处 <attributes>/<divisions>（oemer 只在 measure 1 写，全局继承），默认 16。"""
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
    return divisions


def _measure_fill_ql(measure: ET.Element, divisions: int) -> List[float]:
    """每小节每声部时值和（quarterLength）；跳过 <chord> 内层音符，计入 <forward>。"""
    fills: Dict[str, float] = {}
    for el in measure:
        if el.tag == "forward":
            v = el.findtext("voice")
            if v is None:
                continue
            ql = _note_ql(el, divisions)
            if ql is not None:
                fills[v] = fills.get(v, 0.0) + ql
        elif el.tag == "note":
            if el.find("chord") is not None:
                continue
            v = el.findtext("voice")
            if v is None:
                continue
            ql = _note_ql(el, divisions)
            if ql is not None:
                fills[v] = fills.get(v, 0.0) + ql
    return [round(x, 2) for x in fills.values()]


def _meter_span_votes(musicxml_path: str, sidecar_path: str,
                      root: ET.Element, divisions: int
                      ) -> Tuple[Optional[float], "collections.Counter"]:
    """span 信号：返回 (unit, votes)；votes=Counter{beats: 小节数}。

    1:1 映射与 R-geo 完全一致（sidecar.notes 发射序 ↔ MusicXML 非休止 <note>
    文档序，跨小节不配对）。unit 校准失败 / sidecar 缺失 → (None, 空)。
    """
    if not sidecar_path or not os.path.isfile(sidecar_path):
        return None, collections.Counter()
    try:
        with open(sidecar_path, 'r', encoding='utf-8') as f:
            doc = SidecarDoc.from_dict(json.load(f))
    except Exception:  # noqa: BLE001  sidecar 损坏非致命，弃用 span 信号
        return None, collections.Counter()

    n_notes = len(doc.notes)
    records: List[Tuple[ET.Element, float, Optional[float], Optional[float]]] = []
    spans: List[float] = []
    i = 0
    for m in root.iter("measure"):
        pairs: List[Tuple[ET.Element, float]] = []
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
        if len(pairs) < 2:
            continue
        pairs.sort(key=lambda t: t[1])
        spans.append(pairs[-1][1] - pairs[0][1])
        for k, (note, x) in enumerate(pairs):
            g_prev = (x - pairs[k - 1][1]) if k > 0 else None
            g_next = (pairs[k + 1][1] - x) if k < len(pairs) - 1 else None
            records.append((note, x, g_prev, g_next))

    unit = _calibrate_unit(records, divisions)
    if unit is None or unit <= 0:
        return None, collections.Counter()
    votes: "collections.Counter" = collections.Counter()
    for s in spans:
        u = s / unit
        if not (4 <= u <= 40):
            continue
        b = min(_METER_SPAN_TO_BEATS, key=lambda c: abs(u - c))
        beats = _METER_SPAN_TO_BEATS[b]
        if abs(u - b) / b <= _METER_SPAN_TOL:
            votes[beats] += 1
    return unit, votes


def infer_meter(musicxml_path: str, sidecar_path: str = None) -> Optional[Tuple[int, int]]:
    """推断拍号 → ``(beats, beat_type)``；无可靠信号返回 None（调用方保留默认 4/4）。

    优先级：span 几何信号（相干才采）→ fill 时值信号（仅当 span 完全不可得）→ None。
    """
    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    _strip_ns(root)
    divisions = _first_divisions(root)

    unit, span_votes = _meter_span_votes(musicxml_path, sidecar_path, root, divisions)
    if unit is not None:
        # span 信号存在：相干 → 采信；不相干 → 弃判（不回落 fill）。
        # 相干 = 众数票 ≥ 下限 且 严格 > 次票（单候选视次票 0，全一致页仍采信）。
        ranked = span_votes.most_common(2)
        top_cnt = ranked[0][1] if ranked else 0
        runner_cnt = ranked[1][1] if len(ranked) > 1 else 0
        if top_cnt >= _METER_SPAN_MIN_VOTES and top_cnt > runner_cnt:
            return (ranked[0][0], 4)
        return None

    fill_votes: "collections.Counter" = collections.Counter()
    for m in root.iter("measure"):
        for x in _measure_fill_ql(m, divisions):
            r = round(x)
            if abs(x - r) < 0.1 and r in _METER_BEATS:
                fill_votes[r] += 1
    ranked = fill_votes.most_common(2)
    top_cnt = ranked[0][1] if ranked else 0
    runner_cnt = ranked[1][1] if len(ranked) > 1 else 0
    if top_cnt >= _METER_FILL_MIN_VOTES and top_cnt > runner_cnt:
        return (ranked[0][0], 4)
    return None


def inject_time_signature(musicxml_path: str, sidecar_path: str = None) -> Optional[Tuple[int, int]]:
    """推断并注入 ``<time>``（就地写回首 <attributes>），返回注入的 (beats, beat_type)。

    oemer 的 pred 无 <time>，此注入让 Pudu 渲染器（jianpu_converter 读 doc.beats/
    beatType）正确显示拍号，并给 BeatReconcile 每小节正确对账目标。幂等：已存在
    <time> 时只更新 beats/beat-type。推断失败 / 无 attributes → 不改文件，返回 None。
    """
    meter = infer_meter(musicxml_path, sidecar_path)
    if meter is None:
        return None
    beats, beat_type = meter

    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    _strip_ns(root)
    target = None
    for m in root.iter("measure"):
        target = m.find("attributes")
        if target is not None:
            break
    if target is None:
        return None

    time_el = target.find("time")
    if time_el is None:
        # MusicXML 3.1 attributes 子序：divisions, key, time, staves, clef, ...
        # 插到 <key> 之后；oemer 必有 <key>（未见则 append 兜底）。
        time_el = ET.Element("time")
        key_el = target.find("key")
        if key_el is not None:
            target.insert(list(target).index(key_el) + 1, time_el)
        else:
            target.append(time_el)
    for tag, val in (("beats", str(beats)), ("beat-type", str(beat_type))):
        el = time_el.find(tag)
        if el is None:
            el = ET.SubElement(time_el, tag)
        el.text = val

    try:
        ET.indent(tree, space="  ")   # 交付物可读性（Python 3.9+）
    except AttributeError:
        pass
    tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return (beats, beat_type)


# ----------------------------------------------------------------------
# 小节重切 + 节拍约束校验（方案4 / 方案2）
# 归因背景（2026-08-10，memory jianpu-attribution-reframe）：oemer 的小节分段
# 错误是简谱坏小节的**主导根因**——音符音高时值全对，只是被插/漏了纵线（铁证
# bach p1 开头：PRED m1-m4 与 GT m1-m2 音符集合完全一致，仅切成 2/14/4/12 vs
# 真 16/16）。方案4 拍号约束保守重切把边界重切到 target；方案2 校验每小节 fill
# 并打 footnote 兜底（重切门外页 / off-target 小节 / 残尾）。方案3（补休止）已
# 因 GT 欠填处 rest-sum==0 否决——缺的是错位/丢失的音符，不是休止。
# ----------------------------------------------------------------------

_METER_TARGET_TOL = 0.25          # 一个 16 分：重切切点偏差门与节拍校验容差
_REASON_MEASURE_BEATS = "小节节拍不符"
_RSLICE_MIN_MEASURES = 3          # 碎片页（<3 小节）不重切，拍号推断不可靠


def _meter_target(musicxml_path: str, sidecar_path: str = None) -> Optional[float]:
    """返回小节目标拍数（quarterLength）；无 <time> 且推断失败 → None。

    优先级：文件内既有 <time>（方案1 注入结果，与渲染器同源）→ infer_meter
    推断（span/fill 信号）→ None（调用方保留默认 4/4）。
    """
    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    _strip_ns(root)
    for a in root.iter("attributes"):
        t = a.find("time")
        if t is not None:
            b, bt = t.findtext("beats"), t.findtext("beat-type")
            if b and bt:
                try:
                    return float(b) * 4.0 / float(bt)
                except ValueError:
                    pass
            break
    meter = infer_meter(musicxml_path, sidecar_path)
    if meter is not None:
        return meter[0] * 4.0 / meter[1]
    return None


def re_slice_measures(musicxml_path: str, sidecar_path: str = None,
                      tol: float = _METER_TARGET_TOL) -> Optional[int]:
    """拍号约束保守重切：把小节边界重切到拍号 target（就地写回）。

    背景（2026-08-10 归因，见 build/_rslice_validate.py）：oemer 的小节分段错误
    是简谱坏小节的**主导根因**——音符音高时值全对，只是被插/漏了纵线。本函数把
    每声部音符流（chord 挂父、幻影 v2 并入主声部，小节内按 onset 排序）按 target
    贪心重切。

    保守门（对应产品决策「仅对 hard=0 的安全页生效」）：
        * 原小节数 ≥ _RSLICE_MIN_MEASURES（碎片页拍号不可靠）；
        * **所有**切点的累积偏差 |eps| ≤ tol（默认 0.25 = 1 个 16 分）。
      任一不满足 → 返回 None 不改文件（真丢失/大偏差页，问题留给
      :func:`mark_meter_constraint_failures` 打标，不猜边界）。
      eps ≤ tol 的 off-target 小节保留原内容，由该校验函数打标。

    重建语义：新小节 1..M 连续编号；首小节保留原 attributes（含方案1 注入的
    <time>）；每小节单声部、无 <forward>/<backup>；音符集合与
    <notations>/<footnote> 不变（footnote 随音符走）。尾部不足 target 的残段仍
    输出为末小节（内容缺失，诚实，交校验打标）。幂等：重切后再调用结构不变。

    Args:
        musicxml_path: 待重切 MusicXML（就地写回；仅结构有变时写）。
        sidecar_path: 可选，仅用于无 <time> 时的 meter 推断兜底。
        tol: 切点偏差门（quarterLength）。

    Returns:
        Optional[int]: 重切后小节数；gate 失败 / 无 target / 无音符 → None。
    """
    target = _meter_target(musicxml_path, sidecar_path)
    if target is None or target <= 0:
        return None

    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    _strip_ns(root)
    divisions = _first_divisions(root)

    orig_measures = list(root.iter("measure"))
    if len(orig_measures) < _RSLICE_MIN_MEASURES:
        return None

    # 1) 展平：逐 measure 收集非 chord 音符组（小节内按 onset 排序，幻影 v2 归并）
    groups = []            # [(onset, ql, parent_note, [chord_notes])]
    for part in root.iter("part"):
        for measure in part.iter("measure"):
            cursor = collections.defaultdict(float)
            pending = None
            local = []
            for el in measure:
                if el.tag in ("forward", "backup"):
                    v = el.findtext("voice")
                    ql = _note_ql(el, divisions)
                    if v is None or ql is None:
                        continue
                    cursor[v] += ql if el.tag == "forward" else -ql
                elif el.tag == "note":
                    v = el.findtext("voice") or "1"
                    ql = _note_ql(el, divisions)
                    if ql is None:
                        continue
                    if el.find("chord") is not None:
                        if pending is not None:
                            pending[3].append(el)
                        continue
                    on = cursor[v]
                    cursor[v] += ql
                    pending = [on, ql, el, []]
                    local.append(pending)
            local.sort(key=lambda g: g[0])
            groups.extend(local)
    if not groups:
        return None

    # 2) 贪心切：累积 ql 到 target 切；记录每切点 eps（硬切=内容错位/丢失）
    cuts = []
    eps_list = []
    cum = 0.0
    for i, g in enumerate(groups):
        cum += g[1]
        if cum >= target - 1e-9:
            cuts.append(i + 1)
            eps_list.append(cum - target)
            cum = 0.0
    if not cuts or any(abs(e) > tol for e in eps_list):
        return None

    # 3) 重建
    part_el = root.find("part")
    if part_el is None:
        return None
    first_attrs = None
    for m in orig_measures:
        a = m.find("attributes")
        if a is not None:
            first_attrs = a
            break
    for m in orig_measures:
        part_el.remove(m)

    def _set_voice(note: ET.Element) -> None:
        v = note.find("voice")
        if v is None:
            v = ET.SubElement(note, "voice")   # oemer 恒有 voice，防御兜底
        v.text = "1"

    segs = []
    start = 0
    for c in cuts:
        segs.append(groups[start:c])
        start = c
    if cum > 1e-9:          # 尾部残段仍输出为末小节（内容缺失，诚实）
        segs.append(groups[start:])
    for idx, seg in enumerate(segs, start=1):
        m = ET.SubElement(part_el, "measure", attrib={"number": str(idx)})
        if idx == 1 and first_attrs is not None:
            m.append(first_attrs)
        for _on, _ql, note, chord in seg:
            _set_voice(note)
            m.append(note)
            for c in chord:
                _set_voice(c)
                m.append(c)

    try:
        ET.indent(tree, space="  ")   # 交付物可读性（Python 3.9+）
    except AttributeError:
        pass
    tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return len(segs)


def mark_meter_constraint_failures(musicxml_path: str, sidecar_path: str = None,
                                   tol: float = _METER_TARGET_TOL) -> int:
    """每小节节拍约束校验 + footnote 标记（方案2 兜底，就地写回）。

    在重切门外（真丢失/大偏差/碎片页）或重切后的 off-target 小节、残尾上，
    oemer 的分段/丢失错误仍会造成「每小节节拍数不对」。本函数对每小节**总**
    fill（跨声部和，含休止）与拍号 target 对账：|fill - target| > tol → 在该小节
    首音符写 ``<footnote>需校对：小节节拍不符</footnote>``（幂等，review.json
    据此列出「需校对」面板）。对账用渲染器同源的 target（文件内 <time> →
    infer_meter → 默认 4/4）。

    Args:
        musicxml_path: 待校验 MusicXML（就地写回；仅产生标记时写）。
        sidecar_path: 可选，仅用于无 <time> 时的 meter 推断兜底。
        tol: 校验容差（quarterLength，默认一个 16 分）。

    Returns:
        int: 新打标的小节数。
    """
    target = _meter_target(musicxml_path, sidecar_path)
    if target is None:
        target = 4.0
    tree = ET.parse(musicxml_path)
    root = tree.getroot()
    _strip_ns(root)
    divisions = _first_divisions(root)

    changed = False
    marked = 0
    for measure in root.iter("measure"):
        fill = 0.0
        first_note = None
        for el in measure:
            if el.tag == "note":
                if el.find("chord") is not None:
                    continue
                ql = _note_ql(el, divisions)
                if ql is None:
                    continue
                fill += ql
                if first_note is None:
                    first_note = el
        if first_note is None:
            continue
        if abs(fill - target) > tol:
            if _mark_needs_review(first_note, _REASON_MEASURE_BEATS):
                changed = True
                marked += 1
    if changed:
        try:
            ET.indent(tree, space="  ")   # 交付物可读性（Python 3.9+）
        except AttributeError:
            pass
        tree.write(musicxml_path, encoding="UTF-8", xml_declaration=True)
    return marked


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
