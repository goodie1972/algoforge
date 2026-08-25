---
name: xaubot_backup
magic: 777005
type: Other
display_en: xaubot-ai — XGBoost ML Backup Strategy
desc_en: H1 XGBoost binary classification ML model, 80+ technical features, confidence threshold 0.52
---

**Timeframe:** H1 (model training and prediction on the same timeframe; code defaults to fall back to H1)

## Scoring Factors

### BUY (Long)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| ① | XGBoost prediction | Probability | Model output up-probability > confidence threshold 0.52 |

### SELL (Short)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| ① | XGBoost prediction | Probability | Model output down-probability > confidence threshold 0.52 (1 − up-probability) |

**Feature Engineering:** 80+ technical features, including RSI(14), ATR(14), MACD(12,26,9), Bollinger Bands(20,2), EMA crossovers(9/21), volume features, and ML features (multi-timeframe returns, price position, lagged prices, HH/LL, time features).

## Exit Logic

| # | Condition | Description |
|:----:|:----|:----|
| ① | ATR moving trail | Peak drawdown exceeds 3.0 ATR |
| ② | Hard stop | Loss exceeds 2.0 ATR |

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Confidence threshold | 0.52 | Signal triggered only when up/down probability > 0.52 |
| Trailing stop | 3.0×ATR | Exit when peak drawdown exceeds limit |
| Hard stop | 2.0×ATR | Exit when loss relative to open price exceeds limit |
| Opening SL distance | 3.0×ATR | get_dynamic_sl_tp places order at 3.0×ATR |
| Train/test split | 70% / 30% (with ≤50-bar gap) | Walk-forward prevents data leakage |
| XGBoost params | max_depth=3, lr=0.024, min_child_weight=10, subsample=0.7, colsample=0.6 | Also reg_alpha=1.0 / reg_lambda=5.0 / gamma=1.0 |
| Boosting rounds | 100 (early stop 10 rounds) | early_stopping_rounds=10 |
| Feature count | 80+ | RSI/ATR/MACD/BB/EMA crossover/volume/lagged/time features |
| Training sample floor | Total ≥300 bars, ≥200 after cleaning | No training and no signal if insufficient |

## Risk Control

- Hard stop: 2.0×ATR (relative to open price), exit immediately when loss exceeds limit
- ATR moving trailing stop: exit when peak drawdown exceeds 3.0×ATR, locking in floating profit
- Model-not-ready ban: no signals produced when not fitted (no pretrained model and training incomplete); ML fully disabled when xgboost / polars dependencies are missing
- Training retry cooldown: no retry within 300 seconds after training failure, preventing repeated per-tick training from dragging down the engine; no training with <300 bars, no prediction with <30 bars
- No trade on low confidence: stay flat when both-direction probabilities are ≤0.52, better to miss than to force
- Max position: 1 order (STRATEGY_POOL config)

## Special Rules

- Walk-forward XGBoost binary classification model, predicts next bar direction
- Polars feature engineering, requires xgboost + polars dependencies
- Prefers loading pretrained model `models/xaubot_model.ubj`
- Without pretrained model, auto-trains from SQLite on first load
- Training params: max_depth=3, learning_rate=0.024, min_child_weight=10, subsample=0.7
- Data source: All indicators from DataFactory TA-Lib
