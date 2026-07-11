# 纸面测试目录

## 目录结构

```
papertest/
├── README.md                    # 本文件
├── tools/                       # 分析工具
│   ├── weekly_analysis.py       # 周分析脚本
│   └── sim_engine.py            # 模拟引擎(旧)
├── week1_20260706_20260711/     # 第一周：原始8个策略
│   ├── 模拟交易报表.xlsx         # Excel交易报表
│   ├── weekly_analysis.txt      # 文本分析报告
│   ├── paper_trades.csv         # 所有纸面交易记录(1.8MB)
│   ├── sim_log.csv              # 旧模拟日志
│   └── sim_state.json           # 旧模拟状态
└── week2_20260711_start/        # 第二周：7个优化策略
    └── 模拟交易报表.xlsx         # 空白模板
```

## 运行说明

- 实时数据在 `logs/paper_trades.csv` 和 `logs/signal_analysis.csv`
- 每周结束后分析脚本生成报告放到对应周目录
- 新周开始时复制模板到新目录
