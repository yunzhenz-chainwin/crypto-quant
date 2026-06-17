/**
 * MarketOverview.jsx — 市場總覽卡片網格（含信心分數條）
 */
import { coinZh, coinTicker } from '../constants/coins'

const SIG = {
  BULL:    { label: '多頭', icon: '▲', cls: 'bull' },
  BEAR:    { label: '空頭', icon: '▼', cls: 'bear' },
  NEUTRAL: { label: '中立', icon: '—', cls: 'neutral' },
}

function scoreColor(s) {
  if (s >= 65) return '#22c55e'
  if (s >= 50) return '#84cc16'
  if (s >= 35) return '#f59e0b'
  return '#ef4444'
}

function ScoreBar({ score }) {
  if (score == null) return null
  const color = scoreColor(score)
  return (
    <div className="card-score">
      <div className="card-score-row">
        <span className="card-score-lbl">信心分數</span>
        <span className="card-score-val" style={{ color }}>{score}</span>
      </div>
      <div className="card-score-track">
        {/* 0-35 紅 / 35-65 橙黃 / 65-100 綠 三段背景 */}
        <div className="card-score-fill" style={{ width: `${score}%`, background: color }} />
        <div className="card-score-mark" style={{ left: '35%' }} />
        <div className="card-score-mark" style={{ left: '65%' }} />
      </div>
    </div>
  )
}

function RsiMini({ rsi }) {
  if (rsi == null) return null
  const color = rsi > 65 ? '#ef4444' : rsi < 35 ? '#22c55e' : '#f59e0b'
  const label = rsi > 65 ? '超買' : rsi < 35 ? '超賣' : '正常'
  return (
    <div className="card-rsi">
      <div className="card-rsi-row">
        <span className="card-rsi-val">RSI {rsi.toFixed(0)}</span>
        <span className="card-rsi-lbl" style={{ color }}>{label}</span>
      </div>
      <div className="card-rsi-track">
        <div className="card-rsi-fill" style={{ width: `${Math.min(rsi, 100)}%`, background: color }} />
        <div className="card-rsi-mark" style={{ left: '35%' }} />
        <div className="card-rsi-mark" style={{ left: '65%' }} />
      </div>
    </div>
  )
}

function CoinCard({ s, onSelect }) {
  const sig   = SIG[s.signal] ?? SIG.NEUTRAL
  const price = s.close
    ? `$${Number(s.close).toLocaleString(undefined, { maximumFractionDigits: 4 })}`
    : '—'

  return (
    <div
      className={`coin-card card-${sig.cls}`}
      onClick={() => onSelect(s.symbol)}
      role="button" tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect(s.symbol)}
    >
      <div className="card-header">
        <span className={`card-sig card-sig-${sig.cls}`}>{sig.icon} {sig.label}</span>
        <span className="card-ticker">{coinTicker(s.symbol)}</span>
      </div>

      <div className="card-name">{coinZh(s.symbol)}</div>
      <div className="card-price">{price}</div>

      {/* 信心分數條 */}
      <ScoreBar score={s.score} />

      {/* RSI 條 */}
      <RsiMini rsi={s.rsi} />

      {s.reasons?.length > 0 && (
        <div className="card-reasons">
          {s.reasons.slice(0, 2).map((r, i) => (
            <span key={i} className="card-reason-tag">{r}</span>
          ))}
        </div>
      )}

      <div className="card-cta">查看詳細分析 →</div>
    </div>
  )
}

export default function MarketOverview({ signals, onSelect }) {
  // 先按分數排：高分 BULL → 低分 BEAR
  const sorted = [...(signals ?? [])].sort((a, b) => (b.score ?? 50) - (a.score ?? 50))

  if (sorted.length === 0) {
    return (
      <div className="overview-empty">
        <span className="overview-empty-icon">📡</span>
        <p>資料載入中，請稍候…</p>
      </div>
    )
  }

  return (
    <section className="overview-section">
      <div className="overview-grid">
        {sorted.map(s => (
          <CoinCard key={s.symbol} s={s} onSelect={onSelect} />
        ))}
      </div>
    </section>
  )
}
