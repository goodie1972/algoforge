"""
6个月全策略回测引擎 v1.1
==========================
用法: python scripts/backtest_6months.py [--months=6]
"""
import argparse
import importlib
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)
logging.getLogger('data').setLevel(logging.CRITICAL)
logging.getLogger('core').setLevel(logging.CRITICAL)
logging.getLogger('services').setLevel(logging.CRITICAL)

import numpy as np
import talib
from data.database import get_conn
from core.bridge import Candle, OrderType, MT4BridgeBase

COMMISSION = 0.50
LOT_SIZE = 0.01
CONTRACT = 100
INITIAL_CASH = 10000.0
STRATEGY_DIR = os.path.join(os.path.dirname(__file__), "..", "strategies")


class MockBridge(MT4BridgeBase):
    def __init__(self):
        self._candles = {}
    def set_candles(self, tf, candles):
        self._candles[tf] = candles
    def connect(self):
        return True
    def disconnect(self):
        pass
    def get_candles(self, symbol, timeframe, count=100, offset=0):
        return self._candles.get(timeframe, [])[-count:] if count else self._candles.get(timeframe, [])
    def get_tick_price(self, symbol):
        return (0.0, 0.0)
    def get_positions(self, symbol=None):
        return []
    def open_order(self, *args, **kwargs):
        return 12345
    def close_order(self, *args, **kwargs):
        return True
    def modify_order(self, *args, **kwargs):
        return True
    def get_account_info(self):
        return None
    def get_orders(self, *args, **kwargs):
        return []


def load_data(start_ts, end_ts):
    conn = get_conn()
    data = {}
    for tf in ["M5", "M15", "M30", "H1", "H4"]:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE timeframe=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
            (tf, start_ts, end_ts)
        ).fetchall()
        if not rows:
            data[tf] = {"candles": [], "indicators": []}
            continue
        candles = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3],
                          close=r[4], volume=r[5]) for r in rows]
        closes = np.array([c.close for c in candles], dtype=float)
        highs = np.array([c.high for c in candles], dtype=float)
        lows = np.array([c.low for c in candles], dtype=float)
        volumes = np.array([c.volume for c in candles], dtype=float)
        n = len(candles)
        indicators = [{} for _ in range(n)]

        rsi = talib.RSI(closes, timeperiod=14)
        rsi_5 = talib.RSI(closes, timeperiod=5)
        rsi_10 = talib.RSI(closes, timeperiod=10)
        mfi = talib.MFI(highs, lows, closes, volumes, timeperiod=14)
        bbu, bbm, bbl = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        ema9 = talib.EMA(closes, timeperiod=9)
        ema21 = talib.EMA(closes, timeperiod=21)
        ema120 = talib.EMA(closes, timeperiod=120)
        ema300 = talib.EMA(closes, timeperiod=300)
        sma14 = talib.SMA(closes, timeperiod=14)
        sma20 = talib.SMA(closes, timeperiod=20)
        sma50 = talib.SMA(closes, timeperiod=50)
        atr = talib.ATR(highs, lows, closes, timeperiod=14)
        atr_20 = talib.ATR(highs, lows, closes, timeperiod=20)
        adx = talib.ADX(highs, lows, closes, timeperiod=14)
        pdi = talib.PLUS_DI(highs, lows, closes, timeperiod=14)
        ndi = talib.MINUS_DI(highs, lows, closes, timeperiod=14)
        macd, macdsignal, macdhist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        sk, sd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowd_period=3)
        sk21, sd21 = talib.STOCH(highs, lows, closes, fastk_period=21, slowk_period=5, slowd_period=3)
        sk14, sd14 = talib.STOCH(highs, lows, closes, fastk_period=14, slowk_period=3, slowd_period=3)
        vol_sma20 = talib.SMA(volumes, timeperiod=20)
        bb_width = bbu - bbl

        for i in range(n):
            c = closes[i]
            ind = {
                "close": float(c),
                "trend": "UP" if sma14[i] and c > sma14[i] else "DOWN" if sma14[i] else "NEUTRAL",
                "rsi": float(rsi[i]) if not np.isnan(rsi[i]) else None,
                "rsi_5": float(rsi_5[i]) if not np.isnan(rsi_5[i]) else None,
                "rsi_10": float(rsi_10[i]) if not np.isnan(rsi_10[i]) else None,
                "mfi": float(mfi[i]) if not np.isnan(mfi[i]) else None,
                "bb": {"upper": float(bbu[i]) if not np.isnan(bbu[i]) else None,
                        "mid": float(bbm[i]) if not np.isnan(bbm[i]) else None,
                        "lower": float(bbl[i]) if not np.isnan(bbl[i]) else None},
                "bb_width": float(bb_width[i]) if not np.isnan(bb_width[i]) else None,
                "ema_9": float(ema9[i]) if not np.isnan(ema9[i]) else None,
                "ema_21": float(ema21[i]) if not np.isnan(ema21[i]) else None,
                "ema_120": float(ema120[i]) if not np.isnan(ema120[i]) else None,
                "ema_300": float(ema300[i]) if not np.isnan(ema300[i]) else None,
                "sma_14": float(sma14[i]) if not np.isnan(sma14[i]) else None,
                "sma_20": float(sma20[i]) if not np.isnan(sma20[i]) else None,
                "sma_50": float(sma50[i]) if not np.isnan(sma50[i]) else None,
                "atr": float(atr[i]) if not np.isnan(atr[i]) else None,
                "atr_20": float(atr_20[i]) if not np.isnan(atr_20[i]) else None,
                "adx": float(adx[i]) if not np.isnan(adx[i]) else None,
                "pdi": float(pdi[i]) if not np.isnan(pdi[i]) else None,
                "ndi": float(ndi[i]) if not np.isnan(ndi[i]) else None,
                "macd": {"macd": float(macd[i]) if not np.isnan(macd[i]) else None,
                          "signal": float(macdsignal[i]) if not np.isnan(macdsignal[i]) else None,
                          "histogram": float(macdhist[i]) if not np.isnan(macdhist[i]) else None},
                "stoch_5_3_3": {"k": float(sk[i]) if not np.isnan(sk[i]) else None,
                                 "d": float(sd[i]) if not np.isnan(sd[i]) else None},
                "stoch_21_5_3": {"k": float(sk21[i]) if not np.isnan(sk21[i]) else None,
                                  "d": float(sd21[i]) if not np.isnan(sd21[i]) else None},
                "stoch_14_3_3": {"k": float(sk14[i]) if not np.isnan(sk14[i]) else None,
                                  "d": float(sd14[i]) if not np.isnan(sd14[i]) else None},
                "volume_sma_20": float(vol_sma20[i]) if not np.isnan(vol_sma20[i]) else None,
                "price_position": 0.5,
            }
            if i >= 20:
                hi20 = max(closes[i-19:i+1]); lo20 = min(closes[i-19:i+1])
                ind["price_position"] = (c - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5
            if i >= 4:
                widths = [bb_width[j] for j in range(i-3, i+1) if not np.isnan(bb_width[j])]
                if len(widths) >= 2:
                    ind["bb_width_direction"] = "up" if widths[-1] > widths[-2] else "down"
            if i >= 1 and not np.isnan(mfi[i]) and not np.isnan(mfi[i-1]):
                ind["mfi_direction"] = "up" if mfi[i] > mfi[i-1] else "down" if mfi[i] < mfi[i-1] else "flat"
            indicators[i] = ind
        data[tf] = {"candles": candles, "indicators": indicators}
    conn.close()
    return data


class BacktestTrade:
    def __init__(self, strategy, signal, entry_time, entry_price, atr_val, magic):
        self.strategy = strategy; self.signal = signal; self.entry_time = entry_time
        self.entry_price = entry_price; self.atr_at_entry = atr_val; self.magic = magic
        self.exit_time = None; self.exit_price = None; self.exit_reason = ""
        self.highest = entry_price; self.lowest = entry_price
        self.pnl = 0.0; self.pips = 0.0
        self.is_buy = signal == "BUY"; self.is_open = True

    def update(self, high, low, close):
        if self.is_buy:
            self.highest = max(self.highest, high); self.lowest = min(self.lowest, low)
        else:
            self.highest = max(self.highest, high); self.lowest = min(self.lowest, low)

    def close(self, price, time, reason=""):
        self.exit_time = time; self.exit_price = price; self.exit_reason = reason
        self.is_open = False
        if self.is_buy: self.pips = price - self.entry_price
        else: self.pips = self.entry_price - price
        self.pnl = self.pips * CONTRACT * LOT_SIZE - COMMISSION * 2


def load_strategies():
    strategies = []
    for fname in sorted(os.listdir(STRATEGY_DIR)):
        if not fname.endswith(".py") or fname in ("__init__.py", "base.py", "scanner.py"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(fname[:-3], os.path.join(STRATEGY_DIR, fname))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if isinstance(cls, type) and hasattr(cls, 'name') and hasattr(cls, 'generate_signal'):
                name = getattr(cls, 'name', '')
                if name and name != "base":
                    magic = getattr(cls, 'STRATEGY_MAGIC', 0)
                    tf = getattr(cls, 'TIMEFRAME', 'H1')
                    strategies.append((name, cls, magic, tf))
                    break
    return strategies


def simulate_exit(trade, close, high, low, atr_val, ema21, bb_mid, current_time):
    trade.update(high, low, close)
    elapsed = current_time - trade.entry_time if trade.entry_time else 0
    is_buy = trade.is_buy

    if atr_val > 0:
        hs = 1.5 * atr_val * CONTRACT * LOT_SIZE
        if is_buy and (trade.entry_price - low) * CONTRACT * LOT_SIZE > hs:
            return "硬止损"
        if not is_buy and (high - trade.entry_price) * CONTRACT * LOT_SIZE > hs:
            return "硬止损"

    if ema21 and atr_val and elapsed > 1800:
        if is_buy and close < ema21 - 0.3 * atr_val: return "EMA21追踪"
        if not is_buy and close > ema21 + 0.3 * atr_val: return "EMA21追踪"

    if bb_mid and atr_val and elapsed > 600:
        if is_buy and close > bb_mid - 0.2 * atr_val: return "BB止盈"
        if not is_buy and close < bb_mid + 0.2 * atr_val: return "BB止盈"

    if elapsed > 3600 * 12: return "超时平仓"
    return None


def run_backtest(strategies, start_ts, end_ts):
    print(f"Loading data...")
    data = load_data(start_ts, end_ts)
    for tf in ["M5", "M15", "M30", "H1", "H4"]:
        print(f"  {tf}: {len(data.get(tf, {}).get('candles', []))} bars")

    results = []
    for name, cls, magic, tf in strategies:
        skip = False
        # 跳过已知有问题的策略
        if name in ("bakome_backup", "bakome_backup_optimized", "xaubot_backup"):
            print(f"\n--- {name} (SKIP: 需要Silver Bullet/session检测)")
            results.append({"name": name, "magic": magic, "timeframe": tf,
                           "total_trades": 0, "total_pnl": 0, "win_rate": 0,
                           "profit_factor": 0, "avg_win": 0, "avg_loss": 0,
                           "largest_win": 0, "largest_loss": 0, "max_drawdown_pct": 0,
                           "avg_hold_seconds": 0, "max_consecutive_losses": 0,
                           "errors": 0, "none_indicator_rate": 0,
                           "score": 0, "grade": "C", "reasons": ["需要Silver Bullet实时检测"]})
            continue

        if name == "stoch_trend_h1" or name == "stoch_trend_h1_optimized":
            print(f"\n--- {name} (SKIP: 需要M15 get_cache)")

        print(f"\n--- {name} (magic={magic}, tf={tf})")

        main_tf = tf if tf in data else "H1"
        if not data[main_tf]["candles"]:
            print(f"  No data for {main_tf}")
            continue

        candles = data[main_tf]["candles"]
        indicators = data[main_tf]["indicators"]
        n = len(candles)

        bridge = MockBridge()
        for t in ["M5", "M15", "M30", "H1", "H4"]:
            bridge.set_candles(t, data[t]["candles"])

        try:
            strategy = cls(bridge, magic=magic, timeframe=main_tf)
        except Exception as e:
            print(f"  Init failed: {e}")
            continue

        # 修补 refresh_data 使其不覆盖 _cached_indicators
        _orig_refresh = strategy.refresh_data
        strategy.refresh_data = lambda count=200: None
        # 手动设置 candles
        strategy.candles = candles[-200:]

        trades = []; open_trade = None
        total_profit = 0.0; wins = 0; losses = 0
        max_drawdown = 0.0; peak_equity = INITIAL_CASH
        errors = 0; none_indicators = 0
        equity_curve = []; warmup = min(200, n - 50)

        for i in range(warmup, n):
            candle = candles[i]; ind = indicators[i]; bar_time = int(candle.time)
            strategy.candles = candles[max(0, i - 200):i + 1]
            strategy._cached_indicators = ind

            if ind.get("rsi") is None or ind.get("atr") is None:
                none_indicators += 1

            # 出场检查
            if open_trade:
                reason = simulate_exit(
                    open_trade, candle.close, candle.high, candle.low,
                    ind.get("atr") or 10.0, ind.get("ema_21") or candle.close,
                    ind.get("bb", {}).get("mid") or candle.close, bar_time)
                if reason:
                    open_trade.close(candle.close, bar_time, reason)
                    trades.append(open_trade)
                    total_profit += open_trade.pnl
                    if open_trade.pnl > 0: wins += 1
                    else: losses += 1
                    open_trade = None

            # 信号
            try:
                result = strategy.generate_signal()
            except Exception as e:
                errors += 1; result = (None, 0, 0, [], [], {})

            # 重新设置指标（防止 refresh_data 覆盖）
            strategy._cached_indicators = ind
            signal = result[0] if isinstance(result, tuple) else result

            # 入场
            if signal and not open_trade:
                atr_val = ind.get("atr") or 10.0
                open_trade = BacktestTrade(name, signal.value, bar_time, candle.close, atr_val, magic)

            # 权益
            unrealized = 0.0
            if open_trade:
                if open_trade.is_buy:
                    unrealized = (candle.close - open_trade.entry_price) * CONTRACT * LOT_SIZE
                else:
                    unrealized = (open_trade.entry_price - candle.close) * CONTRACT * LOT_SIZE
            current_equity = INITIAL_CASH + total_profit + unrealized
            peak_equity = max(peak_equity, current_equity)
            dd = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0
            max_drawdown = max(max_drawdown, dd)
            equity_curve.append({"time": bar_time, "equity": round(current_equity, 2)})

        if open_trade:
            open_trade.close(candles[-1].close, int(candles[-1].time), "")
            trades.append(open_trade); total_profit += open_trade.pnl
            if open_trade.pnl > 0: wins += 1
            else: losses += 1

        # 计算指标
        total_trades = len(trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        avg_win = sum(t.pnl for t in trades if t.pnl > 0) / wins if wins > 0 else 0.0
        avg_loss = sum(t.pnl for t in trades if t.pnl < 0) / losses if losses > 0 else 0.0
        pf = abs(sum(t.pnl for t in trades if t.pnl > 0) / (sum(t.pnl for t in trades if t.pnl < 0) or 0.001))
        lw = max((t.pnl for t in trades), default=0.0)
        ll = min((t.pnl for t in trades), default=0.0)
        avg_hold = sum((t.exit_time - t.entry_time for t in trades if t.exit_time), 0) / max(1, total_trades)
        none_rate = none_indicators / max(1, n - warmup) * 100

        max_cl = 0; cur_cl = 0
        for t in trades:
            if t.pnl < 0: cur_cl += 1; max_cl = max(max_cl, cur_cl)
            else: cur_cl = 0

        result = {
            "name": name, "magic": magic, "timeframe": main_tf,
            "total_trades": total_trades, "total_pnl": round(total_profit, 2),
            "win_rate": round(win_rate, 2), "profit_factor": round(pf, 2),
            "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
            "largest_win": round(lw, 2), "largest_loss": round(ll, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "avg_hold_seconds": round(avg_hold),
            "max_consecutive_losses": max_cl,
            "errors": errors, "none_indicator_rate": round(none_rate, 2),
            "trades": [{"entry_time": t.entry_time, "exit_time": t.exit_time,
                        "signal": t.signal, "entry_price": t.entry_price,
                        "exit_price": t.exit_price, "pnl": round(t.pnl, 2),
                        "exit_reason": t.exit_reason} for t in trades],
            "equity_curve": equity_curve[::max(1, len(equity_curve)//100)],
        }
        results.append(result)
        print(f"  {total_trades} trades | PnL ${total_profit:+.2f} | WR {win_rate:.1f}% | PF {pf:.2f} | DD {max_drawdown:.2f}%")

    return results


def score_results(results):
    scored = []
    for r in results:
        t = r["total_trades"]
        if t < 3:
            scored.append({**r, "score": 0, "grade": "C", "reasons": ["不足3笔"]})
            continue
        if r["total_pnl"] < -50:
            scored.append({**r, "score": 0, "grade": "C", "reasons": [f"PnL${r['total_pnl']}"]})
            continue
        if r["max_drawdown_pct"] > 30:
            scored.append({**r, "score": 0, "grade": "C", "reasons": [f"DD{r['max_drawdown_pct']}%"]})
            continue
        if r["win_rate"] < 20 and t >= 10:
            scored.append({**r, "score": 0, "grade": "C", "reasons": [f"WR{r['win_rate']}%"]})
            continue
        if r["errors"] >= 3:
            scored.append({**r, "score": 0, "grade": "C", "reasons": [f"Errors{r['errors']}"]})
            continue

        pnl_s = min(10, max(0, (r["total_pnl"] + 50) / 10)) if r["total_pnl"] > 0 else 0
        wr_s = 10 if r["win_rate"] >= 60 else 7 if r["win_rate"] >= 50 else 5 if r["win_rate"] >= 40 else 3 if r["win_rate"] >= 30 else 0
        pf_s = 10 if r["profit_factor"] >= 2.0 else 7 if r["profit_factor"] >= 1.5 else 5 if r["profit_factor"] >= 1.2 else 3 if r["profit_factor"] >= 1.0 else 0
        profitability = min(30, pnl_s + wr_s + pf_s)

        dd_s = 10 if r["max_drawdown_pct"] < 5 else 7 if r["max_drawdown_pct"] < 10 else 5 if r["max_drawdown_pct"] < 15 else 3 if r["max_drawdown_pct"] < 20 else 0
        ll_s = 8 if abs(r["largest_loss"]) < 5 else 5 if abs(r["largest_loss"]) < 10 else 3 if abs(r["largest_loss"]) < 15 else 0
        cl_s = 7 if r["max_consecutive_losses"] <= 3 else 5 if r["max_consecutive_losses"] <= 5 else 3 if r["max_consecutive_losses"] <= 7 else 0
        risk_control = min(25, dd_s + ll_s + cl_s)

        signal_quality = min(15, (5 if t <= 7 else 3 if t <= 15 else 1) + 5 + 5)
        efficiency = min(10, (5 if r["total_pnl"] > 0 else 3) + (5 if r["avg_hold_seconds"] >= 3600 else 2))
        stability = (5 if r["none_indicator_rate"] < 1 else 3 if r["none_indicator_rate"] < 5 else 0) + (5 if r["errors"] == 0 else 3 if r["errors"] <= 2 else 0)

        total = profitability + risk_control + signal_quality + efficiency + stability
        grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 50 else "C"
        scored.append({**r, "score": total, "grade": grade,
                       "details": {"profitability": profitability, "risk_control": risk_control,
                                   "signal_quality": signal_quality, "efficiency": efficiency, "stability": stability}})

    return sorted(scored, key=lambda x: x["score"], reverse=True)


def print_report(scored):
    print("\n" + "=" * 70)
    print("  XAUUSD 策略回测报告")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print(f"  {'Grade':^4} | {'Strategy':^30} | {'Trades':^6} | {'PnL':^9} | {'WR':^6} | {'PF':^7} | {'DD':^7} | {'Score':^6}")
    print(f"  {'-'*4}-+-{'-'*30}-+-{'-'*6}-+-{'-'*9}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*6}")
    for r in scored:
        g = r["grade"]
        print(f"  {g:^4} | {r['name'][:30]:^30} | {r['total_trades']:^6} | ${r['total_pnl']:>+7.2f} | {r['win_rate']:>5.1f}% | {r['profit_factor']:>6.2f} | {r['max_drawdown_pct']:>5.2f}% | {r['score']:>5.1f}")

    # 分组
    print("\n" + "=" * 70)
    groups = {
        "TREND": ["gold_auto_research", "momentum_pulse_pro", "sanqing_h1", "sanqing_h1_original",
                  "sanqing_h1_upgraded", "stoch_trend_h1", "stoch_trend_h1_optimized", "stoch_trend_h1_upgraded"],
        "BREAKOUT": ["h1_breakout"],
        "REVERSAL": ["m30_bb_deepreturn", "m30_bb_deepreturn_optimized", "M30_rsi_bb",
                     "mfi_bb_m30", "mfi_bb_m30_optimized", "mfi_bb_m30_upgraded",
                     "m30_vol_return", "rsi_grading_m30", "rsi_grading_m30_optimized", "rsi_grading_m30_upgraded"],
        "PATTERN": ["bakome_backup", "bakome_backup_optimized"],
        "SCORE": ["entry_score_pro", "multi_confluence_quant", "viprasol_sniper"],
        "ML": ["xaubot_backup"],
    }
    for gname, gnames in groups.items():
        g = [r for r in scored if r["name"] in gnames]
        if g:
            print(f"\n[{gname}]:")
            for r in g:
                print(f"  {r['grade']} {r['name'][:30]:30} Score={r['score']:>4} PnL=${r['total_pnl']:>+7.2f} WR={r['win_rate']:>5.1f}%")

    s = [r for r in scored if r["grade"] == "S"]
    a = [r for r in scored if r["grade"] == "A"]
    c = [r for r in scored if r["grade"] == "C"]

    print(f"\nRecommended Captain:")
    for r in (s or a)[:3]:
        print(f"  {r['name']} (Score={r['score']})")

    if c:
        print(f"\nEliminate:")
        for r in c:
            print(f"  {r['name']} - {r.get('reasons', ['Low score'])[0]}")

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "evaluation", "backtest_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "results": scored}, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="6-month backtest")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--start", type=str, default="2026-02-01")
    args = parser.parse_args()
    start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    start_ts = int(start_dt.replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(time.time())

    print(f"Backtest: {args.start} ~ now ({args.months} months)")
    strategies = load_strategies()
    print(f"Loaded {len(strategies)} strategies")

    t0 = time.time()
    results = run_backtest(strategies, start_ts, end_ts)
    elapsed = time.time() - t0
    print(f"\nTime: {elapsed:.0f}s ({elapsed/60:.1f}min)")

    scored = score_results(results)
    print_report(scored)