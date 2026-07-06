/**
 * BotWidget.jsx — 全站漂浮 AI 小幫手「小Q」
 *
 * 右下角漂浮吉祥物按鈕（全站都在），點開變成迷你聊天卡：
 *   - 免選幣：同一個聊天室什麼幣都能問，後端從問題文字自動偵測
 *     （「以太幣可以進場嗎？」→ ETH），沒提到幣就沿用目前聊的幣
 *   - 開啟時自動取得目前幣的規則引擎快評，小Q 表情跟著多空變臉
 *   - 快速問題 chips + 自由提問（走 /api/ai/ask，沒 GPT 金鑰自動降級規則引擎）
 *
 * Props：
 *   defaultSymbol  詳細頁＝當前幣；總覽頁＝null（全市場模式：小Q 是整站的
 *                  小幫手，不綁定任何幣，徽章顯示「全市場」、開場講大盤）
 */
import { useState, useEffect, useRef } from 'react'
import { fetchAIAnalysis, askAI, fetchFearGreed, fetchNewsSentiment } from '../api/client'
import { coinZh } from '../constants/coins'
import BotMascot, { stanceToMood } from './BotMascot'

// 快速問題：綁定幣時問該幣；全市場模式引導講幣名或問通用問題
const QUICK_COIN   = ['這顆幣是什麼？', '現在適合進場嗎？', '主要風險是什麼？', '大盤情緒怎麼樣？']
const QUICK_MARKET = ['大盤情緒怎麼樣？', '比特幣現在如何？', 'RSI 是什麼？', '支援哪些幣？']

// 與 AIAnalystPanel 相同的極簡 markdown（粗體 + 條列），不用 innerHTML
function Md({ text }) {
  if (!text) return null
  const bold = (line, ki) => String(line).split('**').map((s, i) => (i % 2 === 1 ? <b key={`${ki}-${i}`}>{s}</b> : s))
  const lines = String(text).split('\n')
  const out = []; let list = []
  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    const m = line.match(/^\s*[-*•・]\s+(.*)$/)
    if (m) { list.push(<li key={`li${i}`}>{bold(m[1], i)}</li>); return }
    if (list.length) { out.push(<ul key={`ul${i}`}>{list}</ul>); list = [] }
    if (line.trim()) out.push(<p key={`p${i}`}>{bold(line, i)}</p>)
  })
  if (list.length) out.push(<ul key="ul-end">{list}</ul>)
  return <div className="ai-md">{out}</div>
}

export default function BotWidget({ defaultSymbol = null }) {
  const [open, setOpen]   = useState(false)
  // 目前聊的幣：null=全市場模式（總覽頁預設）；提到幣名才會綁定
  const [sym, setSym]     = useState(defaultSymbol)
  const [brief, setBrief] = useState(null)            // 規則引擎快評
  const [chat, setChat]   = useState([])              // [{q, a, source, coin}]
  const [q, setQ]         = useState('')
  const [busy, setBusy]   = useState(false)
  const [hello, setHello] = useState(() => !sessionStorage.getItem('cq_bot_greeted'))
  const bodyRef = useRef(null)
  const seq = useRef(0)

  // 詳細頁切幣、回總覽 → 小幫手跟著切（未打開對話時才自動跟隨，避免打斷聊天）
  useEffect(() => {
    if (!open) setSym(defaultSymbol)
  }, [defaultSymbol, open])

  // 打開 / 換幣 → 抓開場快評：有幣=該幣規則引擎快評；全市場=恐懼貪婪+新聞情緒
  useEffect(() => {
    if (!open) return
    const my = ++seq.current
    setBrief(null)
    if (sym) {
      fetchAIAnalysis(sym, { gpt: false })
        .then(r => { if (seq.current === my) setBrief(r) })
        .catch(() => {})
    } else {
      Promise.all([fetchFearGreed(1), fetchNewsSentiment('MARKET', 1)])
        .then(([fg, ns]) => {
          if (seq.current !== my) return
          const d = ns?.daily?.length ? ns.daily[ns.daily.length - 1] : null
          setBrief({ market: { fg: fg?.[0] ?? null, senti: d } })
        })
        .catch(() => { if (seq.current === my) setBrief({ market: {} }) })
    }
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
      // 後端偵測到問題講的是某顆幣 → 聊天室綁定它；全市場回答（symbol=null）則維持不綁定
      if (r.symbol && r.symbol !== sym) setSym(r.symbol)
      setChat(c => c.map(m => (m.q === question && m.a === null)
        ? { ...m, a: r.answer, source: r.source, coin: r.name_zh } : m))
    } catch (e) {
      setChat(c => c.map(m => (m.q === question && m.a === null)
        ? { ...m, a: '哎呀，回答失敗了：' + e.message, source: 'error' } : m))
    } finally {
      setBusy(false)
    }
  }

  // 小Q 的表情：忙碌→思考；單幣=跟多空變臉；全市場=跟恐懼貪婪變臉
  const fgVal = brief?.market?.fg ? Number(brief.market.fg.value) : null
  const mood = busy ? 'thinking'
    : brief?.local ? stanceToMood(brief.local.stance)
    : fgVal != null ? (fgVal <= 25 ? 'bear' : fgVal >= 75 ? 'bull' : 'neutral')
    : 'idle'
  const stance = brief?.local?.stance

  return (
    <div className="bot-widget">
      {/* 聊天卡 */}
      {open && (
        <div className="bot-card">
          <div className="bot-card-head">
            <BotMascot mood={mood} size={42} />
            <div className="bot-card-title">
              <b>小Q</b>
              <span>量化小幫手</span>
            </div>
            <button className="bot-close" onClick={toggle} aria-label="關閉">✕</button>
          </div>

          <div className="bot-card-body" ref={bodyRef}>
            {/* 開場快評（單幣＝規則引擎；全市場＝大盤溫度） */}
            <div className="bot-bubble bot-bubble-bot">
              {brief?.market ? (
                <>
                  <div className="bot-brief-line"><b>全市場現況</b></div>
                  <div className="bot-brief-sub">
                    {brief.market.fg ? `恐懼貪婪指數 ${brief.market.fg.value}（${
                      {'Extreme Fear':'極度恐慌','Fear':'恐慌','Neutral':'中性','Greed':'貪婪','Extreme Greed':'極度貪婪'}[brief.market.fg.value_classification] ?? brief.market.fg.value_classification ?? ''}）` : ''}
                    {brief.market.senti ? `｜今日新聞情緒 ${brief.market.senti.score > 0 ? '+' : ''}${brief.market.senti.score}` : ''}
                  </div>
                  <div className="bot-brief-hint">
                    我是全站小幫手，想看哪顆幣直接講名字（例：「比特幣現在如何？」），教學問題也可以問我～
                  </div>
                </>
              ) : brief ? (
                <>
                  <div className="bot-brief-line">
                    {stance && <span className={`bot-stance s-${stanceToMood(stance)}`}>{stance}</span>}
                    <b>{brief.local?.headline}</b>
                  </div>
                  <div className="bot-brief-sub">
                    {brief.local?.suggestion}
                  </div>
                  <div className="bot-brief-hint">
                    什麼幣都可以直接問我，例如「以太幣風險？」「SOL 最近表現？」
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
                  {m.a !== null && m.source !== 'error' && (
                    <div className="bot-src">
                      {m.coin ? `${m.coin} · ` : ''}
                      {m.source === 'gpt' ? 'by GPT'
                        : m.source === 'canned+gpt' ? 'by 小Q 固定答案 × GPT 優化'
                        : (m.source === 'canned' || m.source === 'knowledge') ? 'by 小Q 固定答案'
                        : 'by 規則引擎'}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="bot-quick">
            {(sym ? QUICK_COIN : QUICK_MARKET).map(t => (
              <button key={t} className="ai-chip" disabled={busy} onClick={() => send(t)}>{t}</button>
            ))}
          </div>
          <div className="bot-input-row">
            <input
              className="ai-input"
              placeholder={sym
                ? `問${coinZh(sym)}，或講其他幣名自動切換…`
                : '問我任何幣或大盤：比特幣如何？市場情緒？'}
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
        {hello && !open && <span className="bot-hello">嗨！我是小Q，什麼幣都能問我</span>}
        <BotMascot mood={open ? mood : 'idle'} size={92} />
      </button>
    </div>
  )
}
