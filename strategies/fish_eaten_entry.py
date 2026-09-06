"""
fish_eaten 入场衰竭打分 —— 纯函数，无框架依赖
=============================================
实盘 strategies/fish_eaten_v3.py 与回测 backtest/fish_eaten_v3.py
共用同一份逻辑，保证「回测看到的就是实盘跑的」，避免两套代码漂移。

为什么要改
----------
旧版 6 道筛子全是「下限型 / 滞后型」：
  1. adx > 22          —— 只有下界，22~60 全通过，中段(ADX上升)与末端(ADX回落)不区分
  2. |+DI--DI| > 5     —— 只有下界，而中段差值反而最大 → 主动选中段
  3. -DI > +DI         —— 方向对，但不约束强度
  4. rsi<30 且 mfi<25  —— 瞬时极值，无钝化/无背离 → 首次跌破 30 常是加速下跌起点
  5. close <= 下轨+5   —— 贴轨下行(band walk)是标准「延续」形态，被当成衰竭选了
  6. bb_mid_dir==down  —— BB 中轨≈SMA20，向下=趋势健康且仍在跑；且滞后，末端仍向下

→ 结论：6 道筛子在趋势中段与末端同样通过，结构上就指向中段。

新版结构
--------
硬门禁（趋势确实存在 + 极端区已被触及）+ 衰竭打分（趋势动能正在衰减）。

所有输入一律取 bar1（最近已闭合 K 线），绝不触碰 forming bar0 —— 无未来函数。
"""

from dataclasses import dataclass, asdict
from typing import Optional

MAX_SCORE = 10  # 满分：8 个单项分(各 1) + 背离(2)


@dataclass
class EntryParams:
    """入场参数。回测会对 score_min / adx_max / require_pierce / div_lookback 网格扫描。"""

    adx_min: float = 22.0
    adx_max: float = 60.0          # 上界：宽止损回测下 A60 优于 A30/A40（A30 是窄止损 regime 过拟合）
    di_diff_min: float = 5.0
    rsi_os: float = 30.0           # 超卖
    rsi_ob: float = 70.0           # 超买
    mfi_os: float = 25.0
    mfi_ob: float = 75.0
    bb_entry_offset: float = 5.0
    div_lookback: int = 8          # 背离回看根数；网格冠军 D8
    score_min: int = 4             # 衰竭分阈值（满分 10）
    require_pierce: bool = False   # 是否把「插针收回」提升为硬门禁

    def as_dict(self) -> dict:
        return asdict(self)


def _f(v, default=None) -> Optional[float]:
    """安全转 float，None/NaN/非法值 → default"""
    try:
        if v is None:
            return default
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _bull_divergence(closes: list, rsis: list, lookback: int) -> bool:
    """底背离：价格比窗口内「前低 pivot」更低，但 RSI 高于该 pivot 处的 RSI。

    注意：不能用「价格创窗口新低 且 RSI > 窗口 RSI 最小值」这种写法 ——
    实测 4889 根 M30 只触发 8 次，形同虚设。原因是价格创新低时 RSI 通常也接近最低。
    正确做法是 A-B 两点比较：拿当前这根与窗口内价格最低那根逐一对比。
    """
    n = _div_window(closes, rsis, lookback)
    if n < 3:
        return False
    win_c, win_r = closes[-n:-1], rsis[-n:-1]
    cur_c, cur_r = closes[-1], rsis[-1]
    if cur_c is None or cur_r is None:
        return False
    j, best = None, None
    for k, v in enumerate(win_c):
        if v is None:
            continue
        if best is None or v < best:
            best, j = v, k
    if j is None or win_r[j] is None:
        return False
    return cur_c < best and cur_r > win_r[j]


def _bear_divergence(closes: list, rsis: list, lookback: int) -> bool:
    """顶背离：价格比窗口内「前高 pivot」更高，但 RSI 低于该 pivot 处的 RSI"""
    n = _div_window(closes, rsis, lookback)
    if n < 3:
        return False
    win_c, win_r = closes[-n:-1], rsis[-n:-1]
    cur_c, cur_r = closes[-1], rsis[-1]
    if cur_c is None or cur_r is None:
        return False
    j, best = None, None
    for k, v in enumerate(win_c):
        if v is None:
            continue
        if best is None or v > best:
            best, j = v, k
    if j is None or win_r[j] is None:
        return False
    return cur_c > best and cur_r < win_r[j]


def _div_window(closes: list, rsis: list, lookback: int) -> int:
    if not closes or not rsis or lookback < 2:
        return 0
    return min(len(closes), len(rsis), lookback + 1)


def score_entry(side: str, ctx: dict, p: EntryParams) -> dict:
    """对单次入场机会打分。

    side: "LONG"（超卖反多） / "SHORT"（超买反空）
    ctx  必需键（全部为 bar1 = 最近已闭合 K 线的值）：
        rsi, rsi_prev, mfi, mfi_prev,
        adx, adx_prev, pdi, pdi_prev, ndi, ndi_prev,
        bb_lower, bb_upper, bb_width, bb_width_prev,
        close, low, high
        closes: 收盘价序列（旧→新，末项 = bar1 close）
        rsis  : RSI 序列（旧→新，末项 = bar1 rsi）
    返回: {"pass", "score", "max", "gates", "reasons", "missing"}
    """
    long_side = (side.upper() == "LONG")

    rsi = _f(ctx.get("rsi")); rsi_p = _f(ctx.get("rsi_prev"))
    mfi = _f(ctx.get("mfi")); mfi_p = _f(ctx.get("mfi_prev"))
    adx = _f(ctx.get("adx")); adx_p = _f(ctx.get("adx_prev"))
    pdi = _f(ctx.get("pdi")); pdi_p = _f(ctx.get("pdi_prev"))
    ndi = _f(ctx.get("ndi")); ndi_p = _f(ctx.get("ndi_prev"))
    bb_lo = _f(ctx.get("bb_lower")); bb_up = _f(ctx.get("bb_upper"))
    bw = _f(ctx.get("bb_width")); bw_p = _f(ctx.get("bb_width_prev"))
    close = _f(ctx.get("close")); low = _f(ctx.get("low")); high = _f(ctx.get("high"))
    closes = ctx.get("closes") or []
    rsis = ctx.get("rsis") or []

    gates: dict = {}
    reasons: list = []
    score = 0

    # ── 硬门禁 0：核心数据完整 ──
    if None in (rsi, mfi, adx, pdi, ndi, bb_lo, bb_up, close, low, high):
        return {"pass": False, "score": 0, "max": MAX_SCORE, "gates": {},
                "reasons": ["指标不完整"], "missing": True}

    # ── 硬门禁 1：ADX 双向区间（新增上界）──
    gates["adx_range"] = (p.adx_min <= adx <= p.adx_max)
    if not gates["adx_range"]:
        return _ret(False, score, gates, [f"ADX={adx:.1f} 不在[{p.adx_min:.0f},{p.adx_max:.0f}]"])

    # ── 硬门禁 2：DI 方向 + 差值下界 ──
    di_diff = abs(pdi - ndi)
    gates["di_dir"] = (ndi > pdi) if long_side else (pdi > ndi)
    gates["di_diff"] = (di_diff >= p.di_diff_min)
    if not gates["di_dir"]:
        return _ret(False, score, gates, [f"DI 方向不符({'−DI>+DI' if long_side else '+DI>−DI'})"])
    if not gates["di_diff"]:
        return _ret(False, score, gates, [f"DI差={di_diff:.1f} < {p.di_diff_min:.0f}"])

    # ── 硬门禁 3：极端区已被触及（当前或上一根）──
    if long_side:
        gates["extreme"] = (min(rsi, rsi_p if rsi_p is not None else rsi) <= p.rsi_os
                            and min(mfi, mfi_p if mfi_p is not None else mfi) <= p.mfi_os)
        touch = (low <= bb_lo + p.bb_entry_offset)
    else:
        gates["extreme"] = (max(rsi, rsi_p if rsi_p is not None else rsi) >= p.rsi_ob
                            and max(mfi, mfi_p if mfi_p is not None else mfi) >= p.mfi_ob)
        touch = (high >= bb_up - p.bb_entry_offset)
    gates["bb_touch"] = touch
    if not gates["extreme"]:
        return _ret(False, score, gates, ["未触及极端区(RSI/MFI)"])
    if not touch:
        return _ret(False, score, gates, ["价格未触及 BB 轨"])

    # ══════════ 衰竭打分 ══════════
    # S1 ADX 掉头：趋势动能衰减（需 1 根历史）
    if adx_p is not None:
        if adx < adx_p:
            score += 1; reasons.append(f"ADX掉头 {adx_p:.1f}→{adx:.1f}")
    else:
        reasons.append("ADX缺历史")

    # S2 DI 差收敛：空/多头主导力在减弱（需 1 根历史）
    if pdi_p is not None and ndi_p is not None:
        di_diff_p = abs(pdi_p - ndi_p)
        if di_diff < di_diff_p:
            score += 1; reasons.append(f"DI收敛 {di_diff_p:.1f}→{di_diff:.1f}")
    else:
        reasons.append("DI缺历史")

    # S3 带宽收缩：波动能量衰减（替代旧的 bb_mid_dir=="down"）
    if bw is not None and bw_p is not None:
        if bw < bw_p:
            score += 1; reasons.append(f"带宽收缩 {bw_p:.2f}→{bw:.2f}")
    else:
        reasons.append("带宽缺历史")

    # S4 插针收回：破轨但收盘收回轨内 —— 拒绝/假突破，最强的单根衰竭形态
    if long_side:
        pierce = (low < bb_lo and close > bb_lo)
    else:
        pierce = (high > bb_up and close < bb_up)
    if pierce:
        score += 1; reasons.append("插针收回")
    if p.require_pierce and not pierce:
        gates["pierce"] = False
        return _ret(False, score, gates, reasons + ["硬门禁:无插针收回"])
    gates["pierce"] = pierce

    # S5 / S6 RSI 回升 + 上穿离开超卖区
    if rsi_p is not None:
        if (rsi > rsi_p) if long_side else (rsi < rsi_p):
            score += 1; reasons.append(f"RSI{'回升' if long_side else '回落'} {rsi_p:.1f}→{rsi:.1f}")
        left = (rsi_p <= p.rsi_os and rsi > p.rsi_os) if long_side else (rsi_p >= p.rsi_ob and rsi < p.rsi_ob)
        if left:
            score += 1; reasons.append(f"RSI离开{'超卖' if long_side else '超买'}")

    # S7 / S8 MFI 回升 + 上穿离开超卖区
    if mfi_p is not None:
        if (mfi > mfi_p) if long_side else (mfi < mfi_p):
            score += 1; reasons.append(f"MFI{'回升' if long_side else '回落'} {mfi_p:.1f}→{mfi:.1f}")
        left = (mfi_p <= p.mfi_os and mfi > p.mfi_os) if long_side else (mfi_p >= p.mfi_ob and mfi < p.mfi_ob)
        if left:
            score += 1; reasons.append(f"MFI离开{'超卖' if long_side else '超买'}")

    # S9 背离（需 ~lookback 根历史）
    div = (_bull_divergence(closes, rsis, p.div_lookback) if long_side
           else _bear_divergence(closes, rsis, p.div_lookback))
    if div:
        score += 2; reasons.append("底背离" if long_side else "顶背离")

    gates["score_ok"] = (score >= p.score_min)
    return _ret(gates["score_ok"], score, gates, reasons)


def _ret(ok: bool, score: int, gates: dict, reasons: list) -> dict:
    return {"pass": bool(ok), "score": score, "max": MAX_SCORE,
            "gates": gates, "reasons": reasons, "missing": False}


def seq_at(seq, back: int = 0):
    """取倒数第 back+1 项：back=0 → bar1（最近已闭合），back=1 → bar2。越界返回 None。"""
    if not seq:
        return None
    i = len(seq) - 1 - back
    return seq[i] if i >= 0 else None


def build_ctx_from_series(ind: dict) -> dict:
    """把 {name: [旧→新序列]} 组装成 score_entry 需要的 ctx（末项 = bar1）。

    便于回测与实盘用同一装配逻辑：实盘序列来自 get_indicator_series，回测来自 DataFrame。
    """
    return {
        "rsi": seq_at(ind.get("rsi"), 0), "rsi_prev": seq_at(ind.get("rsi"), 1),
        "mfi": seq_at(ind.get("mfi"), 0), "mfi_prev": seq_at(ind.get("mfi"), 1),
        "adx": seq_at(ind.get("adx"), 0), "adx_prev": seq_at(ind.get("adx"), 1),
        "pdi": seq_at(ind.get("pdi"), 0), "pdi_prev": seq_at(ind.get("pdi"), 1),
        "ndi": seq_at(ind.get("ndi"), 0), "ndi_prev": seq_at(ind.get("ndi"), 1),
        "bb_lower": seq_at(ind.get("bb_lower"), 0), "bb_upper": seq_at(ind.get("bb_upper"), 0),
        "bb_width": seq_at(ind.get("bb_width"), 0), "bb_width_prev": seq_at(ind.get("bb_width"), 1),
        "close": seq_at(ind.get("close"), 0),
        "low": seq_at(ind.get("low"), 0), "high": seq_at(ind.get("high"), 0),
        "closes": list(ind.get("close") or []),
        "rsis": list(ind.get("rsi") or []),
    }
