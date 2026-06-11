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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

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

# 提前初始化 NewsFilter 单例，引擎启动前加载 DB 缓存
from services.news_filter import NewsFilter
NewsFilter()

# 配置日志
log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
))
# 在 uvicorn 二次 import 时不重复添加 handler
if not logging.getLogger().handlers:
    logging.getLogger().addHandler(log_handler)
    logging.getLogger().setLevel(logging.INFO)
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
from dashboard.backend.routes import signals as route_signals

# run_bridge 是纯函数，不需要 __name__ 守卫
route_account.run_bridge = run_bridge
route_positions.run_bridge = run_bridge
route_market.run_bridge = run_bridge
route_trades.run_bridge = run_bridge
route_data.run_bridge = run_bridge


# === 后台轮询任务 ===
class PollerState:
    """后台任务状态"""
    running = True


async def broadcast_prices():
    """每 0.3 秒推送一次价格（引擎高速采样缓存，使前端 K 线实时跳动）"""
    while PollerState.running:
        try:
            cached = engine_runner._cached_price
            if cached:
                await ws_manager.broadcast("prices", {
                    "bid": cached["bid"],
                    "ask": cached["ask"],
                    "spread": round(cached["ask"] - cached["bid"], 2),
                })
        except Exception:
            pass
        await asyncio.sleep(0.3)


async def broadcast_positions():
    """每 5 秒推送一次持仓（用最新价格刷新 current_price）"""
    while PollerState.running:
        try:
            positions = engine_runner._fresh_positions()
            if positions:
                await ws_manager.broadcast("positions", positions)
        except Exception:
            pass
        await asyncio.sleep(5)


async def broadcast_account():
    """每 10 秒推送一次账户信息（从引擎线程缓存读取）"""
    while PollerState.running:
        try:
            account = engine_runner._cached_account
            if account:
                await ws_manager.broadcast("account", account)
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
    """启动/关闭事件 — 自动启动引擎线程"""
    # 在后台线程启动引擎（不阻塞 asyncio 事件循环）
    await asyncio.to_thread(engine_runner.start)
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
app.include_router(route_signals.router)


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


# === 前端静态文件服务（必须在 API 路由之后注册，避免拦截 /api/*）===
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        # 不拦截 API 和 WebSocket 路径
        if path.startswith("api/") or path.startswith("ws"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

# === 路由依赖注入（必须放在 __name__ 守卫内） ===
# 由于 backend/ 在 sys.path，__import__('main') 会导入自身，
# 导致模块级代码递归执行产生两个 engine_runner 实例互相覆盖。
# 通过 __name__ 守卫确保只注入一次。
if __name__ == "__main__":
    app.state.engine_runner = engine_runner
    app.state.ws_manager = ws_manager
    route_engine.engine_runner = engine_runner
    route_account.engine_runner = engine_runner
    route_positions.engine_runner = engine_runner
    route_config.config_service = config_service
    route_market.engine_runner = engine_runner
    route_logs.log_handler = log_handler
    route_trades.engine_runner = engine_runner
    route_data.engine_runner = engine_runner
    try:
        from engine_standalone.main import STRATEGY_MAP
        route_engine.available_strategies = {k: True for k in STRATEGY_MAP}
    except Exception:
        route_engine.available_strategies = {}


# === 入口 ===
if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  XAUUSD Web Dashboard Backend")
    print("  API:  http://localhost:1783/api")
    print("  Web:  http://localhost:1783  (frontend)")
    print("  WS:   ws://localhost:1783/ws")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=1783, reload=False)
