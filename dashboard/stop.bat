@echo off
chcp 65001 >nul
title XAUUSD Dashboard - 停止

cd /d "%~dp0"

echo ========================================
echo   正在停止 XAUUSD Dashboard...
echo ========================================
echo.

REM 停止后端 FastAPI (port 8000)
echo [1/2] 停止后端 API...
for /f "tokens=5" %%a in ('netstat -ano ^| find ":1783 " ^| find "LISTENING"') do (
    echo   发现 PID=%%a (backend)，正在终止...
    taskkill /F /PID %%a >nul 2>&1 && echo   [OK] 后端已停止 || echo   [!] 后端停止失败
    goto :check_backend_done
)
:check_backend_done
echo.

REM 停止前端 Vite (port 5173)
echo [2/2] 停止前端开发服务器...
for /f "tokens=5" %%a in ('netstat -ano ^| find ":5173 " ^| find "LISTENING"') do (
    echo   发现 PID=%%a (frontend)，正在终止...
    taskkill /F /PID %%a >nul 2>&1 && echo   [OK] 前端已停止 || echo   [!] 前端停止失败
    goto :check_frontend_done
)
:check_frontend_done
echo.

echo ========================================
echo   清理完成。
echo.
echo   若仍有残留进程，可手动执行:
echo     taskkill /F /IM python.exe
echo     taskkill /F /IM node.exe
echo ========================================
pause
