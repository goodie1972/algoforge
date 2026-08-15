"""
FastAPI 主入口 - XAUUSD Web Dashboard 后端
"""
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

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
from dashboard.backend.broadcast_hub import BroadcastHub

config_service = RuntimeConfig()
ws_manager = WebSocketManager()
log_handler = LogCaptureHandler()
broadcast_hub = BroadcastHub()

logger = logging.getLogger("dashboard")

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
from dashboard.backend.routes import reports as route_reports
from dashboard.backend.routes import version as route_version
from dashboard.backend.routes import strategies as route_strategies
from dashboard.backend.routes import supervisor as route_supervisor
from dashboard.backend.routes import paper_trading as route_paper_trading
from dashboard.backend.routes.llm_provider import router as llm_provider_router

# run_bridge 是纯函数，不需要 __name__ 守卫
route_account.run_bridge = run_bridge
route_positions.run_bridge = run_bridge
route_market.run_bridge = run_bridge
route_trades.run_bridge = run_bridge
route_data.run_bridge = run_bridge


# === 后台轮询任务 ===
class PollerState:
    """后台任务状态（类变量，所有实例共享）"""
    running: bool = True


async def broadcast_prices():
    """每 0.3 秒推送一次价格 — 通过 BroadcastHub 背压控制"""
    while PollerState.running:
        try:
            cached = engine_runner._cached_price
            if cached:
                data = {
                    "bid": cached["bid"],
                    "ask": cached["ask"],
                    "spread": round(cached["ask"] - cached["bid"], 2),
                }
                await broadcast_hub.publish("prices", data)
                # 同时推送给未升级的 WebSocket 客户端（兼容）
                await ws_manager.broadcast("prices", data)
        except Exception:
            pass
        await asyncio.sleep(0.3)


async def broadcast_positions():
    """每 5 秒推送一次持仓 — 通过 BroadcastHub 背压控制"""
    while PollerState.running:
        try:
            positions = engine_runner._fresh_positions()
            if positions:
                await broadcast_hub.publish("positions", positions)
                await ws_manager.broadcast("positions", positions)
        except Exception:
            pass
        await asyncio.sleep(5)


async def broadcast_account():
    """每 10 秒推送一次账户信息 — 通过 BroadcastHub 背压控制"""
    while PollerState.running:
        try:
            account = engine_runner._cached_account
            if account:
                await broadcast_hub.publish("account", account)
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


async def report_daily_loop():
    """每 10 分钟生成一条日报记录"""
    from dashboard.backend.routes.reports import _gather_daily_report
    # 启动后先等 30 秒再生成第一条，确保引擎完全就绪
    await asyncio.sleep(30)
    while PollerState.running:
        try:
            _gather_daily_report()
            logger.info("[Report] daily reportgenerated")
        except Exception as e:
            logger.warning(f"[Report] daily reportgeneratedfailed: {e}")
        await asyncio.sleep(600)


async def report_weekly_loop():
    """每 6 小时生成一次快照报告，保留历史记录"""
    from dashboard.backend.routes.reports import _gather_weekly_report
    while PollerState.running:
        _gather_weekly_report()
        logger.info("[Report] snapshotgenerated")
        # 每 6 小时
        for _ in range(21600):
            if not PollerState.running:
                return
            await asyncio.sleep(1)


# === FastAPI 生命周期 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭事件 — 自动启动引擎线程 + 后台预热策略缓存
    
    Shutdown 时完整释放：引擎、桥接、WebSocket、后台任务、日志句柄。
    """
    # 后台任务：预热策略缓存（不阻塞服务器启动）
    async def _warm_cache():
        t0 = datetime.now()
        try:
            from strategies.scanner import scan_strategy_metadata
            await asyncio.to_thread(scan_strategy_metadata)
            logger.info(f"策略缓存预热完成: {(datetime.now()-t0).total_seconds():.2f}s")
        except Exception as e:
            logger.warning(f"策略缓存预热失败: {e}")
    asyncio.create_task(_warm_cache())
    # 在后台线程启动引擎（不阻塞 asyncio 事件循环，也不阻塞 lifespan 完成）
    asyncio.create_task(asyncio.to_thread(engine_runner.start))
    # 后台延迟检查远程更新（默认 15s 后，避免启动同步 fetch 网络）
    try:
        from core.version import start_background_update_check
        start_background_update_check()
    except Exception:
        pass
    PollerState.running = True
    tasks = [
        asyncio.create_task(broadcast_prices()),
        asyncio.create_task(broadcast_positions()),
        asyncio.create_task(broadcast_account()),
        asyncio.create_task(broadcast_logs()),
        asyncio.create_task(broadcast_engine_status()),
        asyncio.create_task(report_daily_loop()),
        asyncio.create_task(report_weekly_loop()),
    ]
    yield
    # === Shutdown: 完整释放资源 ===
    logger.info("[Shutdown] 开始清理资源...")
    PollerState.running = False
    # 1. 取消所有后台任务
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("[Shutdown] 后台任务已取消")
    # 2. 停止引擎（含策略线程、桥接心跳）
    try:
        engine_runner.stop()
        logger.info("[Shutdown] 引擎已停止")
    except Exception as e:
        logger.warning(f"[Shutdown] 引擎停止异常: {e}")
    # 3. 断开所有 WebSocket 连接
    try:
        await ws_manager.disconnect_all()
        logger.info("[Shutdown] WebSocket 连接已断开")
    except Exception:
        pass
    # 4. 关闭桥接连接
    try:
        if hasattr(engine_runner, '_engine') and engine_runner._engine:
            bridge = getattr(engine_runner._engine, 'bridge', None)
            if bridge and hasattr(bridge, 'disconnect'):
                bridge.disconnect()
                logger.info("[Shutdown] 桥接已断开")
    except Exception:
        pass
    # 5. 关闭日志文件句柄
    try:
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'close'):
                handler.close()
        logger.info("[Shutdown] 日志句柄已关闭")
    except Exception:
        pass
    # 6. 强制 GC
    import gc
    gc.collect()
    logger.info("[Shutdown] 资源清理完成")



# === FastAPI 应用 ===
app = FastAPI(
    title="XAUUSD Trading Dashboard",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(route_reports.router)
app.include_router(route_version.router)
app.include_router(route_strategies.router)
app.include_router(route_supervisor.router)
app.include_router(route_paper_trading.router)
app.include_router(llm_provider_router)


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

# === 路由依赖注入 ===
# 当通过 uvicorn main:app 启动时，__name__ 不是 "__main__"，
# 所以注入代码必须放在 __name__ 守卫之外。
# 即使在 python main.py 模式下递归导入，重复注入也仅覆盖指针，不影响功能。
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
route_reports.engine_runner = engine_runner
route_supervisor.engine_runner = engine_runner
route_paper_trading.engine_runner = engine_runner
# supervisor 路由需要引擎的监督者实例（延迟绑定，引擎启动后才有）
def _wire_supervisor():
    sv = getattr(engine_runner, 'supervisor', None)
    if sv:
        from dashboard.backend.routes import supervisor as sv_route
        sv_route.supervisor = sv
import threading
threading.Timer(5.0, _wire_supervisor).start()
try:
    from strategies.scanner import scan_strategies
    route_engine.available_strategies = {k: True for k in scan_strategies()}
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
