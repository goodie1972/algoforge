---
name: entry_score_pro
magic: 661501
type: Scoring
display_en: Entry Score PRO — 5-Factor Weighted Scoring
desc_en: M30 5-factor weighted scoring system, score 0-100, trigger threshold ≥75
---

**Timeframe:** M30

## Scoring Factors
| # | Factor | Weight | Description |
|---|---|---|---|
| ① | Structure | 30% | HTF EMA alignment + candle direction; close>EMA50 adds 25 points, ADX>25 and +DI>-DI adds another 25 points |
| ② | Proximity | 25% | Distance to the nearest swing low <1ATR → 80 points, <2ATR → 65 points |
| ③ | Momentum | 15% | Body/range ratio; the larger the bullish body share, the higher the score |
| ④ | Volatility | 10% | Current ATR / ATR 30 bars ago within 0.8~1.3 → 70 points (healthy volatility) |
| ⑤ | Trend | 20% | close>MA14 adds 30 points, RSI>50 adds 20 points |
| ① | Structure | 30% | close<EMA50 adds 25 points, ADX>25 and -DI>+DI adds another 25 points |
| ② | Proximity | 25% | Distance to the nearest swing high <1ATR → 80 points, <2ATR → 65 points |
| ③ | Momentum | 15% | Body/range ratio; the larger the bearish body share, the higher the score |
| ④ | Volatility | 10% | Current ATR / ATR 30 bars ago within 0.8~1.3 → 70 points |
| ⑤ | Trend | 20% | close<MA14 adds 30 points, RSI<50 adds 20 points |
**Composite Score:** Weighted average (0-100), ENTRY WINDOW ≥75, PRIME ≥80, STRONG ≥85, SUSTAINED ≥80 for 3 consecutive bars.
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | Initial SL | ±0.55 ATR |
| ② | ATR Trailing | Triggered when peak pullback exceeds 1.5 ATR |
| ③ | Initial TP | 3×SL (R:R=3:1) |
## Risk Control
- Directional Edge: Signal triggered only when this direction's score is strictly higher than the opposite direction's
- Initial Hard Stop: entry zone ±0.55×ATR (order-level SL, also serves as the runtime hard stop)
- Trailing: Exit when peak pullback exceeds 1.5×ATR
- Initial Take-Profit: 3×SL (fixed risk-reward R:R=3:1)
- Max Positions: 1 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| w_structure / w_proximity / w_momentum / w_volatility / w_trend | 30 / 25 / 15 / 10 / 20 | Weighted weights of the 5 factors (%) |
| score_entry | 75 | ENTRY WINDOW trigger threshold |
| score_prime | 80 | PRIME tier threshold |
| sl_atr | 0.55 | Initial stop loss = ±0.55×ATR |
| trail_atr | 1.5 | Trailing multiplier |
| rsi_period / atr_period | 14 / 14 | Calculation periods for RSI, ATR |
## Special Rules
- Source: TradingView No-Repaint Entry Score Multi-Factor Confluence [LunqFX]
- SL = entry zone ±0.55ATR, TP = 3×SL (fixed risk-reward R:R=3:1)
- Data Source: All indicators are read from DataFactory TA-Lib
