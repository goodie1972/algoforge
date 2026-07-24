#!/usr/bin/env python
"""Update all 5 strategies: threshold 1.2->1.05 + 3-way AND -> 2/3 scoring"""
import re, os

files = [
    "services/data_factory.py",      # TA-Lib SMA14→SMA3, ratio1.2→1.05
]

# ── Step 1: DataFactory _talib_indicators → SMA3 + 1.05 ──
with open("services/data_factory.py", "r", encoding="utf-8") as f:
    content = f.read()
orig = content

# Replace SMA14 with SMA3 and 1.2 with 1.05
content = content.replace(
    "_avg14 = float(talib.SMA(_widths_arr, timeperiod=14)[-1])",
    "_avg3 = float(talib.SMA(_widths_arr, timeperiod=3)[-1])"
)
content = content.replace(
    'result["bb_width_ratio"] = round(bb_width / _avg14, 3) if _avg14 > 0 else 1.0',
    'result["bb_width_ratio"] = round(bb_width / _avg3, 3) if _avg3 > 0 else 1.0'
)

if content != orig:
    with open("services/data_factory.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("+ services/data_factory.py updated (SMA3 + 1.05)")
else:
    print("= services/data_factory.py no change")

# ── Step 2: All 5 strategies → threshold + 2/3 scoring ──
strategy_files = [
    ("strategies/m30_mfi_bb_upgraded_20260718.py", "_BB_EXPAND_THRESHOLD"),
    ("strategies/m30_bb_deepreturn_optimized_20260711.py", "embedded"),
    ("strategies/rsi_grading_m30_upgraded_20260718.py", "embedded"),
    ("strategies/bakome_backup.py", "embedded"),
    ("strategies/bakome_backup_optimized_20260711.py", "embedded"),
]

for fp, style in strategy_files:
    if not os.path.exists(fp):
        print(f"! {fp} not found")
        continue
    with open(fp, "r", encoding="utf-8") as f:
        content = f.read()
    orig = content

    # Update _BB_EXPAND_THRESHOLD
    content = content.replace("_BB_EXPAND_THRESHOLD = 0.20", "_BB_EXPAND_THRESHOLD = 0.05")
    content = content.replace("_BB_EXPAND_THRESHOLD = 0.05   # 开口扩张 >5% 时禁用同向入场",
                              "_BB_EXPAND_THRESHOLD = 0.05   # 开口扩张 >5%（SMA3）时拦截")

    # Threshold 1.2 → 1.05
    content = re.sub(r'(, and _bwr > )1\.2( and)', r'\1 1.05 \2', content)
    content = re.sub(r'(and _bwr > )1\.2 ([^1])', r'\1 1.05 \2', content)
    content = re.sub(r'(> )1\.2 (and )', r'\1 1.05 \2', content)

    # 3-way AND → 2/3 scoring
    # Pattern for strategies with _block_short/_block_long
    if "_block_short" in content:
        old = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        if _bwr and _bwr > 1.05 and _bwd == "up" and _mfi is not None and _mfi_dir and bb:
            if close > bb["mid"] and _mfi_dir in ("up", "flat"):
                _block_short = True
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升({_mfi:.0f})，禁做空")
            if close < bb["mid"] and _mfi_dir in ("down", "flat"):
                _block_long = True
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降({_mfi:.0f})，禁做多")"""

        new = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir is not None:
            # 3选2：ratio>1.05 + 方向扩张 + MFI方向一致
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if close > bb.get("mid", 0) and _mfi_dir in ("up", "flat"): _score += 1
            if close < bb.get("mid", 0) and _mfi_dir in ("down", "flat"): _score += 1
            if _score >= 2:
                if close > bb.get("mid", 0) and _mfi_dir in ("up", "flat"):
                    _block_short = True
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格>中轴+MFI上升({_mfi:.0f})，禁做空")
                if close < bb.get("mid", 0) and _mfi_dir in ("down", "flat"):
                    _block_long = True
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格<中轴+MFI下降({_mfi:.0f})，禁做多")"""
        content = content.replace(old, new)

    # Pattern for bakome (returns early)
    if "禁做空，跳过FVG/OB" in content:
        old = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr and _bwr > 1.05 and _bwd == "up" and _mfi is not None and _mfi_dir and _bb:
            _close = candles[-1].close
            if _close > _bb["mid"] and _mfi_dir in ("up", "flat"):
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升({_mfi:.0f})，禁做空，跳过FVG/OB")
                return (None, 0, 0, [], [], {})
            if _close < _bb["mid"] and _mfi_dir in ("down", "flat"):
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降({_mfi:.0f})，禁做多，跳过FVG/OB")
                return (None, 0, 0, [], [], {})"""
        new = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and _bb:
            _close = candles[-1].close
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if _close > _bb["mid"] and _mfi_dir in ("up", "flat"): _score += 1
            if _close < _bb["mid"] and _mfi_dir in ("down", "flat"): _score += 1
            if _score >= 2:
                if _close > _bb["mid"] and _mfi_dir in ("up", "flat"):
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格>中轴+MFI上升({_mfi:.0f})，禁做空，跳过FVG/OB")
                    return (None, 0, 0, [], [], {})
                if _close < _bb["mid"] and _mfi_dir in ("down", "flat"):
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格<中轴+MFI下降({_mfi:.0f})，禁做多，跳过FVG/OB")
                    return (None, 0, 0, [], [], {})"""
        content = content.replace(old, new)

    # Pattern for strategies with short_factors/long_factors
    if "BBW-MFI-UP↑" in content or "BB扩张+价格>中轴+MFI上升" in content:
        if "_, flat" in content or "up\", \"flat" in content:
            old = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr and _bwr > 1.2 and _bwd == "up" and _mfi is not None and _mfi_dir and _bb:
            _price_above_mid = close > _bb["mid"]
            if _price_above_mid and _mfi_dir in ("up", "flat"):
                short_score = 0
                short_factors.append("BBW-MFI-UP↑")
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升，禁做空")
            if not _price_above_mid and _mfi_dir in ("down", "flat"):
                long_score = 0
                long_factors.append("BBW-MFI-DN↓")
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降，禁做多")"""
        new = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and _bb:
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if close > _bb.get("mid", 0) and _mfi_dir in ("up", "flat"): _score += 1
            if close < _bb.get("mid", 0) and _mfi_dir in ("down", "flat"): _score += 1
            if _score >= 2:
                if close > _bb.get("mid", 0) and _mfi_dir in ("up", "flat"):
                    short_score = 0
                    short_factors.append("BBW-MFI-UP↑")
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格>中轴+MFI上升({_mfi:.0f})，禁做空")
                if close < _bb.get("mid", 0) and _mfi_dir in ("down", "flat"):
                    long_score = 0
                    long_factors.append("BBW-MFI-DN↓")
                    logger.info(f"[{self.name}] BB扩张(2/3)+价格<中轴+MFI下降({_mfi:.0f})，禁做多")"""
        content = content.replace(old, new)

    if content != orig:
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"+ {fp} updated")
    else:
        print(f"= {fp} no change")

# ── Step 3: _sync_indicators trim hist_widths from 14 to 3 ──
with open("services/data_factory.py", "r", encoding="utf-8") as f:
    content = f.read()
orig = content
content = content.replace(
    'if len(_hist_widths) > 14:\n                        _hist_widths = _hist_widths[-14:]',
    'if len(_hist_widths) > 3:\n                        _hist_widths = _hist_widths[-3:]'
)
if content != orig:
    with open("services/data_factory.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("+ services/data_factory.py _sync_indicators updated")
else:
    print("= services/data_factory.py _sync_indicators no change")

print("\nDone. Compile check...")