"""
训练 XAUBot XGBoost 模型
- 从 SQLite 加载 H1 数据
- 计算 80+ 技术特征
- Walk-forward 训练 XGBoost
- 保存模型到 models/xaubot_model.*
"""

import json
import logging
import os
import sys
from datetime import datetime

# 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
os.makedirs(MODEL_DIR, exist_ok=True)

MODEL_PATH = os.path.join(MODEL_DIR, "xaubot_model.ubj")
META_PATH = os.path.join(MODEL_DIR, "xaubot_meta.json")


def main():
    # 检查依赖
    try:
        import xgboost as xgb
        import polars as pl
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        logger.error("请安装: pip install xgboost polars")
        sys.exit(1)

    # 加载 H1 数据
    from data.database import get_conn

    conn = get_conn()
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
        "WHERE timeframe='H1' ORDER BY timestamp"
    ).fetchall()
    conn.close()

    if not rows or len(rows) < 300:
        logger.error(f"数据不足: {len(rows) if rows else 0}")
        sys.exit(1)

    logger.info(f"加载了 {len(rows)} 条 H1 数据")

    # 构建 Polars DataFrame
    df = pl.DataFrame({
        'time': [datetime.fromtimestamp(r[0]) for r in rows],
        'open': [float(r[1]) for r in rows],
        'high': [float(r[2]) for r in rows],
        'low': [float(r[3]) for r in rows],
        'close': [float(r[4]) for r in rows],
        'volume': [float(r[5]) for r in rows],
    })

    # 特征工程
    from strategies.xaubot_backup import _FeatureEngineer
    fe = _FeatureEngineer()
    df_feat = fe.calculate_all(df, include_ml=True)
    logger.info(f"特征工程完成: {df_feat.shape}")

    # 特征列
    exclude = {'time', 'open', 'high', 'low', 'close', 'volume',
               'spread', 'target', 'target_return'}
    feature_cols = [c for c in df_feat.columns if c not in exclude and not c.startswith('_')]
    logger.info(f"特征数量: {len(feature_cols)}")

    # 目标: 下一根K线方向
    df_feat = df_feat.with_columns([
        pl.col("close").shift(-1).alias("close_next")
    ])
    df_feat = df_feat.with_columns([
        (pl.col("close_next") > pl.col("close")).cast(pl.Int32).alias("target")
    ])

    df_clean = df_feat.select(feature_cols + ["target"]).drop_nulls()
    logger.info(f"有效样本: {len(df_clean)}")

    if len(df_clean) < 200:
        logger.error("有效样本不足")
        sys.exit(1)

    X = df_clean.select(feature_cols).to_numpy()
    y = df_clean.select("target").to_numpy().ravel()
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Walk-forward 切分
    split = int(len(X) * 0.7)
    gap = min(50, len(X) - split - 10)
    X_train, y_train = X[:split], y[:split]
    X_test, y_test = X[split + gap:], y[split + gap:]

    logger.info(f"训练集: {len(X_train)}  测试集: {len(X_test)}")

    if len(X_train) < 100 or len(X_test) < 50:
        logger.error("训练/测试样本不足")
        sys.exit(1)

    # 训练 XGBoost
    params = {
        'objective': 'binary:logistic', 'eval_metric': 'auc',
        'max_depth': 3, 'learning_rate': 0.024,
        'min_child_weight': 10, 'subsample': 0.7, 'colsample_bytree': 0.6,
        'reg_alpha': 1.0, 'reg_lambda': 5.0, 'gamma': 1.0,
        'tree_method': 'hist', 'device': 'cpu',
    }

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_cols)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=feature_cols)

    model = xgb.train(
        params, dtrain, num_boost_round=100,
        evals=[(dtrain, 'train'), (dtest, 'eval')],
        early_stopping_rounds=10, verbose_eval=10,
    )

    # 评估
    train_pred = (model.predict(dtrain) > 0.5).astype(int)
    test_pred = (model.predict(dtest) > 0.5).astype(int)
    train_acc = (train_pred == y_train).mean()
    test_acc = (test_pred == y_test).mean()

    from sklearn.metrics import classification_report
    logger.info(f"\n训练集准确率: {train_acc:.1%}")
    logger.info(f"测试集准确率: {test_acc:.1%}")
    logger.info(f"\n测试集分类报告:\n{classification_report(y_test, test_pred, target_names=['DOWN', 'UP'])}")

    # 保存模型
    model.save_model(MODEL_PATH)
    logger.info(f"模型已保存: {MODEL_PATH}")

    # 保存元数据
    meta = {
        "feature_cols": feature_cols,
        "confidence_threshold": 0.52,
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "train_accuracy": round(float(train_acc), 4),
        "test_accuracy": round(float(test_acc), 4),
        "trained_at": datetime.now().isoformat(),
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    logger.info(f"元数据已保存: {META_PATH}")

    logger.info("=" * 50)
    logger.info("训练完成！重启引擎后 xaubot_backup 将自动加载模型。")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
