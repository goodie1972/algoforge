"""
XAUUSD Engine Patrol Daemon
独立运行的监控守护进程，定时巡检引擎状态并报告异常。
不依赖主应用代码，只通过 REST API 通信。
"""
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# 控制台 UTF-8 输出（Windows 需要）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # py >= 3.7

# 绕过系统代理 — Windows 安全软件会拦截 Python 的 localhost 请求但放行 curl
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

# ============================================================
# 配置
# ============================================================
API_BASE = "http://localhost:8000/api"
POLL_INTERVAL = 30  # 秒
REFERENCE_PRICE = 4507.0
PRICE_DEVIATION = 20.0
ALERT_SL = 4480.03  # 需监视的止损位
STATE_FILE = Path(__file__).parent / ".patrol_state.json"
PID_FILE = Path(__file__).parent / ".patrol.pid"
LOG_FILE = Path(__file__).parent / "patrol.log"

# ============================================================
# 日志
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("patrol")


# ============================================================
# HTTP 工具
# ============================================================
def api_get(path: str):
    """调用 GET API，失败返回 None"""
    try:
        req = urllib.request.Request(API_BASE + path, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"API 请求失败 {path}: {e}")
        return None


# ============================================================
# Windows 通知
# ============================================================
def notify_critical(title: str, message: str):
    """关键报警 — Windows 弹窗 + 日志"""
    logger.warning(f"=== 报警: {title} — {message} ===")
    try:
        subprocess.run(
            [
                "powershell",
                "-Command",
                f'[System.Windows.Forms.MessageBox]::Show("{message}","{title}","OK","Warning")',
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


def notify_info(title: str, message: str):
    """一般通知"""
    logger.info(f"通知: {title} — {message}")


# ============================================================
# 状态管理
# ============================================================
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "positions": [],
        "engine_running": False,
        "bridge_connected": False,
        "last_price": 0,
        "reported_sl_4480": False,
        "reported_deviation": 0,
        "last_pos_tickets": [],
        "last_closed_tickets": set(),
        "last_closed_analysis": {},
    }


def save_state(state: dict):
    copy = dict(state)
    copy["last_pos_tickets"] = list(copy.get("last_pos_tickets", []))
    copy["last_closed_tickets"] = list(copy.get("last_closed_tickets", []))
    STATE_FILE.write_text(json.dumps(copy, indent=2), encoding="utf-8")


# ============================================================
# 巡检逻辑
# ============================================================
def patrol():
    state = load_state()
    # 转换旧格式中的 last_pos_tickets
    if isinstance(state.get("last_pos_tickets"), list):
        state["last_pos_tickets"] = set(state["last_pos_tickets"])
    if isinstance(state.get("last_closed_tickets"), list):
        state["last_closed_tickets"] = set(state["last_closed_tickets"])
    had_alert = False

    # ---- 1. 引擎状态 ----
    engine = api_get("/engine/status")
    if engine is None:
        notify_critical("引擎状态", "无法连接引擎 API！")
        had_alert = True
    else:
        running = engine.get("status") == "running"
        bridge = engine.get("bridge_connected", False)
        uptime = engine.get("uptime_seconds", 0)

        if not running:
            notify_critical("引擎异常", "引擎已停止！请立即处理")
            had_alert = True
        elif not bridge:
            notify_critical("桥接异常", "Bridge 已断开！请立即处理")
            had_alert = True
        else:
            # 从停止恢复
            if not state.get("engine_running"):
                notify_info("引擎恢复", f"引擎已启动（运行 {uptime:.0f}s）")

        state["engine_running"] = running
        state["bridge_connected"] = bridge

    # ---- 2. 价格 ----
    price_data = api_get("/market/price")
    if price_data:
        bid = price_data.get("bid", 0)
        ask = price_data.get("ask", 0)
        spread = price_data.get("spread", 0)
        logger.info(f"价格: bid={bid} ask={ask} spread={spread}")

        # 相对参考价波动（带去重 — 每次突破阈值 ±20 点才再报）
        if bid > 0:
            deviation = abs(bid - REFERENCE_PRICE)
            prev_dev = state.get("reported_deviation", 0)
            if deviation > PRICE_DEVIATION and abs(deviation - prev_dev) >= PRICE_DEVIATION:
                direction = "下跌" if bid < REFERENCE_PRICE else "上涨"
                notify_info(
                    "价格异动",
                    f"价格 {direction} {deviation:.1f} 点（参考 {REFERENCE_PRICE}，当前 {bid}）",
                )
                state["reported_deviation"] = deviation

        state["last_price"] = bid
    else:
        state["last_price"] = 0

    # ---- 3. 持仓 ----
    positions = api_get("/positions")
    if positions is not None:
        current_tickets = {p.get("ticket") for p in positions if p.get("ticket")}
        prev_tickets = state.get("last_pos_tickets", set())

        if current_tickets != prev_tickets:
            # 检查是否有 SL=4480.03 的仓被平
            for prev_pos in state.get("positions", []):
                if (
                    prev_pos.get("ticket") not in current_tickets
                    and abs(prev_pos.get("stop_loss", 0) - ALERT_SL) < 0.01
                ):
                    if not state.get("reported_sl_4480"):
                        notify_critical(
                            "止损触发",
                            f"单 {prev_pos['ticket']} SL={ALERT_SL} 已被触发平仓！",
                        )
                        state["reported_sl_4480"] = True
                        had_alert = True

            # 新开仓
            new_tickets = current_tickets - prev_tickets
            for t in new_tickets:
                p = next((x for x in positions if x["ticket"] == t), None)
                if p:
                    notify_info(
                        "新开仓",
                        f"单 {t} {p.get('order_type')} {p.get('volume')} @ {p.get('open_price')}",
                    )

            # 平仓
            closed_tickets = prev_tickets - current_tickets
            for t in closed_tickets:
                p = next((x for x in state.get("positions", []) if x["ticket"] == t), None)
                if p:
                    profit = p.get("profit", 0)
                    notify_info(
                        "平仓",
                        f"单 {t} 已平，盈亏 {profit:+.2f}",
                    )

        state["last_pos_tickets"] = current_tickets
        state["positions"] = positions

        if positions:
            logger.info(f"持仓: {len(positions)} 单")
            for p in positions:
                logger.info(
                    f"  #{p['ticket']} {p.get('order_type')} vol={p.get('volume')} "
                    f"open={p.get('open_price')} cur={p.get('current_price')} "
                    f"profit={p.get('profit'):+.2f} sl={p.get('stop_loss')}"
                )
        else:
            logger.info("持仓: 无")
    else:
        state["last_pos_tickets"] = set()
        state["positions"] = []

    # ---- 5. 已平仓亏损分析 ----
    history = api_get("/trades/history")
    if history is not None:
        current_closed_tickets = {t.get("ticket") for t in history if t.get("ticket")}
        prev_closed_tickets = state.get("last_closed_tickets", set())
        if isinstance(prev_closed_tickets, list):
            prev_closed_tickets = set(prev_closed_tickets)

        # 检测新平仓记录
        new_closed = current_closed_tickets - prev_closed_tickets
        if new_closed:
            logger.info(f"检测到 {len(new_closed)} 笔新平仓: {new_closed}")
            for t in new_closed:
                trade = next((x for x in history if x.get("ticket") == t), None)
                if trade:
                    pnl = trade.get("pnl", 0)
                    strategy = trade.get("strategy", "?")
                    exit_reason = trade.get("exit_reason", "?")
                    logger.info(f"  平仓 {t}: {strategy} pnl={pnl:+.2f} 原因={exit_reason}")
                    # 亏损单 → 自动分析
                    if pnl < 0:
                        analysis = api_get(f"/trades/analysis/{t}")
                        if analysis:
                            xa = analysis.get("exit_analysis", {})
                            la = xa.get("loss_analysis", {})
                            reasons = la.get("possible_reasons", [])
                            suggestions = la.get("suggestions", [])
                            logger.warning(f"  ⚠ 亏损分析 #{t}:")
                            for r in reasons:
                                logger.warning(f"    - 原因: {r}")
                            for s in suggestions:
                                logger.warning(f"    → 建议: {s}")
                            notify_info(
                                "亏损单分析",
                                f"单 {t} {strategy} 亏损 ${abs(pnl):.2f}。"
                                f"原因: {'; '.join(reasons[:2]) or xa.get('label','?')}",
                            )
                            state.setdefault("last_closed_analysis", {})[str(t)] = analysis

        state["last_closed_tickets"] = current_closed_tickets

    # ---- 4. 错误日志 ----
    logs = api_get("/logs")
    if logs:
        db_kw = ["database", "sqlite", "ohlcv", "no such table", "market_data.db"]
        errors = [
            l.get("message", "")
            for l in logs.get("logs", [])
            if "ERROR" in l.get("message", "")
            or "exception" in l.get("message", "").lower()
            or ("WARNING" in l.get("message", "")
                and any(kw in l.get("message", "").lower() for kw in db_kw))
        ]
        if errors:
            err_count = sum(1 for e in errors if "ERROR" in e.upper() or "exception" in e.lower())
            warn_count = len(errors) - err_count
            label = f"{err_count} 条错误"
            if warn_count:
                label += f", {warn_count} 条数据库告警"
            logger.warning(f"检测到 {label}:")
            for e in errors[-5:]:  # 最多显示 5 条
                logger.warning(f"  {e}")

    # ---- 保存状态 ----
    save_state(state)

    return had_alert


def patrol_loop():
    """主循环"""
    logger.info("=" * 50)
    logger.info("XAUUSD 监控守护进程启动")
    logger.info(f"API 地址: {API_BASE}")
    logger.info(f"巡检间隔: {POLL_INTERVAL}s")
    logger.info(f"参考价格: {REFERENCE_PRICE}")
    logger.info(f"波动阈值: {PRICE_DEVIATION}")
    logger.info("=" * 50)

    # 写 PID
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    while True:
        try:
            tick = time.time()
            has_alert = patrol()

            if not has_alert:
                logger.info("一切正常，无变化")

            elapsed = time.time() - tick
            sleep_time = max(POLL_INTERVAL - elapsed, 5)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("收到中断，退出")
            break
        except Exception as e:
            logger.error(f"巡检异常: {e}", exc_info=True)
            time.sleep(POLL_INTERVAL)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    patrol_loop()
