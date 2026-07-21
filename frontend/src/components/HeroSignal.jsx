/**
 * HeroSignal.jsx — 大訊號卡 + 6 因子信心分數量表
 * （因子：RSI / MACD / 均線排列 / MA200 / 成交量 / 布林位置，見 src/scoring.py）
 *
 * Props：
 *   signal  後端 /api/signals/{symbol} 回傳的物件
 *   symbol  幣種代號
 */
import { coinName, coinCat, coinWhy, catInfo } from '../constants/coins'

const SIGNAL_CONFIG = {
  BULL:    { cls: 'hero-bull',    label: '技術偏多', desc: '六項技術因子目前偏多，僅代表市場狀態，不等同未來報酬預測', icon: '▲' },
  BEAR:    { cls: 'hero-bear',    label: '技術偏空', desc: '六項技術因子目前偏空，僅代表市場狀態，不等同未來報酬預測', icon: '▼' },
  NEUTRAL: { cls: 'hero-neutral', label: '技術中性', desc: '多空技術因子互相抵消，目前沒有明確方向', icon: '—' },
  UNKNOWN: { cls: 'hero-neutral', label: '—',    desc: '資料載入中',                              icon: '…' },
}

// 分數 0-100 映射到顏色
function scoreColor(score) {
  if (score >= 65) return '#22c55e'
  if (score >= 50) return '#84cc16'
  if (score >= 35) return '#f59e0b'
  return '#ef4444'
}

// 半圓弧量表 SVG（匯出供右側欄位重用）
export function ScoreGauge({ score }) {
  if (score == null) return null
  const r  = 50
  const cx = 70, cy = 70
  const angle      = Math.PI - (score / 100) * Math.PI  // 分數對應角度（左端 180° → 右端 0°）

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
        <text x={cx} y={cy + 14} textAnchor="middle" fill="#64748b" fontSize="10">技術狀態</text>
      </svg>
      {/* 刻度說明 */}
      <div className="score-gauge-axis">
        <span style={{ color: '#ef4444' }}>偏空 0</span>
        <span style={{ color: '#f59e0b' }}>中性 50</span>
        <span style={{ color: '#22c55e' }}>偏多 100</span>
      </div>
    </div>
  )
}

// 指標白話卡已抽成共用元件,移至「策略回測」區塊顯示:見 ./IndicatorCards.jsx

export default function HeroSignal({ signal, symbol, live, slim = false }) {
  const cfg   = SIGNAL_CONFIG[signal?.signal ?? 'UNKNOWN']
  const px    = live?.price ?? signal?.close          // 有即時價就用即時價
  const price = px ? `$${Number(px).toLocaleString(undefined, { maximumFractionDigits: px < 1 ? 4 : 2 })}` : '—'
  const chg   = live?.changePct


  return (
    <section className={`hero-signal ${cfg.cls}`}>
      {/* 左：幣名、分類（含歸類原因）、價格、訊號 */}
      <div className="hero-left">
        <div className="hero-coin">{coinName(symbol)}</div>
        <div className="hero-cat-row">
          <span className={`card-cat cat-${coinCat(symbol)}`}>
            {catInfo(coinCat(symbol)).label}
          </span>
          <span className="hero-cat-why">{coinWhy(symbol)}</span>
        </div>
        <div className="hero-price">
          {live && <span className="live-dot" title="即時報價（Binance）" />}
          {price}
          {chg != null && (
            <span className="hero-chg" style={{ color: chg >= 0 ? '#22c55e' : '#ef4444' }}>
              {chg >= 0 ? '▲' : '▼'}{Math.abs(chg).toFixed(2)}%
            </span>
          )}
        </div>
        <div className="hero-signal-row">
          <span className="hero-icon">{cfg.icon}</span>
          <span className="hero-label">{cfg.label}</span>
        </div>
        {!slim && <div className="hero-desc">{cfg.desc}</div>}
      </div>

      {/* 右：信心分數量表（slim 時隱藏——分數量表改放右側欄位，避免重複） */}
      {!slim && (
        <div className="hero-gauge-col"
             title="技術狀態分數＝6 個技術因子的加權合成（RSI、MACD、均線排列、MA200、成交量、布林位置），基準 50、範圍 0~100。≥65 判偏多、≤35 判偏空；它不是未來漲跌機率。">
          <ScoreGauge score={signal?.score} />
          <span className="hero-gauge-info">ⓘ 6 因子合成，計分規則見「買賣判斷依據」</span>
        </div>
      )}
    </section>
  )
}
