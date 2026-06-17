/**
 * HeroSignal.jsx — 大訊號卡（頁面最上方的核心元件）
 *
 * 目的：讓使用者「一眼看懂」這個幣現在是什麼狀態，不需要看懂圖表
 *
 * 包含：
 *   - 幣種名稱 + 最新價格
 *   - BULL / BEAR / NEUTRAL 標籤 + 白話說明
 *   - RSI 進度條（超賣=綠色，正常=黃色，超買=紅色）
 *   - 訊號依據標籤（來自後端 signal.reasons）
 *
 * Props：
 *   signal  後端 /api/signals/{symbol} 回傳的物件（含 signal / close / rsi / reasons）
 *   symbol  幣種代號，例如 'BTCUSDT'
 */
import { coinName } from '../constants/coins'

// 每種訊號對應的 CSS class、標籤文字、白話說明、方向圖示
const SIGNAL_CONFIG = {
  BULL: {
    cls:   'hero-bull',
    label: '多頭',
    desc:  '指標顯示目前上漲動能較強，可考慮觀察買入機會',
    icon:  '▲',
  },
  BEAR: {
    cls:   'hero-bear',
    label: '空頭',
    desc:  '指標顯示目前下跌壓力較大，建議謹慎或等待',
    icon:  '▼',
  },
  NEUTRAL: {
    cls:   'hero-neutral',
    label: '中立',
    desc:  '目前方向不明確，多空訊號互相抵消，建議觀望',
    icon:  '—',
  },
  UNKNOWN: {
    cls:   'hero-neutral',
    label: '—',
    desc:  '資料載入中',
    icon:  '…',
  },
}

/**
 * RSI 進度條
 * - RSI < 35：超賣（綠色，歷史上常是低點）
 * - RSI > 65：超買（紅色，歷史上常是高點）
 * - 其他：正常區間（黃色）
 * 兩條標記線在 35% 和 65% 位置
 */
function RsiBar({ rsi }) {
  if (rsi == null) return null
  const pct   = Math.max(0, Math.min(100, rsi))  // 限制在 0~100 之間
  const color = rsi > 65 ? '#ef4444' : rsi < 35 ? '#22c55e' : '#f59e0b'
  const label = rsi > 65 ? '超買（偏高，注意回調）' : rsi < 35 ? '超賣（偏低，可能反彈）' : '正常區間'
  return (
    <div className="rsi-bar-wrap">
      <div className="rsi-bar-labels">
        <span>RSI {rsi.toFixed(0)}</span>
        <span style={{ color }}>{label}</span>
      </div>
      <div className="rsi-bar-track">
        <div className="rsi-bar-fill" style={{ width: `${pct}%`, background: color }} />
        <div className="rsi-bar-marker" style={{ left: '35%' }} />
        <div className="rsi-bar-marker" style={{ left: '65%' }} />
      </div>
      <div className="rsi-bar-axis">
        <span>0</span><span>超賣 35</span><span>超買 65</span><span>100</span>
      </div>
    </div>
  )
}

export default function HeroSignal({ signal, symbol }) {
  // signal 可能是 undefined（資料還在載入），安全存取用 ?. 和 ?? 預設值
  const cfg   = SIGNAL_CONFIG[signal?.signal ?? 'UNKNOWN']
  const price = signal?.close
    ? `$${signal.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : '—'

  return (
    <section className={`hero-signal ${cfg.cls}`}>
      <div className="hero-left">
        <div className="hero-coin">{coinName(symbol)}</div>
        <div className="hero-price">{price}</div>
        <div className="hero-signal-row">
          <span className="hero-icon">{cfg.icon}</span>
          <span className="hero-label">{cfg.label}</span>
        </div>
        <div className="hero-desc">{cfg.desc}</div>
      </div>

      <div className="hero-right">
        <RsiBar rsi={signal?.rsi} />

        {signal?.reasons?.length > 0 && (
          <div className="hero-reasons">
            <div className="hero-reasons-title">訊號依據</div>
            {signal.reasons.map((r, i) => (
              <span key={i} className="hero-reason-tag">{r}</span>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
