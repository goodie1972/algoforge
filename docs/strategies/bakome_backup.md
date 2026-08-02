---name: bakome_backup
magic: 777004

type: 其他
display: BAKOME GoldScalper 原版
desc: ICT FVG + Order Block + Silver Bullet 时段交易（原版）---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | Silver Bullet时段 | 必需 | London(8~10)或NY(13~15) MT4时间 |
| 2 | FVG向上缺口 | 1 | prev.prev.low > current.high（价格缺口）|
| 3 | Order Block | 1 | 2根大涨后找到前一根大阴线为OB，价格回踩OB区 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | Silver Bullet时段 | 必需 | London(8~10)或NY(13~15) MT4时间 |
| 2 | FVG向下缺口 | 1 | prev.prev.high < current.low（价格缺口）|
| 3 | Order Block | 1 | 2根大跌后找到前一根大阳线为OB，价格回抽OB区 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR追踪止损(trail) | 2.5 ATR 回撤 |
| ② | ATR硬止损(hard) | 1.5 ATR |

## BB扩张 + MFI方向拦截

BB扩张期间，价格位置与MFI方向一致时禁止同向开仓，防趋势加速接飞刀。

| 条件 | 拦截 |
|:----|:----|
| BB扩张(ratio>1.05) + 正在扩张 + 价格>中轴 + MFI上升 | 禁做空 |
| BB扩张(ratio>1.05) + 正在扩张 + 价格<中轴 + MFI下降 | 禁做多 |

## 特别规则

- 非Silver Bullet时段不出信号
- **BB扩张+MFI方向拦截**：防止在强趋势中接飞刀
- 数据源: 全部指标从 DataFactory TA-Lib 读取
