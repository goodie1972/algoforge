"""
提升胜率研究 — 系统性回测多种变体
目标: 找到 H4 上胜率 60%+ 的可行方案
"""

import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Callable

from core.bridge import create_bridge, OrderType

# ============================================================
# 不变参数
# ============================================================
STOCH_K = 8
STOCH_SLOWING = 3
STOCH_D = 3
BB_PERIOD = 20
BB_STD = 2.0
ATR_PERIOD = 14

LOT_SIZE = 0.01
CONTRACT_SIZE = 100
COMMISSION = 0.5

OUTPUT_FILE = "backtest/research_results.md"


@dataclass
class BacktestPosition:
    entry_idx: int
    entry_price: float
    direction: OrderType
    sl: float
    tp: float
    entry_k: float
    ticket: int = 0
    exit_idx: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    peak_diff: float = 0.0


# ============================================================
# 指标计算（复用现有逻辑）
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


# ============================================================
# 可配置的回测核心
# ============================================================
class VariantConfig:
    """单个回测变体的参数"""
    def __init__(self, label: str, **kwargs):
        self.label = label
        # 趋势过滤
        self.trend_filter: str = kwargs.get("trend_filter", "none")  # none / ema50 / ema200 / long_only / bb_band
        # 入场精度
        self.oversold: int = kwargs.get("oversold", 20)
        self.overbought: int = kwargs.get("overbought", 80)
        # 出场策略
        self.exit_mode: str = kwargs.get("exit_mode", "kd_decay")  # kd_decay / fixed_rr / atr_trail / ma_trail
        self.exit_rr: float = kwargs.get("exit_rr", 2.0)  # 固定盈亏比时使用
        # 仓位
        self.max_positions: int = kwargs.get("max_positions", 5)
        self.use_pyramid: bool = kwargs.get("use_pyramid", True)
        # SL 模式
        self.sl_mode: str = kwargs.get("sl_mode", "bb_035")  # bb_035 / atr_20 / none
        # 极端区入场
        self.extreme_entry: bool = kwargs.get("extreme_entry", False)
        # 双倍首单
        self.double_first: bool = kwargs.get("double_first", False)


def trend_filter_pass(config: VariantConfig, direction: OrderType, candles,
                       current_close: float) -> bool:
    """检查趋势过滤条件"""
    if config.trend_filter == "none":
        return True

    if config.trend_filter == "long_only":
        return direction == OrderType.BUY

    if config.trend_filter == "ema50":
        ema50 = calc_ema(candles, 50)
        if ema50 is None:
            return True
        if direction == OrderType.BUY:
            return current_close > ema50
        else:
            return current_close < ema50

    if config.trend_filter == "ema200":
        ema200 = calc_ema(candles, 200)
        if ema200 is None:
            return True
        if direction == OrderType.BUY:
            return current_close > ema200
        else:
            return current_close < ema200

    if config.trend_filter == "bb_band":
        sma, bandwidth, std_val = calc_bb(candles, BB_PERIOD, BB_STD)
        if sma is None:
            return True
        if direction == OrderType.BUY:
            return current_close < sma - 0.5 * bandwidth  # 价格在下半区才做多
        else:
            return current_close > sma + 0.5 * bandwidth  # 价格在上半区才做空

    return True


def run_variant(candles, config: VariantConfig):
    """运行单个变体的回测"""
    positions: list[BacktestPosition] = []
    active: list[BacktestPosition] = []
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    long_wins = 0
    long_total = 0
    short_wins = 0
    short_total = 0
    next_ticket = 1000

    prev_k: Optional[float] = None
    prev_d: Optional[float] = None

    # SL 配置
    sl_params = {
        "bb_035": ("bb", 0.35),
        "atr_20": ("atr", 2.0),
        "none": ("none", 0),
    }
    sl_type, sl_mult = sl_params[config.sl_mode]

    # 固定盈亏比的 SL 距离计算（用 BB 带宽）
    fixed_rr_bb_distance = None  # 用于 fixed_rr 模式，每 tick 更新

    min_bars = max(STOCH_K + STOCH_SLOWING + STOCH_D + 5, 200)

    for i in range(min_bars, len(candles)):
        current = candles[i]
        current_close = float(current.close)
        current_high = float(current.high)
        current_low = float(current.low)

        # Stoch
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

        # SL 距离计算
        if sl_type == "bb":
            _, bandwidth, _ = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
            if bandwidth is not None:
                sl_distance = bandwidth * sl_mult
                if config.exit_mode == "fixed_rr":
                    fixed_rr_bb_distance = sl_distance  # 用于 TP 计算
            else:
                sl_distance = None
        elif sl_type == "atr":
            sl_distance_raw = calc_atr(candles[:i+1], ATR_PERIOD)
            sl_distance = sl_distance_raw * sl_mult if sl_distance_raw else None
        else:
            sl_distance = None

        # === 出场检查 ===
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

            # TP 检查（仅 fixed_rr 模式）
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

            # === 根据 exit_mode 做不同的出场判断 ===
            if config.exit_mode == "kd_decay":
                # 原有 K-D 衰减逻辑
                curr_diff = curr_k - curr_d if is_buy else curr_d - curr_k
                if curr_diff < 0:
                    curr_diff = 0

                # 极端区保护
                if is_buy and pos.entry_k < config.oversold and curr_k < config.oversold and curr_d < config.oversold:
                    still_active.append(pos)
                    continue
                if not is_buy and pos.entry_k > config.overbought and curr_k > config.overbought and curr_d > config.overbought:
                    still_active.append(pos)
                    continue

                if curr_diff > pos.peak_diff:
                    pos.peak_diff = curr_diff

                should_exit = False
                if pos.peak_diff > 0:
                    if pos.peak_diff <= 3:
                        if curr_diff == 0:
                            should_exit = True
                    else:
                        if curr_diff < pos.peak_diff * 0.382:
                            should_exit = True

                if should_exit:
                    pos.exit_idx = i
                    pos.exit_price = current_close
                    pos.exit_reason = "KD_EXIT"
                    closed_positions.append(pos)
                else:
                    still_active.append(pos)

            elif config.exit_mode == "atr_trail":
                # ATR 移动止损
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
                # 再检查 SL
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

            elif config.exit_mode == "ma_trail":
                # EMA20 移动止损
                ema20 = calc_ema(candles[:i+1], 20)
                if ema20 is not None:
                    if is_buy and ema20 > pos.sl:
                        pos.sl = ema20
                    elif not is_buy and ema20 < pos.sl:
                        pos.sl = ema20
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

            elif config.exit_mode == "fixed_rr":
                # 固定盈亏比：SL 和 TP 都已设好，TP 上面已检查，这里只处理过期持仓
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

        n_longs = sum(1 for p in active if p.direction == OrderType.BUY)
        n_shorts = sum(1 for p in active if p.direction == OrderType.SELL)
        signal = None
        signal_direction = None

        in_buy_extreme = curr_k < config.oversold and curr_d < config.oversold
        in_sell_extreme = curr_k > config.overbought and curr_d > config.overbought

        # 首单：金叉/死叉事件
        if n_longs == 0 and n_shorts == 0:
            if golden_cross and curr_k < config.oversold:
                signal = "BUY"
                signal_direction = OrderType.BUY
            elif death_cross and curr_k > config.overbought:
                signal = "SELL"
                signal_direction = OrderType.SELL
        elif n_longs > 0 and n_shorts == 0 and config.use_pyramid:
            # 金字塔加仓
            if n_longs < config.max_positions and n_longs < len([2, 5, 8, 13]):
                diff = curr_k - curr_d
                if diff >= [2, 5, 8, 13][n_longs - 1]:
                    signal = "ADD_BUY"
                    signal_direction = OrderType.BUY
        elif n_shorts > 0 and n_longs == 0 and config.use_pyramid:
            if n_shorts < config.max_positions and n_shorts < len([2, 5, 8, 13]):
                diff = curr_d - curr_k
                if diff >= [2, 5, 8, 13][n_shorts - 1]:
                    signal = "ADD_SELL"
                    signal_direction = OrderType.SELL

        if signal is None or signal_direction is None:
            continue

        # 趋势过滤
        if not trend_filter_pass(config, signal_direction, candles[:i+1], current_close):
            continue

        # 计算 SL
        if sl_type == "bb":
            _, bandwidth, _ = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
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
            tp = 0.0
            if config.exit_mode == "fixed_rr" and dist is not None:
                tp = round(current_close + dist * config.exit_rr, 2)
        else:
            sl = round(current_close + dist, 2) if dist is not None else 99999.0
            tp = 0.0
            if config.exit_mode == "fixed_rr" and dist is not None:
                tp = round(current_close - dist * config.exit_rr, 2)

        if sl <= 0 and sl_type != "none":
            continue

        pos = BacktestPosition(
            entry_idx=i, entry_price=current_close,
            direction=signal_direction, sl=sl, tp=tp,
            entry_k=curr_k, ticket=next_ticket,
        )
        next_ticket += 1
        is_buy = signal_direction == OrderType.BUY
        pos.peak_diff = curr_k - curr_d if is_buy else curr_d - curr_k
        if pos.peak_diff < 0:
            pos.peak_diff = 0
        active.append(pos)

        # 双倍首单：首信号开两张
        if config.double_first and signal in ("BUY", "SELL") and len(active) < config.max_positions:
            pos2 = BacktestPosition(
                entry_idx=i, entry_price=current_close,
                direction=signal_direction, sl=sl, tp=tp,
                entry_k=curr_k, ticket=next_ticket,
            )
            next_ticket += 1
            pos2.peak_diff = pos.peak_diff
            active.append(pos2)

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

    return {
        "label": config.label,
        "trades": total_trades,
        "pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
        "long_wr": round(long_wins / long_total * 100, 1) if long_total > 0 else 0,
        "short_wr": round(short_wins / short_total * 100, 1) if short_total > 0 else 0,
        "long_trades": long_total,
        "short_trades": short_total,
    }


# ============================================================
# 所有实验变体定义
# ============================================================
def get_variants():
    variants = []

    # === Baseline ===
    variants.append(VariantConfig("0_基线", max_positions=5, use_pyramid=True,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none"))

    # === Experiment 1: 趋势过滤 ===
    variants.append(VariantConfig("1a_趋势_EMA50", max_positions=5, use_pyramid=True,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="ema50"))
    variants.append(VariantConfig("1b_趋势_EMA200", max_positions=5, use_pyramid=True,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="ema200"))
    variants.append(VariantConfig("1c_趋势_只做多", max_positions=5, use_pyramid=True,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="long_only"))
    variants.append(VariantConfig("1d_趋势_BB半区", max_positions=5, use_pyramid=True,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="bb_band"))

    # === Experiment 2: 入场精度 ===
    for level, label in [(15, "2a_入场_K15"), (10, "2b_入场_K10"), (5, "2c_入场_K5")]:
        variants.append(VariantConfig(label, max_positions=5, use_pyramid=True,
                                      exit_mode="kd_decay", sl_mode="bb_035",
                                      oversold=level, overbought=100 - level,
                                      trend_filter="none"))

    # === Experiment 3: 出场策略 ===
    variants.append(VariantConfig("3a_出场_固定RR1:2", max_positions=5, use_pyramid=True,
                                  exit_mode="fixed_rr", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  exit_rr=2.0))
    variants.append(VariantConfig("3b_出场_固定RR1:3", max_positions=5, use_pyramid=True,
                                  exit_mode="fixed_rr", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  exit_rr=3.0))
    variants.append(VariantConfig("3c_出场_ATR移动止损", max_positions=5, use_pyramid=True,
                                  exit_mode="atr_trail", sl_mode="atr_20",
                                  oversold=20, overbought=80, trend_filter="none"))
    variants.append(VariantConfig("3d_出场_MA移动止损", max_positions=5, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none"))

    # === Experiment 4: 取消金字塔 ===
    variants.append(VariantConfig("4a_仓位_单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none"))

    # === Experiment 5: 组合最优 ===
    # 趋势过滤 + 极值入场 + 单仓
    variants.append(VariantConfig("5a_EMA50+K15+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=15, overbought=85, trend_filter="ema50"))
    variants.append(VariantConfig("5b_EMA50+K10+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=10, overbought=90, trend_filter="ema50"))
    # 只做多 + 极值 + 单仓
    variants.append(VariantConfig("5c_LongOnly+K15+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="kd_decay", sl_mode="bb_035",
                                  oversold=15, overbought=85, trend_filter="long_only"))
    # EMA50 + 固定RR
    variants.append(VariantConfig("5d_EMA50+固定RR2:1+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="fixed_rr", sl_mode="bb_035",
                                  oversold=15, overbought=85, trend_filter="ema50",
                                  exit_rr=2.0))
    # 只做多 + 固定RR
    variants.append(VariantConfig("5e_LongOnly+固定RR2:1+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="fixed_rr", sl_mode="bb_035",
                                  oversold=15, overbought=85, trend_filter="long_only",
                                  exit_rr=2.0))

    # === Experiment 6: MA移动止损 + 趋势/仓位组合 ===
    variants.append(VariantConfig("6a_MA止损+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none"))
    variants.append(VariantConfig("6b_MA止损+只做多", max_positions=5, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="long_only"))
    variants.append(VariantConfig("6c_MA止损+只做多+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="long_only"))
    variants.append(VariantConfig("6d_MA止损+EMA50+单仓", max_positions=1, use_pyramid=False,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="ema50"))

    # === Experiment 7: 双倍首单 ===
    # 基于6a，首单开2张
    variants.append(VariantConfig("7a_MA止损+单仓+双倍首单", max_positions=2, use_pyramid=False,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=True))
    # 总仓位5张：首2张 + 金字塔3张
    variants.append(VariantConfig("7b_MA止损+金字塔+双倍首单", max_positions=5, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=True))
    # 首2张 + 金字塔2张 = 最多4张
    variants.append(VariantConfig("7c_MA止损+金字塔2层+双倍首单", max_positions=4, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=True))
    # 首2张 + 金字塔1张 = 最多3张
    variants.append(VariantConfig("7d_MA止损+金字塔1层+双倍首单", max_positions=3, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=True))
    # 对比：无双倍，金字塔2层 (总3张)
    variants.append(VariantConfig("7e_MA止损+金字塔2层", max_positions=3, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=False))
    # 对比：无双倍，金字塔1层 (总2张)
    variants.append(VariantConfig("7f_MA止损+金字塔1层", max_positions=2, use_pyramid=True,
                                  exit_mode="ma_trail", sl_mode="bb_035",
                                  oversold=20, overbought=80, trend_filter="none",
                                  double_first=False))

    return variants


# ============================================================
# Main
# ============================================================
def main():
    print("连接 MT4 获取 H4 数据...")
    bridge = create_bridge()
    if not bridge.connect():
        print("MT4 连接失败!")
        sys.exit(1)

    info = bridge.get_account_info()
    if info:
        print(f"账户: #{info.login}")

    raw = bridge.get_candles("XAUUSD", "H4", 1000)
    candles = list(reversed(raw))
    start = datetime.fromtimestamp(int(candles[0].time))
    end = datetime.fromtimestamp(int(candles[-1].time))
    print(f"H4: {len(candles)} 根  {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")

    bridge.disconnect()

    variants = get_variants()
    results = []

    print(f"\n{'='*100}")
    print(f"胜率提升研究 — {len(variants)} 个变体")
    print(f"数据: {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} | H4 | {len(candles)} 根K线")
    print(f"{'='*100}")

    for i, v in enumerate(variants):
        r = run_variant(candles, v)
        results.append(r)
        wr_mark = " ***" if r["win_rate"] >= 60 else ""
        print(f"[{i+1:02d}/{len(variants)}] {r['label']:<30} "
              f"交易={r['trades']:>4} 盈亏=${r['pnl']:>8.2f} "
              f"胜率={r['win_rate']:>5.1f}%{wr_mark} "
              f"多:{r['long_trades']}({r['long_wr']}%) 空:{r['short_trades']}({r['short_wr']}%)")

    # 找 60%+ 的方案
    high_wr = [r for r in results if r["win_rate"] >= 60]
    best_pnl = max(results, key=lambda r: r["pnl"])
    best_wr = max(results, key=lambda r: r["win_rate"])

    print(f"\n{'='*100}")
    print("汇总")
    print(f"{'='*100}")
    print(f"胜率 ≥60% 的方案数: {len(high_wr)}")
    for r in high_wr:
        print(f"  {r['label']}: {r['win_rate']}% 胜率, ${r['pnl']} 盈亏, {r['trades']}笔交易")
    print(f"\n最高胜率: {best_wr['label']} = {best_wr['win_rate']}%")
    print(f"最高盈亏: {best_pnl['label']} = ${best_pnl['pnl']}")

    # 输出 Markdown 报告
    write_report(start, end, len(candles), results, best_wr, best_pnl, high_wr)


def write_report(start, end, bar_count, results, best_wr, best_pnl, high_wr):
    """输出结构化研究结果到 Markdown 文件"""
    lines = []
    lines.append(f"# 胜率提升研究结果\n")
    lines.append(f"**日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**策略**: Stoch({STOCH_K},{STOCH_SLOWING},{STOCH_D}) + 布林带 变体对比")
    lines.append(f"**数据**: H4 {bar_count}根 | {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}")
    lines.append(f"**目标**: 找到胜率 ≥60% 的方案\n")
    lines.append("---\n")

    # Section 1: 基线
    lines.append("## 1. 基线 (当前策略)\n")
    lines.append("| 配置 | 交易 | 盈亏 | 胜率 | 多(胜率) | 空(胜率) |")
    lines.append("|------|------|------|------|----------|----------|")
    baseline = results[0]
    lines.append(f"| {baseline['label']} | {baseline['trades']} | ${baseline['pnl']} | {baseline['win_rate']}% | {baseline['long_trades']}({baseline['long_wr']}%) | {baseline['short_trades']}({baseline['short_wr']}%) |")
    lines.append("")

    # Section 2: Experiments
    sections = [
        ("2. 趋势过滤实验", "1a", "1d"),
        ("3. 入场精度实验", "2a", "2c"),
        ("4. 出场策略实验", "3a", "3d"),
        ("5. 仓位管理实验", "4a", "4a"),
        ("6. 组合优选实验", "5a", "5e"),
        ("7. MA移动止损组合", "6a", "6d"),
        ("8. 双倍首单实验", "7a", "7b"),
    ]

    for title, start_id, end_id in sections:
        lines.append(f"## {title}\n")
        lines.append("| 变体 | 交易 | 盈亏 | 胜率 | 多单(胜率) | 空单(胜率) |")
        lines.append("|------|------|------|------|------------|------------|")
        for r in results:
            if r['label'].startswith(f"{start_id[:1]}"):
                wr_badge = "⭐" if r['win_rate'] >= 60 else ""
                lines.append(f"| {r['label']} | {r['trades']} | ${r['pnl']} | {r['win_rate']}%{wr_badge} | {r['long_trades']}({r['long_wr']}%) | {r['short_trades']}({r['short_wr']}%) |")
        lines.append("")

    # Section 7: Summary
    lines.append("## 7. 关键发现\n")
    lines.append(f"### 胜率 ≥60% 方案 ({len(high_wr)} 个):")
    if high_wr:
        for r in high_wr:
            lines.append(f"- **{r['label']}**: {r['win_rate']}% 胜率, ${r['pnl']} 盈亏, {r['trades']} 笔交易 (多{r['long_wr']}%/空{r['short_wr']}%)")
    else:
        lines.append("- 无方案达到 60% 胜率\n")

    lines.append(f"\n### 极值")
    lines.append(f"- 最高胜率: **{best_wr['label']}** → {best_wr['win_rate']}%")
    lines.append(f"- 最高盈亏: **{best_pnl['label']}** → ${best_pnl['pnl']}")

    lines.append(f"\n### 分析")
    lines.append(f"1. 趋势过滤对胜率影响最大的方向是？对比 1a-1d 的 long_wr 和 short_wr")
    lines.append(f"2. 更极端的入场 (2a→2c) 是否显著提升胜率？代价是交易次数减少多少？")
    lines.append(f"3. 哪种出场策略胜率最高？固定RR vs ATR vs MA？")
    lines.append(f"4. 取消金字塔后胜率变化如何？")
    lines.append(f"5. 组合方案 (5a-5e) 是否达到 60%+？")

    lines.append(f"\n---\n*{datetime.now().strftime('%Y-%m-%d %H:%M')} 生成*")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已写入: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
