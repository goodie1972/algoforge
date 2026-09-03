@echo off
chcp 65001 >nul
REM ============================================================
REM XAUUSD 看门狗 常驻部署脚本
REM 以管理员身份运行本文件，注册 Windows 任务计划程序「开机自启」看门狗启动器。
REM 卸载：run_watchdog_task.bat 里的 schtasks /delete 命令，或任务计划程序手动删。
REM ============================================================
setlocal
set "PYTHON=C:\Python314\python.exe"
set "LAUNCHER=D:\backup\BaoBao\PythonProgram\xauusd\tools\watchdog_launcher.py"
set "TASK=XAUUSD_Watchdog"
set "WORKDIR=D:\backup\BaoBao\PythonProgram\xauusd"

echo 注册任务计划程序: %TASK%
echo   启动器: %LAUNCHER%
echo   Python: %PYTHON%
echo.

REM 创建任务：开机自启、无论用户是否登录都运行、最高权限
schtasks /create ^
  /tn "%TASK%" ^
  /tr "\"%PYTHON%\" \"%LAUNCHER%\"" ^
  /sc onstart ^
  /ru SYSTEM ^
  /rl highest ^
  /f

if errorlevel 1 (
  echo [错误] 注册失败，请确认以「管理员」身份运行本脚本。
  pause
  exit /b 1
)

REM 设置：任务失败每 1 分钟重启，最多无限次（兜底本启动器自身崩溃）
schtasks /change /tn "%TASK%" /ri 1 /du 9999 /f >nul 2>&1

echo.
echo [完成] 任务已注册。可立即启动：
schtasks /run /tn "%TASK%"
echo.
echo 查看状态：  schtasks /query /tn "%TASK%"
echo 停止任务：  schtasks /end /tn "%TASK%"
echo 卸载任务：  schtasks /delete /tn "%TASK%" /f
echo.
pause
