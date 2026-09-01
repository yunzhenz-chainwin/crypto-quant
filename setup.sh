#!/usr/bin/env bash
#
# setup.sh — macOS / Linux 一鍵環境建置（Windows 請看 README §2 的 PowerShell 版）
#
#   ./setup.sh          建立 .venv、裝執行相依、npm ci、build 前端
#   ./setup.sh --dev    另外裝 requirements-dev.txt（測試／驗證／產 Word 文件用）
#
# 這支腳本可以重複執行：已存在的東西會跳過，不會覆寫 secrets.local.sh。
set -euo pipefail
cd "$(dirname "$0")"

WITH_DEV=0
[ "${1:-}" = "--dev" ] && WITH_DEV=1

say() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
die() { printf '\033[31m[錯誤] %s\033[0m\n' "$1" >&2; exit 1; }

# ── 1. 檢查前置工具 ─────────────────────────────────────────────────────────
say "檢查 python3 / node"
command -v python3 >/dev/null || die "找不到 python3。macOS 建議 brew install python@3.12"
command -v node    >/dev/null || die "找不到 node。macOS 建議 brew install node（需 20 以上）"
python3 - <<'PY' || die "Python 版本過舊，請安裝 3.10 以上"
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
echo "python3 $(python3 -c 'import platform;print(platform.python_version())') / node $(node --version)"

# ── 2. 虛擬環境與 Python 相依 ───────────────────────────────────────────────
if [ ! -x .venv/bin/python ]; then
  say "建立虛擬環境 .venv"
  python3 -m venv .venv
else
  say "沿用既有的 .venv"
fi
say "安裝 Python 相依（backend 執行 + src 研究腳本）"
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt -r backend/requirements.txt
if [ "$WITH_DEV" = "1" ]; then
  say "安裝開發／驗證相依（requirements-dev.txt）"
  ./.venv/bin/python -m pip install -r requirements-dev.txt
fi

# ── 3. 前端相依與建置 ───────────────────────────────────────────────────────
say "安裝前端相依並建置（frontend/dist 是正式模式下由 FastAPI 直接服務的靜態檔）"
if [ -f frontend/package-lock.json ]; then
  ( cd frontend && npm ci )
else
  ( cd frontend && npm install )
fi
( cd frontend && npm run build )

# ── 4. 執行期目錄與機密檔 ───────────────────────────────────────────────────
say "準備執行期目錄與 secrets.local.sh"
mkdir -p logs data/clean data/raw reports
if [ -f secrets.local.sh ]; then
  echo "secrets.local.sh 已存在，保留不動"
else
  # 舊機器搬過來的話，搬遷包裡已經有 secrets.local.sh；這裡只服務「全新環境」，
  # 產生一把夠強的簽章密鑰，密碼留空白讓使用者自己填，避免預設密碼流出去。
  secret="$(openssl rand -hex 32)"
  sed -e "s|^export ADMIN_SECRET=.*|export ADMIN_SECRET=${secret}|" secrets.example.sh > secrets.local.sh
  chmod 600 secrets.local.sh
  echo "已從範本產生 secrets.local.sh（ADMIN_SECRET 已隨機產生）"
  echo "請編輯它填入 ADMIN_PASS（對外模式需 12 字元以上）"
fi

say "完成"
cat <<'TIP'
接下來：
  開發模式（前後端一起，前端 http://localhost:5174 、API :8001）
      cd frontend && npm run start

  正式模式（FastAPI 直接服務 build 後的前端）
      ./start_backend.sh            # 預設 127.0.0.1:8000，看門狗會自動重啟
      ./start_backend.sh --once     # 不套看門狗、輸出直接印在畫面上，除錯用

  舊機器的資料（工作項目 / 新聞 / 後台設定）不會跟著 git 走，
  請把搬遷包解開到這個目錄：unzip -o ~/Downloads/crypto-quant-migration-*.zip -d .
TIP
