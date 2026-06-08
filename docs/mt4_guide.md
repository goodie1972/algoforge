# MT4 交易终端配置向导

## 1. 安装 MT4 终端

- 从 [MetaTrader 4 官网](https://www.metatrader4.com/en/download) 下载标准版
- 或使用经纪商提供的定制版（亨达 Hantec、XM、IC Markets 等）
- 安装路径建议保持默认：
  - 64 位系统: `C:\Program Files (x86)\MetaTrader 4`
  - 32 位系统: `C:\Program Files\MetaTrader 4`
- 安装完成后启动 MT4，用模拟账户或真实账户登录

## 2. 加载 FreeMT4Bridge EA

FreeMT4Bridge EA 是连接 Python 交易引擎与 MT4 终端的关键桥接组件，负责接收信号并执行下单操作。

### 2.1 获取 EA 文件

- FreeMT4Bridge EA 是独立组件，需另行获取
- 下载地址: https://github.com/dingmaotu/mql4-lib/releases (搜索 FreeMT4Bridge)
- 将下载的 .ex4 文件放入 MT4 的 `MQL4/Experts/` 目录
- 重启 MT4 → 导航器 → 专家顾问 → 右键刷新

### 2.2 启用 EA 交易

1. 重启 MT4 终端
2. 点击导航器（Navigator）面板，展开"专家顾问（Expert Advisors）"
3. 右键 → 刷新，确认 FreeMT4Bridge 出现在列表中
4. 将 FreeMT4Bridge EA 拖拽到 XAUUSD 图表上
5. 在弹出的设置窗口中确认：
   - **"允许自动交易（Allow Automated Trading）"** 已勾选
   - 通用选项卡 → **"允许 DLL 导入（Allow DLL imports）"** 已勾选
6. 点击确定，EA 图标应显示为笑脸 😊（非哭脸）

### 2.3 EA 参数配置

在 EA 输入参数（Inputs）选项卡中设置：

| 参数 | 值 | 说明 |
|------|-----|------|
| ServerPort | 23232 | 与 `config/settings.py` 的 FREEMT4_PORT 一致 |
| ServerHost | 127.0.0.1 | 本地回环地址 |
| LogLevel | 1 | 日志级别（0=最小, 1=普通, 2=详细） |

### 2.4 确认连接

- MT4 右下角应显示"自动交易（AutoTrading）"图标为绿色箭头
- EA 图表左上角应显示 `FreeMT4Bridge: Connected` 或等待连接状态

## 3. 配置端口验证

### 3.1 运行自检脚本

```bash
python tools/check_setup.py
```

脚本会自动检测：
- Python 环境版本
- 依赖包安装状态
- 项目文件完整性
- MT4 终端安装路径
- FreeMT4 Bridge EA 端口连通性
- 回测数据可用性

### 3.2 手动端口测试

```bash
python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',23232)); print('FreeMT4 Bridge 连接正常')"
```

成功输出: `FreeMT4 Bridge 连接正常`

### 3.3 常见端口问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 连接超时 | MT4 未运行 | 启动 MT4 并登录 |
| 连接被拒绝 | EA 未加载 | 将 EA 拖到图表上 |
| 连接被拒绝 | 端口不匹配 | 检查 EA 参数 ServerPort 与 settings.py 是否一致 |
| 防火墙拦截 | Windows 防火墙 | 添加入站规则放行 23232 端口 |

## 4. 启动交易引擎

### 4.1 一键启动（推荐）

```bash
python run.py
```

启动流程：
1. 检查环境依赖
2. 检测 MT4 连接状态
3. 加载 V6 Hybrid 策略
4. 建立 FreeMT4 Bridge 通信
5. 开始接收行情并执行交易

### 4.2 直接启动（跳过检查）

```bash
python main.py
```

### 4.3 指定其他策略

```bash
python main.py --strategy v6_hybrid
python main.py --strategy rsi_bollinger
```

## 5. 常见问题

### Q1: EA 图表上显示哭脸（😢）怎么办？

哭脸表示 EA 自动交易被禁用。解决方法：
1. 点击 MT4 工具栏的"自动交易"按钮（绿色箭头），确保高亮
2. 检查工具 → 选项 → 专家顾问选项卡 → 勾选"允许自动交易"
3. 将 EA 从图表上移除并重新拖入，勾选"允许自动交易"

### Q2: 启动后引擎提示 "FreeMT4 Bridge 无法连接"？

依次排查：
1. MT4 是否已运行并登录账户
2. EA 是否已加载到 XAUUSD 图表上
3. EA 参数 ServerPort 是否设置为 23232
4. Windows 防火墙是否阻止了端口
5. 运行 `python tools/check_setup.py` 执行完整诊断

### Q3: V6 策略与其他策略有何不同？

V6 Hybrid 是当前默认策略，特点：
- **双向网格**: 同时持有多空头寸，适应震荡和趋势行情
- **V6 评分系统**: 综合趋势强度、动量、RSI、波动率等维度评分决策
- **ATR 动态止损**: 基于波动率的自适应止损，避免过早离场
- **自适应参数**: 自动根据市场波动调整仓位和间距

### Q4: 如何修改交易参数？

编辑 `config/settings.py` 文件：
- `FREEMT4_PORT`: 桥接端口（需与 EA 参数一致）
- `SYMBOL`: 交易品种（默认 XAUUSD）
- `TIMEFRAME`: 时间周期（默认 M1）
- V6 策略参数在策略文件中配置：`strategies/v6_hybrid.py`

### Q5: 日志在哪里查看？

- 引擎日志: `logs/` 目录下按日期命名的文件
- EA 日志: MT4 的 `MQL4/Logs/` 目录，或 MT4 终端 → 专家顾问选项卡
- 实时查看: 运行引擎时控制台输出
- 建议在 `config/settings.py` 中设置 `LOG_LEVEL = "DEBUG"` 获取详细日志

### Q6: 实盘交易前需要做哪些准备？

1. ✅ 完成回测验证（`python backtest/run_backtest.py`）
2. ✅ 使用模拟账户运行至少 1-2 周
3. ✅ 确认止盈止损参数符合风险承受能力
4. ✅ 验证 FreeMT4 Bridge 连接稳定（无断连）
5. ✅ 设定最大回撤止损和每日亏损限额
6. ✅ 了解经纪商对 EA 交易的政策和限制

## 6. 技术架构参考

```
┌─────────────────┐    TCP :23232    ┌──────────────────┐
│  MT4 终端        │ ◄──────────────► │  Python 交易引擎   │
│  FreeMT4Bridge EA │   行情+交易信号  │  V6 Hybrid 策略   │
└─────────────────┘                  └──────────────────┘
       │                                    │
       ▼                                    ▼
  真实/模拟账户                        回测系统 (Backtrader)
                                   策略优化 + 数据管理
```

> 📌 提示: 所有配置修改后都需要重启引擎才能生效。MT4 与引擎之间的连接由心跳机制维护，默认 5 秒一次；若连续三次心跳失败，引擎将自动报警并尝试重连。
