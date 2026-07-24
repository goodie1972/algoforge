#!/usr/bin/env python
"""Update BB expansion threshold in all strategy files: 14→3, 1.2→1.05"""
import re, os

files = [
    "strategies/m30_mfi_bb_upgraded_20260718.py",
    "strategies/m30_bb_deepreturn_optimized_20260711.py",
    "strategies/rsi_grading_m30_upgraded_20260718.py",
    "strategies/bakome_backup.py",
    "strategies/bakome_backup_optimized_20260711.py",
]

for fp in files:
    if not os.path.exists(fp):
        print(f"! {fp} not found"); continue
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()

    orig = content

    # _BB_EXPAND_THRESHOLD
    content = content.replace("_BB_EXPAND_THRESHOLD = 0.20", "_BB_EXPAND_THRESHOLD = 0.05")

    # bb_width_ratio > 1.2 → bb_width_ratio > 1.05
    content = re.sub(r'bb_width_ratio\s*>\s*1\.\s*2(\s*[^.\d])', r'bb_width_ratio > 1.05\1', content)
    content = re.sub(r'bb_width_ratio\s*>=\s*1\.\s*2(\s*[^.\d])', r'bb_width_ratio > 1.05\1', content)
    content = re.sub(r'["\']bb_width_ratio["\']\s*>\s*1\.\s*2(\s*[^.\d])', r'bb_width_ratio > 1.05\1', content)

    if content != orig:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"+ {fp} updated")
    else:
        print(f"= {fp} no change")