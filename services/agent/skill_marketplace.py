"""
技能商店 / 本地技能接入 — 平台注册表 + 适配器 + 安装/卸载

原则：能固化就固化、不能固化就提供直连 URL 跳浏览器。
- skill.sh（A 级）：系统内代理搜索 API，结果从 GitHub raw 拉取安装
- skillsmp / skillhub.cn（C 级）：直链跳转浏览，用户回系统粘贴链接/内容安装
"""
import logging
import os
import re
import shutil
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_ROOT = os.path.join(PROJECT_ROOT, "skills")
IMPORTED_ROOT = os.path.join(SKILLS_ROOT, "imported")  # 商店/粘贴安装的技能落盘处

MAX_CONTENT_BYTES = 200 * 1024  # 200KB 上限
HTTP_TIMEOUT = 10.0

# ── 平台注册表（直链 URL 固化在此）────────────────────────
SKILL_PLATFORMS = [
    {
        "id": "skillsh",
        "name": "skill.sh",
        "url": "https://skills.sh",
        "level": "api",
        "grade": "A",
        "description": "开放技能搜索引擎 — 系统内直接搜索并一键安装",
    },
    {
        "id": "skillsmp",
        "name": "skillsmp",
        "url": "https://skillsmp.com",
        "level": "link",
        "grade": "C",
        "description": "技能集市 — 浏览器打开后复制内容/链接回本系统粘贴安装",
    },
    {
        "id": "skillhubcn",
        "name": "skillhub.cn",
        "url": "https://skillhub.cn",
        "level": "link",
        "grade": "C",
        "description": "中文技能社区 — 浏览器打开后复制内容/链接回本系统粘贴安装",
    },
]

PLATFORM_BY_ID = {p["id"]: p for p in SKILL_PLATFORMS}


class MarketplaceError(Exception):
    """技能商店操作的明确错误（消息可直接展示给用户）"""


def _proxy() -> str:
    """复用系统代理环境变量（与 routes/ai.py 保持一致）"""
    return (os.environ.get("LLM_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or "")


def _client() -> httpx.Client:
    kwargs = {"timeout": HTTP_TIMEOUT, "follow_redirects": True}
    proxy = _proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


# ── GitHub raw 拉取工具 ───────────────────────────────────

def _parse_ref(ref: str) -> tuple[str, str, str]:
    """把用户输入解析为 (owner, repo, path)。

    支持：owner/repo、owner/repo/sub/path、
    https://github.com/owner/repo(/tree/branch/path)、
    各平台技能页链接中内嵌的 github owner/repo。
    解析失败抛 MarketplaceError。
    """
    ref = (ref or "").strip().strip("/")
    if not ref:
        raise MarketplaceError("输入为空：请粘贴技能页链接或 owner/repo 路径")

    # 从 URL 中抽取 github.com/{owner}/{repo}/... 段
    m = re.search(r"github\.com[/:]([\w.\-]+)/([\w.\-]+)(?:/(?:tree|blob)/[^/?#]+(/[^?#]*)?)?", ref)
    if m:
        owner, repo = m.group(1), m.group(2)
        path = (m.group(3) or "").strip("/")
        return owner, repo, path

    # 裸路径 owner/repo[/path...]（skill.sh 搜索结果 / 手工输入）
    if re.match(r"^[\w.\-]+/[\w.\-]+", ref) and "://" not in ref:
        parts = ref.split("/")
        return parts[0], parts[1], "/".join(parts[2:]).strip("/")

    raise MarketplaceError(
        f"无法从输入中解析出 GitHub 源（owner/repo）：{ref[:80]}\n"
        "请粘贴形如 owner/repo 或包含 github 仓库的技能页链接；"
        "也可以直接粘贴 SKILL.md 全文内容安装。"
    )


def _fetch_github_raw(owner: str, repo: str, path: str) -> str:
    """从 GitHub raw 拉取 SKILL.md 内容。

    候选地址：{path}/SKILL.md 与 path 本身（若以 SKILL.md 结尾），分支依次尝试 HEAD → main → master。
    """
    path = (path or "").strip("/")
    if path.lower().endswith("skill.md"):
        candidates = [path]
    elif path:
        # skill.sh 实测：仓库内技能多放在 skills/{skillId}/SKILL.md，两种候选都尝试
        candidates = [f"{path}/SKILL.md", f"skills/{path}/SKILL.md"]
    else:
        candidates = ["SKILL.md"]

    urls = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{p}"
        for branch in ("HEAD", "main", "master")
        for p in candidates
    ]
    # 去重（HEAD/main/master 下候选可能重复无妨，保持顺序即可）
    last_err = ""
    with _client() as client:
        for url in urls:
            try:
                resp = client.get(url)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text
                last_err = f"HTTP {resp.status_code} @ {url}"
            except httpx.TimeoutException:
                last_err = f"请求超时(10s) @ {url}"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e} @ {url}"
    raise MarketplaceError(
        f"从 GitHub 拉取 SKILL.md 失败（{owner}/{repo}）：{last_err}。"
        "请确认仓库/路径存在，或改为直接粘贴 SKILL.md 全文内容。"
    )


# ── 平台适配器 ────────────────────────────────────────────

class SkillsShAdapter:
    """skill.sh — A 级：代理搜索 + GitHub raw 拉取安装"""

    SEARCH_API = "https://skills.sh/api/search"

    def search(self, query: str) -> list[dict]:
        query = (query or "").strip()
        if not query:
            raise MarketplaceError("搜索关键词不能为空")
        try:
            with _client() as client:
                resp = client.get(self.SEARCH_API, params={"q": query})
        except httpx.TimeoutException:
            raise MarketplaceError("skill.sh 搜索超时（10s），请稍后重试或检查网络/代理")
        except Exception as e:  # noqa: BLE001
            raise MarketplaceError(f"skill.sh 搜索请求失败：{type(e).__name__}: {e}")

        if resp.status_code != 200:
            raise MarketplaceError(
                f"skill.sh 搜索返回 HTTP {resp.status_code}（实际响应前 120 字符：{resp.text[:120]!r}）。"
                "可打开平台网页搜索后，将技能链接粘贴回本系统安装。"
            )
        try:
            data = resp.json()
        except Exception:
            raise MarketplaceError(
                f"skill.sh 搜索响应不是有效 JSON（前 120 字符：{resp.text[:120]!r}）。"
                "请改用网页搜索后粘贴链接安装。"
            )
        return self._normalize_results(data)

    @staticmethod
    def _normalize_results(data) -> list[dict]:
        """尽力兼容 skill.sh 返回结构：列表或 {results|skills|hits|data: [...]}"""
        items = data
        if isinstance(data, dict):
            for key in ("results", "skills", "hits", "items", "data"):
                v = data.get(key)
                if isinstance(v, list):
                    items = v
                    break
                if isinstance(v, dict):
                    inner = v.get("results") or v.get("hits") or v.get("items")
                    if isinstance(inner, list):
                        items = inner
                        break
        if not isinstance(items, list):
            return []
        results = []
        for it in items[:50]:
            if isinstance(it, str):
                results.append({"name": it, "description": "", "ref": it})
                continue
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("skill") or it.get("title") or it.get("slug") or ""
            # ref 优先级：显式 ref/path → id（skill.sh 实测：id=owner/repo/子目录，比 source 多一级路径）
            # → source/repo → install → name
            ref = it.get("ref") or it.get("path") or ""
            if not ref:
                sid = str(it.get("id") or "")
                src = str(it.get("source") or it.get("repo") or "")
                ref = sid if sid.count("/") >= 2 else (src or sid)
            ref = ref or it.get("install") or name
            desc = it.get("description") or it.get("desc") or ""
            if name:
                results.append({"name": str(name), "description": str(desc), "ref": str(ref)})
        return results

    def fetch_skill(self, ref: str) -> tuple[str, str]:
        """按 ref（owner/repo[/path]）拉取，返回 (source_url, content)"""
        owner, repo, path = _parse_ref(ref)
        content = _fetch_github_raw(owner, repo, path)
        source_url = f"https://github.com/{owner}/{repo}" + (f"/{path}" if path else "")
        return source_url, content


class _LinkPlatformAdapter:
    """C 级平台通用适配：接受技能页链接或 owner/repo，尽力解析出 GitHub 源拉取"""

    def __init__(self, platform_name: str):
        self.platform_name = platform_name

    def fetch_skill(self, ref: str) -> tuple[str, str]:
        try:
            owner, repo, path = _parse_ref(ref)
        except MarketplaceError:
            raise MarketplaceError(
                f"无法从该输入解析出技能的 GitHub 源。请打开 {self.platform_name} 网页，"
                "复制技能页链接（需含 github 仓库信息）或直接复制 SKILL.md 全文，回本系统粘贴安装。"
            )
        content = _fetch_github_raw(owner, repo, path)
        source_url = f"https://github.com/{owner}/{repo}" + (f"/{path}" if path else "")
        return source_url, content


class SkillsmpAdapter(_LinkPlatformAdapter):
    def __init__(self):
        super().__init__("skillsmp")


class SkillhubAdapter(_LinkPlatformAdapter):
    def __init__(self):
        super().__init__("skillhub.cn")


def get_adapter(platform_id: str):
    return {
        "skillsh": SkillsShAdapter(),
        "skillsmp": SkillsmpAdapter(),
        "skillhubcn": SkillhubAdapter(),
    }.get(platform_id)


# ── 安装 / 卸载 ───────────────────────────────────────────

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def _builtin_names() -> set:
    """内置技能名集合（仅内置目录下的技能，按路径排除 imported/ 与自定义目录）"""
    from services.agent.skill_loader import SkillLoader
    loader = SkillLoader()
    loader.scan()  # 只扫 SKILL_DIRS 内置目录（会递归进 imported，需按路径排除）
    imported_real = os.path.realpath(IMPORTED_ROOT)
    return {s.name for s in loader._skills.values()
            if not os.path.realpath(s.path).startswith(imported_real + os.sep)}


def install_skill(name: str, content: str, source: str = "", source_platform: str = "") -> dict:
    """安装技能：校验 → 落盘 skills/imported/<name>/SKILL.md → 记录元数据 → 默认禁用 → 重扫

    name 为空时以 frontmatter 解析结果为准。
    """
    from services.agent.skill_loader import parse_skill_text, get_loader
    from services.agent.skill_config import get_config

    content = content or ""
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise MarketplaceError(f"技能内容超过 200KB 限制（当前 {size / 1024:.1f}KB）")
    if not content.strip():
        raise MarketplaceError("技能内容为空")

    parsed = parse_skill_text(content)
    if not parsed or not parsed.get("name"):
        raise MarketplaceError("SKILL.md 缺少 YAML frontmatter 或无法解析出 name 字段，请检查内容格式")
    fm_name = parsed["name"]
    final_name = (name or "").strip() or fm_name
    if not _NAME_RE.match(final_name):
        raise MarketplaceError(f"技能名不合法（仅允许字母/数字/_/-，≤64 字符）：{final_name[:64]}")

    target_dir = os.path.join(IMPORTED_ROOT, final_name)
    target_file = os.path.join(target_dir, "SKILL.md")
    if os.path.exists(target_file):
        raise MarketplaceError(f"技能「{final_name}」已安装，请先卸载后再重装")

    os.makedirs(target_dir, exist_ok=True)
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(target_dir, ignore_errors=True)
        raise MarketplaceError(f"写入技能文件失败：{e}")

    config = get_config()
    config.add_installed({
        "name": final_name,
        "source_platform": source_platform or "paste",
        "source_url": source or "",
        "installed_at": datetime.now().isoformat(timespec="seconds"),
    })
    config.set_enabled(final_name, False)  # 默认禁用，待用户确认启用

    get_loader().rescan()  # 热刷新
    logger.info(f"[SkillStore] installed skill '{final_name}' from {source_platform or 'paste'}")
    return {"ok": True, "name": final_name, "enabled": False,
            "path": target_file, "description": parsed.get("description", "")}


def uninstall_skill(name: str) -> dict:
    """卸载技能：仅允许删除 skills/imported/ 下的技能，内置技能拒绝删除"""
    from services.agent.skill_loader import get_loader
    from services.agent.skill_config import get_config

    name = (name or "").strip()
    if not name:
        raise MarketplaceError("技能名不能为空")
    if name in _builtin_names():
        raise MarketplaceError(f"「{name}」是内置技能，禁止卸载")

    target_dir = os.path.realpath(os.path.join(IMPORTED_ROOT, name))
    imported_real = os.path.realpath(IMPORTED_ROOT)
    if not target_dir.startswith(imported_real + os.sep):
        raise MarketplaceError("非法技能名")
    if not os.path.isdir(target_dir):
        raise MarketplaceError(f"未找到已安装技能「{name}」（skills/imported/ 下无此目录）")

    shutil.rmtree(target_dir)

    config = get_config()
    config.remove_installed(name)
    if name in config.get_disabled_list():  # 清理禁用记录残留
        config.set_enabled(name, True)

    get_loader().rescan()  # 热刷新
    logger.info(f"[SkillStore] uninstalled skill '{name}'")
    return {"ok": True, "name": name}
