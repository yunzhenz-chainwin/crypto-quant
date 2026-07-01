/**
 * SignalHistoryChart.jsx — 信心分數歷史走勢
 *
 * 畫每日「多空信心分數」(0~100)。與訊號引擎同一套門檻:
 *   ≥65 偏多、≤35 偏空(中間為中性)。用 ReferenceLine 標出兩條門檻。
 *
 * 資料來自 fetchSignalHistory()(讀 DB 的 daily_signal 表)。
 * 每筆:{ date, signal, score, close, rsi }
 */
import {
  ResponsiveContainer, ComposedChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import { coinName } from '../constants/coins'

// YYYY-MM-DD → MM/DD
const fmtDate = (d) => {
  if (!d) return ''
  const [, m, day] = d.split('-')
  return `${m}/${day}`
}
const SIGNAL_LABEL = { BULL: '偏多', BEAR: '偏空', NEUTRAL: '中性', UNKNOWN: '—' }

export default function SignalHistoryChart({ data, symbol }) {
  if (!data || data.length === 0) return <div className="chart-empty">載入中…</div>

  return (
    <div className="chart-wrap">
      <h3 className="chart-title">
        {symbol && <span className="chart-coin-name">{coinName(symbol)}</span>}
        信心分數歷史 (0~100)
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fill: '#94a3b8', fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 11 }} width={36} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
            labelStyle={{ color: '#94a3b8' }}
            formatter={(v, _n, p) => [`${v}（${SIGNAL_LABEL[p?.payload?.signal] ?? ''}）`, '信心分數']}
          />
          {/* 偏多 / 偏空 門檻(與 scoring 的 65 / 35 一致)*/}
          <ReferenceLine y={65} stroke="#22c55e" strokeDasharray="4 2" label={{ value: '偏多 65', fill: '#22c55e', fontSize: 10, position: 'insideTopRight' }} />
          <ReferenceLine y={35} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '偏空 35', fill: '#ef4444', fontSize: 10, position: 'insideBottomRight' }} />
          <Area dataKey="score" name="信心分數" stroke="#818cf8" fill="#818cf8" fillOpacity={0.15} strokeWidth={1.5} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
