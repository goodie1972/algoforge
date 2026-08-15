"""
V6 Hybrid backtest using SQLite H1 data (live data from MT4)
With M30 direction filtering for comparison
"""
import logging, sys, math, json, os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)

from data.database import init_db, get_conn
from core.bridge import Candle

# Read H1 and M30 data from SQLite
init_db()
conn = get_conn()
h1_rows = conn.execute(
    "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
).fetchall()
m30_rows = conn.execute(
    "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
conn.close()

print(f"Loaded {len(h1_rows)} H1 candles from SQLite")
print(f"Loaded {len(m30_rows)} M30 candles from SQLite")
print(f"H1 Range: {datetime.fromtimestamp(h1_rows[0][0]).strftime('%Y-%m-%d %H:%M')} ~ "
      f"{datetime.fromtimestamp(h1_rows[-1][0]).strftime('%Y-%m-%d %H:%M')}")
print(f"M30 Range: {datetime.fromtimestamp(m30_rows[0][0]).strftime('%Y-%m-%d %H:%M')} ~ "
      f"{datetime.fromtimestamp(m30_rows[-1][0]).strftime('%Y-%m-%d %H:%M')}")

h1_candles = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in h1_rows]
m30_candles = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in m30_rows]

# --- M30 lookup by H1 timestamp ---
# For each H1 bar, find the most recent M30 bar that started at or before the H1 bar's timestamp
m30_ts_list = [int(c.time) for c in m30_candles]

def find_m30_at_h1(h1_ts):
    """Return the index of the latest M30 candle at or before this H1 timestamp."""
    lo, hi = 0, len(m30_ts_list) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if m30_ts_list[mid] <= h1_ts:
            lo = mid + 1
        else:
            hi = mid - 1
    return hi  # hi is the last index <= ts, or -1 if none

# --- Indicator functions ---

def calc_sma(closes, period):
    if len(closes) < period: return None
    return sum(closes[-period:]) / period

def calc_ema(closes, period):
    if len(closes) < period: return None
    k = 2.0 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = (p - ema) * k + ema
    return ema

def calc_ema_series(closes, period):
    """Return full EMA series for trend direction."""
    if len(closes) < period: return None
    k = 2.0 / (period + 1)
    ema = [closes[0]]
    for p in closes[1:]:
        ema.append((p - ema[-1]) * k + ema[-1])
    return ema

def calc_stoch(candles, k_period=9, slowing=3, d_period=3):
    n = len(candles)
    if n < k_period + slowing + d_period + 1:
        return None
    raw_k = []
    for i in range(k_period-1, n):
        window = candles[i-k_period+1:i+1]
        highest = max(c.high for c in window)
        lowest = min(c.low for c in window)
        close = window[-1].close
        raw_k.append(50.0 if highest == lowest else (close-lowest)/(highest-lowest)*100)
    if len(raw_k) < slowing + d_period + 1:
        return None
    smooth_k = [sum(raw_k[i-slowing+1:i+1])/slowing for i in range(slowing-1, len(raw_k))]
    if len(smooth_k) < d_period + 1:
        return None
    curr_k = smooth_k[-1]
    prev_k = smooth_k[-2]
    curr_d = sum(smooth_k[-d_period:])/d_period
    prev_d = sum(smooth_k[-(d_period+1):-1])/d_period
    return {"prev_k": prev_k, "curr_k": curr_k, "prev_d": prev_d, "curr_d": curr_d}

def calc_rsi(closes, period=14):
    if len(closes) < period+1: return None
    gains, losses = [], []
    for i in range(1, period+1):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period
    for i in range(period+1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain*(period-1)+gain)/period
        avg_loss = (avg_loss*(period-1)+loss)/period
    return 100.0 if avg_loss == 0 else 100.0 - 100.0/(1.0+avg_gain/avg_loss)

def calc_macd(closes):
    if len(closes) < 35: return None
    k12,k26,k9 = 2.0/13, 2.0/27, 2.0/10
    e12 = closes[0]; e26 = closes[0]
    macd_line = []
    for p in closes:
        e12 = (p-e12)*k12+e12
        e26 = (p-e26)*k26+e26
        macd_line.append(e12-e26)
    sig = [macd_line[0]]
    for v in macd_line[1:]:
        sig.append((v-sig[-1])*k9+sig[-1])
    hist = [macd_line[i]-sig[i] for i in range(len(macd_line))]
    return {"hist_values": hist}

def check_bottom_div(hist, lookback=10):
    n = len(hist); start = n - lookback*2
    if start < 1: return False
    lows = []
    for i in range(start+1, n-1):
        if hist[i] < hist[i-1] and hist[i] < hist[i+1]:
            lows.append((i, hist[i]))
    if len(lows) < 2: return False
    return lows[-1][1] > lows[-2][1]

def check_top_div(hist, lookback=10):
    n = len(hist); start = n - lookback*2
    if start < 1: return False
    highs = []
    for i in range(start+1, n-1):
        if hist[i] > hist[i-1] and hist[i] > hist[i+1]:
            highs.append((i, hist[i]))
    if len(highs) < 2: return False
    return highs[-1][1] < highs[-2][1]

def calc_bb(closes, period=20, std_mul=2.5):
    if len(closes) < period: return None
    recent = closes[-period:]
    sma = sum(recent)/period
    variance = sum((c-sma)**2 for c in recent)/period
    return {"sma": sma, "upper": sma+std_mul*math.sqrt(variance), "lower": sma-std_mul*math.sqrt(variance)}

def calc_atr(candles, period=20):
    if len(candles) < period+2: return None
    tr = []
    for i in range(1, len(candles)):
        h=candles[i].high; l=candles[i].low; pc=candles[i-1].close
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(tr) < period: return None
    atr=[sum(tr[:period])/period]
    for i in range(period, len(tr)):
        atr.append((atr[-1]*(period-1)+tr[i])/period)
    return atr[-1]

def calc_keltner(closes, atr_val, period=20, mult=2.5):
    ema20 = calc_ema(closes, period)
    if ema20 is None or atr_val is None: return None
    return {"ema": ema20, "upper": ema20+atr_val*mult, "lower": ema20-atr_val*mult}

# --- M30 trend determination ---
def get_m30_trend(m30_closes, m30_idx, lookback=5):
    """
    Determine M30 direction:
    - Use EMA(20) slope over last `lookback` periods
    - Price vs SMA(50) for larger trend context
    Returns 'UP', 'DOWN', or 'NEUTRAL'
    """
    # Need enough data
    need = 60  # enough for EMA20 + lookback
    if m30_idx < need or m30_idx >= len(m30_closes):
        return 'NEUTRAL'

    sub = m30_closes[:m30_idx+1]

    # EMA20 slope
    ema20 = calc_ema_series(sub, 20)
    if ema20 is None or len(ema20) < lookback + 1:
        return 'NEUTRAL'

    ema_slope = ema20[-1] - ema20[-lookback]
    current_price = sub[-1]
    ema_current = ema20[-1]

    # SMA50 for larger context
    sma50 = calc_sma(sub, 50)
    if sma50 is None:
        return 'NEUTRAL'

    # Combine: EMA slope direction + price relative to SMA50
    slope_up = ema_slope > 0
    slope_down = ema_slope < 0
    above_sma50 = current_price > sma50
    below_sma50 = current_price < sma50

    # Strong uptrend: EMA slope up AND price above SMA50
    if slope_up and above_sma50:
        return 'UP'
    # Strong downtrend: EMA slope down AND price below SMA50
    if slope_down and below_sma50:
        return 'DOWN'
    # Weak: check if at least one condition aligns
    if slope_up:
        return 'UP'
    if slope_down:
        return 'DOWN'

    return 'NEUTRAL'

# --- Parameters ---
OVERSOLD = 30; OVERBOUGHT = 65; DIV_LOOKBACK = 10
BB_STD = 2.5; STOCH_K = 9; ATR_PERIOD = 20; KC_MULT = 2.5
MIN_BARS = 250
COMMISSION = 0.5

# --- Run backtest (two versions) ---

def run_backtest(use_m30_filter=False):
    """Run V6 backtest. If use_m30_filter=True, also require M30 trend alignment."""
    signals = []
    trades = []
    position = None
    entry_price = 0; entry_idx = 0

    closes_list = [c.close for c in h1_candles]
    m30_closes_list = [c.close for c in m30_candles]

    for i in range(MIN_BARS, len(h1_candles)):
        c = h1_candles[i]; close = c.close; low = c.low; high = c.high
        sc = closes_list[:i+1]
        sca = h1_candles[:i+1]

        sma200 = calc_sma(sc, 200)
        if sma200 is None: continue
        stoch = calc_stoch(sca, STOCH_K)
        if stoch is None: continue
        rsi = calc_rsi(sc)
        if rsi is None: continue

        k_curr = stoch["curr_k"]; k_prev = stoch["prev_k"]

        macd = calc_macd(sc)
        bottom_div = check_bottom_div(macd["hist_values"], DIV_LOOKBACK) if macd else False
        top_div = check_top_div(macd["hist_values"], DIV_LOOKBACK) if macd else False

        bb = calc_bb(sc, 20, BB_STD)
        if bb is None: continue
        bb_lower = bb["lower"]

        atr_val = calc_atr(sca, ATR_PERIOD)
        if atr_val is None: continue

        kc = calc_keltner(sc, atr_val, 20, KC_MULT)
        if kc is None: continue
        kc_lower = kc["lower"]; kc_upper = kc["upper"]

        vol_recent = sum(closes_list[max(0,i-9):i+1])/min(10,i+1)
        low_vol = atr_val < vol_recent * 0.02

        # --- M30 direction ---
        m30_dir = 'NEUTRAL'
        if use_m30_filter:
            m30_idx = find_m30_at_h1(int(c.time))
            if m30_idx >= 0:
                m30_dir = get_m30_trend(m30_closes_list, m30_idx, lookback=5)
        m30_up = m30_dir == 'UP'
        m30_down = m30_dir == 'DOWN'

        # Long scoring
        long_score = 0; long_d = []
        if close > sma200: long_score += 1; long_d.append("TREND+")
        if k_curr < OVERSOLD or k_prev < OVERSOLD: long_score += 1; long_d.append("KDJ-OS")
        if low <= bb_lower: long_score += 1; long_d.append("BB-BOT")
        if low <= kc_lower: long_score += 1; long_d.append("KC-BOT")
        if bottom_div: long_score += 2; long_d.append("DIVERG")
        if rsi < 30: long_score += 1; long_d.append("RSI-OS")
        if low_vol: long_score += 1; long_d.append("LOW-VOL")
        if m30_up: long_score += 1; long_d.append("M30-UP")
        elif m30_down: long_score -= 1  # penalty for wrong M30 direction

        # Short scoring
        short_score = 0; short_d = []
        if close <= sma200:
            if k_curr > OVERBOUGHT: short_score += 1; short_d.append("KDJ-OB")
            if high >= kc_upper: short_score += 1; short_d.append("KC-TOP")
            if top_div: short_score += 2; short_d.append("TOP-DIV")
            if rsi > 70: short_score += 1; short_d.append("RSI-OB")
            if m30_down: short_score += 1; short_d.append("M30-DN")
            elif m30_up: short_score -= 1

        sig = None
        if use_m30_filter:
            # Soft M30: use scoring bonus (already added above), keep threshold=3
            # M30 contributes +1 for alignment, -1 for opposition
            # When M30 data is unavailable (m30_dir='NEUTRAL'), no effect
            if long_score >= 3: sig = "BUY"
            elif short_score >= 3: sig = "SELL"
        else:
            # Baseline: same 3+ threshold without M30 scoring
            if long_score >= 3: sig = "BUY"
            elif short_score >= 3: sig = "SELL"

        ts = datetime.fromtimestamp(int(c.time)).strftime('%m-%d %H:%M')

        if sig and position is None:
            position = sig; entry_price = close; entry_idx = i
            if use_m30_filter:
                signals.append((ts, close, sig, long_score, short_score, f"M30:{m30_dir} " + " ".join(long_d) if long_d else "-"))
            else:
                signals.append((ts, close, sig, long_score, short_score, " ".join(long_d) if long_d else "-"))
        elif sig and sig != position and position is not None:
            pnl = (close - entry_price)*1.0 - COMMISSION if position == "BUY" else (entry_price - close)*1.0 - COMMISSION
            trades.append({
                "entry_time": datetime.fromtimestamp(int(h1_candles[entry_idx].time)).strftime('%m-%d %H:%M'),
                "exit_time": ts, "direction": position,
                "entry_price": round(entry_price,2), "exit_price": round(close,2),
                "pnl": round(pnl,2), "bars": i-entry_idx
            })
            position = sig; entry_price = close; entry_idx = i
            signals.append((ts, close, f"{sig}(rev)", long_score, short_score, ""))

    if position is not None:
        last = h1_candles[-1]
        pnl = (last.close - entry_price)*1.0 - 0.5 if position == "BUY" else (entry_price - last.close)*1.0 - 0.5
        trades.append({
            "entry_time": datetime.fromtimestamp(int(h1_candles[entry_idx].time)).strftime('%m-%d %H:%M'),
            "exit_time": "NOW", "direction": position,
            "entry_price": round(entry_price,2), "exit_price": round(last.close,2),
            "pnl": round(pnl,2), "bars": len(h1_candles)-1-entry_idx
        })

    closed = [t for t in trades if t['exit_time'] != 'NOW']
    total_pnl = sum(t['pnl'] for t in closed)
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]

    return {
        "total_pnl": total_pnl,
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins)/len(closed)*100,1) if closed else 0,
        "avg_win": round(sum(t['pnl'] for t in wins)/len(wins),2) if wins else 0,
        "avg_loss": round(sum(t['pnl'] for t in losses)/len(losses),2) if losses else 0,
        "best": round(max(t['pnl'] for t in wins),2) if wins else 0,
        "worst": round(min(t['pnl'] for t in losses),2) if losses else 0,
        "trades": closed,
        "signals": signals,
    }


# --- Run both versions ---
print(f"\n{'='*70}")
print(f"  V6 Hybrid Backtest — Baseline vs M30 Direction Filter")
print(f"{'='*70}")
print(f"  Data: {len(h1_candles)} H1 candles, {len(m30_candles)} M30 candles")
print(f"  Period: {datetime.fromtimestamp(int(h1_candles[MIN_BARS].time)).strftime('%Y-%m-%d %H:%M')} ~ "
      f"{datetime.fromtimestamp(int(h1_candles[-1].time)).strftime('%Y-%m-%d %H:%M')}")

baseline = run_backtest(use_m30_filter=False)
filtered = run_backtest(use_m30_filter=True)

for label, result in [("Baseline (no M30 filter)", baseline), ("With M30 direction filter", filtered)]:
    print(f"\n  [{label}]")
    print(f"  Signals: {len(result['signals'])}  |  Trades: {result['total_trades']}")
    print(f"  Total PnL:     ${result['total_pnl']:.2f}")
    print(f"  Win / Loss:    {result['wins']} / {result['losses']}  (Win Rate: {result['win_rate']}%)")
    print(f"  Avg Win:       ${result['avg_win']:.2f}  |  Avg Loss: ${result['avg_loss']:.2f}")
    print(f"  Best:          ${result['best']:.2f}  |  Worst: ${result['worst']:.2f}")

    # Recent trades
    trades = result['trades']
    print(f"  Recent trades (last {min(5, len(trades))}):")
    for t in trades[-5:]:
        m = "+" if t['pnl'] > 0 else "-"
        print(f"    {m} {t['direction']:4s} {t['entry_price']:>7.2f} -> {t['exit_price']:>7.2f}  "
              f"${t['pnl']:>7.2f}  ({t['entry_time']}~{t['exit_time']})")

# Comparison
print(f"\n{'='*70}")
print(f"  Comparison Summary")
print(f"{'='*70}")
pnl_diff = filtered['total_pnl'] - baseline['total_pnl']
trade_diff = filtered['total_trades'] - baseline['total_trades']
print(f"  PnL change:       ${pnl_diff:+.2f} ({pnl_diff/baseline['total_pnl']*100:+.1f}% vs baseline)")
print(f"  Trade count:      {trade_diff:+d} ({trade_diff/baseline['total_trades']*100:+.1f}% vs baseline)")
print(f"  Win rate change:  {filtered['win_rate'] - baseline['win_rate']:+.1f}%")
print(f"  Avg win change:   ${filtered['avg_win'] - baseline['avg_win']:+.2f}")
print(f"  Avg loss change:  ${filtered['avg_loss'] - baseline['avg_loss']:+.2f}")

# Save
with open("backtest/v6_live_backtest_result.json", "w") as f:
    json.dump({
        "baseline": {k: v for k, v in baseline.items() if k != 'trades'},
        "with_m30_filter": {k: v for k, v in filtered.items() if k != 'trades'},
        "comparison": {
            "pnl_diff": round(pnl_diff, 2),
            "trade_diff": trade_diff,
        }
    }, f, indent=2)
print(f"\n  Results saved to backtest/v6_live_backtest_result.json")
