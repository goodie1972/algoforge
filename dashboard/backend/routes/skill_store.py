"""
技能商店 API 路由 — /api/ai/skill-store

平台分级：
- skill.sh（A 级 api）：系统内代理搜索 + GitHub raw 拉取安装
- skillsmp / skillhub.cn（C 级 link）：直链跳转浏览，粘贴链接/内容回系统安装
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.agent import skill_marketplace as mp

router = APIRouter(prefix="/api/ai/skill-store", tags=["skill-store"])
logger = logging.getLogger(__name__)


class InstallRequest(BaseModel):
    platform: str = ""      # 平台 id（skillsh/skillsmp/skillhubcn/paste）
    ref: str = ""           # 技能页链接或 owner/repo 路径
    name: str = ""          # 粘贴内容安装时的可选名称（以 frontmatter 为准）
    content: str = ""       # 直接粘贴的 SKILL.md 全文


@router.get("/platforms")
def list_platforms():
    """返回平台注册表"""
    return {"platforms": mp.SKILL_PLATFORMS}


@router.get("/search")
def search_skills(platform: str = "skillsh", q: str = ""):
    """搜索技能 — 仅 skill.sh 支持系统内搜索"""
    p = mp.PLATFORM_BY_ID.get(platform)
    if not p:
        raise HTTPException(400, f"未知平台：{platform}")
    if p["level"] != "api":
        raise HTTPException(
            400,
            f"「{p['name']}」为直连跳转平台，不支持系统内搜索。"
            f"请打开 {p['url']} 浏览，复制技能链接或内容后回本系统粘贴安装。",
        )
    try:
        results = mp.SkillsShAdapter().search(q)
    except mp.MarketplaceError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "platform": platform, "results": results}


@router.post("/install")
def install_skill(req: InstallRequest):
    """安装技能：{platform, ref} 链接拉取 或 {name, content} 粘贴内容"""
    try:
        # ① 粘贴内容安装（优先级最高，前端自动识别）
        if req.content and req.content.strip():
            platform = req.platform if req.platform in mp.PLATFORM_BY_ID else ""
            result = mp.install_skill(
                name=req.name,
                content=req.content,
                source="",
                source_platform=platform or "paste",
            )
            return result

        # ② 链接/引用拉取安装
        if not req.platform:
            raise mp.MarketplaceError("缺少 platform 参数")
        if not req.ref or not req.ref.strip():
            raise mp.MarketplaceError("缺少 ref 参数（技能页链接或 owner/repo 路径）")
        adapter = mp.get_adapter(req.platform)
        if not adapter or not hasattr(adapter, "fetch_skill"):
            raise mp.MarketplaceError(f"平台 {req.platform} 不支持链接拉取安装")
        source_url, content = adapter.fetch_skill(req.ref)
        return mp.install_skill(name=req.name, content=content,
                                source=source_url, source_platform=req.platform)
    except mp.MarketplaceError as e:
        raise HTTPException(400, str(e))


@router.delete("/{name}")
def uninstall_skill(name: str):
    """卸载技能（内置技能拒绝删除）"""
    try:
        return mp.uninstall_skill(name)
    except mp.MarketplaceError as e:
        raise HTTPException(400, str(e))
