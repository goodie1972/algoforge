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
API_BASE = "http://localhost:1783/api"
POLL_INTERVAL = 30  # 秒
SHARP_MOVE_THRESHOLD = 50   # 短期剧烈波动阈值（点）
MOVE_WINDOW_SECONDS = 60    # 检测窗口（秒）
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
    """关键报警 — Windows 弹窗 + 日志 + 邮件/企微推送"""
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
    try:
        from alert_sender import send_alert
        send_alert(title, f"{title} — {message}")
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
        "price_samples": [],
        "last_seen_error_time": "",
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

    # ---- 2. 短期剧烈波动检测 ----
    price_data = api_get("/market/price")
    if price_data:
        bid = price_data.get("bid", 0)
        ask = price_data.get("ask", 0)
        spread = price_data.get("spread", 0)
        logger.info(f"价格: bid={bid} ask={ask} spread={spread}")

        # 在窗口内查找最大波动（通过与上次巡检价格对比）
        if bid > 0:
            prev_price = state.get("last_price", 0)
            if prev_price > 0:
                move = abs(bid - prev_price)
                # 检查短期累计波动：价格变化超过阈值
                price_samples = state.get("price_samples", [])
                now = time.time()
                price_samples.append({"price": bid, "time": now})
                # 清理超出窗口的样本
                cutoff = now - MOVE_WINDOW_SECONDS
                price_samples = [s for s in price_samples if s["time"] >= cutoff]
                # 最多保留 30 个样本
                if len(price_samples) > 30:
                    price_samples = price_samples[-30:]

                if len(price_samples) >= 2:
                    oldest = price_samples[0]
                    window_move = abs(bid - oldest["price"])
                    if window_move >= SHARP_MOVE_THRESHOLD:
                        direction = "急涨" if bid > oldest["price"] else "急跌"
                        notify_info(
                            "价格剧烈波动",
                            f"{direction} {window_move:.1f} 点（{oldest['price']} → {bid}，{MOVE_WINDOW_SECONDS}s 内）",
                        )
                        # 触发后清空历史，避免重复报警
                        price_samples = []

                state["price_samples"] = price_samples

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

    # ---- 4. 错误日志（仅新出现的错误） ----
    logs = api_get("/logs")
    if logs:
        log_entries = logs.get("logs", [])
        last_seen = state.get("last_seen_error_time", "")
        latest_time = last_seen
        new_errors = []

        for l in log_entries:
            msg = l.get("message", "")
            ts = l.get("time", "") or ""
            if not ts:
                continue
            is_error = "ERROR" in msg or "exception" in msg.lower()
            is_db_warn = "WARNING" in msg and any(kw in msg.lower() for kw in
                         ["database", "sqlite", "ohlcv", "no such table", "market_data.db"])
            if not (is_error or is_db_warn):
                continue
            if ts > latest_time:
                latest_time = ts
            if ts > last_seen:
                new_errors.append(msg)

        if new_errors:
            logger.warning(f"检测到 {len(new_errors)} 条新错误/告警:")
            for e in new_errors[-5:]:
                logger.warning(f"  {e}")
        elif latest_time > last_seen:
            # 没有新错误，但时间戳变了（旧的日志），更新 last_seen 避免重复报告
            pass

        if latest_time > last_seen:
            state["last_seen_error_time"] = latest_time

    # ---- 保存状态 ----
    save_state(state)

    return had_alert


def patrol_loop():
    """主循环"""
    logger.info("=" * 50)
    logger.info("XAUUSD 监控守护进程启动")
    logger.info(f"API 地址: {API_BASE}")
    logger.info(f"巡检间隔: {POLL_INTERVAL}s")
    logger.info(f"剧烈波动阈值: {SHARP_MOVE_THRESHOLD} 点 / {MOVE_WINDOW_SECONDS}s")
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
