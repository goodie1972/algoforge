"""
XAUUSD V6 交易引擎 — 一键启动脚本

执行顺序:
  1. 环境检查 (Python 版本)
  2. 核心模块可导入性检查
  3. 配置有效性检查 (STRATEGY_POOL, SYMBOL, LOT_SIZE)
  4. FreeMT4 EA 连通性检查
  5. 非关键目录检查 (data/, logs/)
  6. 摘要 → 启动引擎

用法:
  python run.py
"""

import os
import sys
import socket

# ── 确保项目根在 sys.path 中 ──────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── ANSI 颜色 ─────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  [{GREEN}PASS{RESET}] {msg}")


def fail(msg: str) -> None:
    print(f"  [{RED}FAIL{RESET}] {msg}")


def warn(msg: str) -> None:
    print(f"  [{YELLOW}WARN{RESET}] {msg}")


# ── 检查结果收集 ──────────────────────────────────────────────────
results: list[tuple[str, bool, bool, str]] = []  # (label, ok, critical, detail)


def record(label: str, result: tuple[bool, str], critical: bool = True) -> None:
    passed, detail = result
    results.append((label, passed, critical, detail))
    if passed:
        ok(label)
    elif critical:
        fail(label + " — " + detail)
    else:
        warn(label + " — " + detail)


# ═══════════════════════════════════════════════════════════════════
# 检查 1 — Python 版本 >= 3.10
# ═══════════════════════════════════════════════════════════════════
def check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        return False, f"Python {v.major}.{v.minor} — 需要 >= 3.10"
    return True, f"Python {v.major}.{v.minor}.{v.micro}"


# ═══════════════════════════════════════════════════════════════════
# 检查 2 — 核心模块可导入
# ═══════════════════════════════════════════════════════════════════
def check_core_bridge() -> tuple[bool, str]:
    try:
        from core.bridge import create_bridge, OrderType  # noqa: F401
        return True, "core.bridge 可导入"
    except ImportError as e:
        return False, f"core.bridge 导入失败: {e}"


# ═══════════════════════════════════════════════════════════════════
# 检查 3 — 配置可导入 + 关键字段有效
# ═══════════════════════════════════════════════════════════════════
def check_settings() -> tuple[bool, str]:
    try:
        from config.settings import STRATEGY_POOL, SYMBOL, LOT_SIZE  # noqa: F401
    except ImportError as e:
        return False, f"config.settings 导入失败: {e}"

    # V6 策略在策略池中
    if "H1_v6_hybrid" not in STRATEGY_POOL:
        return False, "STRATEGY_POOL 缺少 'H1_v6_hybrid'"

    # SYMBOL
    if SYMBOL != "XAUUSD":
        return False, f"SYMBOL = '{SYMBOL}'，应为 'XAUUSD'"

    # LOT_SIZE 应该为正数
    try:
        ls = float(LOT_SIZE)
        if ls <= 0:
            return False, f"LOT_SIZE = {ls}，必须为正数"
    except (TypeError, ValueError):
        return False, f"LOT_SIZE 无效: {LOT_SIZE!r}"

    return True, "config.settings 有效 (V6 策略, XAUUSD, 正确手数)"


# ═══════════════════════════════════════════════════════════════════
# 检查 4 — FreeMT4 EA 端口可达
# ═══════════════════════════════════════════════════════════════════
def check_mt4_connection() -> tuple[bool, str]:
    try:
        from config.settings import FREEMT4_HOST, FREEMT4_PORT
    except ImportError:
        return False, "无法导入 FREEMT4_HOST / FREEMT4_PORT"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((FREEMT4_HOST, FREEMT4_PORT))
        s.close()
        return True, f"FreeMT4 EA 响应 {FREEMT4_HOST}:{FREEMT4_PORT}"
    except OSError as e:
        return False, f"FreeMT4 EA 不可达 {FREEMT4_HOST}:{FREEMT4_PORT} — {e}"


# ═══════════════════════════════════════════════════════════════════
# 检查 5 — 目录存在 (非关键)
# ═══════════════════════════════════════════════════════════════════
def check_data_dir() -> tuple[bool, str]:
    data_path = os.path.join(PROJECT_ROOT, "data")
    if os.path.isdir(data_path):
        return True, "data/ 目录存在"
    return False, "data/ 目录不存在"


def check_logs_dir() -> tuple[bool, str]:
    logs_path = os.path.join(PROJECT_ROOT, "logs")
    if os.path.isdir(logs_path):
        return True, "logs/ 目录存在"
    return False, "logs/ 目录不存在"


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════
def main() -> None:
    print()
    print("=" * 50)
    print("  XAUUSD V6 交易引擎 — 启动前检查")
    print("=" * 50)
    print()

    # ── 1 Python 版本 ────────────────────────────────────────────
    print("[1/5] Python 版本")
    record("Python >= 3.10", check_python_version(), critical=True)
    print()

    # ── 2 核心模块 ────────────────────────────────────────────────
    print("[2/5] 核心模块")
    record("core.bridge 可导入", check_core_bridge(), critical=True)
    print()

    # ── 3 配置 ────────────────────────────────────────────────────
    print("[3/5] 配置检查")
    record("config.settings 有效", check_settings(), critical=True)
    print()

    # ── 4 MT4 连接 ───────────────────────────────────────────────
    print("[4/5] FreeMT4 连接")
    record("FreeMT4 EA 可达", check_mt4_connection(), critical=True)
    print()

    # ── 5 目录 (非关键) ──────────────────────────────────────────
    print("[5/5] 目录检查")
    record("data/ 目录", check_data_dir(), critical=False)
    record("logs/ 目录", check_logs_dir(), critical=False)
    print()

    # ── 摘要 ──────────────────────────────────────────────────────
    print("=" * 50)
    print("  检查摘要")
    print("=" * 50)
    all_critical_pass = True
    for label, passed, critical, detail in results:
        if passed:
            status = "PASS"
            icon = GREEN
        elif critical:
            status = "FAIL"
            icon = RED
            all_critical_pass = False
        else:
            status = "WARN"
            icon = YELLOW
        tag = "(CRIT) " if critical else "(INFO) "
        print(f"  [{icon}{status}{RESET}] {tag}{label}")
    print()

    # ── 启动引擎 ──────────────────────────────────────────────────
    if all_critical_pass:
        print("=" * 50)
        print("  所有关键检查通过，启动 XAUUSD V6 交易引擎...")
        print("=" * 50)
        try:
            from main import main as engine_main
            engine_main()
        except Exception as e:
            print(f"\n  [{RED}错误{RESET}] 引擎启动失败: {e}")
            print(f"  请检查 MT4 连接和日志文件获取详情")
            sys.exit(1)
    else:
        print("=" * 50)
        print(f"  {RED}关键检查未通过，请修复上述 [FAIL] 项后重试{RESET}")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
