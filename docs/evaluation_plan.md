# 策略纸面交易评测方案 v1.0

> 目标：通过一周（7天）的纸面交易，客观评估所有策略的优劣，为组合改造提供数据支撑。

---

## 一、评测周期与数据采集

### 运行配置
- **模式：** 纸面交易（Paper Trading），全部启用
- **周期：** 连续运行 7 天（168小时），中途不重启引擎
- **策略数量：** 所有 25 个策略全部启用
- **最大持仓：** 每个策略 5 张（所有策略统一，避免 max_positions 差异影响比较）
- **数据记录：** 引擎自动记录到 `data/market_data.db` 的 `trades` 表

### 每日数据采集点（北京时间 08:00）

每天固定时间从数据库导出以下数据：

```bash
# 1. 当日成交汇总
python scripts/analyze_closed_trades.py --days=1

# 2. 当前持仓快照
curl http://127.0.0.1:1783/api/positions

# 3. 账户状态
curl http://127.0.0.1:1783/api/account
```

### 需要关注的隐患
- 引擎意外停止 → 自动重启（参照 feedback_auto_restart_engine.md）
- MT4 断线 → 检查 bridge_connected 状态
- 数据库写入异常 → 检查 trades 表数据完整性

---

## 二、评估指标体系

每个策略从以下 **6 个维度** 评估，满分 100 分：

### 1. 盈利能力（30分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 总 PnL | 10分 | 策略所有已平仓交易的总盈亏 | ≥0 得 5 分，每多 10 分加 1 分，上限 10 分 |
| 胜率 | 10分 | 盈利交易数 / 总交易数 | <30%=0分, 30-40%=3分, 40-50%=5分, 50-60%=7分, ≥60%=10分 |
| 盈亏比 | 10分 | 平均盈利 / 平均亏损 | <1.0=0分, 1.0-1.2=3分, 1.2-1.5=5分, 1.5-2.0=7分, ≥2.0=10分 |

### 2. 风险控制（25分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 最大回撤率 | 10分 | 策略峰值到谷底的最大回撤 / 本策略起始资金 | <5%=10分, 5-10%=7分, 10-15%=5分, 15-20%=3分, >20%=0分 |
| 单笔最大亏损 | 8分 | 单笔最差交易亏损额 | <5 美元=8分, 5-10=5分, 10-15=3分, >15=0分 |
| 回撤恢复天数 | 7分 | 从最大回撤恢复到新高所需时间 | <1天=7分, 1-2天=5分, 2-3天=3分, >3天=0分 |

### 3. 交易信号质量（15分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 信号频率 | 5分 | 日均交易次数 | 0-1次/天=5分, 1-3次=3分, 3-5次=1分, >5次=0分（太少缺乏统计意义，太多说明信号太松） |
| 信号与评分一致性 | 5分 | 评分越高是否对应胜率越高 | 正相关显著=5分, 弱相关=3分, 无相关=0分 |
| 信号稳定性 | 5分 | 前3天vs后3天胜率波动 | 波动<10%=5分, 10-20%=3分, >20%=0分 |

### 4. 资金利用效率（10分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 收益率/交易次数 | 5分 | 总收益率 / 总交易次数 | 正收益高效率=5分, 正收益低效率=3分, 负收益=0分 |
| 持仓时间分布 | 5分 | 平均持仓时间 + 标准差 | 平均>1小时且标准差<2小时=5分, 其他=2分 |

### 5. 策略独特性（10分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 与同类策略相关性 | 5分 | 同组策略的持仓重叠率 | <20%=5分, 20-40%=3分, >40%=0分 |
| 市场适应度 | 5分 | 在不同市场状态下表现是否均衡 | 2种以上市场状态盈利=5分, 1种=2分, 0种=0分 |

### 6. 技术稳定性（10分）

| 指标 | 权重 | 计算方式 | 评分标准 |
|:----|:----:|:---------|:---------|
| 指标异常率 | 5分 | `get_indicator()` 返回 None 的比例 | <1%=5分, 1-5%=3分, >5%=0分 |
| 出错率 | 5分 | 策略执行中抛异常的比例 | 0次=5分, 1-3次=3分, >3次=0分 |

---

## 三、评价等级

根据总分对策略分档：

| 等级 | 分数 | 含义 | 后续动作 |
|:----|:----:|:----|:---------|
| **S级** 🏆 | ≥85 | 王牌策略 | 设为组合 Captain，允许 max_positions=8 |
| **A级** ✅ | 70-84 | 可靠策略 | 留在组合中，正常参与 |
| **B级** ⚠️ | 50-69 | 边际策略 | 保留但降低 max_positions=3，需观察 |
| **C级** ❌ | <50 | 待优化/淘汰 | 暂不启用，等待优化后再评估 |

### 一票否决条件

满足以下任一条件，**直接评为 C 级**，无需计算总分：

| # | 条件 | 说明 |
|:-:|:----|:------|
| 1 | 总 PnL < -50 美元 | 一周亏损超过 50 美元 |
| 2 | 最大回撤 > 30% | 本金保护失败 |
| 3 | 胜率 < 20% | 纯运气交易 |
| 4 | 交易次数 < 3 | 样本量不足，无法评估 |
| 5 | 致命错误 ≥ 3 次 | 策略代码有 bug 导致异常 |

---

## 四、跨策略对比方法

### 4.1 同组内横向对比

按策略类别分组，组内排名：

```
TREND 组排名:
  1. stoch_trend_h1_upgraded  (85分)
  2. sanqing_h1_upgraded      (72分)
  3. gold_auto_research        (65分)
  ...

REVERSAL 组排名:
  1. m30_vol_return            (82分)
  2. m30_bb_deepreturn_optimized (74分)
  ...
```

**同组内只保留前 2 名**进入组合，其余作为替补。

### 4.2 版本演进对比

对同一策略链的版本比较（如 `m30_mfi_bb` → `optimized` → `upgraded`）：

| 指标 | v1 | optimized | upgraded | 结论 |
|:----|:--:|:---------:|:--------:|:----|
| 总 PnL | -12 | +8 | +15 | 逐版改善 |
| 胜率 | 35% | 42% | 55% | 信号质量提升 |
| 最大回撤 | 22% | 15% | 8% | 风控改善 |

**结论：** 只保留最优版本，废弃旧版本。

### 4.3 市场状态适应度

评估每个策略在不同市场状态下的表现：

```
策略: stoch_trend_h1_upgraded
  强趋势(ADX>35): 胜率 68%, 总PnL +32 ✅
  弱趋势(25-35):  胜率 52%, 总PnL +12 ✅
  震荡(ADX≤25):   胜率 28%, 总PnL -8  ❌
  高波动:         胜率 40%, 总PnL -5  ❌
  低波动:         胜率 60%, 总PnL +18 ✅
  适应度评分: 3/5 (2种状态盈利)
```

---

## 五、数据收集脚本

### 5.1 生成评测报告

```bash
python scripts/evaluate_strategies.py --days=7
```

输出 JSON 文件 `data/evaluation/weekly_report.json`，包含所有策略的完整评分数据。

### 5.2 报告内容结构

```json
{
  "period": "2026-08-01 ~ 2026-08-07",
  "account": { "start_balance": 228.18, "end_balance": 0, "total_pnl": 0,
               "max_drawdown_pct": 0, "total_trades": 0 },
  "strategies": {
    "stoch_trend_h1_upgraded": {
      "total_pnl": 0, "win_rate": 0, "profit_factor": 0,
      "max_drawdown_pct": 0, "avg_win": 0, "avg_loss": 0,
      "total_trades": 0, "score": 0, "grade": "S",
      "market_adaptation": { "strong_trend": 0, "weak_trend": 0,
                             "ranging": 0, "high_vol": 0, "low_vol": 0 },
      "version_improvement": { "vs_previous": 0 }
    }
  },
  "rankings": {
    "overall": ["策略A", "策略B"],
    "by_group": {
      "TREND": ["策略A", "策略B"],
      "REVERSAL": ["策略C", "策略D"]
    }
  },
  "recommendations": {
    "captain_candidates": ["策略A", "策略B"],
    "eliminate": ["策略D"],
    "watchlist": ["策略E"]
  }
}
```

---

## 六、执行时间表

| 天 | 动作 | 输出 |
|:-:|:----|:-----|
| Day 0 | 启动引擎，启用全部 25 个策略，重置数据库 | 干净基线 |
| Day 1 | 运行 24h，检查引擎状态，确认无异常 | 初次运行确认 |
| Day 2 | 采集第 1 次数据，检查各策略信号频率 | 信号频率初筛 |
| Day 3 | 采集第 2 次数据，检查胜率稳定性 | 中期数据 |
| Day 4 | 采集第 3 次数据，检查市场状态适应度 | 适应度分析 |
| Day 5 | 采集第 4 次数据，检查回撤控制 | 风控评估 |
| Day 6 | 采集第 5 次数据，检查盈利效率 | 效率评估 |
| Day 7 | 最终采集，生成完整评测报告 | **完整报告** |
| Day 8 | 分析报告，确定策略分级 | 分级结果 |
| Day 9+ | 开始实施组合改造（Phase 1） | 组合系统 |

---

## 七、报告模板（最终输出格式）

```
═══════════════════════════════════════════
   XAUUSD 策略纸面交易评测报告 v1.0
   评测周期: 2026-08-01 ~ 2026-08-07
═══════════════════════════════════════════

📊 账户概况
   起始余额: $228.18
   期末余额: $XXX.XX
   总盈亏: $XXX.XX
   最大回撤: XX.XX%
   总交易数: XXX 笔

📋 策略分级总览
   ┌──────┬──────────────┬──────────┬──────┬──────┐
   │ 等级 │ 策略名       │ 总分     │ PnL  │ 胜率 │
   ├──────┼──────────────┼──────────┼──────┼──────┤
   │ S    │ stoch_trend_…│ XX       │ XX   │ XX%  │
   │ A    │ sanqing_…    │ XX       │ XX   │ XX%  │
   │ …    │ …            │ …        │ …    │ …    │
   │ C    │ bakome_backup│ XX       │ XX   │ XX%  │
   └──────┴──────────────┴──────────┴──────┴──────┘

🏆 组内排名
   TREND 组:    1) stoch_trend_h1_upgraded (XX分)
                2) sanqing_h1_upgraded (XX分)
   REVERSAL 组: 1) m30_vol_return (XX分)
                2) m30_bb_deepreturn_optimized (XX分)
   BREAKOUT 组: 1) h1_breakout (XX分)

📈 版本演进 vs 回测预期
   m30_mfi_bb         v1: PnL=XX 胜率=XX% vs 预期XX
   m30_mfi_bb_optimized: PnL=XX 胜率=XX% vs 预期XX
   → 结论: [优化成功/失败]

🎯 组合建议
   Captain 推荐: [策略A, 策略B]
   Captain 替补: [策略C, 策略D]
   待优化: [策略E, 策略F]
   淘汰: [策略G, 策略H]
```

---

## 八、评测脚本

后续需要创建 `scripts/evaluate_strategies.py` 脚本，从数据库读取数据自动计算所有指标并生成报告。

```python
# 伪代码框架
def evaluate_strategies(days=7):
    trades = load_trades_from_db(last_n_days=days)
    account_snapshots = load_account_snapshots(last_n_days=days)
    
    for strategy_name in all_strategies:
        strategy_trades = [t for t in trades if t.strategy == strategy_name]
        
        score = {
            "profitability": calc_profitability_score(strategy_trades),
            "risk_control": calc_risk_score(strategy_trades, account_snapshots),
            "signal_quality": calc_signal_quality_score(strategy_trades),
            "efficiency": calc_efficiency_score(strategy_trades),
            "uniqueness": calc_uniqueness_score(strategy_name, strategy_trades, trades),
            "stability": calc_stability_score(strategy_name),
        }
        total = sum(score.values())
        grade = "S" if total >= 85 else "A" if total >= 70 else "B" if total >= 50 else "C"
        
        results[strategy_name] = {"score": score, "total": total, "grade": grade}
    
    return generate_report(results)
```

---

*文档版本: v1.0 | 创建日期: 2026-08-01 | 关联: [[portfolio-quantum-king-plan]]*