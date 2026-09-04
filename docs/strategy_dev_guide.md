# 策略开发指南

> 主应用内置策略**快照**（clone 后开箱即用）。策略的**日常开发 / 版本管理 / 推送**在独立仓库 [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies) 进行。

## 策略存放位置

| 位置 | 内容 | 说明 |
|:----|:----|:----|
| `strategies/`（主应用） | 框架 + 策略快照 | 引擎运行时从这里 import，clone 后立即可用 |
| `algoforge-strategies/`（独立仓库） | 全部策略源码 + 文档 | 策略开发与版本管理的主阵地 |

同步方式：在独立仓库开发完成后，将新/改策略文件复制回主应用 `strategies/` 并启动引擎生效（或由部署流程同步）。

## 策略文件结构

一个策略文件（如 `20260821_m15_followave_v1.py`）：

```python
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661401
STRATEGY_LEGACY_MAGICS = []
STRATEGY_CHANGELOG = [{"version": "v1", "magic": 661401, "date": "2026-08-21", "desc": "..."}]

class MyStrategy(BaseStrategy):
    name = "my_strategy"                 # 策略名（settings.STRATEGY_POOL 的 key）
    default_timeframe = "M30"
    TIMEFRAME = "M30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # 参数
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30

    def generate_signal(self) -> Optional[tuple]:
        """入场信号。返回 (OrderType, score_long, score_short, long_factors, short_factors, indicator_values)"""
        close = self.candles[-1].close
        rsi = self.get_indicator("rsi")
        ...
        return (OrderType.BUY, 1, 0, ["MY-LONG"], [], {})

    def get_dynamic_sl_tp(self, direction, entry_price, atr_val, position_type="entry"):
        """SL/TP，返回 (stop_loss, take_profit)"""

    def check_ema20_exit(self, position, bid, ask) -> bool:
        """出场逻辑。返回 True = 平仓"""
```

## 指标来源（DataFactory）

全部指标从 DataFactory 缓存读取（`self.get_indicator(key)`），**不要自行用 candles 手算**：

```python
rsi = self.get_indicator("rsi")          # RSI 14
mfi = self.get_indicator("mfi")          # MFI 14
bb = self.get_indicator("bb")            # {"upper", "mid", "lower"}
adx = self.get_indicator("adx")          # ADX 14
pdi = self.get_indicator("pdi")          # +DI
ndi = self.get_indicator("ndi")          # -DI
stoch = self.get_indicator("stoch_5_3_3")# {"k", "d"}
bbi = self.get_indicator("bbi")          # BBI (SMA3/6/12/24 均值)
bb_mid_dir = self.get_indicator("bb_mid_direction")
atr = self.get_indicator("atr")
cci = self.get_indicator("cci")          # CCI(14) 商品通道指数（EA v2 起提供，典型价）
cci_dir = self.get_indicator("cci_direction")  # "up" / "down" / "flat"
# 蜡烛形态：没有 cdl_* 逐形态键，读方向与名称
cdl_dir = self.get_indicator("candle_pattern_dir")    # "long" / "short" / "none"
cdl_name = self.get_indicator("candle_pattern_name")  # "ENGULF" / "HAMMER" / ...
```

完整 46 指标表（EA 直供 24 + EA 派生 2 + TA‑Lib 20）见 `docs/data_factory.md`。

## 命名与 Magic 规范

见 `strategies/STRATEGY_VERSIONING.md`：
- Magic = `PPNNVV`：`66`=自研, `88`=借鉴；NN=策略序号；VV=版本
- 文件命名：`YYYYMMDD_name_vN.py`
- 每个版本在 `STRATEGY_CHANGELOG` 记录

## 注册策略

`config/settings.py` 的 `STRATEGY_POOL` 添加条目：

```python
"my_strategy": {
    "magic": 661401,
    "timeframe": "M30",
    "double_first": False,
    "max_positions": 1,
},
```

启动引擎即自动加载（`scanner.py` 自动发现，无需手动注册类）。

## 上线流程

1. 独立仓库开发 + 本地回测（`backtest/` 脚本）
2. 写策略文档（`docs/strategies/`）
3. 推送到 algoforge-strategies
4. 复制策略文件到主应用 `strategies/`
5. 引擎重启加载，纸面观察
6. 满足入选标准（回测 PnL 为正 / 文档完整 / 纸面通过）后正式启用

## 策略入选标准

- 3 个月以上回测 PnL 为正
- 文档完整（入场/出场逻辑、风控、回测结果）
- 纸面测试通过且不违反风控上限