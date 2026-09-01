#!/usr/bin/env bash
#
# start_backend.sh — macOS / Linux 版後端啟動器（對應 Windows 的 start_backend.cmd）
#
#   ./start_backend.sh          看門狗模式：uvicorn 掛掉就等 30 秒自動重開，log 寫到 logs/backend.log
#   ./start_backend.sh --once   前景執行一次，輸出直接印在終端機，用來看啟動錯誤
#
# 環境變數：
#   CRYPTO_QUANT_BIND_HOST  預設 127.0.0.1。改成 0.0.0.0 或內網 IP 會被後端判定為
#                           「對外模式」，此時 ADMIN_SECRET 需 32 字元以上、ADMIN_PASS 需 12 字元以上。
#   CRYPTO_QUANT_PORT       預設 8000（正式前台與後台 /admin 都在這個 port）
#
# 排程（backend/scheduler.py）隨 FastAPI 一起啟動：每日 09:00、每小時 :06、新聞每 30 分。
# 開機自動啟動：見 scripts/com.cryptoquant.backend.plist（launchd 範本）。
set -uo pipefail            # 刻意不用 -e：看門狗必須能吃掉 uvicorn 的非零離開碼
cd "$(dirname "$0")"

ONCE=0
[ "${1:-}" = "--once" ] && ONCE=1

# 後台帳密（gitignore 的本機檔）。Windows 版讀 secrets.local.cmd，這裡讀 .sh 版。
# shellcheck source=/dev/null
[ -f ./secrets.local.sh ] && . ./secrets.local.sh

HOST="${CRYPTO_QUANT_BIND_HOST:-127.0.0.1}"
PORT="${CRYPTO_QUANT_PORT:-8000}"
export CRYPTO_QUANT_BIND_HOST="$HOST"

# 長駐服務不繼承臨時／開發用 proxy，否則抓 Binance 與 RSS 會走到已經關掉的代理。
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="localhost,127.0.0.1,${HOST}"

PY=".venv/bin/python"
[ -x "$PY" ] || { echo "找不到 $PY，請先在 repo 根目錄執行 ./setup.sh" >&2; exit 1; }
mkdir -p logs

if [ "$ONCE" = "1" ]; then
  exec "$PY" -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
fi

echo "看門狗啟動中，log：logs/backend.log（Ctrl-C 結束）"
while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting uvicorn backend.main:app ${HOST}:${PORT}" >> logs/backend.log
  "$PY" -m uvicorn backend.main:app --host "$HOST" --port "$PORT" >> logs/backend.log 2>&1
  code=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] backend exited (code ${code}), watchdog restarting in 30s" >> logs/backend.log
  sleep 30
done
