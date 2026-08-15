"""
stoch_trend_m30 全面回测 — 原始逻辑 vs ADX分级过滤器
==================================================
ADX分级规则:
  - ADX<10: 禁止开仓（极低波动，随机指标不可靠）
  - ADX 10-20: 原始逻辑不变
  - ADX>20: 加DI方向确认（BUY需pdi>ndi, SELL需ndi>pdi）

运行: python backtest/stoch_trend_m30_bt.py
"""
import os
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_ohlcv, calc_ema, calc_atr_from_lists,
    calc_stoch, calc_bb, calc_adx_real,
)

BB_SLOPE_THRESHOLD = 0.01
ADX_RANGE_THRESHOLD = 28
DI_THRESHOLD = 10
TREND_TP_ATR = 4.0
BB_STD = 2.5


def bb_rising_ok(closes, bb_mid, k_curr, k_prev):
    """BB中轨斜率与K线方向一致性检查"""
    if len(closes) < 21:
        return True
    sma20_prev = sum(closes[-21:-1]) / 20
    bb_mid_slope = bb_mid - sma20_prev
    k_rising = k_curr > k_prev
    bb_rising = bb_mid_slope > BB_SLOPE_THRESHOLD
    return bb_rising == k_rising


def run_backtest(candles, adx_graded_filter=False, lot_size=0.01, commission=0.5):
    """
    stoch_trend_m30 完整回测
    adx_graded_filter=True: ADX分级过滤器启用
    返回 (trades, filter_stats)
    """
    trades = []
    filter_stats = {"adx_lt10_blocked": 0, "adx_gt20_blocked": 0}
    position = None
    entry_info = {}

    n = len(candles)

    for i in range(251, n):
        c = candles[i]
        sub = candles[:i + 1]
        closes = [x['close'] for x in sub]
        highs = [x['high'] for x in sub]
        lows = [x['low'] for x in sub]
        close = closes[-1]

        # ── 指标计算 ──
        ma_val = calc_ema(closes, 21)
        if ma_val is None:
            continue

        atr_val = calc_atr_from_lists(highs, lows, closes, 20)
        if atr_val is None or atr_val <= 0:
            continue

        adx_data = calc_adx_real(highs, lows, closes, 14)
        if adx_data is None:
            continue
        adx = adx_data['adx']
        pdi = adx_data['pdi']
        ndi = adx_data['ndi']

        # 前一根K线的pdi/ndi（宽幅震荡DI交叉检测用）
        prev_adx = calc_adx_real(highs[:-1], lows[:-1], closes[:-1], 14) if len(closes) > 15 else None
        prev_pdi = prev_adx['pdi'] if prev_adx else None
        prev_ndi = prev_adx['ndi'] if prev_adx else None

        bb = calc_bb(closes, 20, BB_STD)
        if bb is None:
            continue
        bb_width = bb["width"]

        stoch = calc_stoch([highs, lows, closes], 9, 3, 3)
        if stoch is None:
            continue
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        is_ranging = adx < ADX_RANGE_THRESHOLD

        # BB中轨斜率
        if i >= 1:
            closes_prev_bar = [x['close'] for x in candles[:i]]
            if len(closes_prev_bar) >= 20:
                sma20_prev = sum(closes_prev_bar[-20:]) / 20
                bb_mid_slope = bb["sma"] - sma20_prev
            else:
                bb_mid_slope = 0
        else:
            bb_mid_slope = 0

        # ── 入场 ──
        if position is None:
            signal = None
            regime = None

            # ADX分级过滤器：ADX<10 禁止开仓
            entry_blocked = False
            if adx_graded_filter and adx < 10:
                entry_blocked = True
                filter_stats["adx_lt10_blocked"] += 1

            if not entry_blocked:
                # ── 震荡模式 ──
                if is_ranging:
                    bb_width_threshold = 0.02

                    if bb_width <= bb_width_threshold:
                        # 窄幅震荡：Stoch极端+交叉+价格在EMA21内
                        if (k_curr < 20) and cross_up_now and (close < ma_val):
                            if not adx_graded_filter or adx <= 20 or pdi > ndi:
                                signal = "BUY"
                                regime = "range"
                            else:
                                if adx_graded_filter and adx > 20:
                                    filter_stats["adx_gt20_blocked"] += 1
                        elif (k_curr > 80) and cross_down_now and (close > ma_val):
                            if not adx_graded_filter or adx <= 20 or ndi > pdi:
                                signal = "SELL"
                                regime = "range"
                            else:
                                if adx_graded_filter and adx > 20:
                                    filter_stats["adx_gt20_blocked"] += 1
                    else:
                        # 宽幅震荡：触轨 + K极端 + DI交叉
                        touch_upper = c['high'] >= bb["upper"]
                        touch_lower = c['low'] <= bb["lower"]
                        if i >= 1:
                            c1 = candles[i - 1]
                            touch_upper = touch_upper or c1['high'] >= bb["upper"]
                            touch_lower = touch_lower or c1['low'] <= bb["lower"]

                        di_death = prev_pdi is not None and prev_ndi is not None and prev_pdi >= prev_ndi and pdi < ndi
                        di_golden = prev_pdi is not None and prev_ndi is not None and prev_pdi <= prev_ndi and pdi > ndi

                        if touch_lower and k_curr < 15 and di_golden:
                            if not adx_graded_filter or adx <= 20 or pdi > ndi:
                                signal = "BUY"
                                regime = "range_wide"
                            else:
                                if adx_graded_filter and adx > 20:
                                    filter_stats["adx_gt20_blocked"] += 1
                        elif touch_upper and k_curr > 85 and di_death:
                            if not adx_graded_filter or adx <= 20 or ndi > pdi:
                                signal = "SELL"
                                regime = "range_wide"
                            else:
                                if adx_graded_filter and adx > 20:
                                    filter_stats["adx_gt20_blocked"] += 1

                # ── 趋势模式（只在非震荡时触发）──
                if signal is None and (not is_ranging) and adx >= ADX_RANGE_THRESHOLD:
                    if (pdi - ndi) > DI_THRESHOLD and close > ma_val and cross_up_now:
                        if not adx_graded_filter or adx <= 20 or pdi > ndi:
                            signal = "BUY"
                            regime = "trend"
                        else:
                            if adx_graded_filter and adx > 20:
                                filter_stats["adx_gt20_blocked"] += 1
                    elif (ndi - pdi) > DI_THRESHOLD and close < ma_val and cross_down_now:
                        if not adx_graded_filter or adx <= 20 or ndi > pdi:
                            signal = "SELL"
                            regime = "trend"
                        else:
                            if adx_graded_filter and adx > 20:
                                filter_stats["adx_gt20_blocked"] += 1

            if signal:
                position = signal
                entry_info = {
                    "time": c['ts_str'],
                    "price": close,
                    "idx": i,
                    "ma": ma_val,
                    "atr": atr_val,
                    "regime": regime,
                    "adx": adx,
                    "peak": close,
                    "peak_profit": 0.0,
                }

        # ── 出场 ──
        else:
            is_buy = position == "BUY"
            entry_price = entry_info['price']
            regime = entry_info['regime']
            pnl_pts = (close - entry_price) if is_buy else (entry_price - close)
            exit_reason = None
            exit_price = close

            # 硬止损
            sl_mult = 2.0 if regime == "trend" else 1.0
            if pnl_pts < -atr_val * sl_mult:
                exit_reason = "hard_stop"
                if is_buy:
                    exit_price = entry_price - atr_val * sl_mult
                else:
                    exit_price = entry_price + atr_val * sl_mult

            # 更新峰值 + 利润峰值跟踪
            if is_buy:
                entry_info["peak"] = max(entry_info["peak"], c['high'])
                _cp = close - entry_price
            else:
                entry_info["peak"] = min(entry_info["peak"], c['low'])
                _cp = entry_price - close
            if abs(_cp) < atr_val * 10:
                entry_info["peak_profit"] = max(entry_info["peak_profit"], _cp)

            # 利润回撤止盈
            if exit_reason is None and _cp > 0 and entry_info["peak_profit"] > atr_val * 0.5:
                _pdd_trend = 0.25
                if adx > 25:
                    _pdd_trend = max(_pdd_trend, 0.5)
                profit_ratio = _cp / entry_info["peak_profit"]
                if profit_ratio < (1 - _pdd_trend):
                    exit_reason = "profit_drawdown"

            # 震荡出场
            if exit_reason is None and regime in ("range", "range_wide"):
                if is_buy and cross_down_now and close >= ma_val:
                    if k_curr >= 80:
                        exit_reason = "rng_long_main"
                    elif not bb_rising_ok(closes, bb["sma"], k_curr, k_prev):
                        exit_reason = "rng_long_misalign"
                elif not is_buy and cross_up_now and close <= ma_val:
                    if k_curr <= 20:
                        exit_reason = "rng_short_main"
                    elif not bb_rising_ok(closes, bb["sma"], k_curr, k_prev):
                        exit_reason = "rng_short_misalign"

            # 趋势出场
            if exit_reason is None and regime == "trend":
                trail_dist = atr_val * (TREND_TP_ATR * 0.5)
                if (is_buy and close < entry_info["peak"] - trail_dist) or \
                   (not is_buy and close > entry_info["peak"] + trail_dist):
                    exit_reason = "trend_trail"
                elif pnl_pts > atr_val * TREND_TP_ATR:
                    exit_reason = "trend_tp"
                elif adx < 20:
                    exit_reason = "trend_adx_drop"
                elif is_buy and ndi > pdi:
                    exit_reason = "trend_di_flip_long"
                elif not is_buy and pdi > ndi:
                    exit_reason = "trend_di_flip_short"

            if exit_reason:
                final_pnl_pts = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
                pnl = final_pnl_pts * 10 * lot_size - commission
                trades.append({
                    "entry_time": entry_info['time'],
                    "exit_time": c['ts_str'],
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_info['idx'],
                    "exit_reason": exit_reason,
                    "regime": regime,
                    "adx_entry": round(entry_info['adx'], 1),
                })
                position = None

    # 最后一笔：未平仓
    if position is not None:
        c = candles[-1]
        close = c['close']
        is_buy = position == "BUY"
        final_pnl_pts = (close - entry_info['price']) if is_buy else (entry_info['price'] - close)
        pnl = final_pnl_pts * 10 * lot_size - commission
        trades.append({
            "entry_time": entry_info['time'],
            "exit_time": c['ts_str'],
            "direction": position,
            "entry_price": round(entry_info['price'], 2),
            "exit_price": round(close, 2),
            "pnl": round(pnl, 2),
            "bars": n - 1 - entry_info['idx'],
            "exit_reason": "end_of_data",
            "regime": entry_info['regime'],
            "adx_entry": round(entry_info['adx'], 1),
        })

    return trades, filter_stats


def compute_stats(trades):
    """计算交易统计数据"""
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl": 0, "avg_pnl": 0, "max_drawdown": 0,
                "profit_factor": 0, "avg_bars": 0,
                "long_count": 0, "short_count": 0}

    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in closed)
    cum, peak, max_dd = 0, 0, 0
    for t in closed:
        cum += t['pnl']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    pf = gp / gl if gl > 0 else 0
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(closed), 2) if closed else 0,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(pf, 2),
        "long_count": sum(1 for t in closed if t['direction'] == "BUY"),
        "short_count": sum(1 for t in closed if t['direction'] == "SELL"),
        "avg_bars": round(sum(t['bars'] for t in closed) / len(closed), 1),
    }


def print_stats_table(label, stats):
    """打印一行统计"""
    print(f"  {label:<22} {stats['trades']:>5}  {stats['wins']:>4}  {stats['losses']:>4}  "
          f"{stats['win_rate']:>6.1f}%  ${stats['total_pnl']:>+9.2f}  "
          f"${stats['avg_pnl']:>+7.2f}  ${stats['max_drawdown']:>8.2f}  "
          f"{stats['profit_factor']:>6.2f}")


def print_exit_breakdown(trades, label):
    """打印出场原因分布"""
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return
    by_reason = defaultdict(list)
    for t in closed:
        by_reason[t['exit_reason']].append(t)
    print(f"\n  [{label}] 出场原因分布 ({len(closed)} 笔):")
    print(f"  {'出场原因':<22} {'笔数':>5} {'占比':>7} {'胜率':>7} {'总盈亏':>10}")
    print(f"  {'-'*54}")
    for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for t in ts if t['pnl'] > 0)
        wr = wins / len(ts) * 100
        rpnl = sum(t['pnl'] for t in ts)
        print(f"  {reason:<22} {len(ts):>5}  {len(ts)/len(closed)*100:>6.1f}%  "
              f"{wr:>5.1f}%  ${rpnl:>+9.2f}")


def print_regime_breakdown(trades, label):
    """按模式/regime 统计"""
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return
    by_regime = defaultdict(list)
    for t in closed:
        by_regime[t['regime']].append(t)
    print(f"\n  [{label}] 模式分布:")
    print(f"  {'模式':<16} {'笔数':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'胜/负':>7}")
    print(f"  {'-'*55}")
    regime_names = {"range": "窄幅震荡", "range_wide": "宽幅震荡", "trend": "趋势"}
    for regime in ["range", "range_wide", "trend"]:
        ts = by_regime.get(regime, [])
        if not ts:
            continue
        wins = sum(1 for t in ts if t['pnl'] > 0)
        wr = wins / len(ts) * 100
        rpnl = sum(t['pnl'] for t in ts)
        avg = rpnl / len(ts)
        name = regime_names.get(regime, regime)
        print(f"  {name:<16} {len(ts):>5}  {wr:>5.1f}%  ${rpnl:>+9.2f}  ${avg:>+7.2f}  {wins}/{len(ts)-wins}")


def print_monthly_breakdown(trades, label):
    """按月统计"""
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return
    by_month = defaultdict(list)
    for t in closed:
        month_key = t['entry_time'][:7]
        by_month[month_key].append(t)
    print(f"\n  [{label}] 月度统计:")
    print(f"  {'月份':<10} {'笔数':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'盈亏比':>7}")
    print(f"  {'-'*49}")
    for month in sorted(by_month.keys()):
        ts = by_month[month]
        wins = sum(1 for t in ts if t['pnl'] > 0)
        wr = wins / len(ts) * 100
        rpnl = sum(t['pnl'] for t in ts)
        avg = rpnl / len(ts)
        gp = sum(t['pnl'] for t in ts if t['pnl'] > 0)
        gl = abs(sum(t['pnl'] for t in ts if t['pnl'] <= 0))
        pf = gp / gl if gl > 0 else 0
        print(f"  {month:<10} {len(ts):>5}  {wr:>5.1f}%  ${rpnl:>+9.2f}  ${avg:>+7.2f}  {pf:>6.2f}")


def main():
    print("=" * 80)
    print("  stoch_trend_m30 全面回测 — 原始逻辑 vs ADX分级过滤器")
    print("=" * 80)
    print()
    print("  ADX分级规则:")
    print("    ADX < 10 : 禁止开仓（极低波动，随机指标不可靠）")
    print("    ADX 10-20: 原始逻辑不变")
    print("    ADX > 20 : 加DI方向确认（BUY需pdi>ndi, SELL需ndi>pdi）")
    print()

    # ── 加载数据 ──
    candles = load_ohlcv("M30")
    if not candles:
        print("  [ERR] 未加载到M30数据")
        return
    print(f"  M30数据: {len(candles)} 根 K线")
    print(f"  范围: {candles[0]['ts_str']} ~ {candles[-1]['ts_str']}")
    print()

    # ── 两个版本回测 ──
    print("  运行回测...")
    trades_orig, _ = run_backtest(candles, adx_graded_filter=False)
    trades_filt, filter_stats = run_backtest(candles, adx_graded_filter=True)
    print(f"  原始逻辑: {len([t for t in trades_orig if t['exit_reason']!='end_of_data'])} 笔")
    print(f"  ADX分级:  {len([t for t in trades_filt if t['exit_reason']!='end_of_data'])} 笔")
    print()

    # ── 总体对比 ──
    s_orig = compute_stats(trades_orig)
    s_filt = compute_stats(trades_filt)

    print("=" * 80)
    print("  总体对比")
    print("=" * 80)
    header = f"  {'':<22} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7}"
    print(header)
    print(f"  {'-'*80}")
    print_stats_table("原始逻辑", s_orig)
    print_stats_table("ADX分级过滤", s_filt)

    # 差异
    diff_pnl = s_filt['total_pnl'] - s_orig['total_pnl']
    diff_wr = s_filt['win_rate'] - s_orig['win_rate']
    diff_pf = s_filt['profit_factor'] - s_orig['profit_factor']
    diff_trades = s_filt['trades'] - s_orig['trades']
    print(f"  {'───'*26}")
    print(f"  {'差异':<22} {diff_trades:>+5} {'':>4} {'':>4}  {diff_wr:>+5.1f}%  ${diff_pnl:>+9.2f} {'':>8} {'':>10}  {diff_pf:>+6.2f}")

    # ── 模式分布 ──
    print()
    print("=" * 80)
    print("  模式分布")
    print("=" * 80)
    print_regime_breakdown(trades_orig, "原始逻辑")
    print_regime_breakdown(trades_filt, "ADX分级过滤")

    # ── 出场原因 ──
    print()
    print("=" * 80)
    print("  出场原因分析")
    print("=" * 80)
    print_exit_breakdown(trades_orig, "原始逻辑")
    print_exit_breakdown(trades_filt, "ADX分级过滤")

    # ── 月度统计 ──
    print()
    print("=" * 80)
    print("  月度统计")
    print("=" * 80)
    print_monthly_breakdown(trades_orig, "原始逻辑")
    print_monthly_breakdown(trades_filt, "ADX分级过滤")

    # ── 过滤统计 ──
    print()
    print("=" * 80)
    print("  ADX过滤器拦截统计")
    print("=" * 80)
    print(f"  ADX<10 拦截:  {filter_stats['adx_lt10_blocked']} 笔")
    print(f"  ADX>20 DI方向: {filter_stats['adx_gt20_blocked']} 笔")
    total_blocked = filter_stats['adx_lt10_blocked'] + filter_stats['adx_gt20_blocked']
    print(f"  合计拦截:      {total_blocked} 笔")

    # ── 方向分布 ──
    print()
    print("=" * 80)
    print("  方向分布")
    print("=" * 80)
    print(f"  {'':<22} {'多头':>7} {'空头':>7} {'多头比例':>9}")
    print(f"  {'-'*48}")
    orig_long_pct = s_orig['long_count'] / s_orig['trades'] * 100 if s_orig['trades'] else 0
    filt_long_pct = s_filt['long_count'] / s_filt['trades'] * 100 if s_filt['trades'] else 0
    print(f"  {'原始逻辑':<22} {s_orig['long_count']:>7} {s_orig['short_count']:>7}  {orig_long_pct:>7.1f}%")
    print(f"  {'ADX分级过滤':<22} {s_filt['long_count']:>7} {s_filt['short_count']:>7}  {filt_long_pct:>7.1f}%")

    # ── 评估结论 ──
    print()
    print("=" * 80)
    print("  评估结论")
    print("=" * 80)
    print()
    if s_filt['total_pnl'] > s_orig['total_pnl'] and s_filt['win_rate'] >= s_orig['win_rate']:
        print("  [OK] ADX分级过滤器全面优于原始逻辑：")
        print(f"     - 总盈亏改善: ${diff_pnl:+.2f}")
        print(f"     - 胜率改善: {diff_wr:+.1f}pp")
        print(f"     - 盈亏比改善: {diff_pf:+.2f}")
        print(f"     - 拦截 {total_blocked} 笔低质量交易")
    elif s_filt['total_pnl'] > s_orig['total_pnl']:
        print("  [!!] ADX分级过滤器总盈亏提升但胜率下降：")
        print(f"     - 总盈亏改善: ${diff_pnl:+.2f}")
        print(f"     - 胜率变化: {diff_wr:+.1f}pp")
        print(f"     - 盈亏比变化: {diff_pf:+.2f}")
        print(f"     - 交易量变化: {diff_trades:+d} 笔")
    elif s_filt['total_pnl'] < s_orig['total_pnl'] and s_filt['max_drawdown'] < s_orig['max_drawdown']:
        print("  [!!] ADX分级过滤器总盈亏略降但回撤显著降低：")
        print(f"     - 总盈亏变化: ${diff_pnl:+.2f}")
        print(f"     - 最大回撤: ${s_orig['max_drawdown']:.2f} → ${s_filt['max_drawdown']:.2f}")
        print(f"     - 盈亏比变化: {diff_pf:+.2f}")
        print(f"     - 拦截 {total_blocked} 笔")
        print(f"     - 建议：如回撤降低明显，可启用过滤器作为风控")
    else:
        print("  [NO] ADX分级过滤器无明显改善：")
        print(f"     - 总盈亏变化: ${diff_pnl:+.2f}")
        print(f"     - 胜率变化: {diff_wr:+.1f}pp")
        print(f"     - 盈亏比变化: {diff_pf:+.2f}")
        print(f"     - 拦截 {total_blocked} 笔（可能拦截了盈利交易）")
    print()

    # ── 列出所有交易 ──
    for label, trades in [("原始逻辑", trades_orig), ("ADX分级过滤", trades_filt)]:
        closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
        print(f"  [{label}] 交易明细 ({len(closed)} 笔)")
        print(f"  {'#':>3} {'方向':>5} {'入场时间':<18} {'出场时间':<18} {'入场价':>9} {'出场价':>9} {'盈亏':>8} {'原因':<20} {'模式':<12} {'ADX':>5}")
        print(f"  {'-'*110}")
        for idx, t in enumerate(closed, 1):
            print(f"  {idx:>3} {t['direction']:>5} {t['entry_time']:<18} {t['exit_time']:<18} "
                  f"{t['entry_price']:>9.2f} {t['exit_price']:>9.2f} ${t['pnl']:>+6.2f} "
                  f"{t['exit_reason']:<20} {t['regime']:<12} {t['adx_entry']:>5}")
        if closed:
            total = sum(t['pnl'] for t in closed)
            wins = sum(1 for t in closed if t['pnl'] > 0)
            print(f"  {'─'*110}")
            print(f"  合计: {len(closed)} 笔, {wins}胜/{len(closed)-wins}负, 总盈亏 ${total:+.2f}")
        print()


if __name__ == "__main__":
    main()
