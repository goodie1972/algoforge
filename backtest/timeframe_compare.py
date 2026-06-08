"""
时间周期对比回测 — 从 SQLite 读取数据
比较 RSI布林带 M30 vs H1, Stoch布林带 H1 vs H4
使用真实策略逻辑（M30 RSI方向过滤, MACD过滤, 极端区保护）
"""
import math
import sys
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import get_candles

# ======================== 常量 ========================
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
STOCH_K = 8
STOCH_SLOWING = 3
STOCH_D = 3
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80
STOCH_EXTREME_OVERSOLD = 10
STOCH_EXTREME_OVERBOUGHT = 90

LOT_SIZE = 0.01
CONTRACT_SIZE = 100
COMMISSION = 0.5

OUTPUT_FILE = "backtest/timeframe_compare_results.md"


@dataclass
class BTPos:
    entry_idx: int
    entry_price: float
    direction: str  # "BUY" / "SELL"
    entry_time: int = 0
    sl: float = 0.0
    tp: float = 0.0
    exit_idx: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    trail_sl: float = 0.0


# ======================== 指标计算 ========================

def calc_rsi(closes, period=14):
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
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema) * k + ema
    return ema


def calc_bb(closes, period, std_mult):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((c - sma) ** 2 for c in recent) / period
    std = math.sqrt(variance)
    return sma, std * std_mult, std


def calc_stoch(candles_slice, k_period, slowing, d_period):
    """candles_slice: list of dict with open/high/low/close"""
    n = len(candles_slice)
    min_needed = k_period + slowing + d_period + 1
    if n < min_needed:
        return None
    raw_k = []
    for i in range(k_period - 1, n):
        window = candles_slice[i - k_period + 1: i + 1]
        highest = max(c["high"] for c in window)
        lowest = min(c["low"] for c in window)
        close = window[-1]["close"]
        if highest == lowest:
            raw_k.append(50.0)
        else:
            raw_k.append((close - lowest) / (highest - lowest) * 100)
    if len(raw_k) < slowing + d_period + 1:
        return None
    smooth_k = []
    for i in range(slowing - 1, len(raw_k)):
        val = sum(raw_k[i - slowing + 1: i + 1]) / slowing
        smooth_k.append(val)
    if len(smooth_k) < d_period + 1:
        return None
    curr_k = smooth_k[-1]
    prev_k = smooth_k[-2]
    curr_d = sum(smooth_k[-d_period:]) / d_period
    prev_d = sum(smooth_k[-(d_period + 1):-1]) / d_period
    return prev_k, curr_k, prev_d, curr_d


def calc_macd(closes):
    """Return (histogram, hist_increasing)"""
    if len(closes) < 35:
        return None, False
    macd_values = []
    for i in range(26, len(closes)):
        window = closes[:i + 1]
        e12 = e26 = window[0]
        k12, k26 = 2.0 / 13, 2.0 / 27
        for p in window[1:]:
            e12 = (p - e12) * k12 + e12
            e26 = (p - e26) * k26 + e26
        macd_values.append(e12 - e26)
    if len(macd_values) < 10:
        return None, False
    k9 = 2.0 / 10
    sig = macd_values[0]
    for v in macd_values[1:]:
        sig = (v - sig) * k9 + sig
    curr_signal = sig
    ps = macd_values[0]
    for v in macd_values[:-1]:
        ps = (v - ps) * k9 + ps
    prev_signal = ps
    curr_hist = macd_values[-1] - curr_signal
    prev_hist = macd_values[-2] - prev_signal
    return curr_hist, curr_hist > prev_hist


def calc_m30_rsi_dir(closes_m30, rsi_period):
    """最近 3 根 M30 的 RSI 连续递增→up, 递减→down"""
    if len(closes_m30) < rsi_period + 4:
        return None
    rsi_old = calc_rsi(closes_m30[:-2], rsi_period)
    rsi_mid = calc_rsi(closes_m30[:-1], rsi_period)
    rsi_new = calc_rsi(closes_m30, rsi_period)
    if rsi_old is None or rsi_mid is None or rsi_new is None:
        return None
    if rsi_old < rsi_mid < rsi_new:
        return "up"
    elif rsi_old > rsi_mid > rsi_new:
        return "down"
    return "flat"


def calc_m30_rsi_exit(closes_m30, rsi_period):
    """最近 2 根 M30 的 RSI 上升→up, 下降→down"""
    if len(closes_m30) < rsi_period + 3:
        return None
    rsi_prev = calc_rsi(closes_m30[:-1], rsi_period)
    rsi_curr = calc_rsi(closes_m30, rsi_period)
    if rsi_prev is None or rsi_curr is None:
        return None
    if rsi_prev < rsi_curr:
        return "up"
    elif rsi_prev > rsi_curr:
        return "down"
    return "flat"


# ======================== 核心回测引擎 ========================

def run_rsi_bollinger_backtest(
    candles_main: list[dict],
    timeframe: str,
    candles_m30: list[dict] = None,
    label: str = ""
):
    """
    RSI Bollinger 真实策略回测
    - 入场: BB触轨 + RSI超卖/超买 + M30 RSI方向过滤
    - 出场: M30 RSI反转出场
    - 初始SL: BB带宽 × 0.35
    """
    positions: list[BTPos] = []
    active: list[BTPos] = []
    total_pnl = 0.0
    wins = 0
    losses = 0
    long_wins = 0
    long_total = 0
    short_wins = 0
    short_total = 0

    min_bars = max(BB_PERIOD, RSI_PERIOD) + 10
    total_bars = len(candles_main)

    # 预计算 M30 收盘价数组（加速）
    m30_closes = [c["close"] for c in candles_m30] if candles_m30 else []
    # M30 时间戳数组
    m30_times = [c["time"] for c in candles_m30] if candles_m30 else []

    for i in range(min_bars, total_bars):
        current = candles_main[i]
        current_close = current["close"]
        current_high = current["high"]
        current_low = current["low"]
        current_time = current["time"]

        # 获取当前主周期之前的收盘价
        closes = [c["close"] for c in candles_main[:i + 1]]

        # 对齐 M30 数据：找到当前时间之前的 M30 收盘价
        m30_aligned = m30_closes
        if m30_times:
            # 找到 <= current_time 的最大索引
            cutoff = 0
            for j in range(len(m30_times) - 1, -1, -1):
                if m30_times[j] <= current_time:
                    cutoff = j + 1
                    break
            m30_aligned = m30_closes[:cutoff] if cutoff > 0 else []

        # 计算指标
        sma, bandwidth, _ = calc_bb(closes, BB_PERIOD, BB_STD)
        rsi = calc_rsi(closes, RSI_PERIOD)
        if sma is None or rsi is None or bandwidth is None:
            continue

        upper = sma + bandwidth
        lower = sma - bandwidth

        # BB 带宽 × 0.35 SL 距离
        sl_dist = bandwidth * 0.35

        # ====== 出场检查（M30 RSI 反转出场）======
        closed_positions = []
        still_active = []

        for pos in active:
            is_buy = pos.direction == "BUY"

            # SL 检查（初始 SL 或追踪后的 SL）
            if pos.sl > 0:
                if is_buy and current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue
                if not is_buy and current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue

            # M30 RSI 反转出场（需要足够 M30 数据）
            if len(m30_aligned) >= RSI_PERIOD + 3:
                exit_dir = calc_m30_rsi_exit(m30_aligned, RSI_PERIOD)
                if exit_dir is not None:
                    if is_buy and exit_dir == "down":
                        pos.exit_idx = i
                        pos.exit_price = current_close
                        pos.exit_reason = "M30_RSI_EXIT"
                        closed_positions.append(pos)
                        continue
                    if not is_buy and exit_dir == "up":
                        pos.exit_idx = i
                        pos.exit_price = current_close
                        pos.exit_reason = "M30_RSI_EXIT"
                        closed_positions.append(pos)
                        continue

            still_active.append(pos)

        # 结算已平仓
        for pos in closed_positions:
            _settle_position(pos)
            total_pnl += pos.pnl
            wins += 1 if pos.pnl > 0 else 0
            losses += 1 if pos.pnl <= 0 else 0
            if pos.direction == "BUY":
                long_total += 1
                long_wins += 1 if pos.pnl > 0 else 0
            else:
                short_total += 1
                short_wins += 1 if pos.pnl > 0 else 0
            positions.append(pos)

        active = still_active

        # ====== 入场 ======
        if len(active) >= 1:
            continue

        # 信号逻辑：BB触轨 + RSI + M30 RSI方向过滤
        signal_dir = None

        if current_close <= lower and rsi < RSI_OVERSOLD:
            # BUY: 需要 M30 RSI 方向向上
            m30_dir = calc_m30_rsi_dir(m30_aligned, RSI_PERIOD) if len(m30_aligned) >= RSI_PERIOD + 4 else None
            if m30_dir == "up":
                signal_dir = "BUY"

        elif current_close >= upper and rsi > RSI_OVERBOUGHT:
            # SELL: 需要 M30 RSI 方向向下
            m30_dir = calc_m30_rsi_dir(m30_aligned, RSI_PERIOD) if len(m30_aligned) >= RSI_PERIOD + 4 else None
            if m30_dir == "down":
                signal_dir = "SELL"

        if signal_dir is None:
            continue

        # 计算 SL
        if signal_dir == "BUY":
            sl = round(current_close - sl_dist, 2)
        else:
            sl = round(current_close + sl_dist, 2)

        if sl <= 0:
            continue

        pos = BTPos(
            entry_idx=i,
            entry_price=current_close,
            direction=signal_dir,
            entry_time=current_time,
            sl=sl,
            trail_sl=sl,
        )
        active.append(pos)

    # 最终平仓
    for pos in active:
        last = candles_main[-1]
        if pos.direction == "BUY":
            pos.pnl = (last["close"] - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        else:
            pos.pnl = (pos.entry_price - last["close"]) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        pos.exit_idx = total_bars - 1
        pos.exit_price = last["close"]
        pos.exit_reason = "EXPIRY"
        total_pnl += pos.pnl
        wins += 1 if pos.pnl > 0 else 0
        losses += 1 if pos.pnl <= 0 else 0
        if pos.direction == "BUY":
            long_total += 1
            long_wins += 1 if pos.pnl > 0 else 0
        else:
            short_total += 1
            short_wins += 1 if pos.pnl > 0 else 0
        positions.append(pos)

    return _compute_stats(positions, wins, losses, long_wins, long_total, short_wins, short_total, total_pnl, label)


def run_stoch_bollinger_backtest(
    candles_main: list[dict],
    timeframe: str,
    label: str = ""
):
    """
    Stoch Bollinger 真实策略回测
    - 入场: Stoch超卖金叉/超买死叉 + MACD过滤 + 极端区保护
    - 出场: EMA20 跟踪止损
    - 初始SL: BB带宽 × 0.35
    """
    positions: list[BTPos] = []
    active: list[BTPos] = []
    total_pnl = 0.0
    wins = 0
    losses = 0
    long_wins = 0
    long_total = 0
    short_wins = 0
    short_total = 0

    prev_k = None
    prev_d = None
    min_bars = BB_PERIOD + 10
    total_bars = len(candles_main)

    for i in range(min_bars, total_bars):
        current = candles_main[i]
        current_close = current["close"]
        current_high = current["high"]
        current_low = current["low"]
        current_time = current["time"]

        closes = [c["close"] for c in candles_main[:i + 1]]
        candles_slice = candles_main[:i + 1]

        # BB
        sma, bandwidth, _ = calc_bb(closes, BB_PERIOD, BB_STD)
        if sma is None or bandwidth is None:
            continue

        upper = sma + bandwidth
        lower = sma - bandwidth
        sl_dist = bandwidth * 0.35

        # Stoch
        stoch = calc_stoch(candles_slice, STOCH_K, STOCH_SLOWING, STOCH_D)
        if stoch is None:
            continue
        p_k, curr_k, p_d, curr_d = stoch

        golden_cross = False
        death_cross = False
        if prev_k is not None and prev_d is not None:
            golden_cross = prev_k <= prev_d and curr_k > curr_d
            death_cross = prev_k >= prev_d and curr_k < curr_d
        prev_k = curr_k
        prev_d = curr_d

        # MACD
        macd_hist, hist_inc = calc_macd(closes)

        # EMA20 for trailing
        ema20 = calc_ema(closes, 20)

        # ====== 出场（EMA20 跟踪止损）======
        closed_positions = []
        still_active = []

        for pos in active:
            is_buy = pos.direction == "BUY"

            # SL
            if pos.sl > 0:
                if is_buy and current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue
                if not is_buy and current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue

            # EMA20 追踪
            if ema20 is not None:
                if is_buy:
                    if ema20 > pos.trail_sl and ema20 < current_close:
                        pos.trail_sl = ema20
                        pos.sl = ema20
                    if current_low <= pos.trail_sl:
                        pos.exit_idx = i
                        pos.exit_price = pos.trail_sl
                        pos.exit_reason = "EMA20_TRAIL"
                        closed_positions.append(pos)
                        continue
                else:
                    if ema20 < pos.trail_sl and ema20 > current_close:
                        pos.trail_sl = ema20
                        pos.sl = ema20
                    if current_high >= pos.trail_sl:
                        pos.exit_idx = i
                        pos.exit_price = pos.trail_sl
                        pos.exit_reason = "EMA20_TRAIL"
                        closed_positions.append(pos)
                        continue

            still_active.append(pos)

        # 结算
        for pos in closed_positions:
            _settle_position(pos)
            total_pnl += pos.pnl
            wins += 1 if pos.pnl > 0 else 0
            losses += 1 if pos.pnl <= 0 else 0
            if pos.direction == "BUY":
                long_total += 1
                long_wins += 1 if pos.pnl > 0 else 0
            else:
                short_total += 1
                short_wins += 1 if pos.pnl > 0 else 0
            positions.append(pos)

        active = still_active

        # ====== 入场 ======
        if len(active) >= 1:
            continue

        signal_dir = None

        # 极端区保护
        in_buy_extreme = curr_k < STOCH_EXTREME_OVERSOLD and curr_d < STOCH_EXTREME_OVERSOLD
        in_sell_extreme = curr_k > STOCH_EXTREME_OVERBOUGHT and curr_d > STOCH_EXTREME_OVERBOUGHT

        if golden_cross and curr_k < STOCH_OVERSOLD:
            if in_sell_extreme:
                continue  # 高位极端区跳过
            # MACD 过滤
            if macd_hist is not None and macd_hist < 0:
                continue
            signal_dir = "BUY"

        elif death_cross and curr_k > STOCH_OVERBOUGHT:
            if in_buy_extreme:
                continue  # 低位极端区跳过
            if macd_hist is not None and macd_hist > 0:
                continue
            signal_dir = "SELL"

        if signal_dir is None:
            continue

        if signal_dir == "BUY":
            sl = round(current_close - sl_dist, 2)
        else:
            sl = round(current_close + sl_dist, 2)

        if sl <= 0:
            continue

        pos = BTPos(
            entry_idx=i,
            entry_price=current_close,
            direction=signal_dir,
            entry_time=current_time,
            sl=sl,
            trail_sl=sl,
        )
        active.append(pos)

    # 最终平仓
    for pos in active:
        last = candles_main[-1]
        if pos.direction == "BUY":
            pos.pnl = (last["close"] - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        else:
            pos.pnl = (pos.entry_price - last["close"]) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        pos.exit_idx = total_bars - 1
        pos.exit_price = last["close"]
        pos.exit_reason = "EXPIRY"
        total_pnl += pos.pnl
        wins += 1 if pos.pnl > 0 else 0
        losses += 1 if pos.pnl <= 0 else 0
        if pos.direction == "BUY":
            long_total += 1
            long_wins += 1 if pos.pnl > 0 else 0
        else:
            short_total += 1
            short_wins += 1 if pos.pnl > 0 else 0
        positions.append(pos)

    return _compute_stats(positions, wins, losses, long_wins, long_total, short_wins, short_total, total_pnl, label)


def run_rsi_bollinger_simple(candles_main: list[dict], label: str = ""):
    """
    RSI Bollinger 简化版（无 M30 RSI 方向过滤）— 作为对比基线
    出场: EMA20 跟踪止损
    """
    positions: list[BTPos] = []
    active: list[BTPos] = []
    total_pnl = 0.0
    wins = 0
    losses = 0
    long_wins = 0
    long_total = 0
    short_wins = 0
    short_total = 0

    min_bars = max(BB_PERIOD, RSI_PERIOD) + 10
    total_bars = len(candles_main)

    for i in range(min_bars, total_bars):
        current = candles_main[i]
        current_close = current["close"]
        current_high = current["high"]
        current_low = current["low"]

        closes = [c["close"] for c in candles_main[:i + 1]]

        sma, bandwidth, _ = calc_bb(closes, BB_PERIOD, BB_STD)
        rsi = calc_rsi(closes, RSI_PERIOD)
        ema20 = calc_ema(closes, 20)

        if sma is None or rsi is None or bandwidth is None:
            continue

        upper = sma + bandwidth
        lower = sma - bandwidth
        sl_dist = bandwidth * 0.35

        # 出场
        closed_positions = []
        still_active = []

        for pos in active:
            is_buy = pos.direction == "BUY"

            if pos.sl > 0:
                if is_buy and current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue
                if not is_buy and current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                    continue

            # EMA20 追踪
            if ema20 is not None:
                if is_buy:
                    if ema20 > pos.trail_sl and ema20 < current_close:
                        pos.trail_sl = ema20
                        pos.sl = ema20
                    if current_low <= pos.trail_sl:
                        pos.exit_idx = i
                        pos.exit_price = pos.trail_sl
                        pos.exit_reason = "EMA20_TRAIL"
                        closed_positions.append(pos)
                        continue
                else:
                    if ema20 < pos.trail_sl and ema20 > current_close:
                        pos.trail_sl = ema20
                        pos.sl = ema20
                    if current_high >= pos.trail_sl:
                        pos.exit_idx = i
                        pos.exit_price = pos.trail_sl
                        pos.exit_reason = "EMA20_TRAIL"
                        closed_positions.append(pos)
                        continue

            still_active.append(pos)

        for pos in closed_positions:
            _settle_position(pos)
            total_pnl += pos.pnl
            wins += 1 if pos.pnl > 0 else 0
            losses += 1 if pos.pnl <= 0 else 0
            if pos.direction == "BUY":
                long_total += 1
                long_wins += 1 if pos.pnl > 0 else 0
            else:
                short_total += 1
                short_wins += 1 if pos.pnl > 0 else 0
            positions.append(pos)

        active = still_active

        # 入场
        if len(active) >= 1:
            continue

        signal_dir = None
        if current_close <= lower and rsi < RSI_OVERSOLD:
            signal_dir = "BUY"
        elif current_close >= upper and rsi > RSI_OVERBOUGHT:
            signal_dir = "SELL"

        if signal_dir is None:
            continue

        if signal_dir == "BUY":
            sl = round(current_close - sl_dist, 2)
        else:
            sl = round(current_close + sl_dist, 2)

        if sl <= 0:
            continue

        active.append(BTPos(
            entry_idx=i, entry_price=current_close,
            direction=signal_dir, sl=sl, trail_sl=sl,
        ))

    # 最终平仓
    for pos in active:
        last = candles_main[-1]
        if pos.direction == "BUY":
            pos.pnl = (last["close"] - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        else:
            pos.pnl = (pos.entry_price - last["close"]) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        pos.exit_idx = total_bars - 1
        pos.exit_price = last["close"]
        pos.exit_reason = "EXPIRY"
        total_pnl += pos.pnl
        wins += 1 if pos.pnl > 0 else 0
        losses += 1 if pos.pnl <= 0 else 0
        if pos.direction == "BUY":
            long_total += 1
            long_wins += 1 if pos.pnl > 0 else 0
        else:
            short_total += 1
            short_wins += 1 if pos.pnl > 0 else 0
        positions.append(pos)

    return _compute_stats(positions, wins, losses, long_wins, long_total, short_wins, short_total, total_pnl, label)


def _settle_position(pos: BTPos):
    if pos.direction == "BUY":
        pos.pnl = (pos.exit_price - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
    else:
        pos.pnl = (pos.entry_price - pos.exit_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION


def _compute_stats(positions, wins, losses, long_wins, long_total, short_wins, short_total, total_pnl, label):
    total_trades = wins + losses
    win_pnls = [p.pnl for p in positions if p.pnl > 0]
    loss_pnls = [p.pnl for p in positions if p.pnl <= 0]
    avg_win = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0
    gross_profit = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999

    peak = 0.0
    max_dd = 0.0
    running = 0.0
    for p in positions:
        running += p.pnl
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    return {
        "label": label,
        "trades": total_trades,
        "pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
        "long_wr": round(long_wins / long_total * 100, 1) if long_total > 0 else 0,
        "short_wr": round(short_wins / short_total * 100, 1) if short_total > 0 else 0,
        "long_trades": long_total,
        "short_trades": short_total,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_dd": round(max_dd, 2),
    }


# ======================== Main ========================

def main():
    print("=" * 80)
    print("时间周期对比回测 — 使用真实策略逻辑")
    print("读取自 SQLite 数据库: data/market_data.db")
    print("=" * 80)

    # 读取数据
    print("\n读取 M30, H1, H4 数据...")
    candles_m30 = get_candles("M30", limit=2000)
    candles_h1 = get_candles("H1", limit=1000)
    candles_h4 = get_candles("H4", limit=800)

    print(f"  M30: {len(candles_m30)} bars, {datetime.fromtimestamp(candles_m30[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(candles_m30[-1]['time']).strftime('%Y-%m-%d')}")
    print(f"  H1:  {len(candles_h1)} bars, {datetime.fromtimestamp(candles_h1[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(candles_h1[-1]['time']).strftime('%Y-%m-%d')}")
    print(f"  H4:  {len(candles_h4)} bars, {datetime.fromtimestamp(candles_h4[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(candles_h4[-1]['time']).strftime('%Y-%m-%d')}")

    all_results = []

    # ============ RSI Bollinger 对比 ============
    print("\n" + "-" * 80)
    print("RSI Bollinger 回测对比")
    print("-" * 80)

    # RSI on H1 (真实策略: M30 RSI方向过滤 + M30 RSI反转出场)
    print("\n1) RSI Bollinger on H1 (真实策略: M30 RSI方向过滤 + M30 RSI反转出场)...")
    r1 = run_rsi_bollinger_backtest(candles_h1, "H1", candles_m30, "RSIBB_H1_真实")
    all_results.append(r1)
    _print_result(r1)

    # RSI on M30 (真实策略: M30 RSI方向过滤 + M30 RSI反转出场)
    print("2) RSI Bollinger on M30 (真实策略)...")
    r2 = run_rsi_bollinger_backtest(candles_m30, "M30", candles_m30, "RSIBB_M30_真实")
    all_results.append(r2)
    _print_result(r2)

    # RSI on H1 (简化版: 无M30过滤, EMA20出场 — 旧版对比基线)
    print("3) RSI Bollinger on H1 (简化版: 无M30过滤 + EMA20出场)...")
    r3 = run_rsi_bollinger_simple(candles_h1, "RSIBB_H1_简化")
    all_results.append(r3)
    _print_result(r3)

    # RSI on M30 (简化版)
    print("4) RSI Bollinger on M30 (简化版: 无M30过滤 + EMA20出场)...")
    r4 = run_rsi_bollinger_simple(candles_m30, "RSIBB_M30_简化")
    all_results.append(r4)
    _print_result(r4)

    # ============ Stoch Bollinger 对比 ============
    print("\n" + "-" * 80)
    print("Stoch Bollinger 回测对比")
    print("-" * 80)

    # Stoch on H4 (真实策略: MACD过滤 + 极端区保护 + EMA20出场)
    print("\n5) Stoch Bollinger on H4 (真实策略: MACD过滤 + 极端区保护 + EMA20出场)...")
    r5 = run_stoch_bollinger_backtest(candles_h4, "H4", "Stoch_H4_真实")
    all_results.append(r5)
    _print_result(r5)

    # Stoch on H1 (真实策略)
    print("6) Stoch Bollinger on H1 (真实策略)...")
    r6 = run_stoch_bollinger_backtest(candles_h1, "H1", "Stoch_H1_真实")
    all_results.append(r6)
    _print_result(r6)

    # ============ 摘要对比 ============
    print("\n" + "=" * 80)
    print("关键对比")
    print("=" * 80)

    print("""
【RSI Bollinger 周期对比】
  M30 vs H1（真实策略，M30 RSI方向过滤 + M30 RSI反转出场）:
""")
    for r in all_results:
        if "RSIBB" in r["label"]:
            print(f"  {r['label']:20s}  交易={r['trades']:>3}  盈亏=${r['pnl']:>8.2f}  胜率={r['win_rate']:>5.1f}%  均赢=${r['avg_win']:>6.0f}  均亏=${r['avg_loss']:>6.0f}  盈亏比={r['profit_factor']:>5.1f}  最大回撤=${r['max_dd']:>7.0f}")

    print("""
【Stoch Bollinger 周期对比】
  H1 vs H4（真实策略，MACD过滤 + 极端区保护 + EMA20出场）:
""")
    for r in all_results:
        if "Stoch" in r["label"]:
            print(f"  {r['label']:20s}  交易={r['trades']:>3}  盈亏=${r['pnl']:>8.2f}  胜率={r['win_rate']:>5.1f}%  均赢=${r['avg_win']:>6.0f}  均亏=${r['avg_loss']:>6.0f}  盈亏比={r['profit_factor']:>5.1f}  最大回撤=${r['max_dd']:>7.0f}")

    # 写入报告
    _write_report(all_results, candles_m30, candles_h1, candles_h4)


def _print_result(r):
    print(f"     交易={r['trades']}  盈亏=${r['pnl']}  胜率={r['win_rate']}%  "
          f"多{r['long_trades']}({r['long_wr']}%)/空{r['short_trades']}({r['short_wr']}%)  "
          f"均赢=${r['avg_win']}/均亏=${r['avg_loss']}  "
          f"盈亏比={r['profit_factor']}  最大回撤=${r['max_dd']}")


def _write_report(results, m30, h1, h4):
    lines = []
    lines.append("# 时间周期对比回测结果\n")
    lines.append(f"**生成日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**数据源**: SQLite data/market_data.db\n")
    lines.append(f"- M30: {len(m30)} 根 | {datetime.fromtimestamp(m30[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(m30[-1]['time']).strftime('%Y-%m-%d')}")
    lines.append(f"- H1:  {len(h1)} 根 | {datetime.fromtimestamp(h1[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(h1[-1]['time']).strftime('%Y-%m-%d')}")
    lines.append(f"- H4:  {len(h4)} 根 | {datetime.fromtimestamp(h4[0]['time']).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(h4[-1]['time']).strftime('%Y-%m-%d')}")
    lines.append("")

    lines.append("---\n")
    lines.append("## 全部结果\n")
    lines.append("| 方案 | 周期 | 交易 | 盈亏 | 胜率 | 多(胜率) | 空(胜率) | 均赢 | 均亏 | 盈亏比 | 最大回撤 |")
    lines.append("|------|------|------|------|------|----------|----------|------|------|--------|----------|")

    for r in sorted(results, key=lambda r: -r["win_rate"]):
        wr_badge = " ⭐" if r["win_rate"] >= 60 else ""
        lines.append(
            f"| {r['label']} | - | {r['trades']} "
            f"| ${r['pnl']} | {r['win_rate']}%{wr_badge} "
            f"| {r['long_trades']}({r['long_wr']}%) | {r['short_trades']}({r['short_wr']}%) "
            f"| ${r['avg_win']} | ${r['avg_loss']} | {r['profit_factor']} | ${r['max_dd']} |"
        )
    lines.append("")

    lines.append("---\n")
    lines.append("## RSI Bollinger — M30 vs H1\n")
    for r in results:
        if "RSIBB" in r["label"]:
            wr_badge = " ⭐" if r["win_rate"] >= 60 else ""
            lines.append(f"- **{r['label']}**: {r['trades']}笔, ${r['pnl']}盈亏, {r['win_rate']}%胜率{wr_badge}, 盈亏比{r['profit_factor']}, 最大回撤${r['max_dd']}")
    lines.append("")

    lines.append("## Stoch Bollinger — H1 vs H4\n")
    for r in results:
        if "Stoch" in r["label"]:
            wr_badge = " ⭐" if r["win_rate"] >= 60 else ""
            lines.append(f"- **{r['label']}**: {r['trades']}笔, ${r['pnl']}盈亏, {r['win_rate']}%胜率{wr_badge}, 盈亏比{r['profit_factor']}, 最大回撤${r['max_dd']}")
    lines.append("")

    lines.append("---\n")
    lines.append("## 关键发现\n")
    lines.append("### RSI Bollinger\n")
    rsi_results = [r for r in results if "RSIBB" in r["label"]]
    if rsi_results:
        best_rsi_pnl = max(rsi_results, key=lambda r: r["pnl"])
        best_rsi_wr = max(rsi_results, key=lambda r: r["win_rate"])
        lines.append(f"- 最高盈亏: **{best_rsi_pnl['label']}** → ${best_rsi_pnl['pnl']} ({best_rsi_pnl['trades']}笔, {best_rsi_pnl['win_rate']}%胜率)")
        lines.append(f"- 最高胜率: **{best_rsi_wr['label']}** → {best_rsi_wr['win_rate']}% (${best_rsi_wr['pnl']})")

        # 对比 M30 vs H1（真实策略）
        m30_real = next((r for r in rsi_results if "M30_真实" in r["label"]), None)
        h1_real = next((r for r in rsi_results if "H1_真实" in r["label"]), None)
        if m30_real and h1_real:
            lines.append(f"\n**M30 vs H1 (真实策略)**:")
            diff_pnl = m30_real["pnl"] - h1_real["pnl"]
            diff_wr = m30_real["win_rate"] - h1_real["win_rate"]
            lines.append(f"- 盈亏差异: ${diff_pnl:+.2f} (M30{'更好' if diff_pnl > 0 else '更差'})")
            lines.append(f"- 胜率差异: {diff_wr:+.1f}% (M30{'更高' if diff_wr > 0 else '更低'})")

        # M30 RSI方向过滤 影响
        h1_real = next((r for r in rsi_results if "H1_真实" in r["label"]), None)
        h1_simple = next((r for r in rsi_results if "H1_简化" in r["label"]), None)
        if h1_real and h1_simple:
            lines.append(f"\n**M30 RSI方向过滤效果 (H1 真实 vs 简化):**")
            lines.append(f"- 真实(有过滤): {h1_real['trades']}笔 ${h1_real['pnl']} {h1_real['win_rate']}%")
            lines.append(f"- 简化(无过滤): {h1_simple['trades']}笔 ${h1_simple['pnl']} {h1_simple['win_rate']}%")
            lines.append(f"- 过滤减少 {h1_simple['trades'] - h1_real['trades']} 笔交易, 胜率变化 {h1_real['win_rate'] - h1_simple['win_rate']:+.1f}%")

    lines.append("")
    lines.append("### Stoch Bollinger\n")
    stoch_results = [r for r in results if "Stoch" in r["label"]]
    if stoch_results:
        best_stoch_pnl = max(stoch_results, key=lambda r: r["pnl"])
        best_stoch_wr = max(stoch_results, key=lambda r: r["win_rate"])
        lines.append(f"- 最高盈亏: **{best_stoch_pnl['label']}** → ${best_stoch_pnl['pnl']} ({best_stoch_pnl['trades']}笔, {best_stoch_pnl['win_rate']}%胜率)")
        lines.append(f"- 最高胜率: **{best_stoch_wr['label']}** → {best_stoch_wr['win_rate']}% (${best_stoch_wr['pnl']})")

        h4_r = next((r for r in stoch_results if "H4" in r["label"]), None)
        h1_r = next((r for r in stoch_results if "H1" in r["label"]), None)
        if h4_r and h1_r:
            lines.append(f"\n**H1 vs H4 对比:**")
            diff_pnl = h1_r["pnl"] - h4_r["pnl"]
            diff_wr = h1_r["win_rate"] - h4_r["win_rate"]
            lines.append(f"- 盈亏差异: ${diff_pnl:+.2f} (H1{'更好' if diff_pnl > 0 else '更差'})")
            lines.append(f"- 胜率差异: {diff_wr:+.1f}% (H1{'更高' if diff_wr > 0 else '更低'})")
            lines.append(f"- H1: {h1_r['trades']}笔 ${h1_r['pnl']} {h1_r['win_rate']}%")
            lines.append(f"- H4: {h4_r['trades']}笔 ${h4_r['pnl']} {h4_r['win_rate']}%")

    lines.append("")
    lines.append("# 结论\n")
    lines.append("待分析...\n")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
