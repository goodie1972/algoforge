#!/usr/bin/env python3
"""bakome_buy_watchdog.py — 监控 bakome_backup_optimized 的 10 个 BUY 持仓

逻辑：
- 每 30 秒轮询 /api/positions
- 记录每单的最高盈利峰值
- 当盈利从峰值回撤 >=40% 时 -> 自动止盈平仓
- 当盈利转亏 -> 立即平仓（绝不让盈利单变亏损）
"""

import json
import time
import sys
import os
import urllib.request

API_BASE = "http://127.0.0.1:1783"
MAGIC = 777006
POLL_INTERVAL = 30
DRAWDOWN_PCT = 0.40
SUMMARY_INTERVAL = 2  # 每 N 次轮询输出一次摘要


def log(msg):
    """UTF-8 直出，GBK终端不乱码"""
    sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def get_positions():
    try:
        resp = urllib.request.urlopen(f"{API_BASE}/api/positions", timeout=5)
        return json.loads(resp.read().decode())
    except Exception as e:
        log(f"[watchdog] 获取持仓失败: {e}")
        return []


def close_ticket(ticket):
    try:
        data = json.dumps({"ticket": ticket}).encode()
        req = urllib.request.Request(
            f"{API_BASE}/api/positions/close",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read().decode())
        log(f"[watchdog] 平仓成功 ticket={ticket}: {result}")
        return True
    except Exception as e:
        log(f"[watchdog] 平仓失败 ticket={ticket}: {e}")
        return False


def main():
    log(f"[watchdog] bakome BUY 监控启动 - 每 {POLL_INTERVAL} 秒轮询")
    log(f"[watchdog] 回撤 {DRAWDOWN_PCT*100:.0f}% 触发止盈，盈利转亏立即平仓")

    peaks = {}  # ticket -> 最高盈利
    counter = 0

    while True:
        positions = get_positions()
        buys = [p for p in positions
                if p.get("magic") == MAGIC and p.get("order_type") in ("OP_BUY", "BUY")]

        if not buys:
            log("[watchdog] 所有 BUY 已平仓，监控结束")
            break

        counter += 1

        # 记录峰值
        for p in buys:
            ticket = p["ticket"]
            profit = p.get("profit", 0)
            if ticket not in peaks or profit > peaks[ticket]:
                peaks[ticket] = profit

        # 检查每单
        for p in buys:
            ticket = p["ticket"]
            profit = p.get("profit", 0)
            peak = peaks.get(ticket, profit)

            # 条件 1: 盈利转亏 -> 立即平仓
            if profit <= 0 and peak > 0:
                log(f"[watchdog] 盈利转亏! ticket={ticket} peak=${peak:.2f} -> now=${profit:.2f}")
                close_ticket(ticket)
                continue

            # 条件 2: 盈利回撤 >= 40% -> 止盈
            if peak > 2.0:
                drawdown = (peak - profit) / peak
                if drawdown >= DRAWDOWN_PCT:
                    log(f"[watchdog] 回撤 {drawdown*100:.0f}% ticket={ticket} peak=${peak:.2f} -> now=${profit:.2f}")
                    close_ticket(ticket)
                    continue

        # 定期输出状态摘要
        if counter % SUMMARY_INTERVAL == 0:
            if buys:
                total_pnl = sum(p.get("profit", 0) for p in buys)
                max_pnl = max(p.get("profit", 0) for p in buys)
                min_pnl = min(p.get("profit", 0) for p in buys)
                log(f"[watchdog] BUY x{len(buys)} 总盈利=${total_pnl:.2f} 最高=${max_pnl:.2f} 最低=${min_pnl:.2f}")

        time.sleep(POLL_INTERVAL)

    log("[watchdog] 监控进程退出")


if __name__ == "__main__":
    main()