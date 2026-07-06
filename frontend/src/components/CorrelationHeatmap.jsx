import { Fragment } from 'react'

// 把相關係數 -1~1 線性映射到顏色
// 正相關：藍色系；負相關：紅色系；中性：深灰
function corrToColor(v) {
  if (v == null) return '#1e293b'
  if (v >= 0) {
    // 0 → #334155（深灰），1 → #1d4ed8（深藍）
    const t = v
    const r = Math.round(51  + (29  - 51)  * t)
    const g = Math.round(65  + (78  - 65)  * t)
    const b = Math.round(85  + (216 - 85)  * t)
    return `rgb(${r},${g},${b})`
  } else {
    // 0 → #334155，-1 → #991b1b（深紅）
    const t = -v
    const r = Math.round(51  + (153 - 51) * t)
    const g = Math.round(65  + (27  - 65) * t)
    const b = Math.round(85  + (27  - 85) * t)
    return `rgb(${r},${g},${b})`
  }
}

export default function CorrelationHeatmap({ data }) {
  if (!data) return <div className="chart-empty">載入中…</div>

  const { symbols, matrix, volatility, period } = data
  const n = symbols.length

  return (
    <div className="heatmap-wrap">
      <h3 className="chart-title">
        日報酬相關性
        <span className="info-tip" title="相關係數 -1~+1：+1=兩幣完全同漲同跌、0=無關、-1=完全反向。幣圈普遍 0.6~0.9 高相關，代表「幣圈內分散買很多幣」的避險效果有限。">ⓘ</span>
        <span className="chart-subtitle"> {period?.start} ~ {period?.end}（{period?.days} 天）</span>
      </h3>

      {/* 熱力圖本體：n×n 的格子 */}
      <div
        className="heatmap-grid"
        style={{ gridTemplateColumns: `80px repeat(${n}, 1fr)` }}
      >
        {/* 左上角空格 */}
        <div />
        {/* 第一列：欄標題 */}
        {symbols.map(s => (
          <div key={s} className="heatmap-label heatmap-col-label">
            {s.replace('USDT', '')}
          </div>
        ))}

        {/* 每一列 */}
        {matrix.map((row, i) => (
          <Fragment key={i}>
            {/* 列標題 */}
            <div className="heatmap-label heatmap-row-label">
              {symbols[i].replace('USDT', '')}
            </div>
            {/* 每個格子 */}
            {row.map((val, j) => (
              <div
                key={`${i}-${j}`}
                className="heatmap-cell"
                style={{ background: corrToColor(val) }}
                title={`${symbols[i]} vs ${symbols[j]}: ${val?.toFixed(3)}`}
              >
                {val?.toFixed(2)}
              </div>
            ))}
          </Fragment>
        ))}
      </div>

      {/* 波動度表格 */}
      {volatility && (
        <div className="vol-table">
          <h4 className="vol-title">年化波動度<span className="info-tip" title="把日波動換算成年：數字越大代表這顆幣越「顛簸」。例如 80% 表示一年內上下 80% 幅度屬正常範圍，倉位應相應縮小。">ⓘ</span></h4>
          <div className="vol-row">
            {Object.entries(volatility).map(([sym, vol]) => (
              <div key={sym} className="vol-item">
                <span className="vol-sym">{sym.replace('USDT', '')}</span>
                <span className="vol-val">{vol.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
