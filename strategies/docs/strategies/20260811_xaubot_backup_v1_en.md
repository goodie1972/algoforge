---
name: xaubot_backup
magic: 777005
type: Other
display_en: xaubot-ai — XGBoost ML Backup Strategy
desc_en: H1 XGBoost binary classification ML model, 80+ technical features, confidence threshold 0.52
---

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

## Special Rules

- Walk-forward XGBoost binary classification model, predicts next bar direction
- Polars feature engineering, requires xgboost + polars dependencies
- Prefers loading pretrained model `models/xaubot_model.ubj`
- Without pretrained model, auto-trains from SQLite on first load
- Training params: max_depth=3, learning_rate=0.024, min_child_weight=10, subsample=0.7
- Data source: All indicators from DataFactory TA-Lib
