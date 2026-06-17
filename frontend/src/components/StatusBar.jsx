import { useEffect, useState } from 'react'
import { fetchStatus } from '../api/client'

export default function StatusBar() {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    fetchStatus()
      .then(d => setStatus(d.last_updated))
      .catch(() => {})
  }, [])

  if (!status) return null

  // 取所有幣種中最新的一筆日期代表整體資料新鮮度
  const dates = Object.values(status)
  const latest = dates.sort().at(-1)

  return (
    <div className="status-bar">
      <span>資料截至：<strong>{latest}</strong></span>
      <span className="status-detail">
        {Object.entries(status).map(([sym, d]) => (
          <span key={sym}>{sym.replace('USDT', '')} {d}</span>
        ))}
      </span>
    </div>
  )
}
