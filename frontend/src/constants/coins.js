/**
 * coins.js — 幣種中英文對照表 + 幣別種類（全前端共用）
 *
 * 格式：{ symbol: { zh: 中文名, ticker: 英文縮寫, cat: 種類 key } }
 * symbol 對應 Binance 的交易對代號（例如 BTCUSDT）
 *
 * 使用方式：
 *   coinName('BTCUSDT')   → '比特幣 BTC'   （sidebar、圖表標題用）
 *   coinZh('BTCUSDT')     → '比特幣'        （純中文名）
 *   coinTicker('BTCUSDT') → 'BTC'           （英文縮寫）
 *   coinCat('BTCUSDT')    → 'major'         （種類 key，對照 CATEGORIES）
 */
export const COIN_INFO = {
  BTCUSDT:  { zh: '比特幣',  ticker: 'BTC',  cat: 'major', why: '市值第一、機構參與最深（美股現貨 ETF），全幣市的定錨資產——其他幣幾乎都跟著它漲跌' },
  ETHUSDT:  { zh: '以太坊',  ticker: 'ETH',  cat: 'major', why: '市值第二、最大智能合約平台（DeFi/NFT/穩定幣多跑在其上），2024 年起也有現貨 ETF' },
  SOLUSDT:  { zh: '索拉納',  ticker: 'SOL',  cat: 'l1',    why: '主打高速低費的智能合約公鏈，以太坊最強挑戰者之一，鏈上交易與新專案活躍' },
  BNBUSDT:  { zh: '幣安幣',  ticker: 'BNB',  cat: 'l1',    why: '全球最大交易所幣安的生態代幣，兼作 BNB Chain 公鏈燃料——價值與幣安平台深度綁定' },
  XRPUSDT:  { zh: '瑞波幣',  ticker: 'XRP',  cat: 'pay',   why: '主打銀行跨境匯款的橋接貨幣（Ripple 公司），目標把跨境轉帳從數天縮到數秒' },
  DOGEUSDT: { zh: '狗狗幣',  ticker: 'DOGE', cat: 'meme',  why: '迷因幣始祖：價值主要來自社群共識與名人效應（馬斯克喊單），基本面支撐薄弱、暴漲暴跌常態' },
  LINKUSDT: { zh: '鏈鏈',    ticker: 'LINK', cat: 'defi',  why: '最大「預言機」網路——把現實世界數據餵給區塊鏈，是 DeFi 報價的基礎設施' },
  ADAUSDT:  { zh: '艾達幣',  ticker: 'ADA',  cat: 'l1',    why: '學術嚴謹路線的智能合約公鏈（升級先發同行評審論文），質押社群龐大' },
  AVAXUSDT: { zh: '雪崩幣',  ticker: 'AVAX', cat: 'l1',    why: '高效能公鏈，特色是可客製的「子網」架構，對遊戲商與機構有吸引力' },
  DOTUSDT:  { zh: '波卡',    ticker: 'DOT',  cat: 'l1',    why: '「跨鏈互操作」代表作：多條平行鏈共享安全互相溝通，創辦人是以太坊共同創辦人 Gavin Wood' },
  ATOMUSDT: { zh: '宇宙幣',  ticker: 'ATOM', cat: 'l1',    why: 'Cosmos 跨鏈生態的中心幣：IBC 協定讓數百條應用鏈互轉資產（幣安鏈也用其技術）' },
  POLUSDT:  { zh: 'Polygon', ticker: 'POL',  cat: 'l1',    why: '以太坊擴容方案（前 MATIC）：讓以太坊交易更便宜快速，企業合作案最多的擴容方案之一' },
  UNIUSDT:  { zh: 'Uniswap', ticker: 'UNI',  cat: 'defi',  why: '最大去中心化交易所 Uniswap 的治理代幣——「用程式碼取代做市商」的 DeFi 龍頭' },
  LTCUSDT:  { zh: '萊特幣',  ticker: 'LTC',  cat: 'pay',   why: '最老牌的比特幣分叉幣（2011）：「比特金、萊特銀」，出塊快 4 倍、主打小額支付' },
  NEARUSDT: { zh: 'Near幣',  ticker: 'NEAR', cat: 'l1',    why: '主打易用性與分片擴容的公鏈，創辦人是 Google Transformer 論文（現代 AI 地基）共同作者' },
}

/**
 * 幣別種類定義（順序即顯示順序）。
 * 新增幣種時在 COIN_INFO 給 cat；查無 cat 的幣自動歸入 'l1'（見 coinCat）。
 */
export const CATEGORIES = [
  { key: 'major', label: '主流幣',    hint: '市值最大、機構參與最深，波動相對溫和' },
  { key: 'l1',    label: '公鏈平台',  hint: '智能合約公鏈與擴容方案，靠生態應用支撐價值' },
  { key: 'defi',  label: 'DeFi 基礎', hint: '去中心化金融與基礎設施（預言機、交易所）' },
  { key: 'pay',   label: '支付轉帳',  hint: '主打支付與跨境轉帳的老牌幣種' },
  { key: 'meme',  label: '迷因幣',    hint: '社群與話題驅動，波動最大、風險最高' },
]

// 用法：coinName('BTCUSDT') → '比特幣 BTC'
export function coinName(symbol) {
  const info = COIN_INFO[symbol]
  if (!info) return symbol.replace('USDT', '')
  return `${info.zh} ${info.ticker}`
}

// 只要中文名：coinZh('BTCUSDT') → '比特幣'
export function coinZh(symbol) {
  return COIN_INFO[symbol]?.zh ?? symbol.replace('USDT', '')
}

// 只要 ticker：coinTicker('BTCUSDT') → 'BTC'
export function coinTicker(symbol) {
  return COIN_INFO[symbol]?.ticker ?? symbol.replace('USDT', '')
}

// 種類 key：coinCat('BTCUSDT') → 'major'；未定義的新幣預設 'l1'
export function coinCat(symbol) {
  return COIN_INFO[symbol]?.cat ?? 'l1'
}

// 歸類原因（為什麼這顆幣屬於這個種類）：coinWhy('BTCUSDT') → '市值第一…'
export function coinWhy(symbol) {
  return COIN_INFO[symbol]?.why ?? ''
}

// 種類 key → 定義物件（label/hint）
export function catInfo(key) {
  return CATEGORIES.find(c => c.key === key) ?? CATEGORIES[1]
}
