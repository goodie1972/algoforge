@echo off
chcp 65001 >nul
REM 立即启动 / 停止 / 卸载 看门狗任务
set "TASK=XAUUSD_Watchdog"
if "%1"=="stop" (
  schtasks /end /tn "%TASK%"
  echo 已停止 %TASK%
  goto :eof
)
if "%1"=="delete" (
  schtasks /delete /tn "%TASK%" /f
  echo 已卸载 %TASK%
  goto :eof
)
schtasks /run /tn "%TASK%"
echo 已启动 %TASK%
