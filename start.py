"""
XAUUSD 一键启动脚本
===================
功能：
1. 检测端口 1783 占用，自动杀死旧进程
2. 启动后端 API（uvicorn + FastAPI）
3. 等待 API 就绪
4. 等待引擎线程完成 MT4 连接
5. 打印最终状态和 URL
6. Ctrl+C 退出时自动清理子进程
"""
import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "dashboard" / "backend"
PORT = 1783

_proc: subprocess.Popen | None = None


def _cleanup():
    global _proc
    if _proc and _proc.poll() is None:
        print("\n  正在停止服务...")
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def kill_port(port: int):
    """强制释放端口（Windows / Linux）"""
    import socket
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                f'netstat -ano | findstr :{port}',
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and "LISTENING" in line:
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
                    print(f"  已终止旧进程 PID={pid}")
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            for pid in result.stdout.strip().splitlines():
                if pid:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"  已终止旧进程 PID={pid}")
    except Exception:
        pass  # 杀不掉就算了，后续端口占用会有报错


def wait_for_port(port: int, timeout: int = 60) -> bool:
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def wait_for_api(timeout: int = 120) -> bool:
    """等待引擎线程进入 running 状态"""
    import urllib.request
    import json
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/engine/status", timeout=3)
            data = json.loads(resp.read().decode())
            if data.get("status") == "running":
                return True
            # 还在初始化，继续等
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    global _proc

    print("=" * 55)
    print("  XAUUSD 量化交易系统 — 一键启动")
    print("=" * 55)
    print()

    # 1. 清理旧进程
    print("  [1/4] 检查端口占用...")
    kill_port(PORT)
    time.sleep(1)
    print()

    # 2. 启动后端
    print("  [2/4] 启动后端 API 服务...")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BASE_DIR};{env.get('PYTHONPATH', '')}"
    _proc = subprocess.Popen(
        [sys.executable, str(BACKEND_DIR / "main.py")],
        cwd=BASE_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    atexit.register(_cleanup)

    # 3. 等待端口就绪
    print("  [3/4] 等待 API 就绪...")
    if not wait_for_port(PORT):
        print("  [失败] API 启动超时")
        _cleanup()
        sys.exit(1)
    print(f"  [OK] API: http://localhost:{PORT}/api")
    print()

    # 4. 等待引擎线程完成 MT4 连接
    print("  [4/4] 等待引擎连接 MT4...")
    if not wait_for_api():
        print("  [警告] 引擎未能在 120 秒内进入运行状态")
        print("  请检查 MT4 是否已启动，桥接是否正常运行")
    else:
        print("  [OK] 引擎已运行，MT4 已连接")
    print()

    # 5. 打印最终信息
    print("=" * 55)
    print("  XAUUSD 量化交易系统")
    print(f"  API:      http://localhost:{PORT}/api")
    print(f"  Dashboard: http://localhost:{PORT}")
    print(f"  WebSocket: ws://localhost:{PORT}/ws")
    print("=" * 55)
    print("  按 Ctrl+C 停止所有服务")
    print()

    try:
        while _proc and _proc.poll() is None:
            # 实时打印后端日志到控制台
            if _proc.stdout:
                line = _proc.stdout.readline()
                if line:
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        try:
                            print(f"  [{time.strftime('%H:%M:%S')}] {text}")
                        except UnicodeEncodeError:
                            safe = text.encode("utf-8", errors="replace").decode("gbk", errors="replace")
                            print(f"  [{time.strftime('%H:%M:%S')}] {safe}")
            else:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n  收到退出信号...")
    finally:
        _cleanup()

    print("  服务已全部停止。")


if __name__ == "__main__":
    main()
