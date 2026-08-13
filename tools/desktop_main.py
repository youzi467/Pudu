# -*- coding: utf-8 -*-
"""
谱渡 Pudu · 桌面端外壳（pywebview / WebView2）
=================================================

P1（2026-08-13）：给本地网页应用（``pudu_server.py``）套原生窗口壳，**保留全部前端**。

  * 进程内起 HTTP（127.0.0.1:0 动态端口），实际端口写 ``%APPDATA%/Pudu/port.txt``（P0 契约）。
  * pywebview 窗口加载 ``http://127.0.0.1:<port>/``，引擎强制 edgechromium（WebView2，Win11 自带）。
  * ``js_api``（前端经 ``window.pywebview.api`` 调用）暴露原生对话框：
      - ``open_files()``  原生打开对话框，返回选中文件路径（供前端 POST /api/open 直投）
      - ``save_result()`` 原生保存对话框，把作业结果复制到用户选择路径
  * 关窗即优雅退出：``httpd.shutdown()`` + ``mgr.shutdown()``（取消进行中作业/终止引擎子进程）。

模块分段：
  PuduApp（进程内服务引导/优雅退出）→ PuduApi（js_api 桥）→ main

用法：
    venv_python tools/desktop_main.py            # 弹原生窗口
    venv_python tools/desktop_main.py --check    # 无头验收：起服务+端口落盘+GET / 后退出

环境变量：
    PUDU_TEST_CLOSE_MS  启动后 N 毫秒自动关窗（自动化验收用）。
"""

import os
import sys
import threading
import time

# 让 ``import pudu_server`` 找到同目录脚本（开发态；打包态由 PyInstaller 打进 bundle）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pudu_server as ps  # noqa: E402


class PuduApp:
    """进程内 HTTP 服务 + 优雅退出。"""

    def __init__(self):
        self.mgr = ps.JobManager(ps.JOBS_ROOT)
        self.httpd = None
        self._server_thread = None

    def boot(self) -> int:
        """绑定 127.0.0.1:0 并后台 serve，返回实际端口。"""
        self.httpd = ps.serve("127.0.0.1", 0, self.mgr)
        port = int(self.httpd.server_address[1])
        ps._write_port_file(port)               # P0 契约：port.txt 落盘
        self._server_thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True)
        self._server_thread.start()
        return port

    def shutdown(self) -> None:
        """停止 HTTP + 取消作业/终止引擎子进程。幂等。"""
        if self.httpd is None:
            return
        try:
            self.httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
        self.mgr.shutdown(join_timeout=8.0)


class PuduApi:
    """js_api 桥：原生打开/保存对话框。方法名即 ``window.pywebview.api.<name>``。"""

    def __init__(self, app: PuduApp):
        self._app = app

    def open_files(self):
        """原生打开对话框，返回选中路径列表（未选则 []）。"""
        import webview
        w = webview.windows[0]
        paths = w.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("图片 / PDF（*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.pdf）",))
        return list(paths) if paths else []

    def save_result(self, job_id: str, name: str):
        """把作业结果文件（jianpu.html / final.musicxml / review.json）保存到用户选择路径。

        Returns:
            {"ok": True, "path": ...} 或 {"ok": False, "reason": ...}
        """
        import shutil
        import webview
        if name not in ps._RESULT_FILES:
            return {"ok": False, "reason": f"未知结果文件: {name}"}
        src = os.path.join(self._app.mgr.root, job_id, name)
        if not os.path.isfile(src):
            return {"ok": False, "reason": "作业结果不存在（可能已清理）"}
        ext = os.path.splitext(name)[1]
        ftype = {"html": "简谱 HTML（*.html）", "musicxml": "MusicXML（*.musicxml）",
                 "json": "JSON（*.json）"}.get(ext.lstrip("."), "所有文件（*.*）")
        w = webview.windows[0]
        target = w.create_file_dialog(webview.SAVE_DIALOG, save_filename=name,
                                      file_types=(ftype,))
        if not target:
            return {"ok": False, "reason": "已取消"}
        try:
            shutil.copyfile(src, target)
        except OSError as e:
            return {"ok": False, "reason": f"保存失败: {e}"}
        return {"ok": True, "path": target}


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    p = argparse.ArgumentParser(prog="pudu_desktop",
                                description="谱渡 Pudu · 桌面端外壳（pywebview）")
    p.add_argument("--check", action="store_true",
                   help="无头验收：起服务 + 端口落盘 + GET / 200 后退出，不弹窗")
    args = p.parse_args(argv)

    # 单实例互斥（与独立服务器同一互斥名，保证桌面端/浏览器端二选一）
    if not ps._acquire_single_instance():
        print("[提示] 谱渡 Pudu 已在运行；本次启动自动退出。")
        return 0

    app = PuduApp()
    try:
        port = app.boot()
    except OSError as e:
        sys.stderr.write(f"[错误] 无法监听回环端口: {e}\n")
        return 1
    url = f"http://127.0.0.1:{port}/"
    print(f"谱渡 Pudu 桌面端已启动: {url}", flush=True)
    print(f"端口文件: {ps._port_file_path()}", flush=True)

    # ---- 无头验收（CI / 自动化）----
    if args.check:
        import urllib.request
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[错误] GET / 失败: {e}\n")
            app.shutdown()
            return 2
        ok = resp.status == 200 and len(body) > 0
        print(f"GET / -> HTTP {resp.status}, {len(body)} bytes", flush=True)
        app.shutdown()
        return 0 if ok else 2

    # ---- 原生窗口 ----
    import webview
    api = PuduApi(app)
    try:
        w = webview.create_window("谱渡 Pudu · 五线谱 ⇄ 简谱", url, js_api=api,
                                  width=1100, height=760, background_color="#f5f8f5")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] 无法创建原生窗口（是否安装 WebView2 运行时？）: {e}\n")
        sys.stderr.write(f"已退回浏览器访问 {url}\n")
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        app.shutdown()
        return 1

    test_close_ms = os.environ.get("PUDU_TEST_CLOSE_MS")
    if test_close_ms:
        def _auto_close():
            time.sleep(float(test_close_ms) / 1000.0)
            try:
                webview.windows[0].destroy()
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=_auto_close, daemon=True).start()

    webview.start(gui="edgechromium", debug=False)
    # 窗口全部关闭 → 优雅退出
    app.shutdown()
    print("谱渡 Pudu 已退出。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
