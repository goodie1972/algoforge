"""
GitHub 全部10个 XAUUSD 开源策略统一回测
=========================================
移植所有有源代码的策略并在 M30/H1/H4 + 原生周期上测试。

10 个仓库状态:
  ✅ 1. sanqing-ea              — MQL4 EMA9/21+ATR14, 3子策略 → 已移植
  ✅ 2. gold-pro-scalper/N30    — MQL5 Z-Score+ADX 均值回归/突破 → 已移植
  ✅ 3. xauusd-trend-follow     — MQL4 EMA200+MACD/Stoch/EMA交叉 → 已移植
  ✅ 4. xaubot-ai               — Python XGBoost+Polars 81特征 → 移植
  ✅ 5. Gold-Predictive-AutoResearch — Python Ollama优化, 核心是共识投票 → 移植
  ✅ 6. BAKOMEGoldScalper        — MQL5 ICT概念(FVG+OB+Silver Bullet) → 移植
  ❌ 7. mt5-ai-xauusd-trader     — PyTorch RL, 需MT5连接+模型权重
  ❌ 8. EA_SCALPER_XAUUSD        — 无源码(编译后.ex5)
  ❌ 9. Forex-Gold-Auto-Trader   — 仅文档, 无可执行策略
  ❌ 10. YQTS                    — 策略规格说明(YQTS_BRIEF.md), 无执行代码
"""
import sys, os, json, math, warnings, pickle
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import polars as pl
from core.bridge import Candle

# ── XGBoost ──
try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

# ── 数据库 ──
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.db")
import sqlite3

COMMISSION = 0.50

# ====================================================================
# 数据加载
# ====================================================================
def load_all_data():
    """从 market_data.db 加载 OHLCV 数据, 返回 {tf: {...}} 字典和 Polars 字典."""
    conn = sqlite3.connect(DB_PATH)
    DATA = {}
    POLARS = {}
    for tf in ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1']:
        rows = conn.execute(
            "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe=? ORDER BY timestamp",
            (tf,)
        ).fetchall()
        if not rows:
            continue
        CND = [Candle(time=str(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]), volume=float(r[5])) for r in rows]
        DATA[tf] = {
            'ts': [int(r[0]) for r in rows],
            'op': [float(r[1]) for r in rows],
            'hi': [float(r[2]) for r in rows],
            'lo': [float(r[3]) for r in rows],
            'cl': [float(r[4]) for r in rows],
            'vol': [float(r[5]) for r in rows],
            'candles': CND,
            'n': len(rows),
        }
        d0 = datetime.fromtimestamp(DATA[tf]['ts'][0])
        d1 = datetime.fromtimestamp(DATA[tf]['ts'][-1])
        print(f"  {tf}: {DATA[tf]['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")

        # Polars DataFrame for ML pipeline
        POLARS[tf] = pl.DataFrame({
            'time': [datetime.fromtimestamp(t) for t in DATA[tf]['ts']],
            'open': DATA[tf]['op'],
            'high': DATA[tf]['hi'],
            'low': DATA[tf]['lo'],
            'close': DATA[tf]['cl'],
            'volume': DATA[tf]['vol'],
        })

    conn.close()
    return DATA, POLARS

DATA, POLARS = load_all_data()
TIMEFRAMES = ['M30', 'H1', 'H4']

# ====================================================================
# 公共指标 (兼容 list-based 引擎)
# ====================================================================
def calc_ema(cl, p):
    if len(cl) < p: return None
    k = 2.0 / (p + 1); e = cl[0]
    for v in cl[1:]: e = (v - e) * k + e
    return e

def calc_ema_series(cl, p):
    if len(cl) < 3: return None
    k = 2.0 / (p + 1); e = cl[0]; r = [e]
    for v in cl[1:]: e = (v - e) * k + e; r.append(e)
    return r

def calc_sma(cl, p):
    if len(cl) < p: return None
    return sum(cl[-p:]) / p

def calc_rsi(cl, p=14):
    if len(cl) < p + 1: return None
    g = l = 0
    for j in range(1, p+1):
        d = cl[j] - cl[j-1]; g += max(d, 0); l += max(-d, 0)
    ag = g / p; al = l / p
    for j in range(p+1, len(cl)):
        d = cl[j] - cl[j-1]
        ag = (ag * (p-1) + max(d, 0)) / p
        al = (al * (p-1) + max(-d, 0)) / p
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

def calc_atr_from_data(hi, lo, cl, p=14):
    n = len(cl)
    if n < p + 2: return [], 0
    tr = []
    for i in range(1, n):
        tr.append(max(hi[i] - lo[i], abs(hi[i] - cl[i-1]), abs(lo[i] - cl[i-1])))
    if len(tr) < p: return [], 0
    atr = [sum(tr[:p]) / p]
    for i in range(p, len(tr)):
        atr.append((atr[-1] * (p-1) + tr[i]) / p)
    return atr, p + 1

def get_atr_val(atr_list, warmup, idx):
    if idx < warmup or atr_list is None: return None
    ai = idx - warmup
    if ai >= len(atr_list): return None
    return atr_list[ai]

def calc_stddev(cl, p):
    if len(cl) < p: return None
    sub = cl[-p:]; s = sum(sub) / p
    return math.sqrt(sum((c - s) ** 2 for c in sub) / p)

def calc_adx(data, p=14):
    candles_n = data['n']; hi = data['hi']; lo = data['lo']; cl = data['cl']
    if candles_n < p + 2: return None
    tr = []; plus_dm = []; minus_dm = []
    for i in range(1, candles_n):
        h = hi[i]; l = lo[i]; pc = cl[i-1]; ph = hi[i-1]; pl_ = lo[i-1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = h - ph; down = pl_ - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
    if len(tr) < p: return None
    atr_val = sum(tr[:p]) / p
    pdi_val = sum(plus_dm[:p]) / p / atr_val * 100 if atr_val > 0 else 0
    ndi_val = sum(minus_dm[:p]) / p / atr_val * 100 if atr_val > 0 else 0
    atr_smooth = [atr_val]; pdi_smooth = [pdi_val]; ndi_smooth = [ndi_val]
    for i in range(p, len(tr)):
        atr_smooth.append((atr_smooth[-1] * (p-1) + tr[i]) / p)
        pd = (pdi_smooth[-1] * (p-1) + plus_dm[i] / atr_smooth[-1] * 100) / p if atr_smooth[-1] > 0 else 0
        nd = (ndi_smooth[-1] * (p-1) + minus_dm[i] / atr_smooth[-1] * 100) / p if atr_smooth[-1] > 0 else 0
        pdi_smooth.append(pd); ndi_smooth.append(nd)
    dx = [abs(pdi_smooth[i] - ndi_smooth[i]) / max(pdi_smooth[i] + ndi_smooth[i], 0.001) * 100 for i in range(len(atr_smooth))]
    adx = [sum(dx[:p]) / p]
    for i in range(p, len(dx)):
        adx.append((adx[-1] * (p-1) + dx[i]) / p)
    return {'adx_list': adx, 'pdi_list': pdi_smooth, 'ndi_list': ndi_smooth, 'warmup': p + 1}

def get_adx_val(adx_result, idx):
    if adx_result is None: return None, None, None
    warmup = adx_result['warmup']
    if idx < warmup: return None, None, None
    ai = idx - warmup
    if ai >= len(adx_result['adx_list']): return None, None, None
    return adx_result['adx_list'][ai], adx_result['pdi_list'][ai], adx_result['ndi_list'][ai]

# ====================================================================
# 统一回测引擎
# ====================================================================
def run_backtest(data, signal_fn, min_bars=100,
                 atr_trail=4.0, atr_hardstop=2.5,
                 tp_atr=None, sl_atr=None, name=""):
    cl = data['cl']; hi = data['hi']; lo = data['lo']
    n = data['n']
    atr_list = data.get('_atr')
    atr_warmup = data.get('_atr_warmup', 0)
    trades = []; pos = None; ep = 0; ei = 0
    trail_extreme = {}

    for i in range(min_bars, n):
        close = cl[i]; low = lo[i]; high = hi[i]
        atr_val = get_atr_val(atr_list, atr_warmup, i)

        if pos is not None and ei >= 0 and i > ei + 1 and atr_val and atr_val > 0:
            closed = False
            if pos == 'BUY':
                if atr_trail:
                    th = trail_extreme.get('h', ep)
                    trail_extreme['h'] = max(th, high)
                    if close < trail_extreme['h'] - atr_val * atr_trail:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                if not closed and atr_hardstop and (ep - close) > atr_val * atr_hardstop:
                    pnl = (close - ep) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                if not closed and tp_atr and sl_atr:
                    if close >= ep + atr_val * tp_atr:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                    elif close <= ep - atr_val * sl_atr:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
            else:
                if atr_trail:
                    tl = trail_extreme.get('l', ep)
                    trail_extreme['l'] = min(tl, low)
                    if close > trail_extreme['l'] + atr_val * atr_trail:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                if not closed and atr_hardstop and (close - ep) > atr_val * atr_hardstop:
                    pnl = (ep - close) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                if not closed and tp_atr and sl_atr:
                    if close <= ep - atr_val * tp_atr:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                    elif close >= ep + atr_val * sl_atr:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
            if closed:
                pos = None; ei = -1; continue

        sig = signal_fn(i, data)
        if sig and pos is None:
            pos = sig; ep = close; ei = i; trail_extreme = {}
        elif sig and sig != pos and pos:
            pnl = (close - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - close) * 1.0 - COMMISSION
            trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
            pos = sig; ep = close; ei = i; trail_extreme = {}

    if pos:
        pnl = (cl[-1] - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - cl[-1]) * 1.0 - COMMISSION
        trades.append({'d': pos, 'ep': ep, 'ex': cl[-1], 'pnl': round(pnl, 2), 'b': n - 1 - ei})

    return trades

def summarize(trades, name):
    if not trades:
        return {'name': name, 'trades': 0, 'pnl': 0, 'wr': 0, 'avg_w': 0, 'avg_l': 0,
                'best': 0, 'worst': 0, 'buy': 0, 'sell': 0, 'buy_pnl': 0, 'sell_pnl': 0, 'avg_bar': 0}
    tp = sum(t['pnl'] for t in trades)
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    aw = sum(t['pnl'] for t in w) / len(w) if w else 0
    al = sum(t['pnl'] for t in l) / len(l) if l else 0
    bt = max(t['pnl'] for t in w) if w else 0
    wt = min(t['pnl'] for t in l) if l else 0
    wr = len(w) / len(trades) * 100
    buys = sum(1 for t in trades if t['d'] == 'BUY')
    sells = sum(1 for t in trades if t['d'] == 'SELL')
    buy_pnl = sum(t['pnl'] for t in trades if t['d'] == 'BUY')
    sell_pnl = sum(t['pnl'] for t in trades if t['d'] == 'SELL')
    avg_bar = sum(t['b'] for t in trades) / len(trades)
    max_consec_loss = 0; cur_loss = 0
    for t in trades:
        if t['pnl'] <= 0: cur_loss += 1
        else: max_consec_loss = max(max_consec_loss, cur_loss); cur_loss = 0
    max_consec_loss = max(max_consec_loss, cur_loss)
    return {
        'name': name, 'trades': len(trades), 'pnl': round(tp, 2),
        'wr': round(wr, 1), 'avg_w': round(aw, 2), 'avg_l': round(al, 2),
        'best': round(bt, 2), 'worst': round(wt, 2),
        'buy': buys, 'sell': sells, 'buy_pnl': round(buy_pnl, 2), 'sell_pnl': round(sell_pnl, 2),
        'avg_bar': round(avg_bar, 1), 'max_loss_streak': max_consec_loss,
    }

# ====================================================================
# 策略 1: sanqing-ea (三清EA) — M5 EMA9/21+ATR14, 3子策略优先级
# ====================================================================
def make_signal_sanqing(**kwargs):
    def fn(i, d):
        if i < 40: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; vol = d['vol']
        close = cl[i]; high = hi[i]; low = lo[i]; volume = vol[i] if i < len(vol) else 0

        ema9 = calc_ema(cl[:i+1], 9)
        ema21 = calc_ema(cl[:i+1], 21)
        if ema9 is None or ema21 is None: return None
        ema9_p = calc_ema(cl[:i], 9)
        ema21_p = calc_ema(cl[:i], 21)
        uptrend = ema9 > ema21; downtrend = ema9 < ema21
        cross_up = ema9_p is not None and ema21_p is not None and ema9_p <= ema21_p and ema9 > ema21
        cross_dn = ema9_p is not None and ema21_p is not None and ema9_p >= ema21_p and ema9 < ema21

        atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
        atr_val = get_atr_val(atr_vals, atr_warmup, i)
        if atr_val is None: return None

        body = abs(close - d['op'][i])
        candle_range = high - low
        body_atr_ratio = body / atr_val if atr_val > 0 else 0

        recent_bodies = [abs(cl[j] - d['op'][j]) for j in range(max(0, i-20), i+1)]
        body_median = sorted(recent_bodies)[len(recent_bodies)//2] if recent_bodies else 1
        body_median_ratio = body / body_median if body_median > 0 else 0
        prev_bodies = [abs(cl[j] - d['op'][j]) for j in range(max(0, i-5), i)]
        prev_body_max = max(prev_bodies) if prev_bodies else 1

        avg_vol = sum(vol[max(0, i-20):i+1]) / min(20, i+1) if i >= 5 else 0

        # BUY score
        buy_score = 0
        if uptrend: buy_score += 2
        elif cross_up: buy_score += 1
        if low <= ema9 * 1.002 and close > ema9: buy_score += 2
        if body_atr_ratio > 1.0: buy_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3: buy_score += 1
        if body_median_ratio >= 1.5 and body / prev_body_max >= 1.5 and candle_range > 0 and body / candle_range >= 0.5:
            buy_score += 2  # expansion

        sell_score = 0
        if downtrend: sell_score += 2
        elif cross_dn: sell_score += 1
        if high >= ema9 * 0.998 and close < ema9: sell_score += 2
        if body_atr_ratio > 1.0: sell_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3: sell_score += 1
        if body_median_ratio >= 1.5 and body / prev_body_max >= 1.5 and candle_range > 0 and body / candle_range >= 0.5:
            sell_score += 2

        if buy_score >= 5: return 'BUY'
        if sell_score >= 5: return 'SELL'
        return None
    return fn

# ====================================================================
# 策略 2: gold-pro-scalper / N30 — Z-Score + ADX 双模式
# ====================================================================
def make_signal_n30_gold(**kwargs):
    def fn(i, d):
        if i < 60: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']
        close = cl[i]
        sma20 = calc_sma(cl[:i+1], 20)
        std20 = calc_stddev(cl[:i+1], 20)
        if sma20 is None or std20 is None or std20 == 0: return None
        z_score = (close - sma20) / std20
        adx_val, pdi, ndi = get_adx_val(d.get('_adx'), i)
        if adx_val is None: return None
        ema50 = calc_ema(cl[:i+1], 50)
        if ema50 is None: return None
        if i < 30: return None
        donch_hi = max(hi[i-29:i+1]); donch_lo = min(lo[i-29:i+1])

        if adx_val < 22:
            if z_score <= -1.8 and close > ema50: return 'BUY'
            elif z_score >= 1.8 and close < ema50: return 'SELL'
        elif adx_val >= 28:
            di_spread = abs(pdi - ndi) if pdi is not None and ndi is not None else 0
            if di_spread >= 2.5:
                if close > donch_hi and pdi > ndi and close > ema50: return 'BUY'
                elif close < donch_lo and ndi > pdi and close < ema50: return 'SELL'
        return None
    return fn

# ====================================================================
# 策略 3: XAUUSD Trend Follow — H1 长线做多
# ====================================================================
def make_signal_xauusd_trend_follow(**kwargs):
    def fn(i, d):
        if i < 220: return None
        cl = d['cl']; candles = d['candles']
        close = cl[i]
        ema200 = calc_ema(cl[:i+1], 200)
        if ema200 is None or close <= ema200: return None
        adx_val, _, _ = get_adx_val(d.get('_adx'), i)
        if adx_val is not None and adx_val < 20: return None
        atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
        atr_val = get_atr_val(atr_vals, atr_warmup, i)
        if atr_val is None: return None

        # MACD cross
        macd = None
        try:
            k12, k26 = 2.0/13, 2.0/27
            e12 = e26 = cl[0]; ml = []
            for p in cl[:i+1]:
                e12 = (p - e12) * k12 + e12; e26 = (p - e26) * k26 + e26; ml.append(e12 - e26)
            if len(ml) >= 2:
                macd = {'macd': ml, 'signal': [ml[0]]}
                for v in ml[1:]: macd['signal'].append((v - macd['signal'][-1]) * 2.0/11 + macd['signal'][-1])
        except: pass

        macd_trigger = False
        if macd and len(macd['macd']) >= 3:
            if macd['macd'][-1] > macd['signal'][-1] and macd['macd'][-2] <= macd['signal'][-2]:
                macd_trigger = True

        # EMA9/21 cross
        ema9 = calc_ema(cl[:i+1], 9); ema21 = calc_ema(cl[:i+1], 21)
        ema_trigger = False
        if ema9 and ema21:
            ema9_p = calc_ema(cl[:i], 9); ema21_p = calc_ema(cl[:i], 21)
            if ema9_p and ema21_p and ema9_p <= ema21_p and ema9 > ema21:
                ema_trigger = True

        if macd_trigger or ema_trigger:
            return 'BUY'
        return None
    return fn

# ====================================================================
# 策略 4: xaubot-ai — XGBoost + Polars 81特征 ML
# ====================================================================
class XAUBotAIPipeline:
    """在历史数据上训练 XGBoost 模型, 然后生成交易信号."""

    def __init__(self, tf='H1'):
        self.tf = tf
        self.model = None
        self.feature_cols = []
        self.fitted = False
        self.confidence_threshold = 0.52
        self._signal_buffer = {}  # cache signals per index

    def compute_features(self, df):
        """Compute all available features from the xaubot-ai FeatureEngineer."""
        fe = _XAUFeatureEngineer()
        df = fe.calculate_all(df, include_ml_features=True)
        return df

    def get_feature_cols(self, df):
        exclude = {'time', 'open', 'high', 'low', 'close', 'volume',
                   'spread', 'target', 'target_return'}
        return [c for c in df.columns if c not in exclude and not c.startswith('_')]

    def train(self, df):
        """Train XGBoost model walk-forward."""
        if not HAS_XGB:
            print("    [xaubot-ai] XGBoost not installed, skipping")
            return False

        df_feat = self.compute_features(df)
        self.feature_cols = self.get_feature_cols(df_feat)

        # Create target: next bar direction
        df_feat = df_feat.with_columns([
            (pl.col("close").shift(-1) > pl.col("close")).cast(pl.Int32).alias("target")
        ])

        df_clean = df_feat.select(self.feature_cols + ["target"]).drop_nulls()
        if len(df_clean) < 200:
            print(f"    [xaubot-ai] Insufficient data: {len(df_clean)}")
            return False

        X = df_clean.select(self.feature_cols).to_numpy()
        y = df_clean.select("target").to_numpy().ravel()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Walk-forward: train=70%, test=30% with gap
        split = int(len(X) * 0.7)
        gap = min(50, len(X) - split - 10)
        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split+gap:], y[split+gap:]

        if len(X_train) < 100 or len(X_test) < 50:
            return False

        params = {
            'objective': 'binary:logistic', 'eval_metric': 'auc',
            'max_depth': 3, 'learning_rate': 0.024,
            'min_child_weight': 10, 'subsample': 0.7, 'colsample_bytree': 0.6,
            'reg_alpha': 1.0, 'reg_lambda': 5.0, 'gamma': 1.0,
            'tree_method': 'hist', 'device': 'cpu',
        }

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=self.feature_cols)
        dtest = xgb.DMatrix(X_test, label=y_test, feature_names=self.feature_cols)

        self.model = xgb.train(params, dtrain, num_boost_round=100,
                               evals=[(dtrain, 'train'), (dtest, 'eval')],
                               early_stopping_rounds=10, verbose_eval=0)
        self.fitted = True

        # Evaluate
        train_pred = (self.model.predict(dtrain) > 0.5).astype(int)
        test_pred = (self.model.predict(dtest) > 0.5).astype(int)
        train_acc = (train_pred == y_train).mean()
        test_acc = (test_pred == y_test).mean()
        print(f"    [xaubot-ai] Train acc: {train_acc:.1%}, Test acc: {test_acc:.1%}")
        return True

    def predict(self, idx, data):
        """Generate signal at given index using the trained model."""
        if idx in self._signal_buffer:
            return self._signal_buffer[idx]
        if not self.fitted or self.model is None:
            return None

        # Get Polars data for the TF
        tf_data = POLARS.get(self.tf)
        if tf_data is None or idx >= len(tf_data):
            return None

        df = tf_data[:idx+1]
        df_feat = self.compute_features(df)

        # Check we have all required features
        avail = [c for c in self.feature_cols if c in df_feat.columns]
        if len(avail) != len(self.feature_cols):
            return None

        last = df_feat.tail(1).select(self.feature_cols)
        X = last.to_numpy()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        dmatrix = xgb.DMatrix(X, feature_names=self.feature_cols)
        prob_up = float(self.model.predict(dmatrix)[0])
        prob_down = 1 - prob_up

        sig = None
        if prob_up > self.confidence_threshold:
            sig = 'BUY'
        elif prob_down > self.confidence_threshold:
            sig = 'SELL'

        self._signal_buffer[idx] = sig
        return sig


class _XAUFeatureEngineer:
    """Simplified Polars-based feature engineer matching xaubot-ai's FeatureEngineer."""

    def calculate_all(self, df, include_ml_features=True):
        df = self.calculate_rsi(df)
        df = self.calculate_atr(df)
        df = self.calculate_macd(df)
        df = self.calculate_bollinger_bands(df)
        df = self.calculate_ema_crossover(df)
        df = self.calculate_volume_features(df)
        if include_ml_features:
            df = self.calculate_ml_features(df)
        return df

    def calculate_rsi(self, df, p=14):
        alpha = 1.0 / p
        df = df.with_columns([pl.col("close").diff().alias("_delta")])
        df = df.with_columns([
            pl.when(pl.col("_delta") > 0).then(pl.col("_delta")).otherwise(0.0).alias("_gains"),
            pl.when(pl.col("_delta") < 0).then(-pl.col("_delta")).otherwise(0.0).alias("_losses"),
        ])
        df = df.with_columns([
            pl.col("_gains").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("_avg_gain"),
            pl.col("_losses").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("_avg_loss"),
        ])
        df = df.with_columns([
            pl.when(pl.col("_avg_loss") == 0).then(100.0)
            .otherwise(100.0 - 100.0 / (1.0 + pl.col("_avg_gain") / pl.col("_avg_loss")))
            .alias("rsi")
        ])
        return df.drop(["_delta", "_gains", "_losses", "_avg_gain", "_avg_loss"])

    def calculate_atr(self, df, p=14):
        alpha = 1.0 / p
        df = df.with_columns([pl.col("close").shift(1).alias("_pc")])
        df = df.with_columns([
            pl.max_horizontal(
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("_pc")).abs(),
                (pl.col("low") - pl.col("_pc")).abs()
            ).alias("_tr")
        ])
        df = df.with_columns([
            pl.col("_tr").ewm_mean(alpha=alpha, adjust=False, min_periods=p).alias("atr"),
            (pl.col("_tr").ewm_mean(alpha=alpha, adjust=False, min_periods=p) / pl.col("close") * 100).alias("atr_percent"),
        ])
        return df.drop(["_pc", "_tr"])

    def calculate_macd(self, df):
        df = df.with_columns([
            pl.col("close").ewm_mean(span=12, adjust=False).alias("_ema12"),
            pl.col("close").ewm_mean(span=26, adjust=False).alias("_ema26"),
        ])
        df = df.with_columns([
            (pl.col("_ema12") - pl.col("_ema26")).alias("macd")
        ])
        df = df.with_columns([
            pl.col("macd").ewm_mean(span=9, adjust=False).alias("macd_signal"),
        ])
        df = df.with_columns([
            (pl.col("macd") - pl.col("macd_signal")).alias("macd_histogram"),
        ])
        return df.drop(["_ema12", "_ema26"])

    def calculate_bollinger_bands(self, df, p=20, std=2.0):
        df = df.with_columns([
            pl.col("close").rolling_mean(p).alias("bb_middle"),
            pl.col("close").rolling_std(p).alias("_bb_std"),
        ])
        df = df.with_columns([
            (pl.col("bb_middle") + std * pl.col("_bb_std")).alias("bb_upper"),
            (pl.col("bb_middle") - std * pl.col("_bb_std")).alias("bb_lower"),
        ])
        df = df.with_columns([
            ((pl.col("bb_upper") - pl.col("bb_lower")) / pl.col("bb_middle")).alias("bb_width"),
            ((pl.col("close") - pl.col("bb_lower")) / (pl.col("bb_upper") - pl.col("bb_lower"))).alias("bb_percent_b"),
        ])
        return df.drop(["_bb_std"])

    def calculate_ema_crossover(self, df, fast=9, slow=21):
        df = df.with_columns([
            pl.col("close").ewm_mean(span=fast, adjust=False).alias(f"ema_{fast}"),
            pl.col("close").ewm_mean(span=slow, adjust=False).alias(f"ema_{slow}"),
        ])
        df = df.with_columns([(pl.col(f"ema_{fast}") > pl.col(f"ema_{slow}")).alias("_ema_above")])
        df = df.with_columns([pl.col("_ema_above").shift(1).alias("_ema_above_p")])
        df = df.with_columns([
            (pl.col("_ema_above") & ~pl.col("_ema_above_p").fill_null(False)).cast(pl.Int8).alias("ema_cross_bull"),
            (~pl.col("_ema_above") & pl.col("_ema_above_p").fill_null(False)).cast(pl.Int8).alias("ema_cross_bear"),
        ])
        return df.drop(["_ema_above", "_ema_above_p"])

    def calculate_volume_features(self, df, p=20):
        if "volume" not in df.columns:
            return df
        df = df.with_columns([pl.col("volume").rolling_mean(p).alias("volume_sma")])
        df = df.with_columns([
            (pl.col("volume") / pl.col("volume_sma")).alias("volume_ratio"),
            (pl.col("volume") > pl.col("volume").shift(1)).cast(pl.Int8).alias("volume_increasing"),
        ])
        df = df.with_columns([
            (pl.col("volume_ratio") > 1.5).cast(pl.Int8).alias("high_volume"),
        ])
        df = df.with_columns([
            pl.when(pl.col("close") > pl.col("open")).then(pl.col("volume")).otherwise(0).alias("buy_volume"),
            pl.when(pl.col("close") < pl.col("open")).then(pl.col("volume")).otherwise(0).alias("sell_volume"),
        ])
        df = df.with_columns([
            ((pl.col("buy_volume") - pl.col("sell_volume")) / (pl.col("buy_volume") + pl.col("sell_volume") + 1e-9)).alias("ofi_pseudo"),
        ])
        df = df.with_columns([
            pl.col("ofi_pseudo").rolling_mean(20).alias("ofi_trend"),
            pl.col("ofi_pseudo").rolling_std(20).alias("ofi_std"),
        ])
        return df

    def calculate_ml_features(self, df):
        df = df.with_columns([
            (pl.col("close") / pl.col("close").shift(1) - 1).alias("returns_1"),
            (pl.col("close") / pl.col("close").shift(5) - 1).alias("returns_5"),
            (pl.col("close") / pl.col("close").shift(20) - 1).alias("returns_20"),
            (pl.col("close") / pl.col("close").shift(1)).log().alias("log_returns"),
        ])
        df = df.with_columns([
            ((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low"))).alias("price_position"),
            pl.col("close").rolling_mean(20).alias("_sma20"),
        ])
        df = df.with_columns([
            (pl.col("close") / pl.col("_sma20") - 1).alias("dist_from_sma_20"),
            pl.col("log_returns").rolling_std(20).alias("volatility_20"),
            ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("normalized_range"),
            ((pl.col("high") - pl.col("low")) / pl.col("close")).rolling_mean(14).alias("avg_normalized_range"),
        ])
        df = df.with_columns([
            pl.col("close").shift(1).alias("close_lag_1"),
            pl.col("close").shift(2).alias("close_lag_2"),
            pl.col("close").shift(3).alias("close_lag_3"),
            pl.col("close").shift(5).alias("close_lag_5"),
        ])
        df = df.with_columns([
            (pl.col("high") > pl.col("high").shift(1)).cast(pl.Int8).alias("higher_high"),
            (pl.col("low") < pl.col("low").shift(1)).cast(pl.Int8).alias("lower_low"),
        ])
        df = df.with_columns([
            pl.col("higher_high").rolling_sum(5).alias("hh_count_5"),
            pl.col("lower_low").rolling_sum(5).alias("ll_count_5"),
        ])
        if "time" in df.columns:
            df = df.with_columns([
                pl.col("time").dt.hour().alias("hour"),
                pl.col("time").dt.weekday().alias("weekday"),
                ((pl.col("time").dt.hour() >= 8) & (pl.col("time").dt.hour() < 16)).cast(pl.Int8).alias("london_session"),
                ((pl.col("time").dt.hour() >= 13) & (pl.col("time").dt.hour() < 21)).cast(pl.Int8).alias("ny_session"),
            ])
        return df.drop(["_sma20"])


# ====================================================================
# 策略 5: Gold-Predictive-AutoResearch — 共识投票策略
# 核心逻辑: EMA趋势 + MACD/Stoch动量 + ADX/ATR波动 + BB/RSI安全过滤
# ====================================================================
def make_signal_gold_auto_research(**kwargs):
    """Gold-Predictive-AutoResearch 核心: 共识投票
    条件: trend_up AND mom_up AND vol_active AND safe_up = BUY
          trend_dn AND mom_dn AND vol_active AND safe_dn = SELL
    """
    def fn(i, d):
        if i < 60: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']
        close = cl[i]

        # EMA trend
        ema_f = calc_ema(cl[:i+1], 10)
        ema_s = calc_ema(cl[:i+1], 20)
        if ema_f is None or ema_s is None: return None
        trend_up = ema_f > ema_s
        trend_dn = ema_f < ema_s

        # MACD momentum
        k12, k26 = 2.0/13, 2.0/27
        e12 = e26 = cl[0]; ml = []
        for p in cl[:i+1]:
            e12 = (p - e12) * k12 + e12; e26 = (p - e26) * k26 + e26; ml.append(e12 - e26)
        macd_val = ml[-1]; macd_sig = ml[0] if len(ml) == 1 else ml[-1]
        if len(ml) >= 2:
            sig = [ml[0]]
            for v in ml[1:]: sig.append((v - sig[-1]) * 2.0/11 + sig[-1])
            macd_sig = sig[-1]

        # Stoch
        stoch_k = None
        lookback = 14
        if i >= lookback:
            w = d['candles'][i-lookback+1:i+1]
            hi_w = max(x.high for x in w); lo_w = min(x.low for x in w)
            stoch_k = 50.0 if hi_w == lo_w else (close - lo_w) / (hi_w - lo_w) * 100

        stoch_d_val = None
        if i >= lookback + 3:
            stok_list = []
            for j in range(i-lookback, i+1):
                w2 = d['candles'][j-lookback+1:j+1]
                hw = max(x.high for x in w2); lw = min(x.low for x in w2)
                if hw == lw: continue
                stok_list.append((d['cl'][j] - lw) / (hw - lw) * 100)
            if len(stok_list) >= 3:
                stoch_d_val = sum(stok_list[-3:]) / 3

        mom_up = (macd_val > macd_sig) or (stoch_k is not None and stoch_d_val is not None and stoch_k > stoch_d_val)
        mom_dn = (macd_val < macd_sig) or (stoch_k is not None and stoch_d_val is not None and stoch_k < stoch_d_val)

        # ADX volatility
        adx_val, _, _ = get_adx_val(d.get('_adx'), i)
        atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
        atr_val = get_atr_val(atr_vals, atr_warmup, i)
        atr_sma = None
        if atr_val and len(cl) > 20:
            atr_list_local = []
            for j in range(len(cl[20:i+1])):
                idx = j + 20 + atr_warmup
                v = get_atr_val(atr_vals, atr_warmup, idx)
                if v: atr_list_local.append(v)
            if atr_list_local:
                atr_sma = sum(atr_list_local[-20:]) / min(20, len(atr_list_local))

        vol_active = True
        if adx_val is not None and adx_val > 20: vol_active = True
        elif atr_val and atr_sma and atr_val > atr_sma: vol_active = True
        else: vol_active = False

        # RSI
        rsi_val = calc_rsi(cl[:i+1], 10)

        # BB safety
        bb_mid = calc_sma(cl[:i+1], 20)
        bb_std = calc_stddev(cl[:i+1], 20)
        bb_up = bb_mid + 2 * bb_std if bb_mid and bb_std else None
        bb_dn = bb_mid - 2 * bb_std if bb_mid and bb_std else None

        safe_up = True
        if bb_up and rsi_val and rsi_val >= 70: safe_up = False
        safe_dn = True
        if bb_dn and rsi_val and rsi_val <= 30: safe_dn = False

        if trend_up and mom_up and vol_active and safe_up:
            return 'BUY'
        if trend_dn and mom_dn and vol_active and safe_dn:
            return 'SELL'
        return None
    return fn

# ====================================================================
# 策略 6: BAKOMEGoldScalper — ICT 概念 (FVG + OB + Silver Bullet)
# ====================================================================
def make_signal_bakome_gold_scalper(**kwargs):
    """
    Ultimate ICT Gold Scalper v3.0 核心逻辑:
    - FVG (Fair Value Gap): 3-candle 模式, 中间蜡烛与两侧有gap
    - Order Block: 强势突破前的最后一根反向蜡烛
    - Silver Bullet: 伦敦8-10点, 纽约1-3点(按服务器时间)
    - 仅在这些窗口内交易
    """
    tf = kwargs.get('timeframe', 'H1')

    def detect_fvg(data, i):
        """检测 Fair Value Gap.
        条件: candle[i-2].low > candle[i].high (bullish FVG)
              或 candle[i-2].high < candle[i].low (bearish FVG)
        """
        if i < 3: return None
        c0 = data['candles'][i-2]; c1 = data['candles'][i-1]; c2 = data['candles'][i]
        # Bullish FVG: prev.prev low > current high (gap down then up)
        if c0.low > c2.high and c1.close < c1.open:
            return 'BUY'
        # Bearish FVG: prev.prev high < current low (gap up then down)
        if c0.high < c2.low and c1.close > c1.open:
            return 'SELL'
        return None

    def detect_order_block(data, i):
        """检测 Order Block.
        OB = 强势突破前的最后一根反向蜡烛
        """
        if i < 5: return None
        cl = data['cl']; op = data['op']
        # 连续2根同向大阳线后, 找之前最后一根阴线作为BUY OB
        if cl[i] > op[i] and cl[i-1] > op[i-1]:
            body_i = abs(cl[i] - op[i]); body_i1 = abs(cl[i-1] - op[i-1])
            avg_body = sum(abs(cl[j] - op[j]) for j in range(max(0, i-10), i)) / min(10, i)
            if body_i > avg_body * 1.5 and body_i1 > avg_body * 1.2:
                # 找之前的阴线
                for j in range(i-2, max(0, i-6), -1):
                    if cl[j] < op[j]:
                        return 'BUY', j  # BUY signal at OB
        # 连续2根同向大阴线后, 找之前最后一根阳线作为SELL OB
        if cl[i] < op[i] and cl[i-1] < op[i-1]:
            body_i = abs(cl[i] - op[i]); body_i1 = abs(cl[i-1] - op[i-1])
            avg_body = sum(abs(cl[j] - op[j]) for j in range(max(0, i-10), i)) / min(10, i)
            if body_i > avg_body * 1.5 and body_i1 > avg_body * 1.2:
                for j in range(i-2, max(0, i-6), -1):
                    if cl[j] > op[j]:
                        return 'SELL', j
        return None

    def is_silver_bullet_session(idx, data):
        """Silver Bullet 时段: 伦敦8-10点, 纽约1-3点."""
        ts = data['ts'][idx]
        dt = datetime.fromtimestamp(ts)
        h = dt.hour
        # Silver Bullet windows (server time, typically UTC+2/+3 for MT5)
        # London: 8-10 AM server = ~6-8 AM UTC
        # NY: 1-3 PM server = ~11 AM-1 PM UTC
        if h in [8, 9, 10]:  # London
            return 'london'
        if h in [13, 14, 15]:  # NY
            return 'ny'
        return None

    def fn(i, d):
        if i < 30: return None

        # 1. 检查 Silver Bullet 时段 (BAKOME 要求仅在这些时段交易)
        session = is_silver_bullet_session(i, d)
        if not session:
            return None

        # 2. FVG 检测
        fvg_sig = detect_fvg(d, i)
        if fvg_sig:
            # FVG 是强信号, 直接入场
            # ATR filter: 波动性不能太低
            atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
            atr_val = get_atr_val(atr_vals, atr_warmup, i)
            if atr_val and atr_val > 0:
                return fvg_sig

        # 3. Order Block 检测
        ob_result = detect_order_block(d, i)
        if ob_result:
            sig, ob_idx = ob_result
            # 确认价格回到 OB 区域
            ob_price = d['cl'][ob_idx]
            if sig == 'BUY' and d['lo'][i] <= ob_price * 1.003:
                atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
                atr_val = get_atr_val(atr_vals, atr_warmup, i)
                if atr_val and atr_val > 0:
                    return 'BUY'
            elif sig == 'SELL' and d['hi'][i] >= ob_price * 0.997:
                atr_vals = d.get('_atr'); atr_warmup = d.get('_atr_warmup', 0)
                atr_val = get_atr_val(atr_vals, atr_warmup, i)
                if atr_val and atr_val > 0:
                    return 'SELL'

        return None
    return fn


# ====================================================================
# 策略配置
# ====================================================================
"""
不可回测的策略 (原因):
  7. mt5-ai-xauusd-trader: 需要 MT5 实时连接 + PyTorch RL 模型权重, 无法独立回测
  8. EA_SCALPER_XAUUSD: 仅编译后 .ex5 文件, 无 MQL 源码
  9. Forex-Gold-Auto-Trader: 仅文档/README, 无可执行策略代码
  10. YQTS: 策略规格说明(YQTS_BRIEF.md), 参数定义但无执行代码
"""

# (name, signal_maker, min_bars, exit_mode, kwargs)
STRATEGIES = [
    ('sanqing-ea',               make_signal_sanqing,               80,  'trail', {'atr_trail': 4.0, 'atr_hardstop': 2.5}, ['M5']),
    ('N30_Gold_Scalper',         make_signal_n30_gold,              80,  'trail', {'atr_trail': 2.0, 'atr_hardstop': 3.0}, ['M1']),
    ('XAUUSD_TrendFollow',       make_signal_xauusd_trend_follow,  250, 'fixed', {'sl_atr': 1.25, 'tp_atr': 6.0, 'atr_trail': 0, 'atr_hardstop': 0}, ['H1']),
    ('Gold_AutoResearch',        make_signal_gold_auto_research,    80,  'trail', {'atr_trail': 3.5, 'atr_hardstop': 2.0}, []),
    ('BAKOME_GoldScalper',       make_signal_bakome_gold_scalper,   40,  'trail', {'atr_trail': 2.5, 'atr_hardstop': 1.5}, ['M5']),
]

# xaubot-ai 需要单独处理 (ML pipeline)
XAUBOT_TIMEFRAMES = ['M30', 'H1', 'H4']

# ====================================================================
def run():
    print("=" * 90)
    print("  GitHub 全部10个开源策略统一回测")
    print("=" * 90)
    print(f"\n  数据源: {DB_PATH}")

    # Derive all TFs to test (standard + native)
    all_test_tfs = set(TIMEFRAMES)
    for _, _, _, _, _, native_tfs in STRATEGIES:
        all_test_tfs.update(native_tfs)
    all_test_tfs = sorted(all_test_tfs)

    # Precompute indicators for all TFs
    for tf in all_test_tfs:
        if tf not in DATA:
            print(f"  {tf}: no data available")
            continue
        d = DATA[tf]
        if d['n'] < 100:
            print(f"  {tf}: insufficient data ({d['n']} candles)")
            continue
        d['_atr'], d['_atr_warmup'] = calc_atr_from_data(d['hi'], d['lo'], d['cl'], 14)
        d['_adx'] = calc_adx(d, 14)
        print(f"  {tf}: ATR+ADX precomputed ({d['n']} candles)")

    all_results = {}

    # ── Run standard strategies ──
    for tf in all_test_tfs:
        if tf not in DATA or DATA[tf].get('_atr') is None:
            continue
        data = DATA[tf]
        d0 = datetime.fromtimestamp(data['ts'][0])
        d1 = datetime.fromtimestamp(data['ts'][-1])
        print(f"\n{'='*90}")
        print(f"  [{tf}] {data['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")
        print(f"{'='*90}")

        for sname, sig_maker, min_bars, exit_mode, exit_kwargs, native_tfs in STRATEGIES:
            # Skip if this TF is not standard and not native for this strategy
            if tf not in TIMEFRAMES and tf not in native_tfs:
                continue
            # Skip BAKOME on higher TFs
            if sname == 'BAKOME_GoldScalper' and tf in ['H1', 'H4']:
                continue
            # N30 scalper skip on H4
            if sname == 'N30_Gold_Scalper' and tf in ['H4']:
                continue

            # Scale min_bars for TF
            tf_scale = {'M1': 0.25, 'M5': 0.5, 'M15': 0.75, 'M30': 1, 'H1': 2, 'H4': 4, 'D1': 24}.get(tf, 1)
            actual_min = max(min_bars, int(min_bars * tf_scale / 2))
            actual_min = min(actual_min, data['n'] // 3)

            sig_kwargs = {}
            if sname == 'BAKOME_GoldScalper':
                sig_kwargs['timeframe'] = tf

            sig_fn = sig_maker(**sig_kwargs)

            trades = run_backtest(data, sig_fn, min_bars=actual_min, name=sname, **exit_kwargs)
            metrics = summarize(trades, f"{sname}_{tf}")
            all_results[(sname, tf)] = metrics

            pnl_s = f"${metrics['pnl']:+.2f}"
            wr_s = f"{metrics['wr']:.1f}%"
            print(f"  {sname:<22} 交易:{metrics['trades']:>4}  盈亏:{pnl_s:>9}  胜率:{wr_s:>6}  "
                  f"B/S:{metrics['buy']}/{metrics['sell']}  "
                  f"均盈:{metrics['avg_w']:>7.2f}  均亏:{metrics['avg_l']:>7.2f}")

    # ── Run xaubot-ai (ML) separately ──
    print(f"\n{'='*90}")
    print(f"  xaubot-ai (XGBoost ML Pipeline)")
    print(f"{'='*90}")

    for tf in XAUBOT_TIMEFRAMES:
        if tf not in DATA:
            continue
        data = DATA[tf]
        print(f"\n  [{tf}] Training xaubot-ai model...")

        pipeline = XAUBotAIPipeline(tf=tf)
        success = pipeline.train(POLARS[tf])

        if success:
            def make_xaubot_signal(pipeline):
                def fn(i, d):
                    return pipeline.predict(i, d)
                return fn

            sig_fn = make_xaubot_signal(pipeline)
            actual_min = min(300, data['n'] // 3)
            trades = run_backtest(data, sig_fn, min_bars=actual_min, name='xaubot-ai',
                                  atr_trail=3.0, atr_hardstop=2.0)
            metrics = summarize(trades, f"xaubot-ai_{tf}")
            all_results[('xaubot-ai', tf)] = metrics

            pnl_s = f"${metrics['pnl']:+.2f}"
            wr_s = f"{metrics['wr']:.1f}%"
            print(f"  xaubot-ai{'':<14} 交易:{metrics['trades']:>4}  盈亏:{pnl_s:>9}  胜率:{wr_s:>6}  "
                  f"B/S:{metrics['buy']}/{metrics['sell']}  "
                  f"均盈:{metrics['avg_w']:>7.2f}  均亏:{metrics['avg_l']:>7.2f}")
        else:
            print(f"  xaubot-ai on {tf}: SKIPPED (training failed)")

    # ── Summary ──
    all_strategy_names = [s[0] for s in STRATEGIES] + ['xaubot-ai']
    not_testable = [
        ('7. mt5-ai-xauusd-trader', '需要 MT5 实时连接 + PyTorch RL 模型权重'),
        ('8. EA_SCALPER_XAUUSD', '仅编译后 .ex5 文件, 无 MQL 源码'),
        ('9. Forex-Gold-Auto-Trader', '仅文档/README, 无可执行策略代码'),
        ('10. YQTS', '策略规格说明(YQTS_BRIEF.md), 无执行代码'),
    ]

    summary_tfs = ['M5', 'M30', 'H1', 'H4']  # Show native + standard

    print("\n" + "=" * 120)
    print("  GitHub 全部10策略 × 多周期 汇总对比")
    print("=" * 120)

    hdr = f"{'策略':<22}"
    for tf in summary_tfs:
        hdr += f" | {tf+'交易':>5} {tf+'盈亏':>10} {tf+'胜率':>6}"
    print(hdr)
    print("-" * 120)

    for sname in all_strategy_names:
        row = f"{sname:<22}"
        for tf in summary_tfs:
            r = all_results.get((sname, tf))
            if r and r['trades'] > 0:
                row += f" | {r['trades']:>5} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}%"
            else:
                row += f" | {'-':>5} {'-':>10} {'-':>6}"
        print(row)

    print(f"\n  {'─'*90}")
    print(f"  {'不可回测的策略':<30}")
    print(f"  {'─'*90}")
    for name, reason in not_testable:
        print(f"  {name:<30} — {reason}")

    # Best per timeframe
    print(f"\n  各周期最佳移植策略:")
    for tf in summary_tfs:
        best = None
        for (sn, tff), r in all_results.items():
            if tff == tf and r['trades'] >= 3:
                if best is None or r['pnl'] > best['pnl']:
                    best = {**r, 'name': sn}
        if best:
            print(f"    {tf}: {best['name']}  ${best['pnl']:+.2f}  ({best['trades']} trades, {best['wr']}% WR)")

    # JSON output
    all_tfs_in_results = sorted(set(tf for _, tf in all_results))
    output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'description': 'GitHub 全部10个开源策略统一回测',
        'data_ranges': {
            tf: {
                'candles': DATA[tf]['n'],
                'from': datetime.fromtimestamp(DATA[tf]['ts'][0]).strftime('%Y-%m-%d'),
                'to': datetime.fromtimestamp(DATA[tf]['ts'][-1]).strftime('%Y-%m-%d'),
            }
            for tf in all_tfs_in_results if tf in DATA
        },
        'results_by_strategy': {},
        'results_by_timeframe': {},
        'not_testable': [{'name': n, 'reason': r} for n, r in not_testable],
    }
    for (sn, tf), r in all_results.items():
        if sn not in output['results_by_strategy']:
            output['results_by_strategy'][sn] = {}
        output['results_by_strategy'][sn][tf] = {k: v for k, v in r.items() if k != 'name'}
        if tf not in output['results_by_timeframe']:
            output['results_by_timeframe'][tf] = {}
        output['results_by_timeframe'][tf][sn] = {k: v for k, v in r.items() if k != 'name'}

    out_path = os.path.join(os.path.dirname(__file__), 'github_all_strategies_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存到 {out_path}")

    return all_results


if __name__ == '__main__':
    run()
