/**
 * CoinSidebar.jsx — 左側幣種選單
 *
 * 顯示 15 個幣種的清單，每列包含：
 *   ● 彩色小圓點（綠=多頭、紅=空頭、黃=中立）
 *   ● 英文縮寫 + 中文名
 *   ● 最新價格 + 訊號文字
 *
 * Props：
 *   symbols  所有幣種代號陣列，例如 ['BTCUSDT', 'ETHUSDT', ...]
 *   signals  所有幣種的訊號資料陣列（含 signal / close 欄位）
 *   active   目前選中的幣種代號
 *   onSelect 點擊幣種時的回呼，傳入被點擊的 symbol
 */
import { coinZh, coinTicker } from '../constants/coins'

// 訊號 → 顏色和文字對照（UNKNOWN 用於訊號還在載入時）
const SIGNAL_STYLE = {
  BULL:    { dot: '#22c55e', text: '多頭' },
  BEAR:    { dot: '#ef4444', text: '空頭' },
  NEUTRAL: { dot: '#f59e0b', text: '中立' },
  UNKNOWN: { dot: '#475569', text: '—'   },
}

export default function CoinSidebar({ symbols, signals, active, onSelect }) {
  // 把 signals 陣列轉成 { symbol → signal物件 } 的 map，方便快速查找
  const sigMap = Object.fromEntries((signals ?? []).map(s => [s.symbol, s]))

  return (
    <aside className="coin-sidebar">
      <div className="sidebar-title">幣種</div>
      {symbols.map(sym => {
        const sig  = sigMap[sym]
        const style = SIGNAL_STYLE[sig?.signal ?? 'UNKNOWN']
        const price = sig?.close
          ? `$${sig.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
          : '—'

        return (
          <button
            key={sym}
            className={`sidebar-item ${active === sym ? 'active' : ''}`}
            onClick={() => onSelect(sym)}
          >
            {/* 訊號燈 */}
            <span className="sidebar-dot" style={{ background: style.dot }} />

            {/* 幣種名稱 */}
            <span className="sidebar-names">
              <span className="sidebar-ticker">{coinTicker(sym)}</span>
              <span className="sidebar-zh">{coinZh(sym)}</span>
            </span>

            {/* 價格 + 訊號 */}
            <span className="sidebar-right">
              <span className="sidebar-price">{price}</span>
              <span className="sidebar-sig" style={{ color: style.dot }}>{style.text}</span>
            </span>
          </button>
        )
      })}
    </aside>
  )
}
