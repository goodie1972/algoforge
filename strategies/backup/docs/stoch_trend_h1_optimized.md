---
name: stoch_trend_h1_optimized
magic: 661202

type: 趋势
display: Stoch 回调顺势策略 (v7_optimized)
desc: H1 多周期 Stoch 评分系统，ADX>20，Stoch(14,3,3)
desc_en: H1 multi-TF Stoch scoring, ADX>20, Stoch(14,3,3)
---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | Stoch 极端区 | +2 | H1 Stoch(14,3,3) K < 20 |
| ② | Stoch 金叉 | +2 | K 线上穿 D 线 |
| ③ | EMA21 方向对齐 | +1 | close > EMA21 |
| ④ | DI 方向对齐 | +1 | +DI > -DI |
| ⑤ | H4 趋势对齐 | +1 | H4 close > EMA21（上行） |
| ⑥ | M15 Stoch 对齐 | +1 | M15 Stoch(14,3,3) K < 30 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | Stoch 极端区 | +2 | H1 Stoch(14,3,3) K > 80 |
| ② | Stoch 死叉 | +2 | K 线下穿 D 线 |
| ③ | EMA21 方向对齐 | +1 | close < EMA21 |
| ④ | DI 方向对齐 | +1 | -DI > +DI |
| ⑤ | H4 趋势对齐 | +1 | H4 close < EMA21（下行） |
| ⑥ | M15 Stoch 对齐 | +1 | M15 Stoch(14,3,3) K > 70 |

**阈值：** 满分 8 分，≥4 分触发信号。H4/M15 桥接加载失败时跳过对应因子。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 硬止损 | 亏损超过 2.0 ATR |
| ② | ATR 追踪止盈 | 峰值回撤超过 1.5 ATR |
| ③ | 利润回撤止盈 | 峰值利润回撤 N%（ADX>25 放宽至 50%） |
| ④ | 保本出场 | 走过 ≥0.3ATR 盈利后回到成本附近 |
| ⑤ | ADX<20 | 趋势衰竭出场 |
| ⑥ | DI 反转 | BUY 持仓 -DI>+DI 或 SELL 持仓 +DI>-DI 时出场 |

## 特别规则

- 核心变化 vs v6：ADX 阈值从 25 降到 20；Stoch(21,5,3) → Stoch(14,3,3) 更快响应；AND 逻辑 → 加权评分系统
- ADX ≤ 20：弱势震荡，不交易
- 多周期架构：H4 趋势 + H1 评分 + M15 Stoch 对齐
- 数据源：全部指标从 DataFactory TA-Lib 读取
