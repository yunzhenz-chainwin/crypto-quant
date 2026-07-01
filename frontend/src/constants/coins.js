/**
 * coins.js — 幣種中英文對照表（全前端共用）
 *
 * 格式：{ symbol: { zh: 中文名, ticker: 英文縮寫 } }
 * symbol 對應 Binance 的交易對代號（例如 BTCUSDT）
 *
 * 使用方式：
 *   coinName('BTCUSDT')   → '比特幣 BTC'   （sidebar、圖表標題用）
 *   coinZh('BTCUSDT')     → '比特幣'        （純中文名）
 *   coinTicker('BTCUSDT') → 'BTC'           （英文縮寫）
 */
export const COIN_INFO = {
  BTCUSDT:  { zh: '比特幣',  ticker: 'BTC',  },
  ETHUSDT:  { zh: '以太坊',  ticker: 'ETH',  },
  SOLUSDT:  { zh: '索拉納',  ticker: 'SOL',  },
  BNBUSDT:  { zh: '幣安幣',  ticker: 'BNB',  },
  XRPUSDT:  { zh: '瑞波幣',  ticker: 'XRP',  },
  DOGEUSDT: { zh: '狗狗幣',  ticker: 'DOGE', },
  LINKUSDT: { zh: '鏈鏈',    ticker: 'LINK', },
  ADAUSDT:  { zh: '艾達幣',  ticker: 'ADA',  },
  AVAXUSDT: { zh: '雪崩幣',  ticker: 'AVAX', },
  DOTUSDT:  { zh: '波卡',    ticker: 'DOT',  },
  ATOMUSDT: { zh: '宇宙幣',  ticker: 'ATOM', },
  POLUSDT:  { zh: 'Polygon', ticker: 'POL',  },
  UNIUSDT:  { zh: 'Uniswap', ticker: 'UNI',  },
  LTCUSDT:  { zh: '萊特幣',  ticker: 'LTC',  },
  NEARUSDT: { zh: 'Near幣',  ticker: 'NEAR', },
}

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
