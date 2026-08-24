# XAUUSD 量化交易系统 — 策略手册

> 版本: 2026-08-11 | 系统: v2.7.9

---

## 1. 全局系统规则

### 1.1 三轨架构

- **轨1 DataFactory**：独立线程，增量拉取 K 线，TA-Lib 统一计算 26 个指标
- **轨2 策略员**：主引擎循环，`get_indicator(key)` 读缓存，评分达标出门票
- **轨3 运动员**：tick 验证层，`_verify_entry` 实时重算入场条件，10 秒过期作废

### 1.2 数据源铁律

**DataFactory + TA-Lib 是唯一数据来源。** 所有策略指标通过 `get_indicator(key)` 读取，禁止自算 RSI/MFI/BB/EMA/ATR/ADX/Stoch/MACD 等指标。

### 1.3 出场逻辑体系

```
check_ema20_exit()
├── ① 趋势出场（穿轨后回抽 + MFI 确认）
├── ② 中线出场（价格先越过中线再返回）
└── ③ 半宽出场（逆势走了入场时 BB 宽度的一半）
```

通用出场（基类内置）：保本出场、利润回撤止盈（动态阈值）、ATR 移动止盈、硬止损。

### 1.4 策略命名规范（强制）

```
strategies/{YYYYMMDD}_{策略名}_v{版本号}.py
```

修改策略 → 原文件移入 `strategies/backup/`，生成新版本号文件。

### 1.5 策略说明文档（双语强制）

```
strategies/docs/{YYYYMMDD}_{策略名}_v{版本号}.md
```

和策略 `.py` 同目录，backup 在 `strategies/docs/backup/`。

**双语要求（强制）：** 每个策略文档的 frontmatter 必须同时填写 `desc`（中文简介）和 `desc_en`（英文简介）。表格中的中文文本需同步更新 `dashboard/frontend/src/utils/strategyTranslations.ts` 的翻译映射，确保英文界面正常显示。

---

---

## 2. 策略总览（30 个）

### 2.1 启用策略（9 个）

| Magic | 策略 | 周期 | 说明 |
|:-----:|:-----|:----:|:-----|
| 660707 | M30_rsi_bb | M30 | M30 RSI+布林带均值回归，7因子评分系统，动态利润回撤止盈 |
| 660904 | rsi_grading_m30_upgraded | M30 | RSI极端+2/边界+1/正常0，固定阈值3分，BB扩张+MFI方向过滤 |
| 661003 | mfi_bb_m30_upgraded | M30 | 超跌反弹，收盘穿轨入场，BB扩张保护，中线出场固定参照 |
| 661102 | m30_bb_deepreturn_optimized | M30 | BB均值回归+MFI确认+方向感知动态阈值 |
| 661202 | stoch_trend_h1_optimized | H1 | 多周期 Stoch 评分系统，ADX>20，Stoch(14,3,3) |
| 880107 | sanqing_h1 | H1 | EMA9/21趋势+ATR14评分+双重止盈 |
| 880108 | sanqing_h1_upgraded | H1 | EMA9/21趋势评分+高位拦截+动态利润回撤止盈 |
| 880301 | h1_breakout | H1 | 区间突破+ADX确认，EMA20追踪止损，6分制评分 |
| 880306 | gold_auto_research | H1 | 4因子共识投票+高位拦截(price_position>0.88且偏离EMA21>4×ATR禁BUY) |

### 2.2 禁用策略（21 个）

| Magic | 策略 | 周期 | 说明 |
|:-----:|:-----|:----:|:-----|
| 660902 | rsi_grading_m30 | M30 | RSI分级评分，ADX>28趋势门禁（原版） |
| 660903 | rsi_grading_m30_optimized | M30 | RSI分级评分优化版 |
| 661001 | mfi_bb_m30 | M30 | MFI极端值+BB触轨均值回归（原版） |
| 661002 | mfi_bb_m30_optimized | M30 | MFI阈值收紧至85/15 |
| 661101 | m30_bb_deepreturn | M30 | BB极值+MFI极值超跌反弹（原版） |
| 661201 | stoch_trend_h1 | M30 | 多周期 Stoch 回调顺势（原版） |
| 661204 | stoch_trend_h1_upgraded | H1 | ADX>25过滤+Stoch极值反转+BBI方向确认 |
| 661301 | momentum_pulse_pro | M30 | 7维度多因子评分，三层TP |
| 661401 | viprasol_sniper | M30 | 7因子评分，多级RR出场 |
| 661501 | entry_score_pro | M30 | 5因子加权评分0-100 |
| 661601 | multi_confluence_quant | M30 | 14因子综合评分 |
| 777004 | bakome_backup | M30 | ICT FVG+OB+Silver Bullet（原版） |
| 777005 | xaubot_backup | M30 | XGBoost ML 模型 |
| 777006 | bakome_backup_optimized | M30 | ICT FVG+OB+Silver Bullet 优化版 |
| 880101 | sanqing_h1_original | H1 | 6因子评分+ATR追踪止损（原版） |
| 880201 | sanqing_original | M5 | M5 4策略优先级调度 |
| 880202 | timeprofit_ea | M5 | H2趋势+整数关口箱体 |
| 880302 | m30_vol_return | M30 | BB触及+ATR扩张+RSI背离 |
| 880303 | bakome_gold_scalper_original | M5 | 完整ICT策略 |
| 880304 | bakome_trinity_ea_original | M5 | 多资产趋势追踪 |
| 880305 | gold_auto_research_original | H1 | 4因子共识投票（原版，无高位拦截） |

---

## 3. 策略分类

### 3.1 趋势策略
- sanqing_h1 / sanqing_h1_upgraded / h1_breakout / stoch_trend_h1_optimized / gold_auto_research

### 3.2 反转策略
- M30_rsi_bb / mfi_bb_m30_upgraded / m30_bb_deepreturn_optimized / rsi_grading_m30_upgraded

### 3.3 评分模型
- entry_score_pro / momentum_pulse_pro / multi_confluence_quant / viprasol_sniper

### 3.4 ML 策略
- xaubot_backup（XGBoost）

### 3.5 移植策略
- sanqing_original / timeprofit_ea / bakome 系列（MQL4 移植）

---

## 4. 版本管理

详细规范见 `strategies/STRATEGY_VERSIONING.md`：

- Magic Number 编号规则（PP+NN+VV）
- 策略文件命名规范（YYYYMMDD_name_v1）
- 说明文档规范（strategies/docs/ 目录）
- 删除规则（移至 backup 可恢复）
- 导入规则（自动规范命名）
- CHANGELOG 规范

---

## 5. 策略更新指南

1. 修改策略 `.py` → 原文件移入 `strategies/backup/`
2. 生成新版本号文件（如 v11 → v12）
3. 更新 `STRATEGY_CHANGELOG`
4. 更新 `strategies/docs/` 下的说明文档
5. 重启引擎生效

---

数据源: 全部指标从 DataFactory TA-Lib 读取