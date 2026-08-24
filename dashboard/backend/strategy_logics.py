"""
策略进出场逻辑加载器 — 从 docs/strategies/*.md 读取
每次请求实时解析，开发时修改 .md 文件即可生效
"""
import os
import re
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "strategies", "docs", "strategies")


class EntryFactor(TypedDict, total=False):
    name: str
    score: str
    detail: str


class ExitRow(TypedDict, total=False):
    method: str
    normal: str
    widen: str


class StratLogic(TypedDict, total=False):
    desc: str
    desc_en: str
    display_en: str
    exitWiden: bool
    exitNote: str
    long: dict
    short: dict


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, body)"""
    m = re.match(r'^---\s*\n?(.*?)\n---\s*\n(.*)', text, re.DOTALL)
    if not m:
        return {}, text
    yaml_text = m.group(1)
    body = m.group(2).strip()
    meta = {}
    for line in yaml_text.strip().split('\n'):
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip().strip("'\"")
    return meta, body


def _parse_entry_table(body: str, section_title: str) -> list[dict]:
    """从 markdown 解析入场因子表格 — 支持灵活标题匹配"""
    # 先精确匹配 section_title（如 "BUY（做多）"）
    pattern = rf"### {re.escape(section_title)}\s*\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m = re.search(pattern, body, re.DOTALL)
    if m:
        return _parse_table_rows(m.group(1))

    # 再尝试匹配"三层筛子（做多"或"三层筛子（做空"（新策略格式）
    search = "三层筛子（做多" if "做多" in section_title else "三层筛子（做空"
    pattern2 = rf"### {re.escape(search)}.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m2 = re.search(pattern2, body, re.DOTALL)
    if m2:
        return _parse_table_rows(m2.group(1))

    # 尝试匹配英文标题 "BUY (Long)" / "SELL (Short)" / "Long Entry" / "Short Entry"
    en_search = "BUY \\(Long\\)|Long Entry|Three-Layer Filter \\(Long" if "做多" in section_title else "SELL \\(Short\\)|Short Entry|Three-Layer Filter \\(Short"
    pattern_en = rf"### ({en_search}).*?\n\s*\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m_en = re.search(pattern_en, body, re.DOTALL)
    if m_en:
        return _parse_table_rows(m_en.group(2))

    # 最后尝试"入场条件"下的通用表格（bakome 等格式）
    pattern3 = r"### 入场条件.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m3 = re.search(pattern3, body, re.DOTALL)
    if m3:
        return _parse_table_rows(m3.group(1))

    # 终极 fallback：尝试纯中文标题 "### 做多" / "### 做空"（含括号后缀如"做多（超卖）"）
    search_zh = "做多" if "做多" in section_title else "做空"
    pattern4 = rf"### {re.escape(search_zh)}[（(]?.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m4 = re.search(pattern4, body, re.DOTALL)
    if m4:
        return _parse_table_rows(m4.group(1))

    return []


def _parse_table_rows(table_text: str) -> list[dict]:
    """解析 markdown 表格行（通用，自动识别 3 列/4 列布局）"""
    import re as _re
    rows = []
    for line in table_text.strip().split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cols = [c.strip() for c in line.split('|')]
        if len(cols) < 3:
            continue
        # cols[0]='' cols[1]=序号 cols[2]=条件/因子
        name = cols[2] if len(cols) > 2 else ''
        score = ''
        detail = ''
        if len(cols) >= 5:
            # 4 列布局: # | 因子 | 得分 | 说明
            score_cand = cols[3]
            detail_cand = cols[4]
            # 第3列是纯数字/分数形式（+1/+2/1.5/10分）才当作 score
            if _re.match(r'^[+-]?\d+(\.\d+)?([分点]|[×x]\d)?$', score_cand) or \
               _re.match(r'^[+-]?\d+$', score_cand):
                score = score_cand
                detail = detail_cand
            else:
                detail = score_cand
                if detail_cand:
                    detail += ('' if not detail_cand.startswith(('，', '、', '；')) else detail_cand)
        elif len(cols) == 4:
            # 3 列布局: # | 条件 | 说明
            detail = cols[3]
        rows.append({"name": name, "score": score, "detail": detail})
    return rows


def _parse_exit_table(body: str) -> list[dict]:
    """从 markdown 解析出场逻辑表格 — 返回 {method, normal} 结构"""
    # 先找"出场逻辑"或"出场"标题
    for header in [r"## 出场逻辑", r"### 出场"]:
        pattern = rf"{header}.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
        m = re.search(pattern, body, re.DOTALL)
        if m:
            rows = _parse_table_rows(m.group(1))
            # 转换为前端期望的 {method, normal} 结构
            return [{"method": r.get("name", ""), "normal": r.get("detail", "") or r.get("score", "")} for r in rows]
    return []


def load_strategy_logic(name: str, lang: str = "zh") -> StratLogic | None:
    """加载单个策略的进出场逻辑（lang=zh 读 _cn.md，lang=en 读 _en.md）"""
    doc_dir = DOCS_DIR
    if not os.path.isdir(doc_dir):
        return None

    suffix = "_cn" if lang == "zh" else "_en"
    files = sorted(f for f in os.listdir(doc_dir) if f.endswith('.md'))
    fpath = None
    # 1. 精确文件名匹配 {name}_cn.md 或 {name}_en.md
    exact = [f for f in files if f.lower() == f'{name}{suffix}.md'.lower()]
    if exact:
        fpath = os.path.join(doc_dir, exact[0])
    else:
        # 2. 前缀+下划线匹配 {name}_cn_.md / {name}_en_.md
        prefix = sorted([f for f in files if f.lower().startswith(f'{name}{suffix}_'.lower())], key=len)
        if prefix:
            fpath = os.path.join(doc_dir, prefix[0])
        else:
            # 3. frontmatter name 精确匹配（只匹配对应语言的 _cn/_en 文件）
            for fname in files:
                if not fname.endswith(f'{suffix}.md'):
                    continue
                try:
                    with open(os.path.join(doc_dir, fname), 'r', encoding='utf-8') as f:
                        fc = f.read()
                    meta, _ = _parse_frontmatter(fc)
                    if meta.get('name') == name:
                        fpath = os.path.join(doc_dir, fname)
                        break
                except Exception:
                    continue
    if fpath is None:
        return None

    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None

    meta, body = _parse_frontmatter(content)
    has_exit_widen = '加宽' in body
    exit_note = ''

    # 解析特别规则中的 exitNote（优先从 frontmatter 读，降级到 body 趋势感知）
    exit_note = meta.get('exitNote', '') or ''
    if not exit_note:
        sn_match = re.search(r'趋势感知[：:](.*?)(?=\n##|\Z)', body, re.DOTALL)
        if sn_match:
            exit_note = sn_match.group(1).strip()[:200]

    result: StratLogic = {
        "desc": meta.get('desc', ''),
        "desc_en": meta.get('desc_en') or meta.get('desc', ''),
        "display_en": meta.get('display_en', ''),
        "exitWiden": has_exit_widen,
        "exitNote": exit_note,
    }

    for side_key, side_title in [("long", "BUY（做多）"), ("short", "SELL（做空）")]:
        entry_rows = _parse_entry_table(body, side_title)
        exit_rows = _parse_exit_table(body)
        result[side_key] = {
            "entry": entry_rows or [],
            "exit": exit_rows or [],
        }

    return result


def load_all_logics(lang: str = "zh") -> dict[str, StratLogic]:
    """加载所有策略的进出场逻辑（lang=zh 读 _cn.md，lang=en 读 _en.md）"""
    logics = {}
    doc_dir = DOCS_DIR
    if not os.path.isdir(doc_dir):
        logger.warning(f"strategydocdirectorynot found: {doc_dir}")
        return logics

    suffix = "_cn" if lang == "zh" else "_en"
    for fname in sorted(os.listdir(doc_dir)):
        if not fname.endswith('.md') or not fname.endswith(f'{suffix}.md'):
            continue
        try:
            with open(os.path.join(doc_dir, fname), 'r', encoding='utf-8') as f:
                content = f.read()
            meta, _ = _parse_frontmatter(content)
            name = meta.get('name', fname.replace(f'{suffix}.md', ''))
            logics[name] = load_strategy_logic(name, lang=lang)
        except Exception as e:
            logger.warning(f"parse {fname} failed: {e}")

    return {k: v for k, v in logics.items() if v is not None}


def get_strategy_logics(lang: str = "zh") -> dict[str, StratLogic]:
    """返回所有策略逻辑定义（供前端API查询），每次实时解析"""
    return load_all_logics(lang=lang)


def get_strategy_logic(name: str) -> StratLogic | None:
    """返回单个策略逻辑定义"""
    return load_strategy_logic(name)
