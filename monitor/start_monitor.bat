@echo off
title XAUUSD Monitor Daemon
cd /d "%~dp0"
echo Starting XAUUSD Monitor Daemon...
echo Log: patrol.log
echo.
python patrol_daemon.py
pause
