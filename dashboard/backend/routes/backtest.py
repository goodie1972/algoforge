"""
/api/backtest 路由 - 回测
"""
import logging
import threading
import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    strategies: list[str]       # 策略名称列表
    symbol: str = "XAUUSD"
    timeframe: str = "H1"
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_cash: float = 10000.0
    commission: float = 0.5


# 内存中的回测任务状态
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _run_backtest_job(job_id: str, params: BacktestRequest):
    """后台线程执行回测"""
    try:
        with _lock:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["progress"] = "正在加载历史数据..."

        # 导入回测模块
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

        import pandas as pd
        from datetime import datetime as dt

        # 尝试加载 CSV 数据
        data_file = os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "backtest", "sample_data",
            f"{params.symbol}_{params.timeframe}.csv",
        )

        df = None
        if os.path.exists(data_file):
            df = pd.read_csv(data_file, parse_dates=["time"])
            df = df[(df["time"] >= params.start_date) & (df["time"] <= params.end_date)]
            logger.info(f"backtest {job_id}: loaded {len(df)} data rows from {data_file}")
        else:
            # 生成模拟数据
            with _lock:
                _jobs[job_id]["progress"] = "生成模拟数据..."
            logger.warning(f"backtest {job_id}: No history data file, using simulated data")
            df = _generate_sample_data(params)

        if df is None or len(df) == 0:
            with _lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = "无可用数据"
            return

        # 运行每个策略
        results = {}
        for strategy_name in params.strategies:
            with _lock:
                _jobs[job_id]["progress"] = f"运行策略: {strategy_name}"

            strategy_result = _run_single_strategy(
                df, strategy_name, params.initial_cash, params.commission
            )
            results[strategy_name] = strategy_result

        # 汇总结果
        summary = {
            "total_return": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "equity_curve": [],
            "trades": [],
            "by_strategy": {},
        }

        for name, r in results.items():
            summary["total_return"] += r.get("total_pnl", 0)
            summary["total_trades"] += r.get("total_trades", 0)
            summary["trades"].extend(r.get("trades", []))
            summary["by_strategy"][name] = r

        if summary["total_trades"] > 0:
            wins = sum(1 for t in summary["trades"] if t.get("pnl", 0) > 0)
            summary["win_rate"] = round(wins / summary["total_trades"] * 100, 2)

        if results:
            summary["equity_curve"] = list(results.values())[0].get("equity_curve", [])

        with _lock:
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["result"] = summary
            _jobs[job_id]["completed_at"] = datetime.now().isoformat()
            _jobs[job_id]["progress"] = "完成"

    except Exception as e:
        logger.exception(f"backtest {job_id} failed")
        with _lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(e)


def _generate_sample_data(params: BacktestRequest):
    """生成模拟 OHLC 数据"""
    import pandas as pd
    import numpy as np

    tf_minutes = {
        "M5": 5, "M15": 15, "M30": 30,
        "H1": 60, "H4": 240, "D1": 1440, "W1": 10080,
    }
    minutes = tf_minutes.get(params.timeframe, 60)
    start = datetime.strptime(params.start_date, "%Y-%m-%d")
    end = datetime.strptime(params.end_date, "%Y-%m-%d")
    total_minutes = (end - start).total_seconds() // 60
    n_candles = int(total_minutes // minutes)

    if n_candles > 50000:
        n_candles = 50000

    np.random.seed(42)
    price = 2650.0
    data = []
    for i in range(n_candles):
        change = np.random.normal(0, 2.0)
        price += change
        high = price + abs(np.random.normal(0, 1.5))
        low = price - abs(np.random.normal(0, 1.5))
        o = price - change * 0.3 + np.random.normal(0, 0.5)
        c = price
        vol = int(abs(np.random.normal(100, 50)))
        ts = int((start.timestamp() + i * minutes * 60))
        data.append({
            "time": ts,
            "open": round(o, 2),
            "high": round(max(o, c, high), 2),
            "low": round(min(o, c, low), 2),
            "close": round(c, 2),
            "tick_volume": vol,
        })

    return pd.DataFrame(data)


def _run_single_strategy(df, strategy_name: str, initial_cash: float, commission: float) -> dict:
    """运行单个策略的简化回测"""
    cash = initial_cash
    position = 0
    entry_price = 0
    equity_curve = []
    trades = []

    # 根据策略名称产生信号
    signals = _generate_signals(df, strategy_name)

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_close = df.iloc[i - 1]["close"]
        price = row["close"]
        signal = signals[i] if i < len(signals) else 0

        # 平仓条件
        if position == 1 and signal == -1:
            pnl = (price - entry_price) * 100 - commission
            cash += pnl
            trades.append({
                "entry_time": int(entry_time) if isinstance(entry_time, float) else 0,
                "exit_time": int(row["time"]),
                "direction": "BUY",
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "pnl": round(pnl, 2),
                "strategy": strategy_name,
            })
            position = 0
        elif position == -1 and signal == 1:
            pnl = (entry_price - price) * 100 - commission
            cash += pnl
            trades.append({
                "entry_time": int(entry_time) if isinstance(entry_time, float) else 0,
                "exit_time": int(row["time"]),
                "direction": "SELL",
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "pnl": round(pnl, 2),
                "strategy": strategy_name,
            })
            position = 0

        # 开仓
        if position == 0 and signal == 1:
            position = 1
            entry_price = price
            entry_time = row["time"]
        elif position == 0 and signal == -1:
            position = -1
            entry_price = price
            entry_time = row["time"]

        equity_curve.append({
            "time": int(row["time"]),
            "value": round(cash + (position * (price - entry_price) * 100 if position != 0 else 0), 2),
        })

    # 强制平仓
    if position != 0:
        last_price = df.iloc[-1]["close"]
        pnl = ((last_price - entry_price) * 100 if position == 1 else (entry_price - last_price) * 100) - commission
        cash += pnl
        trades.append({
            "entry_time": int(entry_time) if isinstance(entry_time, float) else 0,
            "exit_time": int(df.iloc[-1]["time"]),
            "direction": "BUY" if position == 1 else "SELL",
            "entry_price": round(entry_price, 2),
            "exit_price": round(last_price, 2),
            "pnl": round(pnl, 2),
            "strategy": strategy_name,
        })

    total_pnl = cash - initial_cash
    max_equity = initial_cash
    max_drawdown = 0.0
    current_equity = initial_cash
    for pt in equity_curve:
        current_equity = pt["value"]
        if current_equity > max_equity:
            max_equity = current_equity
        dd = (max_equity - current_equity) / max_equity * 100
        if dd > max_drawdown:
            max_drawdown = dd

    return {
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_pnl / initial_cash * 100, 2),
        "total_trades": len(trades),
        "max_drawdown": round(max_drawdown, 2),
        "trades": trades,
        "equity_curve": equity_curve,
    }


def _generate_signals(df, strategy_name: str) -> list[int]:
    """根据策略名称生成简化信号"""
    import pandas as pd

    close = df["close"].values
    signals = [0] * len(df)

    if strategy_name == "v6_hybrid":
        # V6 Hybrid 简化信号：KDJ超卖/超买 + 布林带
        if len(close) < 50:
            return signals
        stoch_k_val = _calc_stoch(df, 14)
        for i in range(50, len(close)):
            if stoch_k_val[i] < 30 and close[i] < close[i - 1]:
                signals[i] = 1
            elif stoch_k_val[i] > 65 and close[i] > close[i - 1]:
                signals[i] = -1

    elif strategy_name == "double_ma":
        fast = 20
        slow = 60
        if len(close) <= slow:
            return signals
        ema_fast = pd.Series(close).ewm(span=fast, adjust=False).mean().values
        ema_slow = pd.Series(close).ewm(span=slow, adjust=False).mean().values
        for i in range(slow + 1, len(close)):
            if ema_fast[i] > ema_slow[i] and ema_fast[i - 1] <= ema_slow[i - 1]:
                signals[i] = 1
            elif ema_fast[i] < ema_slow[i] and ema_fast[i - 1] >= ema_slow[i - 1]:
                signals[i] = -1

    elif strategy_name in ("rsi_bollinger", "H1_rsi_bollinger"):
        rsi_period = 14
        bb_period = 20
        if len(close) < max(rsi_period, bb_period) + 1:
            return signals
        # 简化 RSI
        rsi = _calc_rsi(close, rsi_period)
        # 简化 BB
        sma = pd.Series(close).rolling(bb_period).mean().values
        std = pd.Series(close).rolling(bb_period).std().values
        for i in range(max(rsi_period, bb_period) + 1, len(close)):
            if rsi[i] < 30 and close[i] < sma[i] - 2 * std[i]:
                signals[i] = 1
            elif rsi[i] > 70 and close[i] > sma[i] + 2 * std[i]:
                signals[i] = -1

    elif strategy_name in ("stoch_bollinger", "H4_stoch_bollinger"):
        k_period = 14
        if len(close) < k_period + 1:
            return signals
        # 简化 Stoch
        stoch_k = _calc_stoch(df, k_period)
        for i in range(k_period + 1, len(close)):
            if stoch_k[i] < 20:
                signals[i] = 1
            elif stoch_k[i] > 80:
                signals[i] = -1

    elif strategy_name == "atr_breakout":
        atr_period = 14
        if len(close) < atr_period + 1:
            return signals
        atr = _calc_atr(df, atr_period)
        for i in range(atr_period + 2, len(close)):
            if close[i] > close[i - 1] + atr[i - 1] * 1.5:
                signals[i] = 1
            elif close[i] < close[i - 1] - atr[i - 1] * 1.5:
                signals[i] = -1

    elif strategy_name == "combined":
        # 双确认：MA + RSI
        ma_signals = _generate_signals(df, "double_ma")
        rsi = _calc_rsi(close, 14)
        for i in range(len(close)):
            if ma_signals[i] == 1 and rsi[i] < 70:
                signals[i] = 1
            elif ma_signals[i] == -1 and rsi[i] > 30:
                signals[i] = -1

    return signals


def _calc_rsi(close, period: int) -> list[float]:
    import pandas as pd
    rsi = [50] * len(close)
    if len(close) < period + 1:
        return rsi
    gains, losses = 0, 0
    for i in range(1, period + 1):
        diff = close[i] - close[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    rsi[period] = avg_loss == 0 and 100 or 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(close)):
        diff = close[i] - close[i - 1]
        gain = diff if diff >= 0 else 0
        loss = -diff if diff < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsi[i] = avg_loss == 0 and 100 or 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def _calc_stoch(df, k_period: int) -> list[float]:
    stoch = [50] * len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    for i in range(k_period - 1, len(df)):
        h = max(high[i - k_period + 1:i + 1])
        l = min(low[i - k_period + 1:i + 1])
        rng = h - l
        stoch[i] = rng == 0 and 100 or (close[i] - l) / rng * 100
    return stoch


def _calc_atr(df, period: int) -> list[float]:
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    atr = [0.0] * len(df)
    tr = 0.0
    for i in range(len(df)):
        if i == 0:
            tr = high[i] - low[i]
        else:
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        if i < period:
            atr[i] = tr
        else:
            atr[i] = (atr[i - 1] * (period - 1) + tr) / period
    return atr


# === API 端点 ===

@router.post("/run")
async def run_backtest(params: BacktestRequest):
    """启动回测任务"""
    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "params": params.model_dump(),
            "created_at": datetime.now().isoformat(),
            "progress": "排队中...",
        }
    thread = threading.Thread(target=_run_backtest_job, args=(job_id, params), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def backtest_status(job_id: str):
    """查询回测进度"""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return {"error": "任务不存在"}
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job.get("progress", ""),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    }


@router.get("/results/{job_id}")
async def backtest_results(job_id: str):
    """获取回测结果"""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return {"error": "任务不存在"}
    if job["status"] != "completed":
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job.get("progress", ""),
        }
    return {
        "job_id": job["job_id"],
        "status": "completed",
        "result": job.get("result", {}),
    }


@router.get("/history")
async def backtest_history(limit: int = 20):
    """历史回测记录"""
    with _lock:
        all_jobs = sorted(
            _jobs.values(),
            key=lambda j: j.get("created_at", ""),
            reverse=True,
        )
    recent = all_jobs[:limit]
    return [
        {
            "job_id": j["job_id"],
            "status": j["status"],
            "created_at": j.get("created_at"),
            "params": j.get("params", {}),
            "result_summary": {
                k: v for k, v in j.get("result", {}).items()
                if k in ("total_return", "total_return_pct", "total_trades", "win_rate", "max_drawdown")
            } if j.get("result") else None,
        }
        for j in recent
    ]
