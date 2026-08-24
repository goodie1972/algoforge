"""
汇通快讯爬虫 — 抓取汇通网 7×24 快讯，用 LLM 判断对黄金的多空方向
======================================================================
数据源: https://kx.fx678.com (免费，无 Cloudflare)
LLM 判断: 每条快讯判断「利多黄金/利空黄金/中性」
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HUICONG_URL = "https://kx.fx678.com"
JIN10_URL = "https://www.jin10.com"
REQUEST_INTERVAL = 10  # 每次请求间隔 10 秒（避免反爬）
CACHE_TTL = 300  # 内存缓存 5 分钟

# 需要关注的黄金相关关键词（用于预过滤快讯，减少 LLM 调用）
GOLD_KEYWORDS = [
    "黄金", "金价", "现货黄金", "伦敦金", "XAUUSD",
    "非农", "CPI", "PPI", "GDP", "核心通胀",
    "美联储", "FOMC", "鲍威尔", "加息", "降息",
    "通胀", "美元指数", "美债", "收益率",
    "地缘", "避险", "战争", "制裁",
    "失业", "初请", "零售", "制造业PMI",
    "ISM", "消费者信心", "耐用品",
    # 英文关键词（英文源）
    "gold", "XAU", "precious metal", "bullion", "silver",
    "Fed", "FOMC", "inflation", "CPI", "PPI", "GDP",
    "dollar index", "Treasury", "yield", "rate cut", "rate hike",
    "sanctions", "safe haven", "geopolitical", "nonfarm",
]

# 英文源 URL
FXSTREET_URL = "https://www.fxstreet.com/news"
KITCO_URL = "https://www.kitco.com/news"


def fetch_huicong_news() -> list[dict]:
    """
    抓取汇通快讯页面，解析快讯列表。
    从 topaid ID 中提取精确时间戳。
    返回: [{"time": "2026-08-08 10:53:51", "content": "...", "source": "huicong", ...}, ...]
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.fx678.com/",
    }

    resp = requests.get(HUICONG_URL, headers=headers, timeout=15)
    resp.encoding = "utf-8"
    html = resp.text

    items = []

    # 从 topaid ID 中提取时间: topaid202608081053512063
    # 格式: topaid{YYYY}{MM}{DD}{HH}{MM}{SS}{随机}
    for m in re.finditer(
        r'id="topaid(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\d*"[^>]*href="([^"]*)"[^>]*>([^<]+)</a>',
        html,
    ):
        y, mo, d, h, mi, s = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        url = m.group(7).strip()
        content = m.group(8).strip()
        if not content or len(content) < 5:
            continue
        if url and not url.startswith("http"):
            url = "https://flash.fx678.com" + url
        dt = f"{y}-{mo}-{d} {h}:{mi}:{s}"
        items.append({
            "time": dt,
            "content": content,
            "source": "huicong",
            "url": url,
            "lang": "zh",
            "fetched_at": time.time(),
        })

    # 去重
    seen = set()
    unique = []
    for item in items:
        key = item["content"][:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    logger.info(f"[HuiChengNews] Fetched {len(unique)} (raw {len(items)})")
    return unique


def _extract_nearby_time(html: str, content: str) -> str:
    """从 HTML 中找内容附近的时间"""
    # 用正则找时间模式 HH:MM:SS
    idx = html.find(content[:30])
    if idx < 0:
        return ""
    # 在内容前 500 字符内找时间
    before = html[max(0, idx - 500):idx]
    times = re.findall(r"(\d{2}:\d{2}:\d{2})", before)
    return times[-1] if times else ""


def fetch_fxstreet_news() -> list[dict]:
    """抓取 FXStreet 新闻列表（英文源），返回 {time, content, url, source='fxstreet', lang='en'}"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(FXSTREET_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"[FXStreet] fetch failed: {e}")
        return []

    items = []
    # FXStreet 文章链接: https://www.fxstreet.com/news/xxx-202608240842
    for m in re.finditer(r'<a[^>]*href="(https://www\.fxstreet\.com/news/[^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
        url = m.group(1)
        content = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not content or len(content) < 15:
            continue
        items.append({
            "time": "",
            "content": content,
            "source": "fxstreet",
            "url": url,
            "lang": "en",
            "fetched_at": time.time(),
        })

    # 去重（按内容前 50 字）
    seen = set()
    unique = []
    for item in items:
        key = item["content"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    logger.info(f"[FXStreet] Fetched {len(unique)} (raw {len(items)})")
    return unique


def fetch_kitco_news() -> list[dict]:
    """抓取 Kitco 新闻列表（英文源），返回 {time, content, url, source='kitco', lang='en'}"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(KITCO_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"[Kitco] fetch failed: {e}")
        return []

    items = []
    # Kitco 文章: <a href="/news/article/2026-08-21/xxx"><img alt="标题 teaser image"...>
    for m in re.finditer(r'<a[^>]*href="(/news/article/[^"]+)"[^>]*>(?:(?!</a>).)*?alt="([^"]+)"', html, re.DOTALL):
        url = "https://www.kitco.com" + m.group(1)
        content = m.group(2).strip()
        # 去掉尾部 "<source> teaser image" 等后缀
        content = re.sub(r'\s*[-–]\s*Kitco.*$', '', content)
        content = re.sub(r'\s+teaser image.*$', '', content)
        content = content.replace("&amp;", "&").replace("&#39;", "'").strip()
        if not content or len(content) < 10:
            continue
        items.append({
            "time": "",
            "content": content,
            "source": "kitco",
            "url": url,
            "lang": "en",
            "fetched_at": time.time(),
        })

    # 去重
    seen = set()
    unique = []
    for item in items:
        key = item["content"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    logger.info(f"[Kitco] Fetched {len(unique)} (raw {len(items)})")
    return unique


def filter_gold_related(news: list[dict]) -> list[dict]:
    """过滤出与黄金相关的快讯"""
    gold_news = []
    for item in news:
        content = item.get("content", "")
        if any(kw in content for kw in GOLD_KEYWORDS):
            gold_news.append(item)
    return gold_news


def judge_with_llm(news: list[dict], llm_manager) -> list[dict]:
    """
    用 LLM 判断每条快讯对黄金的多空方向。
    批量判断（多条合并为一次调用，减少 LLM 请求数）。
    """
    if not news or not llm_manager:
        return []

    # 每次最多 5 条，避免 LLM 上下文过长
    batch_size = 5
    results = []

    for i in range(0, len(news), batch_size):
        batch = news[i:i + batch_size]
        try:
            # 构建 LLM 提示
            news_text = "\n".join([f"{j+1}. {item['content']}" for j, item in enumerate(batch)])
            prompt = f"""你是一个黄金交易分析专家。请判断以下每条新闻对黄金(XAUUSD)价格的影响，并翻译成英文。

规则：
- 利多黄金 = 利好金价上涨（如：美联储降息预期、通胀降温、就业恶化、地缘避险、美元走弱）
- 利空黄金 = 利空金价下跌（如：美联储加息预期、通胀升温、就业强劲、避险消退、美元走强）
- 中性 = 无明显影响或影响不确定

请对每条新闻按序号回答，格式: "序号: 利多/利空/中性 | 英文翻译"

注意：英文翻译要简洁，保持金融术语准确。

新闻列表：
{news_text}"""

            result = llm_manager.chat([
                {"role": "user", "content": prompt}
            ])

            if not result:
                logger.warning("[LLM GoldJudge] call failed, falling back to keyword rules")
                # 回退到规则判断
                for item in batch:
                    item["direction"] = _rule_based_judge(item["content"])
                    item["direction_reason"] = "规则回退"
                    item["direction_confidence"] = "low"
                    item["content_en"] = item["content"]  # 无翻译，用原文
                    results.append(item)
                continue

            # 解析 LLM 回复（方向 + 英文翻译）
            for j, item in enumerate(batch):
                line_num = j + 1
                direction = "中性"
                translation = ""
                # 在 LLM 回复中找对应序号
                for line in result.split("\n"):
                    if str(line_num) in line:
                        if "利多" in line:
                            direction = "bullish"
                        elif "利空" in line:
                            direction = "bearish"
                        else:
                            direction = "neutral"
                        # 提取翻译（分隔符 | 后面）
                        if "|" in line:
                            translation = line.split("|", 1)[1].strip()
                        break
                else:
                    # 如果 LLM 没回答，用关键词回退
                    direction = _rule_based_judge(item["content"])
                    translation = item["content"]

                item["direction"] = direction
                item["direction_reason"] = "LLM判断" if direction != _rule_based_judge(item["content"]) else "规则回退"
                item["direction_confidence"] = "high" if direction != "neutral" else "low"
                item["content_en"] = translation or item["content"]  # 无翻译用原文
                results.append(item)

        except Exception as e:
            logger.error(f"[LLM GoldJudge] batch processing exception: {e}")
            for item in batch:
                item["direction"] = _rule_based_judge(item["content"])
                item["direction_reason"] = "规则回退"
                item["direction_confidence"] = "low"
                results.append(item)

        # 批次间隔，避免 LLM API 限流
        if i + batch_size < len(news):
            time.sleep(1)

    return results


def _rule_based_judge(content: str) -> str:
    """关键词规则判断（LLM 回退方案）"""
    content_lower = content.lower()

    # 利多模式
    bullish = [
        "飙涨", "狂飙", "大涨", "走高", "攀升", "拉升",
        "利多黄金", "利好黄金", "黄金上涨", "黄金飙升",
        "非农减少", "非农爆冷", "就业意外", "失业率上升",
        "意外降息", "降息", "鸽派", "避险", "冲突",
        "通胀降温", "CPI低于预期", "物价回落",
        "美联储放鸽", "美元走弱", "美元下跌",
        "地缘紧张", "战争", "制裁", "导弹",
    ]
    # 利空模式
    bearish = [
        "暴跌", "狂跌", "大跌", "走低", "下滑", "承压",
        "利空黄金", "利空黄金", "黄金下跌", "黄金跳水",
        "非农增加", "非农超预期", "就业强劲", "失业率下降",
        "意外加息", "加息", "鹰派", "美元走强",
        "通胀升温", "CPI高于预期", "物价上涨",
        "美联储放鹰", "美元上涨",
        "避险消退", "停火", "风险偏好",
    ]
    # 英文利多模式
    bullish_en = [
        "surge", "rally", "soar", "jump", "higher", "gain", "climb",
        "rate cut", "dovish", "safe haven", "risk-off",
        "weak dollar", "dollar weak", "inflation cools", "yields fall",
        "sanctions", "geopolitical tension", "war", "strike",
        "philly fed", "below expectations", "unemployment up",
    ]
    # 英文利空模式
    bearish_en = [
        "slump", "plunge", "drop", "fall", "lower", "decline", "slide",
        "rate hike", "hawkish", "risk-on", "strong dollar", "dollar firm",
        "inflation hot", "yields rise", "ceasefire", "risk appetite",
        "unemployment down", "above expectations", "bounce",
    ]

    for kw in bullish:
        if kw in content:
            return "bullish"
    for kw in bearish:
        if kw in content:
            return "bearish"
    # 英文：黄金自身涨跌优先（gold/xau + 涨跌词）
    gold_mentions_gold = "gold" in content_lower or "xau" in content_lower
    if gold_mentions_gold:
        for kw in ["rally", "surge", "soar", "jump", "gain", "climb", "higher", "highs",
                   "breaks above", "up", "rebound", "firm", "steady gains"]:
            if kw in content_lower:
                return "bullish"
        for kw in ["slump", "plunge", "drop", "fall", "lower", "decline", "slide",
                   "weak", "loss", "below", "retreat", "pullback", "down"]:
            if kw in content_lower:
                return "bearish"
    for kw in bullish_en:
        if kw in content_lower:
            return "bullish"
    for kw in bearish_en:
        if kw in content_lower:
            return "bearish"
    return "neutral"


def save_huicong_news(news: list[dict]):
    """保存汇通快讯到数据库 gold_news 表"""
    try:
        from data import database as db
        db.init_db()
        db.insert_gold_news(news)
        logger.info(f"[HuiChengNews] saved {len(news)} to database")
    except Exception as e:
        logger.error(f"[HuiChengNews] savefailed: {e}")


def fetch_jin10_news() -> list[dict]:
    """
    抓取金十数据首页快讯列表。
    返回: [{"time": "", "content": "...", "source": "jin10", ...}, ...]
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.jin10.com/",
    }

    resp = requests.get(JIN10_URL, headers=headers, timeout=15)
    resp.encoding = "utf-8"
    html = resp.text

    # 金十快讯结构: <div class="flash-item"> 内含 flash-text
    items = []
    for m in re.finditer(
        r'<div[^>]*class="[^"]*flash-item[^"]*"[^>]*>(.*?)</div>',
        html, re.DOTALL,
    ):
        block = m.group(1)
        content_match = re.search(r'class="[^"]*flash-text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        if not content_match:
            continue
        content = re.sub(r"<[^>]+>", "", content_match.group(1)).strip()
        if not content or len(content) < 5:
            continue
        # 提取链接（flash-item 内的 <a href>）
        url = ""
        href = re.search(r'href="([^"]+)"', block)
        if href:
            url = href.group(1)
            if url and not url.startswith("http"):
                url = "https://www.jin10.com" + url
        items.append({
            "time": "",
            "content": content,
            "source": "jin10",
            "url": url,
            "lang": "zh",
            "fetched_at": time.time(),
        })

    # 去重
    seen = set()
    unique = []
    for item in items:
        key = item["content"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    logger.info(f"[Jin10Data] Fetched {len(unique)} news")
    return unique


def fetch_and_judge(llm_manager=None) -> list[dict]:
    """
    完整流程：抓取汇通+金十 → 过滤 → LLM判断 → 保存 → 返回
    """
    logger.info("[GoldNews] Starting fetch + judge...")

    # 抓取多源（中文：汇通+金十；英文：FXStreet+Kitco）
    all_news = []
    try:
        all_news.extend(fetch_huicong_news())
    except Exception as e:
        logger.warning(f"[HuiChengNews] fetch failed: {e}")
    try:
        all_news.extend(fetch_jin10_news())
    except Exception as e:
        logger.warning(f"[Jin10Data] fetch failed: {e}")
    try:
        all_news.extend(fetch_fxstreet_news())
    except Exception as e:
        logger.warning(f"[FXStreet] fetch failed: {e}")
    try:
        all_news.extend(fetch_kitco_news())
    except Exception as e:
        logger.warning(f"[Kitco] fetch failed: {e}")

    if not all_news:
        logger.warning("[GoldNews] No news fetched")
        return []

    gold_news = filter_gold_related(all_news)
    logger.info(f"[GoldNews] gold related: {len(gold_news)}/{len(all_news)}")

    if llm_manager:
        gold_news = judge_with_llm(gold_news, llm_manager)
    else:
        for item in gold_news:
            item["direction"] = _rule_based_judge(item["content"])
            item["direction_reason"] = "规则判断"
            item["direction_confidence"] = "low"

    save_huicong_news(gold_news)
    # 评估上次的新闻判断准确性
    try:
        evaluate_past_gold_news()
    except Exception as e:
        logger.warning(f"[GoldNews] evaluateexception: {e}")
    return gold_news


def _get_price_at(target_ts: float) -> float:
    """获取 M5 K 线中离目标时间最近的收盘价，误差 5 分钟内"""
    try:
        from data import database as db
        recent_ts = target_ts - 30 * 86400
        candles = db.get_candles("M5", start_ts=int(recent_ts), limit=8000)
        if not candles:
            return 0
        best = 0
        best_diff = float("inf")
        for c in candles:
            c_ts = c.get("time", 0)
            diff = abs(c_ts - target_ts)
            if diff < best_diff and diff < 300:
                best = c.get("close", c.get("close_price", 0))
                best_diff = diff
        return best or 0
    except Exception:
        return 0


def evaluate_past_gold_news():
    """
    评估过去未评估的黄金快讯判断准确性。
    找 gold_news 表中 evaluated_at IS NULL 且距今超过 1 小时的记录，
    对比方向判断 vs 实际价格走势。
    """
    from data import database as db
    conn = db.get_conn()
    try:
        # 找未评估且距今超过 1 小时的记录
        cutoff = time.time() - 3600
        rows = conn.execute(
            "SELECT id, content, direction, fetched_at FROM gold_news "
            "WHERE evaluated_at IS NULL AND fetched_at < ? "
            "ORDER BY fetched_at ASC LIMIT 20",
            (cutoff,),
        ).fetchall()

        if not rows:
            return

        evaluated = 0
        for row in rows:
            row = dict(row)
            gid = row["id"]
            direction = row["direction"]
            fetched_at = row["fetched_at"]

            if direction == "neutral":
                # 中性判断不评估
                conn.execute("UPDATE gold_news SET evaluated_at=? WHERE id=?", (time.time(), gid))
                continue

            # 获取价格: 判断前 15 分钟、后 15 分钟、后 1 小时
            pre_ts = fetched_at - 900
            post_15m_ts = fetched_at + 900
            post_1h_ts = fetched_at + 3600

            pre_price = _get_price_at(pre_ts)
            post_15m_price = _get_price_at(post_15m_ts)
            post_1h_price = _get_price_at(post_1h_ts)

            move_15m = round(post_15m_price - pre_price, 2) if post_15m_price and pre_price else 0
            move_1h = round(post_1h_price - pre_price, 2) if post_1h_price and pre_price else 0

            # 判断方向是否匹配
            direction_match = None
            if direction in ("bullish", "bearish") and move_15m != 0:
                if (direction == "bullish" and move_15m > 0) or (direction == "bearish" and move_15m < 0):
                    direction_match = 1  # correct
                else:
                    direction_match = 0  # wrong

            conn.execute(
                """UPDATE gold_news SET
                   pre_price=?, post_price_15m=?, post_price_1h=?,
                   actual_move_15m=?, actual_move_1h=?,
                   direction_match=?, evaluated_at=?
                   WHERE id=?""",
                (pre_price, post_15m_price, post_1h_price,
                 move_15m, move_1h,
                 direction_match, time.time(), gid),
            )
            evaluated += 1
            logger.info(
                f"[GoldEval] id={gid} {direction} 实动={move_15m:+.2f} "
                f"{'✅正确' if direction_match==1 else '❌错误' if direction_match==0 else 'N/A'}"
            )

        conn.commit()
        if evaluated:
            logger.info(f"[GoldEval] Evaluated {evaluated} this round ")
    except Exception as e:
        logger.warning(f"[GoldEval] exception: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    from services.llm_provider import LLMProviderManager
    mgr = LLMProviderManager()
    active = mgr.get_active()
    if not active:
        for p in mgr._providers:
            if p.get("api_key"):
                mgr.set_active(p["id"])
                break
    results = fetch_and_judge(mgr)
    for r in results[:5]:
        print(f"  [{r.get('direction','?')}] {r['content'][:60]}")