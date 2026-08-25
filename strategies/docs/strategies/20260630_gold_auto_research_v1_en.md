---
name: gold_auto_research
magic: 880306
type: ML
display_en: Gold-AutoResearch — H1 Live Trading Strategy
desc_en: H1 4-factor consensus voting strategy + high-position block (price_position>0.82 and deviation from EMA21>2.5×ATR blocks BUY) + low-position block (<0.18 and deviation<−2.5×ATR blocks SELL)
---

**Timeframe:** H1

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
## Risk Control
- 4-Factor Consensus (AND logic): Triggered only when all 4 items - trend / momentum / volatility activity / safety - agree; no trade if any is missing
- H4 SMA50 Trend Gate: H4 downtrend blocks BUY, H4 uptrend blocks SELL
- Breakeven Exit: Close when the price returns to within ±0.05×ATR of cost after reaching ≥0.3×ATR profit
- Hard Stop: Close when the loss exceeds hard_mult × ATR (with-trend 3.0 / counter-trend 2.0 / ranging 2.5); order-level SL attached accordingly
- Profit Pullback TP: 25% pullback from peak; relaxed to 50% when ADX>25, tightened to 35% when peak profit >$10
- ATR Trailing TP: Trail multiplier locked at entry (with-trend 1.5 / counter-trend 1.0 / ranging 1.2); exit when the drop from peak exceeds multiplier ×ATR
- Max Positions: 1 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| p_trailing_atr | 1.0 | ATR trailing take-profit base multiplier |
| p_hard_atr | 2.0 | Hard stop ATR base multiplier |
| Volatility activity threshold | ADX>20 or ATR above its 20-bar average | Activation condition for factor ③ |
| RSI(10) safety line | ≥70 and price ≥BB upper band blocks longs; ≤35 blocks shorts independently | Safety filter for factor ④ |
| High-position block | price_position>0.82 and deviation from EMA21>2.5×ATR blocks BUY | Prevent chasing highs |
| Low-position block | price_position<0.18 and deviation from EMA21<−2.5×ATR blocks SELL | Prevent chasing lows |
| profit_drawdown_pct | 0.25 | Profit pullback take-profit ratio (relaxed to 0.5 when ADX>25) |
## Special Rules
- H4 SMA50 Trend Gate: H4 downtrend blocks BUY, H4 uptrend blocks SELL
- Position Gate: high-position block (price_position>0.82 and deviation from EMA21>2.5×ATR blocks BUY), low-position block (<0.18 and deviation<−2.5×ATR blocks SELL)
- Data Source: All indicators are read from DataFactory TA-Lib
