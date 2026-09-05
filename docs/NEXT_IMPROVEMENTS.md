# 下次改进计划（Next Improvements）

> 本文档记录已经识别但暂未实施的优化项。每项包含背景/方案/工时/风险。
> 触发实施时复制到 CHANGELOG、记版本号。

---

## F1｜前端 bundle 深度拆分（4.6MB → 首屏 ~150KB）

### 背景
- `dashboard/frontend/dist/assets/index-*.js` 单文件 **587KB**（gzip 后约 180KB）
- vite 已做 manualChunks（vendor-vue / vendor-charts / vendor-i18n），主 chunk 主要是应用代码 + Naive UI 组件库
- 首屏加载慢（弱网体验差），按路由懒加载可显著改善

### 现象
- 用户首次打开 Dashboard → 下载 600KB JS → 解析+执行 1-2s
- 报表/配置/回测等不常用模块被首次加载，浪费带宽

### 方案
1. **路由级 dynamic import**：把 `DashboardView` / `ReportView` / `ConfigView` / `BacktestView` 等改成 `defineAsyncComponent(() => import(...))`
2. **Naive UI 按需**：检查 `unplugin-vue-components` 是否真按需引入；显式 `unplugin-icons` 只 import 实际用到的图标
3. **图表组件懒加载**：K 线图依赖 `lightweight-charts` 已在 vendor-charts 拆分 OK，但可在用户切到 K 线 tab 时再 import
4. **目标**：首屏 JS < 200KB（gzip 后 < 70KB）

### 工时
- 1-2 小时：路由拆分 + 配置 vite `optimizeDeps`
- 0.5 小时：测试构建产物大小
- **总计 1.5-2.5 小时**

### 风险
- 低：纯前端改动，不影响后端 API
- 需测试：路由切换流畅度、首屏加载时间（用 Chrome DevTools）

### 验证
```bash
cd dashboard/frontend
npm run build
du -sh dist/assets/*.js | sort -hr | head -10
# 期望: index-*.js < 200KB, vendor chunks 按需分割
```

---

## F2｜进程内热重启覆盖 DataFactory 代码

### 背景
- A（3.5.5）实现的进程内热重启能重载：策略 `.py`、F043 字段集、桥接参数
- **不能**重载：`services/data_factory.py`（DataFactory 实例被热重启保留）
- 后果：改 DataFactory 后**仍需冷重启**（36s 重连 + 重拉 K 线）

### 当前架构
- DataFactory 是独立线程（`_run_loop`），由引擎 `__init__` 创建
- 热重启 `_reboot_engine()` 只重置 strategies 和风控状态，**DataFactory 实例不动**
- 改 `services/data_factory.py` 需 kill 整个进程才能生效

### 方案
1. **DataFactory.reload() 方法**：优雅停掉旧线程 + 重新 `_run`（需要原子的 stop + start）
2. **热重启流程加一个分支**：检测 DataFactory 文件 mtime 变化 → 触发 `_reload_data_factory()`
3. **或更简单**：用 `importlib.reload(services.data_factory)` + 重建实例
   - 风险：新实例的内部状态（`_DATA_CACHE`、`_HEALTH`、`_EA_PROVIDED_TS`）会重置，K 线内存缓存清空
   - 但暖启动门控（v4）会从 `candles_cache.pkl` 恢复，避免重拉

### 工时
- 2-3 小时：DataFactory reload() 实现 + 测试线程安全
- 1 小时：集成到热重启流程（文件 mtime 检测）
- **总计 3-4 小时**

### 风险
- **中**：线程 stop/start 顺序错会丢 K 线内存或双写
- **中**：reload 后内存状态重置，K 线短暂空白（暖缓存可缓解）
- 需要：单元测试 + 集成测试 + 手动验证

### 验证
1. 改 `services/data_factory.py` 一行无害代码（加注释）
2. `touch config/engine_restart.trigger`
3. 日志应显示 `DataFactory reloaded`
5. 检查 K 线是否短暂空白后通过暖缓存恢复

---

## 待评估（暂未深挖）

| 项 | 状态 |
|:---|:---|
| 策略批量下单合并 | 当前每策略独立 send_order，并发可提升 |
| Tick→K线 异步化 | 当前 tick 处理可能阻塞 K 线渲染线程 |
| WebSocket 多频道订阅优化 | 客户端可能订阅了不需要的频道 |

---

**版本**：1.0  
**创建**：2026-09-05  
**下次评审**：当有用户反馈明显性能问题时优先翻阅