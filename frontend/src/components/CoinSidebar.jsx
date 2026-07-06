/**
 * CoinSidebar.jsx — 左側幣種選單（依幣別種類分組）
 *
 * 依 constants/coins 的 CATEGORIES 分組顯示（主流幣/公鏈平台/DeFi/支付/迷因），
 * 每列包含：
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
import { coinZh, coinTicker, coinCat, coinWhy, CATEGORIES } from '../constants/coins'

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

  // 依種類分組（保持 CATEGORIES 的順序；組內維持 symbols 原順序）
  const groups = CATEGORIES
    .map(cat => ({ cat, syms: symbols.filter(sym => coinCat(sym) === cat.key) }))
    .filter(g => g.syms.length > 0)

  return (
    <aside className="coin-sidebar">
      <div className="sidebar-title">幣種</div>
      {groups.map(({ cat, syms }) => (
        <div key={cat.key} className="sidebar-group">
          <div className="sidebar-group-title" title={cat.hint}>
            {cat.label}
            <span className="sidebar-group-count">{syms.length}</span>
          </div>
          {syms.map(sym => {
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
                title={`${coinZh(sym)}｜${cat.label}：${coinWhy(sym)}`}
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
        </div>
      ))}
    </aside>
  )
}
