"""
回测脚本 - 使用 Backtrader 框架
安装: pip install backtrader pandas
"""

import logging
import os
import sys
from datetime import datetime

import pandas as pd

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class DoubleMA_Backtest:
    """双均线回测（纯 Pandas 实现，不依赖 backtrader）"""

    def __init__(self, data: pd.DataFrame, fast: int = 20, slow: int = 60):
        self.data = data.copy()
        self.fast = fast
        self.slow = slow
        self.initial_cash = settings.BACKTEST_INITIAL_CASH
        self.positions = []
        self.trades = []

    def run(self):
        """运行回测"""
        df = self.data
        df["ma_fast"] = df["close"].ewm(span=self.fast, adjust=False).mean()
        df["ma_slow"] = df["close"].ewm(span=self.slow, adjust=False).mean()

        # 交叉信号
        df["signal"] = 0
        df.loc[
            (df["ma_fast"] > df["ma_slow"]) &
            (df["ma_fast"].shift(1) <= df["ma_slow"].shift(1)),
            "signal"
        ] = 1  # 金叉

        df.loc[
            (df["ma_fast"] < df["ma_slow"]) &
            (df["ma_fast"].shift(1) >= df["ma_slow"].shift(1)),
            "signal"
        ] = -1  # 死叉

        # 模拟交易
        cash = self.initial_cash
        position = 0  # 0=空仓, 1=多仓, -1=空仓
        entry_price = 0

        for i in range(1, len(df)):
            row = df.iloc[i]
            signal = row["signal"]

            if signal == 1 and position == 0:
                # 金叉开多
                position = 1
                entry_price = row["close"]
                logger.info(f"[{row['time']}] 金叉开多 @ {entry_price:.2f}")

            elif signal == -1 and position == 1:
                # 死叉平多
                exit_price = row["close"]
                pnl = exit_price - entry_price
                cash += pnl
                logger.info(
                    f"[{row['time']}] 死叉平多 @ {exit_price:.2f} "
                    f"盈亏: {pnl:+.2f} 资金: {cash:.2f}"
                )
                position = 0
                self.trades.append({
                    "entry_time": df.iloc[i - 1]["time"],
                    "exit_time": row["time"],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                })

        # 如果最后还有持仓，按最后价格平仓
        if position == 1:
            last = df.iloc[-1]
            pnl = last["close"] - entry_price
            cash += pnl
            logger.info(f"[{last['time']}] 最终平仓 @ {last['close']:.2f} 盈亏: {pnl:+.2f}")

        return cash, self.trades

    def report(self, final_cash: float, trades: list):
        """输出回测报告"""
        total_return = (final_cash - self.initial_cash) / self.initial_cash * 100
        total_trades = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0

        # 最大回撤
        equity = [self.initial_cash]
        for t in trades:
            equity.append(equity[-1] + t["pnl"])
        peak = equity[0]
        max_dd = 0
        for eq in equity:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

        logger.info("=" * 50)
        logger.info("回测报告")
        logger.info("=" * 50)
        logger.info(f"初始资金:    ${self.initial_cash:,.2f}")
        logger.info(f"最终资金:    ${final_cash:,.2f}")
        logger.info(f"总收益率:    {total_return:+.2f}%")
        logger.info(f"总交易次数:  {total_trades}")
        logger.info(f"胜率:        {win_rate:.1f}%")
        logger.info(f"平均盈利:    ${avg_win:+.2f}")
        logger.info(f"平均亏损:    ${avg_loss:+.2f}")
        logger.info(f"盈亏比:      {abs(avg_win / avg_loss):.2f}" if avg_loss != 0 else "N/A")
        logger.info(f"最大回撤:    {max_dd:.2f}%")
        logger.info("=" * 50)


def load_csv(path: str) -> pd.DataFrame:
    """加载 CSV 回测数据
    期望列: time,open,high,low,close,volume
    """
    df = pd.read_csv(path)
    if "time" not in df.columns and "date" in df.columns:
        df = df.rename(columns={"date": "time"})
    return df


def main():
    data_path = os.path.join("data", "XAUUSD_H1.csv")

    if not os.path.exists(data_path):
        logger.warning(f"回测数据文件不存在: {data_path}")
        logger.info("请使用 MT4 导出历史数据，或使用 generate_sample_data.py 生成示例数据")
        logger.info("数据格式: CSV, 列: time,open,high,low,close,volume")
        return

    logger.info(f"加载回测数据: {data_path}")
    df = load_csv(data_path)
    logger.info(f"数据量: {len(df)} 条 K线")
    logger.info(f"时间范围: {df['time'].iloc[0]} ~ {df['time'].iloc[-1]}")

    backtest = DoubleMA_Backtest(
        data=df,
        fast=settings.MA_FAST,
        slow=settings.MA_SLOW,
    )

    final_cash, trades = backtest.run()
    backtest.report(final_cash, trades)


if __name__ == "__main__":
    main()
