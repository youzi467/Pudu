# -*- coding: utf-8 -*-
"""P0-2 · C++ 侧红线的沙箱静态回归。

本沙箱没有 MSVC，无法 `cmake --build` 跑 ctest。但 P0-2 最硬的两条红线
（① `tools/omr_oemer.py` 零 diff；② `preprocess=false` 时子进程命令串与
P0-2 之前逐字节一致）本质上是**源码层面的性质**，可以在不编译的前提下
用静态解析证明。本文件即为这层证明，作用是：

  * 让红线在 CI/沙箱里"当场可验"，而不是等到用户本机编译才暴露；
  * 任何人日后改动 `runOmr` 的 oemer 分支拼串逻辑，这里会立刻变红。

做法：把 C++ 里的字符串拼接表达式当作一棵极简的 `+` 语法树求值——
字面量按 C++ 转义规则反转义，标识符（cfg.python / input / ...）代入哨兵值——
从而算出 `cmd` 的**运行期字节串**，再与 P0-2 之前的基线字节串比对。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import unittest

# ---------------------------------------------------------------- 路径与常量

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)

ADAPTER_CPP = os.path.join(REPO_ROOT, "src", "omr_adapter.cpp")
ADAPTER_HPP = os.path.join(REPO_ROOT, "include", "omr_adapter.hpp")
MAIN_CPP = os.path.join(REPO_ROOT, "src", "main.cpp")

# P0-2 之前 oemer 分支产出的命令串（用下面的哨兵值代入后的期望结果）。
# 基线源码为：
#   cmd = "\"" + cfg.python + "\" \"" + cfg.toolsDir + "/omr_oemer.py\" \"" +
#         input + "\" \"" + outMusicXml + "\"";
SENTINELS = {
    "cfg.python": "PYEXE",
    "cfg.toolsDir": "TOOLS",
    "input": "IN",
    "outMusicXml": "OUT",
}
BASELINE_CMD = '"PYEXE" "TOOLS/omr_oemer.py" "IN" "OUT"'
PREPROCESS_CMD = '"PYEXE" "TOOLS/omr_pipeline.py" "IN" "OUT"'

# 生产 C++ 净增行数上限（架构约束：≤ 15 行，且不引入第三方依赖）
MAX_CPP_NET_LINES = 15
PROD_CPP_PATHS = ("include/omr_adapter.hpp", "src/omr_adapter.cpp", "src/main.cpp")
FROZEN_PATHS = ("CMakeLists.txt", "vcpkg.json", "tools/omr_oemer.py")


# ---------------------------------------------------------------- 极简求值器

def _unescape_cpp_literal(body: str) -> str:
    """按 C++ 规则反转义一个字符串字面量的**内容**（不含两侧引号）。"""
    out = []
    i = 0
    simple = {
        "n": "\n", "t": "\t", "r": "\r", "0": "\0",
        '"': '"', "'": "'", "\\": "\\", "a": "\a", "b": "\b",
        "f": "\f", "v": "\v",
    }
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append(simple.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def strip_cpp_comments(src: str) -> str:
    """去掉 `//` 与 `/* */` 注释（字符串字面量内的同形字符不受影响）。

    必须先剥注释再做结构分析，否则"把校验注释掉但注释里仍留着原文"这类
    改动会被静态检查漏过（例如 `if (false) { // cfg.toolsDir.empty()`）。
    """
    out = []
    i, n = 0, len(src)
    in_str = in_chr = False
    while i < n:
        ch = src[i]
        if in_str or in_chr:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if in_str and ch == '"':
                in_str = False
            elif in_chr and ch == "'":
                in_chr = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_chr = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_outside_literals(expr: str) -> str:
    """折叠**字符串字面量之外**的空白，字面量内的字节逐字保留。

    这是"逐字节一致"能否被真正验证的关键：早期实现用 ``" ".join(x.split())``
    做续行拼合，会把字面量**内部**的空白也一并归一，导致
    ``"\\" \\""`` 改成 ``"\\"  \\""``（多一个空格 -> 运行期命令串真的变了）
    却依然测试全绿。此函数只归一字面量外的空白。
    """
    out = []
    i, n = 0, len(expr)
    in_str = False
    while i < n:
        ch = expr[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(expr[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch.isspace():
            while i < n and expr[i].isspace():
                i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _split_top_level_plus(expr: str) -> list:
    """在字符串字面量之外，按 `+` 切分表达式。"""
    parts, buf = [], []
    i, in_str = 0, False
    while i < len(expr):
        ch = expr[i]
        if in_str:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(expr):
                buf.append(expr[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == "+":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def eval_cpp_concat(expr: str, env: dict) -> str:
    """求值形如 `"\\"" + cfg.python + "\\" \\"" + ...` 的拼接表达式。"""
    result = []
    for term in _split_top_level_plus(expr):
        if term.startswith('"') and term.endswith('"') and len(term) >= 2:
            result.append(_unescape_cpp_literal(term[1:-1]))
        elif term in env:
            result.append(env[term])
        else:
            raise AssertionError(
                "命令串出现未预期的项 %r —— P0-2 不允许给 oemer 命令追加任何参数" % term
            )
    return "".join(result)


def extract_oemer_branch(src: str) -> str:
    """截取 runOmr 中 `if (cfg.engine == "oemer") { ... }` 的分支体（已剥注释）。"""
    src = strip_cpp_comments(src)
    m = re.search(r'if\s*\(\s*cfg\.engine\s*==\s*"oemer"\s*\)\s*\{', src)
    assert m, "未找到 oemer 分支（omr_adapter.cpp 结构已变，请同步本测试）"
    i = m.end()
    depth = 1
    start = i
    in_str = False
    while i < len(src) and depth > 0:
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return src[start:i - 1]


def extract_cmd_expr(branch: str) -> str:
    """从分支体里取出 `cmd = <expr>;` 的右值表达式（可跨行）。

    续行拼合只折叠**字面量之外**的空白，字面量内容逐字保留
    （见 :func:`normalize_outside_literals`）。
    """
    m = re.search(r"\bcmd\s*=\s*(.+?);", branch, re.S)
    assert m, "oemer 分支里未找到 `cmd = ...;` 赋值"
    return normalize_outside_literals(m.group(1))


def extract_script_ternary(branch: str):
    """取出 `<ident> = cfg.preprocess ? "<on>" : "<off>";` 的三要素。

    返回 ``(ident, on_value, off_value)``。**必须把三元的目标标识符也取出来**，
    否则"三元赋给一个没人用的变量、真正参与拼串的 script 写死成 pipeline"
    这类伪装改动会被漏检。
    """
    m = re.search(
        r'(\w+)\s*=\s*cfg\.preprocess\s*\?\s*"([^"]*)"\s*:\s*"([^"]*)"\s*;',
        branch,
    )
    assert m, "未找到形如 `<ident> = cfg.preprocess ? \"...\" : \"...\";` 的脚本名选择"
    return m.group(1), m.group(2), m.group(3)


def _git(*args: str):
    """跑一条 git 命令；git 不可用或非仓库时返回 None。"""
    try:
        proc = subprocess.run(
            ("git",) + args,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- 测试用例

class CommandByteIdentityTest(unittest.TestCase):
    """红线②：preprocess=false 时命令串与 P0-2 之前逐字节一致。"""

    @classmethod
    def setUpClass(cls):
        with open(ADAPTER_CPP, "r", encoding="utf-8") as fh:
            cls.src = fh.read()
        cls.branch = extract_oemer_branch(cls.src)
        cls.expr = extract_cmd_expr(cls.branch)
        # 三元的目标标识符必须就是拼串里用到的那一项，绝不能由测试凭空注入
        cls.script_ident, cls.script_on, cls.script_off = \
            extract_script_ternary(cls.branch)

    def _eval_with_script(self, script_value: str) -> str:
        env = dict(SENTINELS)
        env[self.script_ident] = script_value
        return eval_cpp_concat(self.expr, env)

    def test_ternary_target_is_the_identifier_used_in_command(self):
        """三元结果必须**真的**参与拼串，且在分支内只被赋值一次。

        防伪装：`const char* other = cfg.preprocess ? A : B;` 之后
        `const char* script = "/omr_pipeline.py";` —— 三元看起来对，
        但命令串恒用 pipeline。
        """
        terms = _split_top_level_plus(self.expr)
        self.assertIn(
            self.script_ident, terms,
            "cfg.preprocess 三元赋给了 %r，但命令串拼的是 %r —— "
            "开关根本没接到命令串上" % (self.script_ident, terms),
        )
        assigns = re.findall(r"\b%s\s*=(?!=)" % re.escape(self.script_ident),
                             self.branch)
        self.assertEqual(
            len(assigns), 1,
            "%r 在 oemer 分支里被赋值 %d 次，三元结论可能被后续覆盖"
            % (self.script_ident, len(assigns)),
        )

    def test_switch_off_reproduces_baseline_command_byte_for_byte(self):
        """开关关 → 命令串必须等于 P0-2 之前的基线，一个字节都不能差。"""
        got = self._eval_with_script("/omr_oemer.py")
        self.assertEqual(got, BASELINE_CMD)

    def test_switch_on_only_swaps_script_name(self):
        """开关开 → 只有脚本名从 omr_oemer.py 换成 omr_pipeline.py，其余全同。"""
        off = self._eval_with_script("/omr_oemer.py")
        on = self._eval_with_script("/omr_pipeline.py")
        self.assertEqual(on, PREPROCESS_CMD)
        self.assertEqual(off.replace("/omr_oemer.py", "/omr_pipeline.py"), on)

    def test_ternary_false_branch_is_exactly_omr_oemer(self):
        """三元表达式的 false 分支必须精确是 "/omr_oemer.py"。"""
        self.assertEqual(self.script_on, "/omr_pipeline.py")
        self.assertEqual(self.script_off, "/omr_oemer.py")

    def test_source_of_truth_command_matches_expected_baselines(self):
        """用**源码里真实的**三元取值求值，而非测试注入的哨兵取值。"""
        self.assertEqual(self._eval_with_script(self.script_off), BASELINE_CMD)
        self.assertEqual(self._eval_with_script(self.script_on), PREPROCESS_CMD)

    def test_no_extra_arguments_appended_to_command(self):
        """命令串里不得出现任何 P0-2 私有参数（--preprocess-* / --keep-temp 等）。"""
        for forbidden in (
            "--preprocess", "--preprocess-config", "--preprocess-preset",
            "--preprocess-metrics", "--keep-temp", "--no-preprocess",
        ):
            self.assertNotIn(forbidden, self.branch)

    def test_command_has_exactly_four_quoted_fields(self):
        """命令形状恒为 4 个带引号字段：python / script / input / output。"""
        for script in ("/omr_oemer.py", "/omr_pipeline.py"):
            cmd = self._eval_with_script(script)
            self.assertEqual(cmd.count('"'), 8, cmd)
            self.assertEqual(len(re.findall(r'"[^"]*"', cmd)), 4, cmd)

    def test_tools_dir_guard_still_precedes_command_build(self):
        """toolsDir 空校验必须是**生效的 if 条件**，且位于拼串之前。

        只做 `find("toolsDir.empty()")` 是不够的：把校验注释掉、
        或改成 `if (false) { /* cfg.toolsDir.empty() */ ...` 时原文仍在，
        会被漏检。这里在**剥注释后的源码**上匹配真实 if 条件。
        """
        m = re.search(r"if\s*\(\s*cfg\.toolsDir\.empty\(\)\s*\)\s*\{",
                      self.branch)
        self.assertIsNotNone(
            m, "toolsDir 空校验被删除/注释/改写，不再是生效的 if 条件")
        build = self.branch.find("cmd =")
        self.assertNotEqual(build, -1)
        self.assertLess(m.start(), build, "toolsDir 空校验必须在拼串之前")
        self.assertIn("return false", self.branch[m.end():build],
                      "toolsDir 为空时必须提前 return false，不能继续拼串")


class ConfigDefaultOffTest(unittest.TestCase):
    """红线：preprocess 默认必须为 false。"""

    def test_header_declares_preprocess_default_false(self):
        with open(ADAPTER_HPP, "r", encoding="utf-8") as fh:
            hpp = fh.read()
        m = re.search(r"bool\s+preprocess\s*=\s*(\w+)\s*;", hpp)
        self.assertIsNotNone(m, "OmrEngineConfig 未声明 bool preprocess")
        self.assertEqual(m.group(1), "false", "preprocess 默认值必须是 false")

    def test_preprocess_field_lives_in_omr_engine_config(self):
        with open(ADAPTER_HPP, "r", encoding="utf-8") as fh:
            hpp = fh.read()
        m = re.search(r"struct\s+OmrEngineConfig\s*\{(.+?)\n\};", hpp, re.S)
        self.assertIsNotNone(m)
        self.assertIn("bool preprocess", m.group(1))

    def test_main_wires_flag_and_defaults_off(self):
        with open(MAIN_CPP, "r", encoding="utf-8") as fh:
            main_src = fh.read()
        self.assertRegex(main_src, r"bool\s+omrPreprocess\s*=\s*false\s*;")
        self.assertIn('a == "--omr-preprocess"', main_src)
        self.assertRegex(main_src, r"cfg\.preprocess\s*=\s*omrPreprocess\s*;")

    def test_main_flag_consumes_no_extra_argv(self):
        """--omr-preprocess 是布尔开关，不能像 --omr-engine 那样吃掉下一个 argv。"""
        with open(MAIN_CPP, "r", encoding="utf-8") as fh:
            main_src = fh.read()
        m = re.search(
            r'else if \(a == "--omr-preprocess"\)\s*\{(.*?)\}', main_src, re.S
        )
        self.assertIsNotNone(m, "未找到 --omr-preprocess 分支")
        body = m.group(1)
        self.assertIn("omrPreprocess = true", body)
        self.assertNotIn("++i", body)
        self.assertNotIn("argv[i + 1]", body)


class RepoConstraintTest(unittest.TestCase):
    """红线①/④：omr_oemer.py 零 diff、构建文件冻结、C++ 净增 ≤ 15 行。"""

    def setUp(self):
        self.numstat = _git("diff", "--numstat", "HEAD")
        if self.numstat is None:
            self.skipTest("git 不可用或当前目录不是 git 仓库，跳过仓库级约束校验")

    def _changed(self) -> dict:
        rows = {}
        for line in self.numstat.splitlines():
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            added, deleted, path = cols
            if added == "-" or deleted == "-":
                continue    # 二进制文件
            rows[path.replace("\\", "/")] = (int(added), int(deleted))
        return rows

    def test_frozen_files_have_zero_diff(self):
        changed = self._changed()
        for path in FROZEN_PATHS:
            self.assertNotIn(
                path, changed,
                "%s 必须零 diff（P0-2 红线），实际被修改了" % path,
            )

    def test_production_cpp_net_increase_within_budget(self):
        changed = self._changed()
        net = 0
        for path, (added, deleted) in changed.items():
            if path in PROD_CPP_PATHS:
                net += added - deleted
        self.assertLessEqual(
            net, MAX_CPP_NET_LINES,
            "生产 C++ 净增 %d 行，超出 %d 行预算" % (net, MAX_CPP_NET_LINES),
        )

    def test_no_new_third_party_dependency_declared(self):
        vcpkg = os.path.join(REPO_ROOT, "vcpkg.json")
        if not os.path.exists(vcpkg):
            self.skipTest("仓库没有 vcpkg.json")
        with open(vcpkg, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        deps = manifest.get("dependencies", [])
        names = [d if isinstance(d, str) else d.get("name", "") for d in deps]
        for banned in ("opencv", "opencv4", "opencv2"):
            self.assertNotIn(banned, names, "C++ 侧不得引入 OpenCV 依赖")


if __name__ == "__main__":
    unittest.main()
