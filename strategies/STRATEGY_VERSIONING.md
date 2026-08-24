# 策略版本管理规范

## Magic Number 编号规则

6位数字：`PP` + `NN` + `VV`

| 位段 | 位数 | 含义 |
|------|------|------|
| PP   | 2    | 策略来源：`66` = 自研，`88` = 借鉴 |
| NN   | 2    | 策略上线序号 |
| VV   | 2    | 版本号，从01开始按修改次数递增 |

### 完整对照表（2026-08-11 更新）

| 策略名 | 类型 | PP | NN | 最新 Magic | 版本范围 | 引擎状态 |
|--------|------|----|----|-----------|---------|---------|
| M30_rsi_bb | 自研 | 66 | 07 | 660707 | v1~v13 | 启用 |
| gold_auto_research | 借鉴 | 88 | 03 | 880306 | v1~v6 | 启用 |
| h1_breakout | 借鉴 | 88 | 03 | 880301 | v1 | 启用 |
| stoch_trend_h1 | 自研 | 66 | 12 | 661201 | v1~v6 | 禁用 |
| stoch_trend_h1_optimized | 自研 | 66 | 12 | 661202 | v7 | 启用 |
| stoch_trend_h1_upgraded | 自研 | 66 | 12 | 661203 | v12 | 禁用 |
| mfi_bb_m30 | 自研 | 66 | 10 | 661001 | v1~v3 | 禁用 |
| mfi_bb_m30_optimized | 自研 | 66 | 10 | 661002 | v3 | 禁用 |
| mfi_bb_m30_upgraded | 自研 | 66 | 10 | 661003 | v8~v16 | 启用 |
| m30_bb_deepreturn | 自研 | 66 | 11 | 661101 | v1 | 禁用 |
| m30_bb_deepreturn_optimized | 自研 | 66 | 11 | 661102 | v1 | 启用 |
| sanqing_h1 | 借鉴 | 88 | 01 | 880107 | v6~v10 | 启用 |
| sanqing_h1_original | 借鉴 | 88 | 01 | 880106 | v1 | 禁用 |
| sanqing_h1_upgraded | 借鉴 | 88 | 01 | 880108 | v9~v11 | 启用 |
| rsi_grading_m30 | 自研 | 66 | 09 | 660901 | v1 | 禁用 |
| rsi_grading_m30_optimized | 自研 | 66 | 09 | 660902 | v3 | 禁用 |
| rsi_grading_m30_upgraded | 自研 | 66 | 09 | 660904 | v5~v6 | 启用 |

## 策略文件命名规范（强制）

所有策略文件必须使用以下格式：

```
strategies/{YYYYMMDD}_{策略名}_v{版本号}.py
```

示例：
- 20260811_gold_auto_research_v1.py
- 20260811_sanqing_h1_upgraded_v11.py

版本号递增规则：
- 每次修改策略逻辑 -> 版本号 +1
- 修改前将原文件移至 `strategies/backup/`
- 生成新版本号的文件

## 说明文档规范

### 文档位置
- 策略说明文档放在 `strategies/docs/{YYYYMMDD}_{策略名}_v{版本号}.md`
- 和策略 `.py` 文件在同一根目录下，方便关联
- 文档内容包含：评分因子表、出场逻辑表、参数说明

### 文档格式
```
---
name: 策略名
magic: 6位Magic
version: v1
display: 显示名称
desc: 策略简介（中文）
desc_en: Strategy brief (English)
---
```

### 双语要求（强制）

所有策略说明文档必须同时提供中英文版本，具体如下：

1. **frontmatter 字段**：`desc`（中文简介）+ `desc_en`（英文简介）必须同时填写
2. **表格内容**：入场条件、出场逻辑等表格中的中文文本，必须同步在 `dashboard/frontend/src/utils/strategyTranslations.ts` 的 `detailTranslations` 映射表中添加对应英文翻译
3. **新增或修改策略文档时**，必须同步更新 `strategyTranslations.ts`，否则英文界面下表格会显示中文原文
4. 翻译映射 key 为精确中文字符串，value 为英文翻译，建议使用 `"中文字段": "English translation"` 格式

## 策略删除规则

删除策略不是永久删除，而是移至 backup 目录，可随时恢复：

删除前：
  strategies/{文件名}.py
  strategies/docs/{文件名}.md

删除后：
  strategies/backup/{文件名}.py
  strategies/backup/docs/{文件名}.md

恢复方法：从 `strategies/backup/` 将文件移回 `strategies/` 和 `strategies/docs/`，重启引擎即可。

## 策略导入规则

通过策略中心「导入策略」按钮上传 .py 文件：

1. 文件自动规范命名（不符合 YYYYMMDD_name_v1 格式的自动重命名）
2. 上传到 `strategies/` 目录
3. 页面刷新后出现在策略列表中
4. 重启引擎后生效

## CHANGELOG 规范

每个策略文件顶部必须有 `STRATEGY_CHANGELOG`：

```python
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 889900, "date": "2026-08-11",
     "desc": "初始版本"},
    {"version": "v2", "magic": 889900, "date": "2026-08-12",
     "desc": "优化出场逻辑，增加中线穿越检查"},
]
```

- `magic` 必须是当前版本对应的实际6位 magic number
- `date` 格式 `YYYY-MM-DD`
- `desc` 用中文，简洁说明本次改动的核心变化

## backup/ 文件命名规范

```
strategies/backup/{YYYYMMDD}_{策略名}_v{版本号}.py
```

例：`strategies/backup/20260615_sanqing_h1_v6.py`

## 兼容旧版 Magic

历史遗留的 777xxx 系列 magic（旧版 MT4 历史成交记录）仍受支持：

| 旧 Magic | 策略 |
|----------|------|
| 777001 | M30_rsi_bb |
| 777002 | H1_v6_hybrid |
| 777003 | gold_auto_research |

新旧 magic 在 `/api/trades/stats` 的 `by_strategy` 分组中自动合并到同一策略族。