import sqlite3, os
import talib as ta
import numpy as np
from datetime import datetime, timezone

conn = sqlite3.connect(os.path.join('data','market_data.db'))
rows = conn.execute('''SELECT timestamp, open, high, low, close, volume 
    FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp ASC''').fetchall()

opens = np.array([r[1] for r in rows], dtype=float)
highs = np.array([r[2] for r in rows], dtype=float)
lows = np.array([r[3] for r in rows], dtype=float)
closes = np.array([r[4] for r in rows], dtype=float)
volumes = np.array([r[5] for r in rows], dtype=float)

adx_all = ta.ADX(highs, lows, closes, timeperiod=14)
pdi_all = ta.PLUS_DI(highs, lows, closes, timeperiod=14)
ndi_all = ta.MINUS_DI(highs, lows, closes, timeperiod=14)
rsi_all = ta.RSI(closes, timeperiod=14)
mfi_all = ta.MFI(highs, lows, closes, volumes, timeperiod=14)
upper_all, mid_all, lower_all = ta.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)

start_ts = int(datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc).timestamp())
end_ts = int(datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc).timestamp())

print("=== 做空机会（SELL）===")
sell_count = 0
for i in range(14, len(rows)):
    ts = rows[i][0]
    if ts < start_ts or ts > end_ts:
        continue
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    adx = adx_all[i]; pdi = pdi_all[i]; ndi = ndi_all[i]
    rsi = rsi_all[i]; mfi = mfi_all[i]; close = closes[i]
    upper = upper_all[i]; lower = lower_all[i]
    if np.isnan(adx) or np.isnan(pdi): continue
    di_diff = abs(pdi - ndi)
    if not (adx > 20 and di_diff > 5):
        continue
    if pdi > ndi:  # 多头主导，可做空
        rsi_ok = rsi > 70; mfi_ok = mfi > 75
        close_ok = close >= upper - 5
        if rsi_ok or mfi_ok or close_ok:
            sell_count += 1
            if sell_count <= 20:
                r_mark = "V" if rsi_ok else "X"
                m_mark = "V" if mfi_ok else "X"
                c_mark = "V" if close_ok else "X"
                print(f"  {dt.strftime('%m-%d %H:%M')} close={close:.1f} "
                      f"ADX={adx:.1f} +DI={pdi:.1f} -DI={ndi:.1f} "
                      f"RSI={rsi:.1f}({r_mark}>70) MFI={mfi:.1f}({m_mark}>75) "
                      f"close>=上轨-5?{c_mark} 上轨={upper:.1f}")

print(f"\n做空信号（至少一项条件接近）: {sell_count} 次")

# 检查 BUY
print("\n=== 做多机会（BUY）===")
buy_count = 0
for i in range(14, len(rows)):
    ts = rows[i][0]
    if ts < start_ts or ts > end_ts:
        continue
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    adx = adx_all[i]; pdi = pdi_all[i]; ndi = ndi_all[i]
    rsi = rsi_all[i]; mfi = mfi_all[i]; close = closes[i]; lower = lower_all[i]
    if np.isnan(adx) or np.isnan(pdi): continue
    di_diff = abs(pdi - ndi)
    if not (adx > 20 and di_diff > 5):
        continue
    if ndi > pdi:
        rsi_ok = rsi < 30; mfi_ok = mfi < 25
        close_ok = close <= lower + 5
        if rsi_ok or mfi_ok or close_ok:
            buy_count += 1
            if buy_count <= 20:
                r_mark = "V" if rsi_ok else "X"
                m_mark = "V" if mfi_ok else "X"
                c_mark = "V" if close_ok else "X"
                print(f"  {dt.strftime('%m-%d %H:%M')} close={close:.1f} "
                      f"ADX={adx:.1f} +DI={pdi:.1f} -DI={ndi:.1f} "
                      f"RSI={rsi:.1f}({r_mark}<30) MFI={mfi:.1f}({m_mark}<25) "
                      f"close<=下轨+5?{c_mark} 下轨={lower:.1f}")

print(f"\n做多信号（至少一项条件接近）: {buy_count} 次")