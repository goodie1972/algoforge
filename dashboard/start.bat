@echo off
chcp 65001 >nul
title XAUUSD Dashboard

cd /d "%~dp0"
set PYTHONPATH=%cd%\..;%PYTHONPATH%

echo ========================================
echo   XAUUSD Trading Dashboard
echo ========================================
echo.

REM 清理残留进程
echo [清理] 检查并清理残留进程...
for /f "tokens=5" %%a in ('netstat -ano ^| find ":8000 " ^| find "LISTENING"') do (
    echo   发现后端进程 PID=%%a，正在终止...
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":5173 " ^| find "LISTENING"') do (
    echo   发现前端进程 PID=%%a，正在终止...
    taskkill /F /PID %%a >nul 2>&1
)
echo   [OK] 清理完成
echo.

echo [1/3] 启动后端 API 服务...
start "XAUUSD-Backend" /B python backend\main.py > backend.log 2>&1

echo   Waiting for backend...
:wait_backend
timeout /t 3 /nobreak >nul
curl -s http://localhost:8000/api/engine/status >nul 2>&1
if errorlevel 1 goto wait_backend

echo   [OK] API:      http://localhost:8000/api
echo        WebSocket: ws://localhost:8000/ws
echo.

echo [2/3] 启动前端开发服务器...
start "XAUUSD-Frontend" /B cmd /c "cd /d %~dp0frontend && npm run dev" > frontend.log 2>&1

echo   Waiting for frontend...
:wait_frontend
timeout /t 2 /nobreak >nul
curl -s http://localhost:5173 >nul 2>&1
if errorlevel 1 goto wait_frontend

echo   [OK] Frontend: http://localhost:5173
echo.

echo ========================================
echo   全部就绪！
echo.
echo   打开浏览器访问:
echo   ^>^> http://localhost:5173
echo.
echo ========================================

start http://localhost:5173
