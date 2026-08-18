"""
xaubot-ai — XGBoost ML 后备strategy
================================
- Walk-forward XGBoost 二分类模型
- Polars 特征工程 (80+ technical features)
- 置信度threshold 0.52 触发Signal
- ATR 动态trailing止损出场

注意:
  - 优先load models/xaubot_model.ubj（预训练模型）
  - 无预训练模型时首次loadauto从 SQLite 训练
  - 需要 xgboost + polars
data源: all指标从 DataFactory TA-Lib read
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Optional

from config.settings import LOCAL_TZ

import numpy as np

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# Optional dependencies
try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    logger.warning("[xaubot_backup] xgboost not installed, ML disabled")

try:
    import polars as pl
    HAS_POLARS = True
except ImportError:
    HAS_POLARS = False
    logger.warning("[xaubot_backup] polars not installed, ML disabled")


STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 777005
STRATEGY_LEGACY_MAGICS: list[int] = []


class _FeatureEngineer:
    """TA-Lib-based feature engineering (xaubot-ai compatible).

    所有基础指标用 TA-Lib 计算，不手动 ewm_mean/rolling。
    """

    def calculate_all(self, df: 'pl.DataFrame', include_ml: bool = True) -> 'pl.DataFrame':
        import numpy as np
        import talib

        close = df['close'].to_numpy().astype(float)
        high = df['high'].to_numpy().astype(float)
        low = df['low'].to_numpy().astype(float)
        volume = df['volume'].to_numpy().astype(float) if 'volume' in df.columns else None

        # RSI(14)
        rsi = talib.RSI(close, timeperiod=14)
        df = df.with_columns([pl.Series('rsi', rsi)])

        # ATR(14)
        atr = talib.ATR(high, low, close, timeperiod=14)
        df = df.with_columns([pl.Series('atr', atr)])

        # MACD(12,26,9)
        macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        df = df.with_columns([
            pl.Series('macd', macd),
            pl.Series('macd_signal', macd_signal),
            pl.Series('macd_histogram', macd_hist),
        ])

        # Bollinger(20,2)
        bb_upper, bb_mid, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        df = df.with_columns([
            pl.Series('bb_upper', bb_upper),
            pl.Series('bb_middle', bb_mid),
            pl.Series('bb_lower', bb_lower),
        ])
        bb_width = (bb_upper - bb_lower) / np.where(bb_mid == 0, np.nan, bb_mid)
        bb_pctb = (close - bb_lower) / np.where((bb_upper - bb_lower) == 0, np.nan, (bb_upper - bb_lower))
        df = df.with_columns([
            pl.Series('bb_width', bb_width),
            pl.Series('bb_percent_b', bb_pctb),
        ])

        # EMA(9/21) + crossover
        ema_fast = talib.EMA(close, timeperiod=9)
        ema_slow = talib.EMA(close, timeperiod=21)
        df = df.with_columns([
            pl.Series('ema_9', ema_fast),
            pl.Series('ema_21', ema_slow),
        ])
        ema_above = ema_fast > ema_slow
        ema_above_p = np.roll(ema_above, 1)
        ema_above_p[0] = False
        ema_cross_bull = (ema_above & ~ema_above_p).astype(np.int8)
        ema_cross_bear = (~ema_above & ema_above_p).astype(np.int8)
        df = df.with_columns([
            pl.Series('ema_cross_bull', ema_cross_bull),
            pl.Series('ema_cross_bear', ema_cross_bear),
        ])

        # Volume features
        if volume is not None:
            vol_sma = talib.SMA(volume, timeperiod=20)
            df = df.with_columns([pl.Series('volume_sma', vol_sma)])
            vol_ratio = volume / np.where(vol_sma == 0, np.nan, vol_sma)
            df = df.with_columns([pl.Series('volume_ratio', vol_ratio)])
            high_vol = (vol_ratio > 1.5).astype(np.int8)
            df = df.with_columns([pl.Series('high_volume', high_vol)])
            buy_vol = np.where(close > df['open'].to_numpy(), volume, 0.0)
            sell_vol = np.where(close < df['open'].to_numpy(), volume, 0.0)
            ofi = (buy_vol - sell_vol) / (buy_vol + sell_vol + 1e-9)
            df = df.with_columns([
                pl.Series('buy_volume', buy_vol),
                pl.Series('sell_volume', sell_vol),
                pl.Series('ofi_pseudo', ofi),
            ])

        if include_ml:
            df = self._ml_features(df)
        return df

    def _ml_features(self, df: 'pl.DataFrame'):
        import numpy as np
        close = df['close'].to_numpy().astype(float)
        high = df['high'].to_numpy().astype(float)
        low = df['low'].to_numpy().astype(float)

        ret1 = np.zeros_like(close)
        ret5 = np.zeros_like(close)
        ret20 = np.zeros_like(close)
        ret1[1:] = close[1:] / close[:-1] - 1
        ret5[5:] = close[5:] / close[:-5] - 1
        ret20[20:] = close[20:] / close[:-20] - 1
        df = df.with_columns([
            pl.Series('returns_1', ret1),
            pl.Series('returns_5', ret5),
            pl.Series('returns_20', ret20),
        ])

        pp = (close - low) / np.where((high - low) == 0, np.nan, (high - low))
        df = df.with_columns([pl.Series('price_position', pp)])

        import talib
        sma20 = talib.SMA(close, timeperiod=20)
        dist_sma20 = close / np.where(sma20 == 0, np.nan, sma20) - 1
        df = df.with_columns([pl.Series('dist_from_sma_20', dist_sma20)])

        close_lag1 = np.roll(close, 1); close_lag1[0] = np.nan
        close_lag2 = np.roll(close, 2); close_lag2[:2] = np.nan
        close_lag3 = np.roll(close, 3); close_lag3[:3] = np.nan
        df = df.with_columns([
            pl.Series('close_lag_1', close_lag1),
            pl.Series('close_lag_2', close_lag2),
            pl.Series('close_lag_3', close_lag3),
        ])

        hh = np.zeros_like(close, dtype=np.int8)
        ll = np.zeros_like(close, dtype=np.int8)
        hh[1:] = (high[1:] > high[:-1]).astype(np.int8)
        ll[1:] = (low[1:] < low[:-1]).astype(np.int8)
        df = df.with_columns([
            pl.Series('higher_high', hh),
            pl.Series('lower_low', ll),
        ])

        if 'time' in df.columns:
            df = df.with_columns([
                pl.col('time').dt.hour().alias('hour'),
                pl.col('time').dt.weekday().alias('weekday'),
            ])
        return df


class XAUBotBackupStrategy(BaseStrategy):
    """xaubot-ai — XGBoost ML 后备strategy (H1)"""

    name = "xaubot_backup"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    _model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
    _model_path = os.path.join(_model_dir, "xaubot_model.ubj")
    _meta_path = os.path.join(_model_dir, "xaubot_meta.json")

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Exit params
        self.p_trailing_atr = 3.0
        self.p_hard_atr = 2.0

        # ML model
        self.model = None
        self.feature_cols: list[str] = []
        self.fitted = False
        self.confidence_threshold = 0.52
        self._df: Optional['pl.DataFrame'] = None
        self._fe = _FeatureEngineer()

        # attemptloadsave 模型（不训练也能用）
        self._try_load_model()

    def _try_load_model(self):
        """从 models/ loadsave  XGBoost 模型"""
        if not HAS_XGB:
            return
        if not os.path.exists(self._model_path) or not os.path.exists(self._meta_path):
            logger.info(f"[{self.name}] save model not found, will train on first data load")
            return

        try:
            import xgboost as xgb
            self.model = xgb.Booster()
            self.model.load_model(self._model_path)

            with open(self._meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            self.feature_cols = meta.get("feature_cols", [])
            self.confidence_threshold = meta.get("confidence_threshold", 0.52)
            self.fitted = True

            logger.info(
                f"[{self.name}] load预训练模型: "
                f"test_acc={meta.get('test_accuracy', '?')} "
                f"特征={len(self.feature_cols)} "
                f"threshold={self.confidence_threshold}"
            )
        except Exception as e:
            logger.warning(f"[{self.name}] load model failed, will retrain: {e}")
            self.model = None
            self.fitted = False

    def refresh_data(self, count: int = 500):
        super().refresh_data(count)

        # 仅在无save模型时训练，加 5 mincooldown避免每 tick retry
        if not self.fitted and HAS_XGB and HAS_POLARS and len(self.candles) >= 300:
            now = datetime.now(LOCAL_TZ).timestamp()
            if now - getattr(self, "_last_train_attempt", 0) > 300:
                self._last_train_attempt = now
                self._load_and_train()

    def _load_and_train(self):
        """Load H1 data from SQLite, compute features, train XGBoost."""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE timeframe=? ORDER BY timestamp",
                (self.timeframe or 'H1',)
            ).fetchall()
            conn.close()
        except Exception as e:
            logger.warning(f"[{self.name}] SQLite load failed: {e}")
            return

        if not rows or len(rows) < 300:
            logger.warning(f"[{self.name}] Insufficient data: {len(rows) if rows else 0}")
            return

        df = pl.DataFrame({
            'time': [datetime.fromtimestamp(r[0], tz=LOCAL_TZ) for r in rows],
            'open': [float(r[1]) for r in rows],
            'high': [float(r[2]) for r in rows],
            'low': [float(r[3]) for r in rows],
            'close': [float(r[4]) for r in rows],
            'volume': [float(r[5]) for r in rows],
        })
        self._train_model(df)

    def _train_model(self, df: 'pl.DataFrame'):
        """Walk-forward XGBoost training."""
        df_feat = self._fe.calculate_all(df, include_ml=True)

        exclude = {'time', 'open', 'high', 'low', 'close', 'volume',
                   'spread', 'target', 'target_return'}
        self.feature_cols = [c for c in df_feat.columns if c not in exclude and not c.startswith('_')]

        # Binary target: next bar direction
        df_feat = df_feat.with_columns([
            (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Int32).alias("target")
        ])

        df_clean = df_feat.select(self.feature_cols + ["target"]).drop_nulls()
        if len(df_clean) < 200:
            logger.warning(f"[{self.name}] Insufficient clean data: {len(df_clean)}")
            return

        X = df_clean.select(self.feature_cols).to_numpy()
        y = df_clean.select("target").to_numpy().ravel()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Walk-forward split
        split = int(len(X) * 0.7)
        gap = min(50, len(X) - split - 10)
        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split + gap:], y[split + gap:]

        if len(X_train) < 100 or len(X_test) < 50:
            return

        params = {
            'objective': 'binary:logistic', 'eval_metric': 'auc',
            'max_depth': 3, 'learning_rate': 0.024,
            'min_child_weight': 10, 'subsample': 0.7, 'colsample_bytree': 0.6,
            'reg_alpha': 1.0, 'reg_lambda': 5.0, 'gamma': 1.0,
            'tree_method': 'hist', 'device': 'cpu',
        }

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=self.feature_cols)
        dtest = xgb.DMatrix(X_test, label=y_test, feature_names=self.feature_cols)

        self.model = xgb.train(
            params, dtrain, num_boost_round=100,
            evals=[(dtrain, 'train'), (dtest, 'eval')],
            early_stopping_rounds=10, verbose_eval=0,
        )
        self.fitted = True

        # Evaluation
        train_pred = (self.model.predict(dtrain) > 0.5).astype(int)
        test_pred = (self.model.predict(dtest) > 0.5).astype(int)
        train_acc = (train_pred == y_train).mean()
        test_acc = (test_pred == y_test).mean()
        logger.info(
            f"[{self.name}] Model trained: {len(X_train)}/{len(X_test)} samples, "
            f"train_acc={train_acc:.1%}, test_acc={test_acc:.1%}"
        )

    def _predict(self) -> tuple[Optional[OrderType], float, float]:
        """Generate signal from trained model using latest candle data.
        Returns (signal, prob_up, prob_down)."""
        if not self.fitted or self.model is None:
            return (None, 0.0, 0.0)

        # Build Polars DataFrame from current candles
        if len(self.candles) < 30:
            return (None, 0.0, 0.0)
        records = []
        for c in self.candles:
            ts = c.time
            try:
                dt = datetime.strptime(ts, '%Y.%m.%d %H:%M')
            except ValueError:
                try:
                    dt = datetime.strptime(ts.split('.')[0], '%Y-%m-%d')
                except ValueError:
                    dt = datetime.now(LOCAL_TZ)
            records.append({
                'time': dt,
                'open': c.open,
                'high': c.high,
                'low': c.low,
                'close': c.close,
                'volume': c.volume,
            })

        df = pl.DataFrame(records)
        if df.height < 30:
            return (None, 0.0, 0.0)
        df_feat = self._fe.calculate_all(df, include_ml=True)

        avail = [c for c in self.feature_cols if c in df_feat.columns]
        if len(avail) != len(self.feature_cols):
            return (None, 0.0, 0.0)

        last = df_feat.tail(1).select(self.feature_cols)
        X = last.to_numpy()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        dmatrix = xgb.DMatrix(X, feature_names=self.feature_cols)
        prob_up = float(self.model.predict(dmatrix)[0])
        prob_down = 1 - prob_up

        sig = None
        if prob_up > self.confidence_threshold:
            sig = OrderType.BUY
        elif prob_down > self.confidence_threshold:
            sig = OrderType.SELL

        if sig:
            logger.info(f"[{self.name}] ML signal: {sig.value} (up={prob_up:.3f}, down={prob_down:.3f})")

        return (sig, prob_up, prob_down)

    # ─────────────── Signal generation ───────────────

    def generate_signal(self):
        if not self.fitted:
            return (None, 0, 0, [], [], {})
        signal, prob_up, prob_down = self._predict()
        indicator_values = {
            "close": round(self.candles[-1].close, 2) if self.candles else 0,
            "confidence": round(prob_up, 4),
        }
        return (signal, 0, 0, [], [], indicator_values, prob_up)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * 3.0
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist * 50, 2)

    def get_adx_data(self) -> Optional[dict]:
        """提供 ADX/DI data给engineGate"""
        _adx = self.get_indicator("adx")
        if _adx is None:
            return None
        return {"adx": _adx, "pdi": self.get_indicator("pdi"), "ndi": self.get_indicator("ndi")}

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            if drawdown > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "drawdown": round(drawdown, 2)}
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            if rally > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "rally": round(rally, 2)}
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """defaultverify：tick 价不跑出 BB bound"""
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or signal.get("indicator_values", {}).get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
        return True
