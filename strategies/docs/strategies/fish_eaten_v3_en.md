---
name: fish_eaten_v3
magic: 661303
type: Price Reversion (Counter-Trend, Exhaustion Scoring)
display_en: fish_eaten v3.1 — M30 Exhaustion Scoring Reversion Strategy
desc_en: Replaces "trend-following mid-section entry" with 6 exhaustion signals; fixes the problem of being punished inside trends
---

**Timeframe:** M30
**Source files:** `strategies/fish_eaten_v3.py` (main) / `20260906_fish_eaten_v3.py` (strategies repo)
**Scoring module:** `strategies/fish_eaten_entry.py` (pure functions, shared by live and backtest)

> ## Design Motivation
> The original v2's 6 hard gates (e.g. `bb_mid_dir == "down"`) **structurally selected trend mid-sections** — `bb_mid` ≈ SMA(20), so "mid-band down" literally means "downtrend healthy". v3 no longer asks "is the trend established?" but "**is the trend exhausting?**", scoring 6 independent exhaustion signals. Any signal passing scores +1; total ≥ threshold ⇒ entry.

## Entry Logic (Scoring)

### Gates (pre-conditions, ALL must hold)
| # | Condition | Description |
| --- | --- | --- |
| ① | 22 ≤ ADX ≤ 60 | Trend exists but avoid emotional climax zone (>60 actually reduces win rate) |
| ② | ∣+DI − −DI∣ > 5 | Clear trend direction |
| ③ | ≥ 12 bars history available | Required for divergence detection |

### Side Determination
- `−DI > +DI` → LONG side (bears dominate + exhaustion rebound)
- `+DI > −DI` → SHORT side (bulls dominate + exhaustion pullback)

### 6 Exhaustion Signals (each passing = +1, max 10, threshold SCORE_MIN=4)

| Signal | LONG Condition | Meaning |
| --- | --- | --- |
| ① ADX Turn | `adx < adx_prev` (ADX falling from high) | Trend losing energy — classic exhaustion |
| ② DI Convergence | `∣pdi − ndi∣ < ∣pdi_prev − ndi_prev∣` | Dominant force weakening |
| ③ Bandwidth Contraction | `bb_width < bb_width_prev` | Volatility energy contraction |
| ④ Pierce-and-Close | `low < bb_lower and close > bb_lower` (bar1) | Real reversal pattern, not band-walk |
| ⑤ RSI Leaves Oversold | `rsi_prev < 30 and rsi > 30` (LONG) / opposite for SHORT | 1-2 bars later than "just dropped below" but far more reliable |
| ⑥ Divergence | Price new low + RSI not new low (10-bar lookback) / opposite for SHORT | Classic reversal, weighted higher |

**Key changes vs v2:**
- ❌ Removed `bb_mid_dir == "down"` (mistook "trend healthy" for entry condition)
- ❌ Removed instantaneous extreme check (`rsi < 30 and mfi < 25`) — RSI stays below 30 for many bars in strong trends; first cross-down is acceleration, not exhaustion
- ✅ Added ADX dual-zone, DI convergence, divergence (3 truly effective exhaustion predictors)

### Verified Discrimination (live + unit tests)
| Scenario | Score | Result |
| --- | --- | --- |
| Trend mid-section: ADX rising, DI diff expanding, width expanding, band walk, RSI just dropped below 30 | **0/10** | ❌ Blocked |
| Trend end-section: ADX turning, DI converging, width contracting, pierce-and-close, RSI crosses up, divergence | **8/10** | ✅ Entry |

> Both passed v2 — that was the root cause of being punished.

## Exit Logic

### Fish Exit (primary, inherited from v2)
| Side | Trigger | Description |
| --- | --- | --- |
| **Long** | RSI≥70 and MFI≥75 both reached → either leaves → and close < BB upper − offset | Eats the full upside |
| **Short** | RSI≤30 and MFI≤25 both reached → either leaves → and close > BB lower + offset | Eats the full downside |

### Time Stop (backstop)
- After one indicator hits extreme, if the other does not within **48 bars (M30 = 24h)** → force close
- Prevents trades hanging forever

### Hard Stop (v3.1 widened to 3.0×ATR from v2's 1.5×ATR)
- `SL = max(ATR × 3.0, 15)` ≈ $36 (M30 ATR ≈ 12)
- Fixes the v2 issue where 1.5×ATR (≈$18) sat inside the MAE distribution and got swept

## Backtest Results

**Data:** Current M30 DB source, 5419 bars (2026-03-23 → 2026-08-20, ~5 months)

### v3.1 (default S4/A60/-/D8) Across SL Regimes
| SL | Trades | Win Rate | Net PnL | MAE | MFE | MFE/MAE |
| --- | --- | --- | --- | --- | --- | --- |
| No stop | 17 | 58.8% | +$125 | — | — | — |
| 1.5ATR (old live) | 25 | 20.0% | +$1.5 | 26.1 | 40.9 | 1.56 |
| **2.5ATR** | 23 | 34.8% | **+$160** | — | — | — |
| **3.0ATR (recommended)** | **22** | **40.9%** | **+$156** | — | — | — |
| 5.0ATR | 20 | 45.0% | +$117 | — | — | — |

### vs v2.2 Legacy at SL=3.0ATR
| Version | Trades | Win Rate | Net PnL | Entry Quality |
| --- | --- | --- | --- | --- |
| v2.2 (original 6-filter) | 46 | 39.1% | +$252 | ~half still in mid-section |
| **v3.1 (scoring)** | 22 | 40.9% | +$156 | Only at exhaustion points |

> v3.1's PnL is modestly lower than v2.2 ($156 vs $252), but v3.1's entry quality is higher — which is exactly the user's original complaint. v2.2 now runs as legacy in parallel paper trade to let real market data pick the winner.

### Key Finding: Stop-Loss Width Is the Real Bottleneck
- 1.5×ATR (SL ≈ $18, sits inside MAE ≈ $25) → ~20% win rate → this is why trades were getting punished
- **3.0×ATR (SL ≈ $36) → ~40% win rate, sweet spot for both v2 and v3 → go-live regime**
- 5.0×ATR reverses again (trend continuation kills reversion, v2 turns -$157)

### Parameter Grid Top (M30, SL=3.0ATR)
| Combo | Trades | Win Rate | PnL |
| --- | --- | --- | --- |
| **S4/A60/-/D8 (= v3.1 default)** | 22 | 40.9% | +$156 |
| S5/A60/P/D8 | 11 | 50.0% | +$155 |
| S4/A60/P/D8 | 22 | 40.9% | +$156 |
| S6/A60 (most aggressive) | 7 | 57.1% | +$188 |

Note: S=SCORE_MIN, A=adx_max, P=REQUIRE_PIERCE (treat pierce-and-close as hard gate), D=DIV_LOOKBACK.

## Data Source

### Current bar1 single-value (from DataFactory in-memory cache)
- `close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`, `bb_width`, `atr`

### Historical series (v3.1 needs 12 bars, from SQLite `indicator_snapshots`)
- Read via `strategies.base.get_indicator_series(name, n)`
- One DB query per new bar, aligned by candle time
- **Backtest and live share the same interface** — no dual-source drift

### Indicator Dependencies (14 total)
```
close, rsi, mfi, adx, pdi, ndi, bb (upper/mid/lower), 
bb_width, bb_mid_direction, atr,
+ series: rsi, adx, pdi, ndi, bb_width, close, low, high
```

## Risk Control

| Item | Setting | Notes |
| --- | --- | --- |
| Lot | 0.01 fixed | Paper trade v2/v3 share total cap |
| Hard Stop | `max(ATR × 3.0, 15)` ≈ $36 | Controlled by `SL_ATR_MULT` |
| Fish Exit | Enabled | Profit management |
| Time Stop | 48 bars (M30 = 24h) | Dead-trade backstop |
| max_positions | 1 | One position per strategy |
| Magic | **661303** (does NOT conflict with v2.2's 661302 — parallel paper trade) | |

## Go-Live Process & Risk Discipline

1. **Current:** Parallel paper trade (v2.2 magic 661302 + v3.1 magic 661303)
2. **Observation:** Min 1–2 months of live data before committing to one
3. **No immediate full size:** Even with good backtests, first month position should be one tier smaller than normal
4. **In-sample caveat:** The A60 → A30 → A60 flip across SL regimes shows `ADX_MAX` is sensitive to stop width and unstable. Parallel paper trading exists specifically to resolve this.

## Version & Changelog

See `STRATEGY_CHANGELOG` in source. Current version v3.1 (2026-09-06).
