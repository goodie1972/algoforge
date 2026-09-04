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
- 修改协议需四处同步：`tools/FreeMT4Bridge.mq4`（MQL4 响应端）、`core/freemt4_bridge.py`（Python 解析端）、`services/data_factory.py` 的 `ea_keys` 与 `_EA_CACHE_KEYS`，顺序与数量必须严格一致，否则会静默错位。

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
- 引擎日志文件：`logs/` 目录
- EA 日志：MT4 的 `MQL4/Logs/` 目录
