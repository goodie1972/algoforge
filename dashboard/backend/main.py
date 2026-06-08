"""
FastAPI 主入口 - XAUUSD Web Dashboard 后端
"""
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# 专用单线程执行器 — 所有 MT4 桥接调用串行化，避免共享线程池被锁竞争耗尽
_bridge_executor = ThreadPoolExecutor(max_workers=4)

async def run_bridge(func, *args):
    """在专用线程中执行桥接调用，不占用 asyncio 默认线程池"""
    return await asyncio.get_running_loop().run_in_executor(_bridge_executor, func, *args)

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

# === 服务初始化 ===
from dashboard.backend.config_service import RuntimeConfig
from dashboard.backend.engine_runner import EngineRunner
from dashboard.backend.web_manager import WebSocketManager
from dashboard.backend.log_service import LogCaptureHandler

config_service = RuntimeConfig()
ws_manager = WebSocketManager()
log_handler = LogCaptureHandler()

# 配置日志
log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
))
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.INFO)

# 确保引擎线程日志可读（同时输出到 stderr）
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
logging.getLogger().addHandler(_console)

engine_runner = EngineRunner(config_service=config_service)

# === 注入依赖到路由模块 ===
from dashboard.backend.routes import engine as route_engine
from dashboard.backend.routes import account as route_account
from dashboard.backend.routes import positions as route_positions
from dashboard.backend.routes import config as route_config
from dashboard.backend.routes import market as route_market
from dashboard.backend.routes import logs as route_logs
from dashboard.backend.routes import news as route_news
from dashboard.backend.routes import backtest as route_backtest
from dashboard.backend.routes import trades as route_trades
from dashboard.backend.routes import data as route_data

route_engine.engine_runner = engine_runner
# 注入可用策略列表（来自 main.py 的 STRATEGY_MAP）
try:
    _main_module = __import__('main')
    route_engine.available_strategies = {k: True for k in _main_module.STRATEGY_MAP}
except Exception:
    route_engine.available_strategies = {}
route_account.engine_runner = engine_runner
route_account.run_bridge = run_bridge
route_positions.engine_runner = engine_runner
route_positions.run_bridge = run_bridge
route_config.config_service = config_service
route_market.engine_runner = engine_runner
route_market.run_bridge = run_bridge
route_logs.log_handler = log_handler
route_trades.engine_runner = engine_runner
route_trades.run_bridge = run_bridge
route_data.engine_runner = engine_runner
route_data.run_bridge = run_bridge


# === 后台轮询任务 ===
class PollerState:
    """后台任务状态"""
    running = True


async def broadcast_prices():
    """每 2 秒推送一次价格"""
    while PollerState.running:
        try:
            if engine_runner.is_running and engine_runner.bridge:
                bid, ask = await run_bridge(engine_runner.bridge.get_tick_price, "XAUUSD")
                if bid > 0:
                    engine_runner._cached_price = {"bid": bid, "ask": ask}
                    await ws_manager.broadcast("prices", {
                        "bid": bid,
                        "ask": ask,
                        "spread": round(ask - bid, 2),
                    })
        except Exception:
            pass
        await asyncio.sleep(2)


async def broadcast_positions():
    """每 5 秒推送一次持仓"""
    while PollerState.running:
        try:
            if engine_runner.is_running and engine_runner.bridge:
                positions = await run_bridge(engine_runner.bridge.get_positions, "XAUUSD")
                pos_list = [
                    {
                        "ticket": p.ticket,
                        "order_type": p.order_type,
                        "volume": p.volume,
                        "open_price": p.open_price,
                        "current_price": p.current_price,
                        "profit": round(p.profit, 2),
                        "stop_loss": p.stop_loss,
                        "take_profit": p.take_profit,
                        "magic": p.magic,
                        "comment": getattr(p, "comment", ""),
                    }
                    for p in positions
                ]
                engine_runner._cached_positions = pos_list
                await ws_manager.broadcast("positions", pos_list)
        except Exception:
            pass
        await asyncio.sleep(5)


async def broadcast_account():
    """每 10 秒推送一次账户信息"""
    while PollerState.running:
        try:
            if engine_runner.is_running and engine_runner.bridge:
                info = await run_bridge(engine_runner.bridge.get_account_info)
                if info:
                    account_data = {
                        "login": info.login,
                        "balance": info.balance,
                        "equity": info.equity,
                        "margin": info.margin,
                        "free_margin": info.free_margin,
                        "currency": info.currency,
                        "leverage": info.leverage,
                    }
                    engine_runner._cached_account = account_data
                    await ws_manager.broadcast("account", account_data)
        except Exception:
            pass
        await asyncio.sleep(10)


async def broadcast_logs():
    """每 1 秒推送新日志"""
    while PollerState.running:
        new_records = log_handler.pop_new()
        if new_records:
            for record in new_records:
                await ws_manager.broadcast("logs", record)
        await asyncio.sleep(1)


async def broadcast_engine_status():
    """每 15 秒推送一次引擎状态"""
    while PollerState.running:
        status = engine_runner.get_status()
        await ws_manager.broadcast("status", status)
        await asyncio.sleep(15)


# === FastAPI 生命周期 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭事件"""
    poller_state.running = True
    tasks = [
        asyncio.create_task(broadcast_prices()),
        asyncio.create_task(broadcast_positions()),
        asyncio.create_task(broadcast_account()),
        asyncio.create_task(broadcast_logs()),
        asyncio.create_task(broadcast_engine_status()),
    ]
    yield
    poller_state.running = False
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    engine_runner.stop()


poller_state = PollerState()

# === FastAPI 应用 ===
app = FastAPI(
    title="XAUUSD Trading Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 注册路由 ===
app.include_router(route_engine.router)
app.include_router(route_account.router)
app.include_router(route_positions.router)
app.include_router(route_config.router)
app.include_router(route_market.router)
app.include_router(route_logs.router)
app.include_router(route_news.router)
app.include_router(route_backtest.router)
app.include_router(route_trades.router)
app.include_router(route_data.router)


# === WebSocket 端点 ===
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            # 客户端可以发送订阅消息（预留）
            # {"subscribe": "prices"} 等
            pass
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
    except Exception:
        await ws_manager.disconnect(ws)


# === 入口 ===
if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  XAUUSD Web Dashboard Backend")
    print("  API: http://localhost:8000/api")
    print("  WS:  ws://localhost:8000/ws")
    print("=" * 50)
    uvicorn.run("dashboard.backend.main:app", host="127.0.0.1", port=8000, reload=False)
