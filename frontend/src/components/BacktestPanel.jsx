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
import { useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, Legend,
} from 'recharts'
import IndicatorCards from './IndicatorCards'

// 資產倍數曲線圖：X 軸是第幾筆交易，Y 軸是資產倍數（1.0 = 起始本金）
function EquityCurve({ data }) {
  if (!data || data.length === 0) return null
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis dataKey="trade" tick={{ fill: '#94a3b8', fontSize: 10 }} />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={44}
               tickFormatter={(v) => `${v}x`} />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
          formatter={(v, name) => [`${Number(v).toFixed(3)}x`, name]}
          labelFormatter={(l) => `第 ${l} 筆交易`}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine y={1} stroke="#475569" strokeDasharray="4 2" />
        <Line dataKey="equity" name="策略" stroke="#60a5fa" dot={false} strokeWidth={1.8} />
        <Line dataKey="bh" name="買入持有" stroke="#94a3b8" dot={false}
              strokeWidth={1.5} strokeDasharray="5 3" />
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
              <td className="reason">{EXIT_REASON_LABEL[t.exit_reason] ?? t.exit_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ValidationTable({ validation }) {
  if (!validation) return null
  const rows = [
    ['樣本內', validation.in_sample],
    ['樣本外', validation.out_of_sample],
  ]
  return (
    <div className="mini-table-wrap">
      <div className="key-chart-title">
        樣本切分驗證
        <Info text="把資料切成前 60%（樣本內）和後 40%（樣本外）。若樣本外也能賺錢，代表策略不是只在歷史上剛好有效，較不容易是過度最佳化。" />
      </div>
      <table className="mini-table">
        <thead>
          <tr>
            <th>區間</th><th>期間</th><th>報酬</th><th>持有</th><th>回撤</th><th>Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, row]) => {
            const m = row?.metrics ?? {}
            return (
              <tr key={label}>
                <td>{label}</td>
                <td>{row?.period?.start} ~ {row?.period?.end}</td>
                <td className={m.total_return_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(m.total_return_pct)}</td>
                <td>{fmtPct(m.buy_hold_return_pct)}</td>
                <td className="neg">{fmtPct(m.max_drawdown_pct)}</td>
                <td>{m.sharpe_ratio ?? '-'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SweepTable({ rows }) {
  if (!rows || rows.length === 0) return null
  return (
    <div className="mini-table-wrap">
      <div className="key-chart-title">
        參數掃描 Top 5
        <Info text="系統自動試了多種停損／停利組合，依夏普值與超額報酬排序後列出表現最好的前 5 組，方便你挑選參數。" />
      </div>
      <table className="mini-table">
        <thead>
          <tr>
            <th>停損</th><th>停利</th><th>報酬</th><th>超額</th><th>回撤</th><th>Sharpe</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.stop_loss}-${r.take_profit}`}>
              <td>{fmtPct(r.stop_loss * 100, 0)}</td>
              <td>{fmtPct(r.take_profit * 100, 0)}</td>
              <td className={r.total_return_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(r.total_return_pct)}</td>
              <td className={r.excess_return_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(r.excess_return_pct)}</td>
              <td className="neg">{fmtPct(r.max_drawdown_pct)}</td>
              <td>{r.sharpe_ratio}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const n = Number(value)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

// 出場原因：後端用英文代碼，前端顯示成中文讓一般使用者看得懂
const EXIT_REASON_LABEL = {
  stop_loss:   '停損出場',
  take_profit: '停利出場',
  signal_exit: '訊號轉空出場',
}

// 滑鼠移上去會顯示說明的小問號，用來解釋專有名詞
function Info({ text }) {
  return <span className="info-tip" title={text}>ⓘ</span>
}

// 白話結論：把一堆數字翻成一句人話，先講「贏還是輸大盤」再講風險
function VerdictBanner({ data }) {
  const m = data?.metrics
  if (!m || m.error) return null
  const beat     = m.total_return_pct >= m.buy_hold_return_pct
  const diffAbs  = Math.abs(m.total_return_pct - m.buy_hold_return_pct).toFixed(1)
  const ddBetter = Math.abs(m.max_drawdown_pct) < Math.abs(m.buy_hold_max_drawdown_pct)
  const period   = data.period ? `${data.period.start} ~ ${data.period.end}` : ''

  return (
    <div className={`backtest-verdict ${beat ? 'good' : 'warn'}`}>
      <div className="verdict-head">
        {beat ? '✅ 這段期間「照訊號操作」贏過「買了就放著」' : '⚠️ 這段期間「照訊號操作」輸給「買了就放著」'}
      </div>
      <p className="verdict-body">
        {period} 共進出場 <b>{m.total_trades}</b> 次：策略總報酬 <b>{fmtPct(m.total_return_pct)}</b>、
        買入持有 <b>{fmtPct(m.buy_hold_return_pct)}</b>，策略{beat ? '多賺' : '少賺'}約 <b>{diffAbs}%</b>。
        最大回撤（從高點最多跌幅）策略 <b>{fmtPct(m.max_drawdown_pct)}</b>、買入持有 {fmtPct(m.buy_hold_max_drawdown_pct)}，
        代表策略{ddBetter ? '波動較小、比較抗跌' : '波動較大'}。
      </p>
      <p className="verdict-note">※ 這是已扣手續費與滑價的「歷史模擬」，訊號採日線波段，過去績效不代表未來。</p>
    </div>
  )
}

// 回測資料與參數由父層(App)集中管理,面板為受控元件:
//   - 與 K 線買賣標記共用同一份回測(不再各抓一次)
//   - 調整停損/停利時,K 線上的箭頭會跟著一起變
export default function BacktestPanel({ signal, data, loading, params, onParamsChange }) {
  const [showDetail, setShowDetail] = useState(false)   // 交易明細預設收起

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
          <label>停損<Info text="跌幅達多少就認賠出場，保護本金。例如 -6% = 買進後跌 6% 就賣。" />
            <select value={params.stopLoss} onChange={e => onParamsChange({ stopLoss: +e.target.value })}>
              {[-0.03, -0.05, -0.06, -0.08, -0.10, -0.15].map(v => (
                <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
          </label>
          <label>停利<Info text="漲幅達多少就獲利了結。例如 +20% = 買進後漲 20% 就賣。" />
            <select value={params.takeProfit} onChange={e => onParamsChange({ takeProfit: +e.target.value })}>
              {[0.10, 0.15, 0.20, 0.25, 0.30, 0.50].map(v => (
                <option key={v} value={v}>+{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
          </label>
          <label>手續費<Info text="每次買或賣交易所收取的成本，單邊計算。一般現貨約 0.1%。" />
            <select value={params.feeRate} onChange={e => onParamsChange({ feeRate: +e.target.value })}>
              {[0, 0.0005, 0.001, 0.002].map(v => (
                <option key={v} value={v}>{(v * 100).toFixed(2)}%</option>
              ))}
            </select>
          </label>
          <label>滑價<Info text="實際成交價與預期價的落差（市場波動造成）。模擬越保守可設越高。" />
            <select value={params.slippage} onChange={e => onParamsChange({ slippage: +e.target.value })}>
              {[0, 0.0005, 0.001, 0.0025, 0.005].map(v => (
                <option key={v} value={v}>{(v * 100).toFixed(2)}%</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* 策略依據的指標(白話卡)— 不等回測,立即顯示 */}
      {signal?.factors && (
        <div className="bt-indicators">
          <div className="key-chart-title">策略依據的指標(即時解讀)</div>
          <IndicatorCards factors={signal.factors} rsi={signal.rsi} />
        </div>
      )}

      {loading && <div className="chart-empty">計算中…</div>}

      {/* 友善的空狀態：沒有資料或沒有任何交易時，不要顯示一堆空白數字 */}
      {!loading && data?.error && (
        <div className="chart-empty">此幣種尚無回測資料</div>
      )}
      {!loading && m?.error && (
        <div className="chart-empty">{m.error}（試著放寬停損／停利再算一次）</div>
      )}

      {!loading && m && !m.error && (
        <>
          {/* 白話結論 */}
          <VerdictBanner data={data} />

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
                買入持有 {fmtPct(m.buy_hold_return_pct)}，超額 {fmtPct(m.excess_return_pct)}
                <Info text="超額報酬＝策略報酬－買入持有報酬。正數代表這套策略比單純抱著更划算。" />
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
                {m.win_rate >= 50 ? '超過一半交易賺錢' : '不到一半交易賺錢'}，平均成本 {m.avg_cost_pct ?? 0}%
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
                策略回撤 vs 持有回撤 {fmtPct(m.buy_hold_max_drawdown_pct)}，夏普比率 {m.sharpe_ratio}
                <Info text="夏普比率＝每承擔一單位波動換到的報酬。數字越高代表報酬相對風險越划算，一般 >1 算不錯。" />
              </div>
            </div>
          </div>

          <div className="backtest-grid">
            <ValidationTable validation={data.validation} />
            <SweepTable rows={data.parameter_sweep} />
          </div>

          {/* 資產曲線 */}
          <div style={{ marginTop: 16 }}>
            <div className="key-chart-title">
              資產變化曲線:策略 vs 買入持有(每筆交易後的倍數,1.0 = 本金)
            </div>
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
