/**
 * PctInput.jsx — 停損／停利手動輸入框（規則區與回測共用）
 *
 * 使用者直接打想要的百分比；輸入過程只改本地文字，離開欄位或按 Enter 才送出重算，
 * 避免每打一個字就打一次 API。min/max 對齊後端 Query 的範圍防呆。
 *
 * Props：value=正整數百分比(如 6 代表 -6% 或 +6%)、sign 顯示符號、min/max、onCommit(clamped)
 */
import { useState } from 'react'

export default function PctInput({ value, sign, min, max, onCommit }) {
  const [text, setText] = useState(String(value))
  // 外部值變動(如切幣/重置)時同步顯示：在 render 期間依前值判斷調整 state（React 建議做法，免用 effect）
  const [prev, setPrev] = useState(value)
  if (value !== prev) { setPrev(value); setText(String(value)) }
  const commit = () => {
    const raw = text.trim()
    if (raw === '' || !Number.isFinite(Number(raw))) { setText(String(value)); return }   // 空白/非數字 → 還原前值
    const clamped = Math.min(max, Math.max(min, Math.round(Number(raw))))
    setText(String(clamped))
    if (clamped !== value) onCommit(clamped)
  }
  return (
    <span className="pct-input">
      <span className="pct-sign">{sign}</span>
      <input
        type="number" min={min} max={max} value={text}
        onChange={e => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
      />
      <span className="pct-suffix">%</span>
    </span>
  )
}
