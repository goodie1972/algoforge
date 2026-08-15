"""仓位管理 Mixin — 仓位记录、风控阻断检查、强平逻辑。

TradingEngine 通过继承此 Mixin 获得仓位管理能力。
所有方法依赖宿主类的 self.bridge / self._risk_states / self._rt 等属性。
"""
import time
import json
import logging
from datetime import datetime
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


class PositionMgrMixin:
    """仓位管理混入：平仓记录、全局亏损检查、策略阻断检查、强制平仓。"""

    def _record_close(self, ticket: int | str, pnl: float, magic: int, direction: str = ""):
        """记录平仓：更新已实现盈亏 + 快速出场检测（legacy magic 自动映射到主策略）"""
        for s in self.strategies:
            if magic in getattr(s, 'legacy_magics', []):
                magic = s.magic
                break
        state = self._risk_states.get(magic)
        if state is None:
            return

        state.realized_pnl += pnl
        self._entry_times.pop(ticket, None)
        self._known_position_count[magic] = max(0, self._known_position_count.get(magic, 0) - 1)

        now = time.time()
        state.exit_timestamps.append(now)
        while state.exit_timestamps and state.exit_timestamps[0] < now - self._rt('rapid_exit_window_seconds'):
            state.exit_timestamps.popleft()

        if len(state.exit_timestamps) >= self._rt('max_rapid_exits'):
            state.rapid_exit_blocked = True
            state.rapid_exit_blocked_at = now
            logger.error(
                f"[{state.name}] 快速出场阻断: {self._rt('rapid_exit_window_seconds')//60}min 内 "
                f"{len(state.exit_timestamps)} 次平仓（上限 {self._rt('max_rapid_exits')}），"
                f"冷却 {self._rt('rapid_exit_cooldown_seconds')//60}min"
            )

        if pnl < 0:
            state.consecutive_losses += 1
            logger.info(
                f"[{state.name}] 连续亏损 {state.consecutive_losses} 次 "
                f"（上限 {self._rt('max_consecutive_losses')}）"
            )
            if state.consecutive_losses >= self._rt('max_consecutive_losses') and not state.consecutive_loss_blocked:
                state.consecutive_loss_blocked = True
                state.consecutive_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 连续亏损 {state.consecutive_losses} 次，"
                    f"冷却 {self._rt('consecutive_loss_cooldown_hours')}h"
                )
        elif pnl > 0:
            state.consecutive_losses = 0
            if direction:
                if magic not in self._profit_exit_cooldown:
                    self._profit_exit_cooldown[magic] = {}
                self._profit_exit_cooldown[magic][direction] = time.time()
                logger.info(
                    f"[TPCooldown] {state.name} {direction} 盈利 ${pnl:.2f}，"
                    f"{self._rt('profit_exit_cooldown_hours')}h 内不再开同向 orders"
                )

        if state.realized_pnl <= -self._rt('per_strategy_realized_loss_amount') and not state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = True
            state.realized_loss_amount_blocked_at = now
            logger.error(
                f"[{state.name}] 已实现亏损 ${abs(state.realized_pnl):.2f} "
                f"（≥${self._rt('per_strategy_realized_loss_amount')}），"
                f"冷却 {self._rt('per_strategy_loss_block_hours')}h"
            )
        if state.realized_pnl > 0 and state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = False
            logger.info(f"[{state.name}] Loss recovered, cooling lifted")

        balance = self._get_balance()
        if balance > 0:
            loss_pct = abs(state.realized_pnl) / balance * 100
            threshold = self._rt('per_strategy_realized_loss_pct')
            if state.realized_pnl < 0 and loss_pct >= threshold and not state.realized_loss_blocked:
                state.realized_loss_blocked = True
                state.realized_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 已实现亏损 {loss_pct:.2f}%（≥{threshold}%），"
                    f"该策略暂停开仓 {self._rt('per_strategy_loss_block_hours')}h"
                )

    def _check_global_loss(self) -> bool:
        """账户级硬止损：balance-based，12% 触发全局停开仓"""
        now = time.time()
        if now - self._last_balance_check < 300:
            return self._global_loss_blocked
        self._last_balance_check = now

        balance = self._get_balance()
        if balance <= 0:
            self._global_loss_blocked = True
            return True

        loss_pct = (self._daily_start_balance - balance) / self._daily_start_balance * 100 if self._daily_start_balance else 0
        if loss_pct >= self._rt('max_daily_loss_pct'):
            if not self._global_loss_blocked:
                logger.error(
                    f"[GlobalHardStop] 已实现亏损 {loss_pct:.2f}% "
                    f"（上限 {self._rt('max_daily_loss_pct')}%），全策略停开仓"
                )
            self._global_loss_blocked = True
            return True

        if self._global_loss_blocked:
            logger.info(f"[GlobalHardStop] Loss recovered to {loss_pct:.2f}%，trading resumed")
        self._global_loss_blocked = False
        return False

    def _is_strategy_blocked(self, magic: int) -> Optional[str]:
        """检查策略是否被阻断，返回阻断原因或 None"""
        state = self._risk_states.get(magic)
        if state is None:
            return None

        now = time.time()

        if state.realized_loss_blocked:
            elapsed = now - state.realized_loss_blocked_at
            if elapsed >= self._rt('per_strategy_loss_block_hours') * 3600:
                state.realized_loss_blocked = False
                logger.info(f"[{state.name}] 已实现亏损阻断到期（{elapsed/3600:.1f}h），恢复开仓")
            else:
                remain_h = (self._rt('per_strategy_loss_block_hours') * 3600 - elapsed) / 3600
                return f"已实现亏损阻断，剩余 {remain_h:.1f}h"

        if state.floating_loss_blocked:
            balance = self._get_balance()
            if balance > 0:
                floating_pct = abs(state.floating_pnl) / balance * 100
                if floating_pct < self._rt('floating_loss_block_pct'):
                    state.floating_loss_blocked = False
                    logger.info(f"[{state.name}] 浮动亏损已降至 {floating_pct:.2f}%，恢复开仓")
                else:
                    return f"浮动亏损阻断（{floating_pct:.2f}%）"

        if state.realized_loss_amount_blocked:
            elapsed = now - state.realized_loss_amount_blocked_at
            if elapsed >= self._rt('per_strategy_loss_block_hours') * 3600:
                state.realized_loss_amount_blocked = False
                logger.info(f"[{state.name}] 绝对亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓")
            else:
                remain_h = (self._rt('per_strategy_loss_block_hours') * 3600 - elapsed) / 3600
                return f"绝对亏损冷却，剩余 {remain_h:.1f}h"

        if state.consecutive_loss_blocked:
            elapsed = now - state.consecutive_loss_blocked_at
            if elapsed >= self._rt('consecutive_loss_cooldown_hours') * 3600:
                state.consecutive_loss_blocked = False
                logger.info(f"[{state.name}] 连续亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓")
            else:
                remain_h = (self._rt('consecutive_loss_cooldown_hours') * 3600 - elapsed) / 3600
                return f"连续亏损冷却，剩余 {remain_h:.1f}h"

        if state.rapid_exit_blocked:
            elapsed = now - state.rapid_exit_blocked_at
            if elapsed >= self._rt('rapid_exit_cooldown_seconds'):
                state.rapid_exit_blocked = False
                logger.info(f"[{state.name}] 快速出场冷却到期（{elapsed/60:.0f}min），恢复开仓")
            else:
                remain_m = (self._rt('rapid_exit_cooldown_seconds') - elapsed) / 60
                return f"快速出场阻断，剩余 {remain_m:.0f}min"

        return None

    def _close_strategy_positions(self, strategy, reason: str):
        """平掉某个策略的所有持仓（含 legacy magic），记录指定出场原因"""
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic in self._strategy_magics(strategy)]
        if not my_positions:
            return
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        for pos in my_positions:
            entry = pos.open_price
            if pos.order_type in ("OP_BUY", "BUY"):
                pnl = (bid - entry) * self._rt('lot_size') * 100
                exit_price = bid
            else:
                pnl = (entry - ask) * self._rt('lot_size') * 100
                exit_price = ask
            logger.warning(
                f"[NewsRisk] 强制平仓 Ticket={pos.ticket} {pos.order_type} "
                f"入场={entry:.2f} 盈亏=${pnl:.2f} 原因={reason}"
            )
            self.bridge.close_order(pos.ticket)

            broker_open = 0
            broker_close = 0
            try:
                history = self.bridge.get_order_history(settings.SYMBOL)
                for o in history:
                    if o["ticket"] == pos.ticket:
                        broker_open = o["open_time"]
                        broker_close = o["close_time"]
                        break
            except Exception:
                pass

            direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
            self._record_close(pos.ticket, pnl, strategy.magic, direction)

            if broker_close > 0 and broker_open > 0:
                open_dt = self._mt4_to_local(broker_open)
                close_dt = self._mt4_to_local(broker_close)
                open_time_str = open_dt.strftime('%Y-%m-%d %H:%M:%S')
                close_time_str = close_dt.strftime('%Y-%m-%d %H:%M:%S')
                hold_sec = int(broker_close - broker_open)
            else:
                close_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                entry_ts = self._entry_times.get(pos.ticket, 0)
                if entry_ts > 0:
                    from config.settings import LOCAL_TZ
                    open_time_str = datetime.fromtimestamp(entry_ts, tz=LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    hold_sec = int(time.time() - entry_ts)
                else:
                    open_time_str, open_ts = self._pos_open_time(pos)
                    hold_sec = max(0, int(time.time() - open_ts)) if open_ts > 0 else 0

            entry_data = self._entry_signal_data.pop(pos.ticket, {})
            snapshot = {
                "entry_factors": entry_data.get("entry_factors", {}),
                "indicator_values": entry_data.get("indicator_values", {}),
                "scores": entry_data.get("scores", {}),
                "exit_detail": {"exit_type": reason},
            }

            record = dict(
                ticket=pos.ticket, symbol=pos.symbol,
                order_type=pos.order_type, volume=pos.volume,
                entry_price=entry, exit_price=exit_price,
                pnl=round(pnl, 2), stop_loss=pos.stop_loss,
                take_profit=pos.take_profit, swap=pos.swap,
                commission=pos.commission, magic=pos.magic,
                strategy=strategy.name, open_time=open_time_str,
                close_time=close_time_str, hold_seconds=hold_sec,
                exit_reason=reason,
                indicator_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            self._closed_trades.append(record)
            self._trim_closed_trades()
            if hasattr(self, 'supervisor'):
                self.supervisor.on_trade_close(record, reason)
            try:
                with open(self._trades_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass
            try:
                from data import database as db
                db.insert_trade(record)
            except Exception:
                pass

    def _update_floating_pnl(self):
        """更新所有策略的浮动盈亏（含 legacy magic 持仓）"""
        all_positions = self.bridge.get_positions(settings.SYMBOL)
        for state in self._risk_states.values():
            magics = {state.magic}
            for s in self.strategies:
                if s.magic == state.magic:
                    magics.update(self._strategy_magics(s))
                    break
            my_pos = [p for p in all_positions if p.magic in magics]
            state.floating_pnl = sum(p.profit for p in my_pos)
