# -*- coding: utf-8 -*-
"""fix (a) oemer align_staffs 空 staff 守卫 桩测试（不依赖真 oemer）。

Bug A 根因：enhanced 图喂给 oemer 时，align_staffs 在 len_types 为空时对
``max(len_types)`` 抛 ``ValueError: max() iterable argument is empty``，5 个
preset 100% 崩。

补丁 #7 在 max() 之前插入守卫：len_types 为空时抛出 oemer 自有的
StafflineException（可类型化 catch）。本文件用最小桩复刻该逻辑并验证 patch 产物：

  G1. 空 len_types -> 抛 StafflineException（不再裸崩 max()）；
  G2. 非空 len_types -> 正常走到 max()（守卫不误伤正常路径）；
  G3. patch 文件存在、行尾为 LF、守卫代码落点正确（if not len_types / raise
      E.StafflineException）；
  G4. manifest（oemer-0.1.8.checksums.json）可被 load_manifest 解析，
      staffline_extraction.py 含 2 级 stages 且链尾 sha == patched_sha、
      首级 from == original。
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
PATCHES = os.path.join(REPO_ROOT, "third_party", "oemer-patches")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class StafflineException(Exception):
    """桩：模拟 oemer.exceptions.StafflineException（可类型化 catch）。"""


def align_staffs_stub(staffs):
    """复刻 oemer.staffline_extraction.align_staffs 的关键片段（含补丁 #7 守卫）。

    Args:
        staffs: list[list[...]]，每列一个子 staff 列表。

    Returns:
        同构的 staff 结构；守卫命中时抛 StafflineException。
    """
    len_types = set(len(st_part) for st_part in staffs)
    if len(len_types) == 1:
        return list(staffs)
    # [Pudu patch #7] 守卫：空 staff 列表不再裸崩 max()
    if not len_types:
        raise StafflineException(
            "align_staffs received an empty staff list: no staff line column "
            "was detected on this page (blank page or over-processed input).")
    max_len = max(len_types)  # 原崩溃点
    return max_len


class AlignStaffsGuardStubTest(unittest.TestCase):

    def test_empty_len_types_raises_typed_exception(self):
        with self.assertRaises(StafflineException) as ctx:
            align_staffs_stub([])
        self.assertIn("empty staff list", str(ctx.exception))

    def test_nonempty_len_types_proceeds(self):
        # 两列均为 5 行 -> len_types={5}，走 len==1 分支返回
        self.assertEqual(align_staffs_stub([[1] * 5, [1] * 5]), [[1] * 5, [1] * 5])
        # 两列不同长度 -> len_types={3,5}，守卫不命中，走到 max()==5
        self.assertEqual(align_staffs_stub([[1, 2, 3], [1, 2, 3, 4, 5]]), 5)

    def test_patch_file_exists_and_is_lf(self):
        patch = os.path.join(PATCHES, "staffline_extraction.py.align_staffs.patch")
        self.assertTrue(os.path.isfile(patch), "补丁 #7 文件缺失")
        raw = open(patch, "rb").read()
        self.assertNotIn(b"\r\n", raw, "补丁文件须为 LF 行尾")
        text = raw.decode("utf-8")
        self.assertIn("if not len_types:", text, "守卫代码缺失")
        self.assertIn("E.StafflineException", text, "应抛 oemer 自有异常")
        self.assertIn("raise", text)

    def test_manifest_loads_with_two_stage_chain(self):
        from oemer_patch_lib import load_manifest
        version, specs = load_manifest(REPO_ROOT)
        self.assertEqual(version, "0.1.8")
        by_file = {s.file: s for s in specs}
        self.assertIn("staffline_extraction.py", by_file)
        spec = by_file["staffline_extraction.py"]
        self.assertEqual(len(spec.chain), 2,
                         "staffline_extraction.py 应有 2 级增量补丁链")
        # 链尾 sha == patched_sha256_lf
        self.assertEqual(spec.chain[-1].to_sha256_lf, spec.patched_sha256_lf)
        # 首级 from == original
        self.assertEqual(spec.chain[0].from_sha256_lf, spec.original_sha256_lf)
        # 第 7 点守卫补丁文件名存在且 LF
        stage2 = spec.chain[1]
        self.assertTrue(os.path.isfile(os.path.join(PATCHES, stage2.patch_file)))


if __name__ == "__main__":
    unittest.main()
