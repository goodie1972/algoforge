# XAUUSD 量化交易系统 v2.0.0 — CLAUDE.md

## 三轨架构

- **轨1: DataFactory** — `services/data_factory.py` 独立线程，双桥接(exec+data)，增量拉取K线，TA-Lib统一计算指标
- **轨2: 策略员** — 主引擎循环，`get_indicator(key)` 读缓存指标，评分达标出门票（候选信号）
- **轨3: 运动员** — `engine_standalone/athlete.py` tick验证层，调用 `_verify_entry` 实时重算入场条件，10秒过期作废

## 通用指标缓存 (DataFactory TA-Lib)

| key | 说明 | key | 说明 |
|:----|:----|:----|:----|
| `rsi`/`rsi_5`/`rsi_10` | RSI(14/5/10) | `ema_9`/`ema_21` | EMA(9/21) |
| `mfi` | MFI(14) | `sma_14`/`sma_20`/`sma_50` | SMA |
| `bb{upper,mid,lower}` | BBANDS(20,2,2) | `atr`/`atr_20` | ATR(14/20) |
| `adx`/`pdi`/`ndi` | ADX/DI(14) | `trend` | close vs SMA(14) |
| `macd{macd,signal}` | MACD(12,26,9) | `stoch_14_3_3`/`stoch_21_5_3` | Stoch |
| `volume_sma_20` | VolSMA(20) | | |

## 时区规则 (CRITICAL)

- **用户期望的本地时间：UTC+8**
- 系统服务器时区：UTC+8（与本地一致）
- MT4 服务器时区：UTC+3（夏令时）

**绝对规则：** 任何时间显示，禁止裸用 `datetime.fromtimestamp(ts)`。必须使用 `config.settings.LOCAL_TZ`（UTC+8）的 timezone-aware 调用：
```python
# 正确
from config.settings import LOCAL_TZ
datetime.fromtimestamp(ts, tz=LOCAL_TZ)

# 或使用工具函数
from config.settings import dt_local
dt_local(ts)
```

**数据存储说明：**
- `ohlcv` 表的 `timestamp` 列：MT4 服务器时间（UTC+3），存储为 Unix 整数。读取时需用上述规则转换显示。
- `trades` 表的 `open_time / close_time`：已由引擎 `_mt4_to_local()` 转为 UTC+8（整型存储），与用户期望的 UTC+8 一致。
- `signals.timestamp` 及其他 `created_at / updated_at`：Python `datetime.now()` 设置，系统时区 UTC+8。

## 策略注册流程

1. 创建策略文件到 `strategies/` 目录
2. 在 `dashboard/backend/strategy_registry.py` 注册（策略中心可见的前提）
3. 在 `engine_standalone/main.py` 的 `STRATEGY_MAP` 注册（引擎加载的前提）
4. 在 `dashboard/runtime_config.json` 的 `strategy_pool` 添加（enabled=false 默认禁用）
5. 可选：在 `config/settings.py` 的 `STRATEGY_POOL` 添加（RuntimeConfig 的回退）
6. 用户在策略中心 UI 手动启用后，重启引擎生效

## 其他规则

- 引擎操作：发现引擎停止后自动重启（参照 memory：feedback_auto_restart_engine.md）
- 提交代码前：双轮测试（编译验证 + Playwright 实际页面测试）
- 代码修改只改必要行，不添加无意义注释
