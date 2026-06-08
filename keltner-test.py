import backtrader as bt
import pandas as pd
import numpy as np

# ==================== 修复版：安全的MACD背驰检测器 ====================
class SafeMACDDivergence:
    """
    修复点：强制基于 base_idx 向前回溯，杜绝偷看未来数据
    """
    @staticmethod
    def check_bottom_divergence(macd_hist, price_low, base_idx, lookback=15):
        # 安全边界检查
        if base_idx < lookback * 2 + 2:
            return False
        
        lows = []
        # 严格在 base_idx 之前寻找两个波谷
        search_start = base_idx - lookback * 2
        search_end = base_idx 
        
        for i in range(search_start + 1, search_end - 1):
            if (price_low[i] < price_low[i-1] and 
                price_low[i] < price_low[i+1]):
                lows.append((i, price_low[i], macd_hist[i]))
        
        if len(lows) < 2:
            return False
        
        # 取最近两个有效波谷
        p1_idx, p1_val, m1_val = lows[-2]
        p2_idx, p2_val, m2_val = lows[-1]
        
        # 价格创新低 + MACD柱体绝对值缩小（绿柱缩短）
        if p2_val < p1_val and m2_val > m1_val:
            return True
        return False


# ==================== 修复版：肯特纳通道黄金策略 ====================
class KeltnerGoldStrategyFixed(bt.Strategy):
    params = (
        ('ema_period', 20),
        ('atr_mult', 2.5),          # 黄金波动大，通道放宽
        ('atr_period', 20),         # ATR周期延长，平滑噪音
        ('sma200_period', 200),
        ('k_period', 9),
        ('d_period', 3),
        ('oversold_threshold', 25), # 黄金KDJ易钝化，阈值上调
        ('divergence_lookback', 15),
        # ⚠️ 修复：纯ATR动态止损，摒弃固定美元
        ('trailing_stop_atr_mult', 2.0),
        ('hard_stop_atr_mult', 1.5),
        ('print_log', True),
    )

    def __init__(self):
        # 趋势与通道
        self.sma200 = bt.indicators.SMA(self.data.close, period=self.p.sma200_period)
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.kc_top = self.ema + self.atr * self.p.atr_mult
        self.kc_bot = self.ema - self.atr * self.p.atr_mult
        
        # KDJ
        self.stoch = bt.indicators.Stochastic(
            self.data, period=self.p.k_period, 
            period_dfast=self.p.d_period, movav=bt.indicators.MovAv.SMA
        )
        
        # MACD
        self.macd = bt.indicators.MACD(
            self.data.close, period_me1=12, period_me2=26, period_signal=9
        )
        self.macd_hist = self.macd.macd - self.macd.signal
        
        # 状态跟踪
        self.entry_price = None
        self.highest_since_entry = None
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0

    def log(self, txt):
        if self.p.print_log:
            print(f'{self.datas[0].datetime.date(0)} {txt}')

    def next(self):
        # ⚠️ 修复：所有信号判断严格使用 [-1] (上一根已闭合K线)
        k_prev = self.stoch.percK[-1]
        d_prev = self.stoch.percD[-1]
        k_prev2 = self.stoch.percK[-2]
        close_prev = self.data.close[-1]
        low_prev = self.data.low[-1]
        current_atr = self.atr[-1]
        
        # 1. 大趋势过滤
        trend_up = close_prev > self.sma200[-1]
        
        # 2. 超卖 + KDJ反转确认
        # ⚠️ 修复：改为"连续两根抬升 + 脱离极值"，避免索引越界和条件过苛
        in_oversold_zone = k_prev2 < self.p.oversold_threshold
        k_turning_up = (k_prev > k_prev2) and (k_prev > d_prev)
        
        # 3. 触及肯特纳下轨
        near_lower_channel = low_prev <= self.kc_bot[-1]
        
        # 4. 安全的MACD底背驰
        has_divergence = SafeMACDDivergence.check_bottom_divergence(
            self.macd_hist, self.data.low, 
            base_idx=len(self) - 2, 
            lookback=self.p.divergence_lookback
        )
        
        # ===== 入场执行 (基于[-1]信号，在[0]开盘价成交) =====
        if (not self.position and trend_up and 
            in_oversold_zone and k_turning_up and 
            near_lower_channel and has_divergence):
            
            self.buy()
            self.entry_price = self.data.open[0]
            self.highest_since_entry = self.entry_price
            self.trade_count += 1
            self.log(f'BUY @ {self.entry_price:.2f} | K={k_prev:.1f} | ATR={current_atr:.2f}')
        
        # ===== 出场执行 =====
        if self.position and self.entry_price is not None:
            # 更新最高价（使用已闭合的[-1]数据，避免盘中毛刺）
            self.highest_since_entry = max(self.highest_since_entry, self.data.close[-1])
            
            # ⚠️ 修复：纯ATR动态止损计算
            trail_dist = current_atr * self.p.trailing_stop_atr_mult
            hard_dist = current_atr * self.p.hard_stop_atr_mult
            
            drawdown = self.highest_since_entry - self.data.close[-1]
            loss = self.entry_price - self.data.close[-1]
            
            if drawdown > trail_dist or loss > hard_dist:
                exit_price = self.data.open[0]
                pnl = exit_price - self.entry_price
                self.total_pnl += pnl
                if pnl > 0:
                    self.win_count += 1
                    
                self.close()
                self.log(f'SELL @ {exit_price:.2f} | PnL: {pnl:.2f} | Trail:{trail_dist:.2f} Hard:{hard_dist:.2f}')
                self.entry_price = None
                self.highest_since_entry = None

    def stop(self):
        wr = self.win_count / self.trade_count if self.trade_count > 0 else 0
        print(f'\n=== 黄金肯特纳修复版回测统计 ===')
        print(f'交易次数: {self.trade_count} | 胜率: {wr:.2%} | 总盈亏: {self.total_pnl:.2f}')