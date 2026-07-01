/**
 * FearGreedHistoryChart.jsx — 恐懼貪婪指數歷史(全市場)
 *
 * 0 = 極度恐慌，100 = 極度貪婪。這是整體加密市場的情緒,非單一幣種。
 * 參考線:25(恐慌)/ 50(中性)/ 75(貪婪)。
 *
 * 資料來自 fetchFearGreedHistory()(讀 DB 的 fear_greed 表)。
 * 每筆:{ date, value, label }
 */
import {
  ResponsiveContainer, ComposedChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'

const fmtDate = (d) => {
  if (!d) return ''
  const [, m, day] = d.split('-')
  return `${m}/${day}`
}

export default function FearGreedHistoryChart({ data }) {
  if (!data || data.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div className="chart-wrap">
      <h3 className="chart-title">恐懼貪婪指數歷史（全市場 0~100）</h3>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#94a3b8', fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} width={36} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v, _n, p) => [`${v}（${p?.payload?.label ?? ''}）`, '指數']}
          />
          <ReferenceLine y={75} stroke="#22c55e" strokeDasharray="4 2" label={{ value: '貪婪 75', fill: '#22c55e', fontSize: 10 }} />
          <ReferenceLine y={50} stroke="#64748b" strokeDasharray="2 2" />
          <ReferenceLine y={25} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '恐慌 25', fill: '#ef4444', fontSize: 10 }} />
          <Area dataKey="value" name="指數" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.12} strokeWidth={1.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
