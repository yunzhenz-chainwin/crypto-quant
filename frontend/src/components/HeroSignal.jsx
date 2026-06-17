/**
 * HeroSignal.jsx — 大訊號卡 + 7 因子信心分數量表
 *
 * Props：
 *   signal  後端 /api/signals/{symbol} 回傳的物件
 *   symbol  幣種代號
 */
import { coinName } from '../constants/coins'

const SIGNAL_CONFIG = {
  BULL:    { cls: 'hero-bull',    label: '多頭', desc: '指標顯示上漲動能較強，可考慮觀察買入機會', icon: '▲' },
  BEAR:    { cls: 'hero-bear',    label: '空頭', desc: '指標顯示下跌壓力較大，建議謹慎或等待',     icon: '▼' },
  NEUTRAL: { cls: 'hero-neutral', label: '中立', desc: '多空訊號互相抵消，方向不明，建議觀望',     icon: '—' },
  UNKNOWN: { cls: 'hero-neutral', label: '—',    desc: '資料載入中',                              icon: '…' },
}

// 分數 0-100 映射到顏色
function scoreColor(score) {
  if (score >= 65) return '#22c55e'
  if (score >= 50) return '#84cc16'
  if (score >= 35) return '#f59e0b'
  return '#ef4444'
}

// 半圓弧量表 SVG
function ScoreGauge({ score }) {
  if (score == null) return null
  const r  = 50
  const cx = 70, cy = 70
  const startAngle = Math.PI          // 左端 = 180°
  const endAngle   = 0                // 右端 = 0°
  const angle      = Math.PI - (score / 100) * Math.PI  // 分數對應角度

  const arcPath = (a) => ({
    x: cx + r * Math.cos(a),
    y: cy - r * Math.sin(a),
  })

  // 背景軌道弧（從 180° 到 0°，用 SVG arc）
  const bgStart = arcPath(Math.PI)
  const bgEnd   = arcPath(0)

  // 分數弧（從 180° 到 angle）
  const fgEnd   = arcPath(angle)

  const color   = scoreColor(score)

  // 指針
  const needle  = arcPath(angle)

  return (
    <div className="score-gauge-wrap">
      <svg viewBox="0 0 140 80" className="score-gauge-svg">
        {/* 背景軌道 */}
        <path
          d={`M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 0 1 ${bgEnd.x} ${bgEnd.y}`}
          fill="none" stroke="#1e293b" strokeWidth="10" strokeLinecap="round"
        />
        {/* 分數弧 */}
        <path
          d={`M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${score >= 50 ? 0 : 0} 1 ${fgEnd.x} ${fgEnd.y}`}
          fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
        />
        {/* 刻度標記 0 / 35 / 65 / 100 */}
        {[0, 35, 65, 100].map(v => {
          const a = Math.PI - (v / 100) * Math.PI
          const p = arcPath(a)
          return <circle key={v} cx={p.x} cy={p.y} r={2} fill="#334155" />
        })}
        {/* 分數文字 */}
        <text x={cx} y={cy - 5} textAnchor="middle" fill={color}
              fontSize="22" fontWeight="700">{score}</text>
        <text x={cx} y={cy + 14} textAnchor="middle" fill="#64748b" fontSize="10">信心分數</text>
      </svg>
      {/* 刻度說明 */}
      <div className="score-gauge-axis">
        <span style={{ color: '#ef4444' }}>空頭 0</span>
        <span style={{ color: '#f59e0b' }}>中立 50</span>
        <span style={{ color: '#22c55e' }}>多頭 100</span>
      </div>
    </div>
  )
}

// 因子列表
function FactorList({ factors }) {
  if (!factors || Object.keys(factors).length === 0) return null
  const items = Object.entries(factors)

  return (
    <div className="factor-list">
      <div className="factor-list-title">各因子評分</div>
      {items.map(([key, f]) => {
        const pct   = ((f.score + 20) / 40) * 100  // -20~+20 → 0~100%
        const color = f.score > 0 ? '#22c55e' : f.score < 0 ? '#ef4444' : '#475569'
        return (
          <div key={key} className="factor-row">
            <span className="factor-label">{f.label}</span>
            <div className="factor-bar-track">
              <div
                className="factor-bar-fill"
                style={{ width: `${Math.max(2, Math.min(100, pct))}%`, background: color }}
              />
              {/* 中線（=50%） */}
              <div className="factor-bar-center" />
            </div>
            <span className="factor-score" style={{ color }}>
              {f.score > 0 ? '+' : ''}{f.score}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// RSI 進度條
function RsiBar({ rsi }) {
  if (rsi == null) return null
  const pct   = Math.max(0, Math.min(100, rsi))
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
  const cfg   = SIGNAL_CONFIG[signal?.signal ?? 'UNKNOWN']
  const price = signal?.close
    ? `$${signal.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : '—'

  return (
    <section className={`hero-signal ${cfg.cls}`}>
      {/* 左：幣名、價格、訊號 */}
      <div className="hero-left">
        <div className="hero-coin">{coinName(symbol)}</div>
        <div className="hero-price">{price}</div>
        <div className="hero-signal-row">
          <span className="hero-icon">{cfg.icon}</span>
          <span className="hero-label">{cfg.label}</span>
        </div>
        <div className="hero-desc">{cfg.desc}</div>
      </div>

      {/* 中：信心分數量表 */}
      <div className="hero-gauge-col">
        <ScoreGauge score={signal?.score} />
      </div>

      {/* 右：RSI + 因子列表 */}
      <div className="hero-right">
        <RsiBar rsi={signal?.rsi} />

        {signal?.factors && <FactorList factors={signal.factors} />}

        {signal?.reasons?.length > 0 && (
          <div className="hero-reasons">
            <div className="hero-reasons-title">主要依據</div>
            {signal.reasons.slice(0, 4).map((r, i) => (
              <span key={i} className="hero-reason-tag">{r}</span>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
