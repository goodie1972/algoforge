"""
TA-Lib K线形态信号标注图 (独立HTML x 3)
=========================================
为 H1 / M30 / M15 各生成一份独立 HTML，包含：
  - 正常比例的K线图 + 成交量 + EMA20
  - 仅标注回测中有统计意义的信号组合
  - 键盘：←→ 左右平移，↑↓ 缩放

用法:
  python research/ta_lib_chart_analysis.py

输出:
  research/ta_lib_chart_H1.html
  research/ta_lib_chart_M30.html
  research/ta_lib_chart_M15.html
"""

import sys, os
import numpy as np
import talib
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.database import get_conn

# =============================================================
# 配置
# =============================================================
TIMEFRAMES = ["H1", "M30", "M15"]
LOOKAHEAD = 3
RECENT_DAYS = 90

# 默认显示的时间窗口
DEFAULT_WINDOW = {
    "H1": timedelta(days=3),
    "M30": timedelta(days=1),
    "M15": timedelta(hours=12),
}

# 只使用回测中有统计意义的过滤器组合
BULL_FILTERS = ["rsi_mid_oversold", "trend_down"]
BEAR_FILTERS = ["rsi_mid_overbought", "trend_up"]


# =============================================================
# 键盘控制 JS (注入到 HTML)
# =============================================================
KEYBOARD_JS = """
<script>
(function() {
  function getPlotly() {
    var el = document.querySelector('.js-plotly-plot');
    return el && (window.Plotly || el.data && el.layout && { relayout: function(g,u) {
      return Plotly.relayout(g,u);
    }}) || null;
  }
  document.addEventListener('keydown', function(e) {
    var gd = document.querySelector('.js-plotly-plot');
    if (!gd) return;
    var layout = gd._fullLayout || gd.layout;
    if (!layout) return;
    var xa = layout.xaxis;
    if (!xa || !xa.range) return;

    var t0 = new Date(xa.range[0]).getTime();
    var t1 = new Date(xa.range[1]).getTime();
    if (isNaN(t0) || isNaN(t1)) return;
    var span = t1 - t0;
    if (span <= 0) return;

    var key = e.key;
    if (key !== 'ArrowLeft' && key !== 'ArrowRight' && key !== 'ArrowUp' && key !== 'ArrowDown') return;
    e.preventDefault();

    var step, new0, new1;

    switch (key) {
      case 'ArrowLeft':
        step = span * 0.3;
        new0 = new Date(t0 - step);
        new1 = new Date(t1 - step);
        break;
      case 'ArrowRight':
        step = span * 0.3;
        new0 = new Date(t0 + step);
        new1 = new Date(t1 + step);
        break;
      case 'ArrowUp':
        step = span * 0.25;
        new0 = new Date(t0 + step);
        new1 = new Date(t1 - step);
        if (new1.getTime() - new0.getTime() < 60000) return;  // 最小1分钟
        break;
      case 'ArrowDown':
        step = span * 0.3;
        new0 = new Date(t0 - step);
        new1 = new Date(t1 + step);
        break;
    }

    Plotly.relayout(gd, {'xaxis.range': [new0.toISOString(), new1.toISOString()]});
  });
})();
</script>
"""


# =============================================================
# 数据加载与计算
# =============================================================

def load_recent_data(timeframe, days):
    conn = get_conn()
    cutoff = int(datetime.now().timestamp()) - days * 86400
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv WHERE timeframe = ? AND timestamp >= ? ORDER BY timestamp",
        (timeframe, cutoff),
    ).fetchall()
    if not rows:
        return None
    arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
                   dtype=[("ts", "i8"), ("o", "f8"), ("h", "f8"),
                          ("l", "f8"), ("c", "f8"), ("v", "f8")])
    return arr


def compute_indicators(o, h, l, c):
    ind = {}
    ind["rsi"] = talib.RSI(c, timeperiod=14)
    ind["atr"] = talib.ATR(h, l, c, timeperiod=14)
    ind["ema20"] = talib.EMA(c, timeperiod=20)
    return ind


def detect_all_patterns(o, h, l, c):
    patterns = {}
    for pname in dir(talib):
        if pname.startswith("CDL"):
            fn = getattr(talib, pname)
            try:
                sig = fn(o, h, l, c)
            except TypeError:
                try:
                    sig = fn(h, l, c)
                except TypeError:
                    continue
            if np.any(sig != 0):
                patterns[pname] = sig
    return patterns


def check_filter(idx, ind, close_arr, filter_name, sig_dir):
    rsi = ind["rsi"][idx]
    ema20 = ind["ema20"][idx]
    if filter_name == "rsi_mid_oversold":
        return not np.isnan(rsi) and 30 <= rsi <= 50 and sig_dir == "bull"
    elif filter_name == "rsi_mid_overbought":
        return not np.isnan(rsi) and 50 <= rsi <= 70 and sig_dir == "bear"
    elif filter_name == "trend_up":
        return not np.isnan(ema20) and close_arr[idx] > ema20
    elif filter_name == "trend_down":
        return not np.isnan(ema20) and close_arr[idx] < ema20
    return False


def collect_signals(data):
    """收集可靠信号 — 仅使用回测验证有效的过滤器组合"""
    o, h, l, c, v = data["o"], data["h"], data["l"], data["c"], data["v"]
    n = len(data)
    ind = compute_indicators(o, h, l, c)
    patterns = detect_all_patterns(o, h, l, c)

    signals = []
    ts_list = data["ts"]

    for pname, sig_arr in patterns.items():
        for i in range(LOOKAHEAD + 2, n - LOOKAHEAD - 2):
            raw = sig_arr[i]
            if raw == 0:
                continue
            sig_dir = "bull" if raw > 0 else "bear"

            filters_to_check = BULL_FILTERS if sig_dir == "bull" else BEAR_FILTERS

            matched_filter = None
            for fname in filters_to_check:
                if check_filter(i, ind, c, fname, sig_dir):
                    matched_filter = fname
                    break

            if not matched_filter:
                continue

            # 验证结果: 持仓期最高/最低是否朝预测方向移动
            end = min(i + LOOKAHEAD + 1, n)
            if sig_dir == "bull":
                outcome_price = np.max(h[i + 1:end])
                success = outcome_price > c[i]
            else:
                outcome_price = np.min(l[i + 1:end])
                success = outcome_price < c[i]

            change_pct = (outcome_price - c[i]) / c[i] * 100

            filter_labels = {
                "rsi_mid_oversold": "RSI 30~50",
                "rsi_mid_overbought": "RSI 50~70",
                "trend_up": "价>EMA20",
                "trend_down": "价<EMA20",
            }

            signals.append({
                "ts": ts_list[i],
                "price": c[i],
                "dir": sig_dir,
                "pattern": pname,
                "filter": matched_filter,
                "filter_label": filter_labels.get(matched_filter, matched_filter),
                "success": success,
                "change_pct": round(change_pct, 2),
                "rsi": round(ind["rsi"][i], 1) if not np.isnan(ind["rsi"][i]) else None,
                "ema20": round(ind["ema20"][i], 1) if not np.isnan(ind["ema20"][i]) else None,
            })

    # 去重: 同一根K线多个信号保留最强的
    signals.sort(key=lambda s: 0 if s["dir"] == "bull" else 1)
    seen_ts = set()
    unique = []
    for s in signals:
        key = (s["ts"], s["dir"])
        if key not in seen_ts:
            seen_ts.add(key)
            unique.append(s)
    return sorted(unique, key=lambda s: s["ts"])


# =============================================================
# 图表生成
# =============================================================

def build_chart_html(timeframe, data, signals):
    """生成单周期独立 HTML 图表，含键盘控制"""
    ts_list = [datetime.fromtimestamp(t, tz=timezone.utc) for t in data["ts"]]
    o, h, l, c, v = data["o"], data["h"], data["l"], data["c"], data["v"]
    ind = compute_indicators(o, h, l, c)

    # 双行: K线(主) + 成交量(次), 共享X轴
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.78, 0.22],
    )

    # 默认窗口按时间计算
    window = DEFAULT_WINDOW.get(timeframe, timedelta(days=3))
    default_start = ts_list[-1] - window
    if default_start < ts_list[0]:
        default_start = ts_list[0]
    print(f"  [{timeframe}] 共{len(ts_list)}根, 默认窗口: "
          f"{default_start.strftime('%m-%d %H:%M')} ~ {ts_list[-1].strftime('%m-%d %H:%M')}")

    # ---- K线 ----
    fig.add_trace(go.Candlestick(
        x=ts_list,
        open=o, high=h, low=l, close=c,
        name="K线",
        line=dict(width=0.8),
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
        showlegend=False,
    ), row=1, col=1)

    # ---- EMA20 ----
    fig.add_trace(go.Scatter(
        x=ts_list, y=ind["ema20"],
        name="EMA20",
        line=dict(color='#ffa726', width=1.2, dash='dash'),
        showlegend=False,
    ), row=1, col=1)

    # ---- 成交量 ----
    colors = ['#26a69a' if c[i] >= o[i] else '#ef5350' for i in range(len(c))]
    fig.add_trace(go.Bar(
        x=ts_list, y=v,
        name="成交量",
        marker_color=colors,
        opacity=0.35,
        showlegend=False,
    ), row=2, col=1)

    # ---- 信号标注 ----
    for s in signals:
        dt = datetime.fromtimestamp(s["ts"], tz=timezone.utc)
        color = '#26a69a' if s["dir"] == "bull" else '#ef5350'
        symbol = 'triangle-up' if s['dir'] == 'bull' else 'triangle-down'
        textpos = 'top center' if s['dir'] == 'bull' else 'bottom center'
        ok_str = "✓" if s["success"] else "✗"

        hover = (
            f"<b>{s['pattern']}</b><br>"
            f"方向: {'看涨' if s['dir']=='bull' else '看跌'}<br>"
            f"过滤器: {s['filter_label']}<br>"
            f"RSI(14): {s['rsi']}<br>"
            f"EMA20: {s['ema20']}<br>"
            f"入场价: {s['price']:.2f}<br>"
            f"结果: {ok_str} ({s['change_pct']:+.2f}%)"
        )

        fig.add_trace(go.Scatter(
            x=[dt], y=[s["price"]],
            mode='markers+text',
            marker=dict(
                symbol=symbol, size=13,
                color=color, line=dict(width=1, color='white')
            ),
            text='▲' if s['dir'] == 'bull' else '▼',
            textposition=textpos,
            textfont=dict(size=11, color=color),
            name=f"{s['pattern']} ({s['dir'].upper()})",
            hovertext=hover,
            hoverinfo='text',
            showlegend=False,
        ), row=1, col=1)

    # ---- 布局 ----
    bulls = sum(1 for s in signals if s["dir"] == "bull")
    bears = sum(1 for s in signals if s["dir"] == "bear")

    fig.update_layout(
        title=dict(
            text=(
                f"{timeframe} TA-Lib 形态信号分析"
                f"<br><sup style='color:#888'>"
                f"↑{bulls}个看涨 / ↓{bears}个看跌"
                f" | ←→平移 ↑↓缩放 | 共{RECENT_DAYS}天数据"
                f"</sup>"
            ),
            x=0.5,
            font=dict(size=20),
        ),
        height=780,
        template='plotly_dark',
        hovermode='x unified',
        margin=dict(l=50, r=30, t=80, b=30),

        xaxis=dict(
            rangeslider=dict(visible=True, thickness=0.08),
            type="date",
            title="",
            showgrid=True,
            gridcolor='#333',
        ),
        xaxis2=dict(
            rangeslider=dict(visible=False),
            title="时间",
            showgrid=True,
            gridcolor='#333',
        ),
        yaxis=dict(
            title="价格 (USD)",
            showgrid=True,
            gridcolor='#333',
            tickformat=".0f",
        ),
        yaxis2=dict(
            title="成交量",
            showgrid=False,
        ),

        dragmode='zoom',
        modebar=dict(
            orientation='v',
            activecolor='#42a5f5',
        ),
    )

    # 默认窗口
    fig.layout.xaxis.range = (default_start, ts_list[-1])
    fig.layout.xaxis.autorange = False

    # 图例说明
    fig.add_annotation(
        xref="paper", yref="paper",
        x=0, y=1.03,
        text="<b>▲</b> 看涨 &nbsp;&nbsp; <b>▼</b> 看跌 &nbsp;&nbsp; <span style='color:#ffa726'>--</span> EMA20 &nbsp;&nbsp; | &nbsp;&nbsp; <span style='color:#888'>←→平移 ↑↓缩放</span>",
        showarrow=False,
        font=dict(size=13, color='#aaa'),
        align="left",
        bgcolor='rgba(0,0,0,0.5)',
        bordercolor='#555',
        borderwidth=1,
        borderpad=6,
    )

    # ---- 输出 + 注入键盘 JS ----
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, f"ta_lib_chart_{timeframe}.html")
    fig.write_html(out_path, include_plotlyjs=True, full_html=True)

    # 在 </body> 前注入键盘控制脚本
    with open(out_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("</body>", KEYBOARD_JS + "\n</body>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    return out_path


# =============================================================
# 主流程
# =============================================================
print("加载数据...")
all_data = {}
for tf in TIMEFRAMES:
    data = load_recent_data(tf, RECENT_DAYS)
    if data is not None:
        all_data[tf] = data
        f = datetime.fromtimestamp(data["ts"][0]).strftime("%m-%d")
        t = datetime.fromtimestamp(data["ts"][-1]).strftime("%m-%d")
        print(f"  {tf}: {len(data)} candles ({f} ~ {t})")

print("\n检测信号 (仅高质量组合)...")
all_signals = {}
for tf in TIMEFRAMES:
    if tf in all_data:
        sigs = collect_signals(all_data[tf])
        all_signals[tf] = sigs
        bulls = sum(1 for s in sigs if s["dir"] == "bull")
        bears = sum(1 for s in sigs if s["dir"] == "bear")
        print(f"  {tf}: {len(sigs)} 个信号 ({bulls}↑ {bears}↓)")

print("\n生成独立图表...")
for tf in TIMEFRAMES:
    if tf in all_data:
        path = build_chart_html(tf, all_data[tf], all_signals.get(tf, []))
        size_kb = os.path.getsize(path) / 1024
        print(f"  {path} ({size_kb:.0f} KB)")

print("\n完成！")
