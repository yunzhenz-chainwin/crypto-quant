/**
 * MacroPanel.jsx — 宏觀環境（規則式，市場整體背景）
 *
 * 讀 /api/macro：DXY 美元指數 / VIX 恐慌 / 美債殖利率 / 標普 / 黃金 / BTC 主導率 / 總市值
 * → 每個因子對加密「順風/逆風/中性」（左側色條標示，詳細說明 hover 顯示）＋ 彙總整體風險偏好。
 * 純規則、無 GPT。抓不到就整塊不顯示（加值背景，不擋主畫面）。
 */
import { useEffect, useState } from 'react'
import { fetchMacro } from '../api/client'

const TONE_CLS = { good: 'macro-good', warn: 'macro-warn', bad: 'macro-bad' }

function fmtVal(f) {
  if (f.key === 'TOTAL_MCAP') return `$${f.value.toFixed(2)}${f.unit}`
  const s = f.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return f.unit === '%' ? `${s}%` : s
}

export default function MacroPanel() {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let alive = true
    fetchMacro().then(d => { if (alive) setM(d) }).catch(() => { if (alive) setErr(true) })
    return () => { alive = false }
  }, [])

  if (err) return null
  if (!m) {
    return (
      <section className="macro-panel">
        <div className="macro-head"><h3 className="macro-title">宏觀環境</h3></div>
        <div className="macro-grid">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 66, borderRadius: 8 }} />
          ))}
        </div>
      </section>
    )
  }
  if (!m.ok) return null

  return (
    <section className="macro-panel">
      <div className="macro-head">
        <div className="macro-head-l">
          <h3 className="macro-title">宏觀環境</h3>
          <span className="macro-sub">會影響加密的總體經濟背景</span>
        </div>
        <span className={`macro-verdict ${TONE_CLS[m.tone] ?? 'macro-warn'}`}>
          <span className="macro-verdict-dot" />{m.verdict_zh}
        </span>
      </div>

      {m.summary_zh && <div className="macro-summary">{m.summary_zh}</div>}

      <div className="macro-grid">
        {m.factors.map(f => (
          <div key={f.key} className="macro-cell" data-impact={f.impact} title={f.note_zh}>
            <div className="macro-cell-lbl">{f.label_zh}</div>
            <div className="macro-cell-val">{fmtVal(f)}</div>
            <div className="macro-cell-meta">
              <span className="macro-cell-tag" data-impact={f.impact}>{f.impact_zh}</span>
              {f.change_pct != null && (
                <span className="macro-cell-chg">
                  {f.change_pct >= 0 ? '▲' : '▼'}{Math.abs(f.change_pct).toFixed(1)}%
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {m.note_zh && <div className="macro-foot">ⓘ {m.note_zh}</div>}
    </section>
  )
}
