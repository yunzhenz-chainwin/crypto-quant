@echo off
REM Crypto Quant backend launcher with WATCHDOG loop.
REM If uvicorn exits/crashes, waits 30s and restarts it automatically.
REM Managed by Task Scheduler job "CryptoQuantBackend" (auto-start at boot).
REM Manual restart: schtasks /end /tn CryptoQuantBackend, kill leftover port-8000 python if any, then schtasks /run /tn CryptoQuantBackend
REM Log: logs\backend.log   Schedules (backend\scheduler.py): daily 09:00, hourly :06, news every 30 min.
cd /d "C:\Users\Administrator\crypto-quant"
REM Load admin credentials (gitignored). Absolute %~dp0 path required on this machine.
if exist "%~dp0secrets.local.cmd" call "%~dp0secrets.local.cmd"
if not exist logs mkdir logs
:loop
echo [%date% %time%] starting uvicorn backend.main:app :8000 >> "logs\backend.log"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 >> "logs\backend.log" 2>&1
echo [%date% %time%] backend exited (code %errorlevel%), watchdog restarting in 30s >> "logs\backend.log"
ping -n 31 127.0.0.1 > nul
goto loop
