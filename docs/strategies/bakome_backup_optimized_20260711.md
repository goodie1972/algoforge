---
name: bakome_backup_optimized
magic: 777006
version: v2_optimized
display: BAKOME GoldScalper 优化版
desc: ICT FVG + Order Block + Silver Bullet 时段交易
---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | Silver Bullet时段 | 必需 | London(11~15)或NY(17~21) UTC+8 |
| 2 | FVG向上缺口 | 1 | prev.prev.low > current.high（价格缺口）|
| 3 | Order Block | 1 | 2根大涨后找到前一根大阴线为OB，价格回踩OB区 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | Silver Bullet时段 | 必需 | London(11~15)或NY(17~21) UTC+8 |
| 2 | FVG向下缺口 | 1 | prev.prev.high < current.low（价格缺口）|
| 3 | Order Block | 1 | 2根大跌后找到前一根大阳线为OB，价格回抽OB区 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR追踪止损(trail) | 2.5 ATR 回撤 |
| ② | ATR硬止损(hard) | 1.5 ATR |

## 特别规则

- **非Silver Bullet时段不出信号**
- 初始SL/TP: 2.0ATR（宽止损）+ 超大TP，出场全权交给 check_ema20_exit
- ATR过滤器：无ATR数据不出信号
- 数据源: 全部指标从 DataFactory TA-Lib 读取
