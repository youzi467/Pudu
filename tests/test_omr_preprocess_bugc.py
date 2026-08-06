# -*- coding: utf-8 -*-
"""Bug C（过度预处理）端到端回归测试（需要 opencv，**不需要 oemer 权重**）。

背景：P1-2 railA 实验中 5 个 preset × 6 页 **100%** 触发
``oemer.exceptions.StafflineException: align_staffs received an empty staff
list``，全部 ``fell_back_to_raw=True``，导致 A/B 零信号。根因不是二值化，
而是 ``denoise_strength=3`` 的 3×3 中值滤波把 **1px 五线**整条抹平。

**为什么走子进程**：本仓库有一组 R-P0-08 惰性导入护栏，断言
``"cv2" not in sys.modules``。若本文件在父进程里 ``import cv2``，
pytest 收集阶段就会污染 ``sys.modules`` 并连坐打挂那些护栏。
因此所有像素级探测集中在**一个子进程**里跑完（见 :func:`_worker_main`），
父进程只解析 JSON 结果做断言——父进程全程只用 stdlib + 纯函数层。

覆盖：

* :class:`StafflineMeasurementTest` —— 线宽/能量测量本身准确。
* :class:`FixtureRealismTest` —— 证明"1px 五线遇 medianBlur(3) 必死"，
  确保下面的回归不是靠假 fixture 蒙混过关。
* :class:`DenoiseClampTest` —— 防线①：默认 preset 下去噪被钳到 0，
  增强图仍保住五线（这是打破 100% 兜底的直接原因）。
* :class:`RetentionCircuitBreakerTest` —— 防线②：绕过防线①后，
  留存自检必须熔断、**不写增强图**、返回可被上游识别的降级 metrics。
* :class:`ContractInvariantTest` —— 契约不变：metrics 可 JSON 序列化、
  preset 层仍生效、下游 ``.get()`` 读法不受影响。
"""

import importlib.util
import json
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO_ROOT, "tools")
for _p in (TOOLS, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 只导入纯函数层（omr_preprocess 顶层不 import cv2，见 R-P0-08）
from omr_preprocess import (  # noqa: E402
    OVER_PROCESSED_REASON_PREFIX, STAFFLINE_RETENTION_MIN, load_config,
)

#: 不 import cv2 的前提下探测其可用性（find_spec 不会执行模块）
_HAS_CV2 = importlib.util.find_spec("cv2") is not None

#: 子进程探测结果；由 :func:`setUpModule` 填充
_PROBE: dict = {}
_PROBE_ERROR: str = ""

#: 子进程结果的起始标记（避免 opencv/onnx 的噪声输出混进 JSON）
_MARKER = "###BUGC_JSON###"

# 合成谱面参数（够大才能让 width//60 的水平核有意义）
PAGE_W, PAGE_H = 1600, 1200
LINE_GAP, N_SYSTEMS = 12, 4


# ---------------------------------------------------------------------------
# 父进程：拉起子进程并解析结果
# ---------------------------------------------------------------------------
def setUpModule() -> None:
    """跑一次子进程探测，全模块共享结果（约 3 秒）。"""
    global _PROBE, _PROBE_ERROR
    if not _HAS_CV2:
        return
    # 子进程 stdout 是管道，其编码由**子进程自己的** locale 决定：Windows
    # 中文环境下是 GBK，而父进程这里按 UTF-8 解码 —— 中文 warning 于是变成
    # 乱码，任何"断言中文子串"的用例都必然落空。显式把子进程的 IO 编码钉死
    # 成 UTF-8，与下面的 decode 对齐，让本测试不依赖宿主机的控制台代码页。
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--worker"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=child_env)
    stdout = completed.stdout or ""
    if _MARKER not in stdout:
        _PROBE_ERROR = (f"子进程探测失败 rc={completed.returncode}\n"
                        f"--- stdout ---\n{stdout[-2000:]}\n"
                        f"--- stderr ---\n{(completed.stderr or '')[-2000:]}")
        return
    try:
        _PROBE = json.loads(stdout.split(_MARKER, 1)[1].strip())
    except ValueError as exc:
        _PROBE_ERROR = f"子进程输出不是合法 JSON: {exc}"


class _ProbeCase(unittest.TestCase):
    """所有断言从子进程结果里取数的基类。"""

    def probe(self, key: str):
        """取出某个探测场景的结果；子进程失败时直接 fail 并附上下文。"""
        if _PROBE_ERROR:
            self.fail(_PROBE_ERROR)
        self.assertIn(key, _PROBE, f"子进程未产出场景 {key}")
        return _PROBE[key]

    def metrics(self, key: str) -> dict:
        return self.probe(key)["metrics"]


@unittest.skipUnless(_HAS_CV2, "需要 opencv-python")
class StafflineMeasurementTest(_ProbeCase):
    """测量函数本身的准确性（两道防线的输入必须可信）。"""

    def test_thickness_matches_synthetic_ground_truth(self):
        measured = self.probe("thickness_by_gt")
        for gt in ("1", "2", "3", "5"):
            self.assertEqual(measured[gt], float(gt),
                             f"合成线宽 {gt}px 实测 {measured[gt]}")

    def test_energy_is_positive_on_sheet(self):
        self.assertGreater(self.probe("energy_sheet"), 0.0)

    def test_blank_page_has_no_staffline_energy(self):
        self.assertLessEqual(self.probe("energy_blank"),
                             self.probe("energy_sheet"))

    def test_thickness_of_blank_page_is_zero(self):
        """空白页测不出线宽 -> 0.0 -> 上游保守关掉去噪。"""
        self.assertEqual(self.probe("thickness_blank"), 0.0)


@unittest.skipUnless(_HAS_CV2, "需要 opencv-python")
class FixtureRealismTest(_ProbeCase):
    """锚定 Bug C 的物理事实：1px 五线遇 medianBlur(3) 必被抹平。

    这条测试若失效（medianBlur 不再杀线），说明 fixture 已失真，
    下面的回归测试也就失去意义——所以它必须留着。
    """

    def test_median_blur_kills_one_px_stafflines(self):
        retention = self.probe("median3_retention_1px")
        self.assertIsNotNone(retention)
        self.assertLess(retention, STAFFLINE_RETENTION_MIN,
                        f"1px 五线过 medianBlur(3) 后留存率 {retention}，"
                        f"未低于熔断阈值——fixture 已不再复现 Bug C")

    def test_median_blur_spares_thick_stafflines(self):
        """5px 线扛得住 3×3 中值滤波——证明钳制策略不是一刀切。"""
        self.assertGreaterEqual(self.probe("median3_retention_5px"),
                                STAFFLINE_RETENTION_MIN)


@unittest.skipUnless(_HAS_CV2, "需要 opencv-python")
class DenoiseClampTest(_ProbeCase):
    """防线①：去噪核按实测线宽钳制（Bug C 的正面修复）。"""

    def test_one_px_sheet_disables_denoise_and_survives(self):
        """核心回归：默认 denoise=3 的配置不再产出废图。"""
        result = self.probe("default_1px")
        metrics = result["metrics"]
        self.assertTrue(metrics["ok"], metrics.get("degrade_reason"))
        self.assertFalse(metrics["degraded"])
        self.assertEqual(metrics["staffline_thickness_px"], 1.0)
        self.assertEqual(metrics["denoise_strength_applied"], 0)
        self.assertGreaterEqual(metrics["staffline_retention"],
                                STAFFLINE_RETENTION_MIN)
        self.assertTrue(result["dst_exists"])
        self.assertGreater(result["dst_size"], 0)

    def test_clamp_emits_warning(self):
        metrics = self.metrics("default_1px")
        self.assertTrue(
            any("去噪核按五线线宽钳制" in w for w in metrics["warnings"]),
            metrics["warnings"])

    def test_thick_sheet_keeps_denoise_enabled(self):
        """线够粗时去噪照常生效——修复不能变成"永远不去噪"。"""
        metrics = self.metrics("thick_5px")
        self.assertTrue(metrics["ok"], metrics.get("degrade_reason"))
        self.assertEqual(metrics["staffline_thickness_px"], 5.0)
        self.assertEqual(metrics["denoise_strength_applied"], 3)

    def test_denoise_off_config_stays_off(self):
        metrics = self.metrics("denoise_off")
        self.assertEqual(metrics["denoise_strength_applied"], 0)
        self.assertTrue(metrics["ok"])

    def test_binarize_alone_is_not_over_processing(self):
        """探针已证二值化无罪：单开二值化不得触发熔断。"""
        for key in ("binarize_adaptive", "binarize_otsu"):
            metrics = self.metrics(key)
            self.assertTrue(metrics["ok"],
                            f"{key}: {metrics.get('degrade_reason')}")
            self.assertGreaterEqual(metrics["staffline_retention"],
                                    STAFFLINE_RETENTION_MIN, key)

    def test_measurement_failure_disables_denoise(self):
        """线宽测不出时保守关去噪，且不阻断主流程。"""
        metrics = self.metrics("measure_fail")
        self.assertTrue(metrics["ok"], metrics.get("degrade_reason"))
        self.assertEqual(metrics["denoise_strength_applied"], 0)
        self.assertIsNone(metrics["staffline_thickness_px"])
        self.assertTrue(
            any("五线基线测量失败" in w for w in metrics["warnings"]),
            metrics["warnings"])


@unittest.skipUnless(_HAS_CV2, "需要 opencv-python")
class RetentionCircuitBreakerTest(_ProbeCase):
    """防线②：绕过防线①后，留存自检必须熔断并走 fail-open。"""

    def test_trips_and_reports_degraded(self):
        metrics = self.metrics("breaker")
        self.assertFalse(metrics["ok"])
        self.assertTrue(metrics["degraded"])
        self.assertTrue(
            metrics["degrade_reason"].startswith(OVER_PROCESSED_REASON_PREFIX),
            metrics["degrade_reason"])

    def test_does_not_write_enhanced_image(self):
        """熔断时不落盘：上游据此回退原图，省掉一次注定失败的 oemer。"""
        self.assertFalse(self.probe("breaker")["dst_exists"])

    def test_dst_points_back_to_src_for_fallback(self):
        result = self.probe("breaker")
        self.assertEqual(result["metrics"]["dst"], result["src"])

    def test_trips_even_when_fail_open_disabled(self):
        """留存自检是质量闸门而非异常：fail_open=False 也只降级不抛。"""
        metrics = self.metrics("breaker_failopen_false")
        self.assertFalse(metrics["ok"])
        self.assertTrue(
            metrics["degrade_reason"].startswith(OVER_PROCESSED_REASON_PREFIX))

    def test_healthy_page_never_trips(self):
        """不绕过防线①时，同一张图必须正常产出（防误伤）。"""
        result = self.probe("breaker_healthy")
        self.assertTrue(result["metrics"]["ok"],
                        result["metrics"].get("degrade_reason"))
        self.assertTrue(result["dst_exists"])


@unittest.skipUnless(_HAS_CV2, "需要 opencv-python")
class ContractInvariantTest(_ProbeCase):
    """契约不变量：新增字段不得破坏既有下游消费。"""

    def test_all_presets_produce_usable_output(self):
        """4 个 railA preset 全部跑通（子进程已做过 JSON 往返）。"""
        presets = self.probe("presets")
        for name in ("default", "scan", "photo", "low_contrast"):
            metrics = presets[name]["metrics"]
            self.assertTrue(metrics["ok"],
                            f"{name}: {metrics.get('degrade_reason')}")
            self.assertIn("staffline_retention", metrics, name)
            self.assertIn("denoise_strength_applied", metrics, name)
            self.assertTrue(presets[name]["dst_exists"], name)

    def test_downstream_optional_read_is_safe(self):
        """下游（omr_abtest_lib）用 .get() 读，新字段不得改变旧键语义。"""
        metrics = self.probe("presets")["default"]["metrics"]
        self.assertIsInstance(metrics.get("ink_ratio_out"), float)
        self.assertIsInstance(metrics.get("degrade_reason"), str)
        self.assertIsInstance(metrics.get("fell_back_to_raw"), bool)

    def test_timing_records_staffline_step(self):
        metrics = self.probe("presets")["default"]["metrics"]
        self.assertGreater(metrics["steps_timing_ms"]["staffline"], 0.0)


class PresetConfigInvariantTest(unittest.TestCase):
    """preset 覆盖仍生效——修复没有偷偷改配置解析（纯函数，无需 cv2）。"""

    def test_scan_preset_uses_otsu(self):
        cfg, _source, _warns = load_config(preset="scan")
        self.assertEqual(cfg.binarize_method, "otsu")

    def test_photo_preset_enables_deskew(self):
        cfg, _source, _warns = load_config(preset="photo")
        self.assertTrue(cfg.enable_deskew)

    def test_default_preset_still_requests_denoise(self):
        """配置层仍请求 denoise=3；钳制发生在**运行期**而非配置期。

        这条很重要：修复刻意没有改配置默认值，否则线粗的扫描件
        也会永久失去去噪能力。
        """
        cfg, _source, _warns = load_config(preset="default")
        self.assertEqual(cfg.denoise_strength, 3)


# ---------------------------------------------------------------------------
# 子进程 worker：唯一 import cv2 的地方
# ---------------------------------------------------------------------------
def _worker_main() -> int:
    """跑完全部像素级场景，把结果以 JSON 打到 stdout。"""
    import shutil
    import tempfile

    import cv2
    import numpy as np

    import omr_preprocess
    from omr_preprocess import PreprocessConfig, preprocess_for_omr

    def make_sheet(thickness: int = 1):
        """合成一页乐谱灰度图：白纸 + N 个五线栏 + 符头/符干。"""
        page = np.full((PAGE_H, PAGE_W), 255, dtype=np.uint8)
        margin_x, margin_y = 80, 120
        system_gap = (PAGE_H - 2 * margin_y) // N_SYSTEMS
        for s in range(N_SYSTEMS):
            top = margin_y + s * system_gap
            for line in range(5):
                y = top + line * LINE_GAP
                page[y:y + thickness, margin_x:PAGE_W - margin_x] = 0
            # 符头 + 符干：制造"非五线"墨迹，避免测量退化成平凡解
            for k in range(12):
                cx = margin_x + 60 + k * 110
                cy = top + (k % 5) * LINE_GAP
                cv2.ellipse(page, (cx, cy), (7, 5), 0, 0, 360, 0, -1)
                cv2.line(page, (cx + 7, cy), (cx + 7, cy - 40), 0, 2)
        return page

    workdir = tempfile.mkdtemp(prefix="pudu_bugc_worker_")
    try:
        def write_sheet(name: str, thickness: int) -> str:
            path = os.path.join(workdir, name)
            cv2.imwrite(path, make_sheet(thickness))
            return path

        def base_cfg(**overrides) -> PreprocessConfig:
            cfg = PreprocessConfig()
            cfg.denoise_strength = 3        # railA 的肇事配置
            cfg.enable_deskew = False
            cfg.enable_border_crop = False
            for key, value in overrides.items():
                setattr(cfg, key, value)
            return cfg

        def run(tag: str, src: str, cfg: PreprocessConfig) -> dict:
            """跑一次预处理，连同产物落盘情况一起返回。"""
            dst = os.path.join(workdir, f"{tag}.pre.png")
            if os.path.exists(dst):
                os.remove(dst)
            metrics = preprocess_for_omr(src, dst, cfg)
            return {
                "metrics": metrics,
                "src": src,
                "dst_exists": os.path.isfile(dst),
                "dst_size": os.path.getsize(dst) if os.path.isfile(dst) else 0,
            }

        src_1px = write_sheet("sheet1.png", 1)
        src_5px = write_sheet("sheet5.png", 5)
        out: dict = {}

        # --- 测量准确性 ---
        out["thickness_by_gt"] = {
            str(t): omr_preprocess._estimate_staffline_thickness_px(
                cv2, np, make_sheet(t))
            for t in (1, 2, 3, 5)
        }
        blank = np.full((PAGE_H, PAGE_W), 255, dtype=np.uint8)
        out["energy_sheet"] = omr_preprocess._staffline_energy(
            cv2, make_sheet(1))
        out["energy_blank"] = omr_preprocess._staffline_energy(cv2, blank)
        out["thickness_blank"] = omr_preprocess._estimate_staffline_thickness_px(
            cv2, np, np.full((200, 200), 255, dtype=np.uint8))

        # --- fixture 真实性：medianBlur 对不同线宽的杀伤 ---
        for tag, thickness in (("1px", 1), ("5px", 5)):
            gray = make_sheet(thickness)
            before = omr_preprocess._staffline_energy(cv2, gray)
            after = omr_preprocess._staffline_energy(
                cv2, cv2.medianBlur(gray, 3))
            out[f"median3_retention_{tag}"] = omr_preprocess.staffline_retention(
                before, after)

        # --- 防线①：去噪钳制 ---
        out["default_1px"] = run("default_1px", src_1px, base_cfg())
        out["thick_5px"] = run("thick_5px", src_5px, base_cfg())
        out["denoise_off"] = run("denoise_off", src_1px,
                                 base_cfg(denoise_strength=0))
        out["binarize_adaptive"] = run(
            "bin_ada", src_1px,
            base_cfg(denoise_strength=0, binarize_method="adaptive"))
        out["binarize_otsu"] = run(
            "bin_otsu", src_1px,
            base_cfg(denoise_strength=0, binarize_method="otsu"))

        # 线宽测量抛异常 -> 保守关去噪且不阻断
        original_estimate = omr_preprocess._estimate_staffline_thickness_px

        def _boom(*_args, **_kwargs):
            raise RuntimeError("模拟测量炸了")

        omr_preprocess._estimate_staffline_thickness_px = _boom
        try:
            out["measure_fail"] = run("measure_fail", src_1px, base_cfg())
        finally:
            omr_preprocess._estimate_staffline_thickness_px = original_estimate

        # --- 防线②：熔断（先确认不绕过时不误伤） ---
        out["breaker_healthy"] = run("breaker_healthy", src_1px,
                                     base_cfg(denoise_strength=5))

        original_safe = omr_preprocess.safe_denoise_strength
        omr_preprocess.safe_denoise_strength = lambda *_a, **_k: 5
        try:
            out["breaker"] = run("breaker", src_1px,
                                 base_cfg(denoise_strength=5))
            cfg_strict = base_cfg(denoise_strength=5)
            cfg_strict.fail_open = False
            out["breaker_failopen_false"] = run(
                "breaker_strict", src_1px, cfg_strict)
        finally:
            omr_preprocess.safe_denoise_strength = original_safe

        # --- 真实 preset 全跑一遍 ---
        presets = {}
        for name in ("default", "scan", "photo", "low_contrast"):
            cfg, _source, _warns = omr_preprocess.load_config(preset=name)
            presets[name] = run(f"preset_{name}", src_1px, cfg)
        out["presets"] = presets

        sys.stdout.write(_MARKER + "\n")
        # ensure_ascii=True：把中文全部转义成 \uXXXX，载荷是纯 ASCII，
        # 无论管道用 UTF-8 / GBK / cp1252 都能无损穿过；父进程 json.loads
        # 会还原成原本的中文。这是与控制台代码页解耦的第二道保险，
        # 即便上面的 PYTHONIOENCODING 被外部环境覆盖也依然成立。
        sys.stdout.write(json.dumps(out, ensure_ascii=True))
        sys.stdout.write("\n")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    if "--worker" in sys.argv:
        raise SystemExit(_worker_main())
    unittest.main()
