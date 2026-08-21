"""
LLM 参数搜索工具 — 遗传式参数优化 + Ollama LLM 引导
====================================================
参考: BeanBagData/Gold-Predictive-AutoResearch-Backtesting-System
用法: python tools/llm_param_search.py --strategy gold_auto_research --runs 20

流程:
1. 定义参数空间（PARAM_SPACE）
2. 遗传式搜索：每轮候选参数组合 → 运行回测 → 评分
3. 每 5 轮调用 LLM 分析最佳/最差组合，调整搜索方向
4. 输出最佳参数组合
"""
import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── 参数空间定义 ──

@dataclass
class ParamRange:
    """参数范围"""
    name: str
    min_val: float
    max_val: float
    step: float = 1.0
    is_int: bool = True
    hard_low: Optional[float] = None    # 硬边界下限
    hard_high: Optional[float] = None   # 硬边界上限


# 各策略的参数空间
PARAM_SPACES: dict[str, list[ParamRange]] = {
    "gold_auto_research": [
        ParamRange("ema_fast", 3, 50, 1, hard_low=3, hard_high=50),
        ParamRange("ema_slow", 10, 60, 1, hard_low=10, hard_high=60),
        ParamRange("rsi_overbought", 70, 85, 1, hard_low=65, hard_high=90),
        ParamRange("rsi_oversold", 20, 35, 1, hard_low=15, hard_high=40),
        ParamRange("adx_thresh", 15, 60, 1, hard_low=10, hard_high=70),
        ParamRange("bb_stdev", 1.0, 3.0, 0.1, is_int=False, hard_low=1.0, hard_high=4.0),
        ParamRange("price_pos_high", 0.70, 0.95, 0.01, is_int=False, hard_low=0.5, hard_high=0.99),
        ParamRange("price_pos_low", 0.05, 0.30, 0.01, is_int=False, hard_low=0.01, hard_high=0.5),
    ],
    "timeprofit_ea": [
        ParamRange("pullback_distance", 30, 120, 5, hard_low=20, hard_high=200),
        ParamRange("no_trade_distance", 2, 10, 1, hard_low=1, hard_high=20),
        ParamRange("atr_stop_mult", 1.5, 5.0, 0.1, is_int=False, hard_low=1.0, hard_high=6.0),
        ParamRange("cooldown_minutes", 5, 30, 1, hard_low=3, hard_high=60),
    ],
    "goodma": [
        ParamRange("dir_ma_period", 30, 120, 5, hard_low=20, hard_high=200),
        ParamRange("min_trend_strength", 0.1, 2.0, 0.1, is_int=False, hard_low=0.05, hard_high=5.0),
    ],
    "kiss": [
        ParamRange("ma_fast", 20, 60, 2, hard_low=10, hard_high=80),
        ParamRange("ma_slow", 40, 120, 5, hard_low=30, hard_high=200),
        ParamRange("min_ma_gap", 0.1, 2.0, 0.1, is_int=False, hard_low=0.05, hard_high=5.0),
    ],
}


# ── 遗传算法 ──

def random_params(param_ranges: list[ParamRange]) -> dict[str, Any]:
    """生成随机参数组合"""
    params = {}
    for pr in param_ranges:
        if pr.is_int:
            val = random.randint(int(pr.min_val), int(pr.max_val))
        else:
            val = round(random.uniform(pr.min_val, pr.max_val), 2)
        params[pr.name] = val
    return params


def crossover(p1: dict, p2: dict, param_ranges: list[ParamRange]) -> dict:
    """交叉"""
    child = {}
    for pr in param_ranges:
        if random.random() < 0.5:
            child[pr.name] = p1[pr.name]
        else:
            child[pr.name] = p2[pr.name]
    return child


def mutate(params: dict, param_ranges: list[ParamRange], mutation_rate: float = 0.3) -> dict:
    """变异"""
    result = dict(params)
    for pr in param_ranges:
        if random.random() < mutation_rate:
            spread = pr.max_val - pr.min_val
            delta = spread * random.gauss(0, 0.1)
            new_val = params[pr.name] + delta
            if pr.is_int:
                new_val = round(new_val)
            else:
                new_val = round(new_val, 2)
            # 硬边界
            if pr.hard_low is not None:
                new_val = max(new_val, pr.hard_low)
            if pr.hard_high is not None:
                new_val = min(new_val, pr.hard_high)
            result[pr.name] = new_val
    return result


def clamp_params(params: dict, param_ranges: list[ParamRange]) -> dict:
    """硬边界钳制"""
    result = dict(params)
    for pr in param_ranges:
        val = result[pr.name]
        if pr.hard_low is not None:
            val = max(val, pr.hard_low)
        if pr.hard_high is not None:
            val = min(val, pr.hard_high)
        result[pr.name] = val
    return result


# ── 回测评估 ──

def run_backtest(params: dict, strategy_name: str) -> dict:
    """运行回测，返回评分结果"""
    try:
        from backtest.runner import BacktestRunner
        runner = BacktestRunner(strategy_name, params=params)
        result = runner.run()
        return {
            "score": result.get("sharpe", 0) * 100 + result.get("total_pnl", 0) * 0.1,
            "sharpe": result.get("sharpe", 0),
            "total_pnl": result.get("total_pnl", 0),
            "win_rate": result.get("win_rate", 0),
            "trades": result.get("trades", 0),
        }
    except Exception as e:
        logger.warning(f"回测失败: {e}")
        return {"score": -999, "sharpe": -999, "total_pnl": -999, "win_rate": 0, "trades": 0}


# ── LLM 分析 ──

def llm_analyze(best_params: dict, worst_params: dict, strategy_name: str) -> str:
    """调用 LLM 分析最佳/最差参数组合，返回调整建议"""
    try:
        prompt = f"""你是黄金交易策略参数优化专家。
策略: {strategy_name}
最佳参数: {json.dumps(best_params, indent=2)}
最差参数: {json.dumps(worst_params, indent=2)}

请分析：
1. 最佳与最差参数的关键差异是什么？
2. 哪些参数对结果影响最大？
3. 建议下一步搜索方向（缩小范围或调整重心），给出具体数值建议。

回复要简洁，200字以内。"""
        from services.llm_provider import LLMProvider
        provider = LLMProvider()
        resp = provider.chat(prompt, temperature=0.3)
        return resp
    except Exception as e:
        return f"LLM 分析不可用: {e}"


# ── 主流程 ──

def search(strategy_name: str, total_runs: int = 20, population: int = 10, use_llm: bool = True):
    """遗传式参数搜索"""
    param_ranges = PARAM_SPACES.get(strategy_name)
    if not param_ranges:
        logger.error(f"未知策略: {strategy_name}，可用: {list(PARAM_SPACES.keys())}")
        return

    # 初始化种群
    pop = [random_params(param_ranges) for _ in range(population)]
    results = []

    for gen in range(total_runs // population):
        logger.info(f"=== 第 {gen + 1} 代（{len(pop)} 个个体）===")

        # 评估每个个体
        for p in pop:
            p = clamp_params(p, param_ranges)
            result = run_backtest(p, strategy_name)
            result["params"] = p
            results.append(result)

        # 排序
        results.sort(key=lambda r: r["score"], reverse=True)
        best = results[:max(3, len(results) // 4)]
        worst = results[-max(3, len(results) // 4):]

        logger.info(f"  最佳: {best[0]['score']:.1f} (sharpe={best[0]['sharpe']:.2f})")
        logger.info(f"  最差: {worst[-1]['score']:.1f}")

        # LLM 分析
        if use_llm and gen % 2 == 0:
            analysis = llm_analyze(best[0]["params"], worst[-1]["params"], strategy_name)
            logger.info(f"  LLM 建议: {analysis}")

        # 选择 + 交叉 + 变异
        next_pop = [best[0]["params"]]  # 精英保留
        while len(next_pop) < population:
            p1 = random.choice(best)["params"]
            p2 = random.choice(best)["params"]
            child = crossover(p1, p2, param_ranges)
            child = mutate(child, param_ranges)
            child = clamp_params(child, param_ranges)
            next_pop.append(child)
        pop = next_pop

    # 最终结果
    results.sort(key=lambda r: r["score"], reverse=True)
    logger.info("=" * 50)
    logger.info(f"搜索完成！共 {len(results)} 次回测")
    logger.info(f"最佳参数组合（score={results[0]['score']:.1f}）:")
    for k, v in results[0]["params"].items():
        logger.info(f"  {k} = {v}")

    # 保存
    out_path = Path(f"logs/param_search_{strategy_name}_{int(time.time())}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"best": results[0], "top_5": results[:5], "all_count": len(results)}, f, ensure_ascii=False, indent=2)
    logger.info(f"结果保存至: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="LLM 参数搜索工具")
    parser.add_argument("--strategy", "-s", default="gold_auto_research",
                        choices=list(PARAM_SPACES.keys()))
    parser.add_argument("--runs", "-r", type=int, default=20, help="总回测次数")
    parser.add_argument("--population", "-p", type=int, default=10, help="每代个体数")
    parser.add_argument("--no-llm", action="store_true", help="不启用 LLM 分析")
    args = parser.parse_args()

    search(args.strategy, args.runs, args.population, not args.no_llm)


if __name__ == "__main__":
    main()