"""
XAUUSD 三个 Backtrader 策略统一回测运行器
回测策略:
  1. bolling-test — 布林带 + KDJ + MACD底背驰
  2. chan-test — KDJ + MACD底背驰
  3. keltner-test — 肯特纳通道 + KDJ + MACD底背驰

数据: data/XAUUSD_H1_merged.csv (2024-01 ~ 2026-06, H1)
运行: python backtest/backtest_three_strategies.py
"""

import os
import sys
from datetime import datetime

import backtrader as bt
import backtrader.feeds as btfeeds
import pandas as pd
import numpy as np

# ============================================================
# 安全的MACD底背驰检测器（公用，与3个策略完全一致）
# ============================================================
class SafeMACDDivergence:
    @staticmethod
    def check_bottom_divergence(macd_hist_line, price_low_line, lookback=15):
        """安全检测MACD底背驰，使用Backtrader LineBuffer的[-N]索引"""
        try:
            # 使用Backtrader的[-N]负索引从当前bar向前查找
            lows = []
            for i in range(1, lookback * 2):
                p = price_low_line[-i]
                p_prev = price_low_line[-(i+1)]
                p_next = price_low_line[-(i-1)]
                if p < p_prev and p < p_next:
                    m = macd_hist_line[-i]
                    lows.append((i, p, m))
            if len(lows) < 2:
                return False
            p1_idx, p1_val, m1_val = lows[-2]
            p2_idx, p2_val, m2_val = lows[-1]
            if p2_val < p1_val and m2_val > m1_val:
                return True
        except Exception:
            pass
        return False


# ============================================================
# 策略1: Bollinger 布林带版
# ============================================================
class BollingerGoldStrategy(bt.Strategy):
    params = (
        ('sma200_period', 200),
        ('bb_period', 20),
        ('bb_dev', 2.5),
        ('k_period', 9),
        ('d_period', 3),
        ('oversold_threshold', 25),
        ('bias_threshold', 4.0),
        ('divergence_lookback', 15),
        ('trailing_stop_atr_mult', 2.0),
        ('hard_stop_atr_mult', 1.5),
        ('print_log', True),
    )

    def __init__(self):
        self.sma200 = bt.indicators.SMA(self.data.close, period=self.p.sma200_period)
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.k_period,
            period_dfast=self.p.d_period, movav=bt.indicators.MovAv.SMA
        )
        self.macd = bt.indicators.MACD(
            self.data.close, period_me1=12, period_me2=26, period_signal=9
        )
        self.macd_hist = self.macd.macd - self.macd.signal
        self.atr = bt.indicators.ATR(self.data, period=20)
        self.entry_price = None
        self.highest_since_entry = None
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0
        self.trades_log = []

    def log(self, txt):
        if self.p.print_log:
            print(f'{self.datas[0].datetime.date(0)} {txt}')

    def next(self):
        if len(self.data) < self.p.sma200_period + self.p.divergence_lookback * 2 + 5:
            return
        k_prev = self.stoch.percK[-1]
        d_prev = self.stoch.percD[-1]
        k_prev2 = self.stoch.percK[-2]
        close_prev = self.data.close[-1]
        low_prev = self.data.low[-1]
        current_atr = self.atr[-1]
        bb_bot_prev = self.bb.bot[-1]

        trend_up = close_prev > self.sma200[-1]
        bias = (close_prev - bb_bot_prev) / bb_bot_prev * 100 if bb_bot_prev != 0 else 0
        near_lower_band = (low_prev <= bb_bot_prev) and (abs(bias) < self.p.bias_threshold)
        in_oversold_zone = k_prev2 < self.p.oversold_threshold
        k_turning_up = (k_prev > k_prev2) and (k_prev > d_prev)
        has_divergence = SafeMACDDivergence.check_bottom_divergence(
            self.macd_hist, self.data.low,
            lookback=self.p.divergence_lookback
        )

        if (not self.position and trend_up and
            near_lower_band and in_oversold_zone and
            k_turning_up and has_divergence):
            self.buy()
            self.entry_price = self.data.open[0]
            self.highest_since_entry = self.entry_price
            self.trade_count += 1
            self.log(f'BOLL BUY @ {self.entry_price:.2f} | Bias={bias:.2f}% | K={k_prev:.1f}')

        if self.position and self.entry_price is not None:
            self.highest_since_entry = max(self.highest_since_entry, self.data.close[-1])
            trail_dist = current_atr * self.p.trailing_stop_atr_mult
            hard_dist = current_atr * self.p.hard_stop_atr_mult
            drawdown = self.highest_since_entry - self.data.close[-1]
            loss = self.entry_price - self.data.close[-1]
            if drawdown > trail_dist or loss > hard_dist:
                exit_price = self.data.open[0]
                pnl = exit_price - self.entry_price
                self.total_pnl += pnl
                if pnl > 0: self.win_count += 1
                self.trades_log.append({"entry": self.entry_price, "exit": exit_price, "pnl": pnl})
                self.close()
                self.log(f'BOLL SELL @ {exit_price:.2f} | PnL: {pnl:.2f}')
                self.entry_price = None
                self.highest_since_entry = None

    def stop(self):
        wr = self.win_count / self.trade_count if self.trade_count > 0 else 0
        print(f'\n=== 布林带修复版回测结果 ===')
        print(f'交易次数: {self.trade_count} | 胜率: {wr:.2%} | 总盈亏: ${self.total_pnl:.2f}')
        if self.trade_count > 0:
            wins = [t for t in self.trades_log if t["pnl"] > 0]
            losses = [t for t in self.trades_log if t["pnl"] <= 0]
            print(f'盈利交易: {len(wins)} | 亏损交易: {len(losses)}')
            if wins: print(f'平均盈利: ${sum(t["pnl"] for t in wins)/len(wins):.2f}')
            if losses: print(f'平均亏损: ${sum(t["pnl"] for t in losses)/len(losses):.2f}')


# ============================================================
# 策略2: Chan KDJ+MACD 版
# ============================================================
class ChanKDJMACDStrategy(bt.Strategy):
    params = (
        ('sma200_period', 200),
        ('k_period', 9),
        ('d_period', 3),
        ('oversold_threshold', 25),
        ('divergence_lookback', 15),
        ('trailing_stop_atr_mult', 2.0),
        ('hard_stop_atr_mult', 1.5),
        ('print_log', True),
    )

    def __init__(self):
        self.sma200 = bt.indicators.SMA(self.data.close, period=self.p.sma200_period)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.k_period,
            period_dfast=self.p.d_period, movav=bt.indicators.MovAv.SMA
        )
        self.macd = bt.indicators.MACD(
            self.data.close, period_me1=12, period_me2=26, period_signal=9
        )
        self.macd_hist = self.macd.macd - self.macd.signal
        self.atr = bt.indicators.ATR(self.data, period=20)
        self.entry_price = None
        self.highest_since_entry = None
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0
        self.trades_log = []

    def log(self, txt):
        if self.p.print_log:
            print(f'{self.datas[0].datetime.date(0)} {txt}')

    def next(self):
        if len(self.data) < self.p.sma200_period + self.p.divergence_lookback * 2 + 5:
            return
        k_prev = self.stoch.percK[-1]
        d_prev = self.stoch.percD[-1]
        k_prev2 = self.stoch.percK[-2]
        close_prev = self.data.close[-1]
        current_atr = self.atr[-1]

        trend_up = close_prev > self.sma200[-1]
        in_oversold_zone = k_prev2 < self.p.oversold_threshold
        k_turning_up = (k_prev > k_prev2) and (k_prev > d_prev)
        has_divergence = SafeMACDDivergence.check_bottom_divergence(
            self.macd_hist, self.data.low,
            lookback=self.p.divergence_lookback
        )

        if (not self.position and trend_up and
            in_oversold_zone and k_turning_up and has_divergence):
            self.buy()
            self.entry_price = self.data.open[0]
            self.highest_since_entry = self.entry_price
            self.trade_count += 1
            self.log(f'CHAN BUY @ {self.entry_price:.2f} | K={k_prev:.1f} | ATR={current_atr:.2f}')

        if self.position and self.entry_price is not None:
            self.highest_since_entry = max(self.highest_since_entry, self.data.close[-1])
            trail_dist = current_atr * self.p.trailing_stop_atr_mult
            hard_dist = current_atr * self.p.hard_stop_atr_mult
            drawdown = self.highest_since_entry - self.data.close[-1]
            loss = self.entry_price - self.data.close[-1]
            if drawdown > trail_dist or loss > hard_dist:
                exit_price = self.data.open[0]
                pnl = exit_price - self.entry_price
                self.total_pnl += pnl
                if pnl > 0: self.win_count += 1
                self.trades_log.append({"entry": self.entry_price, "exit": exit_price, "pnl": pnl})
                self.close()
                self.log(f'CHAN SELL @ {exit_price:.2f} | PnL: {pnl:.2f}')
                self.entry_price = None
                self.highest_since_entry = None

    def stop(self):
        wr = self.win_count / self.trade_count if self.trade_count > 0 else 0
        print(f'\n=== KDJ+MACD修复版回测结果 ===')
        print(f'交易次数: {self.trade_count} | 胜率: {wr:.2%} | 总盈亏: ${self.total_pnl:.2f}')
        if self.trade_count > 0:
            wins = [t for t in self.trades_log if t["pnl"] > 0]
            losses = [t for t in self.trades_log if t["pnl"] <= 0]
            print(f'盈利交易: {len(wins)} | 亏损交易: {len(losses)}')
            if wins: print(f'平均盈利: ${sum(t["pnl"] for t in wins)/len(wins):.2f}')
            if losses: print(f'平均亏损: ${sum(t["pnl"] for t in losses)/len(losses):.2f}')


# ============================================================
# 策略3: Keltner 肯特纳通道版
# ============================================================
class KeltnerGoldStrategy(bt.Strategy):
    params = (
        ('ema_period', 20),
        ('atr_mult', 2.5),
        ('atr_period', 20),
        ('sma200_period', 200),
        ('k_period', 9),
        ('d_period', 3),
        ('oversold_threshold', 25),
        ('divergence_lookback', 15),
        ('trailing_stop_atr_mult', 2.0),
        ('hard_stop_atr_mult', 1.5),
        ('print_log', True),
    )

    def __init__(self):
        self.sma200 = bt.indicators.SMA(self.data.close, period=self.p.sma200_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.kc_top = self.ema + self.atr * self.p.atr_mult
        self.kc_bot = self.ema - self.atr * self.p.atr_mult
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.k_period,
            period_dfast=self.p.d_period, movav=bt.indicators.MovAv.SMA
        )
        self.macd = bt.indicators.MACD(
            self.data.close, period_me1=12, period_me2=26, period_signal=9
        )
        self.macd_hist = self.macd.macd - self.macd.signal
        self.entry_price = None
        self.highest_since_entry = None
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0
        self.trades_log = []

    def log(self, txt):
        if self.p.print_log:
            print(f'{self.datas[0].datetime.date(0)} {txt}')

    def next(self):
        if len(self.data) < self.p.sma200_period + self.p.divergence_lookback * 2 + 5:
            return
        k_prev = self.stoch.percK[-1]
        d_prev = self.stoch.percD[-1]
        k_prev2 = self.stoch.percK[-2]
        close_prev = self.data.close[-1]
        low_prev = self.data.low[-1]
        current_atr = self.atr[-1]

        trend_up = close_prev > self.sma200[-1]
        in_oversold_zone = k_prev2 < self.p.oversold_threshold
        k_turning_up = (k_prev > k_prev2) and (k_prev > d_prev)
        near_lower_channel = low_prev <= self.kc_bot[-1]
        has_divergence = SafeMACDDivergence.check_bottom_divergence(
            self.macd_hist, self.data.low,
            lookback=self.p.divergence_lookback
        )

        if (not self.position and trend_up and
            in_oversold_zone and k_turning_up and
            near_lower_channel and has_divergence):
            self.buy()
            self.entry_price = self.data.open[0]
            self.highest_since_entry = self.entry_price
            self.trade_count += 1
            self.log(f'KELT BUY @ {self.entry_price:.2f} | K={k_prev:.1f} | ATR={current_atr:.2f}')

        if self.position and self.entry_price is not None:
            self.highest_since_entry = max(self.highest_since_entry, self.data.close[-1])
            trail_dist = current_atr * self.p.trailing_stop_atr_mult
            hard_dist = current_atr * self.p.hard_stop_atr_mult
            drawdown = self.highest_since_entry - self.data.close[-1]
            loss = self.entry_price - self.data.close[-1]
            if drawdown > trail_dist or loss > hard_dist:
                exit_price = self.data.open[0]
                pnl = exit_price - self.entry_price
                self.total_pnl += pnl
                if pnl > 0: self.win_count += 1
                self.trades_log.append({"entry": self.entry_price, "exit": exit_price, "pnl": pnl})
                self.close()
                self.log(f'KELT SELL @ {exit_price:.2f} | PnL: {pnl:.2f}')
                self.entry_price = None
                self.highest_since_entry = None

    def stop(self):
        wr = self.win_count / self.trade_count if self.trade_count > 0 else 0
        print(f'\n=== 肯特纳通道修复版回测结果 ===')
        print(f'交易次数: {self.trade_count} | 胜率: {wr:.2%} | 总盈亏: ${self.total_pnl:.2f}')
        if self.trade_count > 0:
            wins = [t for t in self.trades_log if t["pnl"] > 0]
            losses = [t for t in self.trades_log if t["pnl"] <= 0]
            print(f'盈利交易: {len(wins)} | 亏损交易: {len(losses)}')
            if wins: print(f'平均盈利: ${sum(t["pnl"] for t in wins)/len(wins):.2f}')
            if losses: print(f'平均亏损: ${sum(t["pnl"] for t in losses)/len(losses):.2f}')


# ============================================================
# 统一回测运行器
# ============================================================
def run_backtest(strategy_class, strategy_name, data_path, cash=10000.0):
    """运行单个策略的回测"""
    print(f'\n{"="*55}')
    print(f'  开始回测: {strategy_name}')
    print(f'  数据: {data_path}')
    print(f'  初始资金: ${cash:,.2f}')
    print(f'{"="*55}')

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_class)
    cerebro.broker.setcash(cash)

    # 加载H1数据（使用Backtrader自带的GenericCSVData）
    data = btfeeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d %H:%M:%S',
        timeframe=bt.TimeFrame.Minutes,
        compression=60,  # H1 = 60分钟
        fromdate=datetime(2024, 5, 1),  # 留出200天SMA预热
        todate=datetime(2026, 6, 5),

        # CSV列映射: time,open,high,low,close,volume
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,  # 无此列
    )
    cerebro.adddata(data)

    print(f'初始资金: ${cerebro.broker.getvalue():.2f}')
    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - cash) / cash * 100

    print(f'\n--- {strategy_name} 汇总 ---')
    print(f'初始资金: ${cash:,.2f}')
    print(f'最终资金: ${final_value:,.2f}')
    print(f'总收益率: {total_return:+.2f}%')
    print(f'交易次数: {strat.trade_count}')
    print(f'胜率: {strat.win_count/strat.trade_count*100:.1f}%' if strat.trade_count else 'N/A')

    return {
        'strategy': strategy_name,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': strat.trade_count,
        'win_count': strat.win_count,
        'total_pnl': strat.total_pnl,
    }


def main():
    # 使用最完整的H1合并数据
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "XAUUSD_H1_merged.csv")
    if not os.path.exists(data_path):
        # Fallback: 尝试 dev 目录
        alt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "..", "xauusd-dev", "data", "XAUUSD_H1_merged.csv")
        if os.path.exists(alt_path):
            data_path = alt_path
        else:
            print(f"错误: 找不到数据文件 XAUUSD_H1_merged.csv")
            sys.exit(1)

    print(f'数据文件: {data_path}')
    print(f'数据行数: {sum(1 for _ in open(data_path)) - 1} 根H1 K线')

    strategies = [
        (BollingerGoldStrategy, "布林带+KDJ+MACD底背驰"),
        (ChanKDJMACDStrategy, "KDJ+MACD底背驰（纯）"),
        (KeltnerGoldStrategy, "肯特纳通道+KDJ+MACD底背驰"),
    ]

    all_results = []
    for cls, name in strategies:
        result = run_backtest(cls, name, data_path)
        all_results.append(result)
        print()

    # 对比汇总
    print(f'\n{"="*55}')
    print(f'  三策略对比汇总')
    print(f'{"="*55}')
    print(f'{"策略":<30} {"收益率":>10} {"交易":>6} {"胜率":>8} {"总盈亏":>10}')
    print(f'{"-"*55}')
    for r in all_results:
        wr = r['win_count']/r['trade_count']*100 if r['trade_count'] else 0
        print(f'{r["strategy"]:<30} {r["total_return"]:>+9.2f}% {r["trade_count"]:>6} {wr:>7.1f}% {r["total_pnl"]:>+10.2f}')
    print(f'{"="*55}')


if __name__ == "__main__":
    main()
