"""
XAUUSD 新闻抓取服务 — 多源聚合
====================================
从免费公开源抓取黄金相关新闻，按五大影响变量分类，输出结构化数据。

影响变量:
  inflation    — 通胀类 (CPI, PCE, PPI, 油价)
  rates        — 央行利率/政策 (FOMC, Fed, 点阵图)
  geopolitical — 地缘政治 (战争, 制裁, 协议)
  usd          — 美元/美债收益率
  cb_buying    — 央行购金/ETF 资金流
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── RSS 源 ───────────────────────────────────────────

RSS_FEEDS = [
    {
        "url": "https://news.google.com/rss/search?q=gold+XAUUSD&hl=en-US&gl=US&ceid=US:en",
        "source": "Google News",
        "lang": "en",
    },
    {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "source": "Fed",
        "lang": "en",
    },
]

FETCH_TIMEOUT = 15
CACHE_TTL = 600  # 10 minutes

# ── 变量分类关键词 ───────────────────────────────────

VARIABLE_KEYWORDS = {
    "inflation": [
        "cpi", "consumer price", "ppi", "producer price", "pce",
        "inflation", "core inflation", "oil price", "energy",
        "wage", "average hourly", "employment cost",
    ],
    "rates": [
        "fomc", "federal reserve", "fed", "interest rate",
        "dot plot", "rate hike", "rate cut", "tightening",
        "powell", "warsh", "federal funds", "monetary policy",
        "balance sheet", "quantitative", "liquidity",
    ],
    "geopolitical": [
        "war", "sanction", "ceasefire", "tension", "conflict",
        "nuclear", "tariff", "trade war", "iran", "russia",
        "ukraine", "middle east", "strait", "gaza", "israel",
        "treaty", "agreement", "withdrawal",
    ],
    "usd": [
        "dollar index", "dxy", "usd", "treasury yield",
        "10-year", "real yield", "tips", "bond yield",
        "yield curve", "inversion",
    ],
    "cb_buying": [
        "central bank", "gold reserve", "gold purchase", "etf",
        "gold holding", "wg c", "de-gold", "pbo c", "reserve",
    ],
}

# ── 变量权重 ─────────────────────────────────────────

VARIABLE_WEIGHTS = {
    "inflation": 0.30,
    "rates": 0.25,
    "geopolitical": 0.20,
    "usd": 0.15,
    "cb_buying": 0.10,
}

# ── 逻辑链模板 ───────────────────────────────────────

LOGICAL_CHAINS = {
    "inflation": {
        "bullish": "通胀回落 → 加息预期↓ → 实际利率↓ → 美元↓ → 金价↑",
        "bearish": "通胀升温 → 加息预期↑ → 实际利率↑ → 美元↑ → 金价↓",
    },
    "rates": {
        "bullish": "鸽派信号 → 降息预期↑ → 实际利率↓ → 金价↑",
        "bearish": "鹰派信号 → 降息预期↓ → 实际利率↑ → 金价↓",
    },
    "geopolitical": {
        "bullish": "地缘紧张 → 避险情绪↑ → 资金流入黄金 → 金价↑",
        "bearish": "和平/停火 → 避险情绪消退 → 资金流出黄金 → 金价↓",
    },
    "usd": {
        "bullish": "美元↓/收益率↓ → 持有成本↓ → 金价↑",
        "bearish": "美元↑/收益率↑ → 持有成本↑ → 金价↓",
    },
    "cb_buying": {
        "bullish": "央行/ETF 增持 → 长线买盘 → 金价支撑↑",
        "bearish": "央行/ETF 减持 → 抛压 → 金价压力↓",
    },
}


def classify_variable(title: str, summary: str = "") -> str:
    """判断新闻所属影响变量"""
    text = (title + " " + summary).lower()
    for var, keywords in VARIABLE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return var
    return "other"


def classify_direction(title: str, summary: str = "") -> str:
    """
    判断新闻方向（简化版，基于关键词）。
    返回 'bullish' / 'bearish' / 'neutral'
    """
    text = (title + " " + summary).lower()

    # 利多黄金模式
    bullish_patterns = [
        # 通胀回落
        (["通胀降温", "cpi fall", "cpi below", "cpi missed", "cpi lower",
          "通胀低于", "ppi below", "通胀放缓", "disinflation"], "bullish"),
        # 鸽派
        (["dovish", "rate cut", "降息", "暂停加息", "hold steady",
          "通胀受控", "ease", "accommodative"], "bullish"),
        # 地缘紧张（传统避险）
        (["战争升级", "冲突加剧", "制裁升级", "tension escalate",
          "ceasefire fail", "hostility"], "bullish"),  # 旧逻辑，后续用权重修正
        # 美元走弱
        (["dollar weak", "dollar fell", "美元走弱", "美元下跌",
          "收益率下行", "yield fall", "yield drop"], "bullish"),
        # 央行购金
        (["央行增持", "增持黄金", "gold purchase", "increase reserve",
          "央行购金"], "bullish"),
        # 和平协议（旧逻辑修正：和平/停火 → 避险消退 → 金价↓）
        (["peace", "ceasefire", "truce", "agreement", "de-escalat",
          "和平协议", "停火"], "bearish"),
    ]
    bearish_patterns = [
        # 通胀升温
        (["cpi hot", "cpi above", "cpi rise", "cpi beat", "通胀超预期",
          "通胀升温", "通胀反弹", "通胀高企", "通胀顽固", "cpi高",
          "ppi hot", "核心通胀", "sticky inflation"], "bearish"),
        # 鹰派
        (["hawkish", "rate hike", "加息", "tighten", "加息预期",
          "point to hike", "aggressive"], "bearish"),
        # 美元走强
        (["dollar strong", "dollar surge", "dollar rally", "dollar index up",
          "美元走强", "美元上涨", "美元指数", "收益率上行",
          "yield surge", "yield rise", "treasury sell"], "bearish"),
        # 央行减持
        (["减持黄金", "gold sell", "reduce holding", "etf outflow",
          "etf流出", "gold reserve down"], "bearish"),
    ]

    # 先检查是否有"地缘紧张+避险"这种需要特殊处理的
    # 地缘紧张 → 避险情绪↑ → 资金流入黄金 → 金价↑（传统避险逻辑）
    geopolitical_tension_kw = ["war", "sanction", "conflict", "tension",
                                "strike", "attack", "missile"]
    for kw in geopolitical_tension_kw:
        if kw in text:
            # 地缘紧张 → 避险升温 → 黄金作为避险资产受追捧 → 金价↑
            return "bullish"

    for patterns, direction in bullish_patterns:
        for p in patterns:
            if p in text:
                return direction

    for patterns, direction in bearish_patterns:
        for p in patterns:
            if p in text:
                return direction

    return "neutral"


def get_logical_chain(variable: str, direction: str) -> str:
    """获取对应逻辑链描述"""
    if variable in LOGICAL_CHAINS and direction in LOGICAL_CHAINS[variable]:
        return LOGICAL_CHAINS[variable][direction]
    return ""


def estimate_weight(source: str, title: str, summary: str = "") -> str:
    """评估新闻权重：high / medium / low"""
    text = (title + " " + summary).lower()
    high_kw = ["fomc", "fed", "cpi", "non-farm", "payroll", "pwll",
               "interest rate", "war", "sanction", "nuclear", "central bank"]
    for kw in high_kw:
        if kw in text:
            return "high"
    medium_kw = ["gdp", "retail", "industrial", "consumer", "housing",
                  "dollar", "treasury", "inflation", "trade"]
    for kw in medium_kw:
        if kw in text:
            return "medium"
    return "low"


# ── RSS 解析 ─────────────────────────────────────────

def fetch_rss(feed: dict) -> list[dict]:
    """抓取并解析单个 RSS 源"""
    try:
        resp = requests.get(feed["url"], timeout=FETCH_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = []
        # RSS 2.0: channel > item
        for item_elem in root.iter("item"):
            title = ""
            summary = ""
            link = ""
            pub_date = ""

            for child in item_elem:
                tag = child.tag.split("}")[-1]  # strip namespace
                if tag == "title":
                    title = child.text or ""
                elif tag in ("description", "summary"):
                    summary = re.sub(r"<[^>]+>", "", child.text or "")  # strip HTML
                elif tag == "link":
                    link = child.text or ""
                elif tag in ("pubDate", "pubdate", "published"):
                    pub_date = child.text or ""

            if not title:
                continue

            source = feed["source"]
            variable = classify_variable(title, summary)
            direction = classify_direction(title, summary)
            weight = estimate_weight(source, title, summary)

            items.append({
                "title": title[:200],
                "summary": summary[:300],
                "source": source,
                "url": link,
                "pub_date": pub_date,
                "variable": variable,
                "direction": direction,
                "weight": weight,
                "chain": get_logical_chain(variable, direction),
            })

        logger.info(f"[NewsFetcher] {feed['source']}: 获取 {len(items)} 条")
        return items

    except requests.RequestException as e:
        logger.warning(f"[NewsFetcher] {feed['source']} 请求失败: {e}")
        return []
    except ET.ParseError as e:
        logger.warning(f"[NewsFetcher] {feed['source']} XML 解析失败: {e}")
        return []


def fetch_forex_factory_events(limit: int = 5) -> list[dict]:
    """从 NewsFilter 获取今日高影响事件作为新闻补充"""
    try:
        from services.news_filter import NewsFilter
        nf = NewsFilter()
        events = nf.get_upcoming_events(limit=limit)
        results = []
        for evt in events:
            title = evt.get("title", "")
            variable = classify_variable(title, "")
            direction = classify_direction(title, "")
            results.append({
                "title": title,
                "summary": f"影响: {evt.get('impact', '?')} | 货币: {evt.get('country', '?')} | 时间: {evt.get('datetime', '?')}",
                "source": "ForexFactory",
                "url": "",
                "pub_date": evt.get("datetime", ""),
                "variable": variable,
                "direction": direction,
                "weight": "high" if evt.get("impact") == "High" else "medium",
                "chain": get_logical_chain(variable, direction),
            })
        return results
    except Exception as e:
        logger.warning(f"[NewsFetcher] ForexFactory 获取失败: {e}")
        return []


# ── 聚合 ─────────────────────────────────────────────

class NewsFetcher:
    """多源新闻聚合器"""

    _last_fetch: float = 0
    _cache: list[dict] = []

    def fetch_news(self, limit: int = 15) -> list[dict]:
        """从所有源抓取新闻，去重后返回"""
        now = time.time()
        if now - self._last_fetch < CACHE_TTL and self._cache:
            return self._cache[:limit]

        all_items = []

        # RSS 源
        for feed in RSS_FEEDS:
            items = fetch_rss(feed)
            all_items.extend(items)

        # ForexFactory 日历事件
        ff_items = fetch_forex_factory_events(limit=5)
        all_items.extend(ff_items)

        # 去重（按标题模糊匹配）
        seen_titles = set()
        deduped = []
        for item in all_items:
            key = item["title"][:50].lower().strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                deduped.append(item)

        # 按权重排序（high 优先）
        weight_order = {"high": 0, "medium": 1, "low": 2}
        deduped.sort(key=lambda x: weight_order.get(x["weight"], 99))

        self._cache = deduped
        self._last_fetch = now

        logger.info(f"[NewsFetcher] 聚合完成: {len(deduped)} 条 (去重后)")
        return deduped[:limit]

    def compute_variable_scores(self, news_items: list[dict]) -> dict:
        """
        计算五大变量加权得分。
        返回: {variable: {score, count, bullish_count, bearish_count}}
        """
        scores = {}
        for var, weight in VARIABLE_WEIGHTS.items():
            scores[var] = {
                "weight": weight,
                "count": 0,
                "bullish": 0,
                "bearish": 0,
                "score": 0.0,  # -1 to +1
            }

        for item in news_items:
            var = item.get("variable", "other")
            if var not in scores:
                continue
            direction = item.get("direction", "neutral")
            w = {"high": 1.0, "medium": 0.5, "low": 0.2}.get(item.get("weight", "low"), 0)
            scores[var]["count"] += 1
            if direction == "bullish":
                scores[var]["bullish"] += w
            elif direction == "bearish":
                scores[var]["bearish"] += w

        # 归一化得分
        total_score = 0
        for var, s in scores.items():
            if s["count"] > 0:
                net = s["bullish"] - s["bearish"]
                max_possible = max(s["bullish"], s["bearish"], 1)
                s["score"] = round(net / max_possible, 2)
            total_score += s["score"] * s["weight"]

        return scores
