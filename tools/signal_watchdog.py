"""
监控守护脚本 — 确保信号记录器存活 + 引擎健康检查
每5分钟检查一次
"""
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RECORDER_SCRIPT = BASE_DIR / "tools" / "signal_analysis_recorder.py"
RECORDER_PID_FILE = BASE_DIR / "logs" / "recorder.pid"

API_BASE = "http://127.0.0.1:1783"

def check_engine():
    try:
        resp = urllib.request.urlopen(f"{API_BASE}/api/engine/status", timeout=5)
        data = json.loads(resp.read().decode())
        if data.get("status") == "running" and data.get("bridge_connected"):
            return True, data
        return False, data
    except Exception as e:
        return False, str(e)

def is_recorder_alive():
    if not RECORDER_PID_FILE.exists():
        return False
    try:
        pid = int(RECORDER_PID_FILE.read_text().strip())
        # Check if process exists (windows)
        import os
        try:
            os.kill(pid, 0)  # signal 0 = check existence only
            return True
        except OSError:
            return False
    except:
        return False

def start_recorder():
    log_file = open(BASE_DIR / "logs" / "recorder_out.log", "a")
    proc = subprocess.Popen(
        [sys.executable, str(RECORDER_SCRIPT)],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=log_file,
    )
    RECORDER_PID_FILE.write_text(str(proc.pid))
    print(f"[守护] 记录器已启动 PID={proc.pid}")
    return proc

print("=" * 50)
print(f"监控守护启动 {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 50)

# 首次启动记录器
if not is_recorder_alive():
    start_recorder()
else:
    pid = int(RECORDER_PID_FILE.read_text().strip())
    print(f"[守护] 记录器已在运行 PID={pid}")

while True:
    engine_ok, engine_data = check_engine()
    recorder_ok = is_recorder_alive()

    now = time.strftime("%H:%M:%S")

    if not engine_ok:
        print(f"[{now}] ⚠ 引擎异常: {engine_data}")

    if not recorder_ok:
        print(f"[{now}] ⚠ 记录器已停止，准备重启...")
        start_recorder()
    else:
        pass  # 一切正常，静默

    time.sleep(300)  # 每5分钟检查一次
