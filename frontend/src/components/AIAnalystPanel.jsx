/**
 * AIAnalystPanel.jsx — AI 智能分析面板（雙引擎：本地規則引擎 + GPT）
 *
 * 顯示流程：
 *   1. 先打 gpt=false 的分析（純規則引擎，毫秒級）→ 立刻有內容
 *   2. 背景再打 gpt=true → GPT 深度解讀完成後補上（沒金鑰就顯示提示）
 *   3. 兩個來源立場不一致時顯示「觀點分歧」提醒（互相檢核）
 *   4. 底部提問框：針對這顆幣問 AI（GPT 未設定時後端自動降級回規則引擎摘要）
 *
 * Props：
 *   symbol      幣種
 *   refreshKey  資料版本字串；變了就自動重新分析（配合前台自動更新）
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { fetchAIAnalysis, askAI } from '../api/client'
import BotMascot, { stanceToMood } from './BotMascot'

// 極簡 markdown 渲染（粗體 + 條列 + 段落），全部走 React 節點、不用 innerHTML
function Md({ text }) {
  if (!text) return null
  const bold = (line, ki) => {
    const parts = String(line).split('**')
    return parts.map((s, i) => (i % 2 === 1 ? <b key={`${ki}-${i}`}>{s}</b> : s))
  }
  const lines = String(text).split('\n')
  const out = []
  let list = []
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

const STANCE_STYLE = {
  '偏多': { c: '#22c55e', icon: '▲' },
  '偏空': { c: '#ef4444', icon: '▼' },
  '中性': { c: '#f59e0b', icon: '—' },
}

function StanceChip({ stance, label }) {
  const s = STANCE_STYLE[stance] ?? STANCE_STYLE['中性']
  return (
    <span className="ai-stance" style={{ color: s.c, borderColor: `${s.c}66` }}>
      {s.icon} {stance}{label ? <span className="ai-stance-src">{label}</span> : null}
    </span>
  )
}

const QUICK_QUESTIONS = ['現在適合進場嗎？', '主要風險是什麼？', '短線和波段分別怎麼看？']

export default function AIAnalystPanel({ symbol, refreshKey }) {
  const [data, setData]       = useState(null)   // 分析結果（local 永遠有）
  const [gptLoading, setGptLoading] = useState(false)
  const [err, setErr]         = useState('')
  const [question, setQuestion] = useState('')
  const [chat, setChat]       = useState([])     // [{q, a, source}]
  const [asking, setAsking]   = useState(false)
  const seq = useRef(0)                          // 防止過期回應覆蓋新幣種

  const load = useCallback(async (force = false) => {
    const my = ++seq.current
    setErr('')
    try {
      // 第一步：本地規則引擎（即時）
      const local = await fetchAIAnalysis(symbol, { gpt: false, force })
      if (seq.current !== my) return
      setData(local)
      // 第二步：GPT 深度解讀（背景補上；未設定金鑰時後端直接回 disabled）
      setGptLoading(true)
      const full = await fetchAIAnalysis(symbol, { gpt: true, force })
      if (seq.current !== my) return
      setData(full)
    } catch (e) {
      if (seq.current === my) setErr('AI 分析載入失敗：' + e.message)
    } finally {
      if (seq.current === my) setGptLoading(false)
    }
  }, [symbol])

  useEffect(() => { setChat([]); load() }, [load, refreshKey])

  const submitQuestion = async (q) => {
    const text = (q ?? question).trim()
    if (!text || asking) return
    // 帶上已完成的對話當上下文，GPT 才接得住「那如果跌破呢？」這類追問
    const history = chat.filter(m => m.a && m.source !== 'error')
                        .map(m => ({ q: m.q, a: m.a }))
    setAsking(true); setQuestion('')
    setChat(c => [...c, { q: text, a: null }])
    try {
      const r = await askAI(symbol, text, history)
      setChat(c => c.map(m => (m.q === text && m.a === null)
        ? { ...m, a: r.answer, source: r.source, coin: r.name_zh } : m))
    } catch (e) {
      setChat(c => c.map(m => (m.q === text && m.a === null) ? { ...m, a: '回答失敗：' + e.message, source: 'error' } : m))
    } finally {
      setAsking(false)
    }
  }

  const local = data?.local
  const gpt   = data?.gpt
  const gptDisabled = data?.gpt_status === 'disabled'
  const gptError    = data?.gpt_status?.startsWith?.('error')

  // 小Q 表情：載入/GPT 思考中→thinking；否則跟著規則引擎立場變臉
  const mascotMood = (!data || gptLoading || asking) ? 'thinking'
    : stanceToMood(local?.stance)

  return (
    <div className="ai-panel">
      {/* 標題列：小Q + 立場 + 一致性 + 重新分析 */}
      <div className="ai-head">
        <BotMascot mood={mascotMood} size={72} className="ai-mascot" />
        <span className="ai-title">AI 智能分析</span>
        {local && <StanceChip stance={local.stance} label="規則引擎" />}
        {gpt && <StanceChip stance={gpt.stance} label={`GPT`} />}
        {data?.agreement === true  && <span className="ai-agree ok">✓ 兩個引擎觀點一致</span>}
        {data?.agreement === false && <span className="ai-agree warn">⚠ 觀點分歧，訊號存疑、宜保守</span>}
        <button className="ai-refresh" onClick={() => load(true)} disabled={gptLoading}>
          {gptLoading ? '分析中…' : '↻ 重新分析'}
        </button>
      </div>

      {err && <div className="ai-error">{err}</div>}
      {!data && !err && (
        <div className="ai-cols">
          {[0, 1].map(i => (
            <div key={i} className="ai-col">
              <div className="skeleton sk-line" style={{ width: '45%' }} />
              <div className="skeleton sk-line" style={{ width: '90%' }} />
              <div className="skeleton sk-line" style={{ width: '82%' }} />
              <div className="skeleton sk-line" style={{ width: '86%' }} />
            </div>
          ))}
        </div>
      )}

      {local && (
        <div className="ai-cols">
          {/* 本地規則引擎 */}
          <div className="ai-col">
            <div className="ai-col-head">規則引擎（6 因子量化）</div>
            <div className="ai-headline">{local.headline}</div>
            <ul className="ai-points">
              {local.points.map(p => (
                <li key={p.tag}><b>{p.tag}</b>｜{p.text}</li>
              ))}
            </ul>
            {local.risks?.length > 0 && (
              <div className="ai-risks">
                {local.risks.map((r, i) => <div key={i}>注意：{r}</div>)}
              </div>
            )}
            <div className="ai-suggestion">{local.suggestion}</div>
          </div>

          {/* GPT 深度解讀 */}
          <div className="ai-col">
            <div className="ai-col-head">
              GPT 深度解讀
              {gpt?.model && <span className="ai-model">{gpt.model}</span>}
            </div>
            {gpt ? (
              <>
                <div className="ai-headline">{gpt.headline}</div>
                <Md text={gpt.analysis} />
                {gpt.risks?.length > 0 && (
                  <div className="ai-risks">
                    {gpt.risks.map((r, i) => <div key={i}>注意：{r}</div>)}
                  </div>
                )}
                {gpt.watch?.length > 0 && (
                  <div className="ai-watch">
                    <b>接下來觀察：</b>
                    <ul>{gpt.watch.map((w, i) => <li key={i}>{w}</li>)}</ul>
                  </div>
                )}
                {gpt.agree_with_rules === false && gpt.disagree_reason && (
                  <div className="ai-disagree">GPT 與規則引擎看法不同：{gpt.disagree_reason}</div>
                )}
              </>
            ) : gptLoading ? (
              <div className="ai-loading">GPT 分析中，約需數秒…</div>
            ) : gptDisabled ? (
              <div className="ai-hint">
                尚未設定 GPT API 金鑰。左側規則引擎分析照常可用；<br />
                想啟用 GPT 深度解讀與智慧問答，請到 <a href="/admin">後台 → AI 設定</a> 填入金鑰。
              </div>
            ) : gptError ? (
              <div className="ai-hint">GPT 暫時無法使用（{data.gpt_status.replace('error: ', '')}）。左側規則引擎分析不受影響。</div>
            ) : null}
          </div>
        </div>
      )}

      {/* 提問區 */}
      <div className="ai-ask">
        <div className="ai-ask-quick">
          {QUICK_QUESTIONS.map(q => (
            <button key={q} className="ai-chip" disabled={asking} onClick={() => submitQuestion(q)}>{q}</button>
          ))}
        </div>
        <div className="ai-ask-row">
          <input
            className="ai-input"
            placeholder={`問 AI 關於這顆幣的問題（例如：${QUICK_QUESTIONS[0]}）`}
            value={question}
            maxLength={500}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitQuestion() }}
          />
          <button className="ai-send" onClick={() => submitQuestion()} disabled={asking || !question.trim()}>
            {asking ? '思考中…' : '送出'}
          </button>
        </div>
        {chat.length > 0 && (
          <div className="ai-chat">
            {[...chat].reverse().map((m, i) => (
              <div key={i} className="ai-chat-item">
                <div className="ai-chat-q">{m.q}</div>
                <div className="ai-chat-a">
                  {m.a === null ? <span className="ai-loading">思考中…</span> : <Md text={m.a} />}
                  {m.source === 'gpt' && <span className="ai-chat-src">{m.coin ? `${m.coin} · ` : ''}by GPT</span>}
                  {m.source === 'canned+gpt' && <span className="ai-chat-src">{m.coin ? `${m.coin} · ` : ''}by 小Q 固定答案 × GPT 優化</span>}
                  {(m.source === 'canned' || m.source === 'knowledge') && <span className="ai-chat-src">{m.coin ? `${m.coin} · ` : ''}by 小Q 固定答案</span>}
                  {m.source === 'local' && <span className="ai-chat-src">{m.coin ? `${m.coin} · ` : ''}by 規則引擎</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="ai-disclaimer">
        以上為系統自動產生的技術面解讀（規則引擎 + AI），僅供學習參考，不構成投資建議。
      </div>
    </div>
  )
}
