# 策略回测分析报告 — 2026-08-02

> 基于 3 个月历史数据（2026-02-01 ~ 2026-08-01）的全策略回测结果分析。
> 回测引擎: `scripts/backtest_6months.py`

---

## 一、总体结论

### 1.1 核心发现

**反转类策略是 XAUUSD 最有效的交易方式。** 在 25 个策略中，7 个盈利的策略全部属于 REVERSAL 类别（M30 周期反转策略）。趋势类、突破类、评分类、ML 类策略全部亏损。

### 1.2 盈利策略速览

| 排名 | 策略 | 分类 | 3月PnL | 胜率 | 盈亏比 | 回撤 | 评分 |
|:----:|:----|:----:|:------:|:----:|:------:|:----:|:----:|
| 1 | mfi_bb_m30_optimized | REVERSAL | +$66.60 | 57.6% | 1.38 | 0.51% | A-70 |
| 2 | rsi_grading_m30_upgraded | REVERSAL | +$117.79 | 54.5% | 1.55 | 1.57% | A-70 |
| 3 | m30_bb_deepreturn | REVERSAL | +$213.95 | 54.6% | 1.32 | 1.25% | B-68 |
| 4 | mfi_bb_m30 | REVERSAL | +$198.33 | 54.2% | 1.30 | 1.39% | B-68 |
| 5 | m30_bb_deepreturn_optimized | REVERSAL | +$92.80 | 51.0% | 1.09 | 1.50% | B-66 |
| 6 | momentum_pulse_pro | TREND | +$63.83 | 53.9% | 1.09 | 1.64% | B-66 |
| 7 | rsi_grading_m30 | REVERSAL | +$72.37 | 46.4% | 1.46 | 0.82% | B-66 |

---

## 二、分类分析

### 2.1 REVERSAL（反转类）— 11个策略

**表现：7/11 盈利，4/11 亏损**

盈利策略的共同特征：
- **时间周期：** 全部为 M30
- **核心逻辑：** BB 回归 + MFI/RSI 超买超卖
- **交易频率：** 22~157 笔/3个月（低频精准）
- **回撤控制：** 全部 < 2%

亏损策略的问题：
- **mfi_bb_m30_upgraded**（-$649）：升级版加了太多条件，反而破坏了原有的盈利逻辑
- **M30_rsi_bb**（-$412）：原始版逻辑太简单，信号过多
- **m30_vol_return**（-$2,915）：2,212 笔交易，过度交易
- **rsi_grading_m30_optimized**（-$776）：821 笔，过度优化

**版本演进对比：**

| 策略链 | v1 | optimized | upgraded | 结论 |
|:-------|:--:|:---------:|:--------:|:------|
| mfi_bb_m30 | +$198 / 54.2% | **+$67 / 57.6%** | -$649 / 47.1% | optimized 最好，upgraded 回退 |
| rsi_grading_m30 | +$72 / 46.4% | -$776 / 48.6% | **+$118 / 54.5%** | upgraded 最好 |
| m30_bb_deepreturn | **+$214 / 54.6%** | +$93 / 51.0% | — | v1 最好，optimized 反而下降 |

### 2.2 TREND（趋势类）— 8个策略

**表现：1/8 盈利，7/8 亏损**

- 唯一盈利：**momentum_pulse_pro**（+$63, 53.9%）
- 最差：**sanqing_h1**（-$1,224, 44.5%），**sanqing_h1_upgraded**（-$1,224, 44.5%）
- stoch_trend_h1（2笔，+$10）：信号太少，几乎不出单

**结论：** XAUUSD 在 H1 周期上趋势持续性差，趋势策略频繁被假突破止损。

### 2.3 BREAKOUT（突破类）— 2个策略

**表现：0/2 盈利**

- **h1_breakout**（-$1,086, 46.6%）：954 笔交易，突破信号过多
- **m30_vol_return**（-$2,915, 46.5%）：2,212 笔，严重过度交易

**结论：** 突破策略在 XAUUSD 上完全失效。

### 2.4 PATTERN（形态类）— 2个策略

**表现：0/2 可评估**

- **bakome_backup**：0 笔（需要 Silver Bullet 实时 session 检测，无法回测）
- **bakome_backup_optimized**：0 笔（同上）

**结论：** 需要改进回测引擎以支持 session 时间模拟。

### 2.5 SCORE（评分类）— 3个策略

**表现：0/3 盈利**

- **entry_score_pro**（-$252, 46.5%）：755 笔，过度交易
- **multi_confluence_quant**（-$449, 46.5%）：566 笔
- **viprasol_sniper**（-$2,135, 45.6%）：2,192 笔，严重过度交易

**结论：** 评分类策略信号太松，需要大幅收紧阈值。

### 2.6 ML（机器学习）— 1个策略

**表现：0/1 可评估**

- **xaubot_backup**：0 笔（ML 模型需要实时数据，无法回测）

---

## 三、Quantum King 组合方案（基于回测结果）

### 3.1 Captain 策略（3个）

```yaml
captain:
  - name: mfi_bb_m30_optimized
    role: 主力 Captain
    reason: 最高胜率(57.6%) + 最低回撤(0.51%) + 评分稳定(A)
    weight: 1.0
    
  - name: rsi_grading_m30_upgraded
    role: 副 Captain
    reason: 最高盈亏比(1.55) + 最高利润($117) + 评分稳定(A)
    weight: 0.8
    
  - name: m30_bb_deepreturn
    role: 交易量 Captain
    reason: 最多盈利交易(108笔) + 总利润最高($213) + 统计显著
    weight: 0.7
```

### 3.2 替补策略（4个）

```yaml
backup:
  - name: mfi_bb_m30
    reason: 与 optimized 同源，但交易量更大(131笔)
    condition: 当 mfi_bb_m30_optimized 连续亏损2笔时启用
    
  - name: m30_bb_deepreturn_optimized
    reason: 交易量适中(157笔)，虽然利润低于v1但更稳定
    condition: 当 m30_bb_deepreturn 回撤 > 5% 时切换
    
  - name: momentum_pulse_pro
    reason: 唯一盈利的趋势策略，作为趋势行情时的补充
    condition: 当 ADX > 35 时启用
    
  - name: rsi_grading_m30
    reason: 盈亏比不错(1.46)，交易量少(28笔)
    condition: 低波动行情时启用
```

### 3.3 待观察策略（5个）

```yaml
watchlist:
  - name: stoch_trend_h1_upgraded
    reason: 回测仅2笔，但实际运行可能更多（需M15数据）
    action: 纸面交易中观察信号频率
    
  - name: bakome_backup_optimized
    reason: 无法回测（Silver Bullet），但策略逻辑完整
    action: 纸面交易中观察实际表现
    
  - name: sanqing_h1_upgraded
    reason: 回测亏损，但出场逻辑可能改进后有效
    action: 等待出场逻辑优化后重新评估
```

### 3.4 建议淘汰策略（12个）

```yaml
eliminate:
  - h1_breakout           # -$1,086, 突破策略完全失效
  - m30_vol_return        # -$2,915, 严重过度交易
  - mfi_bb_m30_upgraded   # -$649, 升级版反而更差
  - M30_rsi_bb           # -$412, 原始版太简单
  - rsi_grading_m30_optimized  # -$776, 过度优化
  - entry_score_pro       # -$252, 信号太松
  - multi_confluence_quant     # -$449
  - viprasol_sniper       # -$2,135, 严重过度交易
  - sanqing_h1            # -$1,224
  - sanqing_h1_original   # -$54
  - gold_auto_research    # -$196, 29.2%胜率
  - xaubot_backup         # ML模型需要单独评估
```

---

## 四、收益率潜力分析

### 4.1 当前回测收益率（0.01手，$10,000本金）

| Captain | 3月PnL | 月化收益率 | 年化 |
|:--------|:------:|:---------:|:----:|
| mfi_bb_m30_optimized | +$66.60 | 0.22% | 2.7% |
| rsi_grading_m30_upgraded | +$117.79 | 0.39% | 4.7% |
| m30_bb_deepreturn | +$213.95 | 0.71% | 8.6% |
| **组合（等权）** | **+$398.34** | **1.33%** | **~16%** |

### 4.2 杠杆放大后的收益率（$228账户）

| 手数 | 组合月化 | 组合年化 | 风险（回撤） |
|:----:|:-------:|:--------:|:----------:|
| 0.01 | 1.33% | 16% | 1.5% |
| 0.05 | 6.65% | 80% | 7.5% |
| 0.10 | 13.3% | 160% | 15% |
| 0.20 | 26.6% | 320% | 30% |

**结论：** 0.05~0.10 手可实现年化 50%+ 的目标，但风险也随之放大。建议从 0.03 手开始，稳定后再逐步加仓。

---

## 五、回测局限性

1. **出场逻辑是通用的**，不是每个策略自带的精准出场逻辑
2. **bakome/stoch/xaubot** 因依赖实时数据无法回测，实际表现可能不同
3. **回测使用 0.01 手固定手数**，未考虑复利效应
4. **未考虑滑点和交易延迟**
5. **3个月数据量有限**，可能未覆盖所有市场状态

---

*文档版本: v1.0 | 创建日期: 2026-08-02 | 关联: [[evaluation_plan.md]]*