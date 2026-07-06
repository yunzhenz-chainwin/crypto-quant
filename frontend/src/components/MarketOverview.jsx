/**
 * MarketOverview.jsx — 市場總覽卡片網格（含信心分數條）
 *
 * 幣別種類區分：頂部種類頁籤（全部/主流幣/公鏈平台/DeFi/支付/迷因）可篩選，
 * 每張卡片右上角也標示所屬種類。
 */
import { useState } from 'react'
import { coinZh, coinTicker, coinCat, coinWhy, catInfo, CATEGORIES } from '../constants/coins'

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
        <span className="card-header-right">
          <span
            className={`card-cat cat-${coinCat(s.symbol)}`}
            title={`為什麼是${catInfo(coinCat(s.symbol)).label}：${coinWhy(s.symbol)}`}
          >
            {catInfo(coinCat(s.symbol)).label}
          </span>
          <span className="card-ticker">{coinTicker(s.symbol)}</span>
        </span>
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
  const [cat, setCat] = useState('all')   // 幣別種類篩選：'all' 或 CATEGORIES 的 key

  // 先按分數排：高分 BULL → 低分 BEAR；再依選中的種類篩選
  const sorted = [...(signals ?? [])]
    .sort((a, b) => (b.score ?? 50) - (a.score ?? 50))
    .filter(s => cat === 'all' || coinCat(s.symbol) === cat)

  // 各種類的幣數（顯示在頁籤上）
  const countOf = (key) => (signals ?? []).filter(s => coinCat(s.symbol) === key).length

  if ((signals ?? []).length === 0) {
    // 載入骨架：先給版面形狀，不要整片空白
    return (
      <section className="overview-section">
        <div className="overview-grid">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="coin-card skeleton-card">
              <div className="skeleton sk-line" style={{ width: '55%' }} />
              <div className="skeleton sk-line lg" style={{ width: '70%' }} />
              <div className="skeleton sk-bar" />
              <div className="skeleton sk-bar" />
            </div>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="overview-section">
      {/* 幣別種類頁籤 */}
      <div className="cat-tabs">
        <button
          className={`cat-tab ${cat === 'all' ? 'active' : ''}`}
          onClick={() => setCat('all')}
        >
          全部 <span className="cat-tab-count">{(signals ?? []).length}</span>
        </button>
        {CATEGORIES.map(c => (
          countOf(c.key) > 0 && (
            <button
              key={c.key}
              className={`cat-tab ${cat === c.key ? 'active' : ''}`}
              onClick={() => setCat(c.key)}
              title={c.hint}
            >
              {c.label} <span className="cat-tab-count">{countOf(c.key)}</span>
            </button>
          )
        ))}
      </div>
      {/* 選中種類的一句話說明 */}
      {cat !== 'all' && (
        <div className="cat-hint">{catInfo(cat).label}：{catInfo(cat).hint}</div>
      )}
      <div className="overview-grid">
        {sorted.map(s => (
          <CoinCard key={s.symbol} s={s} onSelect={onSelect} />
        ))}
      </div>
    </section>
  )
}
