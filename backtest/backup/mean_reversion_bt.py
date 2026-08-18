"""
均值回归反向模式回测 — H1 v6_hybrid 策略
=========================================
对比 3 种模式:
  A. 原始（不反向）
  B. 无条件反向（极端位置反转信号）
  C. 状态自适应反向（仅震荡市反转）

数据: data/market_data.db (H1: 2024-01 ~ 2026-06, ~8700 根)
运行: python backtest/mean_reversion_bt.py
"""
import os
import sys
import sqlite3
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# --- 路径 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# 共享指标模块（与 DataFactory 口径一致：TA-Lib + numpy）
from indicators.common import (
    calc_ema, calc_ema_series,
    calc_sma,
    calc_rsi,
    calc_stoch,
    calc_macd,
    calc_bb,
    calc_atr as calc_atr_from_lists,
    calc_keltner,
    calc_adx,
)

# ============================================================
# 数据加载
# ============================================================
def load_h1_data():
    """从 SQLite 加载 H1 K线"""
    db_path = os.path.join(PROJECT_ROOT, "data", "market_data.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
    ).fetchall()
    conn.close()
    candles = []
    for r in rows:
        candles.append({
            'time': int(r[0]),
            'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5],
            'ts_str': datetime.fromtimestamp(int(r[0])).strftime('%Y-%m-%d %H:%M'),
        })
    return candles


def load_m30_data():
    """从 SQLite 加载 M30 K线（M30 数据有限，从 2026-03 开始）"""
    db_path = os.path.join(PROJECT_ROOT, "data", "market_data.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
    ).fetchall()
    conn.close()
    ts_list = [int(r[0]) for r in rows]
    closes = [r[4] for r in rows]
    return ts_list, closes


def load_ohlcv(timeframe):
    """通用 K线加载 (M5/M15/M30/H1/H4/D1)"""
    db_path = os.path.join(PROJECT_ROOT, "data", "market_data.db")
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe=? ORDER BY timestamp",
        (timeframe,),
    ).fetchall()
    conn.close()
    candles = []
    for r in rows:
        candles.append({
            'time': int(r[0]),
            'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5],
            'ts_str': datetime.fromtimestamp(int(r[0])).strftime('%Y-%m-%d %H:%M'),
        })
    return candles


# ============================================================
# 指标计算 — 委托至共享模块 indicators/common.py
# ============================================================
# calc_ema, calc_ema_series, calc_sma, calc_rsi, calc_bb,
# calc_atr_from_lists(=calc_atr), calc_keltner, calc_adx
# 已由 indicators.common 提供（TA-Lib + numpy，与 DataFactory 一致）

def calc_stoch(closes_highs_lows, k_period=9, slowing=3, d_period=3):
    """兼容旧签名：接收 [highs, lows, closes] 列表"""
    highs, lows, closes = closes_highs_lows
    result = calc_stoch_internal(highs, lows, closes, k_period, slowing, d_period)
    if result is None:
        return None
    return {
        "curr_k": result["k"], "prev_k": result["prev_k"],
        "curr_d": result["d"], "prev_d": result["prev_d"],
    }

def calc_stoch_internal(highs, lows, closes, k_period=9, slowing=3, d_period=3):
    """调用共享模块的 calc_stoch"""
    return calc_stoch_shared(highs, lows, closes, k_period, slowing, d_period)

# 导入共享模块的 calc_stoch
from indicators.common import calc_stoch as calc_stoch_shared


def calc_macd(closes):
    """兼容旧签名：返回 {"macd", "signal", "hist_values"}"""
    result = calc_macd_shared(closes, fast=12, slow=26, signal=9)
    if result is None:
        return None
    return {
        "macd": result["macd"],
        "signal": result["signal"],
        "hist_values": [result["hist"]],  # 旧版返回完整列表，简化为末值
    }

from indicators.common import calc_macd as calc_macd_shared


def check_bottom_div(hist, lookback=10):
    n = len(hist); start = n - lookback * 2
    if start < 1: return False
    lows = []
    for i in range(start + 1, n - 1):
        if hist[i] < hist[i - 1] and hist[i] < hist[i + 1]:
            lows.append((i, hist[i]))
    if len(lows) < 2: return False
    return lows[-1][1] > lows[-2][1]

def check_top_div(hist, lookback=10):
    n = len(hist); start = n - lookback * 2
    if start < 1: return False
    highs = []
    for i in range(start + 1, n - 1):
        if hist[i] > hist[i - 1] and hist[i] > hist[i + 1]:
            highs.append((i, hist[i]))
    if len(highs) < 2: return False
    return highs[-1][1] < highs[-2][1]


def calc_adx_proxy(highs, lows, period=14):
    """⚠️ DEPRECATED 2026-06-19: 这个不是真正的 ADX, 是效率比 (0-1 范围).
    实测在 M30 上范围 0.04-0.54, 永远低于 0.55 阈值, 导致 is_ranging 永远 True.
    请改用 calc_adx_real() (Wilder/TA-Lib, 0-100 范围).
    """
    if len(highs) < period: return None
    sub_h = highs[-period:]
    sub_l = lows[-period:]
    range_hl = max(sub_h) - min(sub_l)
    sum_hl = sum(h - l for h, l in zip(sub_h, sub_l))
    if range_hl <= 0: return 0
    return sum_hl / (range_hl * period)


def calc_adx_real(highs, lows, closes, period=14):
    """真 ADX — 委托至共享模块 indicators.common.calc_adx"""
    return calc_adx(highs, lows, closes, period)


def _calc_adx_wilder(highs, lows, closes, period=14):
    """Wilder ADX 纯 numpy 实现 (TA-Lib 不可用时回退) — 委托至共享模块"""
    from indicators.common import _calc_adx_wilder as _impl
    return _impl(highs, lows, closes, period)

# ============================================================
# v6_hybrid 信号生成
# ============================================================
def generate_v6_signal(candles, idx, m30_data=None):
    """生成 v6_hybrid 8 因子评分 + 原始信号

    Returns: dict with long_score, short_score, signal, factors, indicators
    """
    if idx < 250:
        return None
    sub = candles[:idx + 1]
    closes = [c['close'] for c in sub]
    highs = [c['high'] for c in sub]
    lows = [c['low'] for c in sub]
    close = closes[-1]
    high = highs[-1]
    low = lows[-1]

    sma200 = calc_sma(closes, 200)
    if sma200 is None: return None

    stoch = calc_stoch([highs, lows, closes])
    if stoch is None: return None
    k_curr, k_prev = stoch["curr_k"], stoch["prev_k"]

    rsi = calc_rsi(closes, 14)
    if rsi is None: return None

    macd = calc_macd(closes)
    bottom_div = check_bottom_div(macd["hist_values"], 10) if macd else False
    top_div = check_top_div(macd["hist_values"], 10) if macd else False

    bb = calc_bb(closes, 20, 2.5)
    if bb is None: return None
    bb_lower, bb_width = bb["lower"], bb["width"]

    atr_val = calc_atr_from_lists(highs, lows, closes, 20)
    if atr_val is None: return None

    kc = calc_keltner(closes, atr_val, 20, 2.5)
    if kc is None: return None
    kc_lower, kc_upper = kc["lower"], kc["upper"]

    ema21 = calc_ema(closes, 21)
    if ema21 is None: return None

    # ── Long scoring ──
    long_score = 0; long_factors = []
    if close > sma200: long_score += 1; long_factors.append("TREND+")
    if k_curr < 30 or k_prev < 30: long_score += 1; long_factors.append("KDJ-OS")
    if low <= bb_lower: long_score += 1; long_factors.append("BB-BOT")
    if low <= kc_lower: long_score += 1; long_factors.append("KC-BOT")
    if bottom_div: long_score += 2; long_factors.append("DIVERG")
    if rsi < 30: long_score += 1; long_factors.append("RSI-OS")

    # 低波（BB 宽度 < 4%）
    if bb_width < 0.04: long_score += 1; long_factors.append("LOW-VOL")

    # ── Short scoring ──
    short_score = 0; short_factors = []
    if k_curr > 65: short_score += 1; short_factors.append("KDJ-OB")
    if high >= kc_upper: short_score += 1; short_factors.append("KC-TOP")
    if top_div: short_score += 2; short_factors.append("TOP-DIV")
    if rsi > 70: short_score += 1; short_factors.append("RSI-OB")

    # ── 原始信号 ──
    signal = None
    if long_score >= 3: signal = "BUY"
    elif short_score >= 3: signal = "SELL"

    # ── 距 EMA21 的偏离（ATR 倍数）──
    dist_atr = (close - ema21) / atr_val if atr_val > 0 else 0

    # ── Regime ──
    adx_p = calc_adx_proxy(highs, lows, 14) or 0
    regime = "ranging" if (adx_p < 0.55 and bb_width < 0.04) else ("trending" if adx_p > 0.75 else "transition")

    return {
        "signal": signal,
        "long_score": long_score, "short_score": short_score,
        "long_factors": long_factors, "short_factors": short_factors,
        "close": close, "ema21": ema21, "atr": atr_val,
        "dist_atr": dist_atr, "regime": regime, "bb_width": bb_width,
        "rsi": rsi, "adx_proxy": adx_p,
    }


# ============================================================
# 反向模式
# ============================================================
def apply_reverse_mode(signal_info, mode, reverse_threshold=0.8):
    """根据模式应用反向逻辑

    mode: 'A' = 原始 / 'B' = 无条件反向 / 'C' = 状态自适应反向
    """
    if signal_info is None or signal_info["signal"] is None:
        return signal_info["signal"] if signal_info else None, []

    original = signal_info["signal"]
    dist_atr = signal_info["dist_atr"]
    regime = signal_info["regime"]
    tags = []

    if mode == "A":
        return original, tags

    # 反向触发条件: |dist_atr| > threshold
    if abs(dist_atr) < reverse_threshold:
        return original, tags

    if mode == "B":
        # 无条件反向
        if original == "BUY" and dist_atr > 0:
            tags.append(f"REV→SELL({dist_atr:+.1f}σ)")
            return "SELL", tags
        elif original == "SELL" and dist_atr < 0:
            tags.append(f"REV→BUY({dist_atr:+.1f}σ)")
            return "BUY", tags

    elif mode == "C":
        # 状态自适应：仅震荡市反向
        if regime != "ranging":
            return original, tags
        if original == "BUY" and dist_atr > 0:
            tags.append(f"REG-REV→SELL({regime},{dist_atr:+.1f}σ)")
            return "SELL", tags
        elif original == "SELL" and dist_atr < 0:
            tags.append(f"REG-REV→BUY({regime},{dist_atr:+.1f}σ)")
            return "BUY", tags

    return original, tags


# ============================================================
# 回测引擎（简化版：开仓即平仓反向，2x ATR 硬止损）
# ============================================================
@dataclass
class Trade:
    entry_time: str
    exit_time: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl: float = 0.0
    bars: int = 0
    exit_reason: str = ""
    reverse_tag: str = ""


def run_backtest_mode(candles, mode, reverse_threshold=0.8, sl_atr_mult=2.0, lot_size=0.01, commission=0.5):
    """运行回测（一种模式）"""
    trades = []
    position = None
    entry_price = 0.0
    entry_idx = 0
    entry_signal_dist = 0.0
    reverse_tag = ""

    n = len(candles)

    for i in range(250, n):
        c = candles[i]
        sig_info = generate_v6_signal(candles, i)
        signal, tags = apply_reverse_mode(sig_info, mode, reverse_threshold)

        # ── 开仓 ──
        if signal and position is None:
            position = signal
            entry_price = c['close']
            entry_idx = i
            entry_signal_dist = sig_info["dist_atr"]
            reverse_tag = tags[0] if tags else ""

        # ── 持仓管理：硬止损 + 反向信号平仓 ──
        elif position is not None:
            atr_val = sig_info["atr"] if sig_info else 0
            pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])

            # 硬止损
            if atr_val > 0 and pnl_pts < -atr_val * sl_atr_mult:
                exit_p = c['close']
                pnl = pnl_pts * 10 * lot_size - commission  # 1pt = $1 for 0.01 lot (简化)
                trades.append(Trade(
                    entry_time=candles[entry_idx]['ts_str'],
                    exit_time=c['ts_str'],
                    direction=position,
                    entry_price=entry_price, exit_price=exit_p,
                    pnl=round(pnl, 2), bars=i - entry_idx,
                    exit_reason="hard_stop",
                    reverse_tag=reverse_tag,
                ))
                position = None

            # 反向信号平仓
            elif signal and signal != position:
                exit_p = c['close']
                pnl = pnl_pts * 10 * lot_size - commission
                trades.append(Trade(
                    entry_time=candles[entry_idx]['ts_str'],
                    exit_time=c['ts_str'],
                    direction=position,
                    entry_price=entry_price, exit_price=exit_p,
                    pnl=round(pnl, 2), bars=i - entry_idx,
                    exit_reason="reverse_signal",
                    reverse_tag=reverse_tag,
                ))
                position = signal
                entry_price = c['close']
                entry_idx = i
                entry_signal_dist = sig_info["dist_atr"]
                reverse_tag = tags[0] if tags else ""

    # 最后一笔
    if position is not None:
        c = candles[-1]
        pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])
        pnl = pnl_pts * 10 * lot_size - commission
        trades.append(Trade(
            entry_time=candles[entry_idx]['ts_str'],
            exit_time=c['ts_str'],
            direction=position,
            entry_price=entry_price, exit_price=c['close'],
            pnl=round(pnl, 2), bars=n - 1 - entry_idx,
            exit_reason="end_of_data",
            reverse_tag=reverse_tag,
        ))

    return trades


# ============================================================
# 统计 & 报告
# ============================================================
def compute_stats(trades, mode_name):
    closed = [t for t in trades if t.exit_reason != "end_of_data"]
    if not closed:
        return {
            "mode": mode_name, "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
            "max_drawdown": 0, "profit_factor": 0, "avg_bars": 0,
            "reverse_count": 0,
        }

    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in closed)
    avg_pnl = total_pnl / len(closed)
    reverse_count = sum(1 for t in closed if t.reverse_tag)

    # 最大回撤（基于累计 P/L 序列）
    cum = 0
    peak = 0
    max_dd = 0
    for t in closed:
        cum += t.pnl
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)

    # 盈亏比
    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        "mode": mode_name,
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars": round(sum(t.bars for t in closed) / len(closed), 1),
        "reverse_count": reverse_count,
    }


def print_comparison(results):
    print(f"\n{'='*100}")
    print(f"  均值回归反向模式回测对比 (H1 v6_hybrid, 2024-01 ~ 2026-06, 8700+ 根 K 线)")
    print(f"{'='*100}")
    print(f"{'模式':<22} {'交易':>6} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'反向':>5} {'均K线':>7}")
    print(f"{'-'*100}")
    for r in results:
        print(f"{r['mode']:<22} {r['trades']:>6} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['reverse_count']:>5} {r['avg_bars']:>7.0f}")
    print(f"{'='*100}")
    print(f"\n📊 模式说明：")
    print(f"  A = 原始（不反向）")
    print(f"  B = 无条件反向（|距 EMA21| > 0.8 ATR 触发反向）")
    print(f"  C = 状态自适应反向（仅震荡市 ADX<0.55 + BB<4% 才反向）")
    print(f"\n✅ 评估标准：")
    print(f"  - C 胜率 > A 胜率 + 10pp → 启用反向模式")
    print(f"  - C 最大回撤 < $50 → 安全")
    print(f"  - C 盈亏比 > A 盈亏比 → 质量提升")


def save_results_csv(results, output_path):
    """保存结果到 CSV"""
    import csv
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\n💾 结果已保存: {output_path}")


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("  均值回归反向模式回测")
    print("=" * 60)
    print("\n加载 H1 数据...")
    candles = load_h1_data()
    print(f"  {len(candles)} 根 H1 K线")
    print(f"  范围: {candles[0]['ts_str']} ~ {candles[-1]['ts_str']}")

    print("\n加载 M30 数据...")
    m30_ts, m30_closes = load_m30_data()
    print(f"  {len(m30_ts)} 根 M30 K线（M30 仅用于参考，H1 为主）")

    print("\n运行 3 种模式回测...")
    modes = [
        ("A-原始（不反向）", "A"),
        ("B-无条件反向", "B"),
        ("C-状态自适应反向", "C"),
    ]

    results = []
    for name, mode in modes:
        print(f"  运行 {name}...", end="", flush=True)
        trades = run_backtest_mode(candles, mode, reverse_threshold=0.8)
        stats = compute_stats(trades, name)
        results.append(stats)
        print(f" 完成 ({stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f})")

    # 输出对比
    print_comparison(results)

    # 保存 CSV
    output_path = os.path.join(SCRIPT_DIR, "mean_reversion_results.csv")
    save_results_csv(results, output_path)

    # 决策建议
    print("\n" + "=" * 60)
    print("  📋 决策建议")
    print("=" * 60)
    a = results[0]
    b = results[1]
    c = results[2]
    if c["win_rate"] > a["win_rate"] + 10 and c["max_drawdown"] < 50:
        print(f"✅ 推荐启用 C-状态自适应反向")
        print(f"   - 胜率提升: {c['win_rate'] - a['win_rate']:+.1f}pp")
        print(f"   - P/L 改善: ${c['total_pnl'] - a['total_pnl']:+.2f}")
        print(f"   - 反向次数: {c['reverse_count']}")
    elif c["win_rate"] > a["win_rate"]:
        print(f"🟡 C 组胜率略优（+{c['win_rate'] - a['win_rate']:.1f}pp）但 < 10pp 门槛，建议小仓位试运行")
    else:
        print(f"❌ C 组无明显优势，不建议启用反向模式")
    print()


if __name__ == "__main__":
    main()
