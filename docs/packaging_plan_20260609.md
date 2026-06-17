# XAUUSD 桌面端打包方案 — PyWebView + Nuitka

日期：2026-06-09
状态：设计方案（待实施）

## Context

当前系统启动方式：

```
start.bat
  ├── kill 8000/5173 端口
  ├── python backend/main.py        # FastAPI 后端
  └── npx vite --port 5173          # Vite 前端开发服务器
```

三个痛点：依赖 Python、依赖 Node.js、两个进程端口可能冲突。目标是**双击一个 exe，弹出桌面窗口直接使用**。

---

## 整体架构

```
xauusd.exe (Nuitka 编译)
  │
  ├── FastAPI 后端 (uvicorn)
  │   ├── REST API  (/api/*)
  │   ├── WebSocket  (/ws)
  │   └── 静态文件服务 (前端 dist/)     ← 取代 Vite
  │
  └── PyWebView 窗口
      └── WebView2 渲染前端界面
          └── 用户操作全部在窗口内完成
```

零外部依赖：不需要用户安装 Python、Node.js 或任何运行时。

---

## 实施步骤

### Step 1: FastAPI 服务前端静态文件

**文件**: `dashboard/backend/main.py`

改动：在路由注册后，挂载 `dashboard/frontend/dist/` 为静态文件目录，添加通配符路由返回 `index.html`（支持 Vue Router 的 History 模式）。

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 在所有 API 路由之后注册
app.mount("/assets", StaticFiles(
    directory=os.path.join(FRONTEND_DIST_DIR, "assets"),
    name="assets",
))

@app.get("/")
@app.get("/{path:path}")
async def serve_frontend(path: str = ""):
    index = os.path.join(FRONTEND_DIST_DIR, "index.html")
    return FileResponse(index)
```

作用：
- 开发/生产共用，不再需要 Vite 开发服务器
- Vite proxy 配置（/api → localhost:8000）不再需要，因为 API 和前端同源
- CORS middleware 可对应简化

验证方式：直接访问 `http://localhost:8000` 看到完整界面。

### Step 2: 添加 PyWebView 窗口

**新文件**: `dashboard/backend/window.py`

```python
"""
桌面窗口入口 — PyWebView 创建原生 WebView2 窗口
启动 FastAPI 后弹出窗口，关闭窗口时自动停止服务
"""
import threading
import webview
import uvicorn


def start_server():
    """在后台线程启动 FastAPI"""
    from dashboard.backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)


def main():
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 等待服务器就绪
    import time, socket
    while True:
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)

    # 创建原生窗口 — WebView2 (Windows 10/11 自带)
    webview.create_window(
        title="XAUUSD 交易系统",
        url="http://127.0.0.1:8000",
        width=1400,
        height=900,
        resizable=True,
        min_size=(1024, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
```

PyWebView 特性：
- Windows 10/11 自带 WebView2 运行时，无需额外安装（Windows 10 早期版本可能需要安装 WebView2 Runtime，微软提供离线安装包）
- 纯原生窗口，无菜单栏/地址栏，像真正的桌面应用
- 支持 JavaScript 和 Python 双向调用（预留后续扩展）

### Step 3: Nuitka 编译

Nuitka 将 Python 代码编译为 C 再编译为原生 exe，不是简单的打包。体积更小、启动更快、无反编译风险。

#### 前提：安装 C 编译器

Windows 需要 MSVC（Visual Studio Build Tools）或 MinGW：

```bash
# 方式 A: 安装 MSVC (推荐，体积更小)
# 从 https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
# 下载 Build Tools，安装时勾选 "C++ build tools"

# 方式 B: MinGW (备选)
pip install nuitka
```

#### 安装依赖

```bash
pip install nuitka pywebview
```

#### 编译命令

```bash
nuitka --standalone --onefile --windows-disable-console ^
  --enable-plugin=anti-bloat ^
  --include-package=uvicorn ^
  --include-package=fastapi ^
  --include-package=websockets ^
  --include-package=pydantic ^
  --include-package=webview ^
  --include-data-dir=dashboard/frontend/dist=dashboard/frontend/dist ^
  --include-data-dir=config=config ^
  --include-data-dir=core=core ^
  --include-data-dir=strategies=strategies ^
  --include-data-dir=data=data ^
  --include-data-dir=services=services ^
  --include-data-dir=dashboard/backend=dashboard/backend ^
  --nofollow-import-to=numpy ^
  --nofollow-import-to=pandas ^
  --nofollow-import-to=matplotlib ^
  --nofollow-import-to=scipy ^
  --output-dir=build ^
  --output-filename=xauusd.exe ^
  dashboard/backend/window.py
```

关键参数说明：

| 参数 | 作用 |
|------|------|
| `--standalone` | 生成独立可执行文件（含 Python 运行时） |
| `--onefile` | 最终压缩成单 exe |
| `--windows-disable-console` | 无控制台窗口（静默运行） |
| `--include-package` | 强制包含这些包（避免自动检测遗漏） |
| `--include-data-dir` | 打包目录到 exe 内 |
| `--nofollow-import-to` | 排除不需要的大包（numpy、pandas 可省 20-30MB） |

#### 构建时间

首次编译约 **10-20 分钟**（Nuitka 需要将所有 Python 编译为 C 再编译为机器码）。
后续增量编译快很多（只编译修改过的文件）。

#### 输出

```
build/xauusd.dist/    ← --standalone 模式输出目录（含所有依赖 DLL）
build/xauusd.exe      ← --onefile 最终单文件（推荐分发此文件）
```

预期体积：**~30-50MB**（比 PyInstaller 小约 40%）。

### Step 4 (可选): 优雅退出 + 托盘图标

PyWebView 支持系统托盘：

```python
def on_start():
    webview.set_icon("icon.ico")

def on_closing():
    # 确认退出对话框
    pass

webview.create_window(..., on_top=True)
webview.start(on_start)
```

---

## 依赖清单

### Python 包

| 包 | 用途 | 是否已在依赖中 |
|---|------|--------------|
| `fastapi` | REST API | 已用 |
| `uvicorn` | ASGI 服务器 | 已用 |
| `websockets` | WebSocket | 已用 |
| `pydantic` | 数据校验 | 已用 |
| `pywebview` | 桌面窗口 | **新增** |
| `requests` | 新闻爬取 | 已用 |

### 系统组件

| 组件 | 来源 |
|------|------|
| WebView2 Runtime | Windows 10/11 内置；Win10 早期版本需手动安装 |

### 外部程序（不可打包）

| 程序 | 说明 |
|------|------|
| MetaTrader 4 | 用户自行安装，加载 FreeMT4Bridge EA |
| FreeMT4Bridge EA | 部署到 MT4 Experts 目录 |

---

## 打包后体积与性能

| 指标 | PyInstaller | Nuitka |
|------|------------|--------|
| 输出体积 | 50-80MB | **30-50MB** |
| 启动方式 | 解压到临时目录再运行 | 直接运行 |
| 启动速度 | 慢（解压耗时） | **快**（原生 exe） |
| 反编译风险 | 高（pyz 可解包） | **低**（编译为机器码） |
| 构建时间 | 1-2 分钟 | 10-20 分钟（首次） |
| 兼容性 | 偶有隐式 import 遗漏 | 更严格但更稳定 |

---

## 与 Go+Wails 方案对比

| 对比项 | PyWebView + Nuitka (A) | Go + Wails (B) |
|--------|---------------------------|-----------------|
| 代码改动 | 加 1 个文件 + 改几行 main.py | 全量重写后端 |
| 开发周期 | 1-2 天 | 2-4 周 |
| 维护难度 | 零（Python 不变） | 高（两套代码） |
| 运行速度 | 编译为 C，比纯 Python 快 | 原生 Go 速度 |
| 系统托盘 | 支持 | 原生支持（更好） |
| 自动更新 | 需额外实现 | 需额外实现 |
| 体积 | **~40MB**（编译后比 PyInstaller 小） | ~10MB + WebView2 |
| 监控能力 | 完全不变 | API/DB 不变即可 |

---

## 建议前提条件

打包前建议先完成这些优化（否则打包后改起来更麻烦）：

1. **FastAPI 静态服务前端** — Step 1，先去掉 Node.js 依赖，独立验证
2. **配置文件路径处理** — 确保 `data/market_data.db`、`logs/` 等运行时文件使用相对路径或可配置路径，exe 解压后能正确找到
3. **异常处理增强** — 引擎崩溃时能否自动重启、日志是否完整
4. **MT4 连接失败提示** — 启动时检查端口 23232，未连接时在界面显示明确指引
5. **清理旧版本的配置残留** — settings.py 中不用的配置项

---

## 验证清单

- [ ] `http://localhost:8000` 直接访问正常（不依赖 Vite dev server）
- [ ] 所有 API 路由正常工作（health, account, positions, trades, signals 等）
- [ ] WebSocket 实时推送正常（prices, positions, logs）
- [ ] WebView2 窗口弹出无报错
- [ ] 窗口关闭后 FastAPI 进程正确终止
- [ ] Nuitka exe 在另一台没有 Python 的机器上运行正常
- [ ] 数据库文件在 exe 同级目录创建（非临时目录）
- [ ] 日志文件正常写入
