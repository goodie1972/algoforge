---
name: xaubot_backup
magic: 777005
type: 其他
display: xaubot-ai — XGBoost ML 后备策略
desc: H1 XGBoost 二分类 ML 模型，80+ 技术特征，置信度阈值 0.52
---

**适用周期：** H1（模型训练与预测同周期；代码缺省回退 H1）

## 评分因子
| # | 因子 | 得分 | 说明 |
|---|---|---|---|
| ① | XGBoost 预测 | 概率 | 模型输出上涨概率 > 置信度阈值 0.52 |

| # | 因子 | 得分 | 说明 |
|---|---|---|---|
| ① | XGBoost 预测 | 概率 | 模型输出下跌概率 > 置信度阈值 0.52（1 - 上涨概率） |
**特征工程：** 80+ 技术特征，包括 RSI(14)、ATR(14)、MACD(12,26,9)、布林带(20,2)、EMA 交叉(9/21)、成交量特征、ML 特征（多周期收益率、价格位置、滞后价格、HH/LL、时间特征）。
## 出场逻辑
| # | 条件 | 说明 |
|---|---|---|
| ① | ATR 移动追踪 | 峰值回撤超过 3.0 ATR |
| ② | 硬止损 | 亏损超过 2.0 ATR |
## 参数说明
| 参数 | 取值 | 说明 |
|---|---|---|
| 置信度阈值 | 0.52 | 上涨/下跌概率 > 0.52 才触发信号 |
| 追踪止损 | 3.0×ATR | 峰值回撤超限出场 |
| 硬止损 | 2.0×ATR | 相对开仓价亏损超限出场 |
| 开仓 SL 距离 | 3.0×ATR | get_dynamic_sl_tp 按 3.0×ATR 挂单 |
| 训练/测试切分 | 70% / 30%（含 ≤50 根 gap） | Walk-forward 防数据泄漏 |
| XGBoost 参数 | max_depth=3, lr=0.024, min_child_weight=10, subsample=0.7, colsample=0.6 | 另含 reg_alpha=1.0 / reg_lambda=5.0 / gamma=1.0 |
| Boosting 轮数 | 100（早停 10 轮） | early_stopping_rounds=10 |
| 特征数量 | 80+ | RSI/ATR/MACD/BB/EMA 交叉/成交量/滞后/时间特征 |
| 训练样本下限 | 总 ≥300 根、清洗后 ≥200 条 | 不足则不训练不出信号 |
## 风控
- 硬止损：2.0×ATR（相对开仓价），亏损超限立即出场
- ATR 移动追踪止损：峰值回撤超过 3.0×ATR 出场，锁住浮盈
- 模型未就绪禁入：未拟合（缺预训练模型且训练未完成）时不产生任何信号；xgboost / polars 依赖缺失时 ML 整体禁用
- 训练重试冷却：训练失败后 300 秒内不重试，防止每 tick 反复训练拖垮引擎；K 线不足 300 根不训练、不足 30 根不预测
- 低置信度不交易：双向概率均 ≤0.52 时空仓观望，宁缺毋滥
- 最大持仓：1 单（STRATEGY_POOL 配置）
## 特别规则
- Walk-forward XGBoost 二分类模型，预测下一根 K 线方向
- Polars 特征工程，需 xgboost + polars 依赖
- 优先加载 `models/xaubot_model.ubj` 预训练模型
- 无预训练模型时首次加载自动从 SQLite 训练
- 训练参数：max_depth=3, learning_rate=0.024, min_child_weight=10, subsample=0.7
- 数据源：全部指标从 DataFactory TA-Lib 读取