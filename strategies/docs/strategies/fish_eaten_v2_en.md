---
name: fish_eaten_v2
magic: 661302
type: Price Reversion (Counter-Trend, original 6-filter entry)
display_en: fish_eaten v2.2 — M30 Original Price Reversion (Parallel Paper Control)
desc_en: Keeps original v2 6-filter entry + fish exit; only widens stop to 3.0×ATR; runs in parallel with v3.1
---

**Timeframe:** M30
**Source files:** `strategies/fish_eaten_legacy_v2.py` (main) / `20260820_fish_eaten_v1.py` (strategies repo)
**Role:** Parallel paper-trade control vs v3.1. Lets real market data answer "which is more stable: v2 or v3?".

> ## Why Keep v2.2
> User asked to "keep the original version running" + "run your new version on paper trade in parallel". This file is the original v2 logic, with only 3 non-logic changes (see "Differences from v2.0" below). We intentionally do NOT modify the entry logic — so that v2 and v3 see the exact same 5-month in-sample data and the same future live data for a **fair comparison**. If we also changed the entry, we wouldn't be able to tell whether a difference came from entry filtering or stop width.
>
> v2.2 is not meant to be a long-term production strategy. It only serves as the control for v3.1's introduction — deprecate it once live data confirms v3.1 is stable.

## Entry Logic (same as v2.0)

### Gates (pre-conditions)
| # | Condition | Description |
| --- | --- | --- |
| ① | ADX > 22 | Trending, not ranging |
| ② | ∣+DI − −DI∣ > 5 | Clear trend direction |

### Three-Layer Filter (Long: −DI > +DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | RSI < 30 and MFI < 25 | Oversold confirmation |
| 2 | close ≤ BB lower + 5 | Price near BB lower band |
| 3 | BB mid-band direction down | MA trend down, waiting for reversion |

### Three-Layer Filter (Short: +DI > −DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | RSI > 70 and MFI > 75 | Overbought confirmation |
| 2 | close ≥ BB upper − 5 | Price near BB upper band |
| 3 | BB mid-band direction up | MA trend up, waiting for reversion |

> **Known issue:** Layer 3 `bb_mid_dir == "down"` literally means "downtrend healthy" — semantically opposite of "long on reversion". This structural defect is exactly what v3.1 fixes. v2.2 keeps it on purpose for fair comparison.

## Exit Logic (same as v2.0)

### Fish Exit (primary)
| Side | Trigger | Description |
| --- | --- | --- |
| **Long** | RSI≥70 and MFI≥75 both reached → either leaves → and close < BB upper − offset | Eats the full upside |
| **Short** | RSI≤30 and MFI≤25 both reached → either leaves → and close > BB lower + offset | Eats the full downside |

### Time Stop (backstop)
- After one indicator reaches extreme, if the other does not within **48 bars (M30 = 24h)** → force close

## Differences from v2.0 (only 3 non-logic changes)

| Item | v2.0 | v2.2 | Reason |
| --- | --- | --- | --- |
| Hard stop width | `max(ATR × 1.5, 15)` ≈ $18 | `max(ATR × 3.0, 15)` ≈ $36 | Same regime as v3.1 for fair comparison (v2@1.5ATR vs v3.1@3.0ATR would compare apples to oranges) |
| Entry price | `candles[-1].close` (forming bar0) | `candles[-2].close` (closed bar1) | Removes forming-bar repaint/future-function risk; aligned with backtest |
| strategy.name | `"fish_eaten"` | `"fish_eaten_v2"` | No name collision with v3.1's `fish_eaten_v3` in scanner / config pool |
| STRATEGY_MAGIC | 661301 | 661302 | Fix magic collision; preserves history |
| STRATEGY_VERSION | v2 / v2.1 | v2.2 | Reflects above changes |

## Backtest Results

**Data:** Current M30 DB source, 5419 bars (2026-03-23 → 2026-08-20)

### v2.2 (original logic) Across SL Regimes
| SL | Trades | Win Rate | Net PnL | Realized Drawdown |
| --- | --- | --- | --- | --- |
| No stop | 30 | 56.7% | +$188 | — |
| 1.5ATR (old live) | 57 | 22.8% | +$144 | high |
| **3.0ATR (recommended control regime)** | **46** | **39.1%** | **+$252** | medium |
| 5.0ATR | 38 | 42.1% | −$157 | high (trend continuation kills reversion) |

> Net PnL at 3.0×ATR is slightly higher than v3.1 ($252 vs $156), but v2.2's structural entry problem still exists — ~half of entries are still in trend mid-section. **The user's original complaint ("always get punished in trend mid-sections") is NOT fixed by v2.2**, so it should not be the final version.

### Side-by-side vs v3.1 (SL=3.0ATR)
| Version | Trades | Win Rate | Net PnL | Entry Quality |
| --- | --- | --- | --- | --- |
| v2.2 | 46 | 39.1% | +$252 | ~half in mid-section |
| v3.1 | 22 | 40.9% | +$156 | Only at exhaustion |

## Data Source

- All indicators from DataFactory TA-Lib (fallback) / EA F043
- Dependencies: `close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`
- Entry price uses `candles[-2].close` (bar1)

## Risk Control

| Item | Setting |
| --- | --- |
| Lot | 0.01 fixed |
| Hard stop | `max(ATR × 3.0, 15)` ≈ $36 (same regime as v3.1) |
| Fish exit | Enabled |
| Time stop | 48 bars (M30 = 24h) |
| max_positions | 1 |
| Magic | **661302** (preserved; runs parallel with v3.1's 661303) |

## Go-Live Process & Risk Discipline

1. **Current:** Parallel paper-trade control (in same pool as v3.1 magic 661303)
2. **Observation:** Sync with v3.1 — accumulate 1–2 months of live data
3. **Decision basis:** Use win rate / average hold time / mid-section entry rate (NOT PnL — PnL is dominated by 1–2 lucky trades)
4. **Expected lifetime:** Deprecate v2.2 once v3.1 shows stable live performance

## Version & Changelog

See `STRATEGY_CHANGELOG` in source. Current version v2.2 (2026-09-06).
