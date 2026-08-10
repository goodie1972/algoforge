"""
中英双语日志消息模板库。

用法：
    from services.log_messages import L
    logger.info(L('open_order_success', symbol='XAUUSD', volume=0.1, ticket=12345))

根据 runtime_config 的 language 字段自动选择 zh-CN / en-US。
没有匹配模板时回退到原始消息（英文）。
"""

import logging
from typing import Optional

_LANG: Optional[str] = None

def _get_lang() -> str:
    global _LANG
    if _LANG is not None:
        return _LANG
    try:
        from core.runtime_config import RuntimeConfig
        lang = RuntimeConfig().get('language', 'zh-CN')
    except Exception:
        lang = 'zh-CN'
    # 归一化：zh-CN -> zh, en-US -> en
    _LANG = 'zh' if str(lang).lower().startswith('zh') else 'en'
    return _LANG

def set_lang(lang: str):
    """运行时切换语言（测试用）"""
    global _LANG
    _LANG = 'zh' if str(lang).lower().startswith('zh') else 'en'

def clear_lang_cache():
    """清除语言缓存（热重载时调用）"""
    global _LANG
    _LANG = None

def L(key: str, **kw) -> str:
    """获取双语模板格式化后的字符串。"""
    entry = _TEMPLATES.get(key)
    if entry is None:
        # 无模板 -> 回退英文
        return key
    lang = _get_lang()
    tmpl = entry.get(lang, entry.get('en', key))
    try:
        return tmpl.format(**kw)
    except KeyError as e:
        return f"{tmpl} (missing param: {e})"

# ============================================================
# 双语模板表
# 添加新模板时确保 zh 和 en 都完整，{变量} 保持一致
# ============================================================
_TEMPLATES: dict[str, dict[str, str]] = {

    # ---- 引擎生命周期 ----
    'engine_start': {
        'zh': 'XAUUSD 多策略交易引擎启动',
        'en': 'XAUUSD Multi-Strategy Trading Engine Starting',
    },
    'engine_stop': {
        'zh': '交易引擎已停止',
        'en': 'Trading engine stopped',
    },
    'engine_enter_main_loop': {
        'zh': '进入主循环...',
        'en': 'Entering main loop...',
    },
    'engine_interrupt': {
        'zh': '收到中断信号，停止交易',
        'en': 'Interrupt received, stopping',
    },
    'engine_main_loop_error': {
        'zh': '主循环异常: {error}',
        'en': 'Main loop exception: {error}',
    },
    'engine_init_success': {
        'zh': '[三轨] 双桥接 + DataFactory + Athlete 初始化成功，待连接',
        'en': '[ThreeRail] Dual bridge + DataFactory + Athlete initialized, awaiting connection',
    },

    # ---- 策略管理 ----
    'strategy_load': {
        'zh': '[策略加载] {name} Magic={magic} TF={tf}',
        'en': '[StrategyLoad] {name} Magic={magic} TF={tf}',
    },
    'strategy_disabled': {
        'zh': '[策略加载] {name} 已禁用，跳过',
        'en': '[StrategyLoad] {name} disabled, skip',
    },
    'strategy_max_pos_zero': {
        'zh': '[策略加载] {name} 最大持仓为 0，跳过',
        'en': '[StrategyLoad] {name} max_positions=0, skip',
    },
    'strategy_unknown': {
        'zh': '未知策略: {name}，跳过',
        'en': 'Unknown strategy: {name}, skip',
    },
    'strategy_added': {
        'zh': '[策略动态添加] {name} Magic={magic} TF={tf}',
        'en': '[StrategyAdd] {name} Magic={magic} TF={tf}',
    },
    'strategy_removed': {
        'zh': '[策略动态移除] {name} Magic={magic}',
        'en': '[StrategyRemove] {name} Magic={magic}',
    },
    'strategy_already_exists': {
        'zh': '[策略动态添加] {name} 已存在，跳过',
        'en': '[StrategyAdd] {name} already exists, skip',
    },

    # ---- 桥接 ----
    'bridge_connected': {
        'zh': '[桥接] 已连接到 {host}:{port}',
        'en': '[Bridge] Connected to {host}:{port}',
    },
    'bridge_reconnect': {
        'zh': '[桥接] 尝试重连...',
        'en': '[Bridge] Reconnecting...',
    },
    'bridge_reconnect_success': {
        'zh': '[桥接] 重连成功',
        'en': '[Bridge] Reconnected',
    },
    'bridge_heartbeat_failed': {
        'zh': '[桥接] 心跳失败，尝试重连...',
        'en': '[Bridge] Heartbeat failed, reconnecting...',
    },
    'bridge_account_info': {
        'zh': '[桥接] 账户 #{login} 余额: {balance} {currency}',
        'en': '[Bridge] Account #{login} Balance: {balance} {currency}',
    },
    'bridge_paper_mode': {
        'zh': '[桥接] 纸面模式：PaperBridge 包装',
        'en': '[Bridge] Paper mode: PaperBridge wrapper',
    },
    'bridge_open_order_success': {
        'zh': '开仓成功: {symbol} {volume}手 Ticket={ticket}',
        'en': 'Open order success: {symbol} {volume} lots Ticket={ticket}',
    },
    'bridge_open_order_failed': {
        'zh': '开仓失败: {symbol} {reason}',
        'en': 'Open order failed: {symbol} {reason}',
    },
    'bridge_close_order_success': {
        'zh': '平仓成功: Ticket={ticket}',
        'en': 'Close order success: Ticket={ticket}',
    },
    'bridge_close_order_failed': {
        'zh': '平仓失败: Ticket={ticket}',
        'en': 'Close order failed: Ticket={ticket}',
    },
    'bridge_modify_success': {
        'zh': '修改成功: Ticket={ticket} SL={sl} TP={tp}',
        'en': 'Modify success: Ticket={ticket} SL={sl} TP={tp}',
    },
    'bridge_modify_failed': {
        'zh': '修改失败: Ticket={ticket}',
        'en': 'Modify failed: Ticket={ticket}',
    },
    'bridge_ea_error': {
        'zh': '[桥接] EA 错误: {code} 返回 {detail}',
        'en': '[Bridge] EA error: {code} returned {detail}',
    },
    'bridge_parse_failed': {
        'zh': '[桥接] F043 解析失败: {error}, fields={fields}',
        'en': '[Bridge] F043 parse failed: {error}, fields={fields}',
    },

    # ---- K线 ----
    'candle_fetch': {
        'zh': '[K线获取] {tf} 桥接 {bridge} + 补充 {db} = {total}',
        'en': '[CandleFetch] {tf} bridge {bridge} + backfill {db} = {total}',
    },
    'candle_bridge_failed': {
        'zh': '[K线获取] {tf} 桥接失败: {error}',
        'en': '[CandleFetch] {tf} bridge failed: {error}',
    },
    'candle_bridge_empty': {
        'zh': '[K线获取] {tf} 桥接无数据，从数据库补充 {n} 条',
        'en': '[CandleFetch] {tf} bridge empty, fallback DB {n} candles',
    },

    # ---- 数据同步 ----
    'sync_start': {
        'zh': '[数据同步] 开始增量同步: {tfs}',
        'en': '[DataSync] Starting incremental sync: {tfs}',
    },
    'sync_done': {
        'zh': '[数据同步] 完成',
        'en': '[DataSync] Done',
    },
    'sync_write': {
        'zh': '[数据同步] {tf} 写入 {n} 条',
        'en': '[DataSync] {tf} wrote {n} candles',
    },
    'sync_failed': {
        'zh': '[数据同步] {tf} 失败: {error}',
        'en': '[DataSync] {tf} failed: {error}',
    },
    'sync_db_error': {
        'zh': '[数据同步] 数据库异常: {error}',
        'en': '[DataSync] DB error: {error}',
    },

    # ---- 数据工厂 ----
    'datafactory_start': {
        'zh': '[DataFactory] 启动',
        'en': '[DataFactory] Started',
    },
    'datafactory_stop': {
        'zh': '[DataFactory] 停止',
        'en': '[DataFactory] Stopped',
    },
    'datafactory_first_load_done': {
        'zh': '[DataFactory] 首次加载完成，进入增量循环',
        'en': '[DataFactory] First load done, entering incremental loop',
    },
    'datafactory_connect_failed': {
        'zh': '[DataFactory] 桥接连接失败: {error}',
        'en': '[DataFactory] Bridge connect failed: {error}',
    },

    # ---- 时间校准 ----
    'time_sync_failed': {
        'zh': '[时间校准] MT4 服务器时间获取失败，跳过校准',
        'en': '[TimeSync] MT4 server time unavailable, skip sync',
    },
    'time_sync': {
        'zh': '[时间校准] MT4: {mt4} | 本机 UTC: {local} | 偏差: {offset}s',
        'en': '[TimeSync] MT4: {mt4} | Local UTC: {local} | Offset: {offset}s',
    },

    # ---- 交易恢复 ----
    'recovery_loaded': {
        'zh': '加载历史成交 {n} 条',
        'en': 'Loaded {n} historical trades',
    },
    'recovery_no_backfill': {
        'zh': '[成交恢复] 无需补充，已是最新',
        'en': '[TradeRecovery] No backfill needed, up-to-date',
    },
    'recovery_backfilled': {
        'zh': '[成交恢复] 补充 {n} 条历史成交',
        'en': '[TradeRecovery] Backfilled {n} historical trades',
    },
    'recovery_file_write_failed': {
        'zh': '[成交恢复] 写入文件失败: {error}',
        'en': '[TradeRecovery] File write failed: {error}',
    },

    # ---- 运动员 ----
    'athlete_duplicate_ticket': {
        'zh': '[运动员] 重复门票 #{signal_id} {direction}，跳过（已有 #{existing} 在等待）',
        'en': '[Athlete] Duplicate ticket #{signal_id} {direction}, skipped (#{existing} pending)',
    },
    'athlete_ticket_received': {
        'zh': '[运动员] 收到候选门票 #{signal_id} {direction}，剩余 {ticks} tick',
        'en': '[Athlete] Received candidate ticket #{signal_id} {direction}, {ticks} ticks left',
    },
    'athlete_ticket_voided': {
        'zh': '[运动员] 门票 #{signal_id} 作废（{ticks} tick 均未通过）',
        'en': '[Athlete] Ticket #{signal_id} voided (all {ticks} ticks failed)',
    },
    'athlete_open_success': {
        'zh': '[运动员] 开仓成功 #{ticket} {direction} @ {price:.2f}',
        'en': '[Athlete] Open success #{ticket} {direction} @ {price:.2f}',
    },
    'athlete_open_failed': {
        'zh': '[运动员] 开仓失败: {error}',
        'en': '[Athlete] Open failed: {error}',
    },
    'athlete_scanner_error': {
        'zh': '[运动员] scanner 异常({strategy}): {error}',
        'en': '[Athlete] Scanner error({strategy}): {error}',
    },
    'athlete_order_exec_error': {
        'zh': '[运动员] 开仓执行异常: {error}',
        'en': '[Athlete] Order execution error: {error}',
    },

    # ---- 风控 ----
    'risk_global_hard_stop': {
        'zh': '[全局硬止损] 已实现亏损恢复至 {pct:.2f}%，恢复开仓',
        'en': '[GlobalHardStop] Loss recovered to {pct:.2f}%, trading resumed',
    },
    'risk_loss_recovered': {
        'zh': '[风控] {name} 已实现亏损回正，解除绝对亏损冷却',
        'en': '[Risk] {name} Loss recovered, cooling lifted',
    },
    'risk_restored': {
        'zh': '[风控恢复] 已恢复 {n} 个策略的风控状态',
        'en': '[RiskRestore] Restored {n} strategy risk states',
    },
    'risk_block_reason': {
        'zh': '[风控] {name} 跳过开仓: {reason}',
        'en': '[Risk] {name} Skip open: {reason}',
    },

    # ---- 新闻 ----
    'news_filter_loaded': {
        'zh': '[新闻过滤] 已加载 {n} 个禁售窗口',
        'en': '[NewsFilter] Loaded {n} blackout windows',
    },
    'news_bias_block': {
        'zh': '[News-Bias] 方向阻塞触发，跳过开仓',
        'en': '[NewsBias] Direction block triggered, skip open',
    },
    'news_gold_fetch': {
        'zh': '[黄金快讯] 开始抓取+判断...',
        'en': '[GoldNews] Starting fetch + judge...',
    },
    'news_gold_fetch_done': {
        'zh': '[黄金快讯] 定时抓取完成: {n} 条, 利多{bullish}/利空{bearish}',
        'en': '[GoldNews] Scheduled fetch done: {n} results, bullish{bullish}/bearish{bearish}',
    },
    'news_gold_fetch_failed': {
        'zh': '[黄金快讯] 定时抓取异常: {error}',
        'en': '[GoldNews] Scheduled fetch error: {error}',
    },

    # ---- 热重载 ----
    'hot_reload_config': {
        'zh': '[热重载] RuntimeConfig 已重新加载，当前 active 配置已更新',
        'en': '[HotReload] RuntimeConfig reloaded, active config updated',
    },
    'hot_reload_done': {
        'zh': '[热重载] 完成',
        'en': '[HotReload] Done',
    },

    # ---- 数据库 ----
    'db_init_done': {
        'zh': '数据库初始化完成: {path} ({n} 张表: {tables})',
        'en': 'DB initialization complete: {path} ({n} tables: {tables})',
    },
    'db_write_failed': {
        'zh': '[DB] 写入 {item} 失败: {error}',
        'en': '[DB] Write {item} failed: {error}',
    },
    'db_tz_migration': {
        'zh': '时区迁移: 已修正 {n} 条记录 (UTC → UTC+8)',
        'en': 'TZ migration: Fixed {n} records (UTC → UTC+8)',
    },
    'db_tz_migration_skip': {
        'zh': '时区迁移: 已完成（metadata 标记），跳过',
        'en': 'TZ migration: Already done (metadata), skip',
    },

    # ---- 下载器 ----
    'downloader_sync': {
        'zh': '[{tf}] 增量同步: 已有最新 {latest}，拉取 {n} 根',
        'en': '[{tf}] Incremental sync: latest {latest}, fetching {n} candles',
    },
    'downloader_first_download': {
        'zh': '[{tf}] 首次初始下载，拉取 {n} 根',
        'en': '[{tf}] First initial download, fetching {n} candles',
    },
    'downloader_no_data': {
        'zh': '[{tf}] 未获取到数据',
        'en': '[{tf}] No data fetched',
    },
    'downloader_backfill': {
        'zh': '[{tf}] 开始全量分页回填（目标: {target}）',
        'en': '[{tf}] Starting full pagination backfill (target: {target})',
    },
    'downloader_backfill_done': {
        'zh': '[{tf}] 全量回填完成: 总计获取 ~{total} 根，写入 {n} 条',
        'en': '[{tf}] Full backfill complete: ~{total} candles, wrote {n}',
    },
    'downloader_mt4_failed': {
        'zh': '无法连接 MT4，下载失败',
        'en': 'Cannot connect to MT4, download failed',
    },

    # ---- 纸面交易 ----
    'paper_open': {
        'zh': '[PaperBridge] 模拟开仓: {symbol} {type} {volume}手',
        'en': '[PaperBridge] Simulated open: {symbol} {type} {volume} lots',
    },
    'paper_close': {
        'zh': '[PaperBridge] 模拟平仓: Ticket={ticket}',
        'en': '[PaperBridge] Simulated close: Ticket={ticket}',
    },
    'paper_started': {
        'zh': '[PaperBridge] 启动，初始余额=${balance:.2f}',
        'en': '[PaperBridge] Started, initial balance=${balance:.2f}',
    },
    'paper_no_market_data': {
        'zh': '[PaperBridge] 无法开仓：无行情数据',
        'en': '[PaperBridge] Cannot open: no market data',
    },
    'paper_close_not_found': {
        'zh': '[PaperBridge] 平仓失败：Ticket={ticket} 不存在',
        'en': '[PaperBridge] Close failed: Ticket={ticket} not found',
    },

    # ---- LLM ----
    'llm_loaded_env': {
        'zh': '[LLMProvider] 已加载 .env: {path}',
        'en': '[LLMProvider] Loaded .env: {path}',
    },
    'llm_load_failed': {
        'zh': '[LLMProvider] 加载失败: {error}',
        'en': '[LLMProvider] Load failed: {error}',
    },
    'llm_save_failed': {
        'zh': '[LLMProvider] 保存失败: {error}',
        'en': '[LLMProvider] Save failed: {error}',
    },
    'llm_no_provider': {
        'zh': '[LLMProvider] 无可用 Provider 或 API Key 未设置',
        'en': '[LLMProvider] No available Provider or API Key not set',
    },
    'llm_no_model': {
        'zh': '[LLMProvider] 未选择模型',
        'en': '[LLMProvider] No model selected',
    },
    'llm_call_failed': {
        'zh': '[LLMProvider] 调用失败: {error}',
        'en': '[LLMProvider] Call failed: {error}',
    },

    # ---- 监督者 ----
    'supervisor_alert_persist_failed': {
        'zh': '[监督者] 持久化告警失败: {error}',
        'en': '[Supervisor] Persist alert failed: {error}',
    },
    'supervisor_loaded': {
        'zh': '[监督者] 加载 {n} 条历史告警',
        'en': '[Supervisor] Loaded {n} history alerts',
    },

    # ---- 策略 ----
    'strategy_score': {
        'zh': '{name} 评分: {score}/{max_score} {flags} {signal} 明细: {detail}',
        'en': '{name} Score: {score}/{max_score} {flags} {signal} Detail: {detail}',
    },
    'strategy_no_signal': {
        'zh': '无信号',
        'en': 'No signal',
    },
    'strategy_gate_blocked': {
        'zh': '[门禁] {name} {direction}: {reason}',
        'en': '[Gate] {name} {direction}: {reason}',
    },
    'strategy_position_report': {
        'zh': '{name} 持仓: {total} (多:{longs} 空:{shorts})',
        'en': '{name} Positions: {total} (longs:{longs} shorts:{shorts})',
    },
    'strategy_open_signal': {
        'zh': '{name} 开仓信号 {direction} 评分={score}',
        'en': '{name} Open signal {direction} Score={score}',
    },
    'strategy_entry_scored': {
        'zh': '{name} 入场评分 {score}/{max_score} {summary}',
        'en': '{name} Entry score {score}/{max_score} {summary}',
    },

    # ---- 回测与路由 ----
    'backtest_loaded': {
        'zh': '回测 {job}: 从 {file} 加载了 {n} 条数据',
        'en': 'Backtest {job}: Loaded {n} data rows from {file}',
    },
    'backtest_no_data': {
        'zh': '回测 {job}: 无历史数据文件，使用模拟数据',
        'en': 'Backtest {job}: No history data, using simulated data',
    },
    'backtest_failed': {
        'zh': '回测 {job} 失败',
        'en': 'Backtest {job} failed',
    },
    'route_indicator_failed': {
        'zh': '[indicators] 获取指标失败: {error}',
        'en': '[indicators] Get indicators failed: {error}',
    },
    'route_report_daily_done': {
        'zh': '[报告] 日报已生成',
        'en': '[Report] Daily report generated',
    },
    'route_report_daily_failed': {
        'zh': '[报告] 日报生成失败: {error}',
        'en': '[Report] Daily report failed: {error}',
    },

    # ---- 下载器路由 ----
    'route_download_failed': {
        'zh': '[{tf}] 下载失败',
        'en': '[{tf}] Download failed',
    },
}