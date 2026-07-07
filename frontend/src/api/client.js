import { getToken } from './admin'

const BASE = '/api'

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`API ${path} 回應 ${res.status}`)
  return res.json()
}

// 取得所有可用幣種，例如 ["BTCUSDT","ETHUSDT",...]
export const fetchSymbols = () => get('/symbols')

// 取得資料最後更新時間 + 指標交叉驗證摘要
export const fetchStatus = () => get('/status')

// 取得指標交叉驗證的完整結果(各幣通過與否),供前台彈窗顯示
export const fetchVerify = () => get('/verify')

// 取得指定幣種最近 N 天的 OHLC 資料，用來畫 K 線 / 折線圖
export const fetchPrices = (symbol, days = 180) =>
  get(`/prices/${symbol}?days=${days}`)

// 取得原始 OHLCV 資料，供蠟燭圖使用（支援 days 或 start/end 日期；interval 1d/1h）
export const fetchOHLC = (symbol, { days = 365, start = null, end = null, interval = '1d' } = {}) => {
  const p = new URLSearchParams()
  if (start && end) { p.set('start', start); p.set('end', end) }
  else               { p.set('days', days) }
  if (interval !== '1d') p.set('interval', interval)
  return get(`/prices/${symbol}?${p}`)
}

// 取得指定幣種的技術指標（支援 days 或 start/end 日期；interval 1d/1h）
export const fetchIndicators = (symbol, { days = 180, start = null, end = null, interval = '1d' } = {}) => {
  const p = new URLSearchParams()
  if (start && end) { p.set('start', start); p.set('end', end) }
  else               { p.set('days', days) }
  if (interval !== '1d') p.set('interval', interval)
  return get(`/indicators/${symbol}?${p}`)
}

// 各週期有資料的幣種清單，例如 { "1d": [...], "1h": ["BTCUSDT","ETHUSDT"] }
export const fetchIntervals = () => get('/intervals')

// 取得所有幣種的相關性矩陣與年化波動度
export const fetchCorrelation = () => get('/correlation')

// 取得所有幣種的當前訊號（BULL / BEAR / NEUTRAL）
export const fetchAllSignals = () => get('/signals')

// 取得單一幣種的詳細訊號
export const fetchSignal = (symbol) => get(`/signals/${symbol}`)

// 取得回測結果（stop_loss 例如 -0.06，take_profit 例如 0.20）
export const fetchBacktest = (
  symbol,
  stopLoss = -0.06,
  takeProfit = 0.20,
  feeRate = 0.001,
  slippageRate = 0.0005,
) =>
  get(`/backtest/${symbol}?stop_loss=${stopLoss}&take_profit=${takeProfit}&fee_rate=${feeRate}&slippage_rate=${slippageRate}`)

// 所有幣種『已入庫』的回測績效摘要（依總報酬排序），供市場總覽當第二評估標準
export const fetchBacktestSummary = () => get('/backtest/db/summary')

// 取得恐懼貪婪指數（最近 N 天）
export const fetchFearGreed = (limit = 30) =>
  get(`/sentiment/fear_greed?limit=${limit}`)

// 取得信心分數歷史（讀 DB daily_signal，支援 days 或 start/end）
export const fetchSignalHistory = (symbol, { days = 360, start = null, end = null } = {}) => {
  const p = new URLSearchParams()
  if (start && end) { p.set('start', start); p.set('end', end) }
  else               { p.set('days', days) }
  return get(`/signals/${symbol}/history?${p}`)
}

// 取得恐懼貪婪指數歷史（讀 DB fear_greed，全市場）
export const fetchFearGreedHistory = (days = 365) =>
  get(`/sentiment/fear_greed/history?days=${days}`)

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

// 每日新聞情緒分數（-100 極空 ~ +100 極多）；symbol 給幣種看單幣，不給看全市場
export const fetchNewsSentiment = (symbol = 'MARKET', days = 14) =>
  get(`/sentiment/summary?symbol=${symbol}&days=${days}`)

// 回補歷史新聞（從 HackerNews 撈舊資料存入資料庫）
// 此端點為後台維護型寫入，需帶後台 token；未登入或來源失敗時回清楚訊息（#117 / #118）
export const backfillNews = async (fromDate, toDate) => {
  const res = await fetch(
    `/api/sentiment/news/backfill?from_date=${fromDate}&to_date=${toDate}`,
    { method: 'POST', headers: { Authorization: `Bearer ${getToken() || ''}` } },
  )
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const msg = res.status === 401
      ? '此為後台維護功能，請先登入後台再匯入'
      : (data.detail || data.error || `伺服器錯誤（${res.status}）`)
    return { ok: false, error: msg }
  }
  return data
}

// ── AI 分析機器人 ───────────────────────────────────────────────────────────
// 完整分析：gpt=false 只跑本地規則引擎（即時）；gpt=true 加上 GPT 深度解讀
export const fetchAIAnalysis = (symbol, { gpt = true, force = false } = {}) =>
  get(`/ai/analysis/${symbol}?gpt=${gpt ? 1 : 0}${force ? '&force=1' : ''}`)

// 針對幣種提問（GPT 沒設定金鑰時後端會降級為規則引擎摘要）
// 免選幣：後端會從問題文字自動偵測幣種（「以太幣如何？」→ ETH）；
// contextSymbol = 聊天室目前的幣（問題沒提到幣時沿用）。回應含實際回答的 symbol。
// history：最近幾輪對話 [{q, a}]，讓 GPT 能接住「那如果跌破呢？」這類追問
export const askAI = (contextSymbol, question, history = []) =>
  fetch('/api/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context_symbol: contextSymbol, question, history: history.slice(-3) }),
  }).then(async r => {
    if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `API 回應 ${r.status}`)
    return r.json()
  })

// AI 功能狀態（GPT 是否已設定金鑰）
export const fetchAIConfig = () => get('/ai/config')
