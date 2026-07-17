#!/usr/bin/env python3
# ----------------------------------------------------------------------
# 谱渡 Pudu · 阶段1 OMR 黑盒集成 · 真引擎运行器 (oemer)
#
# 适配器以子进程方式调用本脚本：
#   python omr_oemer.py <input_image_or_pdf> <output_musicxml>
#
# 职责：用 oemer（基于深度学习的 OMR）把乐谱图片/PDF 识别为 MusicXML。
# 这是"黑盒"边界——Pudu 只消费产出的 MusicXML，不关心 oemer 内部。
#
# 依赖：oemer 0.1.x（pip install oemer，含 onnxruntime / opencv / scipy /
#       sklearn / augly）+ oemer 预训练权重（首次运行由 oemer.ete.main()
#       自动下载，需网络可达 GitHub Releases 模型托管源）。
#
# 重要（API 形态）：oemer 0.1.x 是【函数式】API，没有 OMR 类。
#   入口是 oemer.ete.main()，它会：
#     (1) 若 checkpoints 缺失则自动下载权重（首次运行）；
#     (2) 调用 extract() 做识别并写出 MusicXML；
#     (3) 额外写一张 teaser png。
#   输出文件名取自输入图 basename；-o 指向目录时写 <dir>/<basename>.musicxml。
#   本脚本通过构造 oemer.ete.main() 期望的 argv 再调用它，最后把产出
#   重命名为适配器要求的 out_path。
# ----------------------------------------------------------------------
import sys
import os
import traceback


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("用法: python omr_oemer.py <input> <output.musicxml>\n")
        return 2

    in_path, out_path = sys.argv[1], sys.argv[2]
    if not os.path.exists(in_path):
        sys.stderr.write(f"[错误] 输入不存在: {in_path}\n")
        return 1

    try:
        import oemer.ete
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] 无法导入 oemer（是否已 pip install oemer？）: {e}\n")
        return 1

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    basename = os.path.splitext(os.path.basename(in_path))[0]
    produced = os.path.join(out_dir, basename + ".musicxml")

    try:
        # 构造 oemer.ete.main() 期望的 argv，再调用它（会触发权重下载+识别）
        sys.argv = ["oemer", in_path, "-o", out_dir]
        oemer.ete.main()
    except SystemExit as se:
        # main() 正常结束不会 sys.exit；若发生非 0 退出视为失败
        if se.code not in (0, None):
            sys.stderr.write(f"[错误] oemer.ete.main() 退出码: {se.code}\n")
            return 1
    except Exception as e:  # noqa: BLE001
        # 透传完整 traceback 到 stderr，便于上游（Pudu omr_adapter）暴露崩溃行号
        traceback.print_exc()
        sys.stderr.write(f"[错误] oemer 识别失败: {e}\n")
        return 1

    if not os.path.exists(produced) or os.path.getsize(produced) == 0:
        sys.stderr.write(f"[错误] oemer 未产出有效 MusicXML: {produced}\n")
        return 1

    if os.path.abspath(produced) != os.path.abspath(out_path):
        os.replace(produced, out_path)

    sys.stdout.write(f"[ok] oemer 产出 MusicXML: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
