---
name: risk_check
description: 风险检查 — 检查当前系统风险状态，包括持仓风险、引擎状态、桥接连接。Use when user asks to "风险检查", "系统风险", "risk check", "系统健康", "引擎状态", "账户安全", "风控检查", "系统有没有问题", "检查连接", "保证金", "账户健康", "今日亏损", or when the user wants a comprehensive system health and risk assessment covering engine status, bridge connection, position risk, account health, and strategy status.
---

# 风险检查 Skill

全面检查系统风险，包括引擎状态、桥接连接、持仓风险、账户健康、策略状态和新闻风险。

## 触发条件

当满足以下任一条件时触发本 Skill：

1. 用户明确请求风险检查、系统健康检查、风控检查
2. 用户询问引擎状态、桥接连接、账户安全
3. 用户询问"系统有没有问题"、"今日亏损多少"、"保证金够不够"
4. 用户在进行交易操作前希望确认系统状态
5. 定期巡检场景（如 patrol_daemon 触发）

**不触发的场景**：用户仅询问市场方向（应触发 `market_analysis`）、用户仅询问单笔持仓健康（应触发 `position_diagnosis`）、用户仅查看引擎是否运行（直接读取 `/api/engine/status` 即可）。

## 执行流程

### Step 1: 引擎状态检查

通过 Dashboard API 或直接检查引擎状态：

1. 调用 `engine_runner.get_status()` 获取引擎运行状态
2. 确认引擎状态为 `running`（非 `uninitialized` / `stopped`）
3. 检查引擎运行时间（`uptime_seconds`）
4. 检查纸面引擎子进程状态（`paper_engine.status`）
5. 记录引擎异常状态

**判定标准**：
- 引擎 `running` → 正常
- 引擎 `stopped` / `uninitialized` → **RED**
- 纸面引擎异常 → **YELLOW**

### Step 2: 桥接连接检查

通过 `core.bridge` 检查 MT4 连接状态：

1. 调用 `bridge.get_tick_price("XAUUSD")` 验证连接活跃
2. 确认返回有效的 bid/ask 价格（非零、非 None）
3. 检查 bid-ask spread 是否合理（< $1.0 为正常）
4. 若连接失败，尝试 `bridge.connect()` 重连

**判定标准**：
- 有效价格 + 合理点差 → 正常
- 连接失败或价格异常 → **RED**
- 点差偏大 → **YELLOW**

### Step 3: 持仓风险评估

通过 `bridge.get_positions()` 获取持仓并评估：

1. 计算总浮动盈亏（所有持仓 profit 之和）
2. 检查每个持仓的止损距离（`abs(current - stop_loss)`）
3. 识别接近止损的仓位（距离 < 1× ATR）
4. 检查持仓数量是否接近上限（参考 `runtime_config.PAPER_DEFAULT_MAX_POSITIONS`）

**判定标准**：
- 浮亏 > 净值 5% → **YELLOW**
- 浮亏 > 净值 10% → **RED**
- 有仓位接近止损 → **YELLOW**

### Step 4: 账户健康检查

通过 `bridge.get_account_info()` 获取账户信息：

1. 计算余额/净值比率：`balance / equity`
2. 计算保证金水平：`equity / margin × 100`（margin level）
3. 检查可用保证金：`free_margin`
4. 检查今日回撤百分比

**判定标准**：
- Margin level > 300% → 正常
- Margin level 200-300% → **YELLOW**
- Margin level < 200% → **RED**
- 余额/净值比 > 1.1 → **YELLOW**

### Step 5: 策略状态检查

通过 Dashboard API 检查策略运行状态：

1. 列出当前活跃策略及其 magic number
2. 检查每个策略的风控状态（`StrategyRiskState`）：
   - `realized_loss_blocked`: 已实现亏损阻断
   - `floating_loss_blocked`: 浮动亏损阻断
   - `consecutive_loss_blocked`: 连续亏损阻断
   - `rapid_exit_blocked`: 快速出场阻断
3. 检查全局亏损阻断状态（`_global_loss_blocked`）
4. 确认活跃策略是否正常产出信号

### Step 6: 新闻风险评估

1. 检查近期重大经济数据发布（非农、CPI、利率决议）
2. 评估新闻方向对当前持仓的潜在影响
3. 标注未来 4 小时内的高影响事件

## 输出契约

风险检查报告必须包含以下结构化段落：

```
## 系统风险检查报告

**时间**: YYYY-MM-DD HH:MM UTC
**综合风险评级**: 🟢 低风险 / 🟡 中风险 / 🔴 高风险

### 系统状态
| 组件 | 状态 | 详情 |
|------|------|------|
| 引擎 | ✅/⚠️/❌ | [running/stopped/异常描述] |
| 桥接 | ✅/⚠️/❌ | [connected/disconnected/点差] |
| 纸面引擎 | ✅/⚠️/❌ | [状态] |

### 账户健康
- **余额**: $XXXX.XX
- **净值**: $XXXX.XX
- **保证金水平**: XXX%
- **可用保证金**: $XXXX.XX
- **今日回撤**: X.X% / 上限 XX%

### 持仓风险
- **活跃持仓**: X 笔
- **总浮动盈亏**: $XX.XX
- **接近止损**: X 笔 — [Ticket 列表]

### 策略状态
| 策略 | Magic | 浮动盈亏 | 已实现盈亏 | 连续亏损 | 阻断状态 |
|------|-------|---------|-----------|---------|---------|
| ...  | ...   | $XX.XX  | $XX.XX    | X       | 无/原因  |

### 风险点
1. [具体风险描述 + 建议操作]
2. [具体风险描述 + 建议操作]

### 新闻风险
- [近期高影响事件 + 预计影响时间]
```

## 验证步骤

完成检查后，逐项验证：

1. **完整性**：6 个检查步骤均已执行，无跳过
2. **数据新鲜度**：所有数据来自实时 API 调用，非缓存值
3. **评级一致**：综合风险评级与各组件中最严重的状态一致
4. **持仓覆盖**：所有活跃持仓均已评估风险
5. **策略覆盖**：所有运行中的策略均已检查风控状态
6. **可操作性**：每个风险点附带具体建议操作
7. **格式合规**：输出符合上述输出契约的 Markdown 结构
