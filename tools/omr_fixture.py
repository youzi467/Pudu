#!/usr/bin/env python3
# ----------------------------------------------------------------------
# 谱渡 Pudu · 阶段1 OMR 黑盒集成 · subprocess fixture 运行器
#
# 适配器以子进程方式调用本脚本（与真引擎同一条子进程契约）：
#   python omr_fixture.py <input> <output.musicxml>
#
# 它把一个预置的合法 MusicXML（omr_fixture_sample.musicxml）复制到输出，
# 模拟"OMR 引擎产出的 MusicXML"。用于：
#   - 手动验证子进程调用路径（与真 oemer 走完全相同的 CreateProcess 机制）；
#   - 在无法安装重引擎的环境演示端到端流程。
#
# 确定性、无需网络/权重/GPU。CI 与 ctest 的确定性由 C++ 原生 fixture 保证
# （见 omr_adapter.cpp 的 kOmrFixtureMusicXml）；本脚本供需要走 subprocess 路径时选用。
# ----------------------------------------------------------------------
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "omr_fixture_sample.musicxml")


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("用法: python omr_fixture.py <input> <output.musicxml>\n")
        return 2

    in_path, out_path = sys.argv[1], sys.argv[2]
    if not os.path.exists(SAMPLE):
        sys.stderr.write(f"[错误] fixture 样例缺失: {SAMPLE}\n")
        return 1

    try:
        shutil.copyfile(SAMPLE, out_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] 复制 fixture 失败: {e}\n")
        return 1

    sys.stdout.write(f"[ok] fixture 产出 MusicXML: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
