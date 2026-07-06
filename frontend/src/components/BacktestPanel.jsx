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

// 出場原因徽章：訊號出場藍 / 停損紅 / 停利綠
function ExitBadge({ reason }) {
  const M = {
    signal_exit: { t: '訊號出場', c: '#60a5fa' },
    stop_loss:   { t: '停損',     c: '#ef4444' },
    take_profit: { t: '停利',     c: '#22c55e' },
  }
  const m = M[reason] ?? { t: EXIT_REASON_LABEL[reason] ?? reason, c: '#94a3b8' }
  return <span className="tt-badge" style={{ color: m.c, borderColor: `${m.c}66`, background: `${m.c}1a` }}>{m.t}</span>
}

// 交易明細：精簡列一眼掃 → 點任一列展開「完整明細卡」（全部欄位，與後台一致）
function TradeTable({ trades }) {
  const [open, setOpen] = useState(null)
  if (!trades || trades.length === 0) return null
  const rows = [...trades].reverse()             // 最新的排最上面
  const px  = (v) => `$${fmtPrice(v)}`
  const pct = (v) => `${v >= 0 ? '+' : ''}${v}%`
  return (
    <div className="trade-table-scroll" style={{ marginTop: 12 }}>
      <table className="trade-table tt-rich">
        <thead>
          <tr>
            <th aria-hidden="true"></th>
            <th>進場日</th><th>買入價</th><th>出場日</th><th>賣出價</th>
            <th>淨報酬</th><th>持倉</th><th>出場原因</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t, i) => ([
            <tr key={`r${i}`}
                className={`tt-row ${t.profit ? 'win' : 'loss'} ${open === i ? 'open' : ''}`}
                onClick={() => setOpen(o => (o === i ? null : i))}
                title="點一下看這一筆的完整明細">
              <td className="tt-caret">{open === i ? '▾' : '▸'}</td>
              <td>{t.entry_date}</td>
              <td>{px(t.entry_price)}</td>
              <td>{t.exit_date}</td>
              <td>{px(t.exit_price)}</td>
              <td className={t.return_pct >= 0 ? 'pos' : 'neg'}>{pct(t.return_pct)}</td>
              <td>{t.hold_days} 天</td>
              <td><ExitBadge reason={t.exit_reason} /></td>
            </tr>,
            open === i && (
              <tr key={`d${i}`} className="tt-detail-row">
                <td colSpan={8}>
                  <div className="tt-detail">
                    <div className="tt-detail-hero">
                      <div className={`tt-ret ${t.profit ? 'pos' : 'neg'}`}>
                        {t.return_pct >= 0 ? '+' : ''}{t.return_pct}<span>%</span>
                      </div>
                      <div className="tt-hero-tags">
                        <span className={`tt-result ${t.profit ? 'win' : 'loss'}`}>{t.profit ? '獲利' : '虧損'}</span>
                        <ExitBadge reason={t.exit_reason} />
                        <span className="tt-hold">{t.entry_date} → {t.exit_date}．持有 {t.hold_days} 天</span>
                      </div>
                    </div>
                    <div className="tt-detail-grid">
                      <div className="tt-field"><span>買入價<i>含滑價</i></span><b>{px(t.entry_price)}</b></div>
                      <div className="tt-field"><span>賣出價<i>含滑價</i></span><b>{px(t.exit_price)}</b></div>
                      <div className="tt-field"><span>進場觸發價<i>原始開盤</i></span><b>{px(t.entry_trigger_price)}</b></div>
                      <div className="tt-field"><span>出場觸發價<i>原始</i></span><b>{px(t.exit_trigger_price)}</b></div>
                      <div className="tt-field"><span>毛報酬<i>未扣成本</i></span><b className={t.gross_return_pct >= 0 ? 'pos' : 'neg'}>{pct(t.gross_return_pct)}</b></div>
                      <div className="tt-field"><span>成本<i>手續費+滑價</i></span><b>{t.cost_pct}%</b></div>
                    </div>
                  </div>
                </td>
              </tr>
            ),
          ]))}
        </tbody>
      </table>
      <div className="trade-table-note">
        ※ 點任一列可展開該筆完整明細。買入／賣出價＝含滑價的模擬成交價；進場一律為「訊號翻多的隔天開盤」，
        出場依原因：停損／停利為當日觸價、訊號轉空為隔天開盤。
      </div>
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

// 價位自適應小數位（低價幣如 DOGE $0.07 不能被捨成 0）
function fmtPrice(value) {
  const n = Number(value)
  if (value === null || value === undefined || Number.isNaN(n)) return '-'
  if (n < 1) return n.toFixed(4)
  if (n < 100) return n.toFixed(2)
  return Math.round(n).toLocaleString()
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
        {beat ? '這段期間「照訊號操作」贏過「買了就放著」' : '注意：這段期間「照訊號操作」輸給「買了就放著」'}
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

// 買賣點規則 + 三基準公正比較 + 驗證方法白話說明
// 目的：讓決策者分得出「賺錢是選時的功勞，還是市場本來就在漲」，且每一步可稽核
function MethodologySection({ data }) {
  const m = data?.metrics
  if (!m || m.error) return null
  const rb  = data.random_baseline           // 舊版後端無此欄位 → 優雅降級
  const pct = rb?.strategy_percentile

  let verdict = null
  if (pct != null) {
    if (pct >= 95)      verdict = { cls: 'good', text: `本策略總報酬贏過 ${pct}% 的隨機進場——「選時」很可能有價值（仍受樣本數限制）。` }
    else if (pct >= 75) verdict = { cls: 'mid',  text: `本策略總報酬贏過 ${pct}% 的隨機進場——略優於亂選日子，但證據還不算強。` }
    else if (pct >= 40) verdict = { cls: 'warn', text: `本策略總報酬只贏過 ${pct}% 的隨機進場——選時與亂選差不多，賺賠主要來自市場本身的漲跌。` }
    else                verdict = { cls: 'warn', text: `本策略總報酬只贏過 ${pct}% 的隨機進場——選時比亂選日子還差。` }
  }

  return (
    <div className="mini-table-wrap methodology">
      <div className="key-chart-title">
        買賣點規則與公正比較
        <Info text="把買賣規則、比較基準、驗證方法攤開講清楚：賺錢要分得出是「選時機的功勞」還是「市場本來就在漲」。" />
      </div>

      {/* 買賣點規則（白話、與 src/backtest.py 的實際邏輯一字一句對齊）*/}
      <div className="method-rules">
        <div><b>買點</b>：6 因子信心分數 ≥65（訊號翻多）→ <b>隔天開盤</b>買入</div>
        <div><b>賣點</b>（先到先賣）：當日跌到停損價／漲到停利價 → 以觸發價賣出；訊號翻空（分數 ≤35）→ 隔天開盤賣出</div>
        <div><b>成本</b>：每筆買賣皆已扣手續費與滑價（雙邊）</div>
        <div className="method-rules-more">完整的 6 因子計分明細與「這顆幣現在幾分」，見上方「買賣判斷依據」面板。</div>
      </div>

      {/* 三基準比較 */}
      <table className="mini-table">
        <thead><tr><th>比較</th><th>總報酬</th><th>說明</th></tr></thead>
        <tbody>
          <tr>
            <td>照訊號進出（本策略）</td>
            <td className={m.total_return_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(m.total_return_pct)}</td>
            <td>由訊號選日子，共 {m.total_trades} 筆</td>
          </tr>
          <tr>
            <td>買入持有</td>
            <td className={m.buy_hold_return_pct >= 0 ? 'pos' : 'neg'}>{fmtPct(m.buy_hold_return_pct)}</td>
            <td>第一天買、抱到最後（完全不選時）</td>
          </tr>
          <tr>
            <td>隨機進場（模擬 {rb?.n_sims ?? 500} 次）</td>
            {rb ? (
              <>
                <td className={rb.median_return_pct >= 0 ? 'pos' : 'neg'}>
                  {fmtPct(rb.median_return_pct)}
                  <span className="method-range">（5%~95%：{fmtPct(rb.p05_return_pct)} ~ {fmtPct(rb.p95_return_pct)}）</span>
                </td>
                <td>筆數、持有天數、停損停利全相同，只有「買的日子」亂選</td>
              </>
            ) : (
              <>
                <td>—</td>
                <td>後端服務更新後顯示</td>
              </>
            )}
          </tr>
        </tbody>
      </table>
      {verdict && <div className={`method-verdict ${verdict.cls}`}>{verdict.text}</div>}

      {/* 驗證方法（可稽核的四條）*/}
      <ul className="method-notes">
        <li>沒偷看未來：訊號只用「當天收盤前已知」的資料計算，隔天開盤才成交。</li>
        <li>樣本內／外切分：前 60% 資料調規則、後 40% 當考試（見下方「樣本切分驗證」表），降低過度最佳化。</li>
        <li>隨機基準用固定亂數種子：任何人重算，數字完全相同（可重現＝可稽核）。</li>
        <li>誠實局限：共 {m.total_trades} 筆交易、樣本有限；「參數掃描 Top 5」屬事後挑最好、直接採用會偏樂觀；過去績效不代表未來。</li>
      </ul>
    </div>
  )
}

// 回測資料與參數由父層(App)集中管理,面板為受控元件:
//   - 與 K 線買賣標記共用同一份回測(不再各抓一次)
//   - 調整停損/停利時,K 線上的箭頭會跟著一起變
// 一鍵參數組合：新手不用懂四個 %，選風格就好（專業模式仍可微調下拉）
const PRESETS = [
  { key: '保守', hint: '小賠就跑、小賺就收',   p: { stopLoss: -0.05, takeProfit: 0.10, feeRate: 0.001, slippage: 0.001 } },
  { key: '平衡', hint: '預設參數',             p: { stopLoss: -0.06, takeProfit: 0.20, feeRate: 0.001, slippage: 0.0005 } },
  { key: '積極', hint: '拉大停損停利抱久一點', p: { stopLoss: -0.10, takeProfit: 0.30, feeRate: 0.001, slippage: 0.0005 } },
]

export default function BacktestPanel({ signal, data, loading, params, onParamsChange }) {
  const [showDetail, setShowDetail] = useState(false)   // 交易明細預設收起
  const activePreset = PRESETS.find(pr =>
    pr.p.stopLoss === params.stopLoss && pr.p.takeProfit === params.takeProfit &&
    pr.p.feeRate === params.feeRate && pr.p.slippage === params.slippage)?.key

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
        <div className="param-col">
        <div className="preset-row">
          <span className="preset-lbl">參數風格：</span>
          {PRESETS.map(pr => (
            <button key={pr.key} title={pr.hint}
              className={`preset-btn ${activePreset === pr.key ? 'active' : ''}`}
              onClick={() => onParamsChange(pr.p)}>
              {pr.key}
            </button>
          ))}
          {!activePreset && <span className="preset-custom">自訂中</span>}
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

          {/* 買賣點規則 + 三基準比較（買入持有／隨機進場）+ 驗證方法白話 */}
          <MethodologySection data={data} />

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
            {showDetail ? '▲ 收起交易明細' : `▼ 查看交易記錄（全部 ${data.recent_trades?.length ?? 0} 筆，點列看完整明細）`}
          </button>
          {showDetail && <TradeTable trades={data.recent_trades} />}
        </>
      )}
    </section>
  )
}
