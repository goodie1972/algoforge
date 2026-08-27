"""
运行时配置单例 - 从 settings.py 读取默认值，runtime_config.json 覆盖
Dashboard 和 Engine 共享同一实例，实现配置热更新
"""

import json
import os
import threading
from typing import Any

import config.settings as settings

# runtime_config.json 位于项目根的 dashboard/ 下
_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CORE_DIR)
CONFIG_FILE = os.path.join(_PROJECT_ROOT, "dashboard", "runtime_config.json")

# ── 持仓上限统一兜底常量（供 core / engine_standalone / dashboard 共用） ──
# 纸面模式单策略默认持仓上限（原散落硬编码 10）
PAPER_DEFAULT_MAX_POSITIONS = 10
# 策略池单策略默认持仓上限（原散落硬编码 1）
STRATEGY_DEFAULT_MAX_POSITIONS = 1

_ENGINE_KEYS = {
    "lot_size", "stop_loss_pips", "take_profit_pips",
    "max_positions", "per_strategy_max_positions", "max_daily_loss_pct",
    "floating_loss_warn_pct", "floating_loss_block_pct",
    "per_strategy_realized_loss_pct", "per_strategy_loss_block_hours",
    "max_rapid_exits", "rapid_exit_window_seconds", "rapid_exit_cooldown_seconds",
    "safety_lock_timeout_minutes",
    "per_strategy_realized_loss_amount", "max_consecutive_losses", "consecutive_loss_cooldown_hours",
    "profit_exit_cooldown_hours",
    "news_filter_enabled", "news_before_minutes", "news_after_minutes",
    "news_impact_filter", "news_currency_filter",
    "news_bias_enabled", "news_bias_report_hours",
    "block_long_when_bias_bearish", "block_short_when_bias_bullish",
    "news_bias_block_refresh_seconds",
}

_STRATEGY_KEYS = {
    "bb_period", "bb_std", "rsi_period", "rsi_oversold", "rsi_overbought",
    "stoch_k", "atr_period",
}



class RuntimeConfig:
    """运行时配置单例 - 线程安全"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data_lock = threading.Lock()
        self._overrides: dict[str, Any] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载覆盖值"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._overrides = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._overrides = {}

    def _save(self):
        """持久化到 JSON 文件"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._overrides, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[Config] Save config failed: {e}")

    def _get_default(self, key: str) -> Any:
        """从 settings.py 读取默认值"""
        key_map = {
            "lot_size": "LOT_SIZE",
            "stop_loss_pips": "STOP_LOSS_PIPS",
            "take_profit_pips": "TAKE_PROFIT_PIPS",
            "max_positions": "MAX_POSITIONS",
            "per_strategy_max_positions": "PER_STRATEGY_MAX_POSITIONS",
            "max_daily_loss_pct": "MAX_DAILY_LOSS_PCT",
            "slippage": "SLIPPAGE",
            "timeframe": "TIMEFRAME",
            "magic_number": "MAGIC_NUMBER",
            "bb_period": "BB_PERIOD",
            "bb_std": "BB_STD",
            "rsi_period": "RSI_PERIOD",
            "rsi_oversold": "RSI_OVERSOLD",
            "rsi_overbought": "RSI_OVERBOUGHT",
            "stoch_k": "STOCH_K",
            "atr_period": "ATR_PERIOD",
            "news_filter_enabled": "NEWS_FILTER_ENABLED",
            "news_before_minutes": "NEWS_BEFORE_MINUTES",
            "news_after_minutes": "NEWS_AFTER_MINUTES",
            "news_impact_filter": "NEWS_IMPACT_FILTER",
            "news_currency_filter": "NEWS_CURRENCY_FILTER",
            "news_bias_enabled": "NEWS_BIAS_ENABLED",
            "news_bias_report_hours": "NEWS_BIAS_REPORT_HOURS",
            "block_long_when_bias_bearish": "BLOCK_LONG_WHEN_BIAS_BEARISH",
            "block_short_when_bias_bullish": "BLOCK_SHORT_WHEN_BIAS_BULLISH",
            "news_bias_block_refresh_seconds": "NEWS_BIAS_BLOCK_REFRESH_SECONDS",
            "floating_loss_warn_pct": "FLOATING_LOSS_WARN_PCT",
            "floating_loss_block_pct": "FLOATING_LOSS_BLOCK_PCT",
            "per_strategy_realized_loss_pct": "PER_STRATEGY_REALIZED_LOSS_PCT",
            "per_strategy_loss_block_hours": "PER_STRATEGY_LOSS_BLOCK_HOURS",
            "max_rapid_exits": "MAX_RAPID_EXITS",
            "rapid_exit_window_seconds": "RAPID_EXIT_WINDOW_SECONDS",
            "rapid_exit_cooldown_seconds": "RAPID_EXIT_COOLDOWN_SECONDS",
            "safety_lock_timeout_minutes": "SAFETY_LOCK_TIMEOUT_MINUTES",
            "per_strategy_realized_loss_amount": "PER_STRATEGY_REALIZED_LOSS_AMOUNT",
            "max_consecutive_losses": "MAX_CONSECUTIVE_LOSSES",
            "consecutive_loss_cooldown_hours": "CONSECUTIVE_LOSS_COOLDOWN_HOURS",
            "profit_exit_cooldown_hours": "PROFIT_EXIT_COOLDOWN_HOURS",
            "paper_trading_enabled": "PAPER_TRADING_ENABLED",
        }
        attr = key_map.get(key)
        if attr and hasattr(settings, attr):
            return getattr(settings, attr)
        return None

    def get(self, key: str) -> Any:
        """获取配置值（覆盖优先，否则返回默认值）"""
        with self._data_lock:
            if key in self._overrides:
                return self._overrides[key]
        return self._get_default(key)

    def get_all(self) -> dict[str, Any]:
        """获取完整配置字典"""
        result = {}
        all_keys = _ENGINE_KEYS | _STRATEGY_KEYS | {"slippage", "timeframe", "magic_number"}
        for key in all_keys:
            result[key] = self.get(key)
        result["strategy_pool"] = self.get_strategy_pool()
        result["coordinator"] = self.get_coordinator_config()
        result["paper_trading"] = self.get_paper_config()
        result["symbol"] = getattr(settings, 'SYMBOL', 'XAUUSD')
        return result

    def get_strategy_pool(self) -> dict[str, Any]:
        """获取策略池（覆盖优先）"""
        with self._data_lock:
            if "strategy_pool" in self._overrides:
                return dict(self._overrides["strategy_pool"])
        return dict(getattr(settings, 'STRATEGY_POOL', {}))

    def set_strategy_pool(self, pool: dict[str, Any]) -> dict[str, Any]:
        """设置策略池覆盖"""
        with self._data_lock:
            self._overrides["strategy_pool"] = dict(pool)
            self._save()
        return self.get_strategy_pool()

    def get_coordinator_config(self) -> dict:
        """获取协调器配置（覆盖优先）"""
        with self._data_lock:
            if "coordinator" in self._overrides:
                return dict(self._overrides["coordinator"])
        return dict(getattr(settings, 'COORDINATOR_CONFIG', {"enabled": False}))

    def set_coordinator_config(self, cfg: dict) -> dict:
        """设置协调器配置（合并方式，仅更新传入的字段）"""
        with self._data_lock:
            existing = self._overrides.get("coordinator", {})
            existing.update(cfg)
            self._overrides["coordinator"] = existing
            self._save()
        return self.get_coordinator_config()

    def get_paper_config(self) -> dict:
        """获取纸面交易配置（覆盖优先）"""
        with self._data_lock:
            global_lot = self._overrides.get("lot_size")
            paper_override = self._overrides.get("paper_trading")
        if global_lot is None:
            global_lot = self._get_default("lot_size")
        defaults = {
            "enabled": False,
            "max_positions": PAPER_DEFAULT_MAX_POSITIONS,
            "ignore_gates": True,
            "initial_balance": 0,
            "lot_size": global_lot,              # 纸面独立手数，缺失时沿用全局 lot_size
            "total_max_positions": 0,            # 纸面全局总持仓上限，0 = 不限制
        }
        if paper_override is not None:
            merged = dict(defaults)
            merged.update(paper_override)
            return merged
        # 从 settings.py 读取 paper_trading_enabled 作为 enabled 兜底
        enabled = self._get_default("paper_trading_enabled")
        if enabled is not None:
            defaults["enabled"] = bool(enabled)
        return dict(defaults)

    def set_paper_config(self, cfg: dict) -> dict:
        """设置纸面交易配置（合并方式，仅更新传入的字段）"""
        with self._data_lock:
            existing = self._overrides.get("paper_trading", {})
            existing.update(cfg)
            self._overrides["paper_trading"] = existing
            self._save()
        return self.get_paper_config()

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """批量更新配置项"""
        updated = {}
        with self._data_lock:
            for key, value in updates.items():
                self._overrides[key] = value
                updated[key] = value
            self._save()
        return updated

    def reload(self):
        """重新从 JSON 文件加载覆盖值（引擎 tick 中热重载用）"""
        with self._data_lock:
            self._load()

    def get_active(self) -> dict:
        """返回引擎当前实际使用的配置（合并 defaults + overrides），供 /api/config/active 使用"""
        result = {}
        for key in _ENGINE_KEYS:
            result[key] = self.get(key)
        result['strategy_pool'] = self.get('strategy_pool') or {}
        result['coordinator'] = self.get_coordinator_config()
        result['paper_trading'] = self.get_paper_config()
        return result

    def reset(self, key: str | None = None):
        """重置指定键或全部覆盖"""
        with self._data_lock:
            if key:
                self._overrides.pop(key, None)
            else:
                self._overrides.clear()
            self._save()
