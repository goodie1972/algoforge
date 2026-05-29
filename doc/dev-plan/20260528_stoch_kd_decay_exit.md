# 2026-05-28 改动: Stoch K-D 衰减出场 + Max Positions 调整

## 背景
- 原策略止盈按中轨（SMA）固定价格出场，价格到中轨但 Stoch K>D 时会卖飞
- 需要将最大持仓数从 3 提高到 5

## 改动 1: Max Positions 3 → 5
**文件**: `config/settings.py`
- `MAX_POSITIONS = 3` → `MAX_POSITIONS = 5`

## 改动 2: Stoch K-D 衰减出场（已实现）
### 逻辑
BUY 持仓追踪 `K-D` 差值（金叉强度），从峰值衰减到阈值以下时平仓：

| 中轨方向 | 比率 | 含义 |
|---------|------|------|
| 上升 | 0.5 | 衰减 50% 才走（趋势支持，持有更久） |
| 下降/走平 | 0.618 | 衰减 38.2% 就走（趋势不利，更敏感） |

SELL 持仓反过来，追踪 `D-K` 差值：
| 中轨方向 | 比率 |
|---------|------|
| 下降 | 0.5 |
| 上升/走平 | 0.618 |

中轨方向: 当前 SMA 与前一根 SMA 比较，> 0.1 为 rising，< -0.1 为 falling

### 涉及文件
- `strategies/stoch_bollinger.py` — 新增 `STOCH_EXIT_RATIO_RISING`/`_WEAK` 常量、`_get_sma_direction()`、`check_exit()`；`get_dynamic_sl_tp()` TP 改为极远值（旧中轨 TP 注释保留）
- `main.py` — `_tick()` 在信号生成前增加 K-D 衰减出场检查；引擎新增 `_peak_kd` 字典

### Bug Fix: check_exit 峰值未保存
- 原因: `peak_kd_dict.get(ticket, curr_diff)` 用 curr_diff 当默认值，导致 `curr_diff > prev_peak` 永远不成立，峰值从未写入字典
- 修复: 改为先用 `ticket not in peak_kd_dict` 检查，首次遇到时初始化并跳过判断

### 改动 3: 同方向开仓间隔控制
- 同一方向两次信号之间至少间隔 30 分钟（`_signal_interval = 1800`）
- 防止在趋势不明朗时同一 K 线连续开满

### 注意事项
- SL 保持 0.35 带宽不变，通过 MT4 执行
- TP 改为极远值（带宽 × 100），由 Python 端 K-D 衰减逻辑控制出场
- peak(K-D) 按 ticket 追踪，引擎维护 `_peak_kd` 字典
