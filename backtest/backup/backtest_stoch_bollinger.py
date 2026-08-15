"""
Stoch + 布林带策略回测 — 多配置对比
各配置独立回测，最后汇总比较
"""

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal

from core.bridge import create_bridge, OrderType

# ============================================================
# 策略参数
# ============================================================
STOCH_K = 8
STOCH_SLOWING = 3
STOCH_D = 3
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80
BB_PERIOD = 20
BB_STD = 2.0
ADD_THRESHOLDS = [2, 5, 8, 13]
STOCH_EXIT_PEAK_THRESHOLD = 3
STOCH_EXIT_RATIO_STRONG = 0.382
ATR_PERIOD = 14

LOT_SIZE = 0.01
CONTRACT_SIZE = 100
MAX_POSITIONS = 5
COMMISSION = 0.5

# SL 模式定义
SLMode = Literal["bb_035", "bb_05", "atr_20", "none"]


@dataclass
class BacktestPosition:
    entry_idx: int
    entry_price: float
    direction: OrderType
    sl: float
    entry_k: float
    ticket: int
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    peak_diff: float = 0.0


# ============================================================
# Stoch / BB / ATR 计算
# ============================================================
def calc_stoch(candles, k_period, slowing, d_period):
    n = len(candles)
    min_needed = k_period + slowing + d_period + 1
    if n < min_needed:
        return None
    raw_k = []
    for i in range(k_period - 1, n):
        window = candles[i - k_period + 1 : i + 1]
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        close = window[-1].close
        if highest == lowest:
            raw_k.append(50.0)
        else:
            raw_k.append((close - lowest) / (highest - lowest) * 100)

    if len(raw_k) < slowing + d_period + 1:
        return None
    smooth_k = []
    for i in range(slowing - 1, len(raw_k)):
        val = sum(raw_k[i - slowing + 1 : i + 1]) / slowing
        smooth_k.append(val)
    if len(smooth_k) < d_period + 1:
        return None
    curr_k = smooth_k[-1]
    prev_k = smooth_k[-2]
    curr_d = sum(smooth_k[-d_period:]) / d_period
    prev_d = sum(smooth_k[-(d_period + 1):-1]) / d_period
    return prev_k, curr_k, prev_d, curr_d


def calc_bb(candles, period, std_mult):
    if len(candles) < period:
        return None, None
    closes = [c.close for c in candles[-period:]]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    std = math.sqrt(variance)
    return sma, std * std_mult


def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(len(candles) - period, len(candles)):
        if i == 0:
            continue
        curr = candles[i]
        prev = candles[i - 1]
        tr = max(float(curr.high) - float(curr.low),
                 abs(float(curr.high) - float(prev.close)),
                 abs(float(curr.low) - float(prev.close)))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


# ============================================================
# 回测主逻辑
# ============================================================
def run_backtest(candles, sl_mode: SLMode, extreme_entry: bool):
    positions: list[BacktestPosition] = []
    active: list[BacktestPosition] = []
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    next_ticket = 1000

    prev_k: Optional[float] = None
    prev_d: Optional[float] = None

    buy_extreme = False
    sell_extreme = False

    # SL 倍数映射
    sl_params = {
        "bb_035": ("bb", 0.35),
        "bb_05":  ("bb", 0.5),
        "atr_20": ("atr", 2.0),
        "none":   ("none", 0),
    }
    sl_type, sl_mult = sl_params[sl_mode]

    min_bars = STOCH_K + STOCH_SLOWING + STOCH_D + 5

    for i in range(min_bars, len(candles)):
        current = candles[i]
        current_close = float(current.close)
        current_high = float(current.high)
        current_low = float(current.low)

        # -- Stoch --
        stoch = calc_stoch(candles[:i+1], STOCH_K, STOCH_SLOWING, STOCH_D)
        if stoch is None:
            continue
        p_k, curr_k, p_d, curr_d = stoch

        golden_cross = False
        death_cross = False
        if prev_k is not None and prev_d is not None:
            golden_cross = prev_k <= prev_d and curr_k > curr_d
            death_cross = prev_k >= prev_d and curr_k < curr_d
        prev_k, prev_d = curr_k, curr_d

        # -- SL 计算（全配置统一，用于出场检查）--
        if sl_type == "bb":
            _, bandwidth = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
            if bandwidth is not None:
                sl_distance = bandwidth * sl_mult
            else:
                sl_distance = None
        elif sl_type == "atr":
            sl_distance_raw = calc_atr(candles[:i+1], ATR_PERIOD)
            if sl_distance_raw is not None:
                sl_distance = sl_distance_raw * sl_mult
            else:
                sl_distance = None
        else:  # none
            sl_distance = None

        # -- 出场检查 --
        closed_positions = []
        still_active = []

        for pos in active:
            is_buy = pos.direction == OrderType.BUY

            # SL 检查
            if sl_distance is not None:
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

            # K-D 衰减出场（含极端区保护）
            curr_diff = curr_k - curr_d if is_buy else curr_d - curr_k
            if curr_diff < 0:
                curr_diff = 0

            if is_buy and pos.entry_k < STOCH_OVERSOLD and curr_k < STOCH_OVERSOLD and curr_d < STOCH_OVERSOLD:
                still_active.append(pos)
                continue
            if not is_buy and pos.entry_k > STOCH_OVERBOUGHT and curr_k > STOCH_OVERBOUGHT and curr_d > STOCH_OVERBOUGHT:
                still_active.append(pos)
                continue

            if curr_diff > pos.peak_diff:
                pos.peak_diff = curr_diff

            should_exit = False
            if pos.peak_diff > 0:
                if pos.peak_diff <= STOCH_EXIT_PEAK_THRESHOLD:
                    if curr_diff == 0:
                        should_exit = True
                else:
                    if curr_diff < pos.peak_diff * STOCH_EXIT_RATIO_STRONG:
                        should_exit = True

            if should_exit:
                pos.exit_idx = i
                pos.exit_price = current_close
                pos.exit_reason = "KD_EXIT"
                closed_positions.append(pos)
            else:
                still_active.append(pos)

        # 结算
        for pos in closed_positions:
            if pos.direction == OrderType.BUY:
                pos.pnl = (pos.exit_price - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
            else:
                pos.pnl = (pos.entry_price - pos.exit_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
            total_pnl += pos.pnl
            total_trades += 1
            if pos.pnl > 0:
                wins += 1
            else:
                losses += 1
            positions.append(pos)
        active = still_active

        # -- 入场/加仓 --
        if len(active) >= MAX_POSITIONS:
            continue

        n_longs = sum(1 for p in active if p.direction == OrderType.BUY)
        n_shorts = sum(1 for p in active if p.direction == OrderType.SELL)
        signal = None
        signal_direction = None

        in_buy_extreme = curr_k < STOCH_OVERSOLD and curr_d < STOCH_OVERSOLD
        in_sell_extreme = curr_k > STOCH_OVERBOUGHT and curr_d > STOCH_OVERBOUGHT

        if n_longs > 0 and n_shorts == 0:
            if extreme_entry and in_buy_extreme:
                buy_extreme = True
                if golden_cross and n_longs < MAX_POSITIONS:
                    signal = "X_BUY"
                    signal_direction = OrderType.BUY
            else:
                buy_extreme = False
                if n_longs < len(ADD_THRESHOLDS):
                    diff = curr_k - curr_d
                    if diff >= ADD_THRESHOLDS[n_longs - 1]:
                        signal = "ADD_BUY"
                        signal_direction = OrderType.BUY
        elif n_shorts > 0 and n_longs == 0:
            if extreme_entry and in_sell_extreme:
                sell_extreme = True
                if death_cross and n_shorts < MAX_POSITIONS:
                    signal = "X_SELL"
                    signal_direction = OrderType.SELL
            else:
                sell_extreme = False
                if n_shorts < len(ADD_THRESHOLDS):
                    diff = curr_d - curr_k
                    if diff >= ADD_THRESHOLDS[n_shorts - 1]:
                        signal = "ADD_SELL"
                        signal_direction = OrderType.SELL
        else:
            buy_extreme = sell_extreme = False
            if golden_cross and curr_k < STOCH_OVERSOLD:
                signal = "BUY"
                signal_direction = OrderType.BUY
                buy_extreme = True
            elif death_cross and curr_k > STOCH_OVERBOUGHT:
                signal = "SELL"
                signal_direction = OrderType.SELL
                sell_extreme = True

        if signal in ("BUY", "SELL", "X_BUY", "X_SELL"):
            if signal_direction == OrderType.BUY:
                buy_extreme = True
            else:
                sell_extreme = True

        if signal is None or signal_direction is None:
            continue

        # 计算 SL
        if sl_type == "bb":
            _, bandwidth = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
            if bandwidth is None:
                continue
            dist = bandwidth * sl_mult
        elif sl_type == "atr":
            dist_raw = calc_atr(candles[:i+1], ATR_PERIOD)
            if dist_raw is None:
                continue
            dist = dist_raw * sl_mult
        else:
            dist = None

        if signal_direction == OrderType.BUY:
            sl = round(current_close - dist, 2) if dist is not None else 0.0
        else:
            sl = round(current_close + dist, 2) if dist is not None else 99999.0

        if sl <= 0 and sl_type != "none":
            continue

        pos = BacktestPosition(
            entry_idx=i,
            entry_price=current_close,
            direction=signal_direction,
            sl=sl,
            entry_k=curr_k,
            ticket=next_ticket,
        )
        next_ticket += 1
        is_buy = signal_direction == OrderType.BUY
        pos.peak_diff = curr_k - curr_d if is_buy else curr_d - curr_k
        if pos.peak_diff < 0:
            pos.peak_diff = 0
        active.append(pos)

    # 最终平仓
    for pos in active:
        last = candles[-1]
        if pos.direction == OrderType.BUY:
            pos.pnl = (last.close - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        else:
            pos.pnl = (pos.entry_price - last.close) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
        pos.exit_idx = len(candles) - 1
        pos.exit_price = last.close
        pos.exit_reason = "EXPIRY"
        total_pnl += pos.pnl
        total_trades += 1
        if pos.pnl > 0:
            wins += 1
        else:
            losses += 1
        positions.append(pos)

    return positions, total_pnl, total_trades, wins, losses


# ============================================================
# 汇总
# ============================================================
def summarize(label, positions, total_pnl, total_trades, wins, losses):
    if total_trades == 0:
        return {"label": label, "trades": 0, "pnl": 0, "win_rate": 0, "max_dd": 0, "sl_cnt": 0, "kd_cnt": 0}

    win_rate = wins / total_trades * 100
    closed = [p for p in positions if p.exit_reason != "EXPIRY"]
    sl_count = sum(1 for p in closed if p.exit_reason == "SL")
    kd_count = sum(1 for p in closed if p.exit_reason == "KD_EXIT")

    equity = [10000.0]
    for p in positions:
        equity.append(equity[-1] + p.pnl)
    peak = equity[0]
    max_dd = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "label": label, "trades": total_trades, "pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1), "max_dd": round(max_dd, 2),
        "sl_cnt": sl_count, "kd_cnt": kd_count,
    }


def print_table(results, start_time, end_time, tf_label):
    print(f"\n{'='*90}")
    print(f"[{tf_label}] Stoch + 布林带 多配置回测对比")
    print(f"数据: {start_time} ~ {end_time}")
    print(f"{'='*90}")
    print(f"{'配置':<32} {'交易':>5} {'总盈亏':>9} {'胜率':>6} {'最大回撤':>7} {'SL':>4} {'KD出场':>6}")
    print(f"{'-'*90}")

    best_pnl = max(r["pnl"] for r in results)
    for r in results:
        marker = " <--" if r["pnl"] == best_pnl else ""
        print(f"{r['label']:<32} {r['trades']:>5}  ${r['pnl']:>8.2f} {r['win_rate']:>5.1f}% {r['max_dd']:>6.2f}% {r['sl_cnt']:>4} {r['kd_cnt']:>6}{marker}")
    print(f"{'='*90}")


def run_configs(candles):
    configs = [
        ("bb_035", False, "BB×0.35 SL + 旧入场"),
        ("bb_05",  False, "BB×0.5  SL + 旧入场"),
        ("atr_20", False, "ATR×2.0 SL + 旧入场"),
        ("none",   False, "无SL + 旧入场"),
        ("bb_035", True,  "BB×0.35 SL + 极端区入场"),
        ("none",   True,  "无SL + 极端区入场"),
    ]
    results = []
    for sl_mode, extreme_entry, label in configs:
        positions, total_pnl, total_trades, wins, losses = \
            run_backtest(candles, sl_mode, extreme_entry)
        r = summarize(label, positions, total_pnl, total_trades, wins, losses)
        results.append(r)
        print(f"  {label:<30} 交易={r['trades']:>4}  盈亏=${r['pnl']:>8.2f}")
    return results


# ============================================================
# 主入口
# ============================================================
def main():
    print("连接 MT4 获取历史数据...")
    bridge = create_bridge()
    if not bridge.connect():
        print("MT4 连接失败!")
        sys.exit(1)

    info = bridge.get_account_info()
    if info:
        print(f"账户: #{info.login}")

    timeframes = ["M15", "M30", "H1", "H4", "D1"]

    # 先取 H4 1000 根确定统一的日期范围
    h4_raw = bridge.get_candles("XAUUSD", "H4", 1000)
    h4_candles = list(reversed(h4_raw))
    h4_start_ts = int(h4_candles[0].time)
    h4_end_ts = int(h4_candles[-1].time)
    h4_start_dt = datetime.fromtimestamp(h4_start_ts)
    h4_end_dt = datetime.fromtimestamp(h4_end_ts)
    print(f"\nH4 基准范围: {h4_start_dt.strftime('%Y-%m-%d')} ~ {h4_end_dt.strftime('%Y-%m-%d')}")

    # 各周期需要的额外根数（按 K 线时长比例放大 + 缓冲）
    # H4=240min, H1=60min, M30=30min, M15=15min, D1=1440min
    tf_buffer = {
        "M15": 16000,  # H4 范围约 240k min → M15 约 16000 根，多取一些
        "M30": 8000,
        "H1":  4000,
        "H4":  1000,
        "D1":  500,
    }

    all_data = {}
    for tf in timeframes:
        count = tf_buffer[tf]
        raw = bridge.get_candles("XAUUSD", tf, count)
        candles = list(reversed(raw))
        # 过滤到 H4 同一日期范围
        candles = [c for c in candles if h4_start_ts <= int(c.time) <= h4_end_ts]
        if not candles:
            print(f"  {tf}: 范围内无数据!")
            continue
        start = datetime.fromtimestamp(int(candles[0].time))
        end = datetime.fromtimestamp(int(candles[-1].time))
        all_data[tf] = {
            "candles": candles,
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "count": len(candles),
        }
        print(f"  {tf}: {len(candles)} 根  {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")

    # 确保所有周期在同一个范围内
    print(f"\n统一数据范围: {h4_start_dt.strftime('%Y-%m-%d')} ~ {h4_end_dt.strftime('%Y-%m-%d')}")

    bridge.disconnect()

    # 对每个周期跑全部配置
    for tf in timeframes:
        d = all_data[tf]
        print(f"\n{'='*70}")
        print(f">>> [{tf}] {d['count']}根K线  {d['start']} ~ {d['end']}")
        results = run_configs(d["candles"])
        print_table(results, d["start"], d["end"], tf)

    # 跨周期汇总：只对比 BB×0.35 SL + 旧入场
    print(f"\n\n{'='*90}")
    print("跨周期汇总 — BB×0.35 SL + 旧入场（统一时间范围）")
    print(f"{'='*90}")
    print(f"{'周期':<8} {'K线数':>6} {'数据范围':<24} {'交易':>5} {'总盈亏':>9} {'胜率':>6} {'最大回撤':>7} {'SL':>4} {'KD出场':>6}")
    print(f"{'-'*90}")
    for tf in timeframes:
        d = all_data[tf]
        # 只跑一次 BB×0.35 + 旧入场
        positions, pnl, trades, wins, losses = \
            run_backtest(d["candles"], "bb_035", False)
        r = summarize(tf, positions, pnl, trades, wins, losses)
        date_range = f"{d['start']}~{d['end']}"
        print(f"{tf:<8} {d['count']:>6} {date_range:<24} {r['trades']:>5}  ${r['pnl']:>8.2f} "
              f"{r['win_rate']:>5.1f}% {r['max_dd']:>6.2f}% {r['sl_cnt']:>4} {r['kd_cnt']:>6}")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
