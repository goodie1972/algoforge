#!/usr/bin/env python
"""Fix: AND → 2/3 scoring. 3 conditions: ratio>1.05 + direction=up + MFI一致. 满足2个才拦截"""
import re, os, ast

files = [
    "strategies/m30_mfi_bb_upgraded_20260718.py",
    "strategies/m30_bb_deepreturn_optimized_20260711.py",
    "strategies/rsi_grading_m30_upgraded_20260718.py",
    "strategies/bakome_backup.py",
    "strategies/bakome_backup_optimized_20260711.py",
]

def compile_check(fp):
    with open(fp, 'r', encoding='utf-8') as f:
        ast.parse(f.read())

for fp in files:
    if not os.path.exists(fp):
        print(f"! {fp} not found")
        continue
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    orig = content

    # Pattern 1: mfi_bb_upgraded (_block_short/_block_long version with bb=bb)
    old1 = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        if _bwr and _bwr > 1.2 and _bwd == "up" and _mfi is not None and _mfi_dir and bb:
            if close > bb["mid"] and _mfi_dir in ("up", "flat"):
                _block_short = True
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升({_mfi:.0f})，禁做空")
            if close < bb["mid"] and _mfi_dir in ("down", "flat"):
                _block_long = True
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降({_mfi:.0f})，禁做多")"""

    new1 = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and bb:
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if (close > bb["mid"] and _mfi_dir in ("up", "flat")) or (close < bb["mid"] and _mfi_dir in ("down", "flat")): _score += 1
            if _score >= 2:
                if close > bb["mid"] and _mfi_dir in ("up", "flat"):
                    _block_short = True
                    logger.info(f"[{self.name}] BB(2/3)+价格>中轴+MFI↑({_mfi:.0f})，禁做空")
                if close < bb["mid"] and _mfi_dir in ("down", "flat"):
                    _block_long = True
                    logger.info(f"[{self.name}] BB(2/3)+价格<中轴+MFI↓({_mfi:.0f})，禁做多")"""

    content = content.replace(old1, new1)

    # Pattern 2: bakome version (return early)
    old2 = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr and _bwr > 1.2 and _bwd == "up" and _mfi is not None and _mfi_dir and _bb:
            _close = candles[-1].close
            if _close > _bb["mid"] and _mfi_dir in ("up", "flat"):
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升({_mfi:.0f})，禁做空，跳过FVG/OB")
                return (None, 0, 0, [], [], {})
            if _close < _bb["mid"] and _mfi_dir in ("down", "flat"):
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降({_mfi:.0f})，禁做多，跳过FVG/OB")
                return (None, 0, 0, [], [], {})"""

    new2 = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and _bb:
            _close = candles[-1].close
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if (_close > _bb["mid"] and _mfi_dir in ("up", "flat")) or (_close < _bb["mid"] and _mfi_dir in ("down", "flat")): _score += 1
            if _score >= 2:
                if _close > _bb["mid"] and _mfi_dir in ("up", "flat"):
                    logger.info(f"[{self.name}] BB(2/3)+价格>中轴+MFI↑({_mfi:.0f})，禁做空，跳过FVG/OB")
                    return (None, 0, 0, [], [], {})
                if _close < _bb["mid"] and _mfi_dir in ("down", "flat"):
                    logger.info(f"[{self.name}] BB(2/3)+价格<中轴+MFI↓({_mfi:.0f})，禁做多，跳过FVG/OB")
                    return (None, 0, 0, [], [], {})"""

    content = content.replace(old2, new2)

    # Pattern 3: rsi_grading + m30_bb_deepreturn version (short_factors/long_factors or short_detail/long_detail)
    old3 = """        _bwr = self.get_indicator("bb_width_ratio")
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

    new3 = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and _bb:
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if (close > _bb.get("mid",0) and _mfi_dir in ("up", "flat")) or (close < _bb.get("mid",0) and _mfi_dir in ("down", "flat")): _score += 1
            if _score >= 2:
                if close > _bb.get("mid",0) and _mfi_dir in ("up", "flat"):
                    short_score = 0
                    short_factors.append("BBW-MFI-UP↑")
                    logger.info(f"[{self.name}] BB(2/3)+价格>中轴+MFI↑({_mfi:.0f})，禁做空")
                if close < _bb.get("mid",0) and _mfi_dir in ("down", "flat"):
                    long_score = 0
                    long_factors.append("BBW-MFI-DN↓")
                    logger.info(f"[{self.name}] BB(2/3)+价格<中轴+MFI↓({_mfi:.0f})，禁做多")"""

    content = content.replace(old3, new3)

    # Also fix detailed versions
    old3d = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        if _bwr and _bwr > 1.2 and _bwd == "up" and _mfi is not None and _mfi_dir:
            if close > bb["mid"] and _mfi_dir in ("up", "flat"):
                short_score = 0
                short_detail.append("BBW-MFI-UP↑")
                logger.info(f"[{self.name}] BB扩张+价格>中轴+MFI上升({_mfi:.0f})，禁做空")
            if close < bb["mid"] and _mfi_dir in ("down", "flat"):
                long_score = 0
                long_detail.append("BBW-MFI-DN↓")
                logger.info(f"[{self.name}] BB扩张+价格<中轴+MFI下降({_mfi:.0f})，禁做多")"""

    new3d = """        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir:
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if (close > bb.get("mid",0) and _mfi_dir in ("up", "flat")) or (close < bb.get("mid",0) and _mfi_dir in ("down", "flat")): _score += 1
            if _score >= 2:
                if close > bb.get("mid",0) and _mfi_dir in ("up", "flat"):
                    short_score = 0
                    short_detail.append("BBW-MFI-UP↑")
                    logger.info(f"[{self.name}] BB(2/3)+价格>中轴+MFI↑({_mfi:.0f})，禁做空")
                if close < bb.get("mid",0) and _mfi_dir in ("down", "flat"):
                    long_score = 0
                    long_detail.append("BBW-MFI-DN↓")
                    logger.info(f"[{self.name}] BB(2/3)+价格<中轴+MFI↓({_mfi:.0f})，禁做多")"""

    content = content.replace(old3d, new3d)

    # 1.2 → 1.05 fallback for any remaining
    content = re.sub(r'> 1\.2 ', '> 1.05 ', content)
    content = re.sub(r'> 1\\.2 ', '> 1.05 ', content)

    if content != orig:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(content)
        try:
            compile_check(fp)
            print(f"+ {fp} OK (2/3 scoring)")
        except SyntaxError as e:
            print(f"! {fp} SYNTAX ERROR: {e}")
    else:
        print(f"= {fp} no change")

print("\nDone")