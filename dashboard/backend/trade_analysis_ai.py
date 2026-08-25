"""
历史成交分析 AI 模块 — 注册表驱动策略解析 + LLM 实时分析（运行时降级）
====================================================================
供 routes/trades.py 的 get_trade_analysis 调用，控制 trades.py 体积。

一、策略解析优先序（动态注册表，去硬编码）：
    1. 激活策略池精确匹配（config.settings.STRATEGY_POOL，按 magic）
    2. 历史映射表（routes/trades.py 模块级 MAGIC_TO_STRATEGY，含历史版本展开）
    3. 扫描器元数据反查（strategies/scanner.py scan_strategy_metadata()）：
       default_magic / STRATEGY_LEGACY_MAGICS / STRATEGY_CHANGELOG[].magic
    4. 名称回退：strategy 字段剥 _BUY/_SELL 后查元数据键；
       magic_XXXXXX 占位符走 PPNN_TO_STRATEGY 前缀兜底
    5. 全失败 → (None, None)

二、LLM 实时分析：每请求新建 LLMProviderManager（读到用户最新激活切换），
同步 chat() 通过 asyncio.to_thread 放入线程池并整体加超时，
无激活 provider / 无 Key / 超时 / 异常 / 返回 None / JSON 解析失败 一律降级。
"""
import asyncio
import importlib
import json
import logging
import os
import re
import sys
import time

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

logger = logging.getLogger(__name__)

# LLM 调用总超时（秒）— 覆盖 mgr.chat 内部 httpx(30s) + 代理探测 + 故障转移
_LLM_TIMEOUT = 40

# magic_XXXXXX 占位符
_MAGIC_PLACEHOLDER_RE = re.compile(r"^magic_(\d{4,6})$")
# strategy 字段方向后缀（大小写不敏感，允许重复后缀）
_SIDE_SUFFIX_RE = re.compile(r"(_BUY|_SELL)+$", re.IGNORECASE)

# ── AI 分析结果缓存（ticket → (result_dict, timestamp)）──────────
_AI_CACHE: dict[int, tuple[dict, float]] = {}
_AI_CACHE_TTL = 24 * 3600  # 24 小时过期


# ── 延迟导入（首次调用时加载，失败容错）──────────────────

def _get_pool() -> dict:
    """激活策略池 config.settings.STRATEGY_POOL"""
    try:
        from config import settings
        return dict(getattr(settings, "STRATEGY_POOL", {}) or {})
    except Exception as e:  # pragma: no cover
        logger.warning(f"[TradeAI] STRATEGY_POOL 加载失败: {e}")
        return {}


def _get_mappings() -> tuple[dict, dict]:
    """复用 routes/trades.py 的模块级映射（不重复构建、不改其构建逻辑）。

    兼容两种模块名：生产服务以 dashboard.backend.routes.trades 加载，
    独立脚本可能以 routes.trades 加载；优先取已加载实例，避免二次执行模块代码。
    """
    for mod_name in ("dashboard.backend.routes.trades", "routes.trades"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "MAGIC_TO_STRATEGY"):
            return mod.MAGIC_TO_STRATEGY, mod.PPNN_TO_STRATEGY
    for mod_name in ("dashboard.backend.routes.trades", "routes.trades"):
        try:
            mod = importlib.import_module(mod_name)
            return mod.MAGIC_TO_STRATEGY, mod.PPNN_TO_STRATEGY
        except Exception:
            continue
    logger.warning("[TradeAI] 历史映射表加载失败")
    return {}, {}


def _get_scan_meta() -> dict:
    """扫描器元数据（模块级缓存，启动已预热）"""
    try:
        from strategies.scanner import scan_strategy_metadata
        return scan_strategy_metadata() or {}
    except Exception as e:  # pragma: no cover
        logger.warning(f"[TradeAI] 扫描器元数据加载失败: {e}")
        return {}


def _load_module(module_name: str):
    """加载策略模块对象（优先取已导入实例，避免重复执行模块代码）"""
    if not module_name:
        return None
    mod = sys.modules.get(module_name)
    if mod is not None:
        return mod
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


# ── 一、策略解析 ──────────────────────────────────────────

def _resolve_by_active_pool(magic: int) -> str | None:
    """① 激活策略池精确匹配（冲突时激活优先）"""
    if not magic:
        return None
    for name, cfg in _get_pool().items():
        try:
            if int(cfg.get("magic", 0)) == int(magic):
                return name
        except (TypeError, ValueError):
            continue
    return None


def _resolve_by_magic_map(magic: int) -> str | None:
    """② 历史映射表（含 6 位 magic 的 01~09 历史版本展开）"""
    if not magic:
        return None
    magic_map, _ = _get_mappings()
    try:
        return magic_map.get(int(magic))
    except (TypeError, ValueError):
        return None


def _resolve_by_scanner(magic: int) -> str | None:
    """③ 扫描器元数据反查：default_magic / STRATEGY_LEGACY_MAGICS / STRATEGY_CHANGELOG"""
    if not magic:
        return None
    try:
        magic_int = int(magic)
    except (TypeError, ValueError):
        return None
    for name, meta in _get_scan_meta().items():
        # default_magic
        if meta.get("default_magic") == magic_int:
            return name
        mod = _load_module(meta.get("module", ""))
        if mod is None:
            continue
        # 模块级历史 magic 列表
        for lm in getattr(mod, "STRATEGY_LEGACY_MAGICS", []) or []:
            if lm == magic_int:
                return name
        # changelog 各条目的 magic
        for entry in getattr(mod, "STRATEGY_CHANGELOG", []) or []:
            if isinstance(entry, dict) and entry.get("magic") == magic_int:
                return name
    return None


def _resolve_by_name(strategy_field: str, magic: int) -> tuple[str | None, str | None]:
    """④ 名称回退：剥 _BUY/_SELL 查元数据键；magic_ 占位符走 PPNN 前缀兜底"""
    raw = str(strategy_field or "").strip()
    if raw:
        base = _SIDE_SUFFIX_RE.sub("", raw).strip()
        if base and base in _get_scan_meta():
            return base, "name"
    m = _MAGIC_PLACEHOLDER_RE.match(raw.lower())
    if m:
        digits = m.group(1)
        try:
            magic_val = int(digits)
        except ValueError:
            magic_val = 0
        if not magic_val:
            magic_val = magic or 0
        if len(digits) >= 4:
            _, ppnn_map = _get_mappings()
            name = ppnn_map.get(digits[:4])
            if name:
                return name, "ppnn_prefix"
    return None, None


def resolve_strategy(trade: dict) -> tuple:
    """按优先序解析交易的策略内部名。

    Args:
        trade: trades 记录 dict（至少含 magic / strategy 字段）

    Returns:
        (internal_name, resolved_by)；全失败返回 (None, None)。
        resolved_by ∈ {"active_pool", "magic_map", "scanner_meta", "name", "ppnn_prefix"}
    """
    try:
        magic = int(trade.get("magic") or 0)
    except (TypeError, ValueError):
        magic = 0

    # ① 激活 POOL 精确匹配
    name = _resolve_by_active_pool(magic)
    if name:
        return name, "active_pool"

    # ② 历史映射表
    name = _resolve_by_magic_map(magic)
    if name:
        return name, "magic_map"

    # ③ 扫描器元数据反查
    name = _resolve_by_scanner(magic)
    if name:
        return name, "scanner_meta"

    # ④ 名称回退
    return _resolve_by_name(trade.get("strategy", ""), magic)


def build_strategy_meta(internal_name: str, resolved_by: str) -> dict | None:
    """组装 strategy_meta 响应字段：
    {internal_name, display, timeframe, version, resolved_by, desc}
    """
    if not internal_name:
        return None
    try:
        from dashboard.backend.strategy_registry import get_strategy_info
        info = get_strategy_info(internal_name) or {}
    except Exception:
        info = {}

    pool_cfg = _get_pool().get(internal_name) or {}

    mod = _load_module(info.get("module", ""))
    version = getattr(mod, "STRATEGY_VERSION", None) if mod else None

    desc = None
    try:
        from dashboard.backend.strategy_logics import get_strategy_logic
        logic = get_strategy_logic(internal_name)
        if logic:
            desc = logic.get("desc") or None
    except Exception as e:
        logger.warning(f"[TradeAI] get_strategy_logic({internal_name}) 失败: {e}")

    # timeframe：激活池配置优先（策略实际运行周期），其次扫描器元数据；
    # 扫描器在类未定义 default_timeframe 时回退默认值 "M30"，此时视为不可信占位。
    timeframe = pool_cfg.get("timeframe")
    if not timeframe:
        scan_tf = info.get("default_timeframe")
        if scan_tf and scan_tf != "M30":
            timeframe = scan_tf

    return {
        "internal_name": internal_name,
        "display": info.get("display") or pool_cfg.get("display") or internal_name,
        "timeframe": timeframe,
        "version": version,
        "resolved_by": resolved_by,
        "desc": desc,
    }


# ── 二、Prompt 构建 ───────────────────────────────────────

def _format_logic_brief(strategy_logic: dict | None, max_rows: int = 8) -> str:
    """把 get_strategy_logic 的入场因子/出场逻辑压成文案（有则注入，无则省略）"""
    if not strategy_logic:
        return ""
    lines = []
    desc = strategy_logic.get("desc")
    if desc:
        lines.append(f"策略简介: {desc}")
    for side, side_label in (("long", "做多"), ("short", "做空")):
        rows = (strategy_logic.get(side) or {}).get("entry") or []
        if not rows:
            continue
        parts = []
        for r in rows[:max_rows]:
            nm = r.get("name", "")
            detail = r.get("detail") or r.get("score") or ""
            parts.append(f"{nm}({detail})" if detail else nm)
        if parts:
            lines.append(f"{side_label}入场因子: " + "；".join(parts))
    exit_rows = (strategy_logic.get("long") or strategy_logic.get("short") or {}).get("exit") or []
    if exit_rows:
        parts = []
        for r in exit_rows[:max_rows]:
            method = r.get("method", "")
            normal = r.get("normal", "")
            parts.append(f"{method}({normal})" if normal else method)
        lines.append("出场逻辑: " + "；".join(parts))
    note = strategy_logic.get("exitNote")
    if note:
        lines.append(f"出场特别规则: {note}")
    return "\n".join(lines)


def build_prompt(trade: dict, strategy_meta: dict | None,
                 strategy_logic: dict | None, exit_detail) -> list[dict]:
    """构建 LLM messages — 交易字段为主（快照空心化，不依赖），策略规则背景可选注入"""
    direction = str(trade.get("order_type", "")).upper()
    direction_cn = "做空（SELL）" if "SELL" in direction else ("做多（BUY）" if "BUY" in direction else direction)
    try:
        hold_minutes = round((trade.get("hold_seconds") or 0) / 60.0, 1)
    except (TypeError, ValueError):
        hold_minutes = 0

    lines = [
        "你是量化交易复盘分析师。请基于下面这笔 XAUUSD（伦敦金）历史成交记录，做量化复盘分析。",
        "",
        "【交易记录】",
        f"方向: {direction_cn}",
        f"开仓价: {trade.get('entry_price')}  平仓价: {trade.get('exit_price')}",
        f"止损 SL: {trade.get('stop_loss')}  止盈 TP: {trade.get('take_profit')}",
        f"盈亏 pnl: {round(trade.get('pnl', 0), 2)} USD",
        f"持仓时长: {hold_minutes} 分钟（{trade.get('hold_seconds', 0)} 秒）",
        f"开仓时间: {trade.get('open_time', '')}  平仓时间: {trade.get('close_time', '')}",
        f"出场原因(exit_reason): {trade.get('exit_reason', '')}",
    ]
    if exit_detail:
        try:
            lines.append(f"出场明细(exit_detail): {json.dumps(exit_detail, ensure_ascii=False)}")
        except (TypeError, ValueError):
            lines.append(f"出场明细(exit_detail): {exit_detail}")

    logic_brief = _format_logic_brief(strategy_logic)
    meta_desc = (strategy_meta or {}).get("desc") if strategy_meta else None
    if logic_brief or meta_desc:
        lines += ["", "【策略规则背景】"]
        if strategy_meta:
            lines.append(
                f"策略: {strategy_meta.get('display', '')}"
                f"（{strategy_meta.get('internal_name', '')}"
                f"，周期 {strategy_meta.get('timeframe', '')}"
                f"，版本 {strategy_meta.get('version', '')}）"
            )
        if meta_desc and not logic_brief:
            lines.append(f"策略简介: {meta_desc}")
        if logic_brief:
            lines.append(logic_brief)
    else:
        lines += ["", "【策略规则背景】（该策略未收录规则文档，请仅基于交易数据推断）"]

    lines += [
        "",
        "请严格输出一个 JSON 对象（不要输出 JSON 以外的任何文字、不要用代码块包裹），结构如下:",
        '{"entry_logic": "...", "exit_reason": "...", "pnl_note": "..."}',
        "字段要求（均为中文、简明、量化复盘口吻，每条不超过 100 字）:",
        "- entry_logic: 结合方向/开仓价/止损止盈推断的入场逻辑解读",
        "- exit_reason: 结合 exit_reason/出场明细/平仓价的出场原因解读",
        "- pnl_note: 盈亏评估与改进建议",
    ]
    return [{"role": "user", "content": "\n".join(lines)}]


# ── 三、LLM 调用与解析（运行时可用性检测 + 降级）──────────

def _parse_llm_json(text) -> dict | None:
    """宽松解析 LLM 输出：剥 ```json 围栏、正则取首个 {...}；失败返回 None"""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    # 剥 ```json / ``` 围栏
    s = re.sub(r"```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = s.replace("```", "").strip()
    obj = None
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            obj = None
    if not isinstance(obj, dict):
        return None
    keys = ("entry_logic", "exit_reason", "pnl_note")
    if not any(k in obj for k in keys):
        return None
    return {k: str(obj.get(k, "") or "") for k in keys}


def _active_model_name(provider: dict) -> str:
    return (provider.get("selected_model")
            or (provider.get("models") or [""])[0]
            or provider.get("name") or "")


async def analyze_trade_ai(trade: dict, strategy_meta: dict | None,
                           strategy_logic: dict | None, exit_detail) -> dict:
    """LLM 实时分析（运行时确认 LLM 可用性，不可用/失败一律降级）。

    带 24h TTL 缓存：同一 ticket 命中缓存则跳过 LLM 调用。

    Returns:
        {"ai_analysis": {...} | None, "analysis_source": "llm" | "fallback"}
    """
    # ── 缓存检查 ──
    ticket = int(trade.get("ticket") or 0)
    if ticket:
        cached = _AI_CACHE.get(ticket)
        if cached is not None:
            result, ts = cached
            if time.time() - ts < _AI_CACHE_TTL:
                logger.info(f"[TradeAI] 缓存命中 ticket={ticket}，跳过 LLM 调用")
                return result
            else:
                del _AI_CACHE[ticket]

    try:
        from services.llm_provider import LLMProviderManager
    except Exception as e:
        logger.warning(f"[TradeAI] LLMProviderManager 导入失败，降级: {e}")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    # 每个请求新建实例 — 读到用户最新的激活切换（模块级共享实例读不到）
    try:
        mgr = LLMProviderManager()
    except Exception as e:
        logger.warning(f"[TradeAI] LLMProviderManager 初始化失败，降级: {e}")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    # 运行时可用性检测：无激活 provider 或无 API Key → 直接降级（不发请求）
    provider = mgr.get_active_raw()
    if not (provider and provider.get("api_key")):
        logger.info("[TradeAI] 无激活 LLM Provider 或未配置 API Key，降级到本地分析")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    messages = build_prompt(trade, strategy_meta, strategy_logic, exit_detail)

    # 同步 chat()（httpx + 代理端口探测）严禁裸调阻塞事件循环 → to_thread + 总超时
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(mgr.chat, messages, None, 0.3),
            timeout=_LLM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[TradeAI] LLM 调用超时（>{_LLM_TIMEOUT}s），降级到本地分析")
        return {"ai_analysis": None, "analysis_source": "fallback"}
    except Exception as e:
        logger.warning(f"[TradeAI] LLM 调用异常，降级: {e}")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    if not text:
        logger.warning("[TradeAI] LLM 返回空结果，降级到本地分析")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    parsed = _parse_llm_json(text)
    if not parsed:
        logger.warning("[TradeAI] LLM 输出 JSON 解析失败，降级到本地分析")
        return {"ai_analysis": None, "analysis_source": "fallback"}

    parsed["model"] = _active_model_name(provider)
    result = {"ai_analysis": parsed, "analysis_source": "llm"}

    # 写入缓存
    if ticket:
        _AI_CACHE[ticket] = (result, time.time())

    return result
