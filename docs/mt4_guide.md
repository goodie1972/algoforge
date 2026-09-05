# MT4 交易终端配置向导

## 1. 安装 MT4 终端

- 从 [MetaTrader 4 官网](https://www.metatrader4.com/en/download) 下载标准版
- 或使用经纪商提供的定制版（亨达 Hantec、XM、IC Markets 等）
- 安装完成后启动 MT4，用模拟账户或真实账户登录

## 2. 加载 FreeMT4Bridge EA

FreeMT4Bridge EA 是连接 Python 交易引擎与 MT4 终端的关键桥接组件。

### 2.1 获取 EA 文件

- 将 FreeMT4Bridge.ex4 放入 MT4 的 `MQL4/Experts/` 目录
- 重启 MT4 → 导航器 → 专家顾问 → 右键刷新

### 2.2 启用 EA 交易

1. 重启 MT4 终端
2. 将 FreeMT4Bridge EA 拖拽到 XAUUSD 图表上
3. 在弹出的设置窗口中确认：
   - **"允许自动交易（Allow Automated Trading）"** 已勾选
   - 通用选项卡 → **"允许 DLL 导入（Allow DLL imports）"** 已勾选
4. 点击确定，EA 图标应显示为笑脸

### 2.3 EA 参数配置

| 参数 | 值 | 说明 |
|------|-----|------|
| ServerPort | 23232 | 与 settings.py 的 FREEMT4_PORT 一致 |
| ServerHost | 127.0.0.1 | 本地回环地址 |
| LogLevel | 1 | 日志级别 |

### 2.4 确认连接

- MT4 右下角应显示"自动交易"图标为绿色箭头
- EA 图表左上角应显示 `FreeMT4Bridge: Connected`

### 2.5 F043 指标协议版本（重要）

DataFactory 通过 F043 命令向 EA 请求指标，Python 端对字段数与顺序有严格约定，EA 必须编译为匹配的版本：

- **当前协议：34 字段**（原版 28 字段已扩展）。v2 起在 `volume_sma_20` 之后新增 `ema_34` / `ema_50` / `ema_200` / `linear_reg_slope` / `cci` / `cci_prev` 共 6 个字段。
- **必须重新编译挂机**：使用旧版 `.ex4`（仅 28 字段）时，DataFactory 会判定字段数不足、拒绝整批指标（`get_indicators` 返回空），除 TA‑Lib 回退键外的 EA 指标全部失效。
- **EA 编译常见错误**（F043 实现中遇到）：
  - `iLR - function not defined`：MQL4 没有内置线性回归函数，需手算最小二乘斜率（见源码示例）
  - `declaration of 'n' hides local variable`：`ProcessCommand` 的 `n` 与自定义循环变量名遮蔽，需 rename（如 `lr_n`）
- 修改协议需四处同步：`tools/FreeMT4Bridge.mq4`（MQL4 响应端）、`core/freemt4_bridge.py`（Python 解析端）、`services/data_factory.py` 的 `ea_keys` 与 `_EA_CACHE_KEYS`，顺序与数量必须严格一致，否则会静默错位。

### 2.6 引擎生命周期管理（3.5.5）

#### 进程内热重启（推荐）

改完策略 .py 代码后，**无需关闭 EA / 断开 MT4 socket / 重拉 2000×4 根 K 线**，可直接热重启：

```bash
# 方式 1：触发文件（SSH/外部脚本友好）
touch config/engine_restart.trigger

# 方式 2：Dashboard API（人在仪表盘按按钮时使用）
curl -X POST http://127.0.0.1:1783/api/engine/restart
```

热重启全程保留：
- ✅ 活 MT4 socket（EA 不掉线）
- ✅ DataFactory 线程与暖缓存（pickle 文件 `data/cache/candles_cache.pkl`）
- ✅ 价格轮询 / 偏置刷新线程（dashboard/backend 路径）
- ✅ 风控阻断状态（DB 恢复）

日志会输出 `[HotRestart] trigger file detected → reboot complete` —— 完成耗时通常 < 1 秒。

> ⚠ **冷重启 vs 热重启边界**：策略 .py / F043 字段集 / 桥接参数可热重载；`services/data_factory.py` / `data/database.py` / 引擎主循环 / dashboard 后端代码改动需冷重启（下次改进 F2 计划让 DataFactory 也可热重载）。

## 3. 启动交易系统

```bash
# 启动后端 + 引擎（推荐）
cd /d/backup/BaoBao/PythonProgram/xauusd
python dashboard/backend/main.py &

# 浏览器打开
# http://127.0.0.1:1783/
```

## 4. 常见问题

### Q1: EA 图表上显示哭脸怎么办？

哭脸表示 EA 自动交易被禁用。解决方法：
1. 点击 MT4 工具栏的"自动交易"按钮（绿色箭头），确保高亮
2. 检查工具 → 选项 → 专家顾问选项卡 → 勾选"允许自动交易"
3. 将 EA 从图表上移除并重新拖入，勾选"允许自动交易"

### Q2: 启动后引擎提示 "无法连接 MT4"？

依次排查：
1. MT4 是否已运行并登录账户
2. EA 是否已加载到 XAUUSD 图表上
3. EA 参数 ServerPort 是否设置为 23232
4. Windows 防火墙是否阻止了端口

### Q3: 如何查看日志？

- 通过 Dashboard → 系统日志页面查看（推荐）
- 引擎日志走两个通道：
  - **数据库 `logs` 表**（推荐，Dashboard 模式下默认开启）
  - **Engine 独立模式 `logs/trading.log`**（10MB × 7 轮转，仅 engine_standalone/main.py 直接跑时生效）
- EA 日志：MT4 的 `MQL4/Logs/` 目录

### Q4: 重启后数据好像没更新？

启动时如果发现 K 线/指标停滞：

1. 检查 MT4 是否还在交易时段（周末休市无新 tick）
2. 调用 `python tools/backfill_indicators.py --only-incomplete` 回填历史指标
3. 触发引擎热重启复用暖缓存：`touch config/engine_restart.trigger`

### Q5: EA 报"无法连接 MT4 socket"错误？

`core/freemt4_bridge.py::connect()` 已优化为 12×3s ≈ 36s 重试（原 30×10s 300s）。检查：
1. EA 是否还在图表上（EA 移除后 socket 立即关闭）
2. 端口 23232 占用：Windows `netstat -ano | findstr :23232`
3. 策略上次 EA 端异常（重启 EA + Python 引擎）
