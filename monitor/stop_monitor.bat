@echo off
cd /d "%~dp0"
if exist .patrol.pid (
    set /p PID=<.patrol.pid
    echo Stopping monitor (PID: %PID%)...
    taskkill //F //PID %PID% 2>nul
    del .patrol.pid 2>nul
    echo Monitor stopped.
) else (
    echo No PID file found, trying taskkill by window title...
    taskkill //F //FI "WINDOWTITLE eq XAUUSD Monitor*" 2>nul
    echo Done.
)
pause
