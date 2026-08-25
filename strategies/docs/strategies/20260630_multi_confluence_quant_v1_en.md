---
name: multi_confluence_quant
magic: 661601
type: Scoring
display_en: Multi-Confluence Quant — 14-Factor Composite Scoring
desc_en: H1 scoring on 14 technical indicator factors, signal triggered at ≥10/14
---

## Scoring Factors
| # | Factor | Score | Description |
|---|---|---|---|
| ① | EMA Ribbon | +1 | EMA20 > EMA50 |
| ② | Long-Term Trend | +1 | close > EMA200 |
| ③ | RSI Direction | +1 | RSI(14) > 50 |
| ④ | ADX Trend Confirmation | +1 | ADX > 20 (scores for both directions, indicates a trending market) |
| ⑤ | Linear Regression Slope | +1 | 20-bar linear regression slope > 0 |
| ⑥ | Volume | +1 | Volume > average of previous 20 bars, and bullish candle |
| ⑦ | HTF Trend | +1 | H1 close > H1 EMA50 |
| ⑧ | Stoch RSI | +1 | K > 50 |
| ⑨ | MACD | +1 | MACD > 0 |
| ⑩ | Volatility Expansion | +1 | ATR > ATR20 × 1.1, and long direction dominates |
| ⑪ | BB Position | +1 | price_pos > 0.5 (in the upper half) |
| ⑫ | Structure Breakout | +1 | close is the 20-bar high (HH20) |
| ⑬ | DI Direction | +1 | +DI > -DI |
| ⑭ | RSI Overextension | -1 | Deducted when RSI > 70 (do not chase longs when overbought) |
| ① | EMA Ribbon | +1 | EMA20 < EMA50 |
| ② | Long-Term Trend | +1 | close < EMA200 |
| ③ | RSI Direction | +1 | RSI(14) < 50 |
| ④ | ADX Trend Confirmation | +1 | ADX > 20 (scores for both directions) |
| ⑤ | Linear Regression Slope | +1 | 20-bar linear regression slope < 0 |
| ⑥ | Volume | +1 | Volume > average of previous 20 bars, and bearish candle |
| ⑦ | HTF Trend | +1 | H1 close < H1 EMA50 |
| ⑧ | Stoch RSI | +1 | K < 50 |
| ⑨ | MACD | +1 | MACD < 0 |
| ⑩ | Volatility Expansion | +1 | ATR > ATR20 × 1.1, and short direction dominates |
| ⑪ | BB Position | +1 | price_pos < 0.5 (in the lower half) |
| ⑫ | Structure Breakout | +1 | close is the 20-bar low (LL20) |
| ⑬ | DI Direction | +1 | -DI > +DI |
| ⑭ | RSI Overextension | -1 | Deducted when RSI < 30 (do not short when oversold) |
**Threshold:** ≥10/14 = SIGNAL, ≥11/14 = God-Tier.
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | Profit Pullback TP | 25% pullback from peak profit (peak > 0.5ATR) |
| ② | ATR Trailing | Pullback from peak exceeds 1.5 ATR |
| ③ | Hard Stop | Loss exceeds 2.0 ATR |
## Special Rules
- Covers the 5 major categories: Trend / Momentum / Volatility / Volume / Structure
- Source: TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- Data Source: All indicators are read from DataFactory TA-Lib
