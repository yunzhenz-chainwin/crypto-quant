@echo off
REM Crypto Quant backend launcher with WATCHDOG loop.
REM If uvicorn exits/crashes, waits 30s and restarts it automatically.
REM Managed by Task Scheduler job "CryptoQuantBackend" (auto-start at boot).
REM Manual restart: schtasks /end /tn CryptoQuantBackend, kill Crypto Quant listener on 10.201.7.12:8000 if any, then schtasks /run /tn CryptoQuantBackend
REM Log: logs\backend.log   Schedules (backend\scheduler.py): daily 09:00, hourly :06, news every 30 min.
cd /d "C:\Users\Administrator\crypto-quant"
REM This launcher binds all interfaces, so credential validation must use external mode.
set "CRYPTO_QUANT_MODE=external"
set "CRYPTO_QUANT_BIND_HOST=10.201.7.12"
REM Never inherit a temporary/developer proxy in the long-running service.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "NO_PROXY=localhost,127.0.0.1,10.201.7.12"
REM Load admin credentials (gitignored). Absolute %~dp0 path required on this machine.
if exist "%~dp0secrets.local.cmd" call "%~dp0secrets.local.cmd"
if not exist logs mkdir logs
:loop
echo [%date% %time%] starting uvicorn backend.main:app 10.201.7.12:8000 >> "logs\backend.log"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 10.201.7.12 --port 8000 >> "logs\backend.log" 2>&1
echo [%date% %time%] backend exited (code %errorlevel%), watchdog restarting in 30s >> "logs\backend.log"
ping -n 31 127.0.0.1 > nul
goto loop
