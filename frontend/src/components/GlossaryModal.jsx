/**
 * GlossaryModal.jsx — 名詞小辭典彈窗（Header「📖 辭典」開啟）
 *
 * 搜尋 + 分組列表；點詞條展開詳細說明；底部引導問小Q。
 */
import { useState } from 'react'
import { GLOSSARY } from '../constants/glossary'

export default function GlossaryModal({ onClose }) {
  const [q, setQ] = useState('')
  const [openTerm, setOpenTerm] = useState(null)

  const kw = q.trim().toLowerCase()
  const groups = GLOSSARY.map(g => ({
    ...g,
    items: g.items.filter(it =>
      !kw || it.term.toLowerCase().includes(kw)
      || it.brief.includes(q.trim()) || (it.detail ?? '').includes(q.trim())),
  })).filter(g => g.items.length)

  return (
    <div className="tour-backdrop" onClick={onClose}>
      <div className="gloss-card" onClick={e => e.stopPropagation()}>
        <div className="gloss-head">
          <span className="gloss-title">📖 名詞小辭典</span>
          <button className="bot-close" onClick={onClose} aria-label="關閉">✕</button>
        </div>
        <input
          className="ai-input gloss-search"
          placeholder="搜尋名詞，例如：RSI、回撤、背離…"
          value={q} onChange={e => setQ(e.target.value)} autoFocus
        />
        <div className="gloss-body">
          {groups.length === 0 && (
            <div className="gloss-empty">找不到「{q}」— 可以直接問右下角的小Q！</div>
          )}
          {groups.map(g => (
            <div key={g.group} className="gloss-group">
              <div className="gloss-group-title">{g.group}</div>
              {g.items.map(it => (
                <div key={it.term}
                     className={`gloss-item ${openTerm === it.term ? 'open' : ''}`}
                     onClick={() => setOpenTerm(openTerm === it.term ? null : it.term)}>
                  <div className="gloss-item-row">
                    <span className="gloss-term">{it.term}</span>
                    <span className="gloss-brief">{it.brief}</span>
                    {it.detail && <span className="gloss-arrow">{openTerm === it.term ? '▲' : '▼'}</span>}
                  </div>
                  {openTerm === it.term && it.detail && (
                    <div className="gloss-detail">{it.detail}</div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="gloss-foot">想更深入？直接問右下角的小Q 🤖（例：「背離是什麼？」）</div>
      </div>
    </div>
  )
}
