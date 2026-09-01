#!/usr/bin/env bash
# secrets.example.sh — 後台帳密範本（macOS / Linux 版，對應 Windows 的 secrets.local.cmd）
#
# 用法：複製成 secrets.local.sh 後填值。secrets.local.sh 已被 .gitignore 排除，
# 絕對不要提交。start_backend.sh 與 setup.sh 會自動 source 它。
#
#   cp secrets.example.sh secrets.local.sh && $EDITOR secrets.local.sh
#
# 驗證規則（backend/services/security_hardening.py）：
#   - 對外模式（bind host 非 127.0.0.1，或 CRYPTO_QUANT_MODE=production/external）：
#       ADMIN_SECRET 至少 32 字元且不得是預設值，ADMIN_PASS 至少 12 字元，否則拒絕啟動。
#   - 本機 loopback 開發若沿用預設密碼，必須另外設 ALLOW_INSECURE_ADMIN_DEFAULTS=1。

# 後台帳號（不設就是 admin）
export ADMIN_USER=admin

# 後台密碼：對外模式至少 12 字元
export ADMIN_PASS=請填入密碼

# 登入 token 的簽章密鑰：至少 32 字元，用 openssl rand -hex 32 產生
export ADMIN_SECRET=請填入至少32字元的隨機密鑰

# GPT 金鑰（選填）。不填則 AI 分析只跑規則引擎；
# 也可以改從後台「AI 設定」頁填入（存在 data/app.db，會跟著搬遷包一起過去）。
# export OPENAI_API_KEY=sk-...
