/**
 * OnboardingTour.jsx — 首次造訪導覽（4 步卡片式，含小Q出場）
 *
 * 首次進站自動顯示（localStorage cq_tour_done 記錄看過）；
 * Header 的「❓ 導覽」可隨時重看。純覆蓋層卡片，不做元素錨定（簡單穩定）。
 */
import { useState } from 'react'
import BotMascot from './BotMascot'

const STEPS = [
  {
    emoji: '🚦', mood: 'neutral', title: '市場總覽＝紅綠燈',
    body: '每張卡片是一顆幣：▲綠色偏多、▼紅色偏空、—黃色中立。「信心分數」是 6 個技術指標的綜合評分（0~100，越高越偏多）。點任何卡片就能看完整分析。',
  },
  {
    emoji: '📈', mood: 'bull', title: '詳細頁：圖表隨你切',
    body: '蠟燭圖可切「日線／時線」（時線目前提供 BTC、ETH）、自由開關均線與指標；下方「AI 智能分析」會用白話幫你解讀盤勢，看不懂的按鈕都有說明。',
  },
  {
    emoji: '📋', mood: 'talk', title: '買賣判斷有依據',
    body: '詳細頁的「買賣判斷依據」面板完整列出進出場規則與 6 因子計分方式；還能自訂指標條件（RSI、MACD、均線、布林），直接在 K 線圖上看對應的買賣點與歷史績效。',
  },
  {
    emoji: '🔄', mood: 'idle', title: '資料自己會更新',
    body: '日線每天更新、時線每小時、新聞每 30 分鐘——頁面會自動偵測新資料，不用手動重整。\n\n⚠️ 最後提醒：本站所有內容是技術面教學分析，不是投資建議。',
  },
]

export default function OnboardingTour({ onClose }) {
  const [step, setStep] = useState(0)
  const s = STEPS[step]
  const last = step === STEPS.length - 1

  const finish = () => {
    localStorage.setItem('cq_tour_done', '1')
    onClose()
  }

  return (
    <div className="tour-backdrop" onClick={finish}>
      <div className="tour-card" onClick={e => e.stopPropagation()}>
        <div className="tour-mascot"><BotMascot mood={s.mood} size={84} /></div>
        <div className="tour-step-emoji">{s.emoji}</div>
        <div className="tour-title">{s.title}</div>
        <div className="tour-body">{s.body}</div>

        <div className="tour-dots">
          {STEPS.map((_, i) => (
            <span key={i} className={`tour-dot ${i === step ? 'on' : ''}`}
                  onClick={() => setStep(i)} />
          ))}
        </div>

        <div className="tour-actions">
          <button className="tour-skip" onClick={finish}>略過</button>
          <div className="tour-nav">
            {step > 0 && (
              <button className="tour-btn ghost" onClick={() => setStep(step - 1)}>上一步</button>
            )}
            <button className="tour-btn" onClick={() => (last ? finish() : setStep(step + 1))}>
              {last ? '開始使用 🎉' : '下一步'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
