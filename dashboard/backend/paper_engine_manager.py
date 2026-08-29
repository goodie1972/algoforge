"""
纸面引擎进程管理器 — 以子进程方式启动/停止/健康检查

职责:
  - 启动纸面引擎子进程 (python -m engine_standalone.paper_main)
  - 健康检查（定期检测进程是否存活，挂掉后自动重启）
  - 停止进程（Windows 下使用 taskkill /F /PID）
  - 对外暴露统一状态字典供 API 查询
"""

import logging
import os
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger("dashboard.paper_engine")

# 项目根目录（用于设置子进程 cwd）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# 最大自动重启次数（防止无限重启循环）
_MAX_RESTART_ATTEMPTS = 3


class PaperEngineManager:
    """管理纸面引擎子进程的生命周期"""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._pid: int | None = None
        self._started_at: datetime | None = None
        self._running: bool = False
        self._restart_count: int = 0

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """启动纸面引擎子进程，返回是否成功"""
        if self._running and self.is_alive():
            logger.warning("[PaperEngine] 进程已在运行 (PID=%s)，跳过启动", self._pid)
            return False

        # 日志由子进程内部的 RotatingFileHandler 管理，stdout/stderr 丢弃即可
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "engine_standalone.paper_main"],
                cwd=_PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self._pid = self._process.pid
            self._started_at = datetime.now()
            self._running = True
            self._restart_count = 0
            logger.info(
                "[PaperEngine] 子进程已启动 PID=%s",
                self._pid,
            )
            return True
        except Exception as e:
            logger.error("[PaperEngine] 启动失败: %s", e)
            self._running = False
            return False

    # ------------------------------------------------------------------
    # 停止
    # ------------------------------------------------------------------
    def stop(self) -> None:
        """停止纸面引擎子进程"""
        if self._process is None and self._pid is None:
            return

        pid = self._pid
        logger.info("[PaperEngine] 正在停止子进程 PID=%s ...", pid)

        try:
            if self._process is not None and self._process.poll() is None:
                # Windows: 必须使用 taskkill /F /PID 才能可靠终止子进程树
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                        timeout=10,
                    )
                else:
                    self._process.terminate()
                # 等待进程退出（最多 10 秒）
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("[PaperEngine] PID=%s 超时未退出，强制终止", pid)
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            capture_output=True,
                            timeout=5,
                        )
                    else:
                        self._process.kill()
                        self._process.wait(timeout=5)
        except Exception as e:
            logger.warning("[PaperEngine] 停止进程异常: %s", e)
        finally:
            self._running = False
            self._process = None
            self._pid = None
            self._started_at = None
            logger.info("[PaperEngine] 子进程已停止 (原 PID=%s)", pid)

    # ------------------------------------------------------------------
    # 存活检测
    # ------------------------------------------------------------------
    def is_alive(self) -> bool:
        """检查纸面引擎进程是否存活"""
        if self._process is None:
            return False
        return self._process.poll() is None

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        """返回纸面引擎状态字典（供 API 使用）"""
        if not self._running and self._process is None:
            return {"status": "not_configured"}

        alive = self.is_alive()
        uptime = 0.0
        started_at_iso = None
        if alive and self._started_at is not None:
            uptime = (datetime.now() - self._started_at).total_seconds()
            started_at_iso = self._started_at.isoformat()

        # 区分“从未启动”与“曾经启动但已退出”
        if alive:
            status = "running"
        elif self._pid is not None:
            status = "crashed"
        else:
            status = "stopped"

        return {
            "status": status,
            "pid": self._pid,
            "uptime_seconds": round(uptime, 1),
            "started_at": started_at_iso,
        }

    # ------------------------------------------------------------------
    # 健康检查（供后台轮询任务调用）
    # ------------------------------------------------------------------
    def ensure_running(self) -> None:
        """健康检查：如果进程意外退出，尝试自动重启（最多 _MAX_RESTART_ATTEMPTS 次）"""
        if not self._running:
            return  # 未配置/未启用，不做任何事

        if self._process is None:
            return

        # poll() 返回 None 说明进程仍在运行
        if self._process.poll() is None:
            return

        # 进程已退出
        exit_code = self._process.returncode
        logger.warning(
            "[PaperEngine] 子进程 PID=%s 意外退出 (exit_code=%s)",
            self._pid,
            exit_code,
        )

        if self._restart_count >= _MAX_RESTART_ATTEMPTS:
            logger.error(
                "[PaperEngine] 已达最大重启次数 (%d)，不再自动重启，请检查日志",
                _MAX_RESTART_ATTEMPTS,
            )
            self._running = False
            return

        self._restart_count += 1
        logger.info(
            "[PaperEngine] 尝试自动重启 (%d/%d) ...",
            self._restart_count,
            _MAX_RESTART_ATTEMPTS,
        )
        # 清理旧进程对象
        self._process = None
        self._pid = None
        self._started_at = None
        self.start()
