@echo off
chcp 65001 >nul
echo ========================================
echo   XAUUSD Quantitative Trading System
echo ========================================
echo.

cd /d "%~dp0"

:menu
echo [1] Environment check
echo [2] Start live trading
echo [3] Run backtest
echo [4] Monitor dashboard
echo [5] View account info
echo [6] Generate sample data
echo [7] Export MT4 history data
echo [0] Exit
echo.
set /p choice=Select:

if "%choice%"=="1" python tools\check_setup.py
if "%choice%"=="2" python main.py
if "%choice%"=="3" python backtest\run_backtest.py
if "%choice%"=="4" python tools\monitor.py
if "%choice%"=="5" python tools\account_info.py
if "%choice%"=="6" python backtest\generate_sample_data.py
if "%choice%"=="7" python tools\export_history.py
if "%choice%"=="0" exit /b

echo.
pause
cls
goto menu
