"""
algoforge 桌面窗口入口 — PyWebView 创建原生 WebView2 窗口
启动 FastAPI 后端，弹出桌面窗口，关闭窗口时自动停止服务。
"""
import os
import socket
import sys
import threading
import time

import uvicorn
import webview

PORT = 1783
HOST = "127.0.0.1"


def _wait_for_port(host: str, port: int, timeout: int = 30) -> bool:
    """等待端口就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def _start_server():
    """在后台线程启动 FastAPI"""
    from dashboard.backend.main import app
    uvicorn.run(app, host=HOST, port=PORT, reload=False, log_level="warning")


def main():
    # 确保项目根目录在 sys.path
    root = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(root))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 后台启动 FastAPI
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # 等待服务就绪
    if not _wait_for_port(HOST, PORT, timeout=30):
        print("[ERROR] FastAPI 启动超时，请检查日志")
        return

    # 创建原生窗口 — WebView2 (Windows 10/11 自带)
    webview.create_window(
        title="AlgoForge — XAUUSD 黄金量化交易系统",
        url=f"http://{HOST}:{PORT}",
        width=1400,
        height=900,
        resizable=True,
        min_size=(1024, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
