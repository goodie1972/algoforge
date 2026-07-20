"""
策略进出场逻辑加载器 — 从 docs/strategies/*.md 读取
每次请求实时解析，开发时修改 .md 文件即可生效
"""
import os
import re
import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "strategies")


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
    exitWiden: bool
    exitNote: str
    long: dict
    short: dict


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, body)"""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
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
    """从 markdown 解析入场因子表格"""
    pattern = rf"### {section_title}.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m = re.search(pattern, body, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).strip().split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cols = [c.strip() for c in line.split('|')]
        # cols[0]='', cols[1]=序号, cols[2]=因子名, cols[3]=得分, cols[4]=说明(可选)
        name = cols[2] if len(cols) > 2 else ''
        score = cols[3] if len(cols) > 3 else ''
        detail = cols[4] if len(cols) > 4 else ''
        rows.append({"name": name, "score": score, "detail": detail})
    return rows


def _parse_exit_table(body: str) -> list[dict]:
    """从 markdown 解析出场逻辑表格"""
    pattern = r"## 出场逻辑.*?\n\|.*?\n\|.*?\n((?:\|.*?\n)*)"
    m = re.search(pattern, body, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).strip().split('\n'):
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cols = [c.strip() for c in line.split('|')]
        # cols[0]='', cols[1]=序号, cols[2]=条件, cols[3]=说明(可选)
        method = cols[2] if len(cols) > 2 else ''
        normal = cols[3] if len(cols) > 3 else ''
        rows.append({"method": method, "normal": normal})
    return rows


def load_strategy_logic(name: str) -> StratLogic | None:
    """加载单个策略的进出场逻辑"""
    doc_dir = DOCS_DIR
    if not os.path.isdir(doc_dir):
        return None

    files = sorted(f for f in os.listdir(doc_dir) if f.endswith('.md'))
    fpath = None
    # 1. 精确文件名匹配 {name}.md
    exact = [f for f in files if f.lower() == f'{name}.md'.lower()]
    if exact:
        fpath = os.path.join(doc_dir, exact[0])
    else:
        # 2. 前缀+下划线匹配 {name}_.md (取最短)
        prefix = sorted([f for f in files if f.lower().startswith(f'{name}_'.lower())], key=len)
        if prefix:
            fpath = os.path.join(doc_dir, prefix[0])
        else:
            # 3. frontmatter name 精确匹配
            for fname in files:
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

    # 解析特别规则中的 exitNote
    sn_match = re.search(r'趋势感知[：:](.*?)(?=\n##|\Z)', body, re.DOTALL)
    if sn_match:
        exit_note = sn_match.group(1).strip()[:200]

    result: StratLogic = {
        "desc": meta.get('desc', ''),
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


def load_all_logics() -> dict[str, StratLogic]:
    """加载所有策略的进出场逻辑"""
    logics = {}
    doc_dir = DOCS_DIR
    if not os.path.isdir(doc_dir):
        logger.warning(f"策略文档目录不存在: {doc_dir}")
        return logics

    for fname in sorted(os.listdir(doc_dir)):
        if not fname.endswith('.md'):
            continue
        try:
            with open(os.path.join(doc_dir, fname), 'r', encoding='utf-8') as f:
                content = f.read()
            meta, _ = _parse_frontmatter(content)
            name = meta.get('name', fname.replace('.md', ''))
            logics[name] = load_strategy_logic(name)
        except Exception as e:
            logger.warning(f"解析 {fname} 失败: {e}")

    return {k: v for k, v in logics.items() if v is not None}


def get_strategy_logics() -> dict[str, StratLogic]:
    """返回所有策略逻辑定义（供前端API查询），每次实时解析"""
    return load_all_logics()


def get_strategy_logic(name: str) -> StratLogic | None:
    """返回单个策略逻辑定义"""
    return load_strategy_logic(name)
