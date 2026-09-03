# 看门狗常驻部署与报警推送

> 关联：`tools/watchdog_launcher.py`、`tools/status_monitor.py`、`monitor/patrol_daemon.py`、`tools/alert_sender.py`
> 背景：此前引擎长期「裸跑」——`patrol_daemon.py` 日志停在 06-08、`status_monitor.py` 停于 08-09，均不在进程内。引擎 14:28→18:26 曾宕 3.5h 无人管。本方案让监控常驻 + 主动推送。

## 一、架构

```
Windows 任务计划程序 (开机自启, 失败每1min重启)
        └─ tools/watchdog_launcher.py   ← 看门狗的看门狗(单实例锁防双跑)
              ├─ tools/status_monitor.py    每5min：引擎API/桥接/主循环异常 → 自动重启引擎 + 推送
              └─ monitor/patrol_daemon.py   每30s：引擎宕/桥断 → Windows弹窗 + 推送
                        └─ tools/alert_sender.py  ← 邮件(SMTP) + 企微(群机器人) 统一推送
```

- `status_monitor.py`：**会自重启引擎**（杀 `dashboard/backend/main.py` 重拉），报警写 `logs/status_check.log` 并推送。
- `patrol_daemon.py`：**只报警不重启**（Windows 弹窗），报警写 `monitor/patrol.log` 并推送。
- `watchdog_launcher.py`：两个守护进程任一退出即 3s 后重启；本身崩了由任务计划程序兜底。

## 二、报警通道配置（邮件 + 企微）

凭据**绝不入库**（`.gitignore` 已忽略 `tools/alert_config.json`）。两种配置方式，**环境变量优先**：

方式 A — 配置文件 `tools/alert_config.json`（复制 `tools/alert_config.example.json` 改名后填真实值）：
```json
{
  "smtp":  {"host":"smtp.xxx.com","port":465,"user":"a@b.com","pass":"***","to":"you@x.com"},
  "wecom": {"webhook":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的群机器人KEY"}
}
```
方式 B — 环境变量：`ALERT_SMTP_HOST/PORT/USER/PASS/TO`、`ALERT_WECOM_WEBHOOK`。

未配置任何通道时，`alert_sender` 安全 no-op（仅本地日志，不报错）。

**自检**：`python tools/alert_sender.py` 打印各通道就绪状态并发送一条测试告警（需先配置）。

> 注意：任务计划程序以 `SYSTEM` 账户运行，读不到交互用户的 env。用**方式 A（配置文件）**最稳妥。

## 三、部署步骤

1. **配置报警**：复制 `tools/alert_config.example.json` → `tools/alert_config.json` 填入真实 SMTP / 企微 webhook。
2. **注册任务计划程序**（管理员 CMD / 双击）：
   ```
   tools\install_watchdog_task.bat
   ```
   会创建任务 `XAUUSD_Watchdog`（开机自启、最高权限、失败每 1 分钟重启），并立即运行。
3. **验证**：
   - `schtasks /query /tn XAUUSD_Watchdog` 状态应为 Running。
   - `tasklist | findstr python` 应出现 `watchdog_launcher.py`、`status_monitor.py`、`patrol_daemon.py` 三个进程。
   - 手动停引擎验证：引擎宕后 ~5min，`status_monitor` 应自动重启；同时你的邮箱/企微收到告警。

## 四、运维

| 操作 | 命令 |
|---|---|
| 立即启动 | `tools\run_watchdog_task.bat` |
| 停止 | `tools\run_watchdog_task.bat stop` |
| 卸载 | `tools\run_watchdog_task.bat delete` |

日志：
- `tools/watchdog_launcher.py` 自身：`logs/watchdog_status_monitor.out` / `monitor/watchdog_patrol.out`（子进程输出）
- 引擎自修复记录：`logs/status_check.log`
- 巡检记录：`monitor/patrol.log`

## 五、已知边界

- 看门狗只管「**引擎崩溃 → 重启**」，管不了「出场逻辑 bug 导致多单下跌不平」（那是另一项代码修复，见交易出场逻辑重构待办）。
- 企微群机器人有频率限制（约 20 条/分钟），`alert_sender` 已做 10 分钟冷却去重；若仍超限，企微侧会返回 errcode 而非崩溃。
- `status_monitor.restart_engine()` 通过 `wmic` 按命令行 `backend/main.py` 杀进程；若引擎日后改用其他启动方式，需同步更新该匹配串。
