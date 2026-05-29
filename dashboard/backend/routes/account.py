"""
/api/account 路由 - 账户信息
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/account", tags=["account"])

engine_runner = None


@router.get("")
async def get_account():
    """获取 MT4 账户信息"""
    if not engine_runner or not engine_runner.bridge:
        return None
    try:
        info = engine_runner.bridge.get_account_info()
        if not info:
            return None
        return {
            "login": info.login,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.free_margin,
            "currency": info.currency,
            "leverage": info.leverage,
        }
    except Exception as e:
        raise HTTPException(502, f"获取账户信息失败: {e}")
