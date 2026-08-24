---
name: xaubot_backup
magic: 777005

type: 其他
display: xaubot-ai — XGBoost ML 后备策略
desc: H1 XGBoost 二分类 ML 模型，80+ 技术特征，置信度阈值 0.52
---

## 评分因子
| # | 因子 | 得分 | 说明 |
| ① | XGBoost 预测 | 概率 | 模型输出上涨概率 > 置信度阈值 0.52 |
| # | 因子 | 得分 | 说明 |
| ① | XGBoost 预测 | 概率 | 模型输出下跌概率 > 置信度阈值 0.52（1 - 上涨概率） |
**特征工程：** 80+ 技术特征，包括 RSI(14)、ATR(14)、MACD(12,26,9)、布林带(20,2)、EMA 交叉(9/21)、成交量特征、ML 特征（多周期收益率、价格位置、滞后价格、HH/LL、时间特征）。
## 出场逻辑
| # | 条件 | 说明 |  |
| # | 条件 | 说明 |
| ① | ATR 移动追踪 | 峰值回撤超过 3.0 ATR |
| ② | 硬止损 | 亏损超过 2.0 ATR |
## 特别规则
- Walk-forward XGBoost 二分类模型，预测下一根 K 线方向
- Polars 特征工程，需 xgboost + polars 依赖
- 优先加载 `models/xaubot_model.ubj` 预训练模型
- 无预训练模型时首次加载自动从 SQLite 训练
- 训练参数：max_depth=3, learning_rate=0.024, min_child_weight=10, subsample=0.7
- 数据源：全部指标从 DataFactory TA-Lib 读取
- Walk-forward XGBoost 二分类模型，预测下一根 K 线方向
- Polars 特征工程，需 xgboost + polars 依赖
- 优先加载 `models/xaubot_model.ubj` 预训练模型
- 无预训练模型时首次加载自动从 SQLite 训练
- 训练参数：max_depth=3, learning_rate=0.024, min_child_weight=10, subsample=0.7