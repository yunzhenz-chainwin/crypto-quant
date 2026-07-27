/**
 * GlossaryModal.jsx — 名詞小辭典彈窗（Header「辭典」開啟）
 *
 * 搜尋 + 分組列表；點詞條展開詳細說明。
 */
import { useRef, useState } from 'react'
import { GLOSSARY } from '../constants/glossary'
import { useDialogFocus } from '../lib/useDialogFocus'

export default function GlossaryModal({ onClose }) {
  const [q, setQ] = useState('')
  const [openTerm, setOpenTerm] = useState(null)
  const dialogRef = useRef(null)
  const searchRef = useRef(null)

  useDialogFocus(dialogRef, onClose, searchRef)

  const kw = q.trim().toLowerCase()
  const groups = GLOSSARY.map(g => ({
    ...g,
    items: g.items.filter(it =>
      !kw || it.term.toLowerCase().includes(kw)
      || it.brief.includes(q.trim()) || (it.detail ?? '').includes(q.trim())),
  })).filter(g => g.items.length)

  return (
    <div className="tour-backdrop" onClick={onClose}>
      <div
        ref={dialogRef}
        className="gloss-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="glossary-dialog-title"
        aria-describedby="glossary-dialog-help"
        tabIndex="-1"
        onClick={e => e.stopPropagation()}
      >
        <div className="gloss-head">
          <h2 id="glossary-dialog-title" className="gloss-title">名詞小辭典</h2>
          <button className="bot-close" onClick={onClose} aria-label="關閉">✕</button>
        </div>
        <input
          ref={searchRef}
          className="ai-input gloss-search"
          aria-label="搜尋名詞"
          placeholder="搜尋名詞，例如：RSI、回撤、背離…"
          value={q} onChange={e => setQ(e.target.value)}
        />
        <div className="gloss-body">
          {groups.length === 0 && (
            <div className="gloss-empty">找不到「{q}」——試試其他關鍵字（例：RSI、回撤、均線）</div>
          )}
          {groups.map((g, groupIndex) => (
            <div key={g.group} className="gloss-group">
              <div className="gloss-group-title">{g.group}</div>
              {g.items.map((it, itemIndex) => {
                const detailId = `glossary-detail-${groupIndex}-${itemIndex}`
                const isOpen = openTerm === it.term
                return (
                <button key={it.term}
                     type="button"
                     className={`gloss-item ${isOpen ? 'open' : ''}`}
                     disabled={!it.detail}
                     aria-expanded={it.detail ? isOpen : undefined}
                     aria-controls={it.detail ? detailId : undefined}
                     onClick={() => setOpenTerm(isOpen ? null : it.term)}>
                  <div className="gloss-item-row">
                    <span className="gloss-term">{it.term}</span>
                    <span className="gloss-brief">{it.brief}</span>
                    {it.detail && <span className="gloss-arrow" aria-hidden="true">{isOpen ? '▲' : '▼'}</span>}
                  </div>
                  {isOpen && it.detail && (
                    <div id={detailId} className="gloss-detail">{it.detail}</div>
                  )}
                </button>
              )})}
            </div>
          ))}
        </div>
        <div id="glossary-dialog-help" className="gloss-foot">更完整的指標教學：K 線圖下方選擇擺盪指標後，點「看詳細」。</div>
      </div>
    </div>
  )
}
