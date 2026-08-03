# 策略三级管理体系 + 自动轮换方案

> 设计版本：v1.0 — 2026-08-02
> 状态：待实施（等待条件成熟）

---

## 一、为什么需要改造

| 当前问题 | 影响 |
|:---------|:-----|
| 27+ 策略文件全在 `strategies/` 一层，启用/禁用混在一起 | 目录拥挤，难以管理 |
| 策略中心 UI 只有名字列表，没有分类/分级标签 | 难以分辨核心策略 vs 实验策略 |
| 管理手段只有 on/off 开关 | 无法根据市场状态自动切换 |
| 盈利策略和亏损策略并存 | 干扰注意力，增加风险 |

---

## 二、三级体系定义

### CORE 🏆 — 核心策略

**特征：** 回测评分 A 级以上，连续 3 个月盈利，胜率 > 50%，回撤 < 5%

**规则：**
- 默认永远开启，是系统的主力
- 触发一票否决时自动降级到 MONITOR
  - 连续 5 笔亏损
  - 单日回撤 > 10%
  - 月亏损 > 初始资金 20%
- 观察 2 周恢复表现后回到 CORE

**当前候选（基于回测数据）：**
| 策略 | 3月PnL | 胜率 | 盈亏比 | 回撤 | 评分 |
|:----|:------:|:----:|:-----:|:----:|:---:|
| mfi_bb_m30_optimized | +$66.60 | 57.6% | 1.38 | 0.51% | 70 |
| rsi_grading_m30_upgraded | +$117.79 | 54.5% | 1.55 | 1.57% | 70 |
| m30_bb_deepreturn | +$213.95 | 54.6% | 1.32 | 1.25% | — |

---

### ROTATION 🔄 — 轮换策略

**特征：** 回测盈利但不够稳定，或只在特定市场状态下有效

**规则：**
- 不同时运行，根据市场状态选最优的 1-2 个激活
- 每小时检查一次市场状态
- 从该分类的候选池中选 Captain（过去 24h 表现最好的）
- 激活 Captain，禁用同分类的其他策略
- 记录轮换日志

**当前候选：**
| 策略 | 3月PnL | 适用市场 |
|:----|:------:|:---------|
| mfi_bb_m30 | +$198.33 | 震荡 |
| m30_bb_deepreturn_optimized | +$92.80 | 震荡 |
| momentum_pulse_pro | +$63.83 | 趋势 |
| rsi_grading_m30 | +$72.37 | 震荡 |
| m30_vol_return | — | 高波动 |
| h1_breakout | — | 低波动/突破 |

---

### MONITOR 👁️ — 观察策略

**特征：** 新移植策略、回测表现一般、刚从 CORE 降级下来的

**规则：**
- 永远不自动交易
- 每天一次自动回测（用最近 7 天数据）
- 连续 7 天回测盈利 → 升到 ROTATION 候选池
- 连续 30 天亏损 → 自动移入 ARCHIVE

**当前候选：** sanqing 系列、stoch 系列、移植策略等

---

### ARCHIVE 🗄️ — 归档

**特征：** 回测严重亏损、逻辑已过时

**规则：**
- 系统不加载，不扫描
- 保留代码用于参考

**当前候选：** gold_auto_research、viprasol_sniper、entry_score_pro 等

---

## 三、市场状态分类器

### 检测指标

| 市场状态 | 触发条件 | 数据来源 |
|:---------|:---------|:---------|
| **强趋势** | ADX > 30，BB 带宽 > 均值 × 1.5 | H1 DataFactory |
| **震荡** | ADX < 20，BB 带宽 < 均值 | H1 DataFactory |
| **高波动** | ATR > 20 日均值 × 1.3 | H1 DataFactory |
| **低波动** | ATR < 20 日均值 × 0.7 | H1 DataFactory |

### 轮换逻辑（伪代码）

```
每小时执行:
  1. 读取 H1 指标 (ADX, BB_width, ATR)
  2. 判断当前市场状态: 趋势/震荡/高波动/低波动
  3. 从 ROTATION 池中选出匹配该状态的策略列表
  4. 从列表中选出 Captain:
     a. 优先选有 CORE 评级的
     b. 其次选过去 24h 表现最好的
     c. 平局选回撤最小的
  5. 激活 Captain，禁用同分类其他策略
  6. 记录轮换日志到数据库
```

---

## 四、目录结构改造

```
strategies/
├── __init__.py
├── base.py                    # 基类（不变）
├── scanner.py                 # 改造：优先读 registry.json
├── registry.json              # 新增：策略注册表
├── market_regime.py           # 新增：市场状态分类器
│
├── core/                      # CORE 策略
│   ├── mfi_bb_m30_optimized_20260719.py
│   ├── rsi_grading_m30_upgraded_20260711.py
│   └── m30_bb_deepreturn_20260630.py
│
├── rotation/                  # ROTATION 策略
│   ├── mfi_bb_m30_20260630.py
│   ├── m30_bb_deepreturn_optimized_20260719.py
│   ├── momentum_pulse_pro_20260630.py
│   ├── rsi_grading_m30_20260630.py
│   ├── m30_vol_return_20260801.py
│   └── h1_breakout_20260801.py
│
├── monitor/                   # MONITOR 策略
│   ├── sanqing_h1_20260630.py
│   ├── sanqing_h1_original.py
│   ├── sanqing_h1_upgraded_20260719.py
│   ├── stoch_trend_h1_20260630.py
│   ├── stoch_trend_h1_optimized_20260711.py
│   ├── stoch_trend_h1_upgraded_20260719.py
│   ├── sanqing_original_20260802.py
│   └── timeprofit_ea_20260802.py
│
├── archive/                   # ARCHIVE 策略
│   ├── gold_auto_research_20260630.py
│   ├── viprasol_sniper_20260630.py
│   ├── entry_score_pro_20260630.py
│   ├── multi_confluence_quant_20260630.py
│   ├── mfi_bb_m30_upgraded_20260711.py
│   ├── M30_rsi_bb_20260630.py
│   ├── bakome_backup_20260711.py
│   ├── bakome_backup_optimized_20260719.py
│   └── xaubot_backup_20260630.py
│
└── backup/                    # 旧备份（不变）
```

---

## 五、registry.json 格式

```json
{
  "version": "2.2.0",
  "updated_at": "2026-08-02T00:00:00+08:00",
  "strategies": [
    {
      "name": "mfi_bb_m30_optimized",
      "file": "core/mfi_bb_m30_optimized_20260719.py",
      "class": "MfiBbM30Optimized",
      "magic": 660101,
      "timeframe": "M30",
      "tier": "CORE",
      "category": "REVERSAL",
      "grade": "A",
      "score": 70,
      "enabled": true,
      "max_positions": 5,
      "notes": "Captain候选，3月回测+$66.60，胜率57.6%，回撤0.51%"
    }
  ]
}
```

---

## 六、实施步骤

### Phase 1：基础改造（1-2 天）

1. 创建 `registry.json`，填入当前 27 个策略的完整元数据
2. 创建 `strategies/core/`、`rotation/`、`monitor/`、`archive/` 目录
3. 按分级移动策略文件到对应目录
4. 修改 `scanner.py`：优先读 `registry.json`，按 index 加载策略
5. 修改 `strategies.py` API 路由：返回 tier 字段
6. 更新前端策略中心 UI：显示分级标签（CORE/ROTATION/MONITOR）
7. 更新 CLAUDE.md 和策略文档标准

### Phase 2：市场状态分类器（2-3 天）

1. 创建 `strategies/market_regime.py`：
   - `get_regime() → str`：返回当前市场状态
   - `get_regime_history() → list`：返回历史状态记录
   - 每小时一次，读取 H1 指标计算
2. 单元测试：验证状态切换逻辑

### Phase 3：Captain 轮换机制（2-3 天）

1. 修改引擎 `engine_standalone/main.py`：
   - 添加 `_rotation_cycle()` 方法，每小时执行
   - 调用 `market_regime.get_regime()` 获取状态
   - 从 ROTATION 池中选 Captain
   - 激活/禁用策略（通过 `_config_service`）
   - 记录轮换日志
2. 添加轮换日志表到数据库
3. 前端添加轮换历史面板

### Phase 4：自动升降级（1-2 天）

1. 实现 MONITOR 策略的每日自动回测
2. 实现 CORE 一票否决自动降级
3. 实现满足条件的自动升级

---

## 七、需要解决的问题

| 问题 | 说明 |
|:----|:------|
| **引擎热加载** | 策略切换时是否需要重启引擎？目前配置是启动时读取一次 |
| **Captain 评估周期** | 用回测评分还是实时表现？实时表现需要至少 24h 数据 |
| **市场状态切换频率** | 每小时一次是否太频繁？太频繁会导致策略频繁开关 |
| **ROTATION 空窗期** | 如果当前市场状态没有匹配策略，是否允许 CORE 单独运行？ |
| **日志记录** | 轮换记录需要新的数据库表，字段设计？ |

---

## 八、回滚方案

如果三级体系效果不理想，可以快速回滚：
1. 恢复 `scanner.py` 到扫描整个 `strategies/` 目录版本
2. 将所有策略移回 `strategies/` 根目录
3. 删除 `registry.json`
4. 还原 `runtime_config.json` 到原始状态