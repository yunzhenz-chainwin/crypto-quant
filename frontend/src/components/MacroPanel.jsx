/**
 * MacroPanel.jsx — 宏觀環境（規則式，市場整體背景）
 *
 * 讀 /api/macro：DXY 美元指數 / VIX 恐慌 / 美債殖利率 / 標普 / 黃金 / BTC 主導率 / 總市值
 * → 每個因子對加密「順風/逆風/中性」（左側色條標示，詳細說明 hover 顯示）＋ 彙總整體風險偏好。
 *
 * 2026-08 起補上兩件讓這塊有分析價值的資訊（原本只有「現在的數字」）：
 *   連動強度 linkage — BTC 與各宏觀序列的 60 日滾動相關 + 歷史百分位。
 *                      回答「此刻該不該把宏觀當一回事」，相關性低就別拿總經解釋幣價。
 *   證據 evidence   — 這套順風/逆風標籤在歷史上的預測力檢定（src/macro_eval.py）。
 *                      目前主檢定並不顯著，面板就照實講不顯著，不用措辭撐場面。
 * 深水區（逐序列相關、檢定數字、近一年環境時間軸）預設收起，維持主畫面精簡。
 *
 * 純規則、無 GPT。抓不到就整塊不顯示（加值背景，不擋主畫面）。
 */
import { useEffect, useId, useState } from 'react'
import { fetchMacro, fetchMacroHistory } from '../api/client'

const TONE_CLS = { good: 'macro-good', warn: 'macro-warn', bad: 'macro-bad' }
const VERDICT_ZH = { RISK_ON: '順風', NEUTRAL: '中性', RISK_OFF: '逆風' }
// 證據強度 → 標籤顏色：有統計證據才給綠燈，其餘一律黃燈（不顯著就不能看起來像結論）
const EVIDENCE_CLS = { SUPPORTED: 'macro-good', DIRECTIONAL_ONLY: 'macro-warn' }

function fmtVal(f) {
  if (f.key === 'TOTAL_MCAP') return `$${f.value.toFixed(2)}${f.unit}`
  const s = f.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  return f.unit === '%' ? `${s}%` : s
}

// 逐日標籤 → 連續同標籤的區段，讓時間軸只畫數十個色塊而不是 365 個 div
function toRuns(points) {
  const runs = []
  for (const p of points) {
    const last = runs[runs.length - 1]
    if (last && last.verdict === p.verdict) {
      last.days += 1
      last.end = p.date
    } else {
      runs.push({ verdict: p.verdict, days: 1, start: p.date, end: p.date })
    }
  }
  return runs
}

function RegimeTimeline({ history }) {
  if (!history?.points?.length) return null
  const runs = toRuns(history.points)
  const counts = history.counts || {}
  return (
    <div className="macro-block">
      <div className="macro-block-title">
        近 {history.days} 天的環境變化
        <span className="macro-block-sub">
          順風 {counts.RISK_ON ?? 0} 天 · 中性 {counts.NEUTRAL ?? 0} 天 · 逆風 {counts.RISK_OFF ?? 0} 天
        </span>
      </div>
      <div className="macro-timeline">
        {runs.map((r, i) => (
          <div
            key={`${r.start}-${i}`}
            className="macro-timeline-seg"
            data-verdict={r.verdict}
            style={{ flexGrow: r.days }}
            title={`${r.start} ~ ${r.end}：${VERDICT_ZH[r.verdict] ?? r.verdict}（${r.days} 天）`}
          />
        ))}
      </div>
      <div className="macro-timeline-axis">
        <span>{history.points[0].date}</span>
        <span>{history.points[history.points.length - 1].date}</span>
      </div>
    </div>
  )
}

/**
 * data：由 App 統一抓好的 /api/macro。判斷摘要的第④格與這塊面板共用同一份，
 *       畫面上兩處講的環境才不會出現「摘要說順風、面板說逆風」。
 *       沒給時自行抓（元件仍可獨立使用，例如日後被其他頁面掛載）。
 */
export default function MacroPanel({ data = null }) {
  const [fetched, setFetched] = useState(null)
  const [err, setErr] = useState(false)
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState(null)
  const detailId = useId()
  const m = data ?? fetched

  useEffect(() => {
    if (data) return
    let alive = true
    fetchMacro().then(d => { if (alive) setFetched(d) }).catch(() => { if (alive) setErr(true) })
    return () => { alive = false }
  }, [data])

  // 時間軸只在使用者展開時才抓，主畫面載入不多打一支 API
  useEffect(() => {
    if (!open || history) return
    let alive = true
    fetchMacroHistory(365).then(d => { if (alive && d?.ok) setHistory(d) }).catch(() => {})
    return () => { alive = false }
  }, [open, history])

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

  const link = m.linkage
  const ev = m.evidence

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

      {/* 連動強度的白話結論放在主畫面：它決定上面那些數字現在值不值得看 */}
      {link?.text_zh && (
        <div className="macro-reading" data-level={link.level}>
          <span className="macro-reading-tag">影響力{link.level_zh}</span>
          {link.text_zh}
        </div>
      )}

      {(link?.series?.length || ev) && (
        <>
          <button
            className="detail-toggle"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            aria-controls={detailId}
          >
            {open
              ? '▲ 收起宏觀證據'
              : '▼ 展開宏觀證據（各項連動強度・歷史檢定・近一年環境變化）'}
          </button>

          {open && (
            <div id={detailId}>
              {link?.series?.length > 0 && (
                <div className="macro-block">
                  <div className="macro-block-title">
                    連動強度：BTC 與各宏觀序列的 {link.window_days} 日滾動相關
                    <span className="macro-block-sub">
                      +1 完全同向 / 0 無關 / −1 完全反向；百分位＝目前值在近五年中的位置
                    </span>
                  </div>
                  <div className="macro-link-grid">
                    {link.series.map(s => (
                      <div key={s.key} className="macro-link-cell">
                        <div className="macro-cell-lbl">{s.label_zh}</div>
                        <div className="macro-cell-val">
                          {s.corr >= 0 ? '+' : '−'}{Math.abs(s.corr).toFixed(2)}
                        </div>
                        <div className="macro-cell-meta">
                          <span className="macro-cell-chg">百分位 {s.percentile.toFixed(0)}%</span>
                        </div>
                        <div className="macro-link-bar">
                          <div className="macro-link-mid" />
                          <div
                            className="macro-link-fill"
                            data-sign={s.corr >= 0 ? 'pos' : 'neg'}
                            style={{ width: `${Math.min(50, Math.abs(s.corr) * 50)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {ev && (
                <div className="macro-block">
                  <div className="macro-block-title">
                    這個順風／逆風判斷，歷史上有多少證據
                    <span className={`macro-ev-tag ${EVIDENCE_CLS[ev.level] ?? 'macro-warn'}`}>
                      {ev.level_zh}
                    </span>
                  </div>
                  <div className="macro-ev-text">{ev.text_zh}</div>
                  <div className="macro-ev-sample">{ev.sample_zh}</div>
                </div>
              )}

              <RegimeTimeline history={history} />
            </div>
          )}
        </>
      )}

      {m.note_zh && <div className="macro-foot">ⓘ {m.note_zh}</div>}
    </section>
  )
}
