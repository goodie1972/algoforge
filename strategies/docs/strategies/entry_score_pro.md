---
name: entry_score_pro
magic: 661501

type: 评分
display: Entry Score PRO — 5因子加权评分
desc: H1 5因子加权评分系统，评分0-100，阈值≥75触发
desc_en: H1 5-factor weighted scoring system, scoring 0-100, threshold ≥75 triggers
---

## 评分因子

### BUY（做多）
| # | 因子 | 权重 | 说明 |
|:-:|:----|:----:|:----|
| ① | 结构 | 30% | HTF EMA 排列 + K 线方向，close>EMA50 加 25 分，ADX>25 且 +DI>-DI 再加 25 分 |
| ② | 临近 | 25% | 距最近摆动低点 <1ATR → 80 分，<2ATR → 65 分 |
| ③ | 动量 | 15% | 实体/范围比，阳线实体占比越大得分越高 |
| ④ | 波动 | 10% | 当前 ATR / 30 根前 ATR 在 0.8~1.3 之间 → 70 分（健康波动） |
| ⑤ | 趋势 | 20% | close>MA14 加 30 分，RSI>50 加 20 分 |

### SELL（做空）
| # | 因子 | 权重 | 说明 |
|:-:|:----|:----:|:----|
| ① | 结构 | 30% | close<EMA50 加 25 分，ADX>25 且 -DI>+DI 再加 25 分 |
| ② | 临近 | 25% | 距最近摆动高点 <1ATR → 80 分，<2ATR → 65 分 |
| ③ | 动量 | 15% | 实体/范围比，阴线实体占比越大得分越高 |
| ④ | 波动 | 10% | 当前 ATR / 30 根前 ATR 在 0.8~1.3 之间 → 70 分 |
| ⑤ | 趋势 | 20% | close<MA14 加 30 分，RSI<50 加 20 分 |

**综合评分：** 加权平均（0-100），ENTRY WINDOW ≥75，PRIME ≥80，STRONG ≥85，SUSTAINED ≥80 连续 3 根。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 初始 SL | ±0.55 ATR |
| ② | ATR 移动追踪 | 峰值回撤超过 1.5 ATR 触发 |
| ③ | 初始 TP | 3×SL（R:R=3:1） |

## 特别规则

- 来源：TradingView No-Repaint Entry Score Multi-Factor Confluence [LunqFX]
- SL=入场区 ±0.55ATR，TP=下一摆动点
- 数据源：全部指标从 DataFactory TA-Lib 读取
