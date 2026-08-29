"""
纸面引擎独立进程入口 — 模拟交易（无需 MT4 连接）

用法:
  python -m engine_standalone.paper_main

与实盘引擎 (main.py) 的区别:
  - engine_mode="paper"：只加载 mode='paper' 的策略
  - create_bridge_pair() 在纸面模式下自动使用 PaperBridge
  - 独立日志文件和 PID 文件
"""

import logging
import logging.handlers
import os
import sys

# ── 确保项目根在 sys.path 中 ──────────────────────────────────────
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 切换工作目录到项目根，确保相对路径一致
os.chdir(_project_root)

from config import settings

# ── 日志配置 ───────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
LOG_DIR = settings.LOG_DIR  # 与实盘引擎共用 logs/ 目录


def _setup_logging() -> None:
    """配置纸面引擎独立日志（不影响实盘引擎日志文件）"""

    class ErrorFilter(logging.Filter):
        """只允许 ERROR 及以上级别的日志通过"""
        def filter(self, record):
            return record.levelno >= logging.ERROR

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))

    # 主日志: paper_engine.log
    main_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "paper_engine.log"),
        maxBytes=10_000_000,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    main_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # 错误日志: paper_engine_error.log
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "paper_engine_error.log"),
        maxBytes=5_000_000,    # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)


# ── PID 文件管理 ───────────────────────────────────────────────────
PID_FILE = os.path.join(_project_root, ".paper_engine_pid")


def _write_pid() -> None:
    """写入当前进程 PID 到 .paper_engine_pid"""
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    logging.getLogger(__name__).info(f"[PaperEngine] PID {os.getpid()} written to {PID_FILE}")


def _remove_pid() -> None:
    """清理 PID 文件"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            logging.getLogger(__name__).info("[PaperEngine] PID file cleaned")
    except OSError as e:
        logging.getLogger(__name__).warning(f"[PaperEngine] Failed to remove PID file: {e}")


# ── 主入口 ─────────────────────────────────────────────────────────
def main():
    """纸面引擎独立进程入口"""
    # 1. 配置日志
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("  Paper Trading Engine starting...")
    logger.info("=" * 50)

    # 2. 写入 PID 文件
    _write_pid()

    try:
        # 3. 创建纸面引擎
        from engine_standalone.main import TradingEngine
        engine = TradingEngine(engine_mode="paper")
        logger.info("[PaperEngine] engine_mode=paper, strategies loaded: "
                     f"{[s.__class__.__name__ for s in engine.strategies]}")

        # 4. 启动引擎
        engine.start()
    except KeyboardInterrupt:
        logger.info("[PaperEngine] Received KeyboardInterrupt, shutting down...")
    except Exception:
        logger.exception("[PaperEngine] Fatal error")
        sys.exit(1)
    finally:
        _remove_pid()
        logger.info("[PaperEngine] Process exited")


if __name__ == "__main__":
    main()
