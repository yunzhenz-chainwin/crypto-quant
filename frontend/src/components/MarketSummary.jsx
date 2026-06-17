/**
 * MarketSummary.jsx — 頂部市場摘要列
 * 顯示：今日日期、多空分布、恐懼貪婪指數、最後更新時間 + 手動刷新
 */
import { useState, useEffect } from 'react'

const FG_CONFIG = [
  { max: 25,  label: '極度恐慌', color: '#ef4444' },
  { max: 45,  label: '恐慌',     color: '#f97316' },
  { max: 55,  label: '中立',     color: '#f59e0b' },
  { max: 75,  label: '貪婪',     color: '#22c55e' },
  { max: 100, label: '極度貪婪', color: '#10b981' },
]
function fgInfo(val) {
  return FG_CONFIG.find(c => val <= c.max) ?? FG_CONFIG[FG_CONFIG.length - 1]
}

export default function MarketSummary({ signals, fearGreed, lastUpdated, onRefresh, refreshing }) {
  const [elapsed, setElapsed] = useState(0)

  // 每 10 秒更新「X 分鐘前」顯示
  useEffect(() => {
    if (!lastUpdated) return
    setElapsed(Math.floor((Date.now() - lastUpdated) / 1000))
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - lastUpdated) / 1000))
    }, 10000)
    return () => clearInterval(id)
  }, [lastUpdated])

  const bull    = signals.filter(s => s.signal === 'BULL').length
  const bear    = signals.filter(s => s.signal === 'BEAR').length
  const neutral = signals.filter(s => s.signal === 'NEUTRAL').length

  const fg     = fearGreed ? parseInt(fearGreed.value) : null
  const fgMeta = fg != null ? fgInfo(fg) : null

  const dateStr = new Date().toLocaleDateString('zh-TW', {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
  })

  const elapsedStr = elapsed < 60
    ? `${elapsed} 秒前更新`
    : elapsed < 3600
    ? `${Math.floor(elapsed / 60)} 分鐘前更新`
    : `${Math.floor(elapsed / 3600)} 小時前更新`

  return (
    <div className="market-summary">
      {/* 日期 */}
      <span className="ms-date">{dateStr}</span>

      <span className="ms-sep">|</span>

      {/* 多空分布 */}
      <div className="ms-signals">
        <span className="ms-sig ms-bull">▲ {bull} 多頭</span>
        <span className="ms-sig ms-neutral">— {neutral} 中立</span>
        <span className="ms-sig ms-bear">▼ {bear} 空頭</span>
      </div>

      <span className="ms-sep">|</span>

      {/* 恐懼貪婪 */}
      {fgMeta && (
        <span className="ms-fg" style={{ color: fgMeta.color }}>
          恐懼貪婪 {fg} · {fgMeta.label}
        </span>
      )}

      {/* 彈性空白 */}
      <span style={{ flex: 1 }} />

      {/* 更新時間 */}
      {lastUpdated > 0 && (
        <span className="ms-updated">{elapsedStr}</span>
      )}

      {/* 刷新按鈕 */}
      <button
        className={`ms-refresh-btn ${refreshing ? 'spinning' : ''}`}
        onClick={onRefresh}
        title="重新整理市場資料"
        disabled={refreshing}
      >
        ↻
      </button>
    </div>
  )
}
