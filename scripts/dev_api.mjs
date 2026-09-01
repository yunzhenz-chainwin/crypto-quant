#!/usr/bin/env node
/**
 * dev_api.mjs — 開發模式後端啟動器（frontend 的 `npm run api` / `npm run start` 會呼叫這支）
 *
 * 原本 package.json 直接寫死 Windows cmd 語法：
 *     set CRYPTO_QUANT_MODE=development&& ... .venv\Scripts\python.exe -m uvicorn ...
 * macOS / Linux 上沒有 `set`、venv 的 python 也在 .venv/bin/python，整條指令會直接失敗。
 * 平台差異全部收斂到這支腳本，package.json 只留 `node ../scripts/dev_api.mjs`，
 * 兩邊行為維持一致（同樣的環境變數、同樣的 host/port、同樣的 --reload）。
 *
 * 僅供本機 loopback 開發：這裡會帶 ALLOW_INSECURE_ADMIN_DEFAULTS=1，讓沒設定
 * ADMIN_PASS 的乾淨環境也能起得來。正式／對外啟動請走 start_backend.sh（macOS）
 * 或 start_backend.cmd（Windows），那兩支不會帶這個 opt-in。
 *
 * 可用環境變數：
 *   CRYPTO_QUANT_DEV_HOST  預設 127.0.0.1（改成非 loopback 會被後端安全檢查擋下，這是刻意的）
 *   CRYPTO_QUANT_DEV_PORT  預設 8001（vite.config.js 的 proxy 指向這個 port）
 *   DEV_API_DRY_RUN=1      只印出要執行的指令就結束，用來排查「找不到 python」這類問題
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'
const venvPython = isWindows
  ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(repoRoot, '.venv', 'bin', 'python')

const host = process.env.CRYPTO_QUANT_DEV_HOST || '127.0.0.1'
const port = process.env.CRYPTO_QUANT_DEV_PORT || '8001'
const args = ['-m', 'uvicorn', 'backend.main:app', '--host', host, '--port', port, '--reload']

if (!existsSync(venvPython)) {
  console.error(`[dev_api] 找不到虛擬環境的 Python：${venvPython}`)
  console.error(
    isWindows
      ? '[dev_api] 請先建立 .venv：python -m venv .venv 再 .venv\Scripts\python.exe -m pip install -r requirements.txt -r backend\requirements.txt'
      : '[dev_api] 請先在 repo 根目錄執行 ./setup.sh 建立 .venv 與相依套件'
  )
  process.exit(1)
}

console.error(`[dev_api] ${venvPython} ${args.join(' ')}`)
if (process.env.DEV_API_DRY_RUN === '1') process.exit(0)

const child = spawn(venvPython, args, {
  cwd: repoRoot,
  stdio: 'inherit',
  env: {
    ...process.env,
    CRYPTO_QUANT_MODE: 'development',
    CRYPTO_QUANT_BIND_HOST: host,
    ALLOW_INSECURE_ADMIN_DEFAULTS: '1',
  },
})

// concurrently 會 kill 這個 node 進程；把訊號往下傳，避免 uvicorn 變孤兒進程占著 port。
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig))
child.on('exit', (code, signal) => process.exit(signal ? 1 : code ?? 0))
