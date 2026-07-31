# -*- coding: utf-8 -*-
"""oemer 权重完整性校验工具单测。

覆盖 ``tools/verify_oemer_checkpoints.py`` 的核心纯函数与 CLI 行为：

  * 全量完整 / 残片 / 缺失 / 超大 四种状态判定；
  * 脚手架文件（``arch.json`` / ``metadata.pkl``）不干扰判定；
  * checkpoints 目录定位失败的行为（退出码 2 语义）；
  * ``--json`` 输出可被 ``json.loads`` 解析且字段齐全；
  * 修复命令：PARTIAL 用 ``curl -L -C -`` 续传，MISSING 用 ``curl -L``。

测试通过**注入小体积期望表**（``expected=`` 参数 / 猴子补丁
``CHECKPOINT_FILES``）来造假 checkpoints 目录，绝不真写 70MB 文件。
纯标准库，不依赖 oemer，不联网。
"""
import io
import os
import sys
import json
import unittest
import tempfile
import contextlib

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import verify_oemer_checkpoints  # noqa: E402

V = verify_oemer_checkpoints

# 小体积期望表：结构与真实 CHECKPOINT_FILES 完全一致，仅字节数缩小，
# 便于在临时目录里快速造出「完整 / 残片 / 超大」三种文件。
FAKE_EXPECTED = (
    {"remote": "1st_model.onnx", "path": "unet_big/model.onnx", "size": 1000},
    {"remote": "1st_weights.h5", "path": "unet_big/weights.h5", "size": 2000},
    {"remote": "2nd_model.onnx", "path": "seg_net/model.onnx", "size": 3000},
    {"remote": "2nd_weights.h5", "path": "seg_net/weights.h5", "size": 4000},
)


def _write_bytes(root, rel_path, nbytes):
    """在 ``root`` 下按相对路径写入 ``nbytes`` 个填充字节，返回绝对路径。"""
    abs_path = os.path.join(root, *rel_path.split("/"))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as fh:
        fh.write(b"\x00" * nbytes)
    return abs_path


def _make_dir(root, sizes=None):
    """按 FAKE_EXPECTED 造假 checkpoints 目录。

    Args:
        root: 目标根目录。
        sizes: ``{rel_path: nbytes}`` 覆盖表；值为 ``None`` 表示该文件不创建。
    """
    overrides = sizes or {}
    for item in FAKE_EXPECTED:
        rel = item["path"]
        size = overrides.get(rel, item["size"]) if rel in overrides else item["size"]
        if size is None:
            continue
        _write_bytes(root, rel, size)


class TestVerifyCheckpoints(unittest.TestCase):
    """核心纯函数 ``verify_checkpoints`` 的状态判定。"""

    def _status_map(self, result):
        return {f["rel_path"]: f["status"] for f in result["files"]}

    def test_all_files_correct_size_is_ok(self):
        """用例1：4 个文件字节数全部正确 -> 全 OK，总体 ok=True。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp)
            result = V.verify_checkpoints(tmp, expected=FAKE_EXPECTED)

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["ok_count"], 4)
        self.assertEqual(result["problem_count"], 0)
        self.assertEqual(
            set(self._status_map(result).values()), {V.STATUS_OK}
        )
        for info in result["files"]:
            self.assertEqual(info["actual"], info["expected"])
            self.assertAlmostEqual(info["percent"], 100.0, places=1)
        # 无修复命令
        self.assertEqual(V.build_fix_commands(result), [])

    def test_all_ok_main_exit_code_zero(self):
        """用例1（续）：全 OK 时 main() 退出码为 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = self._main_with_fake_table(["--checkpoints", tmp])
        self.assertEqual(code, 0)
        self.assertIn("[OK]", buf.getvalue())

    def _main_with_fake_table(self, argv):
        """以小体积期望表猴子补丁运行 main()，返回退出码。"""
        original = V.CHECKPOINT_FILES
        V.CHECKPOINT_FILES = FAKE_EXPECTED
        try:
            # verify_checkpoints 的默认参数在定义时绑定，需显式重绑
            original_defaults = V.verify_checkpoints.__defaults__
            V.verify_checkpoints.__defaults__ = (FAKE_EXPECTED,)
            try:
                return V.main(argv)
            finally:
                V.verify_checkpoints.__defaults__ = original_defaults
        finally:
            V.CHECKPOINT_FILES = original

    def test_partial_file_detected_with_percent(self):
        """用例2：某文件偏小 -> PARTIAL，百分比正确，总体 ok=False。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp, sizes={"seg_net/model.onnx": 300})  # 300/3000 = 10.0%
            result = V.verify_checkpoints(tmp, expected=FAKE_EXPECTED)

        self.assertFalse(result["ok"])
        self.assertEqual(result["ok_count"], 3)
        self.assertEqual(result["problem_count"], 1)
        info = next(f for f in result["files"] if f["rel_path"] == "seg_net/model.onnx")
        self.assertEqual(info["status"], V.STATUS_PARTIAL)
        self.assertEqual(info["actual"], 300)
        self.assertEqual(info["expected"], 3000)
        self.assertAlmostEqual(info["percent"], 10.0, places=1)

        cmds = V.build_fix_commands(result)
        self.assertEqual(len(cmds), 1)
        self.assertIn("-C -", cmds[0])  # 残片必须续传
        self.assertIn("2nd_model.onnx", cmds[0])

    def test_missing_file_detected(self):
        """用例3：某文件缺失 -> MISSING，总体 ok=False，修复命令不带续传。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp, sizes={"unet_big/weights.h5": None})
            result = V.verify_checkpoints(tmp, expected=FAKE_EXPECTED)

        self.assertFalse(result["ok"])
        info = next(f for f in result["files"] if f["rel_path"] == "unet_big/weights.h5")
        self.assertEqual(info["status"], V.STATUS_MISSING)
        self.assertIsNone(info["actual"])
        self.assertAlmostEqual(info["percent"], 0.0, places=1)

        cmds = V.build_fix_commands(result)
        self.assertEqual(len(cmds), 1)
        self.assertNotIn("-C -", cmds[0])  # 缺失文件直接重下
        self.assertIn("1st_weights.h5", cmds[0])

    def test_oversize_file_detected(self):
        """用例4：某文件偏大 -> OVERSIZE，总体 ok=False。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp, sizes={"seg_net/weights.h5": 5000})  # 预期 4000
            result = V.verify_checkpoints(tmp, expected=FAKE_EXPECTED)

        self.assertFalse(result["ok"])
        info = next(f for f in result["files"] if f["rel_path"] == "seg_net/weights.h5")
        self.assertEqual(info["status"], V.STATUS_OVERSIZE)
        self.assertEqual(info["actual"], 5000)
        self.assertGreater(info["percent"], 100.0)

    def test_scaffold_files_do_not_affect_verdict(self):
        """用例5：arch.json / metadata.pkl 存在但 4 权重齐全 -> 仍判全 OK。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp)
            _write_bytes(tmp, "unet_big/arch.json", 17)
            _write_bytes(tmp, "seg_net/arch.json", 23)
            _write_bytes(tmp, "unet_big/metadata.pkl", 11)
            _write_bytes(tmp, "seg_net/metadata.pkl", 13)
            result = V.verify_checkpoints(tmp, expected=FAKE_EXPECTED)

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["ok_count"], 4)
        rels = {f["rel_path"] for f in result["files"]}
        self.assertNotIn("unet_big/arch.json", rels)
        self.assertNotIn("seg_net/metadata.pkl", rels)

    def test_report_is_pure_ascii_markers(self):
        """报告使用 ASCII 状态标记，可在 GBK 控制台安全输出。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp, sizes={"seg_net/model.onnx": 300})
            text = V.format_report(V.verify_checkpoints(tmp, expected=FAKE_EXPECTED))

        self.assertIn("[OK]", text)
        self.assertIn("[PARTIAL]", text)
        text.encode("gbk")  # 不抛 UnicodeEncodeError 即为通过


class TestResolveCheckpointsDir(unittest.TestCase):
    """checkpoints 目录定位逻辑。

    1/2 级（``--checkpoints`` / ``PUDU_OEMER_CHECKPOINTS``）是**严格模式**：
    指定了就必须存在，否则立即失败，不回落到默认 venv；3/4/5 级才是推断回落。
    """

    @staticmethod
    def _ghost_path():
        """返回一个必然不存在的绝对路径（临时目录退出后即消失）。"""
        with tempfile.TemporaryDirectory() as tmp:
            return os.path.join(tmp, "no_such_checkpoints")

    def test_explicit_dir_wins(self):
        """显式 --checkpoints 优先级最高。"""
        with tempfile.TemporaryDirectory() as tmp:
            found, tried, reason = V.resolve_checkpoints_dir(explicit=tmp, env={})
        self.assertEqual(os.path.normcase(found), os.path.normcase(os.path.abspath(tmp)))
        self.assertEqual(reason, V.REASON_OK)
        self.assertTrue(tried)

    def test_env_var_used_when_no_explicit(self):
        """无显式参数时使用 PUDU_OEMER_CHECKPOINTS。"""
        with tempfile.TemporaryDirectory() as tmp:
            found, _tried, reason = V.resolve_checkpoints_dir(
                explicit=None, env={"PUDU_OEMER_CHECKPOINTS": tmp}
            )
        self.assertEqual(os.path.normcase(found), os.path.normcase(os.path.abspath(tmp)))
        self.assertEqual(reason, V.REASON_OK)

    def test_explicit_nonexistent_dir_fails_strictly(self):
        """严格模式：显式目录不存在 -> 直接失败，绝不回落到默认路径。"""
        ghost = self._ghost_path()
        found, tried, reason = V.resolve_checkpoints_dir(explicit=ghost, env={})

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_EXPLICIT_MISSING)
        # tried 只记录用户指定的那一个路径，不含任何兜底候选
        self.assertEqual(tried, [os.path.abspath(ghost)])
        default_path = os.path.abspath(V.default_checkpoints_path())
        self.assertNotIn(default_path, tried)

    def test_env_nonexistent_dir_fails_strictly(self):
        """严格模式：环境变量指向的目录不存在 -> 直接失败，不回落。"""
        ghost = self._ghost_path()
        found, tried, reason = V.resolve_checkpoints_dir(
            explicit=None, env={"PUDU_OEMER_CHECKPOINTS": ghost}
        )

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_ENV_MISSING)
        self.assertEqual(tried, [os.path.abspath(ghost)])
        default_path = os.path.abspath(V.default_checkpoints_path())
        self.assertNotIn(default_path, tried)

    def test_explicit_strict_failure_does_not_reach_default_venv(self):
        """严格模式回归防护：即使默认 venv 真实存在，也不能被命中。"""
        ghost = self._ghost_path()
        with tempfile.TemporaryDirectory() as real_default:
            # 把兜底默认路径指向一个**确实存在**的目录；若严格模式失效，
            # resolve 就会错误地命中它，本用例即可捕获该回归。
            original_default = V.default_checkpoints_path
            V.default_checkpoints_path = lambda: real_default
            try:
                found, tried, reason = V.resolve_checkpoints_dir(explicit=ghost, env={})
            finally:
                V.default_checkpoints_path = original_default

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_EXPLICIT_MISSING)
        self.assertNotIn(os.path.abspath(real_default), tried)

    def test_main_returns_2_on_explicit_missing_with_precise_message(self):
        """用例6a：显式目录不存在 -> main() 返回 2，文案指向 --checkpoints。"""
        ghost = self._ghost_path()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = V.main(["--checkpoints", ghost])

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("[ERROR]", out)
        self.assertIn("--checkpoints 指定的目录不存在", out)
        self.assertIn(os.path.abspath(ghost), out)
        # 不应出现通用的"已尝试"清单式提示
        self.assertNotIn("无法定位", out)

    def test_main_returns_2_on_env_missing_with_precise_message(self):
        """用例6b：环境变量目录不存在 -> main() 返回 2，文案指向环境变量。"""
        ghost = self._ghost_path()
        original_environ = os.environ.get("PUDU_OEMER_CHECKPOINTS")
        os.environ["PUDU_OEMER_CHECKPOINTS"] = ghost
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = V.main([])
        finally:
            if original_environ is None:
                os.environ.pop("PUDU_OEMER_CHECKPOINTS", None)
            else:
                os.environ["PUDU_OEMER_CHECKPOINTS"] = original_environ

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("[ERROR]", out)
        self.assertIn("PUDU_OEMER_CHECKPOINTS", out)
        self.assertIn(os.path.abspath(ghost), out)

    def test_main_returns_2_when_all_inference_fails(self):
        """用例6c：未显式指定且全部推断落空 -> 返回 2，打印候选清单与指引。"""
        original_default = V.default_checkpoints_path
        original_current = V._oemer_checkpoints_from_current_process
        ghost_default = self._ghost_path()
        # 屏蔽兜底候选（默认路径 + 当前解释器 oemer），确保推断必然失败
        V.default_checkpoints_path = lambda: ghost_default
        V._oemer_checkpoints_from_current_process = lambda: None
        original_environ = os.environ.pop("PUDU_OEMER_CHECKPOINTS", None)
        original_py = os.environ.pop("PUDU_OMR_PYTHON", None)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = V.main([])
        finally:
            V.default_checkpoints_path = original_default
            V._oemer_checkpoints_from_current_process = original_current
            if original_environ is not None:
                os.environ["PUDU_OEMER_CHECKPOINTS"] = original_environ
            if original_py is not None:
                os.environ["PUDU_OMR_PYTHON"] = original_py

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("[ERROR]", out)
        self.assertIn("无法定位", out)
        self.assertIn("--checkpoints", out)

    def test_empty_explicit_is_strict_failure_not_unspecified(self):
        """空串 --checkpoints 视为『指定了非法值』，严格失败且不回落。"""
        found, tried, reason = V.resolve_checkpoints_dir(explicit="", env={})

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_EXPLICIT_MISSING)
        # 防回退：绝不能落到默认 venv
        default_path = os.path.abspath(V.default_checkpoints_path())
        self.assertNotIn(default_path, tried)
        # 不能把空串 abspath 成 cwd 后记进 tried，否则报错指向用户没提过的路径
        self.assertNotIn(os.path.abspath(os.getcwd()), tried)

    def test_whitespace_explicit_is_strict_failure(self):
        """纯空白 --checkpoints 同样视为非法值，严格失败。"""
        found, tried, reason = V.resolve_checkpoints_dir(explicit="   ", env={})

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_EXPLICIT_MISSING)
        self.assertNotIn(os.path.abspath(V.default_checkpoints_path()), tried)

    def test_empty_env_var_is_strict_failure(self):
        """环境变量取值为空串 -> 严格失败，不回落。"""
        found, tried, reason = V.resolve_checkpoints_dir(
            explicit=None, env={"PUDU_OEMER_CHECKPOINTS": ""}
        )

        self.assertIsNone(found)
        self.assertEqual(reason, V.REASON_ENV_MISSING)
        self.assertNotIn(os.path.abspath(V.default_checkpoints_path()), tried)

    def test_unset_env_var_still_falls_back_to_inference(self):
        """回归防护：环境变量**未设置**时必须继续走 3/4/5 级推断回落。"""
        with tempfile.TemporaryDirectory() as real_default:
            original_default = V.default_checkpoints_path
            original_current = V._oemer_checkpoints_from_current_process
            V.default_checkpoints_path = lambda: real_default
            V._oemer_checkpoints_from_current_process = lambda: None
            try:
                # env 中没有 PUDU_OEMER_CHECKPOINTS 键 -> get 返回 None
                found, _tried, reason = V.resolve_checkpoints_dir(explicit=None, env={})
            finally:
                V.default_checkpoints_path = original_default
                V._oemer_checkpoints_from_current_process = original_current

        self.assertEqual(
            os.path.normcase(found), os.path.normcase(os.path.abspath(real_default))
        )
        self.assertEqual(reason, V.REASON_OK)

    def test_explicit_pointing_to_file_is_strict_failure(self):
        """--checkpoints 指向一个已存在的**文件** -> 严格失败（非目录）。"""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "not_a_dir.txt")
            with open(file_path, "wb") as fh:
                fh.write(b"x")

            found, tried, reason = V.resolve_checkpoints_dir(explicit=file_path, env={})

            self.assertIsNone(found)
            self.assertEqual(reason, V.REASON_EXPLICIT_MISSING)
            self.assertEqual(tried, [os.path.abspath(file_path)])
            # 文案必须说准：是"不是有效目录"而非"不存在"
            desc = V.describe_invalid_path(os.path.abspath(file_path))
            self.assertIn("不是有效目录", desc)

    def test_describe_invalid_path_branches(self):
        """describe_invalid_path 三个分支各自措辞正确。"""
        self.assertIn("为空字符串", V.describe_invalid_path(""))
        self.assertIn("为空字符串", V.describe_invalid_path("   "))
        ghost = self._ghost_path()
        self.assertIn("不存在", V.describe_invalid_path(ghost))
        self.assertNotIn("不是有效目录", V.describe_invalid_path(ghost))
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "f.bin")
            with open(f, "wb") as fh:
                fh.write(b"y")
            self.assertIn("不是有效目录", V.describe_invalid_path(f))

    def test_main_returns_2_on_empty_explicit(self):
        """main 层：空串 --checkpoints -> 退出码 2 且文案说明为空字符串。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = V.main(["--checkpoints", ""])

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("[ERROR]", out)
        self.assertIn("为空字符串", out)
        # 不得输出被 abspath 出来的 cwd
        self.assertNotIn(os.path.abspath(os.getcwd()), out)

    def test_main_returns_2_on_empty_env_var(self):
        """main 层：环境变量为空串 -> 退出码 2 且文案指向该环境变量。"""
        original = os.environ.get("PUDU_OEMER_CHECKPOINTS")
        os.environ["PUDU_OEMER_CHECKPOINTS"] = ""
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = V.main([])
        finally:
            if original is None:
                os.environ.pop("PUDU_OEMER_CHECKPOINTS", None)
            else:
                os.environ["PUDU_OEMER_CHECKPOINTS"] = original

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("PUDU_OEMER_CHECKPOINTS", out)
        self.assertIn("为空字符串", out)

    def test_main_returns_2_when_explicit_is_a_file(self):
        """main 层：--checkpoints 指向文件 -> 退出码 2 且文案含『不是有效目录』。"""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "some_file.onnx")
            with open(file_path, "wb") as fh:
                fh.write(b"z")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = V.main(["--checkpoints", file_path])

        self.assertEqual(code, 2)
        out = buf.getvalue()
        self.assertIn("[ERROR]", out)
        self.assertIn("不是有效目录", out)
        self.assertNotIn("指定的目录不存在", out)

    def test_json_output_on_strict_failure(self):
        """严格失败时 --json 也应输出可解析的结构并含 reason。"""
        ghost = self._ghost_path()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = V.main(["--checkpoints", ghost, "--json"])

        self.assertEqual(code, 2)
        data = json.loads(buf.getvalue())
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], V.REASON_EXPLICIT_MISSING)
        self.assertIn("error", data)
        self.assertEqual(data["tried"], [os.path.abspath(ghost)])


class TestJsonOutput(unittest.TestCase):
    """--json 输出结构。"""

    def _run_json(self, argv):
        original = V.CHECKPOINT_FILES
        original_defaults = V.verify_checkpoints.__defaults__
        V.CHECKPOINT_FILES = FAKE_EXPECTED
        V.verify_checkpoints.__defaults__ = (FAKE_EXPECTED,)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = V.main(argv)
            return code, buf.getvalue()
        finally:
            V.verify_checkpoints.__defaults__ = original_defaults
            V.CHECKPOINT_FILES = original

    def test_json_output_parsable_and_complete(self):
        """用例7：--json 可被 json.loads 解析且含预期字段。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp, sizes={"seg_net/model.onnx": 300})
            code, out = self._run_json(["--checkpoints", tmp, "--json"])

        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertIn("ok", data)
        self.assertFalse(data["ok"])
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["ok_count"], 3)
        self.assertEqual(data["problem_count"], 1)
        self.assertIn("fix_commands", data)
        self.assertEqual(len(data["files"]), 4)
        for info in data["files"]:
            for key in ("path", "expected", "actual", "status", "percent", "url"):
                self.assertIn(key, info)

    def test_json_output_all_ok(self):
        """全 OK 时 --json 的 ok=True 且退出码 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_dir(tmp)
            code, out = self._run_json(["--checkpoints", tmp, "--json"])

        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["fix_commands"], [])


class TestRealExpectedTable(unittest.TestCase):
    """真实期望表的自洽性（防止升级 oemer 时表结构写坏）。"""

    def test_table_shape_and_values(self):
        self.assertEqual(len(V.CHECKPOINT_FILES), 4)
        expected_sizes = {
            "unet_big/model.onnx": 70767752,
            "unet_big/weights.h5": 70977288,
            "seg_net/model.onnx": 38448467,
            "seg_net/weights.h5": 38570576,
        }
        for item in V.CHECKPOINT_FILES:
            self.assertIn("remote", item)
            self.assertIn("path", item)
            self.assertIn("size", item)
            self.assertEqual(item["size"], expected_sizes[item["path"]])
        self.assertTrue(
            V.DOWNLOAD_BASE_URL.startswith("https://github.com/BreezeWhite/oemer")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
