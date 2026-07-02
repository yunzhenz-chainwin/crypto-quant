/**
 * BotWidget.jsx — 全站漂浮 AI 小幫手「小Q」
 *
 * 右下角漂浮吉祥物按鈕（全站都在），點開變成迷你聊天卡：
 *   - 幣種下拉（預設跟隨目前瀏覽的幣）
 *   - 開啟時自動取得該幣的規則引擎快評（立場 + 一句話），小Q 表情跟著多空變臉
 *   - 快速問題 chips + 自由提問（走 /api/ai/ask，沒 GPT 金鑰會自動降級規則引擎）
 *
 * Props：
 *   symbols        可選幣種清單
 *   defaultSymbol  預設幣種（詳細頁跟隨當前幣）
 */
import { useState, useEffect, useRef } from 'react'
import { fetchAIAnalysis, askAI } from '../api/client'
import { coinZh, coinTicker } from '../constants/coins'
import BotMascot, { stanceToMood } from './BotMascot'

const QUICK = ['現在適合進場嗎？', '主要風險是什麼？', '幫我總結今天的狀況']

// 與 AIAnalystPanel 相同的極簡 markdown（粗體 + 條列），不用 innerHTML
function Md({ text }) {
  if (!text) return null
  const bold = (line, ki) => String(line).split('**').map((s, i) => (i % 2 === 1 ? <b key={`${ki}-${i}`}>{s}</b> : s))
  const lines = String(text).split('\n')
  const out = []; let list = []
  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    const m = line.match(/^\s*[-*•]\s+(.*)$/)
    if (m) { list.push(<li key={`li${i}`}>{bold(m[1], i)}</li>); return }
    if (list.length) { out.push(<ul key={`ul${i}`}>{list}</ul>); list = [] }
    if (line.trim()) out.push(<p key={`p${i}`}>{bold(line, i)}</p>)
  })
  if (list.length) out.push(<ul key="ul-end">{list}</ul>)
  return <div className="ai-md">{out}</div>
}

export default function BotWidget({ symbols = [], defaultSymbol = 'BTCUSDT' }) {
  const [open, setOpen]   = useState(false)
  const [sym, setSym]     = useState(defaultSymbol)
  const [brief, setBrief] = useState(null)     // 規則引擎快評
  const [chat, setChat]   = useState([])       // [{q, a, source}]
  const [q, setQ]         = useState('')
  const [busy, setBusy]   = useState(false)
  const [hello, setHello] = useState(() => !sessionStorage.getItem('cq_bot_greeted'))
  const bodyRef = useRef(null)
  const seq = useRef(0)

  // 詳細頁切幣時，小幫手跟著換（未打開對話時才自動跟隨，避免打斷聊天）
  useEffect(() => {
    if (!open && defaultSymbol) setSym(defaultSymbol)
  }, [defaultSymbol, open])

  // 打開 / 換幣 → 抓規則引擎快評（毫秒級、免費）
  useEffect(() => {
    if (!open || !sym) return
    const my = ++seq.current
    setBrief(null)
    fetchAIAnalysis(sym, { gpt: false })
      .then(r => { if (seq.current === my) setBrief(r) })
      .catch(() => {})
  }, [open, sym])

  // 新訊息進來時捲到底
  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight
  }, [chat, brief])

  const toggle = () => {
    setOpen(v => !v)
    if (hello) { setHello(false); sessionStorage.setItem('cq_bot_greeted', '1') }
  }

  const send = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    // 帶上已完成的對話當上下文（連續追問）
    const history = chat.filter(m => m.a && m.source !== 'error')
                        .map(m => ({ q: m.q, a: m.a }))
    setQ(''); setBusy(true)
    setChat(c => [...c, { q: question, a: null }])
    try {
      const r = await askAI(sym, question, history)
      setChat(c => c.map(m => (m.q === question && m.a === null)
        ? { ...m, a: r.answer, source: r.source } : m))
    } catch (e) {
      setChat(c => c.map(m => (m.q === question && m.a === null)
        ? { ...m, a: '哎呀，回答失敗了：' + e.message, source: 'error' } : m))
    } finally {
      setBusy(false)
    }
  }

  // 小Q 的表情：忙碌→思考；有快評→跟著多空變臉；否則待機
  const mood = busy ? 'thinking' : brief ? stanceToMood(brief.local?.stance) : 'idle'
  const stance = brief?.local?.stance

  return (
    <div className="bot-widget">
      {/* 聊天卡 */}
      {open && (
        <div className="bot-card">
          <div className="bot-card-head">
            <BotMascot mood={mood} size={38} />
            <div className="bot-card-title">
              <b>小Q</b>
              <span>量化小幫手</span>
            </div>
            <select className="bot-coin-select" value={sym} onChange={e => setSym(e.target.value)}>
              {(symbols.length ? symbols : [sym]).map(s => (
                <option key={s} value={s}>{coinZh(s)} {coinTicker(s)}</option>
              ))}
            </select>
            <button className="bot-close" onClick={toggle} aria-label="關閉">✕</button>
          </div>

          <div className="bot-card-body" ref={bodyRef}>
            {/* 開場快評 */}
            <div className="bot-bubble bot-bubble-bot">
              {brief ? (
                <>
                  <div className="bot-brief-line">
                    {stance && <span className={`bot-stance s-${stanceToMood(stance)}`}>{stance}</span>}
                    <b>{brief.local?.headline}</b>
                  </div>
                  <div className="bot-brief-sub">
                    {brief.local?.suggestion}
                  </div>
                </>
              ) : (
                <span className="ai-loading">小Q 正在看盤…</span>
              )}
            </div>

            {/* 對話 */}
            {chat.map((m, i) => (
              <div key={i}>
                <div className="bot-bubble bot-bubble-user">{m.q}</div>
                <div className="bot-bubble bot-bubble-bot">
                  {m.a === null
                    ? <span className="bot-typing"><i /><i /><i /></span>
                    : <Md text={m.a} />}
                  {m.source === 'gpt' && <div className="bot-src">by GPT</div>}
                  {m.source === 'local' && <div className="bot-src">by 規則引擎</div>}
                </div>
              </div>
            ))}
          </div>

          <div className="bot-quick">
            {QUICK.map(t => (
              <button key={t} className="ai-chip" disabled={busy} onClick={() => send(t)}>{t}</button>
            ))}
          </div>
          <div className="bot-input-row">
            <input
              className="ai-input"
              placeholder={`問小Q 關於${coinZh(sym)}的問題…`}
              value={q} maxLength={500}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') send() }}
            />
            <button className="ai-send" onClick={() => send()} disabled={busy || !q.trim()}>送出</button>
          </div>
          <div className="bot-foot">技術面解讀僅供學習參考，不構成投資建議</div>
        </div>
      )}

      {/* 漂浮按鈕（吉祥物本體） */}
      <button className={`bot-fab ${open ? 'open' : ''}`} onClick={toggle}
              aria-label="開啟 AI 小幫手">
        {hello && !open && <span className="bot-hello">嗨！我是小Q，點我聊行情 👋</span>}
        <BotMascot mood={open ? mood : 'idle'} size={60} />
      </button>
    </div>
  )
}
