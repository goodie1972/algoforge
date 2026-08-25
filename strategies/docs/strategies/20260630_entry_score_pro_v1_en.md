---
name: entry_score_pro
magic: 661501
type: Scoring
display_en: Entry Score PRO — 5-Factor Weighted Scoring
desc_en: H1 5-factor weighted scoring system, score 0-100, trigger threshold ≥75
---

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
## Special Rules
- Source: TradingView No-Repaint Entry Score Multi-Factor Confluence [LunqFX]
- SL = entry zone ±0.55ATR, TP = 3×SL (fixed risk-reward R:R=3:1)
- Data Source: All indicators are read from DataFactory TA-Lib
