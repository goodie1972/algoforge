"""
Simulation: Compare profit_drawdown tuning scenarios against today's 28 trades.

Scenarios:
  1. profit_drawdown_min_peak_atr = 0.1 → 1.0  (peak must hit 1×ATR before drawdown activates)
  3. ADX>25 → auto-widen pdd from 0.3 to 0.5     (trend-aware wider drawdown tolerance)
"""
import json
from data.database import get_trades

trades = get_trades(limit=200)
today = [t for t in trades if str(t.get("close_time", ""))[:10] == "2026-06-25"]
today.sort(key=lambda x: x["close_time"])

# Strategy-specific pdd logic
STRATEGY_PDD = {
    "sanqing_h1": "adaptive",       # 0.5/0.4/0.3 based on peak/ATR
    "gold_auto_research": "fixed",  # fixed 0.3
    "M30_rsi_bb": "fixed",          # fixed 0.3
}

def get_current_pdd_used(strategy: str, peak_profit: float, atr_val: float, pdd_base: float) -> float:
    """Replicate current profit_drawdown logic."""
    if strategy == "sanqing_h1":
        if peak_profit < atr_val * 1.0:
            return 0.5
        elif peak_profit < atr_val * 2.0:
            return 0.4
        else:
            return pdd_base
    else:
        return pdd_base  # fixed

print("=" * 120)
print(f"{'Time':<20} {'Strategy':<22} {'Entry→Exit':<20} {'P&L':>7} {'Peak':>6} {'ATR':>6} {'ADX':>5} {'CurrPDD':>7} {'Sc1:Off?':>9} {'Sc1:NewPdd':>10} {'Sc3:NewPdd':>10} {'Sc3:StillExit?':>14}")
print("-" * 120)

pdd_base = 0.3  # profit_drawdown_pct from runtime_config.json

results = {"sc1_no_drawdown": 0, "sc1_drawdown_still": 0, "sc3_exit_still": 0, "sc3_no_exit": 0}

for t in today:
    strategy = t["strategy"]
    pnl = t["pnl"]
    close_time = t["close_time"]
    entry_price = t["entry_price"]
    exit_price = t["exit_price"]
    price_range = f"{entry_price}→{exit_price}"

    snap = json.loads(t["indicator_snapshot"] or "{}")
    iv = snap.get("indicator_values", {})
    ed = snap.get("exit_detail", {})

    peak_profit = ed.get("peak_profit", 0)
    atr_val = ed.get("atr", 0)
    adx = iv.get("adx", 0)
    current_profit_ed = ed.get("current_profit", pnl)

    # Current pdd_used
    curr_pdd = get_current_pdd_used(strategy, peak_profit, atr_val, pdd_base)
    profit_ratio = current_profit_ed / peak_profit if peak_profit > 0 else 999
    curr_exit = profit_ratio < (1 - curr_pdd) if peak_profit > 0 else True

    # --- Scenario 1: min_peak_atr = 1.0 ---
    min_peak_atr_sc1 = 1.0
    sc1_drawdown_on = peak_profit > atr_val * min_peak_atr_sc1
    if sc1_drawdown_on:
        sc1_pdd = get_current_pdd_used(strategy, peak_profit, atr_val, pdd_base)
        sc1_exit = profit_ratio < (1 - sc1_pdd)
        sc1_label = f"{'OFF→ON':>9}"
        sc1_pdd_label = f"{sc1_pdd:.1f}"
    else:
        sc1_label = f"{'DDOFF':>9}"
        sc1_pdd_label = "N/A"
        results["sc1_no_drawdown"] += 1
    if sc1_drawdown_on:
        results["sc1_drawdown_still"] += 1

    # --- Scenario 3: ADX>25 → widen pdd to 0.5 ---
    sc3_pdd = 0.5 if (adx > 25 and peak_profit > 0) else curr_pdd
    # For sc3, we keep min_peak_atr=0.1 (same as current)
    sc3_drawdown_on = peak_profit > atr_val * 0.1
    if sc3_drawdown_on and peak_profit > 0:
        sc3_exit = profit_ratio < (1 - sc3_pdd)
    else:
        sc3_exit = curr_exit

    if adx > 25:
        if sc3_exit:
            sc3_label = f"{'still exit':>14}"
            results["sc3_exit_still"] += 1
        else:
            sc3_label = f"{'WOULD HOLD':>14}"
            results["sc3_no_exit"] += 1
    else:
        sc3_label = f"{'ADX≤25,n/c':>14}"

    print(
        f"{close_time:<20} {strategy:<22} {price_range:<20} "
        f"{pnl:>7.2f} {peak_profit:>6.1f} {atr_val:>6.1f} {adx:>5.0f} "
        f"{curr_pdd:>7.1f} {sc1_label:>9} {sc1_pdd_label:>10} {sc3_pdd:>10.1f} {sc3_label:>14}"
    )

print("=" * 120)
print(f"\nSummary:")
print(f"  Scenario 1 (min_peak_atr=1.0): {results['sc1_no_drawdown']} trades would NOT trigger drawdown check, {results['sc1_drawdown_still']} would still trigger")
print(f"  Scenario 3 (ADX>25 → pdd=0.5): {results['sc3_no_exit']} trades would NOT exit at this point (would hold longer), {results['sc3_exit_still']} would still exit")
print()

# --- Detailed analysis ---
print("\n=== DETAILED ANALYSIS ===")
print()

# Scenario 1 impact
print("--- Scenario 1: min_peak_atr=0.1→1.0 ---")
print("Gate check: peak_profit > atr_val × 1.0 (= $atr_val)")
print()
sc1_affected = [t for t in today if (
    json.loads(t["indicator_snapshot"] or "{}").get("exit_detail", {}).get("peak_profit", 0) <=
    json.loads(t["indicator_snapshot"] or "{}").get("exit_detail", {}).get("atr", 1) * 1.0
)]
total_pnl_affected = sum(t["pnl"] for t in sc1_affected)
total_pnl_all = sum(t["pnl"] for t in today)
print(f"Trades where peak_profit < 1.0×ATR (drawdown check would NOT activate): {len(sc1_affected)}/{len(today)}")
print(f"  These trades' PnL: ${total_pnl_affected:.2f} (out of ${total_pnl_all:.2f} total)")
print()
print("These trades would NOT be stopped by profit_drawdown.")
print("They would continue running until trail_stop or hard_stop triggers.")
print("Trail stop for SELL in downtrend: rally > ATR × 2.5 ≈ $67 from local low")
print()

# Scenario 3 impact
print("--- Scenario 3: ADX>25 → pdd=0.3→0.5 ---")
print("Applies to trades where ADX>25 AND peak_profit > 0")
print()

sc3_details = []
for t in today:
    strategy = t["strategy"]
    pnl = t["pnl"]
    snap = json.loads(t["indicator_snapshot"] or "{}")
    iv = snap.get("indicator_values", {})
    ed = snap.get("exit_detail", {})
    peak = ed.get("peak_profit", 0)
    atr = ed.get("atr", 0)
    cur = ed.get("current_profit", pnl)
    adx = iv.get("adx", 0)

    if adx > 25 and peak > 0:
        curr_pdd = get_current_pdd_used(strategy, peak, atr, pdd_base)
        sc3_threshold = 1 - 0.5  # wider pdd
        curr_threshold = 1 - curr_pdd
        ratio = cur / peak

        still_exit = ratio < sc3_threshold

        # What profit level would trigger exit under Sc3?
        sc3_exit_profit = peak * sc3_threshold
        curr_exit_profit = peak * curr_threshold
        extra_room = sc3_exit_profit - curr_exit_profit

        sc3_details.append({
            "time": t["close_time"],
            "strategy": strategy,
            "pnl": pnl,
            "peak": peak,
            "atr": atr,
            "adx": adx,
            "curr_pdd": curr_pdd,
            "ratio": ratio,
            "still_exit": still_exit,
            "sc3_exit_profit": sc3_exit_profit,
            "curr_exit_profit": curr_exit_profit,
            "extra_room": extra_room,
        })

        print(f"  {t['close_time']} {strategy:<20} peak={peak:>5.1f} ratio={ratio:.3f} "
              f"curr_pdd={curr_pdd:.1f}(thresh={curr_threshold:.1f}) → sc3_pdd=0.5(thresh={sc3_threshold:.1f}) "
              f"{'→ STILL EXIT' if still_exit else '→ WOULD HOLD'}"
              f"{f' (exit at ${sc3_exit_profit:.1f}, +${extra_room:.1f} room)' if not still_exit else ''}")

# Also check gold_auto_research - no ADX, so no impact
gar_trades = [t for t in today if t["strategy"] == "gold_auto_research"]
gar_pnl = sum(t["pnl"] for t in gar_trades)
print(f"\n  gold_auto_research trades (all ADX=0): {len(gar_trades)} trades, ${gar_pnl:.2f} PnL")
print(f"  → Scenario 3 has NO impact on these (ADX never >25)")
print()

# Summary: what would Sc1 mean without drawdown
print("\n--- What happens to Sc1 'drawdown off' trades? ---")
print("Without profit_drawdown, these trades only exit via trail_stop or hard_stop.")
print("For SELL in strong downtrend (ADX~50, ndi>>pdi):")
print("  - trail_stop triggers at rally > ATR×2.5 ≈ $67 from local low")
print("  - hard_stop triggers at loss > ATR×4.0 ≈ $108 from entry")
print()
print("This is a LOT of room — likely larger profits but also risk of reversal.")
print("Actual outcome depends on 1-min tick data not stored in DB.")
print()

# Trading cost analysis
print("\n--- Cost Analysis ---")
print(f"Commission per trade (0.01 lot XAUUSD): -$0.50")
total_commission = len(today) * 0.5
print(f"Total commission for {len(today)} trades: -${total_commission:.2f}")
print(f"Net PnL after commission: ${total_pnl_all - total_commission:.2f}")
avg_hold = sum(t.get("hold_seconds", 0) for t in today) / len(today)
print(f"Average hold time: {avg_hold:.0f}s ({avg_hold/60:.1f} min)")
