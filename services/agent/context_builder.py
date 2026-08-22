"""
上下文构建器 — 收集实时交易上下文（引擎/账户/持仓/价格/指标/信号/成交/新闻/策略）
阶段1 增强: K线摘要 + 信号流水 + 近期成交 + 策略逻辑
"""
import logging
from datetime import datetime
from typing import Optional

from config.settings import LOCAL_TZ

logger = logging.getLogger(__name__)


class ContextBuilder:
    def __init__(self, engine_runner=None):
        self._engine = engine_runner
        self._sections = {}  # name -> enabled

    def set_engine(self, engine_runner):
        self._engine = engine_runner

    def _get_engine(self):
        """懒加载 engine_runner"""
        if self._engine is None:
            try:
                from dashboard.backend.engine_runner import EngineRunner
                self._engine = EngineRunner.get_instance()
            except Exception:
                pass
        return self._engine

    # ── 各上下文段 ──

    def _section_engine(self) -> list[str]:
        lines = []
        engine = self._get_engine()
        if not engine:
            return lines
        try:
            status = self._engine.get_status()
            lines.append(f"引擎: {status.get('status', '?')} (已运行 {status.get('uptime_seconds', 0):.0f}s), 桥接: {'已连接' if status.get('bridge_connected') else '未连接'}")
        except Exception:
            pass
        try:
            acct = self._engine._cached_account
            if acct:
                lines.append(f"账户: 余额 ${acct.get('balance', 0):.2f} | 净值 ${acct.get('equity', 0):.2f} | 浮盈 ${acct.get('floating_pnl', 0):+.2f} | 可用 ${acct.get('free_margin', 0):.2f}")
        except Exception:
            pass
        return lines

    def _section_positions(self) -> list[str]:
        engine = self._get_engine()
        lines = []
        if not self._engine:
            return lines
        try:
            positions = self._engine._fresh_positions()
            if positions:
                lines.append("持仓:")
                for p in positions[:5]:
                    d = p.get('type', p.get('order_type', '?'))
                    v = p.get('volume', 0)
                    e = p.get('open_price', p.get('entry_price', 0))
                    pf = p.get('profit', p.get('floating_pnl', 0))
                    sl = p.get('stop_loss', 0)
                    tp = p.get('take_profit', 0)
                    t = p.get('ticket', '?')
                    lines.append(f"  - #{t} {d} {v} XAUUSD @{e} 浮盈${pf:+.2f} 止损{sl} 止盈{tp}")
            else:
                lines.append("持仓: 无")
        except Exception:
            pass
        return lines

    def _section_price(self) -> list[str]:
        engine = self._get_engine()
        lines = []
        if not self._engine:
            return lines
        try:
            price = self._engine._cached_price
            if price:
                bid = price.get('bid', 0)
                ask = price.get('ask', 0)
                spread = round(ask - bid, 2)
                lines.append(f"价格: bid {bid} ask {ask} spread {spread}")
        except Exception:
            pass
        return lines

    def _section_indicators(self) -> list[str]:
        engine = self._get_engine()
        """增强版：注入 M30/H1/H4 指标 + K 线摘要"""
        lines = []
        if not self._engine:
            return lines
        try:
            indicators = self._engine._cached_indicators
            if indicators:
                lines.append("指标:")
                for tf in ('M30', 'H1', 'H4'):
                    tf_data = indicators.get(tf, {})
                    if tf_data:
                        rsi = tf_data.get('rsi', '?')
                        macd = tf_data.get('macd', {})
                        bb = tf_data.get('bb', {})
                        atr = tf_data.get('atr', '?')
                        adx = tf_data.get('adx', '?')
                        trend = tf_data.get('trend', '?')
                        ema9 = tf_data.get('ema_9', '?')
                        ema21 = tf_data.get('ema_21', '?')
                        macd_s = f"MACD={macd.get('macd','?')}/{macd.get('signal','?')}" if isinstance(macd, dict) else ""
                        bb_s = f"BB({bb.get('upper','?')}/{bb.get('mid','?')}/{bb.get('lower','?')})" if isinstance(bb, dict) else ""
                        lines.append(f"  {tf}: RSI={rsi} {macd_s} {bb_s} ATR={atr} ADX={adx} EMA9={ema9} EMA21={ema21} 趋势={trend}")
        except Exception:
            pass
        return lines

    def _section_kline_summary(self) -> list[str]:
        engine = self._get_engine()
        """K 线形态摘要（阶段1新增）"""
        lines = []
        if not self._engine:
            return lines
        try:
            indicators = self._engine._cached_indicators
            if indicators:
                lines.append("K线形态:")
                for tf in ('M30', 'H1'):
                    tf_data = indicators.get(tf, {})
                    if tf_data:
                        close = tf_data.get('close', '?')
                        bb = tf_data.get('bb', {})
                        bb_mid = bb.get('mid', 0) if isinstance(bb, dict) else 0
                        bb_upper = bb.get('upper', 0) if isinstance(bb, dict) else 0
                        bb_lower = bb.get('lower', 0) if isinstance(bb, dict) else 0
                        rsi = tf_data.get('rsi', 50)
                        # 价格在 BB 中的位置
                        bb_range = bb_upper - bb_lower
                        pos = "中轨" if bb_range == 0 else ("上轨" if close >= bb_upper else ("下轨" if close <= bb_lower else f"{(close-bb_lower)/bb_range*100:.0f}%"))
                        lines.append(f"  {tf}: 收盘{close} BB位置{pos} RSI{rsi}")
        except Exception:
            pass
        return lines

    def _section_signals(self) -> list[str]:
        """近期信号流水（阶段1新增）"""
        lines = []
        try:
            from data.database import get_conn
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT strategy, signal, status, void_reason, timestamp FROM signals "
                    "ORDER BY rowid DESC LIMIT 10"
                ).fetchall()
                if rows:
                    lines.append("近期信号:")
                    for r in rows:
                        st = r[0]; sg = r[1]; status = r[2]; vr = r[3]; ts = r[4]
                        status_str = f"{status}" if status != 'voided' else f"拒绝({vr})"
                        lines.append(f"  {st}: {sg} → {status_str} @{ts}")
            finally:
                conn.close()
        except Exception:
            pass
        return lines

    def _section_trades(self) -> list[str]:
        """近期成交盈亏（阶段1新增）"""
        lines = []
        try:
            from data.database import get_conn
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT strategy, direction, entry_price, close_price, pnl, close_time FROM trades "
                    "WHERE close_time IS NOT NULL ORDER BY close_time DESC LIMIT 10"
                ).fetchall()
                if rows:
                    lines.append("近期成交:")
                    for r in rows:
                        st = r[0]; d = r[1]; ep = r[2]; cp = r[3]; pnl = r[4]; ct = r[5]
                        lines.append(f"  {st} {d}: 入场{ep} 出场{cp} 盈亏${pnl:+.2f} @{ct}")
            finally:
                conn.close()
        except Exception:
            pass
        return lines

    def _section_strategies(self) -> list[str]:
        engine = self._get_engine()
        """策略列表 + 各策略进出场逻辑（阶段1增强）"""
        lines = []
        if not self._engine:
            return lines
        try:
            strats = self._engine.get_active_strategies()
            if strats:
                names = [s.get('name', s) if isinstance(s, dict) else str(s) for s in strats]
                lines.append(f"策略: {len(names)}个活跃 - {', '.join(names[:10])}")

                # 从 strategy_logics 读取简要逻辑
                try:
                    from dashboard.backend.strategy_logics import get_strategy_logics
                    logics = get_strategy_logics()
                    for name in names[:8]:
                        logic = logics.get(name) or logics.get(name.lower(), {})
                        if logic and logic.get('desc'):
                            lines.append(f"  {name}: {logic['desc'][:100]}")
                except Exception:
                    pass
        except Exception:
            pass
        return lines

    def _section_news(self) -> list[str]:
        lines = []
        try:
            from dashboard.backend.ai_service import _get_latest_news
            news = _get_latest_news(3)
            if news:
                lines.append("新闻:")
                for n in news:
                    direction = n.get('direction', '?')
                    content = n.get('content', '')[:60]
                    lines.append(f"  - [{direction}] {content}")
        except Exception:
            pass
        return lines

    def _section_calendar(self) -> list[str]:
        lines = []
        try:
            from dashboard.backend.ai_service import _get_today_calendar
            events = _get_today_calendar()
            if events:
                lines.append(f"经济日历: {events}")
        except Exception:
            pass
        return lines

    # ── 构建 ──

    def build(self, sections: list[str] = None) -> str:
        """构建完整上下文。sections: 需包含的段名，None=全部"""
        section_map = {
            "engine": self._section_engine,
            "positions": self._section_positions,
            "price": self._section_price,
            "indicators": self._section_indicators,
            "kline": self._section_kline_summary,
            "signals": self._section_signals,
            "trades": self._section_trades,
            "strategies": self._section_strategies,
            "news": self._section_news,
            "calendar": self._section_calendar,
        }
        if sections is None:
            sections = list(section_map.keys())

        parts = ["\n【当前交易上下文】"]
        now = datetime.now(LOCAL_TZ)
        parts.append(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC+8")

        for s in sections:
            fn = section_map.get(s)
            if fn:
                lines = fn()
                if lines:
                    parts.extend(lines)

        return "\n".join(parts)


_builder = ContextBuilder()

def get_builder() -> ContextBuilder:
    return _builder