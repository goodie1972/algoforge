"""
XAUUSD 多策略优化回测脚本 v2.0
================================
目标:  在考虑+1 K线滑点的前提下，比较6个策略变体
核心改进:
  - 信号用 [-1] 已闭合K线数据，通过 pending flag 在下一根 K 线的 open[0] 成交
  - cerebro.broker.set_slip_perc(0.001) = 0.1% 单边滑点
  - 动态 ATR 止损 + 做空逻辑 + 放宽条件增加交易频率
数据: data/XAUUSD_H1_merged.csv (2024-01 ~ 2026-06, H1)
运行: python backtest/backtest_optimization.py
"""

import os, sys, json, csv, shutil
from datetime import datetime
import backtrader as bt
import backtrader.feeds as btfeeds


# XAUUSD 手续费模型
# 每标准手(100oz)双边约$2-3, 取中值$2.50
# backtrader 默认 size=1 (1oz), 双边 $0.025/oz
# 费率 = 单边$0.0125 / $2300 ≈ 0.0000054 (0.00054%)
# 对 size=100 (0.1手) 的交易, 双边约$2.50
XAUUSD_COMMISSION_RATE = 0.0000054


# ============================================================
# 安全的MACD底背驰检测器
# ============================================================
class SafeMACDDivergence:
    @staticmethod
    def check_bottom_divergence(macd_hist_line, price_low_line, lookback=15):
        try:
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
            p1_val, m1_val = lows[-2][1], lows[-2][2]
            p2_val, m2_val = lows[-1][1], lows[-1][2]
            if p2_val < p1_val and m2_val > m1_val:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def check_top_divergence(macd_hist_line, price_high_line, lookback=15):
        try:
            highs = []
            for i in range(1, lookback * 2):
                p = price_high_line[-i]
                p_prev = price_high_line[-(i+1)]
                p_next = price_high_line[-(i-1)]
                if p > p_prev and p > p_next:
                    m = macd_hist_line[-i]
                    highs.append((i, p, m))
            if len(highs) < 2:
                return False
            p1_val, m1_val = highs[-2][1], highs[-2][2]
            p2_val, m2_val = highs[-1][1], highs[-1][2]
            if p2_val > p1_val and m2_val < m1_val:
                return True
        except Exception:
            pass
        return False


# ============================================================
# 基础策略基类 — 统一模板
# ============================================================
class BaseOptimizedStrategy(bt.Strategy):
    """所有变体共用基类：+1 K线入场 + ATR动态止损"""

    params = (
        ('name', 'Base'),
        ('trailing_atr', 3.5),
        ('hard_atr', 2.5),
    )

    def __init__(self):
        self.sma200 = bt.indicators.SMA(self.data.close, period=200)
        self.stoch = bt.indicators.Stochastic(
            self.data, period=9, period_dfast=3, movav=bt.indicators.MovAv.SMA
        )
        self.macd = bt.indicators.MACD(
            self.data.close, period_me1=12, period_me2=26, period_signal=9
        )
        self.macd_hist = self.macd.macd - self.macd.signal
        self.atr = bt.indicators.ATR(self.data, period=20)
        self.atr_sma = bt.indicators.SMA(self.atr, period=10)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

        self.entry_price = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0
        self.trades_log = []

        # +1 K线入场: pending flag — signal detected this bar, execute NEXT bar at open[0]
        self._pending_order = None  # 'buy' or 'sell' or None

    def log(self, txt):
        print(f'{self.datas[0].datetime.date(0)} {txt}')

    def _enter_long(self, price=None):
        self.buy()
        self.entry_price = price or self.data.open[0]
        self.highest_since_entry = self.entry_price
        self.trade_count += 1

    def _enter_short(self, price=None):
        self.sell()
        self.entry_price = price or self.data.open[0]
        self.lowest_since_entry = self.entry_price
        self.trade_count += 1

    def _exit_long(self, price, reason=''):
        pnl = price - self.entry_price
        self.total_pnl += pnl
        if pnl > 0:
            self.win_count += 1
        self.trades_log.append(dict(entry=self.entry_price, exit=price, pnl=pnl, reason=reason))
        self.close()
        self.log(f'{self.p.name} SELL @ {price:.2f} | PnL: {pnl:+.2f} | {reason}')
        self.entry_price = None
        self.highest_since_entry = None

    def _exit_short(self, price, reason=''):
        pnl = self.entry_price - price
        self.total_pnl += pnl
        if pnl > 0:
            self.win_count += 1
        self.trades_log.append(dict(entry=self.entry_price, exit=price, pnl=pnl, reason=reason))
        self.close()
        self.log(f'{self.p.name} COVER @ {price:.2f} | PnL: {pnl:+.2f} | {reason}')
        self.entry_price = None
        self.lowest_since_entry = None

    def _check_exit_long(self, current_data, current_atr):
        """ATR动态止损: 多单"""
        self.highest_since_entry = max(self.highest_since_entry, current_data)
        drawdown = self.highest_since_entry - current_data
        loss = self.entry_price - current_data
        trail = self.p.trailing_atr * current_atr
        hard = self.p.hard_atr * current_atr
        if drawdown > trail:
            self._exit_long(self.data.open[0], f'TrailStop ({drawdown:.1f}>{trail:.1f})')
            return True
        if loss > hard:
            self._exit_long(self.data.open[0], f'HardStop ({loss:.1f}>{hard:.1f})')
            return True
        return False

    def _check_exit_short(self, current_data, current_atr):
        """ATR动态止损: 空单"""
        self.lowest_since_entry = min(self.lowest_since_entry, current_data)
        rally = current_data - self.lowest_since_entry
        loss = current_data - self.entry_price
        trail = self.p.trailing_atr * current_atr
        hard = self.p.hard_atr * current_atr
        if rally > trail:
            self._exit_short(self.data.open[0], f'TrailStop ({rally:.1f}>{trail:.1f})')
            return True
        if loss > hard:
            self._exit_short(self.data.open[0], f'HardStop ({loss:.1f}>{hard:.1f})')
            return True
        return False

    def notify_order(self, order):
        if order.status in [order.Completed, order.Rejected, order.Margin]:
            self._pending_order = None

    def stop(self):
        wr = self.win_count / self.trade_count if self.trade_count > 0 else 0
        print(f'\n  [{self.p.name}] 交易: {self.trade_count} | 胜率: {wr:.1%} | 总盈亏: ${self.total_pnl:.2f}')
        if self.trade_count > 0:
            wins = [t for t in self.trades_log if t["pnl"] > 0]
            losses = [t for t in self.trades_log if t["pnl"] <= 0]
            avg_w = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
            avg_l = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
            print(f'  盈利: {len(wins)}笔 均+${avg_w:.2f} | 亏损: {len(losses)}笔 均${avg_l:.2f}')


# ============================================================
# V1: KDJ + MACD 底背驰（原版信号，放宽止损）
# ============================================================
class V1_KDJ_MACD(BaseOptimizedStrategy):
    params = (
        ('name', 'V1-KDJ+MACD'),
        ('trailing_atr', 3.5),
        ('hard_atr', 2.5),
        ('oversold', 25),
        ('div_lookback', 15),
    )

    def next(self):
        if len(self) < 250:
            return

        # === +1 K线执行：上一根K线设置的pending信号 ===
        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f}')
            return  # 等下一根才继续检测新信号
        elif self._pending_order == 'sell' and not self.position:
            self._enter_short()
            self.log(f'{self.p.name} SHORT @ {self.entry_price:.2f}')
            return

        # === 持仓时：止损检查 ===
        if self.position:
            if self.position.size > 0:  # 多单
                if self._check_exit_long(self.data.close[-1], self.atr[-1]):
                    return
            else:  # 空单
                if self._check_exit_short(self.data.close[-1], self.atr[-1]):
                    return
            return  # 持仓中不检测新信号

        # === 空仓时：用 [-1] 数据检测入场信号 ===
        k_prev = self.stoch.percK[-1]
        k_prev2 = self.stoch.percK[-2]
        d_prev = self.stoch.percD[-1]
        close_prev = self.data.close[-1]
        trend_up = close_prev > self.sma200[-1]

        in_oversold = k_prev2 < self.p.oversold
        k_turning = (k_prev > k_prev2) and (k_prev > d_prev)
        divergence = SafeMACDDivergence.check_bottom_divergence(
            self.macd_hist, self.data.low, lookback=self.p.div_lookback
        )

        if trend_up and in_oversold and k_turning and divergence:
            self._pending_order = 'buy'


# ============================================================
# V2: KDJ + RSI（去MACD背离，加RSI<30过滤）
# ============================================================
class V2_KDJ_RSI(BaseOptimizedStrategy):
    params = (
        ('name', 'V2-KDJ+RSI'),
        ('trailing_atr', 3.0),
        ('hard_atr', 2.0),
        ('oversold', 30),
    )

    def next(self):
        if len(self) < 250:
            return

        # +1 K线入场
        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f} | RSI={self.rsi[-1]:.1f}')
            return

        # 止损
        if self.position:
            if self.position.size > 0:
                if self._check_exit_long(self.data.close[-1], self.atr[-1]):
                    return
            else:
                if self._check_exit_short(self.data.close[-1], self.atr[-1]):
                    return
            return

        # 入场信号（仅用[-1]数据）
        k_prev = self.stoch.percK[-1]
        k_prev2 = self.stoch.percK[-2]
        d_prev = self.stoch.percD[-1]
        close_prev = self.data.close[-1]
        trend_up = close_prev > self.sma200[-1]

        in_oversold = k_prev2 < self.p.oversold
        k_turning = (k_prev > k_prev2) and (k_prev > d_prev)
        rsi_oversold = self.rsi[-1] < 30  # RSI代替MACD背离

        if trend_up and in_oversold and k_turning and rsi_oversold:
            self._pending_order = 'buy'


# ============================================================
# V3: 双向交易（SMA200方向做多/做空）
# ============================================================
class V3_LongShort(BaseOptimizedStrategy):
    params = (
        ('name', 'V3-LongShort'),
        ('trailing_atr', 3.0),
        ('hard_atr', 2.0),
        ('oversold', 30),
        ('overbought', 70),
    )

    def next(self):
        if len(self) < 250:
            return

        # +1 K线入场
        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f}')
            return
        elif self._pending_order == 'sell' and not self.position:
            self._enter_short()
            self.log(f'{self.p.name} SHORT @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f}')
            return

        # 止损
        if self.position:
            if self.position.size > 0:
                if self._check_exit_long(self.data.close[-1], self.atr[-1]):
                    return
            else:
                if self._check_exit_short(self.data.close[-1], self.atr[-1]):
                    return
            return

        # 入场信号
        k_prev = self.stoch.percK[-1]
        k_prev2 = self.stoch.percK[-2]
        d_prev = self.stoch.percD[-1]
        close_prev = self.data.close[-1]
        rsi_val = self.rsi[-1]
        trend_up = close_prev > self.sma200[-1]

        if trend_up:
            # 多头：KDJ超卖 + 金叉 + RSI<30
            if (k_prev2 < self.p.oversold and
                k_prev > k_prev2 and k_prev > d_prev and
                rsi_val < 30):
                self._pending_order = 'buy'
        else:
            # 空头：KDJ超买 + 死叉 + RSI>70
            d_prev2 = self.stoch.percD[-2]
            if (k_prev2 > self.p.overbought and
                k_prev < k_prev2 and k_prev < d_prev and
                rsi_val > 70):
                self._pending_order = 'sell'


# ============================================================
# V4: 布林带 + KDJ + RSI（简化版，去MACD背离）
# ============================================================
class V4_Bollinger_KDJ(BaseOptimizedStrategy):
    params = (
        ('name', 'V4-Bollinger'),
        ('trailing_atr', 3.0),
        ('hard_atr', 2.0),
        ('bb_period', 20),
        ('bb_dev', 2.5),
        ('bias', 6.0),
        ('oversold', 30),
    )

    def __init__(self):
        super().__init__()
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )

    def next(self):
        if len(self) < 250:
            return

        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f} | RSI={self.rsi[-1]:.1f}')
            return

        if self.position:
            if self.position.size > 0:
                if self._check_exit_long(self.data.close[-1], self.atr[-1]):
                    return
            else:
                if self._check_exit_short(self.data.close[-1], self.atr[-1]):
                    return
            return

        k_prev = self.stoch.percK[-1]
        k_prev2 = self.stoch.percK[-2]
        d_prev = self.stoch.percD[-1]
        close_prev = self.data.close[-1]
        low_prev = self.data.low[-1]
        trend_up = close_prev > self.sma200[-1]

        bb_bot = self.bb.bot[-1]
        bias_pct = (close_prev - bb_bot) / bb_bot * 100 if bb_bot else 0
        near_lower = (low_prev <= bb_bot) and (abs(bias_pct) < self.p.bias)
        in_oversold = k_prev2 < self.p.oversold
        k_turning = (k_prev > k_prev2) and (k_prev > d_prev)
        rsi_ok = self.rsi[-1] < 35

        if trend_up and near_lower and in_oversold and k_turning and rsi_ok:
            self._pending_order = 'buy'


# ============================================================
# V5: 肯特纳通道 + KDJ + RSI（简化版，去MACD背离）
# ============================================================
class V5_Keltner_KDJ(BaseOptimizedStrategy):
    params = (
        ('name', 'V5-Keltner'),
        ('trailing_atr', 3.0),
        ('hard_atr', 2.0),
        ('ema_period', 20),
        ('kc_mult', 2.5),
        ('oversold', 30),
    )

    def __init__(self):
        super().__init__()
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.kc_bot = self.ema - self.atr * self.p.kc_mult

    def next(self):
        if len(self) < 250:
            return

        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f} | K={self.stoch.percK[-1]:.1f}')
            return

        if self.position:
            if self.position.size > 0:
                if self._check_exit_long(self.data.close[-1], self.atr[-1]):
                    return
            else:
                if self._check_exit_short(self.data.close[-1], self.atr[-1]):
                    return
            return

        k_prev = self.stoch.percK[-1]
        k_prev2 = self.stoch.percK[-2]
        d_prev = self.stoch.percD[-1]
        close_prev = self.data.close[-1]
        low_prev = self.data.low[-1]
        trend_up = close_prev > self.sma200[-1]

        near_lower = low_prev <= self.kc_bot[-1]
        in_oversold = k_prev2 < self.p.oversold
        k_turning = (k_prev > k_prev2) and (k_prev > d_prev)
        rsi_ok = self.rsi[-1] < 35

        if trend_up and near_lower and in_oversold and k_turning and rsi_ok:
            self._pending_order = 'buy'


# ============================================================
# V6: 终极混合版 — 多信号融合 + 双向 + 自适应ATR止损
# ============================================================
class V6_Hybrid(BaseOptimizedStrategy):
    params = (
        ('name', 'V6-Hybrid'),
        ('trailing_atr', 3.5),
        ('hard_atr', 3.0),
        ('oversold', 35),
        ('overbought', 65),
        ('div_lookback', 15),
    )

    def __init__(self):
        super().__init__()
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=20, devfactor=2.5
        )
        self.ema = bt.indicators.EMA(self.data.close, period=20)
        self.kc_bot = self.ema - self.atr * 2.5
        self.kc_top = self.ema + self.atr * 2.5

        # 信号计数器
        self.long_signals = 0
        self.short_signals = 0

    def next(self):
        if len(self) < 250:
            return

        # +1 K线入场
        if self._pending_order == 'buy' and not self.position:
            self._enter_long()
            self.log(f'{self.p.name} BUY @ {self.entry_price:.2f}')
            return
        elif self._pending_order == 'sell' and not self.position:
            self._enter_short()
            self.log(f'{self.p.name} SHORT @ {self.entry_price:.2f}')
            return

        # 止损
        if self.position:
            if self.position.size > 0:
                if self._check_exit_long(self.data.close[-1], self.atr_sma[-1]):
                    return
            else:
                if self._check_exit_short(self.data.close[-1], self.atr_sma[-1]):
                    return
            return

        close = self.data.close[-1]
        low = self.data.low[-1]
        high = self.data.high[-1]
        sma = self.sma200[-1]
        trend_up = close > sma

        k = self.stoch.percK[-1]
        k_prev = self.stoch.percK[-2]
        d = self.stoch.percD[-1]
        rsi_val = self.rsi[-1]
        atr_val = self.atr[-1]
        bb_bot = self.bb.bot[-1]

        # === 多头信号融合（逐层加分） ===
        long_score = 0
        long_detail = []

        # ① SMA200趋势
        if trend_up:
            long_score += 1
            long_detail.append('TREND+')

        # ② KDJ超卖
        if k < self.p.oversold or k_prev < self.p.oversold:
            long_score += 1
            long_detail.append('KDJ-OS')

        # ③ 触碰布林带下轨/肯特纳下轨
        if low <= bb_bot:
            long_score += 1
            long_detail.append('BB-BOT')
        if low <= self.kc_bot[-1]:
            long_score += 1
            long_detail.append('KC-BOT')

        # ④ MACD底背驰
        if SafeMACDDivergence.check_bottom_divergence(
                self.macd_hist, self.data.low, lookback=self.p.div_lookback):
            long_score += 2  # 背离权重更高
            long_detail.append('DIVERGENCE')

        # ⑤ RSI超卖
        if rsi_val < 30:
            long_score += 1
            long_detail.append('RSI-OS')

        # ⑥ ATR: 波动率低时更安全
        if atr_val < self.atr_sma[-1] * 1.2:
            long_score += 1
            long_detail.append('LOW-VOL')

        # 多头需要至少3分
        if long_score >= 3 and not self.position:
            self._pending_order = 'buy'

        # === 空头信号 ===
        if not trend_up:  # SMA200空头才考虑做空
            short_score = 0
            short_detail = []

            if k > self.p.overbought:
                short_score += 1
                short_detail.append('KDJ-OB')

            if high >= self.kc_top[-1]:
                short_score += 1
                short_detail.append('KC-TOP')

            if SafeMACDDivergence.check_top_divergence(
                    self.macd_hist, self.data.high, lookback=self.p.div_lookback):
                short_score += 2
                short_detail.append('TOP-DIV')

            if rsi_val > 70:
                short_score += 1
                short_detail.append('RSI-OB')

            if short_score >= 3:
                self._pending_order = 'sell'


# ============================================================
# 统一回测运行器
# ============================================================
def run_backtest(strategy_class, strategy_name, data_path, cash=10000.0,
                 fromdate=datetime(2024, 5, 1), todate=datetime(2026, 6, 5)):
    print(f'\n{"="*60}')
    print(f'  [{strategy_name}]')
    print(f'  {"="*56}')

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_class)
    cerebro.broker.setcash(cash)
    # XAUUSD 手续费模型: 每标准手(100oz)双边约$2-3, 取中值$2.50
    # backtrader 默认 size=1(1oz), 费率 = $0.0125/$2300 ≈ 0.0000054
    cerebro.broker.setcommission(commission=XAUUSD_COMMISSION_RATE)

    # 滑点: 0.1% 单边 → 约$2.3/手（金价2300时），双边$4.6
    cerebro.broker.set_slippage_perc(0.001)

    data = btfeeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d %H:%M:%S',
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
        fromdate=fromdate,
        todate=todate,
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
    )
    cerebro.adddata(data)

    print(f'  资金: ${cash:.2f} | 数据: {os.path.basename(data_path)}')
    print(f'  手续费: {XAUUSD_COMMISSION_RATE:.8f} (≈$2.50/0.1手双边) | 滑点: 0.1% 单边 | +1 K线入场')
    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - cash) / cash * 100
    trade_count = strat.trade_count

    # 估算手续费总额: 每笔双边约$2.50 (按 size=1 的 0.025/oz 比例)
    est_commission_total = trade_count * 0.025  # size=1, 双边 $0.025/笔
    gross_pnl = strat.total_pnl
    net_pnl = final_value - cash

    print(f'\n  --- {strategy_name} ---')
    print(f'  初始: ${cash:,.2f} → 最终: ${final_value:,.2f}')
    print(f'  收益率: {total_return:+.2f}%')
    print(f'  交易: {trade_count} | 胜率: {strat.win_count/trade_count*100:.1f}%' if trade_count else '  N/A')
    print(f'  ⚠️  手续费影响: ~${est_commission_total:.2f} (估算) | 毛PnL: ${gross_pnl:+.2f} | 净PnL: ${net_pnl:+.2f}')

    return {
        'strategy': strategy_name,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': trade_count,
        'win_count': strat.win_count,
        'total_pnl': strat.total_pnl,
        'commission_rate': XAUUSD_COMMISSION_RATE,
        'est_commission_total': est_commission_total,
    }


def main():
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "XAUUSD_H1_merged.csv")
    if not os.path.exists(data_path):
        alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "..", "xauusd-dev", "data", "XAUUSD_H1_merged.csv")
        if os.path.exists(alt):
            data_path = alt
        else:
            print("错误: 找不到数据文件")
            sys.exit(1)

    lines = sum(1 for _ in open(data_path)) - 1
    print(f'XAUUSD H1 多策略优化回测 v2.0')
    print(f'数据: {data_path} ({lines} 根K线)')
    print(f'模型: 信号→+1K线(open)入场 + 0.1%滑点 + ATR动态止损')

    strategies = [
        (V1_KDJ_MACD,  "V1-KDJ+MACD(宽止损)"),
        (V2_KDJ_RSI,   "V2-KDJ+RSI(无背离)"),
        (V3_LongShort, "V3-双向交易"),
        (V4_Bollinger_KDJ, "V4-布林带简化版"),
        (V5_Keltner_KDJ, "V5-肯特纳简化版"),
        (V6_Hybrid,    "V6-终极混合版"),
    ]

    all_results = []
    for cls, name in strategies:
        result = run_backtest(cls, name, data_path)
        all_results.append(result)

    # 对比汇总
    print(f'\n\n{"="*68}')
    print(f'  {"多策略优化对比汇总":^62}')
    print(f'  {"="*64}')
    hdr = f'  {"策略":<20} {"收益率":>10} {"交易":>6} {"胜率":>8} {"总盈亏":>10}  评级'
    print(hdr)
    print(f'  {"-"*62}')

    # 按总盈亏排序
    all_results.sort(key=lambda r: r['total_pnl'], reverse=True)

    for r in all_results:
        wr = r['win_count']/r['trade_count']*100 if r['trade_count'] else 0
        pnl = r['total_pnl']
        if pnl > 50:
            rank = '[***]'
        elif pnl > 0:
            rank = '[**]'
        elif pnl > -50:
            rank = '[*]'
        else:
            rank = '   '
        print(f'  {r["strategy"]:<20} {r["total_return"]:>+9.2f}% {r["trade_count"]:>6} {wr:>7.1f}% {r["total_pnl"]:>+10.2f}  {rank}')

    print(f'  {"="*62}')
    print(f'  [!] 所有策略含 +1 K线入场延迟 + 0.1%单边滑点')
    print(f'  [!] 手续费: {XAUUSD_COMMISSION_RATE:.8f} (≈$2.50/0.1手双边)')
    print(f'  [!] 评级: [***]>$50  [**]>$0  [*]>-$50')
    print()

    # 落盘结果 — JSON + CSV
    save_results(all_results, data_path, lines, XAUUSD_COMMISSION_RATE)


def save_results(all_results, data_path, line_count, commission_rate):
    """将回测结果落盘为 JSON 和 CSV，确保可复现"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)

    # JSON: 完整结果 + 元数据
    json_path = os.path.join(out_dir, f"backtest_{ts}.json")
    payload = {
        "timestamp": datetime.now().isoformat(),
        "data_file": data_path,
        "candle_count": line_count,
        "commission_rate": commission_rate,
        "commission_note": "XAUUSD 每标准手(100oz)双边约$2.50",
        "slippage_perc": 0.001,
        "entry_delay": "+1K线",
        "strategies": all_results,
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'  📄 JSON 结果已保存: {json_path}')

    # CSV: 策略对比表
    csv_path = os.path.join(out_dir, f"backtest_{ts}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['策略', '收益率%', '交易数', '胜场', '总盈亏', '手续费率', '估算手续费', '数据文件', 'K线数'])
        for r in sorted(all_results, key=lambda x: -x['total_pnl']):
            wr = r['win_count'] / r['trade_count'] * 100 if r['trade_count'] else 0
            w.writerow([
                r['strategy'], f"{r['total_return']:.2f}", r['trade_count'], r['win_count'],
                f"{r['total_pnl']:.2f}", f"{r.get('commission_rate', 0):.8f}",
                f"{r.get('est_commission_total', 0):.2f}",
                os.path.basename(data_path), line_count,
            ])
    print(f'  📄 CSV 结果已保存: {csv_path}')


if __name__ == "__main__":
    main()
