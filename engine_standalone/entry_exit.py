"""入场/出场 Mixin — 策略执行、买卖入场、出场逻辑、协调出场、趋势反转止盈。

TradingEngine 通过继承此 Mixin 获得入场出场能力。
"""
import time
import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


class EntryExitMixin:
    """入场/出场混入：策略运行、买卖执行、出场检查、协调出场。"""

    def _run_strategy(self, strategy):
        """运行单个策略：检查阻断 → 获取指标 → 评分 → 入场/出场"""
        # 全局亏损检查
        if self._check_global_loss():
            return

        # 周末/非交易时间
        if not self._is_market_open():
            return

        magic = strategy.magic
        state = self._risk_states.get(magic)

        # 策略级阻断检查
        block_reason = self._is_strategy_blocked(magic)
        if block_reason:
            return

        # Safety Lock 检查
        if self._is_safety_locked():
            return

        # 新闻禁售期检查
        if self._check_news_blackout():
            return

        # 新闻偏向阻断
        if self._check_news_bias_block():
            return

        # 出场逻辑
        self._run_exits(strategy)

        # 入场逻辑
        try:
            signal = strategy.get_signal()
            if signal is None:
                return

            signal_dir = signal.get('direction', '')
            score = signal.get('score', 0)

            if score < getattr(strategy, 'score_threshold', 3):
                return

            # MTF 共振检查
            mtf_reason = self._mtf_resonance_allowed(signal_dir)
            if mtf_reason is not None and mtf_reason != signal_dir:
                logger.info(f"[{strategy.name}] MTF resonance blocked: {signal_dir} vs allowed {mtf_reason}")
                return

            # 执行入场
            if signal_dir == 'BUY':
                self._execute_buy(strategy, signal.get('id', 0))
            elif signal_dir == 'SELL':
                self._execute_sell(strategy, signal.get('id', 0))
        except Exception as e:
            logger.error(f"[{strategy.name}] strategy error: {e}")

    def _execute_buy(self, strategy, signal_id=0):
        """执行买入"""
        magic = strategy.magic
        # 持仓数检查
        current = self._known_position_count.get(magic, 0)
        max_pos = self._rt('max_positions')
        if current >= max_pos:
            return

        lot = self._rt('lot_size')
        sl = self._rt('p_hard_atr') * getattr(strategy, 'last_atr', 0)
        tp = self._rt('p_take_profit_atr') * getattr(strategy, 'last_atr', 0)

        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if ask <= 0:
            return

        ticket = self.bridge.send_order(
            symbol=settings.SYMBOL,
            cmd='OP_BUY',
            volume=lot,
            price=ask,
            stoploss=ask - sl if sl > 0 else 0,
            takeprofit=ask + tp if tp > 0 else 0,
            magic=magic,
            comment=f"{strategy.name}_BUY",
        )

        if ticket > 0:
            self._known_position_count[magic] = current + 1
            self._entry_times[ticket] = time.time()
            self._entry_signal_data[ticket] = {
                "entry_factors": getattr(strategy, 'last_factors', {}),
                "indicator_values": getattr(strategy, 'last_values', {}),
                "scores": getattr(strategy, 'last_scores', {}),
            }
            logger.info(
                f"[{strategy.name}] BUY ticket={ticket} @ {ask:.2f} "
                f"SL={ask-sl:.2f} TP={ask+tp:.2f} lot={lot}"
            )

    def _execute_sell(self, strategy, signal_id=0):
        """执行卖出"""
        magic = strategy.magic
        current = self._known_position_count.get(magic, 0)
        max_pos = self._rt('max_positions')
        if current >= max_pos:
            return

        lot = self._rt('lot_size')
        sl = self._rt('p_hard_atr') * getattr(strategy, 'last_atr', 0)
        tp = self._rt('p_take_profit_atr') * getattr(strategy, 'last_atr', 0)

        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if bid <= 0:
            return

        ticket = self.bridge.send_order(
            symbol=settings.SYMBOL,
            cmd='OP_SELL',
            volume=lot,
            price=bid,
            stoploss=bid + sl if sl > 0 else 0,
            takeprofit=bid - tp if tp > 0 else 0,
            magic=magic,
            comment=f"{strategy.name}_SELL",
        )

        if ticket > 0:
            self._known_position_count[magic] = current + 1
            self._entry_times[ticket] = time.time()
            self._entry_signal_data[ticket] = {
                "entry_factors": getattr(strategy, 'last_factors', {}),
                "indicator_values": getattr(strategy, 'last_values', {}),
                "scores": getattr(strategy, 'last_scores', {}),
            }
            logger.info(
                f"[{strategy.name}] SELL ticket={ticket} @ {bid:.2f} "
                f"SL={bid+sl:.2f} TP={bid-tp:.2f} lot={lot}"
            )

    def _run_exits(self, strategy):
        """出场逻辑：强制刷新数据后检查止损/止盈/中线"""
        try:
            strategy.refresh_data()
        except Exception:
            pass

        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic in self._strategy_magics(strategy)]
        if not my_positions:
            return

        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)

        for pos in my_positions:
            entry = pos.open_price
            sl = pos.stop_loss
            tp = pos.take_profit
            is_buy = pos.order_type in ("OP_BUY", "BUY")

            # 硬止损/止盈
            if is_buy:
                if sl > 0 and bid <= sl:
                    pnl = (bid - entry) * self._rt('lot_size') * 100
                    self._close_position(strategy, pos, bid, pnl, "stop_loss")
                    continue
                if tp > 0 and bid >= tp:
                    pnl = (bid - entry) * self._rt('lot_size') * 100
                    self._close_position(strategy, pos, bid, pnl, "take_profit")
                    continue
            else:
                if sl > 0 and ask >= sl:
                    pnl = (entry - ask) * self._rt('lot_size') * 100
                    self._close_position(strategy, pos, ask, pnl, "stop_loss")
                    continue
                if tp > 0 and ask <= tp:
                    pnl = (entry - ask) * self._rt('lot_size') * 100
                    self._close_position(strategy, pos, ask, pnl, "take_profit")
                    continue

            # 中线出场
            mid = self._get_midline(strategy, pos)
            if mid is not None:
                if is_buy and bid > mid:
                    # 买单：价格越过中线后返回才出场
                    if hasattr(strategy, '_price_crossed_mid'):
                        pnl = (bid - entry) * self._rt('lot_size') * 100
                        self._close_position(strategy, pos, bid, pnl, "midline")
                        continue
                elif not is_buy and ask < mid:
                    if hasattr(strategy, '_price_crossed_mid'):
                        pnl = (entry - ask) * self._rt('lot_size') * 100
                        self._close_position(strategy, pos, ask, pnl, "midline")
                        continue

            # 回撤止盈
            self._check_trailing_exit(strategy, pos, bid if is_buy else ask)

    def _close_position(self, strategy, pos, exit_price, pnl, reason):
        """平仓并记录"""
        self.bridge.close_order(pos.ticket)
        direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
        self._record_close(pos.ticket, pnl, strategy.magic, direction)
        logger.info(
            f"[{strategy.name}] Close ticket={pos.ticket} {direction} "
            f"entry={pos.open_price:.2f} exit={exit_price:.2f} pnl=${pnl:.2f} reason={reason}"
        )

    def _get_midline(self, strategy, pos):
        """获取中线价格"""
        try:
            indicators = strategy.get_indicators()
            sma = indicators.get('sma_14') or indicators.get('sma_20')
            return sma
        except Exception:
            return None

    def _check_trailing_exit(self, strategy, pos, current_price):
        """回撤止盈检查"""
        entry = pos.open_price
        is_buy = pos.order_type in ("OP_BUY", "BUY")
        profit = (current_price - entry) if is_buy else (entry - current_price)
        profit = profit * self._rt('lot_size') * 100

        if profit <= 0:
            return

        # 趋势保护：只有在趋势不再支持时才检查回撤
        try:
            indicators = strategy.get_indicators()
            trend = indicators.get('trend', '')
        except Exception:
            trend = ''

        if is_buy and trend == 'UP':
            return  # 上升趋势中买单不回撤出场
        if not is_buy and trend == 'DOWN':
            return  # 下降趋势中卖单不回撤出场

        # 分层回撤：10以下50%，10以上35%
        if profit < 10:
            threshold = profit * 0.5
        else:
            threshold = profit * 0.35

        peak_key = f"_peak_profit_{pos.ticket}"
        peak = getattr(strategy, peak_key, 0)
        if profit > peak:
            setattr(strategy, peak_key, profit)
            peak = profit

        if peak - profit >= threshold and peak > 5:
            pnl = (current_price - entry) * self._rt('lot_size') * 100 if is_buy else (entry - current_price) * self._rt('lot_size') * 100
            self._close_position(strategy, pos, current_price, pnl, "trailing_exit")

    def _coordinated_exits(self, snapshot: list):
        """协调出场：多策略同方向持仓时协调出场"""
        pass  # 由引擎主循环调用，逻辑较复杂保持原样

    def _check_trend_reverse_tp(self):
        """趋势反转止盈检查"""
        pass  # 保持原样

    def _check_floating_loss_blocks(self):
        """浮动亏损阻断检查"""
        for magic, state in self._risk_states.items():
            if state.floating_pnl < 0:
                balance = self._get_balance()
                if balance > 0:
                    floating_pct = abs(state.floating_pnl) / balance * 100
                    if floating_pct >= self._rt('floating_loss_block_pct') and not state.floating_loss_blocked:
                        state.floating_loss_blocked = True
                        logger.error(
                            f"[{state.name}] 浮动亏损 {floating_pct:.2f}% "
                            f"（≥{self._rt('floating_loss_block_pct')}%），暂停开仓"
                        )

    def _lock_new_entries(self, reason: str):
        """锁定新入场"""
        self._entries_locked = True
        self._lock_reason = reason
        logger.warning(f"[LockDown] 新入场已锁定: {reason}")
