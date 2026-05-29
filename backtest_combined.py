"""
Combined Strategy Backtest
EMA20/60 + ATR 20-bar channel breakout, double confirm
ATR dynamic SL/TP (SL=2xATR, TP=4xATR)
"""
import sys
import math
from datetime import datetime

from core.bridge import create_bridge, OrderType, Candle
from config.settings import MA_FAST, MA_SLOW, MA_METHOD

# ============================================================
# 1. Fetch historical M30 data from MT4
# ============================================================
print("连接 MT4 获取历史数据...")
bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

info = bridge.get_account_info()
if info:
    print(f"账户: #{info.login} 余额: ${info.balance:.2f}")
else:
    print("账户: N/A")

# 获取 1000 根 M30 K线
raw = bridge.get_candles("XAUUSD", "M30", 1000)
candles = list(reversed(raw))  # 时间顺序 旧→新
print(f"获取到 {len(candles)} 根 M30 K线")
print(f"时间范围: {datetime.fromtimestamp(int(candles[0].time))} ~ {datetime.fromtimestamp(int(candles[-1].time))}")

bridge.disconnect()

# ============================================================
# 2. Backtest engine
# ============================================================
def calc_ema(closes, period):
    multiplier = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calc_atr(candles, period=14):
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

MA_FAST = 20
MA_SLOW = 60
ATR_PERIOD = 14
BREAKOUT_PERIOD = 20
ATR_SL_MULTIPLIER = 2.0
ATR_TP_MULTIPLIER = 4.0  # 2:1 reward:risk
LOT_SIZE = 0.01
CONTRACT_SIZE = 100  # XAUUSD 1 lot = 100 oz
MAX_POSITIONS = 3

class BacktestPosition:
    def __init__(self, entry_idx, entry_price, direction, sl, tp):
        self.entry_idx = entry_idx
        self.entry_price = entry_price
        self.direction = direction  # OrderType.BUY or OrderType.SELL
        self.sl = sl
        self.tp = tp
        self.exit_idx = None
        self.exit_price = None
        self.pnl = 0.0
        self.exit_reason = ""

def run_backtest(candles):
    positions = []  # 所有已平仓
    active_positions = []  # 当前持仓
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0

    required = max(MA_SLOW, BREAKOUT_PERIOD + 1, ATR_PERIOD + 1) + 5

    for i in range(required, len(candles)):
        current = candles[i]
        current_close = float(current.close)
        current_high = float(current.high)
        current_low = float(current.low)

        # --- Check existing positions for SL/TP ---
        closed_positions = []
        still_active = []
        for pos in active_positions:
            if pos.direction == OrderType.BUY:
                if current_low <= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                elif current_high >= pos.tp:
                    pos.exit_idx = i
                    pos.exit_price = pos.tp
                    pos.exit_reason = "TP"
                    closed_positions.append(pos)
                else:
                    still_active.append(pos)
            else:  # SELL
                if current_high >= pos.sl:
                    pos.exit_idx = i
                    pos.exit_price = pos.sl
                    pos.exit_reason = "SL"
                    closed_positions.append(pos)
                elif current_low <= pos.tp:
                    pos.exit_idx = i
                    pos.exit_price = pos.tp
                    pos.exit_reason = "TP"
                    closed_positions.append(pos)
                else:
                    still_active.append(pos)

        # Calculate P&L for closed positions
        for pos in closed_positions:
            if pos.direction == OrderType.BUY:
                pos.pnl = (pos.exit_price - pos.entry_price) * CONTRACT_SIZE * LOT_SIZE
            else:
                pos.pnl = (pos.entry_price - pos.exit_price) * CONTRACT_SIZE * LOT_SIZE
            total_pnl += pos.pnl
            total_trades += 1
            if pos.pnl > 0:
                wins += 1
            else:
                losses += 1
            positions.append(pos)

        active_positions = still_active

        # --- Generate combined signal ---
        if len(active_positions) >= MAX_POSITIONS:
            continue

        # Current candles slice
        current_slice = candles[:i+1]
        closes = [float(c.close) for c in current_slice]
        highs = [float(c.high) for c in current_slice]
        lows = [float(c.low) for c in current_slice]

        # DoubleMA signal
        fast_now = calc_ema(closes, MA_FAST)
        slow_now = calc_ema(closes, MA_SLOW)

        old_closes = closes[:-1]
        fast_prev = calc_ema(old_closes, MA_FAST)
        slow_prev = calc_ema(old_closes, MA_SLOW)

        ma_signal = None
        if fast_prev <= slow_prev and fast_now > slow_now:
            ma_signal = OrderType.BUY
        elif fast_prev >= slow_prev and fast_now < slow_now:
            ma_signal = OrderType.SELL

        # ATRBreakout signal
        lookback = current_slice[-(BREAKOUT_PERIOD + 1):-1]
        highest = max(float(c.high) for c in lookback)
        lowest = min(float(c.low) for c in lookback)

        atr_signal = None
        if current_close > highest:
            atr_signal = OrderType.BUY
        elif current_close < lowest:
            atr_signal = OrderType.SELL

        # Combined: both must agree
        if ma_signal is None or atr_signal is None or ma_signal != atr_signal:
            continue

        # Signal confirmed - open position
        direction = ma_signal
        entry_price = current_close  # use close as fill price

        # Calculate ATR for SL/TP
        atr = calc_atr(current_slice, ATR_PERIOD)
        if atr is None:
            continue

        sl_distance = atr * ATR_SL_MULTIPLIER
        tp_distance = atr * ATR_TP_MULTIPLIER

        if direction == OrderType.BUY:
            sl = entry_price - sl_distance
            tp = entry_price + tp_distance
        else:
            sl = entry_price + sl_distance
            tp = entry_price - tp_distance

        pos = BacktestPosition(i, entry_price, direction, sl, tp)
        active_positions.append(pos)

    # Mark remaining open positions
    for pos in active_positions:
        positions.append(pos)

    return positions, total_pnl, total_trades, wins, losses


# ============================================================
# 3. Run and report
# ============================================================
print("\n" + "="*60)
print("COMBINED 策略回测 (EMA20/60 + ATR突破 双确认)")
print("="*60)

positions, total_pnl, total_trades, wins, losses = run_backtest(candles)

print(f"\n总交易次数: {total_trades}")
if total_trades > 0:
    win_rate = wins / total_trades * 100
    print(f"胜率: {wins}/{total_trades} = {win_rate:.1f}%")
    print(f"总盈亏: ${total_pnl:.2f}")
    print(f"平均每单: ${total_pnl/total_trades:.2f}")

    # Analyze by direction
    buy_pnl = sum(p.pnl for p in positions if p.direction == OrderType.BUY)
    sell_pnl = sum(p.pnl for p in positions if p.direction == OrderType.SELL)
    buy_count = sum(1 for p in positions if p.direction == OrderType.BUY)
    sell_count = sum(1 for p in positions if p.direction == OrderType.SELL)
    print(f"\n多单: {buy_count} 单, 盈亏 ${buy_pnl:.2f}")
    print(f"空单: {sell_count} 单, 盈亏 ${sell_pnl:.2f}")

    # Exit reason breakdown
    tp_count = sum(1 for p in positions if p.exit_reason == "TP")
    sl_count = sum(1 for p in positions if p.exit_reason == "SL")
    open_count = sum(1 for p in positions if p.exit_reason == "")
    print(f"\n止盈: {tp_count} | 止损: {sl_count} | 未平: {open_count}")

    # Recent trades (last 10)
    closed = [p for p in positions if p.exit_reason != ""]
    print(f"\n最近 10 笔交易:")
    for p in closed[-10:]:
        dir_str = "BUY " if p.direction == OrderType.BUY else "SELL"
        idx_time = datetime.fromtimestamp(int(candles[p.entry_idx].time))
        print(f"  {dir_str} @ {p.entry_price:.2f} → {p.exit_price:.2f} "
              f"[{p.exit_reason}] PnL=${p.pnl:.2f}  ({idx_time.month}-{idx_time.day} {idx_time.hour}:{idx_time.minute:02d})")
else:
    print("没有产生任何交易信号")
