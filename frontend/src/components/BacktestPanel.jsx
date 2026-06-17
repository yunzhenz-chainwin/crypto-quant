/**
 * BacktestPanel.jsx — 策略回測結果面板
 *
 * 目的：讓使用者用最少的數字理解「這個策略過去表現如何」
 *
 * 顯示三個核心指標：
 *   1. 策略報酬 vs 買入持有（比較是否比直接持有賺更多）
 *   2. 勝率（超過 50% 表示賺錢的次數多於賠錢）
 *   3. 最大資產回撤（從高點最多跌了多少，風險指標）
 *
 * 其他功能：
 *   - 可調整停損 / 停利參數（即時重新計算）
 *   - 資產變化曲線圖（每筆交易後的資產倍數）
 *   - 最近交易明細（預設收起，點擊展開）
 *
 * Props：
 *   symbol  幣種代號，例如 'BTCUSDT'
 */
import { useState, useEffect } from 'react'
import {
  ResponsiveContainer, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import { fetchBacktest } from '../api/client'
import { coinName } from '../constants/coins'

// 資產倍數曲線圖：X 軸是第幾筆交易，Y 軸是資產倍數（1.0 = 起始本金）
function EquityCurve({ data }) {
  if (!data || data.length === 0) return null
  return (
    <ResponsiveContainer width="100%" height={160}>
      <LineChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="trade" tick={{ fill: '#94a3b8', fontSize: 10 }} />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={44} />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
          formatter={(v) => [v.toFixed(3), '資產倍數']}
          labelFormatter={(l) => `第 ${l} 筆交易`}
        />
        <ReferenceLine y={1} stroke="#475569" strokeDasharray="4 2" />
        <Line dataKey="equity" stroke="#60a5fa" dot={false} strokeWidth={1.5} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function TradeTable({ trades }) {
  if (!trades || trades.length === 0) return null
  return (
    <div className="trade-table-scroll" style={{ marginTop: 12 }}>
      <table className="trade-table">
        <thead>
          <tr>
            <th>進場日</th><th>出場日</th>
            <th>損益</th><th>持倉</th><th>原因</th>
          </tr>
        </thead>
        <tbody>
          {[...trades].reverse().map((t, i) => (
            <tr key={i} className={t.profit ? 'win' : 'loss'}>
              <td>{t.entry_date}</td>
              <td>{t.exit_date}</td>
              <td className={t.return_pct >= 0 ? 'pos' : 'neg'}>
                {t.return_pct >= 0 ? '+' : ''}{t.return_pct}%
              </td>
              <td>{t.hold_days}天</td>
              <td className="reason">{t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function BacktestPanel({ symbol }) {
  const [data,       setData]       = useState(null)
  const [stopLoss,   setStopLoss]   = useState(-0.06)   // 預設停損 -6%
  const [takeProfit, setTakeProfit] = useState(0.20)    // 預設停利 +20%
  const [loading,    setLoading]    = useState(false)
  const [showDetail, setShowDetail] = useState(false)   // 交易明細預設收起

  // 換幣種或調整參數時重新計算回測
  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setData(null)
    fetchBacktest(symbol, stopLoss, takeProfit)
      .then(setData).catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [symbol, stopLoss, takeProfit])

  const m = data?.metrics
  // beatsHold=true 表示策略報酬 > 單純買入持有，用來決定顯示綠色還是警告色
  const beatsHold = m && m.total_return_pct > m.buy_hold_return_pct
  // diff 是策略報酬與買入持有的差距（正數=策略贏、負數=策略輸）
  const diff = m ? (m.total_return_pct - m.buy_hold_return_pct).toFixed(1) : null

  return (
    <section className="backtest-section">
      {/* 標題列 */}
      <div className="backtest-header">
        <div>
          <h2 className="section-title">策略回測</h2>
          <p className="section-subtitle">模擬過去 5 年依訊號買賣的假設績效</p>
        </div>
        <div className="param-row">
          <label>停損
            <select value={stopLoss} onChange={e => setStopLoss(+e.target.value)}>
              {[-0.03, -0.05, -0.06, -0.08, -0.10, -0.15].map(v => (
                <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
          </label>
          <label>停利
            <select value={takeProfit} onChange={e => setTakeProfit(+e.target.value)}>
              {[0.10, 0.15, 0.20, 0.25, 0.30, 0.50].map(v => (
                <option key={v} value={v}>+{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {loading && <div className="chart-empty">計算中…</div>}

      {m && (
        <>
          {/* 三個核心數字 */}
          <div className="key-metrics">
            {/* 策略 vs 持有 */}
            <div className={`key-metric ${beatsHold ? 'key-good' : 'key-warn'}`}>
              <div className="key-metric-top">
                <span className="key-metric-label">策略報酬</span>
                <span className="key-metric-badge">
                  {beatsHold ? `比持有多賺 +${diff}%` : `比持有少賺 ${diff}%`}
                </span>
              </div>
              <div className="key-metric-value">
                {m.total_return_pct >= 0 ? '+' : ''}{m.total_return_pct}%
              </div>
              <div className="key-metric-compare">
                買入持有 {m.buy_hold_return_pct >= 0 ? '+' : ''}{m.buy_hold_return_pct}%
              </div>
            </div>

            {/* 勝率 */}
            <div className={`key-metric ${m.win_rate >= 50 ? 'key-good' : 'key-neutral'}`}>
              <div className="key-metric-top">
                <span className="key-metric-label">勝率</span>
                <span className="key-metric-badge">{m.total_trades} 筆交易</span>
              </div>
              <div className="key-metric-value">{m.win_rate}%</div>
              <div className="key-metric-compare">
                {m.win_rate >= 50 ? '超過一半交易賺錢' : '不到一半交易賺錢'}，平均獲利 +{m.avg_win_pct}% / 平均虧損 {m.avg_loss_pct}%
              </div>
            </div>

            {/* 最大虧損 */}
            <div className="key-metric key-warn">
              <div className="key-metric-top">
                <span className="key-metric-label">最大資產回撤</span>
                <span className="key-metric-badge">風險指標</span>
              </div>
              <div className="key-metric-value" style={{ color: '#ef4444' }}>
                {m.max_drawdown_pct}%
              </div>
              <div className="key-metric-compare">
                策略資金從高點最多曾跌這麼多，夏普比率 {m.sharpe_ratio}
              </div>
            </div>
          </div>

          {/* 資產曲線 */}
          <div style={{ marginTop: 16 }}>
            <div className="key-chart-title">資產變化曲線（每筆交易後的倍數）</div>
            <EquityCurve data={data.equity_curve} />
          </div>

          {/* 展開更多 */}
          <button className="detail-toggle" onClick={() => setShowDetail(v => !v)}>
            {showDetail ? '▲ 收起交易明細' : '▼ 查看最近交易記錄'}
          </button>
          {showDetail && <TradeTable trades={data.recent_trades} />}
        </>
      )}
    </section>
  )
}
