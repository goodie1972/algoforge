# 策略版本管理规范

## Magic Number 编号规则

6位数字：`PP` + `NN` + `VV`

| 位段 | 位数 | 含义 |
|------|------|------|
| PP   | 2    | 策略来源：`66` = 自研，`88` = 借鉴 |
| NN   | 2    | 策略上线序号（见完整对照表），跳过02/04/12/14等 |
| VV   | 2    | 版本号，从01开始按修改次数递增 |

### 完整对照表

| 策略名 | 类型 | PP | NN | 新 Magic |
|--------|------|----|----|----------|
| M30_rsi_bb | 自研 | 66 | 07 | 660701~660704 |
| H1_v6_hybrid | 自研 | 66 | 06 | 660601~660604 |
| sanqing_h1 | 借鉴 | 88 | 01 | 880101~880104 |
| gold_auto_research | 借鉴 | 88 | 03 | 880301~880305 |

### 版本历史

#### M30_rsi_bb (6607)

| 版本 | Magic | 日期 | 说明 |
|------|-------|------|------|
| v1 | 660701 | 2026-06-08 | 初始上线：5因子评分≥3，ATR跟踪止损 trail=4.0 hard=3.0 |
| v2 | 660702 | 2026-06-08 | 修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪 |
| v3 | 660703 | 2026-06-09 | 双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，indicator_values |
| v4 | 660704 | 2026-06-11 | RSI分层过滤：RSI<20禁空，RSI20-30空头扣1分；tight_exit_mode 新闻风控 |

#### H1_v6_hybrid (6606)

| 版本 | Magic | 日期 | 说明 |
|------|-------|------|------|
| v1 | 660601 | 2026-06-08 | 初始上线：8因子评分≥3，ATR跟踪止损 trail=4.0 hard=3.0 |
| v2 | 660602 | 2026-06-08 | 修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪 |
| v3 | 660603 | 2026-06-09 | 双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，indicator_values |
| v4 | 660604 | 2026-06-11 | tight_exit_mode 新闻风控；RSI分层过滤 |

#### sanqing_h1 (8801)

| 版本 | Magic | 日期 | 说明 |
|------|-------|------|------|
| v1 | 880101 | 2026-06-08 | 初始上线：6因子评分≥5，ATR跟踪止损 trail=4.0 hard=2.5 |
| v2 | 880102 | 2026-06-08 | 修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪 |
| v3 | 880103 | 2026-06-09 | 双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，indicator_values |
| v4 | 880104 | 2026-06-11 | tight_exit_mode 新闻风控 |

#### gold_auto_research (8803)

| 版本 | Magic | 日期 | 说明 |
|------|-------|------|------|
| v1 | 880301 | 2026-06-08 | 初始上线：4因子共识投票，ATR跟踪止损 trail=3.5 hard=2.0 |
| v2 | 880302 | 2026-06-08 | 修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪 |
| v3 | 880303 | 2026-06-09 | 双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，indicator_values |
| v4 | 880304 | 2026-06-11 | tight_exit_mode 新闻风控 |
| v5 | 880305 | 2026-06-11 | SAFE-DN改为RSI≤35独立封空，防止接近超卖区开空 |

---

## 修改策略的标准流程

1. **备份当前文件** → `strategies/backup/YYYYMMDD_策略文件名_版本号.py`
2. **修改策略逻辑**
3. **更新版本字段**：
   - 类外变量：`STRATEGY_VERSION`（如 `"v5"`）、`STRATEGY_MAGIC`（新6位magic）
   - `STRATEGY_CHANGELOG` 追加一条新记录
4. **更新** `config/settings.py`：`STRATEGY_POOL` 中对应策略的 `magic` 改为新值
5. **重启引擎**，此时 `engine_runner.py` 自动将 changelog 写入 `strategy_versions` 表

---

## STRATEGY_CHANGELOG 格式规范

```python
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660701, "date": "2026-06-08", "desc": "初始上线：简要说明"},
    {"version": "v2", "magic": 660702, "date": "2026-06-08", "desc": "修改内容简述"},
]
```

- `magic` 必须是当前版本对应的实际6位 magic number
- `date` 格式 `YYYY-MM-DD`
- `desc` 用中文，简洁说明本次改动的核心变化

---

## backup/ 文件命名规范

```
strategies/backup/YYYYMMDD_<策略文件名>_<版本号>.py
```

例：`strategies/backup/20260611_gold_autoresearch_h1_v4.py`

- 日期为备份操作的实际日期（与代码日期一致）
- 策略文件名与 `strategies/` 下实际文件名一致
- 版本号为被备份版本的 `STRATEGY_VERSION`

---

## 兼容旧版 Magic

历史遗留的 777xxx 系列 magic（旧版 MT4 历史成交记录）仍受支持：

| 旧 Magic | 策略 |
|----------|------|
| 777001 | M30_rsi_bb |
| 777002 | H1_v6_hybrid |
| 777003 | gold_auto_research |

新旧 magic 在 `/api/trades/stats` 的 `by_strategy` 分组中自动合并到同一策略族。
