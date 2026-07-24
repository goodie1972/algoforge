#!/usr/bin/env python
"""Step 1: Trim _talib_indicators in services/data_factory.py"""
import re

with open('services/data_factory.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the _talib_indicators function boundaries
start = content.find('def _talib_indicators(candles: list, tf: str) -> dict:')
if start < 0:
    print("ERROR: _talib_indicators not found")
    exit(1)

# Find next top-level function (def at column 0) after this
rest = content[start:]
# Split into lines, find first line starting with 'def ' that's not the current one
lines = rest.split('\n')
end_offset = len(rest)  # default: end of file
for i in range(1, len(lines)):
    if lines[i].startswith('def ') and not lines[i].startswith('    def '):
        end_offset = sum(len(l) + 1 for l in lines[:i])
        break

new_func = '''def _talib_indicators(candles: list, tf: str) -> dict:
    \"\"\"精简版：只算 close/trend/bb_width/direction/ratio，其他由 F043 覆盖\"\"\"
    import numpy as np
    import talib
    closes = np.array([c.close for c in candles], dtype=float)
    if len(closes) < 30:
        return {}

    result = {}

    # BB(20,2) — 仅用于 bb_width / direction / ratio(SMA3)
    try:
        upper, mid, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        bb_width = float(upper[-1] - lower[-1])
        result["bb_width"] = bb_width
        if len(upper) > 2:
            _prev = float(upper[-2] - lower[-2])
            result["bb_width_direction"] = "up" if bb_width > _prev else ("down" if bb_width < _prev else "flat")
        else:
            result["bb_width_direction"] = "flat"
        # BB 宽度比率：当前 / 过去3根均值（SMA3，更快响应扩张）
        if len(upper) > 4:
            _widths_arr = upper - lower
            _avg3 = float(talib.SMA(_widths_arr, timeperiod=3)[-1])
            result["bb_width_ratio"] = round(bb_width / _avg3, 3) if _avg3 > 0 else 1.0
        else:
            result["bb_width_ratio"] = 1.0
    except Exception:
        pass

    # close + trend（SMA14）
    result["close"] = float(closes[-1])
    try:
        s14_v = float(talib.SMA(closes, timeperiod=14)[-1])
        result["trend"] = "UP" if closes[-1] > s14_v else "DOWN"
    except Exception:
        result["trend"] = "NEUTRAL"

    return result
'''

content = content[:start] + new_func + content[start + end_offset:]
with open('services/data_factory.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("OK - _talib_indicators trimmed")