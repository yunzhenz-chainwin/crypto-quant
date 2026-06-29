import { useEffect, useState } from 'react'
import { fetchStatus } from '../api/client'
import VerifyModal from './VerifyModal'

export default function StatusBar() {
  const [data, setData] = useState(null)
  const [showVerify, setShowVerify] = useState(false)

  useEffect(() => {
    fetchStatus().then(setData).catch(() => {})
  }, [])

  if (!data) return null

  const lu = data.last_updated ?? {}
  // 取所有幣種中最新的一筆日期代表整體資料新鮮度
  const latest = Object.values(lu).sort().at(-1)
  const v = data.verification   // 指標交叉驗證摘要

  return (
    <div className="status-bar">
      <span>資料截至：<strong>{latest}</strong></span>

      {/* 信任徽章:可點擊看詳細驗證資料 */}
      {v && (
        <button
          className={`verify-badge ${v.ok ? 'ok' : 'warn'}`}
          onClick={() => setShowVerify(true)}
          title="點擊查看交叉驗證詳情"
        >
          ✓ 指標已交叉驗證 {v.passed}/{v.total}
        </button>
      )}

      {showVerify && <VerifyModal onClose={() => setShowVerify(false)} />}
    </div>
  )
}
