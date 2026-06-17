const BASE = '/api'

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`API ${path} 回應 ${res.status}`)
  return res.json()
}

// 取得所有可用幣種，例如 ["BTCUSDT","ETHUSDT",...]
export const fetchSymbols = () => get('/symbols')

// 取得資料最後更新時間，例如 { BTCUSDT: "2026-06-17", ... }
export const fetchStatus = () => get('/status')

// 取得指定幣種最近 N 天的 OHLC 資料，用來畫 K 線 / 折線圖
export const fetchPrices = (symbol, days = 180) =>
  get(`/prices/${symbol}?days=${days}`)

// 取得原始 OHLCV 資料，供蠟燭圖使用（不含指標欄位）
export const fetchOHLC = (symbol, days = 365) =>
  get(`/prices/${symbol}?days=${days}`)

// 取得指定幣種的技術指標（MA20、MA60、RSI、MACD、HIST）
export const fetchIndicators = (symbol, days = 180) =>
  get(`/indicators/${symbol}?days=${days}`)

// 取得所有幣種的相關性矩陣與年化波動度
export const fetchCorrelation = () => get('/correlation')

// 取得所有幣種的當前訊號（BULL / BEAR / NEUTRAL）
export const fetchAllSignals = () => get('/signals')

// 取得單一幣種的詳細訊號
export const fetchSignal = (symbol) => get(`/signals/${symbol}`)

// 取得回測結果（stop_loss 例如 -0.06，take_profit 例如 0.20）
export const fetchBacktest = (symbol, stopLoss = -0.06, takeProfit = 0.20) =>
  get(`/backtest/${symbol}?stop_loss=${stopLoss}&take_profit=${takeProfit}`)

// 取得恐懼貪婪指數（最近 N 天）
export const fetchFearGreed = (limit = 30) =>
  get(`/sentiment/fear_greed?limit=${limit}`)

// 取得最新新聞（RSS 即時抓取並存入資料庫）
export const fetchNews = (symbol = null) =>
  get(`/sentiment/news${symbol ? `?symbol=${symbol}` : ''}`)

// 查詢指定日期的歷史新聞
export const fetchNewsHistory = (date, category = null) => {
  const params = new URLSearchParams({ date })
  if (category) params.append('category', category)
  return get(`/sentiment/news/history?${params}`)
}

// 取得有新聞紀錄的日期清單
export const fetchNewsDates = () => get('/sentiment/news/dates')

// 回補歷史新聞（從 HackerNews 撈舊資料存入資料庫）
export const backfillNews = (fromDate, toDate) =>
  fetch(`/api/sentiment/news/backfill?from_date=${fromDate}&to_date=${toDate}`, { method: 'POST' })
    .then(r => r.json())
