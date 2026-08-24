# -*- coding: utf-8 -*-
"""为缺失的策略术语生成英文翻译，写入 strategyTranslations.ts"""
import sys, os, re, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.llm_provider import LLMProviderManager


def translate_terms(terms: list[str]) -> dict[str, str]:
    manager = LLMProviderManager()
    provider = manager.get_active_raw()
    if not provider or not provider.get("api_key"):
        print("未配置 LLM Provider")
        return {}

    result_map: dict[str, str] = {}
    batch_size = 30
    for i in range(0, len(terms), batch_size):
        batch = terms[i : i + batch_size]
        news_text = "\n".join([f"{j+1}. {t}" for j, t in enumerate(batch)])
        prompt = f"""你是金融交易术语翻译专家。请将以下中文交易术语翻译成简洁的英文（金融/技术分析术语）。

要求：
- 保持专业术语准确性（金叉=golden cross, 死叉=death cross, 布林带=Bollinger Bands, 均线=MA, ATR 保持原样）
- 数字、指标参数(RSI/MFI/EMA/BB/ADX)保持原样
- 只输出翻译，不要解释
- 已含英文的术语直接重复

格式每行: "中文术语": "English translation",
第 {i+1}-{min(i+batch_size, len(terms))} 条：
{news_text}"""
        try:
            result = manager.chat([{"role": "user", "content": prompt}])
            if not result:
                print(f"批次 {i} 失败")
                continue
            for line in str(result).split("\n"):
                line = line.strip().rstrip(",")
                m = re.match(r'"(.+)"\s*[:：]\s*"(.+)"', line)
                if m:
                    result_map[m.group(1)] = m.group(2)
        except Exception as e:
            print(f"批次 {i} 异常: {e}")
        time.sleep(1)
    return result_map


def main():
    terms = [
        l.strip() for l in open("missing_terms2.txt", encoding="utf-8").read().split("\n") if l.strip()
    ]
    print(f"待翻译: {len(terms)} 条")
    mapping = translate_terms(terms)
    print(f"翻译成功: {len(mapping)} 条")

    if not mapping:
        print("无翻译结果，退出")
        return

    # 读取现有映射文件
    path = "dashboard/frontend/src/utils/strategyTranslations.ts"
    src = open(path, encoding="utf-8").read()
    # 在 detailTranslations 的末尾（} 前）插入
    insert_point = src.rfind("\n}")
    if insert_point < 0:
        print("找不到插入点")
        return

    lines = []
    for cn, en in sorted(mapping.items()):
        if f'"{cn}"' in src:
            continue
        lines.append(f'  "{cn}": "{en}",')
    block = "\n".join(lines)
    if block:
        src = src[:insert_point] + "\n" + block + src[insert_point:]
        open(path, "w", encoding="utf-8").write(src)
        print(f"已插入 {len(lines)} 条翻译 -> {path}")
    else:
        print("无新增翻译")


if __name__ == "__main__":
    main()