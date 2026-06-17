/**
 * PriceChart.jsx — 價格走勢圖
 *
 * 顯示三條線：
 *   收盤價（白色）、MA20 短期均線（紫色）、MA60 中期均線（橙色）
 *
 * 資料格式（每筆）：{ date, close, MA20, MA60 }
 * date 格式是 YYYY-MM-DD，X 軸轉成 MM/DD 顯示
 * Y 軸顯示千元縮寫（例如 $65k）
 *
 * Props：
 *   data  來自 fetchIndicators() 的陣列
 */
import {
  ResponsiveContainer, ComposedChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend,
} from 'recharts'

// YYYY-MM-DD → MM/DD（X 軸空間有限，不顯示年份）
const fmtDate = (d) => {
  if (!d) return ''
  const [, m, day] = d.split('-')
  return `${m}/${day}`
}

// 格式化價格顯示，null/undefined 時顯示破折號
const fmtPrice = (v) =>
  v == null ? '—' : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 })}`

export default function PriceChart({ data }) {
  if (!data || data.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="date"
            tickFormatter={fmtDate}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            width={52}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v, name) => [fmtPrice(v), name]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line dataKey="close" name="收盤價" stroke="#e2e8f0" dot={false} strokeWidth={1.5} />
          <Line dataKey="MA20" name="MA20 短期" stroke="#818cf8" dot={false} strokeWidth={1.2} />
          <Line dataKey="MA60" name="MA60 中期" stroke="#fb923c" dot={false} strokeWidth={1.2} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
