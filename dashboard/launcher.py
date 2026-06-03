"""
XAUUSD Dashboard Launcher

启动/停止后端 API + 前端开发服务器，退出时自动清理子进程。
编译为 exe: pyinstaller --onefile --console launcher.py
"""

import atexit
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

_child_procs: list[subprocess.Popen] = []


def _cleanup():
    for proc in _child_procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in _child_procs:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    _child_procs.clear()


def wait_for_port(port: int, timeout: int = 30) -> bool:
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def start_backend() -> subprocess.Popen | None:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJECT_ROOT};{env.get('PYTHONPATH', '')}"
    proc = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "backend" / "main.py")],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    _child_procs.append(proc)
    return proc


def start_frontend() -> subprocess.Popen | None:
    frontend_dir = BASE_DIR / "frontend"
    proc = subprocess.Popen(
        ["npx.cmd", "vite", "--port", "5173"],
        cwd=frontend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    _child_procs.append(proc)
    return proc


def _print_output(proc: subprocess.Popen, prefix: str):
    import threading
    def _reader():
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"  [{prefix}] {text}")
        proc.stdout.close()
    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def main():
    print("=" * 55)
    print("  XAUUSD Trading Dashboard Launcher")
    print("=" * 55)
    print()

    atexit.register(_cleanup)
    if sys.platform == "win32":
        signal.signal(signal.SIGTERM, lambda *_: _cleanup())

    print("  [1/3] 启动后端 API 服务...")
    backend = start_backend()
    if backend is None:
        print("  [FAIL] 后端启动失败")
        sys.exit(1)
    _print_output(backend, "backend")
    if wait_for_port(8000):
        print("  [OK] 后端 API: http://localhost:8000/api")
    else:
        print("  [FAIL] 后端启动超时")
        _cleanup()
        sys.exit(1)
    print()

    print("  [2/3] 启动前端开发服务器...")
    frontend = start_frontend()
    if frontend is None:
        print("  [FAIL] 前端启动失败")
        _cleanup()
        sys.exit(1)
    _print_output(frontend, "frontend")
    if wait_for_port(5173):
        print("  [OK] 前端: http://localhost:5173")
    else:
        print("  [FAIL] 前端启动超时")
        _cleanup()
        sys.exit(1)
    print()

    print("  [3/3] 打开浏览器...")
    webbrowser.open("http://localhost:5173")
    print()

    print("=" * 55)
    print("  全部就绪！关闭此窗口将自动停止服务。")
    print("=" * 55)

    try:
        while all(p.poll() is None for p in _child_procs):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  收到退出信号，正在停止服务...")
    finally:
        _cleanup()

    print("  服务已全部停止。")


if __name__ == "__main__":
    main()
