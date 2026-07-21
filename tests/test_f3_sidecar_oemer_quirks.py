# -*- coding: utf-8 -*-
"""F3 sidecar 提取 · oemer 0.1.8 真实形态回归测试（无需真实 oemer / GPU）。

QA 在 concerto 实拍页 p1–p6（oemer 0.1.8）做 A/B 时发现 F3 sidecar 路径
**100% 崩溃**，根因是 omr_oemer.py 假设 get_layer 返回 1D 对象序列，但真实
oemer 0.1.8 的形态是：

  * get_layer('staffs') 返回 **2D object ndarray**（shape [n_columns][n_substaffs]，
    来自 align_staffs → np.array(List[List[Staff]])）。旧代码 `for st in staffs_arr`
    拿到的 `st` 其实是一整列（ndarray），`st.track` → AttributeError。
  * NoteHead.bbox 是 **numpy ndarray** [x1,y1,x2,y2]；旧 `_bbox_center` 用
    `if not bbox` 判空 → "truth value of an array is ambiguous" ValueError。

两个 bug 必须**一起**修复一起测：Bug#1 的 staffs 在 Bug#2 之前先崩，单独修
Bug#1 会立刻暴露 Bug#2。

本测试不安装真实 oemer：把一个 fake `oemer` 模块注入 sys.modules，
`.layers.get_layer(name)` 返回与 0.1.8 一致的真实形状，从而精确复现 QA 的
崩溃模式（CI 之前的单测只 mock 了 1D/list，没覆盖到，故绿但线上崩）。
"""

import os
import sys
import json
import types
import unittest
import tempfile

import numpy as np

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_oemer  # noqa: E402  (模块级不 import oemer，可安全导入)


# ----------------------- fake oemer 0.1.8 对象 -----------------------

class _FakeSfn:
    """模仿 oemer 的 SfnType 枚举（仅用 .name）。"""
    def __init__(self, name):
        self.name = name


class _FakeLine:
    def __init__(self, y_center):
        self.y_center = float(y_center)
        self.y_upper = float(y_center) - 1.0
        self.y_lower = float(y_center) + 1.0


class _FakeStaff:
    """模仿 oemer Staff：lines / track / group / unit_size / y_center。"""
    def __init__(self, track, y_bottom, unit_size=20.0, group=0):
        # 5 条线，自下而上均匀排布
        self.lines = [_FakeLine(y_bottom - i * unit_size) for i in range(5)]
        self.track = track
        self.group = group
        self.unit_size = float(unit_size)
        self.y_center = float(y_bottom - 2.0 * unit_size)


class _FakeNoteHead:
    """模仿 oemer NoteHead：bbox(ndarray) / points(ndarray (y,x)) / staff_line_pos /
    track / group / id / sfn / invalid。"""
    def __init__(self, nid, x1, y1, x2, y2, staff_line_pos, track=0, group=0,
                 points=None, sfn=None, invalid=False):
        self.id = nid
        # 关键：bbox 是 numpy ndarray（真实 0.1.8 形态）
        self.bbox = np.array([x1, y1, x2, y2], dtype=float)
        # points 存为 (y, x) 元组序列，这里用 ndarray Nx2
        if points is None:
            pts = np.array([[ (y1 + y2) / 2.0, (x1 + x2) / 2.0 ]], dtype=float)
        else:
            pts = np.asarray(points, dtype=float).reshape(-1, 2)
        self.points = pts
        self.staff_line_pos = staff_line_pos
        self.track = track
        self.group = group
        self.sfn = sfn
        self.invalid = invalid


class _FakeClef:
    """模仿 oemer Clef：track / label(ClefType.name) / bbox(ndarray) / x_center。"""
    def __init__(self, track, label_name, x_center, y_center):
        self.track = track
        self.label = _FakeSfn(label_name)
        self.bbox = np.array([x_center - 5.0, y_center - 8.0,
                              x_center + 5.0, y_center + 8.0], dtype=float)
        self.x_center = float(x_center)


def _make_fake_oemer():
    """构造并返回注入 sys.modules 的 fake oemer 模块，get_layer 返回真实形态。"""
    notes = [
        _FakeNoteHead(0, 100.0, 200.0, 120.0, 220.0, staff_line_pos=4, track=0, group=0,
                      sfn=_FakeSfn("NATURAL")),
        _FakeNoteHead(1, 140.0, 180.0, 160.0, 200.0, staff_line_pos=5, track=0, group=0,
                      sfn=None),
        _FakeNoteHead(2, 200.0, 260.0, 220.0, 280.0, staff_line_pos=2, track=1, group=1,
                      sfn=_FakeSfn("SHARP")),
    ]
    # 关键回归：staffs 必须是 **2D object ndarray**（[n_columns][n_substaffs]）
    staffs = np.empty((2, 2), dtype=object)
    staffs[0, 0] = _FakeStaff(track=0, y_bottom=300.0, unit_size=20.0, group=0)
    staffs[0, 1] = _FakeStaff(track=1, y_bottom=300.0, unit_size=20.0, group=0)
    staffs[1, 0] = _FakeStaff(track=2, y_bottom=560.0, unit_size=20.0, group=1)
    staffs[1, 1] = _FakeStaff(track=3, y_bottom=560.0, unit_size=20.0, group=1)

    clefs = [
        _FakeClef(track=0, label_name="G_CLEF", x_center=60.0, y_center=240.0),
        _FakeClef(track=1, label_name="F_CLEF", x_center=60.0, y_center=520.0),
    ]

    def get_layer(name):
        layers = {
            "notes": notes,
            "staffs": staffs,   # 2D ndarray —— 触发原 Bug#1
            "clefs": clefs,
        }
        return layers[name]

    layers_mod = types.ModuleType("oemer.layers")
    layers_mod.get_layer = get_layer

    oemer_mod = types.ModuleType("oemer")
    oemer_mod.layers = layers_mod
    sys.modules["oemer"] = oemer_mod
    sys.modules["oemer.layers"] = layers_mod
    return oemer_mod


class F3SidecarOemerQuirksTest(unittest.TestCase):
    def setUp(self):
        # 注入 fake oemer（必须在调用 _dump_geometry_sidecar 之前）
        self._oemer = _make_fake_oemer()
        # 模拟发射序捕获成功：notes 按 id 顺序
        omr_oemer._EMISSION_ORDER = [0, 1, 2]

    def tearDown(self):
        sys.modules.pop("oemer", None)
        sys.modules.pop("oemer.layers", None)
        omr_oemer._EMISSION_ORDER = []

    def test_dump_geometry_sidecar_oemer_018_shapes(self):
        """核心回归：oemer-0.1.8 真实形态下，sidecar 提取不崩且 JSON 合法。"""
        tmp = tempfile.mkdtemp(prefix="f3_quirks_")
        mxl = os.path.join(tmp, "fake.musicxml")

        # 关键断言：整个过程不得抛 AttributeError / ValueError
        sidecar = omr_oemer._dump_geometry_sidecar(mxl)

        self.assertTrue(os.path.isabs(sidecar) or sidecar.endswith(".geometry.json"))
        self.assertTrue(os.path.exists(sidecar), "sidecar 文件应被写出")

        with open(sidecar, "r", encoding="utf-8") as f:
            doc = json.load(f)

        # staves：2D staffs 必须被展平，得到 4 个 Staff（不是 2 个列）
        self.assertEqual(len(doc["staves"]), 4,
                         "2D staffs ndarray 应被展平为 4 个 staff")
        tracks = sorted(s["track"] for s in doc["staves"])
        self.assertEqual(tracks, [0, 1, 2, 3])

        # notes：数量对齐发射序中的有效音符（3 个，全部 valid）
        self.assertEqual(len(doc["notes"]), 3,
                         "notes 应与发射序 1:1 对齐")
        ids = sorted(n["id"] for n in doc["notes"])
        self.assertEqual(ids, [0, 1, 2])

        # bbox 为 numpy ndarray → center 计算不应全 0（否则说明真值判空崩过）
        for n in doc["notes"]:
            cx, cy = n["center"]
            self.assertNotEqual((cx, cy), (0.0, 0.0),
                                "ndarray bbox 的中心不应是 (0,0) 兜底")
        # staff_line_pos 被原样透传
        self.assertEqual(doc["notes"][0]["staff_line_pos"], 4)

        # clefs 解析
        self.assertEqual(len(doc["clefs"]), 2)
        types_ = sorted(c["type"] for c in doc["clefs"])
        self.assertEqual(types_, ["F", "G"])

    def test_flatten_layer_2d(self):
        """单测 _flatten_layer：2D ndarray → 1D 列表。"""
        arr2d = np.empty((2, 2), dtype=object)
        a, b, c, d = object(), object(), object(), object()
        arr2d[0, 0], arr2d[0, 1] = a, b
        arr2d[1, 0], arr2d[1, 1] = c, d
        flat = omr_oemer._flatten_layer(arr2d)
        self.assertEqual(flat, [a, b, c, d])

    def test_flatten_layer_1d(self):
        """单测 _flatten_layer：1D 序列原样 list()。"""
        arr1d = np.array([1, 2, 3], dtype=object)
        self.assertEqual(omr_oemer._flatten_layer(arr1d), [1, 2, 3])

    def test_bbox_center_ndarray(self):
        """单测 _bbox_center 对 ndarray bbox 不崩（Bug#2）。"""
        out = omr_oemer._bbox_center(np.array([10.0, 20.0, 30.0, 40.0]))
        self.assertEqual(out, (20.0, 30.0))
        self.assertEqual(omr_oemer._bbox_center(None), (0.0, 0.0))
        self.assertEqual(omr_oemer._bbox_center(np.array([])), (0.0, 0.0))

    def test_safe_x_ndarray(self):
        """单测 _safe_x 对 ndarray bbox 不崩（Bug#2 同类）。"""
        out = omr_oemer._safe_x(_FakeNoteHead(0, 10.0, 20.0, 30.0, 40.0, 0))
        self.assertEqual(out, 20.0)
        self.assertEqual(omr_oemer._safe_x(_FakeNoteHead(0, 0, 0, 0, 0, 0)), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
