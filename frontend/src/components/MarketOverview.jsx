/**
 * MarketOverview.jsx — 市場總覽頁
 *
 * 一頁顯示所有 15 個幣種的關鍵指標，方便快速掃視：
 *   - 幣種名稱 + 訊號（BULL/BEAR/NEUTRAL）
 *   - 最新價格
 *   - RSI（顏色區分超買/超賣/正常）
 *   - 訊號理由
 *
 * 點擊任一列 → 切換到該幣種的詳細頁
 *
 * Props：
 *   signals   所有幣種的訊號陣列（來自 /api/signals）
 *   onSelect  點擊幣種時的回呼，傳入 symbol
 */
import { coinZh, coinTicker } from '../constants/coins'

const SIG = {
  BULL:    { label: '多頭 ▲', cls: 'ov-bull' },
  BEAR:    { label: '空頭 ▼', cls: 'ov-bear' },
  NEUTRAL: { label: '中立 —', cls: 'ov-neutral' },
}

// RSI 顏色：超買(>65)紅、超賣(<35)綠、正常黃
function RsiCell({ rsi }) {
  if (rsi == null) return <td className="ov-muted">—</td>
  const color = rsi > 65 ? '#ef4444' : rsi < 35 ? '#22c55e' : '#f59e0b'
  const tip   = rsi > 65 ? '超買' : rsi < 35 ? '超賣' : '正常'
  return (
    <td>
      <span style={{ color, fontWeight: 600 }}>{rsi.toFixed(0)}</span>
      <span className="ov-rsi-tip" style={{ color }}> {tip}</span>
    </td>
  )
}

export default function MarketOverview({ signals, onSelect }) {
  // 依訊號排序：BULL → NEUTRAL → BEAR
  const ORDER = { BULL: 0, NEUTRAL: 1, BEAR: 2 }
  const sorted = [...(signals ?? [])].sort(
    (a, b) => (ORDER[a.signal] ?? 1) - (ORDER[b.signal] ?? 1)
  )

  return (
    <section className="overview-section">
      <div className="overview-header">
        <h2 className="section-title">市場總覽</h2>
        <p className="section-subtitle">點擊任一幣種查看詳細分析</p>
      </div>

      <div className="overview-table-wrap">
        <table className="overview-table">
          <thead>
            <tr>
              <th>幣種</th>
              <th>訊號</th>
              <th>最新價格</th>
              <th>RSI</th>
              <th>訊號依據</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(s => {
              const sig   = SIG[s.signal] ?? SIG.NEUTRAL
              const price = s.close
                ? `$${Number(s.close).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
                : '—'

              return (
                <tr key={s.symbol} className="overview-row" onClick={() => onSelect(s.symbol)}>
                  {/* 幣種名稱 */}
                  <td className="ov-coin">
                    <span className="ov-ticker">{coinTicker(s.symbol)}</span>
                    <span className="ov-zh">{coinZh(s.symbol)}</span>
                  </td>

                  {/* 訊號標籤 */}
                  <td><span className={`ov-sig ${sig.cls}`}>{sig.label}</span></td>

                  {/* 價格 */}
                  <td className="ov-price">{price}</td>

                  {/* RSI */}
                  <RsiCell rsi={s.rsi} />

                  {/* 訊號理由（最多顯示 2 個） */}
                  <td className="ov-reasons">
                    {(s.reasons ?? []).slice(0, 2).map((r, i) => (
                      <span key={i} className="ov-reason-tag">{r}</span>
                    ))}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
