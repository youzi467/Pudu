#!/usr/bin/env python3
# ----------------------------------------------------------------------
# 谱渡 Pudu · 引擎迁移 · Audiveris 运行器
#
# 适配器以子进程方式调用本脚本：
#   python omr_audiveris.py <input_image_or_pdf> <output.musicxml>
#
# 职责：用 Audiveris 5.11.0（自带 JRE 的桌面 OMR，-batch CLI）把乐谱图片/PDF
# 识别为 MusicXML。随后做：
#   * keysig：**不覆盖**——AV 图像 glyph 检测 13/13 全对，oemer 的统计
#     fallback 反而会把正确 fifths 覆盖掉（如 canon_p1 2→1）。
#   * 拍号校验打标：复用 geometric_pitch.mark_meter_constraint_failures（无
#     sidecar 依赖），给「每小节节拍不符」打 <footnote>，供 review.json「需校对」
#     面板（幂等，pudu_server 层再跑为 no-op）。
#   * 不做 F3/R-geo：AV 音高 97.56% / 时值 99.26% 已大幅胜出，且无 oemer
#     geometry sidecar 源。
#
# PDF 策略：AV 整册 Book 模式坏页会拖垮整本 export（实测 canon_p2 "No system
# found" → 整册失败），故逐页 `-sheets N` 单独跑：坏页单独 skip，好页不受牵连。
# 各页独立 .mxl 解包后用 ET 拼接为一个合法 score-partwise（见 merge_pages：
# 保留页 1 骨架、后续页只取 measure、顺序重编号、divisions 一致性守卫）。
#
# 单图策略（本文件的自动放大重试）：用户上传的 PNG/JPG 可能是截图/导出而来，
# 分辨率不足时 AV 测得 interline（五线谱行距）过小 → "resolution is too low"
# / "interline value is NOT RELIABLE" → Sheet 标记 invalid → export 失败 rc=1。
# 此时自动用 PIL LANCZOS 放大 2x→3x 重试（实测 968x1369/interline 8px 的图
# 放大后 RC=0，fifths/time/音符数与原 PDF 单页一致）。正常分辨率图首跑成功，
# 不经过放大路径、零影响。
#
# 依赖：Audiveris 5.11.0 安装（内置 JRE，无需系统 Java）。定位顺序：
#   env PUDU_AUDIVERIS_EXE → build/_audiveris/extract/Audiveris/Audiveris.exe
#   → PATH 中的 Audiveris.exe。
#
# 契约（与 omr_oemer.py 同构）：<input> <output.musicxml>；exit 0/1/2；
# stage 行 `[audiveris]` / `[ok]` 打到 stdout 供 pudu_server 进度解析。
# ----------------------------------------------------------------------
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

try:
    from geometric_pitch import mark_meter_constraint_failures  # noqa: E402
except Exception as e:  # noqa: BLE001
    # 拍号打标非致命：AV 识别本身不依赖 geometric_pitch
    mark_meter_constraint_failures = None
    sys.stderr.write(f"[警告] 无法导入 geometric_pitch（拍号打标跳过）: {e}\n")

# 仓库默认 AV 安装路径（gitignored；由 A/B 阶段 MSI 解包而来）
_DEFAULT_EXE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "build", "_audiveris", "extract", "Audiveris", "Audiveris.exe")
_TIMEOUT_S = int(os.environ.get("PUDU_AUDIVERIS_TIMEOUT", "600"))
_PDF_EXT = ".pdf"


def resolve_audiveris_exe() -> Optional[str]:
    """三级选址：env PUDU_AUDIVERIS_EXE → 仓库默认路径 → PATH。

    显式指定（env）但文件不存在 → 返回 None（尊重用户覆盖意图，让错误明确）。
    """
    env = os.environ.get("PUDU_AUDIVERIS_EXE")
    if env:
        return env if os.path.isfile(env) else None
    if os.path.isfile(_DEFAULT_EXE):
        return _DEFAULT_EXE
    return shutil.which("Audiveris.exe")


def count_pdf_pages(pdf_path: str) -> int:
    """统计 PDF 页数。

    优先取 /Count 的最大值（Pages 树顶层总数，canon=/Count 2）；退化为统计
    /Type /Page 对象（`/Page\b` 不匹配 /Pages，天然排除目录对象）。
    """
    with open(pdf_path, "rb") as f:
        data = f.read()
    counts = [int(m) for m in re.findall(rb"/Count\s+(\d+)", data)]
    n = max(counts) if counts else 0
    if n <= 0:
        n = len(re.findall(rb"/Type\s*/Page\b", data))
    return n


def build_av_cmd(exe: str, in_path: str, out_dir: str, sheet: int = None) -> List[str]:
    """构造 Audiveris CLI 命令。

    [exe, -batch, -export] + [-sheets N]（PDF 逐页） + [-output, out_dir, --, in_path]
    """
    cmd = [exe, "-batch", "-export"]
    if sheet is not None:
        cmd += ["-sheets", str(sheet)]
    cmd += ["-output", out_dir, "--", in_path]
    return cmd


def _is_resolution_failure(text: str) -> bool:
    """判断 AV 失败输出是否属于「分辨率过低」（值得放大重试）。

    匹配 AV 5.11 ScaleStep / SheetStub 的关键行：
      * "resolution is too low (try 300 DPI)"
      * "This interline value is NOT RELIABLE"
      * "interline value of 8 pixels"（过低提示）
    命中任意一个即视为低分辨率边界。区分其他失败（如 No system found /
    非图片输入），那些放大无效，不应重试。
    """
    if not text:
        return False
    lowered = text.lower()
    markers = (
        "resolution is too low",
        "interline value is not reliable",
        "too low interline value",
    )
    return any(m in lowered for m in markers)


def upscale_image(in_path: str, out_path: str, scale: int) -> bool:
    """PIL LANCZOS 放大图片到 out_path（无 PIL 时返回 False）。

    放大只用于低分辨率救回（见 _is_resolution_failure）。保持灰度转换让 AV
    的 binarization 有更干净的输入——AV 自己也会 Converting max RGB to gray。
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        im = Image.open(in_path).convert("L")
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
        im.save(out_path)
        return True
    except Exception:  # noqa: BLE001
        return False


def locate_export(out_dir: str, base: str) -> Optional[str]:
    """定位 AV 导出的 .mxl。

    AV 5.11 实测平铺 out/<base>.mxl；兼容嵌套 out/<base>/<base>.mxl。逐页
    `-sheets` 各自独立临时目录时，退化为返回唯一的顶层 .mxl（容错命名差异）。
    """
    for cand in (os.path.join(out_dir, base + ".mxl"),
                 os.path.join(out_dir, base, base + ".mxl")):
        if os.path.isfile(cand):
            return cand
    m = glob.glob(os.path.join(out_dir, "*.mxl"))
    if len(m) == 1:
        return m[0]
    return None


def extract_mxl(mxl_path: str, out_musicxml: str) -> bool:
    """从 AV 的 .mxl（ZIP）解出同名 .xml 写到 out_musicxml。"""
    try:
        import zipfile
        with zipfile.ZipFile(mxl_path) as z:
            xml_name = next(n for n in z.namelist()
                            if n.endswith(".xml") and not n.startswith("META-INF"))
            data = z.read(xml_name)
    except Exception:  # noqa: BLE001
        return False
    with open(out_musicxml, "wb") as f:
        f.write(data)
    return True


# ----------------------- 多页 PDF 拼接（merge_pages） -----------------------

def _local(tag):
    """取标签本地名（去掉 XML 命名空间前缀）。"""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _strip_ns(root):
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _first_divisions(root) -> Optional[int]:
    for div in root.iter("divisions"):
        try:
            return int(float(str(div.text).strip()))
        except (TypeError, ValueError):
            continue
    return None


def _max_measure_number(part_el) -> int:
    mx = 0
    for m in part_el:
        if not isinstance(m.tag, str) or _local(m.tag) != "measure":
            continue
        try:
            mx = max(mx, int(m.attrib.get("number", "0")))
        except ValueError:
            continue
    return mx


def _renumber_measure(m, n):
    m.attrib["number"] = str(n)


def _rescale_durations(m, div1, divi):
    """divisions 不一致时重算该小节所有 duration（含 backup/forward）。

    Pudu 解析器每 part 只读一次 <divisions>（musicxml_parser.cpp:187-204），
    后续页 divisions 不同会让 quarterLength 用错单位；把页 i 的 duration 从
    divi 单位换算到页 1 的 div1 单位。
    """
    for dur in m.iter("duration"):
        try:
            v = int(float(str(dur.text).strip()))
        except (TypeError, ValueError):
            continue
        dur.text = str(max(1, round(v * div1 / divi)))


def merge_pages(page_xmls: List[str], out_musicxml: str) -> int:
    """把逐页导出的完整 MusicXML 拼接为一个合法 score-partwise。

    * 以页 1 树为基底，保留 <score-partwise>/<identification>/<defaults>/
      <part-list>/<part id="P1">。
    * 后续页丢弃 identification/defaults/part-list，只取 P1 下的 <measure>。
    * 顺序重编号：measure.number 会流入 L2 HTML/JSON/review.json「小节 N」
      引用（jianpu_converter.cpp:132/620），两页都叫 number=1 会混淆，故页 2
      之后从页 1 最大号+1 续起。
    * 页 2 首小节 <attributes> 保留：parser 对 <time> 每个 attributes 块都读
      （musicxml_parser.cpp:210-224），无 time 继承页 1 拍号、有则更新。
    * divisions 一致性守卫（见 _rescale_durations）。

    Returns:
        int: 拼接后总小节数。
    """
    base = ET.parse(page_xmls[0])
    root = base.getroot()
    _strip_ns(root)
    base_part = next((p for p in root.findall("part")), None)
    if base_part is None:
        return 0
    divs = _first_divisions(root)
    pid = base_part.attrib.get("id")
    next_number = _max_measure_number(base_part) + 1
    total = _max_measure_number(base_part)

    for page_path in page_xmls[1:]:
        ptree = ET.parse(page_path)
        proot = ptree.getroot()
        _strip_ns(proot)
        pdivs = _first_divisions(proot)
        for p in proot.findall("part"):
            if p.attrib.get("id") != pid:
                continue
            for child in list(p):
                if not isinstance(child.tag, str) or _local(child.tag) != "measure":
                    continue  # 跳过注释 / 非 measure 元素
                _renumber_measure(child, next_number)
                if divs is not None and pdivs is not None and pdivs != divs:
                    _rescale_durations(child, divs, pdivs)
                base_part.append(child)
                next_number += 1
                total += 1

    try:
        ET.indent(root, space="  ")   # 交付物可读性（Python 3.9+）
    except AttributeError:
        pass
    base.write(out_musicxml, encoding="UTF-8", xml_declaration=True)
    return total


# ----------------------- 子进程执行 -----------------------

def _run_audiveris(cmd: List[str], timeout: int = _TIMEOUT_S) -> Tuple[int, str]:
    """运行 Audiveris CLI，返回 (rc, 合并 stdout+stderr 文本)。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, f"[错误] Audiveris 超时（>{timeout}s）"
    except FileNotFoundError as e:
        return -1, f"[错误] 无法启动 Audiveris: {e}"
    out = ((proc.stdout or b"").decode("utf-8", errors="replace")
           + (proc.stderr or b"").decode("utf-8", errors="replace"))
    return proc.returncode, out


# ----------------------- 主流程 -----------------------

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("用法: python omr_audiveris.py <input> <output.musicxml>\n")
        return 2
    in_path, out_path = argv[0], argv[1]
    if not os.path.exists(in_path):
        sys.stderr.write(f"[错误] 输入不存在: {in_path}\n")
        return 1
    exe = resolve_audiveris_exe()
    if not exe:
        sys.stderr.write(
            "[错误] Audiveris 未安装。请设置环境变量 PUDU_AUDIVERIS_EXE 指向 "
            "Audiveris.exe（或放入 PATH）；默认期望 build/_audiveris/extract/"
            "Audiveris/Audiveris.exe\n")
        return 1

    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    in_abs = os.path.abspath(in_path)
    base = os.path.splitext(os.path.basename(in_abs))[0]
    is_pdf = os.path.splitext(in_abs)[1].lower() == _PDF_EXT

    # 每个 AV 运行用独立临时输出目录（AV 产物按输入 base 命名，同目录会覆盖）
    with tempfile.TemporaryDirectory(prefix="pudu_av_") as tmp:
        if not is_pdf:
            rc, out = _run_audiveris(build_av_cmd(exe, in_abs, tmp))
            # 低分辨率边界：首跑失败且命中分辨率特征 → 自动放大重试
            if rc != 0 and _is_resolution_failure(out):
                retried = 0
                for scale in (2, 3):
                    up_path = os.path.join(tmp, f"upscaled_{scale}x.png")
                    if not upscale_image(in_abs, up_path, scale):
                        break
                    rc2, out2 = _run_audiveris(build_av_cmd(exe, up_path, tmp))
                    retried += 1
                    if rc2 == 0:
                        rc, out = 0, out2
                        sys.stdout.write(
                            f"[audiveris] 低分辨率检测，{scale}x 放大重试成功\n")
                        break
                else:
                    # 2x/3x 均失败：用最后一次失败信息（out 已为 out2）
                    pass
                if rc != 0 and retried:
                    sys.stderr.write(
                        f"[错误] Audiveris 单页导出失败（rc={rc}，已尝试"
                        f"{retried} 次放大重试）:\n{out[-2000:]}\n")
                    return 1
            if rc != 0:
                sys.stderr.write(
                    f"[错误] Audiveris 单页导出失败（rc={rc}）:\n{out[-2000:]}\n")
                return 1
            mxl = locate_export(tmp, base)
            if not mxl:
                sys.stderr.write(
                    f"[错误] Audiveris 未产出 .mxl（out 目录: {os.listdir(tmp)}）\n")
                return 1
            if not extract_mxl(mxl, out_abs):
                sys.stderr.write(f"[错误] 无法解包 .mxl: {mxl}\n")
                return 1
        else:
            n_pages = count_pdf_pages(in_abs)
            if n_pages <= 0:
                sys.stderr.write(f"[错误] 无法解析 PDF 页数: {in_path}\n")
                return 1
            page_xmls: List[str] = []
            ok = 0
            for sheet in range(1, n_pages + 1):
                sheet_tmp = os.path.join(tmp, f"p{sheet}")
                os.makedirs(sheet_tmp, exist_ok=True)
                rc, out = _run_audiveris(
                    build_av_cmd(exe, in_abs, sheet_tmp, sheet=sheet))
                mxl = locate_export(sheet_tmp, base)
                if rc != 0 or not mxl:
                    sys.stderr.write(
                        f"[警告] 第 {sheet} 页导出失败（rc={rc}），跳过\n")
                    if out:
                        sys.stderr.write(out[-800:] + "\n")
                    continue
                xml_path = os.path.join(sheet_tmp, f"p{sheet}.xml")
                if extract_mxl(mxl, xml_path):
                    page_xmls.append(xml_path)
                    ok += 1
            if not page_xmls:
                sys.stderr.write("[错误] PDF 无任何页导出成功\n")
                return 1
            sys.stdout.write(f"[audiveris] PDF {n_pages} 页，成功 {ok} 页\n")
            if ok < n_pages:
                sys.stderr.write(
                    f"[警告] {n_pages - ok} 页导出失败被跳过（可识别页已拼接）\n")
            merge_pages(page_xmls, out_abs)

    if not os.path.exists(out_abs) or os.path.getsize(out_abs) == 0:
        sys.stderr.write(f"[错误] 未产出有效 MusicXML: {out_abs}\n")
        return 1

    # 拍号校验打标（无 sidecar 依赖；幂等，pudu_server 层再跑为 no-op）
    if mark_meter_constraint_failures is not None:
        try:
            n_mark = mark_meter_constraint_failures(out_abs, "")
            if n_mark:
                sys.stdout.write(f"[audiveris] 节拍校验标记 {n_mark} 小节\n")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[警告] 拍号打标异常（不阻断）: {e}\n")

    sys.stdout.write(f"[ok] audiveris 产出 MusicXML: {out_abs}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
