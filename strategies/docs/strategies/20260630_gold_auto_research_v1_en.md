---
name: gold_auto_research
magic: 880306
type: ML
display_en: Gold-AutoResearch — H1 Live Trading Strategy
desc_en: H1 4-factor consensus voting strategy + high-position block (price_position>0.82 and deviation from EMA21>2.5×ATR blocks BUY) + low-position block (<0.18 and deviation<−2.5×ATR blocks SELL)
---

## Scoring Factors
| # | Factor | Score | Description |
|---|---|---|---|
| ① | Trend | +1 | H1 EMA10 > EMA20 |
| ② | Momentum | +1 | MACD(12,26,9) + Stoch(14,3,3) both bullish |
| ③ | Volatility Activity | +1 | ADX>20 or ATR above SMA20 |
| ④ | Safety | +1 | RSI(10) not overbought + price not beyond BB upper band |
| ① | Trend | +1 | H1 EMA10 < EMA20 |
| ② | Momentum | +1 | MACD(12,26,9) + Stoch(14,3,3) both bearish |
| ③ | Volatility Activity | +1 | ADX>20 or ATR above SMA20 |
| ④ | Safety | +1 | When RSI≤35, shorts are blocked independently to prevent opening shorts near the oversold zone |
**Judgment Rule:** A signal is triggered only when all 4 factors agree (AND logic); no trade if any factor is missing.
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | Breakeven Exit | After reaching ≥0.3ATR profit, price returns near breakeven |
| ② | Profit Pullback TP | 25% pullback from peak profit (relaxed to 50% when ADX>25) |
| ③ | ATR Trailing TP | Drops more than trail_mult × ATR from the highest point |
| ④ | Hard Stop | Loss exceeds hard_mult × ATR (3.0×ATR with-trend, 2.0×ATR against-trend) |
## Special Rules
- H4 SMA50 Trend Gate: H4 downtrend blocks BUY, H4 uptrend blocks SELL
- Position Gate: high-position block (price_position>0.82 and deviation from EMA21>2.5×ATR blocks BUY), low-position block (<0.18 and deviation<−2.5×ATR blocks SELL)
- Data Source: All indicators are read from DataFactory TA-Lib
