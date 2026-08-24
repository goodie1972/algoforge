"""
工具注册表 — 注册/查找/调用工具
每个工具: {name, description, parameters(dict), handler(callable)}
"""
import logging
import inspect
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, handler: Callable,
                 parameters: Optional[dict] = None, category: str = "builtin") -> None:
        """注册工具"""
        if parameters is None:
            sig = inspect.signature(handler)
            params = {}
            for p_name, p_param in sig.parameters.items():
                if p_name == "self" or p_name == "kwargs":
                    continue
                param_type = "string"
                if p_param.annotation is not inspect.Parameter.empty:
                    if p_param.annotation is int:
                        param_type = "integer"
                    elif p_param.annotation is float:
                        param_type = "number"
                    elif p_param.annotation is bool:
                        param_type = "boolean"
                params[p_name] = {"type": param_type, "description": ""}
            parameters = {"type": "object", "properties": params}

        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
            "category": category,
        }
        logger.info(f"[ToolRegistry] registered: {name} ({category})")

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[dict]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> list[dict]:
        tools = self._tools.values()
        if category:
            tools = [t for t in tools if t["category"] == category]
        return [{"name": t["name"], "description": t["description"],
                 "parameters": t["parameters"]} for t in tools]

    def call(self, name: str, **kwargs) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return f"错误: 工具 '{name}' 不存在"
        try:
            return tool["handler"](**kwargs)
        except Exception as e:
            logger.error(f"[ToolRegistry] call {name} failed: {e}")
            return f"调用失败: {e}"

    def to_openai_tools(self, category: Optional[str] = None) -> list[dict]:
        """转为 OpenAI function calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            }
            for t in self._tools.values()
            if category is None or t["category"] == category
        ]


# 全局单例
_registry = ToolRegistry()

def get_registry() -> ToolRegistry:
    return _registry


def _get_engine():
    """安全获取 EngineRunner 单例"""
    try:
        from dashboard.backend.engine_runner import EngineRunner
        return EngineRunner.get_instance()
    except Exception:
        return None


def register_builtin_tools() -> None:
    """注册内置工具骨架（function calling 集成预备）

    注册以下核心工具：
    - get_positions: 获取当前持仓信息
    - get_indicators: 获取技术指标数据
    - get_account_info: 获取账户信息
    - get_trades_history: 获取最近成交历史
    - get_market_price: 获取实时价格

    TODO: 在 function calling 集成时接入启动流程，例如:
        from services.agent.tool_registry import register_builtin_tools
        register_builtin_tools()
    """
    registry = get_registry()

    # ── 工具 handler 定义 ──

    def get_positions(direction: str = "") -> list:
        """获取当前持仓信息

        Args:
            direction: 可选过滤方向，"BUY" 或 "SELL"，空字符串表示全部

        Returns:
            持仓列表，每项包含: ticket, direction, volume, entry_price,
            current_price, profit, stop_loss, take_profit, strategy
        """
        engine = _get_engine()
        if not engine:
            return {"error": "引擎未启动，无法获取持仓信息"}
        try:
            # _fresh_positions 是方法，需要用最新价格重算浮盈
            fresh_fn = getattr(engine, '_fresh_positions', None)
            if callable(fresh_fn):
                positions = fresh_fn()
            else:
                positions = getattr(engine, '_cached_positions', [])

            # 方向过滤
            if direction and positions:
                direction = direction.upper()
                positions = [p for p in positions
                            if direction in p.get('order_type', '').upper()]

            # 格式化输出
            result = []
            for p in positions:
                result.append({
                    "ticket": p.get("ticket"),
                    "direction": p.get("order_type", ""),
                    "volume": p.get("volume", 0),
                    "entry_price": p.get("open_price", 0),
                    "current_price": p.get("current_price", 0),
                    "profit": p.get("profit", 0),
                    "stop_loss": p.get("stop_loss", 0),
                    "take_profit": p.get("take_profit", 0),
                    "strategy": p.get("strategy", p.get("comment", "")),
                })
            return result if result else {"message": "当前无持仓"}
        except Exception as e:
            return {"error": f"获取持仓失败: {e}"}

    def get_indicators(timeframe: str = "H1") -> dict:
        """获取指定时间框架的技术指标数据

        Args:
            timeframe: K线周期，可选值: M1, M5, M15, M30, H1, H4, D1, W1，默认 H1

        Returns:
            指标字典，包含: rsi, macd, bb, atr, adx, ema_9, ema_21, trend 等
        """
        engine = _get_engine()
        timeframe = timeframe.upper()

        # 优先从 data_factory 缓存获取指标
        try:
            from services.data_factory import get_cache
            cache = get_cache(timeframe)
            if cache:
                # 提取关键指标
                result = {
                    "timeframe": timeframe,
                    "rsi": cache.get("rsi"),
                    "macd": {
                        "macd": cache.get("macd"),
                        "signal": cache.get("macd_signal"),
                        "histogram": cache.get("macd_hist"),
                    },
                    "bb": {
                        "upper": cache.get("bb_upper"),
                        "mid": cache.get("bb_mid"),
                        "lower": cache.get("bb_lower"),
                    },
                    "atr": cache.get("atr"),
                    "adx": cache.get("adx"),
                    "ema_9": cache.get("ema_9"),
                    "ema_21": cache.get("ema_21"),
                    "trend": cache.get("trend"),
                    "close": cache.get("close"),
                }
                # 移除 None 值
                return {k: v for k, v in result.items() if v is not None}
        except Exception:
            pass

        # 回退：从策略的缓存获取
        if engine and hasattr(engine, '_engine') and engine._engine:
            try:
                for strategy in engine._engine.strategies:
                    if getattr(strategy, 'timeframe', '') == timeframe:
                        cached = getattr(strategy, '_cached_indicators', {})
                        if cached:
                            return {"timeframe": timeframe, **cached}
            except Exception:
                pass

        return {"error": f"无法获取 {timeframe} 周期的指标数据（引擎可能未启动）"}

    def get_account_info() -> dict:
        """获取账户信息

        Returns:
            账户信息字典: login, balance, equity, margin, free_margin,
            currency, leverage, floating_pnl
        """
        engine = _get_engine()
        if not engine:
            return {"error": "引擎未启动，无法获取账户信息"}
        try:
            acct = getattr(engine, '_cached_account', None)
            if acct:
                # 计算浮盈
                positions = getattr(engine, '_cached_positions', [])
                floating_pnl = sum(p.get('profit', 0) for p in positions)
                return {
                    "login": acct.get("login"),
                    "balance": acct.get("balance", 0),
                    "equity": acct.get("equity", 0),
                    "margin": acct.get("margin", 0),
                    "free_margin": acct.get("free_margin", 0),
                    "currency": acct.get("currency", "USD"),
                    "leverage": acct.get("leverage"),
                    "floating_pnl": round(floating_pnl, 2),
                }
            return {"error": "账户数据尚未就绪，请稍后重试"}
        except Exception as e:
            return {"error": f"获取账户信息失败: {e}"}

    def get_trades_history(limit: int = 10) -> list:
        """获取最近成交历史

        Args:
            limit: 返回记录数量，默认 10，最大 100

        Returns:
            成交记录列表，每项包含: ticket, symbol, direction, volume,
            entry_price, exit_price, pnl, strategy, close_time
        """
        limit = max(1, min(int(limit), 100))
        try:
            from data.database import get_trades
            trades = get_trades(limit=limit)
            if trades:
                result = []
                for t in trades:
                    result.append({
                        "ticket": t.get("ticket"),
                        "symbol": t.get("symbol", "XAUUSD"),
                        "direction": t.get("order_type", ""),
                        "volume": t.get("volume", 0),
                        "entry_price": t.get("entry_price", 0),
                        "exit_price": t.get("exit_price", 0),
                        "pnl": t.get("pnl", 0),
                        "strategy": t.get("strategy", ""),
                        "close_time": t.get("close_time", ""),
                    })
                return result
            return {"message": "暂无成交记录"}
        except Exception as e:
            return {"error": f"获取成交历史失败: {e}"}

    def get_market_price() -> dict:
        """获取实时市场价格

        Returns:
            价格字典: bid, ask, spread, timestamp
        """
        engine = _get_engine()
        if not engine:
            return {"error": "引擎未启动，无法获取市场价格"}
        try:
            price = getattr(engine, '_cached_price', None)
            if price:
                bid = price.get("bid", 0)
                ask = price.get("ask", 0)
                return {
                    "bid": bid,
                    "ask": ask,
                    "spread": round(ask - bid, 2) if bid and ask else 0,
                    "timestamp": price.get("timestamp"),
                }
            return {"error": "价格数据尚未就绪，请稍后重试"}
        except Exception as e:
            return {"error": f"获取市场价格失败: {e}"}

    # ── 注册工具 ──

    # 手动定义参数 schema，提供更清晰的描述
    registry.register(
        name="get_positions",
        description="获取当前所有持仓信息，包括票号、方向、手数、入场价、当前价、浮盈、止损、止盈、策略名。可按方向(BUY/SELL)过滤。",
        handler=get_positions,
        parameters={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "过滤方向: 'BUY' 或 'SELL'，留空获取全部",
                    "enum": ["", "BUY", "SELL"]
                }
            },
            "required": []
        },
        category="trading"
    )

    registry.register(
        name="get_indicators",
        description="获取指定周期的技术指标数据，包括 RSI、MACD、布林带、ATR、ADX、EMA 等。用于技术分析判断趋势和入场时机。",
        handler=get_indicators,
        parameters={
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "description": "K线周期: M1/M5/M15/M30/H1/H4/D1/W1",
                    "enum": ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"],
                    "default": "H1"
                }
            },
            "required": []
        },
        category="market_data"
    )

    registry.register(
        name="get_account_info",
        description="获取交易账户信息，包括余额、净值、保证金、可用保证金、浮盈等。",
        handler=get_account_info,
        parameters={"type": "object", "properties": {}, "required": []},
        category="account"
    )

    registry.register(
        name="get_trades_history",
        description="获取最近的成交历史记录，包括入场价、出场价、盈亏、策略等信息。",
        handler=get_trades_history,
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回记录数量，默认10，最大100",
                    "default": 10
                }
            },
            "required": []
        },
        category="trading"
    )

    registry.register(
        name="get_market_price",
        description="获取 XAUUSD 实时市场价格，包括买入价(bid)、卖出价(ask)、点差(spread)。",
        handler=get_market_price,
        parameters={"type": "object", "properties": {}, "required": []},
        category="market_data"
    )

    logger.info("[ToolRegistry] 内置工具注册完成: get_positions, get_indicators, get_account_info, get_trades_history, get_market_price")
