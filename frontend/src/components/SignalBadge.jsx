import { coinZh, coinTicker } from '../constants/coins'

const CONFIG = {
  BULL:    { label: '多頭 ▲', cls: 'signal-bull' },
  BEAR:    { label: '空頭 ▼', cls: 'signal-bear' },
  NEUTRAL: { label: '中立 —', cls: 'signal-neutral' },
  UNKNOWN: { label: '無資料', cls: 'signal-neutral' },
}

// signal: { symbol, signal, close, rsi, date, reasons[] }
export default function SignalBadge({ signal }) {
  if (!signal) return <div className="signal-card loading">載入中…</div>

  const { label, cls } = CONFIG[signal.signal] ?? CONFIG.UNKNOWN

  return (
    <div className={`signal-card ${cls}`}>
      <div className="signal-header">
        <div className="signal-symbol-wrap">
          <span className="signal-ticker">{coinTicker(signal.symbol)}</span>
          <span className="signal-zh">{coinZh(signal.symbol)}</span>
        </div>
        <span className="signal-label">{label}</span>
      </div>
      {signal.close && (
        <div className="signal-price">${signal.close.toLocaleString()}</div>
      )}
      {signal.rsi && (
        <div className="signal-rsi">RSI {signal.rsi.toFixed(1)}</div>
      )}
      <ul className="signal-reasons">
        {(signal.reasons ?? []).map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  )
}
