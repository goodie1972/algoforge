# -*- coding: utf-8 -*-
"""
看门狗常驻启动器（watchdog for the watchdogs）
==============================================
常驻运行，拉起并守护两个监控守护进程：
  - tools/status_monitor.py  （引擎状态监控 + 自动重启 + 报警推送）
  - monitor/patrol_daemon.py （引擎巡检 + Windows 弹窗报警）
任一子进程退出即立即重启（带单实例锁，防 Task Scheduler 与手动双跑）。

部署：用 tools/install_watchdog_task.bat 注册为 Windows 任务计划程序「开机自启」，
本启动器自身崩溃也由任务计划程序的「失败重启」兜底。

用法：
  python tools/watchdog_launcher.py
"""
import os
import sys
import time
import json
import signal
import subprocess
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("watchdog_launcher")

BASE_DIR = Path(__file__).resolve().parent.parent
# 与实盘引擎同一 Python 解释器（C:\Python314\python.exe），保证环境一致
ENGINE_PYTHON = os.environ.get("ENGINE_PYTHON") or r"C:\Python314\python.exe"
LOCK_FILE = BASE_DIR / "tools" / ".watchdog_launcher.lock"

CHILDREN = [
    {
        "name": "status_monitor",
        "script": BASE_DIR / "tools" / "status_monitor.py",
        "log": BASE_DIR / "logs" / "watchdog_status_monitor.out",
    },
    {
        "name": "patrol_daemon",
        "script": BASE_DIR / "monitor" / "patrol_daemon.py",
        "log": BASE_DIR / "monitor" / "watchdog_patrol.out",
    },
]


def _acquire_lock() -> bool:
    """单实例锁：写 PID，已存在且进程存活则放弃。"""
    try:
        if LOCK_FILE.exists():
            try:
                old_pid = int(LOCK_FILE.read_text().strip())
            except ValueError:
                old_pid = None
            if old_pid:
                try:
                    os.kill(old_pid, 0)  # signal 0 = 仅检测存活
                    logger.warning(f"已有实例在运行 (PID={old_pid})，退出避免双跑")
                    return False
                except OSError:
                    pass  # 旧 PID 已死，覆盖
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning(f"取锁失败(继续): {e}")
        return True


def _release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def main():
    if not _acquire_lock():
        sys.exit(0)

    logger.info("=" * 60)
    logger.info("XAUUSD 看门狗常驻启动器 启动")
    logger.info(f"引擎 Python: {ENGINE_PYTHON}")
    logger.info(f"守护子进程: {[c['name'] for c in CHILDREN]}")
    logger.info("=" * 60)

    if not os.path.exists(ENGINE_PYTHON):
        logger.error(f"引擎 Python 不存在: {ENGINE_PYTHON}，请用环境变量 ENGINE_PYTHON 指定")
        _release_lock()
        sys.exit(1)

    procs: dict[str, subprocess.Popen] = {}

    def start_child(c: dict) -> subprocess.Popen:
        logf = open(c["log"], "a", encoding="utf-8")
        p = subprocess.Popen(
            [ENGINE_PYTHON, str(c["script"])],
            cwd=str(BASE_DIR),
            stdout=logf,
            stderr=logf,
        )
        logger.info(f"[启动] {c['name']} PID={p.pid}")
        return p

    for c in CHILDREN:
        try:
            procs[c["name"]] = start_child(c)
        except Exception as e:
            logger.error(f"[启动失败] {c['name']}: {e}")

    _stop = {"flag": False}

    def _on_signal(signum, frame):
        logger.info(f"收到信号 {signum}，准备退出")
        _stop["flag"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not _stop["flag"]:
            for c in CHILDREN:
                p = procs.get(c["name"])
                if p is None or p.poll() is not None:
                    code = p.returncode if p else "未启动"
                    logger.warning(f"[守护] {c['name']} 已退出(code={code})，3s 后重启")
                    time.sleep(3)
                    try:
                        procs[c["name"]] = start_child(c)
                    except Exception as e:
                        logger.error(f"[重启失败] {c['name']}: {e}")
            time.sleep(5)
    finally:
        logger.info("正在终止子进程...")
        for name, p in procs.items():
            if p and p.poll() is None:
                logger.info(f"[终止] {name} PID={p.pid}")
                p.terminate()
        # 给子进程一点时间优雅退出
        time.sleep(2)
        for name, p in procs.items():
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        _release_lock()
        logger.info("看门狗启动器已退出")


if __name__ == "__main__":
    main()
