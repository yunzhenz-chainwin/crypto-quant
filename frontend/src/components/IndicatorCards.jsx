/**
 * IndicatorCards.jsx — 指標白話卡(共用元件)
 *
 * 把訊號的各因子(RSI / MACD / 均線 / MA200 / 量 / 布林)用
 * 「圖示 + 名稱 + ⓘ說明 + 方向箭頭 + 一句白話」呈現,RSI 另附溫度條。
 * 目前用於「策略回測」區塊頂部,說明策略依據的指標即時狀態。
 *
 * Props:
 *   factors  signal.factors(後端 /api/signals 回傳)
 *   rsi      signal.rsi(供 RSI 溫度條)
 */
const FACTOR_META = {
  RSI:    { icon: '🌡️', name: 'RSI 強弱',  tip: '看最近是不是漲太多(偏貴)或跌太多(便宜)' },
  MACD:   { icon: '📊', name: 'MACD 動能', tip: '上漲或下跌的「力道」變化;交叉是轉折訊號' },
  MA:     { icon: '📈', name: '均線趨勢',  tip: '價格相對短中期平均成本的位置(多頭/空頭排列)' },
  MA200:  { icon: '🧭', name: '長期趨勢',  tip: '站上或跌破 200 日均線,長線多空的分界' },
  Volume: { icon: '🔊', name: '成交量',    tip: '放量代表訊號較可信,縮量則較存疑' },
  BB:     { icon: '📏', name: '布林位置',  tip: '價格在常態波動帶的高低(靠上偏貴、靠下便宜)' },
}
const FACTOR_ORDER = ['RSI', 'MACD', 'MA', 'MA200', 'Volume', 'BB']

const factorArrow = (s) => (s > 0 ? '↗' : s < 0 ? '↘' : '—')
const factorColor = (s) => (s > 0 ? '#22c55e' : s < 0 ? '#ef4444' : '#64748b')

// RSI 溫度條(便宜 ←→ 偏貴)
function RsiMini({ rsi }) {
  if (rsi == null) return null
  const pct   = Math.max(0, Math.min(100, rsi))
  const color = rsi > 65 ? '#ef4444' : rsi < 35 ? '#22c55e' : '#f59e0b'
  return (
    <div className="ind-rsi">
      <div className="ind-rsi-track">
        <div className="ind-rsi-fill" style={{ width: `${pct}%`, background: color }} />
        <div className="ind-rsi-mark" style={{ left: '35%' }} />
        <div className="ind-rsi-mark" style={{ left: '65%' }} />
      </div>
      <div className="ind-rsi-axis"><span>便宜</span><span>正常</span><span>偏貴</span></div>
    </div>
  )
}

// 單一指標白話卡:圖示 + 名稱 + ⓘ + 方向箭頭 + 一句白話(RSI 另附溫度條)
function IndicatorCard({ fkey, f, rsi }) {
  const meta  = FACTOR_META[fkey] ?? { icon: '•', name: f.label, tip: '' }
  const color = factorColor(f.score)
  return (
    <div className="ind-card">
      <div className="ind-card-head">
        <span className="ind-card-name">{meta.icon} {meta.name}</span>
        {meta.tip && <span className="info-tip" title={meta.tip}>ⓘ</span>}
        <span className="ind-card-arrow" style={{ color }}>{factorArrow(f.score)}</span>
      </div>
      <div className="ind-card-note" style={{ color }}>{f.note}</div>
      {fkey === 'RSI' && <RsiMini rsi={rsi} />}
    </div>
  )
}

export default function IndicatorCards({ factors, rsi }) {
  if (!factors || Object.keys(factors).length === 0) return null
  const keys = FACTOR_ORDER.filter(k => factors[k])
  return (
    <div className="ind-cards">
      <div className="ind-cards-grid">
        {keys.map(k => <IndicatorCard key={k} fkey={k} f={factors[k]} rsi={rsi} />)}
      </div>
    </div>
  )
}
