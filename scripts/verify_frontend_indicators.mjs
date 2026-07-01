/**
 * verify_frontend_indicators.mjs
 *
 * 用「實際上線的那份」frontend/src/lib/indicators.js 計算某幣的技術指標,
 * 把結果以 JSON 印到 stdout,供 verify_frontend_indicators.py 與 pandas_ta 逐點比對。
 *
 * 用法：node scripts/verify_frontend_indicators.mjs <SYMBOL>
 */
import { readFileSync } from 'fs'
import { fileURLToPath, pathToFileURL } from 'url'
import { dirname, join } from 'path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const lib = await import(pathToFileURL(join(ROOT, 'frontend/src/lib/indicators.js')).href)

const SYMBOL = process.argv[2]
if (!SYMBOL) { console.error('用法: node scripts/verify_frontend_indicators.mjs <SYMBOL>'); process.exit(2) }

const csv = readFileSync(join(ROOT, `data/clean/${SYMBOL}_1d.csv`), 'utf8')
const prices = csv.trim().split(/\r?\n/).slice(1).map(l => {
  const c = l.split(',')
  return { date: c[0].slice(0, 10), open: +c[1], high: +c[2], low: +c[3], close: +c[4], volume: +c[5] }
})

const toMap = (arr, keys) => {
  const m = {}
  for (const x of arr) { const o = {}; for (const k of keys) o[k] = x[k]; m[x.time] = o }
  return m
}

process.stdout.write(JSON.stringify({
  symbol: SYMBOL,
  n: prices.length,
  sma20:  toMap(lib.sma(prices, 20), ['value']),
  ema20:  toMap(lib.ema(prices, 20), ['value']),
  kdj:    toMap(lib.kdj(prices, 9), ['k', 'd', 'j']),
  dmi:    toMap(lib.dmi(prices, 14), ['pdi', 'mdi', 'adx']),
  bias6:  toMap(lib.bias(prices, 6), ['value']),
  bias24: toMap(lib.bias(prices, 24), ['value']),
}))
