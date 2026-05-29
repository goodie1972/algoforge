"""Debug: 检查空单为什么 0% 胜率"""
import sys
from datetime import datetime
from core.bridge import create_bridge
from backtest.winrate_research import (run_variant, VariantConfig, calc_stoch,
                                        calc_bb, calc_ema, BacktestPosition,
                                        STOCH_K, STOCH_SLOWING, STOCH_D,
                                        BB_PERIOD, BB_STD)

def debug_shorts():
    bridge = create_bridge()
    if not bridge.connect():
        print("MT4连接失败")
        return

    raw = bridge.get_candles("XAUUSD", "H4", 1000)
    candles = list(reversed(raw))
    bridge.disconnect()

    print(f"H4: {len(candles)} 根, "
          f"{datetime.fromtimestamp(int(candles[0].time)).strftime('%Y-%m-%d')} ~ "
          f"{datetime.fromtimestamp(int(candles[-1].time)).strftime('%Y-%m-%d')}")

    # 只跑基线
    config = VariantConfig("基线debug", max_positions=1, use_pyramid=False,
                           exit_mode="kd_decay", sl_mode="bb_035",
                           oversold=20, overbought=80, trend_filter="none")

    results = run_variant(candles, config)

    # 手动跑一遍，抓取前5笔空单的详情
    positions = []
    active = []
    prev_k = None
    prev_d = None
    min_bars = 200

    for i in range(min_bars, len(candles)):
        c = candles[i]
        stoch = calc_stoch(candles[:i+1], STOCH_K, STOCH_SLOWING, STOCH_D)
        if stoch is None:
            continue
        p_k, curr_k, p_d, curr_d = stoch

        golden = False
        death = False
        if prev_k is not None and prev_d is not None:
            golden = prev_k <= prev_d and curr_k > curr_d
            death = prev_k >= prev_d and curr_k < curr_d
        prev_k, prev_d = curr_k, curr_d

        # 空单入场
        if len(active) == 0 and death and curr_k > 80:
            _, bandwidth, _ = calc_bb(candles[:i+1], BB_PERIOD, BB_STD)
            dist = bandwidth * 0.35 if bandwidth else 0
            sl = round(float(c.close) + dist, 2)
            pos = BacktestPosition(
                entry_idx=i, entry_price=float(c.close),
                direction="SELL", sl=sl, tp=0, entry_k=curr_k,
            )
            active.append(pos)

        # 出场检查
        still = []
        for pos in active:
            is_sell = True  # all shorts

            # SL check
            if float(c.high) >= pos.sl:
                pos.exit_idx = i
                pos.exit_price = pos.sl
                pos.exit_reason = "SL"
                # Calculate PnL
                pnl = (pos.entry_price - pos.exit_price) * 100.0 * 0.01 - 0.5
                pos.pnl = pnl
                positions.append(pos)
                continue

            # KD decay
            curr_diff = curr_d - curr_k
            if curr_diff < 0:
                curr_diff = 0

            # extreme protection
            if pos.entry_k > 80 and curr_k > 80 and curr_d > 80:
                still.append(pos)
                continue

            if curr_diff > pos.peak_diff:
                pos.peak_diff = curr_diff

            should_exit = False
            if pos.peak_diff > 0:
                if pos.peak_diff <= 3:
                    if curr_diff == 0:
                        should_exit = True
                else:
                    if curr_diff < pos.peak_diff * 0.382:
                        should_exit = True

            if should_exit:
                pos.exit_idx = i
                pos.exit_price = float(c.close)
                pos.exit_reason = "KD_EXIT"
                pnl = (pos.entry_price - pos.exit_price) * 100.0 * 0.01 - 0.5
                pos.pnl = pnl
                positions.append(pos)
            else:
                still.append(pos)

        active = still
        if len(positions) >= 10:
            break

    # 最终平仓
    for pos in active:
        pos.exit_idx = len(candles) - 1
        pos.exit_price = float(candles[-1].close)
        pos.exit_reason = "EXPIRY"
        pnl = (pos.entry_price - pos.exit_price) * 100.0 * 0.01 - 0.5
        pos.pnl = pnl
        positions.append(pos)

    # 打印详情
    print("\n前10笔空单详情:")
    print(f"{'#':<4} {'方向':<6} {'入场':>8} {'出场':>8} {'SL':>8} {'方式':<8} {'盈亏':>8} {'K':>6} {'D':>6}")
    print("-"*80)
    for j, p in enumerate(positions[:10]):
        k_entry = p.entry_k
        print(f"{j+1:<4} {'SELL':<6} {p.entry_price:>8.2f} {p.exit_price:>8.2f} {p.sl:>8.2f} {p.exit_reason:<8} ${p.pnl:>7.2f} {k_entry:>6.1f}")


if __name__ == "__main__":
    debug_shorts()
