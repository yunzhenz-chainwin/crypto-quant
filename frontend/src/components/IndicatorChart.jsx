import {
  ResponsiveContainer, ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from 'recharts'
import { coinName } from '../constants/coins'

const fmtDate = (d) => {
  if (!d) return ''
  const [, m, day] = d.split('-')
  return `${m}/${day}`
}

// ── RSI 面板 ──────────────────────────────────────────────────────────────
// RSI 在 70 以上代表超買（可能要回調），30 以下代表超賣（可能要反彈）
// 用 ReferenceLine 畫出這兩條警戒線
function RsiPanel({ data, symbol }) {
  return (
    <div className="chart-wrap">
      <h3 className="chart-title">
        {symbol && <span className="chart-coin-name">{coinName(symbol)}</span>}
        RSI (14)
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#94a3b8', fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} width={36} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v) => [v?.toFixed(2), 'RSI']}
          />
          {/* 超買線：紅色虛線 */}
          <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '70', fill: '#ef4444', fontSize: 10 }} />
          {/* 超賣線：綠色虛線 */}
          <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="4 2" label={{ value: '30', fill: '#22c55e', fontSize: 10 }} />
          <Line dataKey="RSI" name="RSI" stroke="#34d399" dot={false} strokeWidth={1.5} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── MACD 面板 ─────────────────────────────────────────────────────────────
// HIST（柱狀圖）正值=動能增強(綠)、負值=動能減弱(紅)
// MACD 線穿越 Signal 線 = 交叉訊號
function MacdPanel({ data, symbol }) {
  // 為每一根柱子動態上色，正值綠、負值紅
  const coloredData = (data ?? []).map(d => ({
    ...d,
    HIST_POS: d.HIST != null && d.HIST >= 0 ? d.HIST : null,
    HIST_NEG: d.HIST != null && d.HIST < 0  ? d.HIST : null,
  }))

  return (
    <div className="chart-wrap">
      <h3 className="chart-title">
        {symbol && <span className="chart-coin-name">{coinName(symbol)}</span>}
        MACD (12, 26, 9)
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={coloredData} margin={{ top: 4, right: 16, bottom: 0, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#94a3b8', fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={52} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v, name) => [v?.toFixed(2), name]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <ReferenceLine y={0} stroke="#475569" />
          {/* 柱狀圖：正綠負紅，疊在 MACD 線底下 */}
          <Bar dataKey="HIST_POS" name="柱狀(正)" fill="#22c55e" opacity={0.7} stackId="hist" />
          <Bar dataKey="HIST_NEG" name="柱狀(負)" fill="#ef4444" opacity={0.7} stackId="hist" />
          <Line dataKey="MACD"   name="MACD"   stroke="#60a5fa" dot={false} strokeWidth={1.2} />
          <Line dataKey="SIGNAL" name="訊號線" stroke="#f97316" dot={false} strokeWidth={1.2} strokeDasharray="4 2" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// 對外只暴露一個元件，外部不需要知道裡面分成兩個 panel
export default function IndicatorChart({ data, symbol }) {
  if (!data || data.length === 0) return <div className="chart-empty">載入中…</div>
  return (
    <>
      <RsiPanel data={data} symbol={symbol} />
      <MacdPanel data={data} symbol={symbol} />
    </>
  )
}
