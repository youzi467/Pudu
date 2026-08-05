# -*- coding: utf-8 -*-
"""fix (a) 增量补丁链（schema v2）纯逻辑测试：decide_state / apply_patch / 链校验。

不依赖真 oemer wheel：用一段合成源码 + 两级合成 .patch，验证 staged 模型
在三态判定与 apply 上的行为：

  C1. decide_state：original→CLEAN(idx0)；mid→CLEAN(idx1)；tail→ALREADY；
      other→DRIFT。
  C2. apply_patch：从 original 起连续 apply 两级，终态 sha == stage2.to；
      幂等：再次 apply → SKIPPED。
  C3. 从 mid 起只 apply 第 2 级即达终态（现网已 6 点补丁的升级路径）。
  C4. check_only：不修改文件且返回 SKIPPED（read-only）。
  C5. _validate_chain：合法链通过；断裂链（相邻级首尾不接）抛 ValueError。
"""

import difflib
import hashlib
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from oemer_patch_lib import (  # noqa: E402
    ApplyOutcome, FileState, PatchSpec, PatchStage,
    apply_patch, decide_state, lf_normalized_sha256, _validate_chain,
)

GIT_AVAILABLE = shutil.which("git") is not None


def _lf_sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# 合成源码（CRLF 无关，统一 LF）
SRC_ORIG = b"line1\nline2\nline3\n"
SRC_MID = b"line1\nline2-patched-a\nline3\n"
SRC_TAIL = b"line1\nline2-patched-a\nline3-patched-b\n"


# 被打补丁的合成文件名。必须与 PatchSpec.file 以及 diff 头里
# ``a/``/``b/`` 前缀之后的路径**逐字节一致**——apply_patch 是以 oemer 包目录
# 为 cwd 调 ``git apply -p1``，-p1 剥掉一层前缀后剩下的路径就是 git 要在
# cwd 下寻找的目标文件。两者不一致会得到
# ``error: <name>: No such file or directory``。
SYNTH_FILE = "a.py"


def _patch(from_text: bytes, to_text: bytes) -> bytes:
    """生成 from_text -> to_text 的 unified diff（单文件，路径 a/a.py）。

    用 ``a/<SYNTH_FILE>`` / ``b/<SYNTH_FILE>`` 形式，使 ``git apply -p1`` 剥掉
    ``a/`` 前缀后正好得到 ``SYNTH_FILE``（与真实 oemer patch 同款 ``a/`` 前缀
    约定，见 staffline_extraction.py.align_staffs.patch 的 ``--- a/…`` 头）。
    """
    diff = difflib.unified_diff(
        from_text.decode().splitlines(keepends=True),
        to_text.decode().splitlines(keepends=True),
        fromfile=f"a/{SYNTH_FILE}", tofile=f"b/{SYNTH_FILE}")
    return "".join(diff).encode("utf-8")


@unittest.skipUnless(GIT_AVAILABLE, "需要 git 执行 git apply")
class StagedPatchChainTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pudu_chain_")
        self.pkg = os.path.join(self.tmp, "oemer")
        os.makedirs(self.pkg)
        self.patches = os.path.join(self.tmp, "patches")
        os.makedirs(self.patches)

        self.src_path = os.path.join(self.pkg, SYNTH_FILE)
        open(self.src_path, "wb").write(SRC_ORIG)

        p1 = _patch(SRC_ORIG, SRC_MID)
        p2 = _patch(SRC_MID, SRC_TAIL)
        self.p1 = os.path.join(self.patches, "a.s1.patch")
        self.p2 = os.path.join(self.patches, "a.s2.patch")
        open(self.p1, "wb").write(p1)
        open(self.p2, "wb").write(p2)

        self.sha_orig = _lf_sha(SRC_ORIG)
        self.sha_mid = _lf_sha(SRC_MID)
        self.sha_tail = _lf_sha(SRC_TAIL)

        self.spec = PatchSpec(
            file=SYNTH_FILE,
            patch_file="a.s1.patch",
            original_sha256_lf=self.sha_orig,
            patched_sha256_lf=self.sha_tail,
            stages=(
                PatchStage(patch_file="a.s1.patch",
                           from_sha256_lf=self.sha_orig,
                           to_sha256_lf=self.sha_mid),
                PatchStage(patch_file="a.s2.patch",
                           from_sha256_lf=self.sha_mid,
                           to_sha256_lf=self.sha_tail),
            ),
        )
        self.pkg_path = pathlib.Path(self.pkg)
        self.patches_path = pathlib.Path(self.patches)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data: bytes):
        open(self.src_path, "wb").write(data)

    def test_decide_state_positions(self):
        # original -> CLEAN, start 0
        self._write(SRC_ORIG)
        d = decide_state(self.spec, self.pkg_path)
        self.assertEqual(d.state, FileState.CLEAN)
        self.assertEqual(d.start_index, 0)
        # mid -> CLEAN, start 1
        self._write(SRC_MID)
        d = decide_state(self.spec, self.pkg_path)
        self.assertEqual(d.state, FileState.CLEAN)
        self.assertEqual(d.start_index, 1)
        # tail -> ALREADY
        self._write(SRC_TAIL)
        d = decide_state(self.spec, self.pkg_path)
        self.assertEqual(d.state, FileState.ALREADY_PATCHED)
        self.assertEqual(d.start_index, len(self.spec.chain))
        # other -> DRIFT
        self._write(b"something completely different\n")
        d = decide_state(self.spec, self.pkg_path)
        self.assertEqual(d.state, FileState.DRIFT)

    def test_apply_chained_from_original(self):
        self._write(SRC_ORIG)
        res = apply_patch(self.spec, self.pkg_path, self.patches_path)
        self.assertEqual(res.outcome, ApplyOutcome.APPLIED, res.message)
        self.assertEqual(
            lf_normalized_sha256(self.pkg_path / SYNTH_FILE), self.sha_tail)
        # 幂等：再 apply -> SKIP
        res2 = apply_patch(self.spec, self.pkg_path, self.patches_path)
        self.assertEqual(res2.outcome, ApplyOutcome.SKIPPED, res2.message)

    def test_apply_from_mid_applies_only_stage2(self):
        # 现网已处在链第 1 环（6 点补丁态）的升级路径
        self._write(SRC_MID)
        res = apply_patch(self.spec, self.pkg_path, self.patches_path)
        self.assertEqual(res.outcome, ApplyOutcome.APPLIED, res.message)
        self.assertEqual(
            lf_normalized_sha256(self.pkg_path / SYNTH_FILE), self.sha_tail)

    def test_check_only_does_not_modify(self):
        self._write(SRC_ORIG)
        before = lf_normalized_sha256(self.pkg_path / SYNTH_FILE)
        res = apply_patch(self.spec, self.pkg_path, self.patches_path,
                          check_only=True)
        self.assertEqual(res.outcome, ApplyOutcome.SKIPPED, res.message)
        after = lf_normalized_sha256(self.pkg_path / SYNTH_FILE)
        self.assertEqual(before, after)

    def test_validate_chain_rejects_broken(self):
        broken = PatchSpec(
            file=SYNTH_FILE, patch_file="a.s1.patch",
            original_sha256_lf=self.sha_orig, patched_sha256_lf=self.sha_tail,
            stages=(
                PatchStage(patch_file="a.s1.patch",
                           from_sha256_lf=self.sha_orig,
                           to_sha256_lf=self.sha_mid),
                # 故意断裂：from 不匹配上级 to
                PatchStage(patch_file="a.s2.patch",
                           from_sha256_lf="deadbeef" * 8,
                           to_sha256_lf=self.sha_tail),
            ))
        with self.assertRaises(ValueError):
            _validate_chain(broken)


if __name__ == "__main__":
    unittest.main()
