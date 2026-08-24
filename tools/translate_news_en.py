# -*- coding: utf-8 -*-
"""批量翻译 gold_news 表中 content_en 为中文原文的记录为英文

用法: python tools/translate_news_en.py [limit] [offset]
"""
import sys
import os
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("translate_news_en")

from services.llm_provider import LLMProviderManager


def translate_batch(items: list[dict]) -> list[dict]:
    """调用 LLM 批量翻译（每批 5 条）"""
    manager = LLMProviderManager()
    if not manager.get_active_raw() or not manager.get_active_raw().get("api_key"):
        logger.error("未配置 LLM Provider")
        return []

    news_text = "\n".join([f"{j+1}. {item['content']}" for j, item in enumerate(items)])
    prompt = f"""你是一个黄金市场新闻翻译专家。请将以下每条中文新闻翻译成英文。

要求：
- 保持金融术语准确
- 简洁流畅，符合英文新闻风格
- 不要翻译人名和机构名以外的不必要内容

请对每条新闻按序号回答，格式: "序号: 英文翻译"

新闻列表：
{news_text}"""

    try:
        result = manager.chat([{"role": "user", "content": prompt}])
        if not result:
            return []
        # 解析翻译
        translations: dict[int, str] = {}
        for line in str(result).split("\n"):
            line = line.strip()
            if ":" in line and line.split(":", 1)[0].strip().isdigit():
                idx = int(line.split(":", 1)[0].strip())
                translations[idx] = line.split(":", 1)[1].strip()
        for i, item in enumerate(items):
            if i + 1 in translations:
                item["content_en"] = translations[i + 1]
        return items
    except Exception as e:
        logger.error(f"LLM 翻译异常: {e}")
        return []


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    from data import database as db
    db.init_db()
    conn = db.get_conn()

    # 找出 content_en 仍为中文原文（= content）或为空的记录
    rows = conn.execute(
        """SELECT id, content, content_en FROM gold_news
           WHERE content_en IS NULL OR content_en = '' OR content_en = content
           ORDER BY rowid DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    logger.info(f"待翻译记录: {len(rows)} 条 (limit={limit}, offset={offset})")

    if not rows:
        logger.info("没有需要翻译的记录")
        return

    # 分 5 条一批
    batch_size = 5
    done = 0
    for i in range(0, len(rows), batch_size):
        batch_rows = rows[i : i + batch_size]
        items = [{"id": r[0], "content": r[1], "content_en": r[2]} for r in batch_rows]
        translated = translate_batch(items)
        for item in translated:
            if item.get("content_en") and item["content_en"] != item["content"]:
                conn.execute(
                    "UPDATE gold_news SET content_en=? WHERE id=?",
                    (item["content_en"], item["id"]),
                )
                done += 1
        conn.commit()
        if i + batch_size < len(rows):
            time.sleep(1)

    logger.info(f"完毕: 成功翻译 {done}/{len(rows)} 条")
    conn.close()


if __name__ == "__main__":
    main()