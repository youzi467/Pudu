# -*- coding: utf-8 -*-
"""
谱渡 Pudu · 本地网页应用后端（stdlib only）
=============================================

给 OMR 引擎（Audiveris 默认；oemer 回退）+ Pudu.exe 补一层薄 HTTP 壳，
面向非开发者用户：浏览器上传乐谱图片/PDF → 简谱预览 + MusicXML 下载 + 需校对面板。

设计要点（docs/user-side-interface-design.md §5、计划 sorted-twirling-gizmo.md）：
  * 零新依赖：仅 ``http.server`` / ``threading`` / ``subprocess`` / ``json`` 等 stdlib。
  * FROZEN_PATHS 零 diff：CMakeLists.txt / vcpkg.json / tools/omr_oemer.py 不动；
    识别走子进程 ``omr_audiveris.py <img> <out>.pred.musicxml``（AV 默认，PDF 逐页
    -sheets 拼接）；engine=oemer 时走 ``omr_oemer.py ... --f3-geometric --rhythm-geometric``，
    L2 渲染走子进程 ``Pudu.exe <mx> --to-jianpu-l2 <out.html>``。
  * 成品口径：``final.musicxml`` = 修正后的 ``.pred.musicxml`` 文件本身（复制规范化），
    绝不走 ``--to-musicxml``（会五线→简→五线重建，divisions→4）。
  * 定点重跑：进程内 ``import geometric_pitch``（纯 stdlib），
    ``repair_forward_overflow`` + 循环 ``recompute_rhythm_from_geometry`` 至 0
    （对齐 build/_rerun_fixedpoint.py 的定盘逻辑）。
  * 作业目录 ``build/_ui_jobs/<uuid>/``（build/ 已 gitignored）。
  * 仅监听 127.0.0.1；取消/超时/异常一律显式 error（对齐 product-status §5）。

模块分段（纯函数段不依赖服务器对象、可被 tests 直接 import）：
  CONFIG → PURE_UTIL → JOB → WORKER → HANDLER → MAIN

用法：
    venv_python tools/pudu_server.py [--port 8765] [--host 127.0.0.1]
"""

import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------
# CONFIG（常量 + env 覆盖）
# ----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))      # tools/
REPO = os.path.dirname(HERE)                            # 仓库根
TOOLS = HERE
BUILD = os.path.join(REPO, "build")
JOBS_ROOT = os.path.join(BUILD, "_ui_jobs")             # gitignored（build/ 首行忽略）

PUDU_EXE = os.path.join(BUILD, "Pudu.exe")
UI_HTML = os.path.join(TOOLS, "pudu_ui.html")
VENV_PYTHON = os.environ.get("PUDU_OMR_PYTHON") or sys.executable

# oemer GPU 运行所需 DLL 目录（仅追加存在者；缺失则 CPU 回退，见 inject_cuda_path）
CUDA_BINS = [
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.3\bin\x64",
    r"C:\Program Files\NVIDIA\CUDNN\v9.24\bin\13.3\x64",
]

OCR_TIMEOUT_S = int(os.environ.get("PUDU_OCR_TIMEOUT", "600"))
HOST = "127.0.0.1"                                     # 只绑回环，不暴露外网
PORT = int(os.environ.get("PUDU_PORT", "8765"))
MAX_UPLOAD_BYTES = 64 * 1024 * 1024                    # 64MB

# 识别引擎：AV 默认（A/B 全胜）；oemer 回退。env PUDU_OMR_ENGINE 覆盖。
DEFAULT_ENGINE = os.environ.get("PUDU_OMR_ENGINE", "audiveris")
_ENGINES = {"audiveris", "oemer"}

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".pdf"}
_RESULT_FILES = {"jianpu.html", "final.musicxml", "review.json"}
_JOB_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import geometric_pitch as gp  # noqa: E402  纯 stdlib，供定点重跑 + footnote 常量

_MARK_PREFIX = gp._MARK_PREFIX                       # "需校对："
_REASON_PITCH_SKIP = gp._REASON_PITCH_SKIP           # "几何音高未验证"
_REASON_RHYTHM_SKIP = gp._REASON_RHYTHM_SKIP         # "几何时值未校正"


# ----------------------------------------------------------------------
# PURE_UTIL（可单测，不碰服务器对象）
# ----------------------------------------------------------------------

def inject_cuda_path(env: Dict[str, str]) -> Dict[str, str]:
    """把存在的 CUDA/CUDNN DLL 目录前置进 PATH（GPU 用；缺失则 CPU 回退）。"""
    env = dict(env)
    extra = [d for d in CUDA_BINS if os.path.isdir(d)]
    if not extra:
        return env
    path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join(extra + ([path] if path else []))
    return env


def build_ocr_cmd(image: str, mx_out: str, engine: str = DEFAULT_ENGINE) -> List[str]:
    """识别命令：audiveris = omr_audiveris.py（AV -batch，PDF 逐页拼接）；
    oemer = omr_oemer.py 一次子进程（oemer + keysig + F3 + R-geo + sidecar）。"""
    if engine == "audiveris":
        return [VENV_PYTHON, os.path.join(TOOLS, "omr_audiveris.py"), image, mx_out]
    return [VENV_PYTHON, os.path.join(TOOLS, "omr_oemer.py"), image, mx_out,
            "--f3-geometric", "--rhythm-geometric"]


def build_render_cmd(mx: str, l2_html: str) -> List[str]:
    """L2 简谱渲染：Pudu.exe <mx> --to-jianpu-l2 <out.html>。"""
    return [PUDU_EXE, mx, "--to-jianpu-l2", l2_html]


def build_fixture_cmd(image: str, l2_html: str) -> List[str]:
    """fixture 演示：Pudu.exe --from-omr <img> --omr-engine fixture --to-jianpu-l2。"""
    return [PUDU_EXE, "--from-omr", image, "--omr-engine", "fixture",
            "--to-jianpu-l2", l2_html]


def parse_multipart(body: bytes, content_type: str) -> Tuple[str, bytes]:
    """手写 multipart/form-data 解析（Python 3.13 已移除 cgi）。

    Returns:
        (filename, data)：第一个带 ``filename=`` 的 file 字段。
    Raises:
        ValueError: boundary 缺失 / 无 file 字段。
    """
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    boundary = (m.group(1) or m.group(2)) if m else None
    if not boundary:
        raise ValueError("multipart boundary 缺失")
    delimiter = b"--" + boundary.strip().encode("ascii", "replace")
    for part in body.split(delimiter):
        if b"\r\n\r\n" not in part:
            continue  # preamble / 结尾 "--"
        header, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        htext = header.decode("utf-8", "replace")
        for line in htext.splitlines():
            if line.lower().lstrip().startswith("content-disposition"):
                mf = re.search(r'filename="([^"]*)"', line)
                if mf:
                    fname = mf.group(1)
                    if fname:
                        return fname, data
    raise ValueError("multipart 无 file 字段")


def extract_footnotes(mx_path: str) -> dict:
    """从成品 MusicXML 提取需校对标记 → review.json 结构（读侧，天然幂等）。

    返回::
        {"total": N, "categories": {"原因": 计数, ...},
         "items": [{"measure":"12","note_index":3,"reasons":[...],
                    "step":"C","octave":"4"}, ...]}
    文件缺失/解析失败 → 空结构（非致命）。note_index 为小节内文档序（含 chord 内音符）。
    """
    empty = {"total": 0, "categories": {}, "items": []}
    if not mx_path or not os.path.isfile(mx_path):
        return empty
    try:
        tree = ET.parse(mx_path)
    except Exception:  # noqa: BLE001
        return empty
    root = tree.getroot()
    gp._strip_ns(root)

    items: List[dict] = []
    for part in root.iter("part"):
        for measure in part.iter("measure"):
            num = str(measure.get("number", "?"))
            note_index = 0
            for note in measure.iter("note"):
                note_index += 1
                fn = note.find("notations/footnote")
                if fn is None or not fn.text:
                    continue
                text = fn.text.strip()
                if text.startswith(_MARK_PREFIX):
                    text = text[len(_MARK_PREFIX):]
                reasons = [r.strip() for r in text.split("；") if r.strip()]
                item: dict = {"measure": num, "note_index": note_index,
                              "reasons": reasons}
                pitch = note.find("pitch")
                if pitch is not None:
                    step = pitch.find("step")
                    octv = pitch.find("octave")
                    if step is not None and step.text:
                        item["step"] = step.text
                    if octv is not None and octv.text:
                        item["octave"] = octv.text
                items.append(item)

    categories: Dict[str, int] = {}
    for it in items:
        for r in it["reasons"]:
            categories[r] = categories.get(r, 0) + 1
    return {"total": len(items), "categories": categories, "items": items}


def run_fixedpoint(mx: str, sc: str) -> int:
    """进程内定点重跑：forward 修复 + F3 + R-geo 循环至 0 改写（对齐定盘口径）。

    Args:
        mx: 待校正 MusicXML（就地写回）。
        sc: 对应 ``<base>.pred.geometry.json``。
    Returns:
        R-geo 累计改写音符数（0 = 已是定点）。
    """
    if not os.path.isfile(sc):
        return 0
    gp.repair_forward_overflow(mx)
    total = 0
    for _ in range(5):
        gp.recompute_pitch_from_geometry(mx, sc)
        n = gp.recompute_rhythm_from_geometry(mx, sc)
        total += n
        if n == 0:
            break
    return total


def _new_job_id() -> str:
    return str(uuid.uuid4())


def _assert_job_id(job_id: str) -> str:
    """job_id 正则白名单（防路径穿越；配合 registry 查找双保险）。"""
    if not _JOB_ID_RE.match(job_id or ""):
        raise ValueError("无效 job_id")
    return job_id


def _placeholder_png() -> bytes:
    """demo 无上传体时合成 1×1 透明 PNG（fixture 引擎不读图内容，仅需文件存在）。"""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ----------------------------------------------------------------------
# JOB（线程安全作业区）
# ----------------------------------------------------------------------

class JobState:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """单个识别作业（线程安全：所有可变字段经 self.lock 读写）。"""
    id: str
    dir: str                       # 作业目录（build/_ui_jobs/<id>/）
    engine: str = DEFAULT_ENGINE   # "audiveris" | "oemer"
    demo: bool = False
    filename: str = ""
    input_ext: str = ""
    input_path: Optional[str] = None
    state: str = JobState.QUEUED
    stage: Optional[str] = None
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    proc: Optional[subprocess.Popen] = None
    worker: Optional[threading.Thread] = None

    # ---- 派生路径（识别/渲染/成品，全部落在 job.dir 内） ----
    @property
    def pred_mx(self) -> str:
        return os.path.join(self.dir, "input.pred.musicxml")

    @property
    def sidecar(self) -> str:
        return os.path.join(self.dir, "input.pred.geometry.json")

    @property
    def final_mx(self) -> str:
        return os.path.join(self.dir, "final.musicxml")

    @property
    def l2_html(self) -> str:
        return os.path.join(self.dir, "jianpu.html")

    @property
    def review_json(self) -> str:
        return os.path.join(self.dir, "review.json")


_STAGE_PROGRESS = {
    "extract": 30, "keysig": 40, "f3": 50, "rgeo": 55,
    "audiveris": 45, "fixedpoint": 70, "render": 90,
}


class JobManager:
    """作业注册表 + 状态更新 + 取消/退出清理。"""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}

    def create(self, ext: str, demo: bool = False, filename: str = "",
               engine: str = DEFAULT_ENGINE) -> Job:
        job_id = _new_job_id()
        d = os.path.join(self.root, job_id)
        os.makedirs(d, exist_ok=True)
        job = Job(id=job_id, dir=d, engine=engine, demo=demo,
                  filename=filename, input_ext=ext)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())

    def set_state(self, job: Job, state: str, stage: Optional[str] = None,
                  message: Optional[str] = None, progress: Optional[int] = None,
                  error: Optional[str] = None):
        with job.lock:
            job.state = state
            if stage is not None:
                job.stage = stage
            if message is not None:
                job.message = message
            if error is not None:
                job.error = error
            if progress is not None:
                job.progress = progress
            elif state == JobState.RUNNING and stage in _STAGE_PROGRESS:
                job.progress = _STAGE_PROGRESS[stage]
            elif state == JobState.DONE:
                job.progress = 100
            elif state in (JobState.ERROR, JobState.CANCELLED):
                job.progress = job.progress or 0
            job.updated = time.time()

    def cancel(self, job_id: str) -> bool:
        """置 cancel_event；运行中则 kill 子进程（worker 侧再判定终态）。"""
        job = self.get(job_id)
        if job is None:
            return False
        with job.lock:
            if job.state in (JobState.DONE, JobState.ERROR, JobState.CANCELLED):
                return False
        job.cancel_event.set()
        proc = job.proc
        if proc is not None and proc.poll() is None:
            _kill_proc(job)
        return True

    def shutdown(self, join_timeout: float = 10.0):
        """退出清理：kill 全部运行中子进程 + join worker 线程（防僵尸）。"""
        jobs = self.list()
        for job in jobs:
            job.cancel_event.set()
            proc = job.proc
            if proc is not None and proc.poll() is None:
                _kill_proc(job)
        for job in jobs:
            w = job.worker
            if w is not None and w.is_alive():
                w.join(timeout=join_timeout)


# ----------------------------------------------------------------------
# WORKER（一个 job 一个线程的识别管线）
# ----------------------------------------------------------------------

class OcrError(RuntimeError):
    """识别管线显式失败（对齐 product-status §5「失败页明确报错」）。"""


def _kill_proc(job: Job):
    """kill 子进程并 wait（防僵尸；kill 后必 wait）。"""
    proc = job.proc
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10.0)
    except Exception:  # noqa: BLE001
        pass
    job.proc = None


def run_worker(job: Job, mgr: JobManager):
    """作业状态机：queued → running[stage] → done / error / cancelled。"""
    try:
        if job.demo:
            _run_demo(mgr, job)
        else:
            _run_engine(mgr, job)
            if job.cancel_event.is_set():
                return
            if job.engine == "audiveris":
                # AV 自带音高/时值/部分拍号，无 oemer sidecar：仅拍号校验打标兜底
                # （幂等；omr_audiveris.py 已打标则此处为 no-op）。
                n_mark = gp.mark_meter_constraint_failures(job.pred_mx, "")
                if n_mark:
                    mgr.set_state(job, JobState.RUNNING, "fixedpoint",
                                  f"节拍校验标记 {n_mark} 小节")
            else:
                _run_fixedpoint(mgr, job)
            shutil.copy2(job.pred_mx, job.final_mx)      # 成品 = 修正后的 pred 文件本身
            _run_render(mgr, job)
        _finalize(mgr, job)
    except OcrError as e:
        if not job.cancel_event.is_set():
            mgr.set_state(job, JobState.ERROR, error=str(e))
    except Exception as e:  # noqa: BLE001
        if not job.cancel_event.is_set():
            mgr.set_state(job, JobState.ERROR,
                          error=f"内部错误: {type(e).__name__}: {e}")
    finally:
        job.proc = None
        if job.cancel_event.is_set():
            mgr.set_state(job, JobState.CANCELLED, message="已取消")


def _run_engine(mgr: JobManager, job: Job):
    """识别子进程（AV / oemer；逐行解析 stage 关键字，支持超时/取消）。"""
    mgr.set_state(job, JobState.RUNNING, "extract", "提取音符中…")
    cmd = build_ocr_cmd(job.input_path, job.pred_mx, engine=job.engine)
    env = inject_cuda_path({**os.environ, "PYTHONIOENCODING": "utf-8"})
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            env=env, creationflags=_CREATE_NO_WINDOW)
    job.proc = proc

    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def _pump():
        try:
            for line in proc.stdout:
                q.put(line)
        except Exception:  # noqa: BLE001
            pass
        finally:
            q.put(None)

    threading.Thread(target=_pump, daemon=True).start()

    deadline = time.monotonic() + OCR_TIMEOUT_S
    tail: List[str] = []
    while True:
        if job.cancel_event.is_set():
            _kill_proc(job)
            return
        if time.monotonic() > deadline:
            _kill_proc(job)
            raise OcrError(f"识别超时（{OCR_TIMEOUT_S}s）")
        try:
            line = q.get(timeout=0.5)
        except queue.Empty:
            continue
        if line is None:
            break
        msg = line.strip()
        tail.append(msg)
        if len(tail) > 50:
            tail.pop(0)
        if "[keysig]" in msg:
            mgr.set_state(job, JobState.RUNNING, "keysig", "调号校正中…")
        elif "[f3]" in msg:
            mgr.set_state(job, JobState.RUNNING, "f3", "几何音高校正中…")
        elif "[rhythm]" in msg:
            mgr.set_state(job, JobState.RUNNING, "rgeo", "几何时值校正中…")
        elif "[audiveris]" in msg:
            # AV stage：PDF 逐页进度 / 拍号打标（消息取括号后文本）
            sub = msg.split("]", 1)[-1].strip() or "Audiveris 识别中…"
            mgr.set_state(job, JobState.RUNNING, "audiveris", sub)

    rc = proc.wait()
    job.proc = None
    if job.cancel_event.is_set():
        return
    if rc != 0:
        raise OcrError(f"识别失败（退出码 {rc}）: {tail[-1] if tail else '无输出'}")
    if not os.path.isfile(job.pred_mx):
        raise OcrError("识别未产出 MusicXML")


def _run_fixedpoint(mgr: JobManager, job: Job):
    """进程内定点重跑（F3/R-geo 至 0 改写，交付态对齐定盘 83.3% 口径）。"""
    mgr.set_state(job, JobState.RUNNING, "fixedpoint", "定点校验中…")
    if not os.path.isfile(job.sidecar):
        raise OcrError("sidecar 缺失，无法几何校正")
    run_fixedpoint(job.pred_mx, job.sidecar)
    # 方案1：拍号推断 + <time> 注入（oemer 不产拍号，pred 无 <time> → 渲染回退 4/4）。
    # 推断失败保留默认（pudu_ui 展示原文案；注入幂等，已含 <time> 时仅更新）。
    meter = gp.inject_time_signature(job.pred_mx, job.sidecar)
    if meter:
        mgr.set_state(job, JobState.RUNNING, "fixedpoint",
                      f"拍号推断 {meter[0]}/{meter[1]}")
    # 方案4：拍号约束保守重切（oemer 小节分段错误是坏小节主导根因——音符全对仅
    # 错位。gate 内页重切；gate 外保留原样交方案2 打标，不猜边界）。
    n_rslice = gp.re_slice_measures(job.pred_mx, job.sidecar)
    if n_rslice:
        mgr.set_state(job, JobState.RUNNING, "fixedpoint",
                      f"小节重切 {n_rslice} 小节")
    # 方案2：小节节拍约束校验 + footnote 标记（重切残尾/off-target 与 gate 外页兜底）。
    n_mark = gp.mark_meter_constraint_failures(job.pred_mx, job.sidecar)
    if n_mark:
        mgr.set_state(job, JobState.RUNNING, "fixedpoint",
                      f"节拍校验标记 {n_mark} 小节")


def _run_render(mgr: JobManager, job: Job):
    """L2 简谱渲染子进程。"""
    cmd = build_render_cmd(job.final_mx, job.l2_html)
    _run_pudu(mgr, job, cmd, "render", "简谱渲染中…")


def _run_demo(mgr: JobManager, job: Job):
    """fixture 演示管线（零 GPU）：Pudu 原生写 <input>.pudu.musicxml + L2。"""
    mgr.set_state(job, JobState.RUNNING, "extract", "演示样例生成中…")
    cmd = build_fixture_cmd(job.input_path, job.l2_html)
    _run_pudu(mgr, job, cmd, "render", "简谱渲染中…")
    src = job.input_path + ".pudu.musicxml"
    if not os.path.isfile(src):
        raise OcrError("fixture 未产出 MusicXML")
    shutil.copy2(src, job.final_mx)


def _run_pudu(mgr: JobManager, job: Job, cmd: List[str], stage: str, msg: str):
    """Pudu.exe 通用子进程运行（communicate + 超时 + 取消后 kill）。"""
    if not os.path.isfile(PUDU_EXE):
        raise OcrError(f"Pudu.exe 缺失: {PUDU_EXE}")
    mgr.set_state(job, JobState.RUNNING, stage, msg)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            env=inject_cuda_path(os.environ.copy()),
                            creationflags=_CREATE_NO_WINDOW)
    job.proc = proc
    try:
        out, _ = proc.communicate(timeout=OCR_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _kill_proc(job)
        raise OcrError(f"{stage} 超时（{OCR_TIMEOUT_S}s）")
    finally:
        job.proc = None
    if job.cancel_event.is_set():
        return
    if proc.returncode != 0:
        tail = (out or "")[-400:].strip()
        raise OcrError(f"{stage} 失败（退出码 {proc.returncode}）: {tail or '无输出'}")


def _finalize(mgr: JobManager, job: Job):
    """写 review.json + 置 done。"""
    if not os.path.isfile(job.final_mx):
        raise OcrError("缺少 final.musicxml")
    if not os.path.isfile(job.l2_html):
        raise OcrError("缺少 jianpu.html")
    review = extract_footnotes(job.final_mx)
    with open(job.review_json, "w", encoding="utf-8") as f:
        json.dump(review, f, ensure_ascii=False, indent=2)
    mgr.set_state(job, JobState.DONE, message="完成", progress=100)


# ----------------------------------------------------------------------
# HANDLER（HTTP 路由）
# ----------------------------------------------------------------------

class PuduHandler(BaseHTTPRequestHandler):
    """HTTP 接口。mgr 由 serve() 注入为类属性。"""

    mgr: JobManager = None  # type: ignore
    server_version = "PuduUI"

    # ---- 工具 ----
    def _send_bytes(self, code: int, body: bytes, content_type: str,
                    extra: Optional[Dict[str, str]] = None,
                    attachment: Optional[str] = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if attachment:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{attachment}"')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code: int, obj: dict):
        self._send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

    def _send_file(self, path: str, content_type: str,
                   attachment: Optional[str] = None):
        if not os.path.isfile(path):
            self._send_404(f"文件不存在: {os.path.basename(path)}")
            return
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError as e:
            self._send_500(f"读文件失败: {e}")
            return
        self._send_bytes(200, body, content_type, attachment=attachment)

    def _send_400(self, msg: str):
        self._send_json(400, {"error": msg})

    def _send_404(self, msg: str = "not found"):
        self._send_json(404, {"error": msg})

    def _send_413(self, msg: str):
        self._send_json(413, {"error": msg})

    def _send_409(self, msg: str):
        self._send_json(409, {"error": msg})

    def _send_500(self, msg: str):
        self._send_json(500, {"error": msg})

    def _job_or_404(self, job_id: str):
        try:
            _assert_job_id(job_id)
        except ValueError:
            self._send_404("无效 job_id")
            return None
        job = self.mgr.get(job_id)
        if job is None:
            self._send_404("作业不存在")
            return None
        return job

    # ---- GET ----
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/":
            self._send_file(UI_HTML, "text/html; charset=utf-8")
        elif path == "/api/jobs":  # P1 顺手提供（辅助多任务/调试）
            jobs = []
            for j in self.mgr.list():
                jobs.append({"id": j.id, "state": j.state, "stage": j.stage,
                             "filename": j.filename, "demo": j.demo,
                             "created": j.created, "updated": j.updated})
            jobs.sort(key=lambda d: d["created"], reverse=True)
            self._send_json(200, {"jobs": jobs})
        elif path.startswith("/api/status/"):
            self._get_status(path[len("/api/status/"):])
        elif path.startswith("/api/result/"):
            self._get_result(path[len("/api/result/"):])
        else:
            self._send_404()

    def _get_status(self, job_id: str):
        job = self._job_or_404(job_id)
        if job is None:
            return
        self._send_json(200, {
            "id": job.id, "state": job.state, "stage": job.stage,
            "progress": job.progress, "message": job.message, "error": job.error,
            "created": job.created, "updated": job.updated,
            "demo": job.demo, "filename": job.filename,
        })

    def _get_result(self, rest: str):
        parts = rest.split("/", 1)
        if len(parts) != 2:
            self._send_404()
            return
        job_id, name = parts
        job = self._job_or_404(job_id)
        if job is None:
            return
        if job.state != JobState.DONE:
            self._send_404("作业未完成")
            return
        if name == "image":
            path, ct = job.input_path, f"image/{job.input_ext.lstrip('.')}"
            self._send_file(path, ct)
            return
        if name not in _RESULT_FILES:
            self._send_404("未知结果文件")
            return
        path = os.path.join(job.dir, name)
        ct = "text/html; charset=utf-8" if name == "jianpu.html" else \
            ("application/json; charset=utf-8" if name == "review.json" else
             "application/xml; charset=utf-8")
        attachment = name if name == "final.musicxml" else None
        self._send_file(path, ct, attachment=attachment)

    # ---- POST ----
    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/api/ocr":
            self._handle_ocr(parsed.query)
        elif path.startswith("/api/cancel/"):
            self._handle_cancel(path[len("/api/cancel/"):])
        else:
            self._send_404()

    def _read_body(self) -> Tuple[bytes, Optional[int]]:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            return b"", 400
        length = self.headers.get("Content-Length")
        try:
            length = int(length) if length else 0
        except ValueError:
            return b"", 400
        if length > MAX_UPLOAD_BYTES:
            return b"", 413
        body = self.rfile.read(length) if length else b""
        return body, None  # None = 成功

    def _handle_ocr(self, query: str):
        qs = urllib.parse.parse_qs(query)
        demo = qs.get("demo", ["0"])[0] in ("1", "true", "yes")
        engine = qs.get("engine", [DEFAULT_ENGINE])[0]
        if engine not in _ENGINES:
            self._send_400(f"未知引擎: {engine}（可选: {sorted(_ENGINES)}）")
            return
        body, err = self._read_body()
        if err is not None:
            if err == 413:
                self._send_413("文件超过 64MB 上限")
            else:
                self._send_400("请求体格式不支持")
            return

        ct = self.headers.get("Content-Type", "")
        filename = self.headers.get("X-Filename", "")
        if body and not filename:
            if ct.startswith("multipart/form-data"):
                try:
                    filename, body = parse_multipart(body, ct)
                except ValueError as e:
                    self._send_400(f"multipart 解析失败: {e}")
                    return
            else:
                self._send_400("缺少 X-Filename 头或 multipart 表单")
                return
        if demo and not body:
            body = _placeholder_png()
            filename = filename or "demo.png"

        if not body:
            self._send_400("空文件")
            return
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _IMAGE_EXTS:
            self._send_400(f"仅支持 {sorted(_IMAGE_EXTS)} 图片/PDF（收到: {filename or '?'}）")
            return

        try:
            job = self.mgr.create(ext, demo=demo, filename=filename, engine=engine)
            in_path = os.path.join(job.dir, "input" + ext)
            with open(in_path, "wb") as f:
                f.write(body)
            job.input_path = in_path
            t = threading.Thread(target=run_worker, args=(job, self.mgr), daemon=True)
            job.worker = t
            t.start()
        except OSError as e:
            self._send_500(f"作业创建失败: {e}")
            return
        self._send_json(200, {"job_id": job.id, "demo": demo})

    def _handle_cancel(self, job_id: str):
        try:
            _assert_job_id(job_id)
        except ValueError:
            self._send_404("无效 job_id")
            return
        if self.mgr.cancel(job_id):
            self._send_json(200, {"ok": True})
        else:
            self._send_409("作业已完成或不存在")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def serve(host: str, port: int, mgr: JobManager) -> ThreadingHTTPServer:
    """构造并返回已绑定（未 serve_forever）的服务器；仅监听回环。"""
    PuduHandler.mgr = mgr
    httpd = ThreadingHTTPServer((host, port), PuduHandler)
    httpd.daemon_threads = True
    return httpd


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    p = argparse.ArgumentParser(prog="pudu_server",
                                description="谱渡 Pudu · 本地网页应用后端")
    p.add_argument("--host", default=HOST, help="仅监听回环即可（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--jobs", default=JOBS_ROOT, help="作业根目录（默认 build/_ui_jobs）")
    p.add_argument("--no-browser", action="store_true",
                   help="不自动打开浏览器（如无头/自动化环境）")
    args = p.parse_args(argv)

    jobs_root = os.path.abspath(args.jobs)
    mgr = JobManager(jobs_root)
    try:
        httpd = serve(args.host, args.port, mgr)
    except OSError as e:
        sys.stderr.write(f"[错误] 无法监听 {args.host}:{args.port}: {e}\n")
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"谱渡 Pudu 已启动: {url}", flush=True)
    print(f"作业目录: {jobs_root}", flush=True)
    print("仅监听回环；Ctrl+C 退出。请勿直接双击打开 pudu_ui.html，须从本服务器访问。",
          flush=True)
    if not args.no_browser and args.host in ("127.0.0.1", "localhost", "::1"):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001  自动开浏览器失败不致命
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        mgr.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
