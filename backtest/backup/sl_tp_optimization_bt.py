"""
v6_hybrid SL/TP 优化回测
========================
用户反馈:
  - 硬止损 2 ATR → 3 ATR (加宽避免频繁打止损)
  - 显式止盈 6 ATR (R:R = 1:2)
  - 位置门禁: |距 EMA21| < 阈值 才开仓

回测组合:
  A-baseline: SL=2, no TP, no gate        (原 v6 行为)
  B-tp_sl:    SL=3, TP=6, no gate
  C-gate1.0:  SL=3, TP=6, gate=1.0σ
  D-gate1.5:  SL=3, TP=6, gate=1.5σ
  E-gate2.0:  SL=3, TP=6, gate=2.0σ

出场优先级: SL hit → TP hit → reverse signal
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import load_h1_data, generate_v6_signal, Trade


def run_backtest(candles, sl_atr=3.0, tp_atr=None, gate_sigma=None, lot_size=0.01, commission=0.5):
    """单次回测

    Args:
        sl_atr: 硬止损 ATR 倍数 (None = 不设硬止损)
        tp_atr: 显式止盈 ATR 倍数 (None = 不设显式 TP)
        gate_sigma: 位置门禁 (None = 不门禁), |dist_atr| < gate_sigma 才开仓
    """
    trades = []
    position = None
    entry_price = 0.0
    entry_idx = 0
    entry_signal_dist = 0.0
    entry_long_factors = []
    entry_short_factors = []
    entry_regime = ""
    n = len(candles)

    for i in range(250, n):
        c = candles[i]
        sig_info = generate_v6_signal(candles, i)
        if sig_info is None:
            continue
        signal = sig_info["signal"]

        if signal and position is None:
            if gate_sigma is not None and abs(sig_info["dist_atr"]) >= gate_sigma:
                continue
            position = signal
            entry_price = c['close']
            entry_idx = i
            entry_signal_dist = sig_info["dist_atr"]
            entry_long_factors = list(sig_info["long_factors"])
            entry_short_factors = list(sig_info["short_factors"])
            entry_regime = sig_info["regime"]

        elif position is not None:
            atr_val = sig_info["atr"]
            pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])

            exit_reason = None
            exit_p = c['close']

            if sl_atr is not None and atr_val > 0 and pnl_pts < -atr_val * sl_atr:
                exit_reason = "hard_stop"
                exit_p = entry_price - (atr_val * sl_atr if position == "BUY" else -atr_val * sl_atr)

            elif tp_atr is not None and atr_val > 0 and pnl_pts > atr_val * tp_atr:
                exit_reason = "take_profit"
                exit_p = entry_price + (atr_val * tp_atr if position == "BUY" else -atr_val * tp_atr)

            elif signal and signal != position:
                exit_reason = "reverse_signal"

            if exit_reason:
                final_pnl_pts = (exit_p - entry_price) if position == "BUY" else (entry_price - exit_p)
                pnl = final_pnl_pts * 10 * lot_size - commission
                trades.append(Trade(
                    entry_time=candles[entry_idx]['ts_str'],
                    exit_time=c['ts_str'],
                    direction=position,
                    entry_price=round(entry_price, 2),
                    exit_price=round(exit_p, 2),
                    pnl=round(pnl, 2),
                    bars=i - entry_idx,
                    exit_reason=exit_reason,
                    reverse_tag="",
                ))
                position = None

    if position is not None:
        c = candles[-1]
        atr_val = sig_info["atr"] if sig_info else 0
        pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])
        exit_reason = "end_of_data"
        exit_p = c['close']
        if sl_atr is not None and atr_val > 0 and pnl_pts < -atr_val * sl_atr:
            exit_reason = "hard_stop"
            exit_p = entry_price - (atr_val * sl_atr if position == "BUY" else -atr_val * sl_atr)
        elif tp_atr is not None and atr_val > 0 and pnl_pts > atr_val * tp_atr:
            exit_reason = "take_profit"
            exit_p = entry_price + (atr_val * tp_atr if position == "BUY" else -atr_val * tp_atr)
        if exit_reason != "end_of_data":
            final_pnl_pts = (exit_p - entry_price) if position == "BUY" else (entry_price - exit_p)
        else:
            final_pnl_pts = pnl_pts
        pnl = final_pnl_pts * 10 * lot_size - commission
        trades.append(Trade(
            entry_time=candles[entry_idx]['ts_str'],
            exit_time=c['ts_str'],
            direction=position,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_p, 2),
            pnl=round(pnl, 2),
            bars=n - 1 - entry_idx,
            exit_reason=exit_reason,
            reverse_tag="",
        ))

    return trades


def compute_stats(trades):
    closed = [t for t in trades if t.exit_reason != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0, "avg_bars": 0,
                "sl_count": 0, "tp_count": 0, "rev_count": 0, "gross_profit": 0, "gross_loss": 0}

    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in closed)
    avg_pnl = total_pnl / len(closed)

    cum = 0; peak = 0; max_dd = 0
    for t in closed:
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    sl_count = sum(1 for t in closed if t.exit_reason == "hard_stop")
    tp_count = sum(1 for t in closed if t.exit_reason == "take_profit")
    rev_count = sum(1 for t in closed if t.exit_reason == "reverse_signal")

    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars": round(sum(t.bars for t in closed) / len(closed), 1),
        "sl_count": sl_count,
        "tp_count": tp_count,
        "rev_count": rev_count,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


def main():
    print("=" * 70)
    print("  v6_hybrid SL/TP 优化回测 (H1 2024-01 ~ 2026-06, 8700+ 根 K 线)")
    print("=" * 70)

    candles = load_h1_data()
    print(f"  数据: {len(candles)} 根 H1 K线\n")

    configs = [
        ("A-baseline",  {"sl_atr": 2.0, "tp_atr": None, "gate_sigma": None}),
        ("B-SL3/TP6",   {"sl_atr": 3.0, "tp_atr": 6.0, "gate_sigma": None}),
        ("C-1.0sigma",  {"sl_atr": 3.0, "tp_atr": 6.0, "gate_sigma": 1.0}),
        ("D-1.5sigma",  {"sl_atr": 3.0, "tp_atr": 6.0, "gate_sigma": 1.5}),
        ("E-2.0sigma",  {"sl_atr": 3.0, "tp_atr": 6.0, "gate_sigma": 2.0}),
        # ── 第二轮: 不同 SL/TP 组合 + 1.0σ 门禁 ──
        ("F-SL2/TP3",   {"sl_atr": 2.0, "tp_atr": 3.0, "gate_sigma": 1.0}),
        ("G-SL2.5/TP4", {"sl_atr": 2.5, "tp_atr": 4.0, "gate_sigma": 1.0}),
        ("H-SL2/TP4",   {"sl_atr": 2.0, "tp_atr": 4.0, "gate_sigma": 1.0}),
        ("I-SL1.5/TP3", {"sl_atr": 1.5, "tp_atr": 3.0, "gate_sigma": 1.0}),
    ]

    results = []
    for name, cfg in configs:
        print(f"  跑 {name}...", end="", flush=True)
        trades = run_backtest(candles, **cfg)
        stats = compute_stats(trades)
        stats["name"] = name
        results.append(stats)
        print(f" 完成 ({stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f})")

    print("\n" + "=" * 110)
    print("  对比表 (出场计数: SL=硬止损, TP=止盈, REV=反向信号)")
    print("=" * 110)
    print(f"  {'配置':<12} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'SL':>4} {'TP':>4} {'REV':>4} {'均K线':>7}")
    print("  " + "-" * 110)
    for r in results:
        print(f"  {r['name']:<12} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['sl_count']:>4} {r['tp_count']:>4} {r['rev_count']:>4} {r['avg_bars']:>7.1f}")
    print("=" * 110)

    print("\n" + "=" * 70)
    print("  决策建议")
    print("=" * 70)
    baseline = results[0]
    best = max(results[1:], key=lambda r: r['total_pnl'])
    print(f"  A-baseline 总盈亏: ${baseline['total_pnl']:+.2f}  胜率 {baseline['win_rate']:.1f}%  最大回撤 ${baseline['max_drawdown']:.2f}")
    print(f"  最优配置: {best['name']}  总盈亏 ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  最大回撤 ${best['max_drawdown']:.2f}")
    print(f"  改善幅度: ${best['total_pnl'] - baseline['total_pnl']:+.2f}")

    # 找出盈利配置（如果有）
    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        prof_best = max(profitable, key=lambda r: r['total_pnl'])
        print(f"\n  ★ 唯一盈利配置: {prof_best['name']}  P/L ${prof_best['total_pnl']:+.2f}  胜率 {prof_best['win_rate']:.1f}%")

    if best['total_pnl'] > 0 and best['win_rate'] >= 30:
        print(f"\n  推荐: {best['name']}  (总盈亏转正 + 胜率达标)")
    elif best['total_pnl'] > 0:
        print(f"\n  边际改善: {best['name']}  盈亏转正但需观察胜率")
    else:
        print(f"\n  所有改进仍亏损，需更深层调整")
    print()


if __name__ == "__main__":
    main()
