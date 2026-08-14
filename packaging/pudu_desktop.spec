# -*- mode: python ; coding: utf-8 -*-
"""谱渡 Pudu 桌面端 PyInstaller spec（onedir，pywebview 壳）。

随包内容（全进 _internal/）：
  * 冻结模块：desktop_main.py（入口）+ pudu_server.py + geometric_pitch.py
  * 数据：pudu_ui.html、引擎脚本 omr_audiveris.py / omr_oemer.py
  * 核心：Pudu.exe（Release）+ pugixml.dll
  * 运行时：embeddable python（runtime/python.exe，跑 stdlib 引擎脚本）
  * 引擎：Audiveris 解包目录（audiveris/Audiveris/，随包再分发，附 AGPL LICENSE + 源码链接）
  * 许可：本应用 MIT（LICENSE）
"""
import os

# SPECPATH 由 PyInstaller 注入 = spec 所在目录（packaging/）→ 仓库根
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

from PyInstaller.building.datastruct import Tree  # noqa: E402

# 引擎脚本必须是普通 .py 数据文件（由 runtime/python.exe 以子进程脚本方式运行）
engine_scripts = [
    (os.path.join(ROOT, "tools", "omr_audiveris.py"), "."),
    (os.path.join(ROOT, "tools", "omr_oemer.py"), "."),
]

# 单文件数据
single_files = [
    (os.path.join(ROOT, "tools", "pudu_ui.html"), "."),
    (os.path.join(ROOT, "favicon.ico"), "."),
    (os.path.join(ROOT, "build", "windows-msvc-vcpkg", "Release", "Pudu.exe"), "."),
    (os.path.join(ROOT, "build", "windows-msvc-vcpkg", "Release", "pugixml.dll"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "packaging", "AV_LICENSE.txt"), "audiveris"),
    (os.path.join(ROOT, "packaging", "AV_NOTICE.txt"), "audiveris"),
]

# 整目录（Tree 保留目录结构，prefix 决定 _internal 下相对位置）
runtime_tree = Tree(os.path.join(ROOT, "build", "_pkg", "runtime"), prefix="runtime")
av_tree = Tree(os.path.join(ROOT, "build", "_audiveris", "extract", "Audiveris"),
               prefix=os.path.join("audiveris", "Audiveris"))

a = Analysis(
    [os.path.join(ROOT, "tools", "desktop_main.py")],
    pathex=[os.path.join(ROOT, "tools")],
    binaries=[],
    datas=engine_scripts + single_files,
    hiddenimports=[
        "pudu_server",          # desktop_main 顶部 import
        "geometric_pitch",      # pudu_server 内部 import（stdlib-only）
        "webview",              # desktop_main 函数内懒加载，需显式打入
        "clr_loader",           # pywebview edgechromium 依赖（pythonnet 桥）
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "oemer"],   # oemer 不随包；numpy 仅 oemer 需要，剔除减体积
    noarchive=False,
)

# 把两个 Tree 追加进 datas（Analysis 只接受 datas 元组；Tree 需单独并入 COLLECT）
a.datas += runtime_tree
a.datas += av_tree

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pudu_desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,         # 发布形态：无控制台窗口（日志重定向 desktop.log）
    icon=[os.path.join(ROOT, "favicon.ico")],   # EXE 图标（资源管理器/任务栏）
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pudu_desktop",
)
