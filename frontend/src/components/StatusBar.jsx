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

      {/* 行情出處：原本只有即時報價圓點的 hover 提到 Binance，
          而真正拿來算指標與回測的「歷史 K 棒」一個字都沒標。 */}
      <span className="status-source">
        行情：
        <a href="https://www.binance.com" target="_blank" rel="noopener noreferrer"
           title="K 線（開高低收、成交量）取自 Binance 公開 API；只存已收盤的 K 棒，避免半根 K 棒污染指標">
          Binance API
        </a>
        <span className="status-source-note">（只取已收盤 K 棒）</span>
      </span>

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
