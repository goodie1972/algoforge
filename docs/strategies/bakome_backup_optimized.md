---
name: bakome_backup_optimized
magic: 777006
version: v3_optimized
display: BAKOME GoldScalper 优化版
desc: ICT FVG + Order Block + Silver Bullet 时段交易 + ADX自适应出场
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

## 出场逻辑（ADX 自适应）

| # | 条件 | 震荡(ADX≤25) | 中等趋势(ADX 25~35) | 强趋势(ADX>35) |
|:-:|:----|:----:|:----:|:----:|
| ① | ADX自适应止盈 | 1.5 ATR | 3.0 ATR | 5.0 ATR |
| ② | ADX自适应追踪止损 | 1.0 ATR 回撤 | 2.0 ATR 回撤 | 3.0 ATR 回撤 |
| ③ | ADX自适应硬止损 | 2.0 ATR | 3.5 ATR | 5.0 ATR |

## BB扩张 + MFI方向拦截

BB扩张期间，价格位置与MFI方向一致时禁止同向开仓，防趋势加速接飞刀。

| 条件 | 拦截 |
|:----|:----|
| BB扩张(ratio>1.2) + 正在扩张 + 价格>中轴 + MFI上升 | 禁做空 |
| BB扩张(ratio>1.2) + 正在扩张 + 价格<中轴 + MFI下降 | 禁做多 |

## 特别规则

- **非Silver Bullet时段不出信号**
- **ADX自适应出场**：强趋势（ADX>35）放宽追踪和止盈让利润跑，震荡（ADX≤25）收紧快速落袋
- **BB扩张+MFI方向拦截**：防止在强趋势中接飞刀
- 初始SL/TP: 2.0ATR（宽止损）+ 超大TP，出场全权交给 check_ema20_exit
- 硬止损固定 1.5 ATR（不随ADX变化）
- ATR过滤器：无ATR数据不出信号
- 数据源: 全部指标从 DataFactory TA-Lib 读取
