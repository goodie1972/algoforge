---
name: sanqing_h1_upgraded
magic: 880108

type: 趋势
display: H1 SanQing 升级版
display_en: H1 SanQing Upgraded
desc: EMA9/21趋势评分 + 高位拦截 + 动态利润回撤止盈
desc_en: EMA9/21 Trend Score + Athlete Pullback to EMA9 Entry + ADX Adaptive Exit
---

## 评分因子

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | 上涨趋势 | +2 | EMA9 > EMA21 |
| 2 | EMA金叉 | +1 | EMA9上穿EMA21 |
| 3 | 回抽EMA9 | +2 | low ≤ EMA9×1.002 且 close > EMA9 |
| 4 | 实体>1ATR | +1 | 实体长度超过1倍ATR |
| 5 | 放量 | +1 | 成交量 > 均量×1.3 |
| 6 | 吞没形态 | +2 | 实体中位数≥1.5且实体/前高≥1.5且实体占K线≥50% |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | 下跌趋势 | +2 | EMA9 < EMA21 |
| 2 | EMA死叉 | +1 | EMA9下穿EMA21 |
| 3 | 回抽EMA9 | +2 | high ≥ EMA9×0.998 且 close < EMA9 |
| 4 | 实体>1ATR | +1 | 实体长度超过1倍ATR |
| 5 | 放量 | +1 | 成交量 > 均量×1.3 |
| 6 | 吞没形态 | +2 | 实体中位数≥1.5且实体/前高≥1.5且实体占K线≥50% |


## 运动员验票

| 方向 | 条件 |
|:----|:----|
| BUY | 等价格回抽到 ≤ EMA9×1.002 再入场 |
| SELL | 等价格反弹到 ≥ EMA9×0.998 再入场 |

## Athlete Ticket Check

| 方向 | 条件 |
|:----|:----|
| BUY | 等价格回抽到 ≤ EMA9×1.002 再入场 |
| SELL | 等价格反弹到 ≥ EMA9×0.998 再入场 |

## 出场逻辑（ADX 自适应）

| # | 条件 | 震荡(ADX≤25) | 中等趋势(ADX 25~35) | 强趋势(ADX>35) |
|:-:|:----|:----:|:----:|:----:|
| ① | ADX自适应追踪止损 | 1.5 ATR 回撤 | 2.5 ATR 回撤 | 3.5 ATR 回撤 |
| ② | ADX自适应止盈 | 2.5 ATR | 4.0 ATR | 6.0 ATR |
| ③ | 硬止损（固定） | 1.5 ATR | 1.5 ATR | 1.5 ATR |
| ④ | 利润回撤+DI保护 | 峰值回撤25%，DI对齐(趋势完好)时跳过回撤止盈 |
| ⑤ | DI反转出场 | 开仓5分钟后: BUY持仓NDI>PDI / SELL持仓PDI>NDI |

## Exit Logic (ADX Adaptive)

| # | Condition | Range (ADX≤25) | Medium Trend (25~35) | Strong Trend (ADX>35) |
|:-:|:---------|:----:|:----:|:----:|
| ① | ADX adaptive trailing stop | 1.5 ATR drawdown | 2.5 ATR drawdown | 3.5 ATR drawdown |
| ② | ADX adaptive take profit | 2.5 ATR | 4.0 ATR | 6.0 ATR |
| ③ | Hard stop (fixed) | 1.5 ATR | 1.5 ATR | 1.5 ATR |
| ④ | Profit drawdown + DI protection | Peak drawdown 25%, skip if DI aligned (trend intact) |
| ⑤ | DI reversal exit | 5 min after open: BUY pos NDI>PDI / SELL pos PDI>NDI |

## 特别规则

- 阈值: **固定 5 分**（评分 3→5，提高入场门槛，减少低质量信号约60%）
- **ADX 门禁**: ADX>25 时才允许入场（20→25，加强趋势过滤）
- **位置门禁**: 价格在60根K线顶部10%禁多，底部10%禁空
- **硬止损**: 1.2 ATR（1.5→1.2，每笔约36点，防大亏）
- **v10_optimized (2026-08-08)**: 提高评分阈值至5、ADX阈值至25、硬止损收紧至1.2ATR，减少交易量、提升信号质量
- 数据源: 全部指标从 DataFactory TA-Lib 读取

## Special Rules

- 阈值: **Fixed 5 points**（评分 3→5，提高入场门槛，减少低质量信号约60%）
- **ADX Gate**: ADX>25 时才允许入场（20→25，加强趋势过滤）
- **Position Gate**: Price in top 10% of 60-bar range blocks long，bottom 10% blocks short
- **硬止损**: 1.2 ATR（1.5→1.2，每笔约36点，防大亏）
- **v10_optimized (2026-08-08)**: 提高Score threshold至5、ADX阈值至25、硬止损收紧至1.2ATR，减少交易量、提升信号质量
- Data source: All indicators from DataFactory TA-Lib
