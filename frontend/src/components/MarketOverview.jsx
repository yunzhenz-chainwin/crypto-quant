/**
 * MarketOverview.jsx — 市場總覽卡片網格（含技術分數條）
 *
 * 幣別種類區分：頂部種類頁籤（全部/主流幣/公鏈平台/DeFi/支付/迷因）可篩選，
 * 每張卡片右上角也標示所屬種類。
 */
import { useState } from 'react'
import { coinZh, coinTicker, coinCat, coinWhy, catInfo, CATEGORIES } from '../constants/coins'

const SIG = {
  BULL:    { label: '技術偏多', icon: '▲', cls: 'bull' },
  BEAR:    { label: '技術偏空', icon: '▼', cls: 'bear' },
  NEUTRAL: { label: '技術中立', icon: '—', cls: 'neutral' },
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
        <span className="card-score-lbl">① 技術分數</span>
        <span className="card-score-val" style={{ color }}>{score}</span>
      </div>
      <div
        className="card-score-track"
        role="meter"
        aria-label="技術分數"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
      >
        {/* 0-35 紅 / 35-65 橙黃 / 65-100 綠 三段背景 */}
        <div className="card-score-fill" style={{ width: `${score}%`, background: color }} />
        <div className="card-score-mark" style={{ left: '35%' }} />
        <div className="card-score-mark" style={{ left: '65%' }} />
      </div>
    </div>
  )
}

function fmtPct(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
}

// 回測策略摘要：只陳述歷史報酬差，不把「少跌」包裝成勝出。
// 數字是策略報酬減買入持有報酬，單位為百分點；細節在 title 懸停顯示。
function BacktestMini({ bt }) {
  if (!bt || bt.excess_return_pct == null) return null
  const higher = bt.excess_return_pct >= 0
  const color = higher && bt.total_return_pct >= 0 ? '#22c55e' : higher ? '#f59e0b' : '#ef4444'
  const ex = Math.round(bt.excess_return_pct)
  return (
    <div
      className="card-bt"
      title={`歷史回測比較：策略報酬 ${fmtPct(bt.total_return_pct)}、買入持有 ${fmtPct(bt.buy_hold_return_pct)}、勝率 ${bt.win_rate}%、共 ${bt.total_trades} 筆`}
    >
      <span className="card-bt-lbl">② 歷史回測</span>
      <span className="card-bt-val" style={{ color }}>
        較持有{higher ? '高' : '低'} {Math.abs(ex)} 個百分點
      </span>
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
      <div
        className="card-rsi-track"
        role="meter"
        aria-label={`RSI ${label}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={rsi}
      >
        <div className="card-rsi-fill" style={{ width: `${Math.min(rsi, 100)}%`, background: color }} />
        <div className="card-rsi-mark" style={{ left: '35%' }} />
        <div className="card-rsi-mark" style={{ left: '65%' }} />
      </div>
    </div>
  )
}

function CoinCard({ s, bt, live, onSelect }) {
  const sig   = SIG[s.signal] ?? SIG.NEUTRAL
  const px    = live?.price ?? s.close          // 有即時價就用即時價，否則排程價
  const price = px
    ? `$${Number(px).toLocaleString(undefined, { maximumFractionDigits: px < 1 ? 4 : px < 100 ? 2 : 2 })}`
    : '—'
  const chg   = live?.changePct
  const cardLabel = `${coinZh(s.symbol)}，${sig.label}，技術分數 ${s.score ?? '無資料'}，查看詳細分析`

  const handleKeyDown = (event) => {
    if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) {
      event.preventDefault()
      onSelect(s.symbol)
    }
  }

  return (
    <div
      className={`coin-card card-${sig.cls}`}
      onClick={() => onSelect(s.symbol)}
      role="button" tabIndex={0}
      onKeyDown={handleKeyDown}
      aria-label={cardLabel}
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
      <div className="card-price">
        {live && <span className="live-dot" title="即時報價（Binance）" />}
        {price}
        {chg != null && (
          <span className="card-chg" style={{ color: chg >= 0 ? '#22c55e' : '#ef4444' }}>
            {chg >= 0 ? '▲' : '▼'}{Math.abs(chg).toFixed(2)}%
          </span>
        )}
      </div>

      {/* 評估窗：① 技術分數 ＋ ② 歷史回測框成一組，與下方 RSI／理由分開。 */}
      <div className="card-eval">
        <div className="card-eval-hd">評估</div>
        <ScoreBar score={s.score} />
        <BacktestMini bt={bt} />
      </div>

      {/* RSI 條（輔助指標，非決策標準，故放評估窗外） */}
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

export default function MarketOverview({ signals, backtests = [], livePrices = {}, onSelect }) {
  const [cat, setCat] = useState('all')   // 幣別種類篩選：'all' 或 CATEGORIES 的 key

  // 幣種 → 回測摘要，供卡片顯示與第二排序鍵
  const btMap = new Map((backtests ?? []).map(b => [b.symbol, b]))
  const excessOf = (s) => btMap.get(s.symbol)?.excess_return_pct ?? -Infinity

  // 兩層評估標準排序：① 技術分數（主）高→低；② 分數相同時，回測報酬差（次）高→低。
  // 沒有回測資料的幣其超額視為 -∞，同分時自動排到後面。再依選中的種類篩選。
  const sorted = [...(signals ?? [])]
    .sort((a, b) => ((b.score ?? 50) - (a.score ?? 50)) || (excessOf(b) - excessOf(a)))
    .filter(s => cat === 'all' || coinCat(s.symbol) === cat)

  // 各種類的幣數（顯示在頁籤上）
  const countOf = (key) => (signals ?? []).filter(s => coinCat(s.symbol) === key).length

  if ((signals ?? []).length === 0) {
    // 載入骨架：先給版面形狀，不要整片空白
    return (
      <section className="overview-section" role="status" aria-live="polite" aria-label="市場技術狀態載入中">
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
      <div className="cat-tabs" role="group" aria-label="幣別種類篩選">
        <button
          className={`cat-tab ${cat === 'all' ? 'active' : ''}`}
          onClick={() => setCat('all')}
          aria-pressed={cat === 'all'}
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
              aria-pressed={cat === c.key}
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
          <CoinCard key={s.symbol} s={s} bt={btMap.get(s.symbol)} live={livePrices[s.symbol]} onSelect={onSelect} />
        ))}
      </div>
    </section>
  )
}
