"""
H1 全策略回测对比 — 双均线 / ATR突破 / 组合 / RSI布林带 / Stoch布林带
"""

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.bridge import create_bridge, OrderType

# ============================================================
# 常量
# ============================================================
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14
RSI_PERIOD = 14
STOCH_K = 8
STOCH_SLOWING = 3
STOCH_D = 3

LOT_SIZE = 0.01
CONTRACT_SIZE = 100
COMMISSION = 0.5

OUTPUT_FILE = "backtest/h1_all_results.md"


@dataclass
class BTPos:
    entry_idx: int
    entry_price: float
    direction: OrderType
    sl: float
    tp: float
    entry_k: float = 0.0
    exit_idx: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    peak_diff: float = 0.0


# ============================================================
# 指标计算
# ============================================================
def calc_stoch(candles, k_period, slowing, d_period):
    n = len(candles)
    min_needed = k_period + slowing + d_period + 1
    if n < min_needed:
        return None
    raw_k = []
    for i in range(k_period - 1, n):
        window = candles[i - k_period + 1: i + 1]
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
        val = sum(raw_k[i - slowing + 1: i + 1]) / slowing
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
        return None, None, None
    closes = [c.close for c in candles[-period:]]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    std = math.sqrt(variance)
    return sma, std * std_mult, std


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


def calc_ema(candles, period: int) -> Optional[float]:
    closes = [c.close for c in candles]
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema) * k + ema
    return ema


def calc_rsi(candles, period=14):
    if len(candles) < period + 1:
        return None
    closes = [c.close for c in candles]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if period < len(gains):
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_sma(candles, period: int) -> Optional[float]:
    closes = [c.close for c in candles]
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


# ============================================================
# 信号函数：每个策略一个
# 参数: (candles, i, prev_state) -> (signal, direction) or None
# ============================================================

def signal_double_ma(candles, i, state):
    """双均线: EMA快线上穿→BUY, EMA快线下穿→SELL"""
    ma_fast = state.get("ma_fast", 20)
    ma_slow = state.get("ma_slow", 60)

    if i < ma_slow + 1:
        return None

    curr_fast = calc_ema(candles[:i+1], ma_fast)
    curr_slow = calc_ema(candles[:i+1], ma_slow)
    prev_fast = calc_ema(candles[:i], ma_fast)
    prev_slow = calc_ema(candles[:i], ma_slow)

    if curr_fast is None or curr_slow is None or prev_fast is None or prev_slow is None:
        return None

    prev_cross = prev_fast - prev_slow
    curr_cross = curr_fast - curr_slow

    if prev_cross <= 0 and curr_cross > 0:
        return ("BUY", OrderType.BUY)
    if prev_cross >= 0 and curr_cross < 0:
        return ("SELL", OrderType.SELL)
    return None


def signal_atr_breakout(candles, i, state):
    """ATR 通道突破: 价格突破N期最高→BUY, 跌破N期最低→SELL"""
    breakout = state.get("breakout_period", 20)

    if i < breakout + 1:
        return None

    current_close = float(candles[i].close)
    prev_close = float(candles[i - 1].close)

    # 前一根K线收盘已确认的突破
    lookback = candles[i - breakout:i]  # i 之前的情况用 i-1
    highest = max(float(c.high) for c in lookback[:-1])  # N-1 根的最高
    lowest = min(float(c.low) for c in lookback[:-1])

    # 用前一根收盘确认突破（当前K线尚未收）
    if prev_close > highest:
        return ("BUY", OrderType.BUY)
    if prev_close < lowest:
        return ("SELL", OrderType.SELL)
    return None


def signal_combined(candles, i, state):
    """双均线 + ATR 双重确认"""
    if i < 70:
        return None

    s_ma = signal_double_ma(candles, i, state)
    if s_ma is None:
        return None

    s_atr = signal_atr_breakout(candles, i, state)
    if s_atr is None:
        return None

    if s_ma[1] == s_atr[1]:
        return s_ma
    return None


def signal_rsi_bollinger(candles, i, state):
    """RSI + 布林带: 价格触轨 + RSI 确认"""
    period = state.get("bb_period", BB_PERIOD)
    rsi_period = state.get("rsi_period", RSI_PERIOD)
    oversold = state.get("rsi_oversold", 30)
    overbought = state.get("rsi_overbought", 70)

    if i < max(period, rsi_period) + 5:
        return None

    sma, bandwidth, std_val = calc_bb(candles[:i+1], period, BB_STD)
    rsi = calc_rsi(candles[:i+1], rsi_period)
    if sma is None or rsi is None or bandwidth is None:
        return None

    current_close = float(candles[i].close)
    lower = sma - bandwidth
    upper = sma + bandwidth

    if current_close <= lower and rsi < oversold:
        return ("BUY", OrderType.BUY)
    if current_close >= upper and rsi > overbought:
        return ("SELL", OrderType.SELL)
    return None


def signal_stoch_bollinger(candles, i, state):
    """Stoch + 布林带: 超卖金叉/超买死叉"""
    oversold = state.get("stoch_oversold", 20)
    overbought = state.get("stoch_overbought", 80)
    k_period = state.get("stoch_k", STOCH_K)
    slowing = state.get("stoch_slowing", STOCH_SLOWING)
    d_period = state.get("stoch_d", STOCH_D)

    stoch = calc_stoch(candles[:i+1], k_period, slowing, d_period)
    if stoch is None:
        return None
    p_k, curr_k, p_d, curr_d = stoch

    prev_k = state.get("prev_k")
    prev_d = state.get("prev_d")

    golden = False
    death = False
    if prev_k is not None and prev_d is not None:
        golden = prev_k <= prev_d and curr_k > curr_d
        death = prev_k >= prev_d and curr_k < curr_d

    state["prev_k"] = curr_k
    state["prev_d"] = curr_d
    state["curr_k"] = curr_k
    state["curr_d"] = curr_d

    if golden and curr_k < oversold:
        return ("BUY", OrderType.BUY)
    if death and curr_k > overbought:
        return ("SELL", OrderType.SELL)
    return None


# ============================================================
# 通用回测引擎
# ============================================================
class VariantConfig:
    def __init__(self, label: str, strategy: str, **kwargs):
        self.label = label
        self.strategy = strategy
        self.max_positions: int = kwargs.get("max_positions", 1)
        self.exit_mode: str = kwargs.get("exit_mode", "ma_trail")
        self.sl_mode: str = kwargs.get("sl_mode", "bb_035")
        self.exit_rr: float = kwargs.get("exit_rr", 2.0)
        self.signal_params: dict = kwargs.get("signal_params", {})

    def __repr__(self):
        return f"Variant({self.label})"


SIGNAL_REGISTRY = {
    "double_ma": signal_double_ma,
    "atr_breakout": signal_atr_breakout,
    "combined": signal_combined,
    "rsi_bollinger": signal_rsi_bollinger,
    "stoch_bollinger": signal_stoch_bollinger,
}


def run_variant(candles, config: VariantConfig):
    signal_fn = SIGNAL_REGISTRY[config.strategy]
    positions: list[BTPos] = []
    active: list[BTPos] = []
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    long_wins = 0
    long_total = 0
    short_wins = 0
    short_total = 0

    state = {}
    state.update(config.signal_params)
    min_bars = 200

    for i in range(min_bars, len(candles)):
        current = candles[i]
        current_close = float(current.close)
        current_high = float(current.high)
        current_low = float(current.low)

        # SL 距离
        _, bandwidth, _ = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
        sl_distance = bandwidth * 0.35 if bandwidth else None

        # === 出场检查 ===
        closed_positions = []
        still_active = []

        for pos in active:
            is_buy = pos.direction == OrderType.BUY

            # 基本 SL 检查
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

            # TP 检查 (fixed_rr 模式)
            if config.exit_mode == "fixed_rr" and pos.tp > 0:
                if is_buy and current_high >= pos.tp:
                    pos.exit_idx = i
                    pos.exit_price = pos.tp
                    pos.exit_reason = "TP"
                    closed_positions.append(pos)
                    continue
                if not is_buy and current_low <= pos.tp:
                    pos.exit_idx = i
                    pos.exit_price = pos.tp
                    pos.exit_reason = "TP"
                    closed_positions.append(pos)
                    continue

            # === 移动止损 ===
            if config.exit_mode == "ma_trail":
                ema20 = calc_ema(candles[:i+1], 20)
                if ema20 is not None:
                    if is_buy and ema20 > pos.sl:
                        pos.sl = ema20
                    elif not is_buy and ema20 < pos.sl:
                        pos.sl = ema20
                # 更新后重检 SL
                if is_buy and current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "MA_TRAIL"
                    closed_positions.append(pos)
                elif not is_buy and current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "MA_TRAIL"
                    closed_positions.append(pos)
                else:
                    still_active.append(pos)
                continue

            elif config.exit_mode == "atr_trail":
                atr_now = calc_atr(candles[:i+1], ATR_PERIOD)
                if atr_now is not None:
                    if is_buy:
                        new_sl = current_close - atr_now * 2.0
                        if new_sl > pos.sl:
                            pos.sl = new_sl
                    else:
                        new_sl = current_close + atr_now * 2.0
                        if new_sl < pos.sl:
                            pos.sl = new_sl
                if is_buy and current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "ATR_TRAIL"
                    closed_positions.append(pos)
                elif not is_buy and current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "ATR_TRAIL"
                    closed_positions.append(pos)
                else:
                    still_active.append(pos)
                continue

            elif config.exit_mode == "fixed_rr":
                still_active.append(pos)
                continue

            else:
                still_active.append(pos)

        # 结算已平仓
        for pos in closed_positions:
            _settle_position(pos)
            total_pnl += pos.pnl
            total_trades += 1
            if pos.pnl > 0:
                wins += 1
                if pos.direction == OrderType.BUY:
                    long_wins += 1
                else:
                    short_wins += 1
            else:
                losses += 1
            if pos.direction == OrderType.BUY:
                long_total += 1
            else:
                short_total += 1
            positions.append(pos)
        active = still_active

        # === 入场 ===
        if len(active) >= config.max_positions:
            continue

        result = signal_fn(candles, i, state)
        if result is None:
            continue
        signal_name, signal_dir = result

        # 计算 SL
        if bandwidth is None:
            continue
        dist = bandwidth * 0.35

        if signal_dir == OrderType.BUY:
            sl = round(current_close - dist, 2)
            tp = round(current_close + dist * config.exit_rr, 2) if config.exit_mode == "fixed_rr" else 0.0
        else:
            sl = round(current_close + dist, 2)
            tp = round(current_close - dist * config.exit_rr, 2) if config.exit_mode == "fixed_rr" else 0.0

        if sl <= 0:
            continue

        pos = BTPos(
            entry_idx=i, entry_price=current_close,
            direction=signal_dir, sl=sl, tp=tp,
            entry_k=state.get("curr_k", 0),
        )
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
            if pos.direction == OrderType.BUY:
                long_wins += 1
            else:
                short_wins += 1
        else:
            losses += 1
        if pos.direction == OrderType.BUY:
            long_total += 1
        else:
            short_total += 1
        positions.append(pos)

    # 计算统计
    win_pnls = [p.pnl for p in positions if p.pnl > 0]
    loss_pnls = [p.pnl for p in positions if p.pnl <= 0]
    avg_win = round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else 0
    avg_loss = round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else 0
    gross_profit = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999

    # 最大回撤（峰值→谷值）
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
        "label": config.label,
        "strategy": config.strategy,
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


def _settle_position(pos: BTPos):
    if pos.direction == OrderType.BUY:
        pos.pnl = (pos.exit_price - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION
    else:
        pos.pnl = (pos.entry_price - pos.exit_price) * CONTRACT_SIZE * LOT_SIZE - COMMISSION


# ============================================================
# 变体定义 — 每个策略 3-4 个变体
# ============================================================
def get_variants():
    v = []

    # ---- 双均线 ----
    v.append(VariantConfig("MA_基线_20x60", "double_ma", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 20, "ma_slow": 60}))
    v.append(VariantConfig("MA_快线10x30", "double_ma", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 10, "ma_slow": 30}))
    v.append(VariantConfig("MA_慢线20x100", "double_ma", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 20, "ma_slow": 100}))
    v.append(VariantConfig("MA_20x60_固定RR2", "double_ma", exit_mode="fixed_rr", sl_mode="bb_035",
                           exit_rr=2.0, signal_params={"ma_fast": 20, "ma_slow": 60}))

    # ---- ATR 突破 ----
    v.append(VariantConfig("ATR_基线_20x2", "atr_breakout", exit_mode="atr_trail", sl_mode="bb_035",
                           signal_params={"breakout_period": 20}))
    v.append(VariantConfig("ATR_突破10x2", "atr_breakout", exit_mode="atr_trail", sl_mode="bb_035",
                           signal_params={"breakout_period": 10}))
    v.append(VariantConfig("ATR_20x2_MA止损", "atr_breakout", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"breakout_period": 20}))
    v.append(VariantConfig("ATR_20x2_固定RR2", "atr_breakout", exit_mode="fixed_rr", sl_mode="bb_035",
                           exit_rr=2.0, signal_params={"breakout_period": 20}))

    # ---- 组合（双均线 + ATR 双重确认）----
    v.append(VariantConfig("组合_基线", "combined", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 20, "ma_slow": 60, "breakout_period": 20}))
    v.append(VariantConfig("组合_快线", "combined", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 10, "ma_slow": 30, "breakout_period": 10}))
    v.append(VariantConfig("组合_ATR止损", "combined", exit_mode="atr_trail", sl_mode="bb_035",
                           signal_params={"ma_fast": 20, "ma_slow": 60, "breakout_period": 20}))
    v.append(VariantConfig("组合_固定RR2", "combined", exit_mode="fixed_rr", sl_mode="bb_035",
                           exit_rr=2.0, signal_params={"ma_fast": 20, "ma_slow": 60, "breakout_period": 20}))

    # ---- RSI + 布林带 ----
    v.append(VariantConfig("RSIBB_基线_30x70", "rsi_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"rsi_oversold": 30, "rsi_overbought": 70}))
    v.append(VariantConfig("RSIBB_极值_20x80", "rsi_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"rsi_oversold": 20, "rsi_overbought": 80}))
    v.append(VariantConfig("RSIBB_基线_固定RR2", "rsi_bollinger", exit_mode="fixed_rr", sl_mode="bb_035",
                           exit_rr=2.0, signal_params={"rsi_oversold": 30, "rsi_overbought": 70}))
    v.append(VariantConfig("RSIBB_基线_ATR止损", "rsi_bollinger", exit_mode="atr_trail", sl_mode="bb_035",
                           signal_params={"rsi_oversold": 30, "rsi_overbought": 70}))

    # ---- Stoch + 布林带 ----
    v.append(VariantConfig("Stoch_MA止损(当前实盘)", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"stoch_oversold": 20, "stoch_overbought": 80}))
    v.append(VariantConfig("Stoch_极值_15x85", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                           signal_params={"stoch_oversold": 15, "stoch_overbought": 85}))
    v.append(VariantConfig("Stoch_固定RR2", "stoch_bollinger", exit_mode="fixed_rr", sl_mode="bb_035",
                           exit_rr=2.0, signal_params={"stoch_oversold": 20, "stoch_overbought": 80}))
    v.append(VariantConfig("Stoch_ATR止损", "stoch_bollinger", exit_mode="atr_trail", sl_mode="bb_035",
                           signal_params={"stoch_oversold": 20, "stoch_overbought": 80}))

    return v


# ============================================================
# Main
# ============================================================
def main():
    print("连接 MT4 获取 H1 数据...")
    bridge = create_bridge()
    if not bridge.connect():
        print("MT4 连接失败!")
        sys.exit(1)

    info = bridge.get_account_info()
    if info:
        print(f"账户: #{info.login}")

    raw = bridge.get_candles("XAUUSD", "H1", 4000)
    candles = list(reversed(raw))
    start = datetime.fromtimestamp(int(candles[0].time))
    end = datetime.fromtimestamp(int(candles[-1].time))
    print(f"H1: {len(candles)} 根  {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")

    bridge.disconnect()

    variants = get_variants()
    results = []

    print(f"\n{'='*100}")
    print(f"H1 全策略回测 — {len(variants)} 个变体")
    print(f"数据: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} | H1 | {len(candles)} 根K线")
    print(f"{'='*100}")
    print(f"{'策略':<30} {'交易':>4} {'盈亏':>9} {'胜率':>7} {'均赢':>8} {'均亏':>8} {'盈亏比':>7} {'最大回撤':>9}")
    print("-" * 95)

    for i, v in enumerate(variants):
        r = run_variant(candles, v)
        results.append(r)
        wr_mark = " ***" if r["win_rate"] >= 60 else ""
        print(f"{r['strategy']+'/'+r['label']:<30} {r['trades']:>4} ${r['pnl']:>8.2f} {r['win_rate']:>6.1f}%{wr_mark} ${r['avg_win']:>7.0f} ${r['avg_loss']:>7.0f} {r['profit_factor']:>6.1f} ${r['max_dd']:>8.0f}")

    # 汇总
    print(f"\n{'='*100}")
    print("汇总")
    print(f"{'='*100}")

    high_wr = [r for r in results if r["win_rate"] >= 60]
    best_pnl = max(results, key=lambda r: r["pnl"])
    best_wr = max(results, key=lambda r: r["win_rate"])

    print(f"胜率 ≥60%: {len(high_wr)} 个")
    for r in sorted(high_wr, key=lambda r: -r["win_rate"]):
        print(f"  {r['strategy']}/{r['label']}: {r['win_rate']}% 胜率, ${r['pnl']} 盈亏, {r['trades']}笔")
    print(f"\n最高胜率: {best_wr['strategy']}/{best_wr['label']} = {best_wr['win_rate']}%")
    print(f"最高盈亏: {best_pnl['strategy']}/{best_pnl['label']} = ${best_pnl['pnl']}")

    # 按策略分组
    print(f"\n--- 按策略分组 ---")
    for strat in ["double_ma", "atr_breakout", "combined", "rsi_bollinger", "stoch_bollinger"]:
        group = [r for r in results if r["strategy"] == strat]
        if not group:
            continue
        best = max(group, key=lambda r: r["pnl"])
        print(f"{strat}: 最佳={best['label']} 胜率={best['win_rate']}% 盈亏=${best['pnl']} 交易={best['trades']}笔")

    write_report(start, end, len(candles), results, best_wr, best_pnl, high_wr)


def write_report(start, end, bar_count, results, best_wr, best_pnl, high_wr):
    lines = []
    lines.append(f"# H1 全策略回测结果\n")
    lines.append(f"**日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**数据**: H1 {bar_count}根 | {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")
    lines.append(f"**策略数**: 5 策略 × 4 变体 = {len(results)} 个\n")
    lines.append("---\n")

    lines.append("## 全部结果\n")
    lines.append("| 策略 | 变体 | 交易 | 盈亏 | 胜率 | 多(胜率) | 空(胜率) |")
    lines.append("|------|------|------|------|------|----------|----------|")
    for r in sorted(results, key=lambda r: -r["win_rate"]):
        wr_badge = "⭐" if r["win_rate"] >= 60 else ""
        lines.append(f"| {r['strategy']} | {r['label']} | {r['trades']} | ${r['pnl']} | {r['win_rate']}%{wr_badge} | {r['long_trades']}({r['long_wr']}%) | {r['short_trades']}({r['short_wr']}%) |")
    lines.append("")

    lines.append("## 按策略分组\n")
    for strat in ["double_ma", "atr_breakout", "combined", "rsi_bollinger", "stoch_bollinger"]:
        group = [r for r in results if r["strategy"] == strat]
        if not group:
            continue
        lines.append(f"### {strat}\n")
        lines.append("| 变体 | 交易 | 盈亏 | 胜率 | 多(胜率) | 空(胜率) |")
        lines.append("|------|------|------|------|----------|----------|")
        for r in group:
            wr_badge = "⭐" if r["win_rate"] >= 60 else ""
            lines.append(f"| {r['label']} | {r['trades']} | ${r['pnl']} | {r['win_rate']}%{wr_badge} | {r['long_trades']}({r['long_wr']}%) | {r['short_trades']}({r['short_wr']}%) |")
        lines.append("")

    lines.append("## 关键发现\n")
    lines.append(f"### 胜率 ≥60% 方案 ({len(high_wr)} 个):")
    for r in sorted(high_wr, key=lambda r: -r["win_rate"]):
        lines.append(f"- **{r['strategy']}/{r['label']}**: {r['win_rate']}% 胜率, ${r['pnl']} 盈亏, {r['trades']} 笔")
    if not high_wr:
        lines.append("- H1 上无一方案达到 60% 胜率")
    lines.append(f"\n### 极值")
    lines.append(f"- 最高胜率: **{best_wr['strategy']}/{best_wr['label']}** → {best_wr['win_rate']}%")
    lines.append(f"- 最高盈亏: **{best_pnl['strategy']}/{best_pnl['label']}** → ${best_pnl['pnl']}")
    lines.append(f"\n---\n*{datetime.now().strftime('%Y-%m-%d %H:%M')} 生成*")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
