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


@router.post("/{name}/remove")
async def remove_strategy(name: str):
    """删除策略：将 .py 和文档 .md 移动到 strategies/backup/ 目录"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    moved = []
    # 匹配策略 .py 文件（策略名 + 任意日期后缀）
    for fname in os.listdir(STRATEGIES_DIR):
        if fname.startswith(name + "_") and fname.endswith(".py"):
            src = os.path.join(STRATEGIES_DIR, fname)
            dst = os.path.join(BACKUP_DIR, fname)
            try:
                shutil.move(src, dst)
                moved.append(fname)
            except Exception as e:
                raise HTTPException(500, f"移动 {fname} 失败: {e}")
    # 匹配策略文档 .md
    if os.path.isdir(DOCS_DIR):
        for fname in os.listdir(DOCS_DIR):
            if fname.startswith(name) and fname.endswith(".md"):
                src = os.path.join(DOCS_DIR, fname)
                dst = os.path.join(BACKUP_DIR, fname)
                try:
                    shutil.move(src, dst)
                    moved.append(fname)
                except Exception as e:
                    raise HTTPException(500, f"移动 {fname} 失败: {e}")
    if not moved:
        raise HTTPException(404, f"未找到策略 {name} 的文件")
    return {"message": f"策略 {name} 已删除（移至 backup）", "moved": moved}


@router.get("/{name}/logic")
async def get_strategy_logic_route(name: str):
    """返回单个策略的进出场逻辑（从 docs/strategies/ 读取）"""
    logic = get_strategy_logic(name)
    if logic is None:
        raise HTTPException(404, f"策略 {name} 的逻辑文档不存在")
    return {"logic": logic}
