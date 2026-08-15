"""
RSI 单线 vs 双线交叉 回测对比
H1 数据，同参数框架，只换 RSI 逻辑
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from collections import deque


# ============================================================
# 基础数据结构
# ============================================================
class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass
class Candle:
    time: object
    open: float
    high: float
    low: float
    close: float

@dataclass
class Position:
    direction: OrderType
    entry_price: float
    entry_time: object
    sl: float = 0
    trail_sl: float = 0
    ticket: int = 0

# ============================================================
# 技术指标
# ============================================================
def calc_sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def calc_stddev(values, period, mean):
    if len(values) < period:
        return None
    variance = sum((v - mean) ** 2 for v in values[-period:]) / period
    return math.sqrt(variance)

def calc_ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = (v - ema) * k + ema
    return ema

def calc_rsi(closes, period):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calc_bb_bandwidth(closes, period, std_mult):
    if len(closes) < period:
        return None
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((c - sma) ** 2 for c in recent) / period
    return math.sqrt(variance) * std_mult

# ============================================================
# 回测配置
# ============================================================
@dataclass
class Config:
    name: str
    bb_period: int = 20
    bb_std: float = 2.0
    sl_bb_mult: float = 0.35
    max_positions: int = 1

@dataclass
class RSISingleConfig(Config):
    rsi_period: int = 14
    rsi_oversold: float = 30
    rsi_overbought: float = 70

@dataclass
class RSICrossConfig(Config):
    rsi_fast: int = 3
    rsi_slow: int = 13

# ============================================================
# 信号函数
# ============================================================
def signal_rsi_single(candles, closes, config, state):
    """RSI 单线: 价格触轨 + RSI 极端值"""
    sma = calc_sma(closes, config.bb_period)
    if sma is None:
        return None
    std = calc_stddev(closes, config.bb_period, sma)
    if std is None:
        return None
    upper = sma + config.bb_std * std
    lower = sma - config.bb_std * std
    rsi = calc_rsi(closes, config.rsi_period)
    if rsi is None:
        return None
    current = closes[-1]

    # 忽略已有持仓状态（由 main 循环控制）
    if current <= lower and rsi < config.rsi_oversold:
        return OrderType.BUY
    if current >= upper and rsi > config.rsi_overbought:
        return OrderType.SELL
    return None

def signal_rsi_cross(candles, closes, config, state):
    """RSI 双线交叉: 价格触轨 + 快慢线交叉"""
    sma = calc_sma(closes, config.bb_period)
    if sma is None:
        return None
    std = calc_stddev(closes, config.bb_period, sma)
    if std is None:
        return None
    upper = sma + config.bb_std * std
    lower = sma - config.bb_std * std

    fast = calc_rsi(closes, config.rsi_fast)
    slow = calc_rsi(closes, config.rsi_slow)
    if fast is None or slow is None:
        return None

    prev_fast = state.get("prev_fast")
    prev_slow = state.get("prev_slow")

    state["prev_fast"] = fast
    state["prev_slow"] = slow

    if prev_fast is None or prev_slow is None:
        return None

    golden = prev_fast <= prev_slow and fast > slow
    death = prev_fast >= prev_slow and fast < slow
    current = closes[-1]

    if golden and current <= lower:
        return OrderType.BUY
    if death and current >= upper:
        return OrderType.SELL
    return None

# ============================================================
# 出场逻辑 (EMA20 渐进追踪)
# ============================================================
def check_ema20_exit(pos, closes, bid_ask, direction):
    """EMA20 只向有利方向移动"""
    ema = calc_ema(closes, 20)
    if ema is None:
        return False
    if direction == OrderType.BUY:
        if ema > pos.trail_sl:
            pos.trail_sl = ema
        if bid_ask[0] <= pos.trail_sl:
            return True
    else:
        if ema < pos.trail_sl:
            pos.trail_sl = ema
        if bid_ask[1] >= pos.trail_sl:
            return True
    return False

# ============================================================
# 回测引擎
# ============================================================
def run_backtest(candles, closes, config, signal_fn):
    trades = []
    active = []
    state = {}
    next_ticket = 1
    equity_curve = []

    for i in range(max(config.bb_period, 20) + 10, len(candles)):
        window_candles = candles[:i+1]
        window_closes = closes[:i+1]
        current_candle = candles[i]
        # 用收盘价模拟，价差 ~0.4
        price = current_candle.close
        spread = 0.4
        bid = price
        ask = price + spread

        # === 出场检查 ===
        still_active = []
        for pos in active:
            if check_ema20_exit(pos, window_closes, (bid, ask), pos.direction):
                exit_price = bid if pos.direction == OrderType.BUY else ask
                profit = (exit_price - pos.entry_price) if pos.direction == OrderType.BUY else (pos.entry_price - exit_price)
                trades.append({
                    "ticket": pos.ticket,
                    "direction": pos.direction.value,
                    "entry": pos.entry_price,
                    "exit": ask if pos.direction == OrderType.BUY else bid,
                    "profit": profit,
                    "entry_time": pos.entry_time,
                })
            else:
                still_active.append(pos)
        active = still_active

        # === 入场检查 ===
        if len(active) < config.max_positions:
            signal = signal_fn(window_candles, window_closes, config, state)
            if signal:
                entry_price = ask if signal == OrderType.BUY else bid  # BUY 用 ask, SELL 用 bid
                bandwidth = calc_bb_bandwidth(window_closes, config.bb_period, config.bb_std)
                if bandwidth and bandwidth > 0:
                    sl_dist = bandwidth * config.sl_bb_mult
                else:
                    sl_dist = entry_price * 0.005

                if signal == OrderType.BUY:
                    sl = entry_price - sl_dist
                else:
                    sl = entry_price + sl_dist

                pos = Position(
                    direction=signal,
                    entry_price=entry_price,
                    entry_time=current_candle.time,
                    sl=sl,
                    trail_sl=sl,
                    ticket=next_ticket,
                )
                next_ticket += 1
                active.append(pos)

    # 平掉未平仓（按最后一根收盘价）
    if active:
        last_close = closes[-1]
        last_bid = last_close
        last_ask = last_close + 0.4
        for pos in active:
            exit_price = last_bid if pos.direction == OrderType.BUY else last_ask
            profit = (exit_price - pos.entry_price) if pos.direction == OrderType.BUY else (pos.entry_price - exit_price)
        trades.append({
            "ticket": pos.ticket,
            "direction": pos.direction.value,
            "entry": pos.entry_price,
            "exit": last_close,
            "profit": profit,
            "entry_time": pos.entry_time,
        })

    return trades

# ============================================================
# 统计
# ============================================================
def summarize(name, trades):
    n = len(trades)
    if n == 0:
        return f"{name}: 0 笔交易"
    wins = sum(1 for t in trades if t["profit"] > 0)
    total_profit = sum(t["profit"] for t in trades)
    avg_win = sum(t["profit"] for t in trades if t["profit"] > 0) / max(wins, 1)
    avg_loss = sum(t["profit"] for t in trades if t["profit"] <= 0) / max(n - wins, 1)
    return (f"{name}: {n}笔 | 盈亏=${total_profit:,.0f} | 胜率={wins/n*100:.1f}% | "
            f"均盈=${avg_win:,.0f} 均亏=${avg_loss:,.0f}")

# ============================================================
# Main
# ============================================================
def main():
    import sys
    sys.path.insert(0, ".")
    from core.bridge import create_bridge
    from datetime import datetime

    bridge = create_bridge()
    if not bridge.connect():
        print("MT4 连接失败!")
        return

    raw = bridge.get_candles("XAUUSD", "H1", 4000)
    candles = list(reversed(raw))
    bridge.disconnect()

    # 转换为 backtest Candle
    bt_candles = []
    for c in candles:
        bt_candles.append(Candle(
            time=datetime.fromtimestamp(int(c.time)),
            open=c.open, high=c.high, low=c.low, close=c.close,
        ))

    closes = [c.close for c in bt_candles]
    print(f"数据: {len(bt_candles)} 根 H1 K线  {bt_candles[0].time} ~ {bt_candles[-1].time}\n")

    configs = [
        (RSISingleConfig(name="RSI单线_30x70"), signal_rsi_single),
        (RSISingleConfig(name="RSI单线_35x65", rsi_oversold=35, rsi_overbought=65), signal_rsi_single),
        (RSICrossConfig(name="RSI交叉_3x13"), signal_rsi_cross),
        (RSICrossConfig(name="RSI交叉_3x21", rsi_slow=21), signal_rsi_cross),
        (RSICrossConfig(name="RSI交叉_5x13", rsi_fast=5, rsi_slow=13), signal_rsi_cross),
    ]

    for config, signal_fn in configs:
        trades = run_backtest(bt_candles, closes, config, signal_fn)
        print(summarize(config.name, trades))

    print()

if __name__ == "__main__":
    main()
