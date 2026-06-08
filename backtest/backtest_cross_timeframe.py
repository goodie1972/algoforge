"""
跨周期多策略对比回测（v2.1）
对每个时间帧（M15, M30, H1, H4）运行全部6个优化变体
输出统一对比表
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # xauusd项目根

import backtrader as bt
from datetime import datetime
from collections import defaultdict

# ── 导入所有策略 ──
from backtest_optimization import (
    V1_KDJ_MACD,
    V2_KDJ_RSI,
    V3_LongShort,
    V4_Bollinger_KDJ,
    V5_Keltner_KDJ,
    V6_Hybrid,
)

DEV_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "xauusd-dev", "data")

TIMEFRAMES = {
    "M15": os.path.join(DEV_DATA, "XAUUSD_M15.csv"),
    "M30": os.path.join(DEV_DATA, "XAUUSD_M30.csv"),
    "H1":  os.path.join(DEV_DATA, "XAUUSD_H1_merged.csv"),
    "H4":  os.path.join(DEV_DATA, "XAUUSD_H4_resampled.csv"),
}

VARIANT_INFO = {
    "V1-KDJ+MACD":    V1_KDJ_MACD,
    "V2-KDJ+RSI":     V2_KDJ_RSI,
    "V3-双向交易":      V3_LongShort,
    "V4-布林带KDJ":     V4_Bollinger_KDJ,
    "V5-肯特纳KDJ":     V5_Keltner_KDJ,
    "V6-终极混合":       V6_Hybrid,
}


class CrossTimeframeAnalyzer(bt.Analyzer):
    """自定义分析器：从策略属性提取核心指标"""
    def get_analysis(self):
        strat = self.strategy
        bank = strat.broker.getvalue()
        starting = strat.broker.startingcash
        total_pnl = getattr(strat, 'total_pnl', 0.0)
        n_trades = getattr(strat, 'trade_count', 0)
        win_count = getattr(strat, 'win_count', 0)
        trades_log = getattr(strat, 'trades_log', [])
        
        wins = [t for t in trades_log if t["pnl"] > 0]
        losses = [t for t in trades_log if t["pnl"] <= 0]
        avg_bars = 0.0  # 策略不追踪持仓时长
        
        return {
            "total_return_pct": round((bank / starting - 1) * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "n_trades": n_trades,
            "win_rate": round(win_count / n_trades * 100, 1) if n_trades > 0 else 0.0,
            "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0.0,
            "avg_bars": avg_bars,
            "max_dd_pct": 0.0,
            "profit_factor": round(abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)), 2) if losses and sum(t["pnl"] for t in losses) != 0 else float('inf'),
        }


def run_strategy(name: str, strategy_cls, csv_path: str, tf_label: str, cash: float = 10000.0, slippage: float = 0.001):
    """在指定 CSV 上跑单个策略"""
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_cls)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0)  # 滑点已在策略内做

    data = bt.feeds.GenericCSVData(
        dataname=csv_path,
        dtformat="%Y-%m-%d %H:%M:%S",
        timeframe=bt.TimeFrame.Minutes,
        compression={"M15": 15, "M30": 30, "H1": 60, "H4": 240}[tf_label],
        openinterest=-1,
    )
    cerebro.adddata(data)
    cerebro.addanalyzer(CrossTimeframeAnalyzer, _name="xva")
    
    # 注册自定义指标
    bt.indicators.SMA = bt.indicators.SimpleMovingAverage
    
    try:
        results = cerebro.run()
        if results:
            return results[0].analyzers.xva.get_analysis()
    except Exception as e:
        return {"error": str(e)}
    
    return {"error": "no results"}


def print_comparison_table(all_results: dict):
    """打印跨周期对比表"""
    tfs = ["M15", "M30", "H1", "H4"]
    
    print("\n" + "=" * 140)
    print(f"{'策略':<22} {'周期':<6} {'收益率%':<10} {'总损益$':<10} {'交易数':<8} {'胜率%':<8} {'盈亏比':<8} {'均盈利':<8} {'均亏损':<8} {'均持仓':<8}")
    print("-" * 140)
    
    summary = defaultdict(list)
    
    for tf in tfs:
        tf_results = all_results.get(tf, {})
        for name in VARIANT_INFO:
            r = tf_results.get(name, {})
            if r.get("error"):
                row = f"{name:<22} {tf:<6} ERROR: {r['error']}"
                print(row)
                continue
            
            summary[tf].append({
                "name": name,
                "return_pct": r.get("total_return_pct", 0),
                "pnl": r.get("total_pnl", 0),
                "n_trades": r.get("n_trades", 0),
                "win_rate": r.get("win_rate", 0),
                "profit_factor": r.get("profit_factor", 0),
            })
            
            pf_str = f"{r.get('profit_factor', 0):.2f}" if r.get('profit_factor', 0) != float('inf') else "∞"
            print(f"{name:<22} {tf:<6} "
                  f"{r.get('total_return_pct', 0):>+8.2f}% "
                  f"${r.get('total_pnl', 0):>+7.2f} "
                  f"{r.get('n_trades', 0):<8} "
                  f"{r.get('win_rate', 0):>6.1f}% "
                  f"{pf_str:<8} "
                  f"${r.get('avg_win', 0):>+6.2f} "
                  f"${r.get('avg_loss', 0):>6.2f} "
                  f"{r.get('avg_bars', 0):>6.1f}")
    
    print("=" * 140)
    
    # ── 最佳周期汇总 ──
    print("\n\n== 各时间帧最优策略（按收益率排序） ==")
    print("-" * 80)
    for tf in tfs:
        entries = summary.get(tf, [])
        if not entries:
            continue
        sorted_entries = sorted(entries, key=lambda x: x["return_pct"], reverse=True)
        print(f"\n  {tf}:")
        for i, e in enumerate(sorted_entries[:3], 1):
            print(f"    {i}. {e['name']:<22} {e['return_pct']:+8.2f}%  "
                  f"({e['n_trades']}笔交易, 胜率{e['win_rate']:.1f}%)")
    
    # ── 跨周期最佳策略汇总 ──
    print("\n\n== 各策略跨周期表现（按H1+H4平均收益率排序） ==")
    print("-" * 100)
    strategy_avg = defaultdict(list)
    for tf in tfs:
        entries = summary.get(tf, [])
        for e in entries:
            strategy_avg[e["name"]].append((tf, e["return_pct"]))
    
    for name in sorted(strategy_avg, key=lambda n: sum(v for _,v in strategy_avg[n]) / len(strategy_avg[n]), reverse=True):
        vals = strategy_avg[name]
        avg = sum(v for _,v in vals) / len(vals)
        detail = " | ".join(f"{tf}={v:+5.2f}%" for tf,v in vals)
        print(f"  {name:<22} 平均={avg:>+7.2f}%  [{detail}]")


if __name__ == "__main__":
    print("=== 跨周期多策略对比回测 v2.1 ===\n")
    all_results = {}
    
    for tf, csv_path in TIMEFRAMES.items():
        if not os.path.exists(csv_path):
            print(f"\n  WARN: {tf}: {csv_path} not found, skipping")
            continue
        
        print(f"\n{'='*60}")
        print(f">> 时间帧: {tf}  ({csv_path})")
        print(f"{'='*60}")
        
        tf_results = {}
        for name, strategy_cls in VARIANT_INFO.items():
            sys.stdout.write(f"  -> {name}..."); sys.stdout.flush()
            result = run_strategy(name, strategy_cls, csv_path, tf)
            if "error" in result:
                print(f"  ERR: {result['error']}")
            else:
                print(f"  OK: {result.get('total_return_pct', 0):+6.2f}%  ({result.get('n_trades', 0)}trades)")
            tf_results[name] = result
        
        all_results[tf] = tf_results
    
    print("\n\n" + "=" * 140)
    print("== 最终对比 ==")
    print_comparison_table(all_results)
    
    # 保存 JSON
    out_path = os.path.join(os.path.dirname(__file__), "cross_timeframe_results.json")
    
    # 清理不可序列化内容
    clean = {}
    for tf, results in all_results.items():
        clean[tf] = {}
        for name, r in results.items():
            clean[tf][name] = {k: v for k, v in r.items() if isinstance(v, (int, float, str, bool, type(None)))}
    
    with open(out_path, "w") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")
