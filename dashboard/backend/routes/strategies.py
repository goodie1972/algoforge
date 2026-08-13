"""
/api/strategies 路由 — 策略发现 + 添加/删除
"""
import os
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File
from dashboard.backend.strategy_registry import get_available_strategies
from dashboard.backend.strategy_logics import get_strategy_logics, get_strategy_logic

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), "../../../strategies")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "../../../docs/strategies")
BACKUP_DIR = os.path.join(STRATEGIES_DIR, "backup")


@router.get("/available")
async def list_available():
    """返回所有可实盘交易的策略清单（含 backup 规范名、默认参数）"""
    return {"strategies": get_available_strategies()}


@router.get("/logics")
async def list_logics():
    """返回所有策略的进出场逻辑描述（供前端交易终端/策略中心展示）"""
    return {"logics": get_strategy_logics()}


@router.post("/upload")
async def upload_strategy(file: UploadFile = File(...)):
    """上传策略 .py 文件到 strategies/ 目录"""
    filename = file.filename or ""
    if not filename.endswith(".py"):
        raise HTTPException(400, "只支持 .py 策略文件")
    # 防目录穿越
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".py"):
        raise HTTPException(400, "非法文件名")
    dest = os.path.join(STRATEGIES_DIR, safe_name)
    if os.path.exists(dest):
        raise HTTPException(409, f"策略文件 {safe_name} 已存在，请先删除或改名")
    try:
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, f"保存策略文件失败: {e}")
    return {"message": f"策略 {safe_name} 已上传，重启引擎后生效"}


@router.post("/batch-remove")
async def batch_remove_strategies(req: dict):
    """批量删除策略：检查在线状态，移至 backup。force=true 跳过在线检查"""
    names = req.get("names", [])
    force = req.get("force", False)
    if not names:
        raise HTTPException(400, "未指定策略")
    from dashboard.backend.routes.engine import engine_runner
    # 检查在线策略（force=true 时跳过）
    online = []
    if not force:
        try:
            import json
            rt = json.load(open(os.path.join(os.path.dirname(__file__), "../../../dashboard/runtime_config.json"), encoding='utf-8'))
            pool = rt.get("strategy_pool", {})
            for n in names:
                if pool.get(n, {}).get("enabled", False):
                    online.append(n)
        except Exception:
            pass
    if online:
        return {"online": online, "need_confirm": True}
    # 获取策略注册表，找到文件名
    from dashboard.backend.strategy_registry import get_available_strategies
    all_strats = {s["name"]: s for s in get_available_strategies()}
    # 执行删除
    moved = []
    for name in names:
        meta = all_strats.get(name)
        if not meta:
            continue
        fname = meta.get("file", "")
        # 先禁用策略（更新 runtime_config，防止引擎热加载后仍尝试运行）
        try:
            rt_path = os.path.join(os.path.dirname(__file__), "../../../dashboard/runtime_config.json")
            rt = json.load(open(rt_path, encoding='utf-8'))
            if rt.get("strategy_pool", {}).get(name, {}).get("enabled", False):
                rt["strategy_pool"][name]["enabled"] = False
                json.dump(rt, open(rt_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        except Exception:
            pass
        # 移动 .py 文件
        if fname:
            src = os.path.join(STRATEGIES_DIR, fname)
            dst = os.path.join(BACKUP_DIR, fname)
            if os.path.exists(src):
                os.makedirs(BACKUP_DIR, exist_ok=True)
                shutil.move(src, dst)
                moved.append(fname)
        # 移动说明文档 .md（从 strategies/docs/ 查找）
        doc_dir = os.path.join(STRATEGIES_DIR, "docs")
        if os.path.isdir(doc_dir):
            md_name = fname.replace(".py", ".md")
            src_md = os.path.join(doc_dir, md_name)
            doc_backup = os.path.join(BACKUP_DIR, "docs")
            if os.path.exists(src_md):
                os.makedirs(doc_backup, exist_ok=True)
                shutil.move(src_md, doc_backup)
                moved.append(md_name)
    logger.info(f"[StrategyDelete] 已删除策略 {names}: 文件 {moved} 移至 backup")
    return {"message": f"已删除 {len(names)} 个策略", "moved": moved}


@router.get("/{name}/logic")
async def get_strategy_logic_route(name: str):
    """返回单个策略的进出场逻辑（从 docs/strategies/ 读取）"""
    logic = get_strategy_logic(name)
    if logic is None:
        raise HTTPException(404, f"策略 {name} 的逻辑文档不存在")
    return {"logic": logic}
