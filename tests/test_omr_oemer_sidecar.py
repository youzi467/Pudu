# -*- coding: utf-8 -*-
"""F3 sidecar 提取 · 真实 oemer 0.1.8 输出形态单测。

QA（Edward）在真实协奏曲 A/B 中发现 2 个生产崩溃，根因是既有单测只
覆盖 mock 的 1D / list 输入，没跑真实 oemer 0.1.8 输出：

  * ``layers.get_layer('staffs')`` 是 **2D object ndarray**（shape
    ``[n_columns][n_substaffs]``，来自 ``align_staffs`` →
    ``np.array(List[List[Staff]])``）；旧代码当 1D ``Staff`` 序列遍历 →
    ``AttributeError: 'numpy.ndarray' object has no attribute 'track'``。
  * ``NoteHead.bbox`` 是 **numpy ndarray**（非 list）；旧 ``_bbox_center``
    用 ``if not bbox`` 真值判断 →
    ``ValueError: truth value of an array is ambiguous``。

本文件补一组**真实形态**单测，避免“CI 全绿却在真实数据上崩”：

  * ``_bbox_center`` / ``_safe_x`` / ``_ink_centroid`` 接受 numpy ndarray bbox；
  * ``_flatten_layer`` 把 2D object ndarray 正确展平为一维 Staff 列表；
  * ``_dump_geometry_sidecar`` 端到端：喂入 2D staffs ndarray + 真实形态
    ndarray bbox，断言不崩溃且 sidecar 的 staves/notes 计数正确。
"""
import os
import sys
import json
import unittest
import tempfile

import numpy as np

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_oemer  # noqa: E402

# oemer 仅在 ``_dump_geometry_sidecar`` 内部 ``from oemer import layers`` 时需要；
# 端到端测试通过 stub ``oemer.layers.get_layer`` 注入真实形态数据，故需 oemer
# 可导入。无 oemer 环境（如纯单测 CI）跳过该用例，其余用例仅依赖 numpy。
try:
    import oemer.layers as _oemer_layers_mod  # noqa: F401
    _OEMER_AVAILABLE = True
except Exception:  # noqa: BLE001
    _OEMER_AVAILABLE = False


# ============ 真实 oemer 0.1.8 形态的轻量替身（仅测试内构造） ============
class FakeLine:
    """模拟 oemer Line：y_center / y_upper / y_lower。"""

    def __init__(self, y_center):
        self.y_center = float(y_center)
        self.y_upper = self.y_center - 1.0
        self.y_lower = self.y_center + 1.0


class FakeStaff:
    """模拟 oemer Staff：lines / unit_size / track / group / y_center。"""

    def __init__(self, track, group, lines_y, unit_size=11.2):
        self.lines = [FakeLine(y) for y in lines_y]
        self.track = track
        self.group = group
        self.unit_size = float(unit_size)
        self.y_center = float(np.mean(lines_y))


class _ClefLabel:
    """模拟 oemer ClefType 枚举（带 .name 属性）。"""

    def __init__(self, name):
        self.name = name


class FakeClef:
    """模拟 oemer Clef：track / label（带 .name）/ bbox(ndarray) / x_center。"""

    def __init__(self, track, label_name):
        self.track = track
        self.label = _ClefLabel(label_name)
        self.x_center = 12.0
        # 真实 oemer 形态：bbox 是 numpy ndarray（非 list）
        self.bbox = np.array([2.0, 1200.0, 22.0, 1230.0], dtype=float)


class FakeNoteHead:
    """模拟 oemer NoteHead：bbox 为 ndarray（真实形态）；points 为 (y, x) 列表。"""

    def __init__(self, nid, track, group, bbox, points=None, slp=0, sfn=None):
        self.id = nid
        self.track = track
        self.group = group
        # 真实 oemer 形态：bbox 为 ndarray；None 保持 None（oemer 也允许 bbox=None）
        self.bbox = None if bbox is None else np.asarray(bbox, dtype=float)
        self.points = points if points is not None else []
        self.staff_line_pos = slp
        self.sfn = sfn
        self.invalid = False


def _make_staffs_2d():
    """构造 [n_columns][n_substaffs] 的 2D object ndarray（oemer 0.1.8 真实形态）。"""
    col0 = [FakeStaff(0, 0, [1256.0, 1244.8, 1233.6, 1222.4, 1211.2]),
            FakeStaff(1, 0, [1156.0, 1144.8, 1133.6, 1122.4, 1111.2])]
    col1 = [FakeStaff(0, 0, [1256.0, 1244.8, 1233.6, 1222.4, 1211.2]),
            FakeStaff(1, 0, [1156.0, 1144.8, 1133.6, 1122.4, 1111.2])]
    return np.array([col0, col1], dtype=object)


class TestBBoxCenterRealShapes(unittest.TestCase):
    def test_ndarray_bbox(self):
        # 真实 oemer 形态：numpy ndarray bbox（非 list）
        bbox = np.array([10.0, 1250.0, 30.0, 1270.0], dtype=float)
        cx, cy = omr_oemer._bbox_center(bbox)
        self.assertAlmostEqual(cx, 20.0)
        self.assertAlmostEqual(cy, 1260.0)

    def test_ndarray_bbox_int_dtype(self):
        bbox = np.asarray([10, 1250, 30, 1270])  # int 也应被安全转 float
        cx, cy = omr_oemer._bbox_center(bbox)
        self.assertAlmostEqual(cx, 20.0)
        self.assertAlmostEqual(cy, 1260.0)

    def test_none_bbox(self):
        cx, cy = omr_oemer._bbox_center(None)
        self.assertEqual((cx, cy), (0.0, 0.0))

    def test_empty_ndarray_bbox(self):
        # 真实 oemer 不会出现，但应健壮返回占位而非崩溃
        cx, cy = omr_oemer._bbox_center(np.array([]))
        self.assertEqual((cx, cy), (0.0, 0.0))

    def test_list_and_tuple_bbox_no_regression(self):
        # 旧单测形态（list / tuple）不应回归
        self.assertEqual(omr_oemer._bbox_center((10, 1250, 30, 1270)),
                         (20.0, 1260.0))
        self.assertEqual(omr_oemer._bbox_center([10, 1250, 30, 1270]),
                         (20.0, 1260.0))


class TestSafeXRealShapes(unittest.TestCase):
    def test_ndarray_bbox(self):
        nh = FakeNoteHead(0, 0, 0, [10.0, 1250.0, 30.0, 1270.0])
        self.assertAlmostEqual(omr_oemer._safe_x(nh), 20.0)

    def test_none_bbox(self):
        nh = FakeNoteHead(0, 0, 0, None)
        self.assertEqual(omr_oemer._safe_x(nh), 0.0)


class TestInkCentroidRealShapes(unittest.TestCase):
    def test_ndarray_bbox_fallback(self):
        # 无 points → 退化为 bbox 中心（ndarray bbox）
        nh = FakeNoteHead(0, 0, 0, [10.0, 1250.0, 30.0, 1270.0], points=[])
        cx, cy = omr_oemer._ink_centroid(nh)
        self.assertAlmostEqual(cx, 20.0)
        self.assertAlmostEqual(cy, 1260.0)

    def test_points_are_yd_x_order(self):
        # oemer points 存为 (y, x)
        nh = FakeNoteHead(0, 0, 0, [10, 1250, 30, 1270],
                          points=[(1250.0, 10.0), (1270.0, 30.0)])
        cx, cy = omr_oemer._ink_centroid(nh)
        self.assertAlmostEqual(cx, 20.0)
        self.assertAlmostEqual(cy, 1260.0)


class TestFlattenLayer(unittest.TestCase):
    def test_2d_object_ndarray(self):
        s = _make_staffs_2d()
        flat = omr_oemer._flatten_layer(s)
        self.assertEqual(len(flat), 4)  # 2 列 × 2 子谱表
        for obj in flat:
            self.assertIsInstance(obj, FakeStaff)

    def test_ragged_2d_grid_with_zero_fill(self):
        # 模拟 align_staffs 的 np.zeros(dtype=object) 填充形态：每格是
        # Staff 或标量 0 残留（真实 0.1.8 不出现，仅健壮性）。
        grid = np.zeros((2, 2), dtype=object)
        grid[0, 0] = FakeStaff(0, 0, [1256, 1244, 1233, 1222, 1211])
        grid[0, 1] = FakeStaff(1, 0, [1156, 1144, 1133, 1122, 1111])
        grid[1, 0] = FakeStaff(0, 0, [1256, 1244, 1233, 1222, 1211])
        grid[1, 1] = FakeStaff(1, 0, [1156, 1144, 1133, 1122, 1111])
        flat = omr_oemer._flatten_layer(grid)
        staffs = [o for o in flat if hasattr(o, "lines")]
        self.assertEqual(len(staffs), 4)

    def test_1d_passthrough(self):
        arr = np.array([FakeStaff(i, 0, [1256, 1244, 1233, 1222, 1211])
                        for i in range(3)], dtype=object)
        flat = omr_oemer._flatten_layer(arr)
        self.assertEqual(len(flat), 3)


@unittest.skipUnless(_OEMER_AVAILABLE, "oemer not importable in this env")
class TestDumpSidecarRealShapes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f3_sidecar_")
        self.mxl = os.path.join(self.tmp, "page1.musicxml")
        with open(self.mxl, "w", encoding="utf-8") as f:
            f.write('<score-partwise version="4.0"><part id="P1">'
                    '<measure number="1"></measure></part></score-partwise>')
        # 保证 _EMISSION_ORDER 干净（无 monkeypatch 注入）
        omr_oemer._EMISSION_ORDER = []

    def _stub_layers(self, staffs_2d, notes, clefs):
        fake = {
            "staffs": staffs_2d,
            "notes": np.array(notes, dtype=object),
            "clefs": np.array(clefs, dtype=object),
        }
        orig = _oemer_layers_mod.get_layer
        _oemer_layers_mod.get_layer = lambda name: fake[name]
        return orig

    def test_2d_staffs_and_ndarray_bbox(self):
        staffs_2d = _make_staffs_2d()  # 2 列 × 2 子谱表
        notes = [
            FakeNoteHead(0, 0, 0, [10.0, 1250.0, 30.0, 1270.0],
                         points=[(1256.0, 20.0)], slp=1),
            FakeNoteHead(1, 1, 0, [40.0, 1150.0, 60.0, 1170.0],
                         points=[(1156.0, 50.0)], slp=0),
        ]
        clefs = [FakeClef(0, "G_CLEF"), FakeClef(1, "F_CLEF")]
        orig = self._stub_layers(staffs_2d, notes, clefs)
        try:
            sidecar = omr_oemer._dump_geometry_sidecar(self.mxl)
        finally:
            _oemer_layers_mod.get_layer = orig

        self.assertTrue(os.path.exists(sidecar), "sidecar 应被写出")
        with open(sidecar, "r", encoding="utf-8") as f:
            doc = json.load(f)
        # 2 列 × 2 子谱表 = 4 个 StaffGeometry，且未因 2D 遍历崩溃
        self.assertEqual(len(doc["staves"]), 4)
        # 两个音符均被捕获（ndarray bbox 不崩溃）
        self.assertEqual(len(doc["notes"]), 2)
        # 谱号类型正确推导
        types = {c["type"] for c in doc["clefs"]}
        self.assertEqual(types, {"G", "F"})

    def test_ragged_2d_grid_skips_non_staff(self):
        # 1 格填 0（模拟 np.zeros 残留），其余填 Staff：
        # flatten 后 _dump_geometry_sidecar 应跳过无 lines 的元素。
        grid = np.zeros((2, 2), dtype=object)
        grid[0, 0] = FakeStaff(0, 0, [1256, 1244, 1233, 1222, 1211])
        grid[0, 1] = FakeStaff(1, 0, [1156, 1144, 1133, 1122, 1111])
        grid[1, 0] = FakeStaff(0, 0, [1256, 1244, 1233, 1222, 1211])
        grid[1, 1] = 0  # 非 Staff 填充 -> 应被跳过
        notes = [FakeNoteHead(0, 0, 0, [10.0, 1250.0, 30.0, 1270.0], slp=1)]
        clefs = [FakeClef(0, "G_CLEF")]
        orig = self._stub_layers(grid, notes, clefs)
        try:
            sidecar = omr_oemer._dump_geometry_sidecar(self.mxl)
        finally:
            _oemer_layers_mod.get_layer = orig
        with open(sidecar, "r", encoding="utf-8") as f:
            doc = json.load(f)
        # 4 格中 3 个是 Staff，0 填充被跳过
        self.assertEqual(len(doc["staves"]), 3)
        self.assertEqual(len(doc["notes"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
