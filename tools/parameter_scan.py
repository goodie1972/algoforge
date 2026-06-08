"""
V6 Hybrid 参数扫描脚本
========================
对 oversold/overbought/trailing_atr/hard_atr/div_lookback 进行网格搜索
用法: python tools/parameter_scan.py
"""

import itertools
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtest_optimization import V6_Hybrid, run_backtest


PARAM_GRID = {
    "oversold": [30, 35, 40],
    "overbought": [60, 65, 70],
    "trailing_atr": [2.5, 3.0, 3.5, 4.0],
    "hard_atr": [2.0, 2.5, 3.0, 3.5],
    "div_lookback": [10, 15, 20],
}


def make_v6_class(param_overrides: dict):
    """Create a V6_Hybrid subclass with overridden params"""
    class V6_Variant(V6_Hybrid):
        params = (
            ('name', 'V6-Scan'),
            ('trailing_atr', param_overrides.get('trailing_atr', 3.5)),
            ('hard_atr', param_overrides.get('hard_atr', 3.0)),
            ('oversold', param_overrides.get('oversold', 35)),
            ('overbought', param_overrides.get('overbought', 65)),
            ('div_lookback', param_overrides.get('div_lookback', 15)),
        )
    V6_Variant.__name__ = f"V6_{param_overrides.get('name', 'scan')}"
    return V6_Variant


def run_scan():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.path.join(root, "data", "XAUUSD_H1_merged.csv")
    if not os.path.exists(data_path):
        alt = os.path.join(root, "..", "xauusd-dev", "data", "XAUUSD_H1_merged.csv")
        if os.path.exists(alt):
            data_path = alt
        else:
            print(f"数据文件未找到: {data_path}")
            print(f"备选路径也不存在: {alt}")
            return

    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combinations = list(itertools.product(*values))
    total = len(combinations)

    print(f"V6 参数扫描: {total} 种组合")
    print(f"数据: {data_path}")
    print(f"日期范围: 2024-05 ~ 2026-06")
    print("=" * 70)
    print(f"{'#':>3} {'过卖':>4} {'过买':>4} {'追踪ATR':>7} {'硬止损ATR':>8} {'背离回看':>8} {'收益率':>8} {'交易':>5} {'胜率':>7} {'总盈亏':>10}")
    print("-" * 70)

    results = []
    for i, combo in enumerate(combinations):
        params = dict(zip(keys, combo))
        # Build a descriptive name
        label = f"OS{combo[0]}_OB{combo[1]}_TA{combo[2]}_HA{combo[3]}_DL{combo[4]}"
        params['name'] = label

        variant_class = make_v6_class(params)

        try:
            result = run_backtest(
                variant_class, label, data_path,
                cash=10000.0,
                fromdate=datetime(2024, 5, 1),
                todate=datetime(2026, 6, 5),
            )
            wr = result['win_count'] / result['trade_count'] * 100 if result['trade_count'] else 0
            results.append((result['total_pnl'], result, params))

            print(f"{i+1:>3} {combo[0]:>4} {combo[1]:>4} {combo[2]:>7} {combo[3]:>8} {combo[4]:>8} {result['total_return']:>+7.2f}% {result['trade_count']:>5} {wr:>6.1f}% ${result['total_pnl']:>+8.2f}")
        except Exception as e:
            print(f"{i+1:>3} {label} ERROR: {e}")

    # Sort by total_pnl descending
    results.sort(key=lambda x: x[0], reverse=True)

    print("\n" + "=" * 70)
    print(f"  TOP 5 推荐参数组合")
    print("=" * 70)
    for rank, (pnl, result, params) in enumerate(results[:5], 1):
        wr = result['win_count'] / result['trade_count'] * 100 if result['trade_count'] else 0
        print(f"\n  [#{rank}] {result['strategy']}")
        print(f"      过卖={params['oversold']} | 过买={params['overbought']} | 追踪ATR={params['trailing_atr']} | 硬止损ATR={params['hard_atr']} | 背离回看={params['div_lookback']}")
        print(f"      收益率: {result['total_return']:+.2f}% | 交易: {result['trade_count']} | 胜率: {wr:.1f}% | 总盈亏: ${result['total_pnl']:+.2f}")


if __name__ == "__main__":
    run_scan()
