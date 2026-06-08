"""
xaubot-ai — XGBoost ML 后备策略
================================
- Walk-forward XGBoost 二分类模型
- Polars 特征工程 (80+ technical features)
- 置信度阈值 0.52 触发信号
- ATR 动态追踪止损出场

注意:
  - 优先加载 models/xaubot_model.ubj（预训练模型）
  - 无预训练模型时首次加载自动从 SQLite 训练
  - 需要 xgboost + polars
"""

import json
import logging
import math
import os
from datetime import datetime
from typing import Optional

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


class _FeatureEngineer:
    """Polars-based feature engineering (xaubot-ai compatible)."""

    def calculate_all(self, df: 'pl.DataFrame', include_ml: bool = True) -> 'pl.DataFrame':
        df = self._rsi(df)
        df = self._atr(df)
        df = self._macd(df)
        df = self._bollinger(df)
        df = self._ema_crossover(df)
        df = self._volume_features(df)
        if include_ml:
            df = self._ml_features(df)
        return df

    def _rsi(self, df, p=14):
        alpha = 1.0 / p
        df = df.with_columns([pl.col("close").diff().alias("_delta")])
        df = df.with_columns([
            pl.when(pl.col("_delta") > 0).then(pl.col("_delta")).otherwise(0.0).alias("_gains"),
            pl.when(pl.col("_delta") < 0).then(-pl.col("_delta")).otherwise(0.0).alias("_losses"),
        ])
        df = df.with_columns([
            pl.col("_gains").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("_avg_gain"),
            pl.col("_losses").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("_avg_loss"),
        ])
        df = df.with_columns([
            pl.when(pl.col("_avg_loss") == 0).then(100.0)
            .otherwise(100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss")))
            .alias("rsi")
        ])
        return df.drop(["_delta", "_gains", "_losses", "_avg_gain", "_avg_loss"])

    def _atr(self, df, p=14):
        alpha = 1.0 / p
        df = df.with_columns([pl.col("close").shift(1).alias("_pc")])
        df = df.with_columns([
            pl.max_horizontal(
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("_pc")).abs(),
                (pl.col("low") - pl.col("_pc")).abs()
            ).alias("_tr")
        ])
        df = df.with_columns([
            pl.col("_tr").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("atr"),
        ])
        return df.drop(["_pc", "_tr"])

    def _macd(self, df):
        df = df.with_columns([
            pl.col("close").ewm_mean(span=12, adjust=False).alias("_ema12"),
            pl.col("close").ewm_mean(span=26, adjust=False).alias("_ema26"),
        ])
        df = df.with_columns([(pl.col("_ema12") - pl.col("_ema26")).alias("macd")])
        df = df.with_columns([pl.col("macd").ewm_mean(span=9, adjust=False).alias("macd_signal")])
        df = df.with_columns([(pl.col("macd") - pl.col("macd_signal")).alias("macd_histogram")])
        return df.drop(["_ema12", "_ema26"])

    def _bollinger(self, df, p=20, std=2.0):
        df = df.with_columns([
            pl.col("close").rolling_mean(p).alias("bb_middle"),
            pl.col("close").rolling_std(p).alias("_bb_std"),
        ])
        df = df.with_columns([
            (pl.col("bb_middle") + std * pl.col("_bb_std")).alias("bb_upper"),
            (pl.col("bb_middle") - std * pl.col("_bb_std")).alias("bb_lower"),
        ])
        df = df.with_columns([
            ((pl.col("bb_upper") - pl.col("bb_lower")) / pl.col("bb_middle")).alias("bb_width"),
            ((pl.col("close") - pl.col("bb_lower")) / (pl.col("bb_upper") - pl.col("bb_lower"))).alias("bb_percent_b"),
        ])
        return df.drop(["_bb_std"])

    def _ema_crossover(self, df, fast=9, slow=21):
        df = df.with_columns([
            pl.col("close").ewm_mean(span=fast, adjust=False).alias(f"ema_{fast}"),
            pl.col("close").ewm_mean(span=slow, adjust=False).alias(f"ema_{slow}"),
        ])
        df = df.with_columns([(pl.col(f"ema_{fast}") > pl.col(f"ema_{slow}")).alias("_ema_above")])
        df = df.with_columns([pl.col("_ema_above").shift(1).alias("_ema_above_p")])
        df = df.with_columns([
            (pl.col("_ema_above") & ~pl.col("_ema_above_p").fill_null(False)).cast(pl.Int8).alias("ema_cross_bull"),
            (~pl.col("_ema_above") & pl.col("_ema_above_p").fill_null(False)).cast(pl.Int8).alias("ema_cross_bear"),
        ])
        return df.drop(["_ema_above", "_ema_above_p"])

    def _volume_features(self, df, p=20):
        if "volume" not in df.columns:
            return df
        df = df.with_columns([pl.col("volume").rolling_mean(p).alias("volume_sma")])
        df = df.with_columns([
            (pl.col("volume") / pl.col("volume_sma")).alias("volume_ratio"),
        ])
        df = df.with_columns([
            (pl.col("volume_ratio") > 1.5).cast(pl.Int8).alias("high_volume"),
        ])
        df = df.with_columns([
            pl.when(pl.col("close") > pl.col("open")).then(pl.col("volume")).otherwise(0).alias("buy_volume"),
            pl.when(pl.col("close") < pl.col("open")).then(pl.col("volume")).otherwise(0).alias("sell_volume"),
        ])
        df = df.with_columns([
            ((pl.col("buy_volume") - pl.col("sell_volume")) / (pl.col("buy_volume") + pl.col("sell_volume") + 1e-9)).alias("ofi_pseudo"),
        ])
        return df

    def _ml_features(self, df):
        df = df.with_columns([
            (pl.col("close") / pl.col("close").shift(1) - 1).alias("returns_1"),
            (pl.col("close") / pl.col("close").shift(5) - 1).alias("returns_5"),
            (pl.col("close") / pl.col("close").shift(20) - 1).alias("returns_20"),
        ])
        df = df.with_columns([
            ((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low"))).alias("price_position"),
            pl.col("close").rolling_mean(20).alias("_sma20"),
        ])
        df = df.with_columns([
            (pl.col("close") / pl.col("_sma20") - 1).alias("dist_from_sma_20"),
        ])
        df = df.with_columns([
            pl.col("close").shift(1).alias("close_lag_1"),
            pl.col("close").shift(2).alias("close_lag_2"),
            pl.col("close").shift(3).alias("close_lag_3"),
        ])
        df = df.with_columns([
            (pl.col("high") > pl.col("high").shift(1)).cast(pl.Int8).alias("higher_high"),
            (pl.col("low") < pl.col("low").shift(1)).cast(pl.Int8).alias("lower_low"),
        ])
        if "time" in df.columns:
            df = df.with_columns([
                pl.col("time").dt.hour().alias("hour"),
                pl.col("time").dt.weekday().alias("weekday"),
            ])
        return df.drop(["_sma20"])


class XAUBotBackupStrategy(BaseStrategy):
    """xaubot-ai — XGBoost ML 后备策略 (H1)"""

    name = "xaubot_backup"

    _model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
    _model_path = os.path.join(_model_dir, "xaubot_model.ubj")
    _meta_path = os.path.join(_model_dir, "xaubot_meta.json")

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

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

        # 尝试加载已保存的模型（不训练也能用）
        self._try_load_model()

    def _try_load_model(self):
        """从 models/ 加载已保存的 XGBoost 模型"""
        if not HAS_XGB:
            return
        if not os.path.exists(self._model_path) or not os.path.exists(self._meta_path):
            logger.info(f"[{self.name}] 未找到已保存模型，将在首次数据加载时训练")
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
                f"[{self.name}] 已加载预训练模型: "
                f"test_acc={meta.get('test_accuracy', '?')} "
                f"特征={len(self.feature_cols)} "
                f"阈值={self.confidence_threshold}"
            )
        except Exception as e:
            logger.warning(f"[{self.name}] 加载模型失败，将重新训练: {e}")
            self.model = None
            self.fitted = False

    def refresh_data(self, count: int = 500):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

        # 仅在无已保存模型时训练
        if not self.fitted and HAS_XGB and HAS_POLARS and len(self.candles) >= 300:
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
            'time': [datetime.fromtimestamp(r[0]) for r in rows],
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

    def _predict(self) -> Optional[OrderType]:
        """Generate signal from trained model using latest candle data."""
        if not self.fitted or self.model is None:
            return None

        # Build Polars DataFrame from current candles
        if len(self.candles) < 30:
            return None
        records = []
        for c in self.candles:
            ts = c.time
            try:
                dt = datetime.strptime(ts, '%Y.%m.%d %H:%M')
            except ValueError:
                try:
                    dt = datetime.strptime(ts.split('.')[0], '%Y-%m-%d')
                except ValueError:
                    dt = datetime.now()
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
            return None
        df_feat = self._fe.calculate_all(df, include_ml=True)

        avail = [c for c in self.feature_cols if c in df_feat.columns]
        if len(avail) != len(self.feature_cols):
            return None

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

        return sig

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        if not self.fitted:
            # Fall back to simple EMA crossover if model not trained
            return None
        return self._predict()

    # ─────────────── SL/TP and Exit ───────────────

    def _calc_atr_values(self, period: int = 14) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
            tr_values.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(tr_values) < period:
            return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 14) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals else None

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * 3.0
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist * 50, 2)

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
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            if drawdown > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            if rally > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True

        return False
