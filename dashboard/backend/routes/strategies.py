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
    """批量删除策略：检查在线状态，移至 backup"""
    names = req.get("names", [])
    if not names:
        raise HTTPException(400, "未指定策略")
    from dashboard.backend.routes.engine import engine_runner
    # 检查在线策略
    online = []
    if engine_runner:
        status = engine_runner.get_status()
        enabled_strats = set()
        if status:
            pool = status.get("strategy_pool", {})
            for name, cfg in pool.items():
                if cfg.get("enabled"):
                    enabled_strats.add(name)
        for n in names:
            if n in enabled_strats:
                online.append(n)
    if online:
        return {"online": online, "need_confirm": True}
    # 执行删除
    moved = []
    for name in names:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        for fname in os.listdir(STRATEGIES_DIR):
            if fname.startswith(name + "_") and fname.endswith(".py"):
                shutil.move(os.path.join(STRATEGIES_DIR, fname), os.path.join(BACKUP_DIR, fname))
                moved.append(fname)
        # 移动说明文档
        for dname in os.listdir(DOCS_DIR):
            if dname.startswith(name) and dname.endswith(".md"):
                os.makedirs(os.path.join(BACKUP_DIR, "docs"), exist_ok=True)
                shutil.move(os.path.join(DOCS_DIR, dname), os.path.join(BACKUP_DIR, "docs", dname))
                moved.append(dname)
    return {"message": f"已删除 {len(names)} 个策略", "moved": moved}


@router.get("/{name}/logic")
async def get_strategy_logic_route(name: str):
    """返回单个策略的进出场逻辑（从 docs/strategies/ 读取）"""
    logic = get_strategy_logic(name)
    if logic is None:
        raise HTTPException(404, f"策略 {name} 的逻辑文档不存在")
    return {"logic": logic}
