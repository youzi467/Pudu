# -*- coding: utf-8 -*-
"""R-geo 几何感知时值校正单测：校准门控 + 双侧判定 + 只缩不伸 + dot 移除。

背景（2026-08-09 全量 A/B 归因，docs/f3-abtest.md §R-geo）：oemer 的 duration 在
快速乐句上普遍「读长」（16分→4/8分 ×334、16分→8分 ×265、8分→4分 ×70，占 771 个
rhythm 失败的 87%）。sidecar 里符头 onset 间距与时值成精确比例，可按间距反推。

关键设计决策（本文件覆盖的边界）：
  1. 校准门控：仅用 oemer 读出的 16 分音符（quarterLength==0.25）作锚点，不足
     ``_MIN_RHYTHM_CALIBRATION=40`` 个 → 整页跳过（返回 0 不改文件）。8 分/32 分
     兜底已移除（the-swan 靠兜底净亏 -6 的根因）。
  2. 双侧判定：两侧一致 → 该 class 可信；一侧 ≥4 倍级更大 → 快音符贴慢音符，取快
     class；其余不一致 → 保守取大 class（防把真 8 分/4 分误缩成 16 分）。
  3. 只缩不伸：仅当 ``0.25*class < oemer 当前 ql`` 时改写；绝不伸长。
  4. 改写同步更新 ``<duration>``/``<type>``、移除 ``<dot>``，保持 MusicXML 自洽。

本文件纯 stdlib（xml.etree.ElementTree + json），不依赖 oemer / numpy。
"""
import json
import os
import sys
import tempfile
import unittest

import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import geometric_pitch as gp  # noqa: E402


# ===================== 测试辅助 =====================
DIVISIONS = 16  # 1 分音符 = 16 单位；16 分 = 4、8 分 = 8、4 分 = 16

# 几何约定（纯相对）：unit=10px = 1 个 16 分间距
UNIT = 10.0


def _ql_to_dur(ql):
    return int(ql * DIVISIONS)


def build_score(notes_spec):
    """构造最小 score-partwise。

    Args:
        notes_spec: 元素为 dict：
            - ``ql``: quarterLength（决定 ``<duration>``）
            - ``measure``: 小节号（默认 1）
            - ``x``: 该音符的几何 x（默认按出现序 10/20/30...）
            - ``rest``: True 表示休止符（无 duration 几何）
            - ``dot``: True 表示 ``<dot/>``（测试移除）
            - ``type``: 显式 ``<type>`` 文本（默认按 ql 映射）
    """
    root = ET.Element("score-partwise")
    part = ET.SubElement(root, "part", attrib={"id": "P1"})
    measures = {}
    for spec in notes_spec:
        num = str(spec.get("measure", 1))
        if num not in measures:
            m = ET.SubElement(part, "measure", attrib={"number": num})
            if num == "1":
                attrs = ET.SubElement(m, "attributes")
                ET.SubElement(attrs, "divisions").text = str(DIVISIONS)
            measures[num] = m
        note = ET.SubElement(measures[num], "note")
        if spec.get("rest"):
            ET.SubElement(note, "rest")
            continue
        ET.SubElement(note, "duration").text = str(_ql_to_dur(spec["ql"]))
        tp = spec.get("type")
        if tp is None:
            tp = {0.25: "16th", 0.5: "eighth", 1.0: "quarter"}.get(spec["ql"])
        if tp:
            ET.SubElement(note, "type").text = tp
        if spec.get("dot"):
            ET.SubElement(note, "dot")
    return root


def build_sidecar(root, notes_spec):
    """从根元素 + notes_spec 构造 sidecar JSON dict（发射序 1:1 = 非休止音符文档序）。"""
    g_notes = []
    idx = 0
    for spec in notes_spec:
        if spec.get("rest"):
            continue
        x = spec.get("x", (idx + 1) * UNIT)
        g_notes.append({
            "id": idx,
            "track": 0,
            "group": 0,
            "bbox": [x, 95.0, x + 5.0, 105.0],
            "center": [x, 100.0],
            "ink_centroid": [x, 100.0],
            "staff_line_pos": 1,
            "sfn": None,
        })
        idx += 1
    doc = {
        "schema_version": 1,
        "source_image": "test.png",
        "musicxml": "test.musicxml",
        "coordinate_space": "pixel_model",
        "note_order": "oemer_emission",
        "staves": [{
            "staff_id": 0, "track": 0, "group": 0, "unit_size": 10.0,
            "y_center": 100.0,
            "lines": [{"y_center": 120.0, "thickness": 1.0},
                      {"y_center": 110.0, "thickness": 1.0},
                      {"y_center": 100.0, "thickness": 1.0},
                      {"y_center": 90.0, "thickness": 1.0},
                      {"y_center": 80.0, "thickness": 1.0}],
        }],
        "clefs": [{"track": 0, "type": "G"}],
        "notes": g_notes,
    }
    return doc


def run_rgeo(root, notes_spec):
    """把 score + sidecar 写盘后调用 recompute_rhythm_from_geometry。

    Returns:
        (rewrite_count, root)  root 为改写后的根元素。
    """
    fd, mx_path = tempfile.mkstemp(suffix=".musicxml")
    os.close(fd)
    sc_path = mx_path.replace(".musicxml", ".geometry.json")
    try:
        ET.ElementTree(root).write(mx_path, encoding="UTF-8", xml_declaration=True)
        with open(sc_path, "w", encoding="utf-8") as f:
            json.dump(build_sidecar(root, notes_spec), f)
        n = gp.recompute_rhythm_from_geometry(mx_path, sc_path)
        tree = ET.parse(mx_path)
        r = tree.getroot()
        gp._strip_ns(r)
        return n, r
    finally:
        for p in (mx_path, sc_path):
            if os.path.exists(p):
                os.remove(p)


def read_qls(root):
    """读取所有非休止音符的 (quarterLength, has_dot, type)。"""
    out = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue
        dur = note.find("duration")
        if dur is None or dur.text is None:
            continue
        ql = int(dur.text) / DIVISIONS
        has_dot = note.find("dot") is not None
        tp = note.find("type")
        out.append((ql, has_dot, tp.text if tp is not None else None))
    return out


def _notes(count, ql, **kw):
    """count 个 ql 音符的 spec 列表（默认 x 连续 10/20/...）。"""
    return [{"ql": ql, **kw} for _ in range(count)]


# ===================== 校准门控 =====================
class TestCalibrationGate(unittest.TestCase):
    """校准锚点不足 → 跳过整页；不足 40 个 16 分锚点不兜底。"""

    @staticmethod
    def _records(qls):
        """构造 (note_el, x, g_prev, g_next) 记录列表（等比间距 UNIT）。"""
        out = []
        n = len(qls)
        for i, ql in enumerate(qls):
            note = ET.Element("note")
            ET.SubElement(note, "duration").text = str(_ql_to_dur(ql))
            out.append((note, (i + 1) * UNIT,
                        UNIT if i > 0 else None,
                        UNIT if i < n - 1 else None))
        return out

    def test_below_min_returns_none(self):
        """16 分锚点 < 40 → _calibrate_unit 返回 None（跳过整页）。"""
        # 30 个 oemer-16 分 + 2 个 8 分（旧兜底路径会拿 8 分/2 校准，现在不兜底）
        records = self._records([0.25] * 30 + [0.5] * 2)
        self.assertIsNone(gp._calibrate_unit(records, DIVISIONS))

    def test_at_least_min_returns_median(self):
        """16 分锚点 ≥ 40 → 返回中位数。"""
        records = self._records([0.25] * 40)
        self.assertAlmostEqual(gp._calibrate_unit(records, DIVISIONS), UNIT)

    def test_no_16th_anchors_returns_none(self):
        """整页无 16 分锚点（旧 8 分/2 兜底场景）→ 返回 None，不再兜底。"""
        records = self._records([0.5] * 50)  # 全是 8 分，无 16 分
        self.assertIsNone(gp._calibrate_unit(records, DIVISIONS))


# ===================== 双侧判定 / 只缩不伸 =====================
class TestRhythmRewrite(unittest.TestCase):
    """recompute_rhythm_from_geometry 的核心改写行为。"""

    def _build(self, notes_spec):
        root = build_score(notes_spec)
        n, r = run_rgeo(root, notes_spec)
        return n, r

    def test_basic_shorten_16th_grid(self):
        """统一 16 分网格：40 个 16 分锚点 + 4 个被读长的 4 分 → 4 分被缩回 16 分。"""
        # 44 个音符全部等距 10px；前 40 个 oemer 读 16 分（锚点 unit=10），
        # 后 4 个 oemer 读 4 分 → 两侧 class=1 → 缩回 0.25
        notes = _notes(40, 0.25) + _notes(4, 1.0)
        n, r = self._build(notes)
        self.assertEqual(n, 4)
        qls = read_qls(r)
        # 前 40 保持 16 分；后 4 缩成 16 分
        self.assertTrue(all(abs(q - 0.25) < 1e-9 for q, _, _ in qls[:40]))
        self.assertTrue(all(abs(q - 0.25) < 1e-9 for q, _, _ in qls[40:]))

    def test_only_shorten_never_lengthen(self):
        """只缩不伸：几何间距对应 4 分、oemer 已读 16 分 → 不动（绝不伸长）。"""
        # 4 分间距 = 40px；oemer 全读 16 分。前 40 个锚点按 10px 校准。
        # 但混排会污染…… 用独立构造：40 个 16 分锚点 10px 间距 + 2 个 40px 间距的 16 分
        notes = _notes(40, 0.25, x=10) + _notes(2, 0.25, x=0)
        # 手动指定 x：前 40 在 10/20/.../400，后 2 个 x 为 410/450 → 后者间距 40px
        notes = []
        for i in range(40):
            notes.append({"ql": 0.25, "x": (i + 1) * UNIT})
        notes.append({"ql": 0.25, "x": 42 * UNIT})      # 与前一音距 2*UNIT
        notes.append({"ql": 0.25, "x": 48 * UNIT})      # 与前一音距 6*UNIT
        n, r = self._build(notes)
        # 锚点校准仍为 10px（中位数）；最后两音间距大 → class 4 / class 6
        # class 4: new_ql=1.0 >= old 0.25 → 不动；class 6 非标准 → 跳过
        self.assertEqual(n, 0)
        qls = read_qls(r)
        self.assertTrue(all(abs(q - 0.25) < 1e-9 for q, _, _ in qls))

    def test_both_sides_consistent_takes_class(self):
        """两侧一致（class 1）→ 缩到 16 分。"""
        notes = _notes(40, 0.25) + [{"ql": 1.0}]       # 最后 1 个 4 分，两侧 10px
        n, r = self._build(notes)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(read_qls(r)[-1][0], 0.25)

    def test_fast_touching_slow_takes_fast(self):
        """一侧 4 倍级更大（16 分贴 4 分边界）→ 取快 class（16 分）。"""
        # 40 个 16 分锚点 10px；末尾一个被读成 4 分的 16 分，其右邻距 40px（一个 4 分）
        notes = _notes(40, 0.25)
        # 41 号：x=41*UNIT，左邻距 10px、右邻距 40px（42 号）
        notes.append({"ql": 1.0, "x": 41 * UNIT})
        notes.append({"ql": 1.0, "x": 45 * UNIT})       # 与 41 号距 40px
        n, r = self._build(notes)
        # 41 号：左 class 1、右 class 4 → 4>=4*1 → 取快 class 1 → 缩到 16 分
        self.assertEqual(n, 1)
        self.assertAlmostEqual(read_qls(r)[40][0], 0.25)

    def test_disagree_below_4x_takes_larger(self):
        """两侧不一致但 <4 倍（16 分/8 分边界）→ 保守取大 class（8 分，不误缩成 16 分）。"""
        # 40 个 16 分锚点；末尾一个被读成 4 分的「真 8 分」，左邻距 10px(16分)、
        # 右邻距 20px(8分)。classes=[1,2]，2 < 4*1 → 取大 class=2 → 缩到 8 分而非 16 分
        notes = _notes(40, 0.25)
        notes.append({"ql": 1.0, "x": 41 * UNIT})       # 左邻 10px
        notes.append({"ql": 0.5, "x": 43 * UNIT})       # 与 41 号距 20px
        n, r = self._build(notes)
        self.assertEqual(n, 1)
        # 41 号被缩到 8 分（0.5），不是 16 分（0.25）
        self.assertAlmostEqual(read_qls(r)[40][0], 0.5)

    def test_dot_removed(self):
        """改写时同步移除 <dot/> 并更新 <type>。"""
        notes = _notes(40, 0.25) + [{"ql": 1.0, "dot": True}]
        n, r = self._build(notes)
        self.assertEqual(n, 1)
        ql, has_dot, tp = read_qls(r)[-1]
        self.assertAlmostEqual(ql, 0.25)
        self.assertFalse(has_dot)
        self.assertEqual(tp, "16th")

    def test_rest_not_affected(self):
        """休止符不参与映射，也不被改写。"""
        # 40 个 16 分锚点 + 1 个休止符 + 1 个被读长的 4 分
        notes = _notes(40, 0.25) + [{"rest": True}] + [{"ql": 1.0}]
        n, r = self._build(notes)
        self.assertEqual(n, 1)
        qls = read_qls(r)
        self.assertEqual(len(qls), 41)
        self.assertAlmostEqual(qls[-1][0], 0.25)

    def test_sidecar_missing_nonfatal(self):
        """sidecar 缺失 → 返回 0 不改文件（非致命）。"""
        fd, mx_path = tempfile.mkstemp(suffix=".musicxml")
        os.close(fd)
        try:
            with open(mx_path, "w", encoding="utf-8") as f:
                f.write("<score-partwise><part/></score-partwise>")
            n = gp.recompute_rhythm_from_geometry(
                mx_path, mx_path.replace(".musicxml", ".geometry.json"))
            self.assertEqual(n, 0)
        finally:
            if os.path.exists(mx_path):
                os.remove(mx_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
