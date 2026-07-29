#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谱渡 Pudu · oemer 补丁安装器单元测试

测试三态判定 + sha 归一化 + apply 幂等，使用临时副本验证：
  1. CLEAN → APPLY（原版文件 apply 后 sha == patched_lf）
  2. PATCHED → SKIP（已打补丁的文件跳过，幂等）
  3. DRIFT → ABORT（sha 不匹配的文件 abort）
  4. sha 归一化（CRLF 文件与 LF 文件 sha 一致）
  5. apply 后回验 + 回滚

运行：
  python tools/test_install_oemer.py
"""

from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

# 确保能 import 同目录的 oemer_patch_lib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from oemer_patch_lib import (  # noqa: E402
    ApplyOutcome,
    FileState,
    PatchSpec,
    apply_patch,
    decide_state,
    lf_normalized_sha256,
    load_manifest,
)


# ---------------------------------------------------------------------------
# 测试用常量（与 oemer-0.1.8.checksums.json 一致）
# ---------------------------------------------------------------------------
BBOX_ORIG_LF = "ff72f4b07889c33b63c8978a9abc7145392012396eca86da07b01de8a0e520e3"
BBOX_PATCHED_LF = "126630fbb29a404bb74c8022257ae6ad47ab87ef2762610d7274d14c9f88482f"
STAFFLINE_ORIG_LF = "ba60d544d0ccd737db11a982a3addf94b31ff433f7572c192b501bd812ad7d9d"
STAFFLINE_PATCHED_LF = "4717828270d0d9cf826998e25c798048af9cb3a15c922067afe73cafb6fce6bd"

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PATCHES_DIR = REPO_ROOT / "third_party" / "oemer-patches"

# 原版文件路径（从 wheel 解压，或用 site-packages 的 .bak）
# 测试中我们会动态生成原版和补丁版的临时副本
WHEEL_OEMER = pathlib.Path(r"C:/tmp/oemer-whl/oemer")


def _make_patch_spec(file: str, orig_sha: str, patched_sha: str) -> PatchSpec:
    """创建测试用 PatchSpec。"""
    return PatchSpec(
        file=file,
        patch_file=f"{file}.patch",
        original_sha256_lf=orig_sha,
        patched_sha256_lf=patched_sha,
    )


def _lf_sha_of_bytes(data: bytes) -> str:
    """计算 bytes 的 LF 归一化 sha256。"""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


class TestLfNormalizedSha256(unittest.TestCase):
    """测试 LF 归一化 sha256。"""

    def test_lf_file(self):
        """纯 LF 文件的 sha 正确。"""
        content = b"line1\nline2\nline3\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(content)
            f.flush()
            path = pathlib.Path(f.name)
        try:
            sha = lf_normalized_sha256(path)
            expected = hashlib.sha256(content).hexdigest()
            self.assertEqual(sha, expected)
        finally:
            path.unlink()

    def test_crlf_normalized_to_lf(self):
        """CRLF 文件归一化后 sha == 对应 LF 文件的 sha。"""
        lf_content = b"line1\nline2\nline3\n"
        crlf_content = b"line1\r\nline2\r\nline3\r\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(crlf_content)
            f.flush()
            path = pathlib.Path(f.name)
        try:
            sha = lf_normalized_sha256(path)
            expected = hashlib.sha256(lf_content).hexdigest()
            self.assertEqual(sha, expected)
        finally:
            path.unlink()

    def test_mixed_endings(self):
        """混合行尾也能正确归一化。"""
        content = b"line1\nline2\r\nline3\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(content)
            f.flush()
            path = pathlib.Path(f.name)
        try:
            sha = lf_normalized_sha256(path)
            expected = hashlib.sha256(b"line1\nline2\nline3\n").hexdigest()
            self.assertEqual(sha, expected)
        finally:
            path.unlink()


class TestDecideState(unittest.TestCase):
    """测试三态判定。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="oemer-test-")
        self.pkg = pathlib.Path(self.tmpdir) / "oemer"
        self.pkg.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_state(self):
        """原版文件 → CLEAN。"""
        spec = _make_patch_spec("test.py", "aaa", "bbb")
        target = self.pkg / "test.py"
        target.write_bytes(b"original content\n")
        # 手动计算 sha 并设为 original
        sha = lf_normalized_sha256(target)
        spec = _make_patch_spec("test.py", sha, "bbb")
        state = decide_state(spec, self.pkg)
        self.assertEqual(state, FileState.CLEAN)

    def test_patched_state(self):
        """补丁后文件 → ALREADY_PATCHED。"""
        spec = _make_patch_spec("test.py", "aaa", "bbb")
        target = self.pkg / "test.py"
        target.write_bytes(b"patched content\n")
        sha = lf_normalized_sha256(target)
        spec = _make_patch_spec("test.py", "aaa", sha)
        state = decide_state(spec, self.pkg)
        self.assertEqual(state, FileState.ALREADY_PATCHED)

    def test_drift_state(self):
        """sha 不匹配任何已知值 → DRIFT。"""
        spec = _make_patch_spec("test.py", "aaa", "bbb")
        target = self.pkg / "test.py"
        target.write_bytes(b"some other content\n")
        state = decide_state(spec, self.pkg)
        self.assertEqual(state, FileState.DRIFT)

    def test_missing_file_drift(self):
        """文件不存在 → DRIFT。"""
        spec = _make_patch_spec("nonexistent.py", "aaa", "bbb")
        state = decide_state(spec, self.pkg)
        self.assertEqual(state, FileState.DRIFT)

    def test_crlf_patched_detected_as_patched(self):
        """CRLF 版补丁文件也能被正确识别为 ALREADY_PATCHED（行尾铁律）。"""
        spec = _make_patch_spec("test.py", "aaa", "bbb")
        target = self.pkg / "test.py"
        # 写 CRLF 版
        target.write_bytes(b"patched content\r\n")
        sha = lf_normalized_sha256(target)
        spec = _make_patch_spec("test.py", "aaa", sha)
        state = decide_state(spec, self.pkg)
        self.assertEqual(state, FileState.ALREADY_PATCHED)


class TestApplyPatchRealFiles(unittest.TestCase):
    """用真实 oemer patch 文件测试 apply_patch 全流程。

    需要从 wheel 解压的原版文件。若 wheel 不存在则跳过。
    """

    def setUp(self):
        if not WHEEL_OEMER.exists():
            self.skipTest(f"wheel 原版不可用: {WHEEL_OEMER}")
        if not PATCHES_DIR.exists():
            self.skipTest(f"patches 目录不可用: {PATCHES_DIR}")

        self.tmpdir = tempfile.mkdtemp(prefix="oemer-apply-test-")
        self.pkg = pathlib.Path(self.tmpdir) / "oemer"
        self.pkg.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _copy_original(self, filename: str) -> None:
        """从 wheel 复制原版文件到临时包目录。"""
        src = WHEEL_OEMER / filename
        dst = self.pkg / filename
        shutil.copy2(src, dst)
        # 确保是 LF（wheel 原版应该是 LF，但保险起见）
        raw = dst.read_bytes().replace(b"\r\n", b"\n")
        dst.write_bytes(raw)

    def test_bbox_clean_to_applied(self):
        """CLEAN → APPLY：原版 bbox.py apply 后 sha == patched_lf。"""
        self._copy_original("bbox.py")
        spec = _make_patch_spec("bbox.py", BBOX_ORIG_LF, BBOX_PATCHED_LF)
        result = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result.outcome, ApplyOutcome.APPLIED,
                         f"Expected APPLIED, got {result.outcome}: {result.message}")
        # 验证 apply 后 sha
        sha = lf_normalized_sha256(self.pkg / "bbox.py")
        self.assertEqual(sha, BBOX_PATCHED_LF)

    def test_staffline_clean_to_applied(self):
        """CLEAN → APPLY：原版 staffline_extraction.py apply 后 sha == patched_lf。"""
        self._copy_original("staffline_extraction.py")
        spec = _make_patch_spec(
            "staffline_extraction.py", STAFFLINE_ORIG_LF, STAFFLINE_PATCHED_LF
        )
        result = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result.outcome, ApplyOutcome.APPLIED,
                         f"Expected APPLIED, got {result.outcome}: {result.message}")
        sha = lf_normalized_sha256(self.pkg / "staffline_extraction.py")
        self.assertEqual(sha, STAFFLINE_PATCHED_LF)

    def test_patched_skip_idempotent(self):
        """PATCHED → SKIP：已打补丁的文件跳过（幂等）。"""
        self._copy_original("bbox.py")
        spec = _make_patch_spec("bbox.py", BBOX_ORIG_LF, BBOX_PATCHED_LF)
        # 第一次 apply
        result1 = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result1.outcome, ApplyOutcome.APPLIED)
        # 第二次 apply（应该 SKIP）
        result2 = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result2.outcome, ApplyOutcome.SKIPPED,
                         f"Expected SKIPPED on second apply, got {result2.outcome}")
        # sha 不变
        sha = lf_normalized_sha256(self.pkg / "bbox.py")
        self.assertEqual(sha, BBOX_PATCHED_LF)

    def test_patched_skip_with_crlf(self):
        """PATCHED → SKIP：CRLF 版补丁文件也能正确跳过（行尾铁律）。"""
        self._copy_original("bbox.py")
        spec = _make_patch_spec("bbox.py", BBOX_ORIG_LF, BBOX_PATCHED_LF)
        # apply 得到 LF 版补丁文件
        result = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result.outcome, ApplyOutcome.APPLIED)
        # 把文件转成 CRLF（模拟现网手工编辑）
        target = self.pkg / "bbox.py"
        lf_content = target.read_bytes()
        crlf_content = lf_content.replace(b"\n", b"\r\n")
        target.write_bytes(crlf_content)
        # 应该仍然被识别为 ALREADY_PATCHED 并 SKIP
        result2 = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result2.outcome, ApplyOutcome.SKIPPED,
                         f"CRLF patched file should be SKIPPED, got {result2.outcome}")

    def test_drift_abort(self):
        """DRIFT → ABORT：sha 不匹配的文件 abort。"""
        # 写一个内容不同的文件
        target = self.pkg / "bbox.py"
        target.write_bytes(b"this is not the original file\n")
        spec = _make_patch_spec("bbox.py", BBOX_ORIG_LF, BBOX_PATCHED_LF)
        result = apply_patch(spec, self.pkg, PATCHES_DIR)
        self.assertEqual(result.outcome, ApplyOutcome.ABORTED,
                         f"Expected ABORTED for drift, got {result.outcome}")
        # 文件未被修改
        self.assertEqual(target.read_bytes(), b"this is not the original file\n")

    def test_check_only_does_not_modify(self):
        """--check-only 模式不修改文件。"""
        self._copy_original("bbox.py")
        original_sha = lf_normalized_sha256(self.pkg / "bbox.py")
        spec = _make_patch_spec("bbox.py", BBOX_ORIG_LF, BBOX_PATCHED_LF)
        result = apply_patch(spec, self.pkg, PATCHES_DIR, check_only=True)
        self.assertEqual(result.outcome, ApplyOutcome.SKIPPED)
        # 文件未被修改
        after_sha = lf_normalized_sha256(self.pkg / "bbox.py")
        self.assertEqual(original_sha, after_sha)


class TestLoadManifest(unittest.TestCase):
    """测试 manifest 加载。"""

    def test_load_manifest(self):
        """加载真实 checksums.json，验证结构和 sha 值。"""
        version, specs = load_manifest(REPO_ROOT)
        self.assertEqual(version, "0.1.8")
        self.assertEqual(len(specs), 2)

        # 找到 bbox.py 和 staffline_extraction.py
        files = {s.file: s for s in specs}
        self.assertIn("bbox.py", files)
        self.assertIn("staffline_extraction.py", files)

        # 验证 sha 值
        self.assertEqual(files["bbox.py"].original_sha256_lf, BBOX_ORIG_LF)
        self.assertEqual(files["bbox.py"].patched_sha256_lf, BBOX_PATCHED_LF)
        self.assertEqual(files["staffline_extraction.py"].original_sha256_lf, STAFFLINE_ORIG_LF)
        self.assertEqual(files["staffline_extraction.py"].patched_sha256_lf, STAFFLINE_PATCHED_LF)

    def test_patch_files_exist(self):
        """patch 文件实际存在。"""
        _, specs = load_manifest(REPO_ROOT)
        for spec in specs:
            patch_path = PATCHES_DIR / spec.patch_file
            self.assertTrue(patch_path.exists(), f"patch 文件不存在: {patch_path}")


class TestPatchFileLineEndings(unittest.TestCase):
    """测试 patch 文件行尾为 LF。"""

    def test_bbox_patch_is_lf(self):
        """bbox.py.patch 行尾为 LF。"""
        patch_path = PATCHES_DIR / "bbox.py.patch"
        if not patch_path.exists():
            self.skipTest("bbox.py.patch 不存在")
        content = patch_path.read_bytes()
        self.assertNotIn(b"\r\n", content, "patch 文件包含 CRLF")

    def test_staffline_patch_is_lf(self):
        """staffline_extraction.py.patch 行尾为 LF。"""
        patch_path = PATCHES_DIR / "staffline_extraction.py.patch"
        if not patch_path.exists():
            self.skipTest("staffline_extraction.py.patch 不存在")
        content = patch_path.read_bytes()
        self.assertNotIn(b"\r\n", content, "patch 文件包含 CRLF")


if __name__ == "__main__":
    unittest.main(verbosity=2)
