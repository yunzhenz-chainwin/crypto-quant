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
 *   - 每日資產變化曲線圖（依完成日線盯市）
 *   - 最近交易明細（預設收起，點擊展開）
 *
 * Props：
 *   symbol  幣種代號，例如 'BTCUSDT'
 */
import { useId, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, Legend,
} from 'recharts'
import PctInput from './PctInput'

// 每日資產倍數曲線圖：X 軸是日期，Y 軸是資產倍數（1.0 = 起始本金）
function EquityCurve({ data }) {
  if (!data || data.length === 0) return null
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart accessibilityLayer data={data} margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="date"
          minTickGap={28}
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          tickFormatter={(value) => String(value).slice(0, 7)}
        />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={44}
               tickFormatter={(v) => `${v}x`} />
        <Tooltip
          contentStyle={{ background: '#0b1220', border: '1px solid #334155', borderRadius: 6 }}
          formatter={(v, name) => [`${Number(v).toFixed(3)}x`, name]}
          labelFormatter={(date) => `日期 ${date}`}
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
  const tableId = useId()
  if (!trades || trades.length === 0) return null
  const rows = [...trades].reverse()             // 最新的排最上面
  const px  = (v) => `$${fmtPrice(v)}`
  const pct = (v) => `${v >= 0 ? '+' : ''}${v}%`
  const toggleRow = (index) => setOpen(current => (current === index ? null : index))
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
                onClick={() => toggleRow(i)}
                title="點一下看這一筆的完整明細">
              <td className="tt-caret">
                <button
                  type="button"
                  aria-label={`${t.entry_date} 交易完整明細`}
                  aria-expanded={open === i}
                  aria-controls={`${tableId}-trade-detail-${i}`}
                  onClick={(event) => {
                    event.stopPropagation()
                    toggleRow(i)
                  }}
                  style={{ background: 'transparent', border: 0, color: 'inherit', cursor: 'pointer', padding: 0 }}
                >
                  {open === i ? '▾' : '▸'}
                </button>
              </td>
              <td>{t.entry_date}</td>
              <td>{px(t.entry_price)}</td>
              <td>{t.exit_date}</td>
              <td>{px(t.exit_price)}</td>
              <td className={t.return_pct >= 0 ? 'pos' : 'neg'}>{pct(t.return_pct)}</td>
              <td>{t.hold_days} 天</td>
              <td><ExitBadge reason={t.exit_reason} /></td>
            </tr>,
            open === i && (
              <tr key={`d${i}`} id={`${tableId}-trade-detail-${i}`} className="tt-detail-row">
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
    ['前段 60%', validation.in_sample],
    ['後段 40%', validation.out_of_sample],
  ]
  return (
    <div className="mini-table-wrap">
      <div className="key-chart-title">
        前後期穩定性檢查
        <Info text="依時間順序把資料切成前 60% 與後 40%，用相同固定規則比較不同時期的表現。這不是獨立模型驗證，也不能證明未來有效。" />
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
        參數探索 Top 5（事後探索）
        <Info text="在同一段歷史資料試多種停損／停利組合後排序，只適合觀察參數敏感度；直接挑第一名會高估未來表現。" />
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
      <div className="trade-table-note">
        ※ 這是同一歷史區間的事後探索，不是獨立驗證，也不是建議直接採用的參數。
      </div>
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
  return <span className="info-tip" title={text} tabIndex={0} role="note" aria-label={text}>ⓘ</span>
}

/**
 * 風險與統計對照：把三個「後端早就算好、但畫面從沒顯示」的數字接上來。
 *
 * 少了這三根柱子，使用者只看得到總報酬，很容易把下面三種情況誤讀成策略有效：
 *   夏普對照 — 策略 0.08 看起來「還行」，但同期買入持有是 0.49，其實輸很多。
 *   曝險比例 — 策略多數時間空手時，「贏過大盤」可能只是沒參與到下跌，不是選時準。
 *   t 統計量 — 交易次數少時，賺賠很可能只是運氣；|t|>2 才算有統計證據。
 */
function tstatReading(t) {
  if (t == null) return null
  if (Math.abs(t) < 2) {
    return '與 0 沒有明顯差別 —— 目前的賺賠可能只是運氣，交易次數還不足以證明策略有效'
  }
  // 直接看 t 的正負，不要用「總報酬是否為正」去猜方向：
  // 兩者可能不一致（複利路徑 vs 每筆平均），猜錯就會把賠錢講成賺錢。
  return t > 0
    ? '顯著大於 0 —— 在統計上站得住腳（仍不保證未來）'
    : '顯著小於 0 —— 這不是運氣不好，是穩定在賠錢'
}

function RiskReality({ m }) {
  const bhSharpe = m?.buy_hold_sharpe_ratio
  const exposure = m?.exposure_pct
  const tstat = m?.mean_trade_return_tstat
  if (bhSharpe == null && exposure == null && tstat == null) return null

  // API 為了可稽核保留 4 位小數（0.0777 / 36.1782），畫面要收斂成讀得下去的位數
  const f2 = v => (v == null ? '-' : Number(v).toFixed(2))
  // 比較要用「顯示後的精度」判斷：ETH 是 0.3146 vs 0.3074，四捨五入後畫面兩個都是 0.31，
  // 若還宣稱「策略優於」，讀者會看到兩個一樣的數字配上有優劣的結論。
  const sharpeGap = (bhSharpe != null && m.sharpe_ratio != null) ? m.sharpe_ratio - bhSharpe : null
  const sharpeTied = sharpeGap != null && Math.abs(sharpeGap) < 0.005
  const sharpeWorse = sharpeGap != null && !sharpeTied && sharpeGap < 0
  const tText = tstatReading(tstat)

  return (
    <div className="risk-reality">
      <div className="risk-reality-title">
        風險調整後的對照
        <Info text="只看總報酬會漏掉三件事：承擔了多少波動、有多少時間真的在場上、以及這個結果有沒有統計意義。" />
      </div>
      <div className="risk-reality-grid">
        {bhSharpe != null && (
          <div className="risk-reality-item" data-tone={sharpeTied ? 'warn' : sharpeWorse ? 'bad' : 'ok'}>
            <div className="risk-reality-lbl">夏普比率對照</div>
            <div className="risk-reality-val">
              策略 {f2(m.sharpe_ratio)} <span className="risk-reality-vs">vs</span> 買入持有 {f2(bhSharpe)}
            </div>
            <div className="risk-reality-note">
              {sharpeTied
                ? '兩者接近，看不出差別：每承擔一單位波動換到的報酬與單純買了放著相當'
                : sharpeWorse
                  ? '每承擔一單位波動換到的報酬，策略比單純買了放著更差'
                  : '每承擔一單位波動換到的報酬，策略優於單純買了放著'}
            </div>
          </div>
        )}

        {exposure != null && (
          <div className="risk-reality-item" data-tone={exposure < 40 ? 'warn' : 'ok'}>
            <div className="risk-reality-lbl">曝險比例</div>
            <div className="risk-reality-val">{Number(exposure).toFixed(0)}%</div>
            <div className="risk-reality-note">
              期間內只有這麼多時間真的持有部位；空手時既沒參與下跌、也沒參與上漲。
              {exposure < 40 && ' 曝險偏低時「少賠」可能只是因為多半不在場上，不代表選時準。'}
            </div>
          </div>
        )}

        {tText && (
          // 色條必須看 t 的「正負」而不只是「顯不顯著」：
          // ATOM t=-3.57／UNI t=-2.96 這種是「顯著地穩定賠錢」，塗綠會把最壞的情況講成最好的。
          <div className="risk-reality-item"
               data-tone={tstat >= 2 ? 'ok' : tstat <= -2 ? 'bad' : 'warn'}>
            <div className="risk-reality-lbl">每筆報酬的統計檢定</div>
            <div className="risk-reality-val">t = {f2(tstat)}</div>
            <div className="risk-reality-note">{tText}</div>
          </div>
        )}
      </div>
    </div>
  )
}

// 白話結論：陳述歷史報酬差與回撤，不把「少跌」包裝成勝出。
function VerdictBanner({ data }) {
  const m = data?.metrics
  if (!m || m.error) return null
  const returnGap = m.total_return_pct - m.buy_hold_return_pct
  const gapAbs    = Math.abs(returnGap).toFixed(1)
  const ddBetter = Math.abs(m.max_drawdown_pct) < Math.abs(m.buy_hold_max_drawdown_pct)
  const ddEqual  = Math.abs(m.max_drawdown_pct) === Math.abs(m.buy_hold_max_drawdown_pct)
  const period   = data.period ? `${data.period.start} ~ ${data.period.end}` : ''
  const oosReturn = data?.validation?.out_of_sample?.metrics?.total_return_pct
  const randomPercentile = data?.random_baseline?.strategy_percentile

  const headline = returnGap > 0
    ? (m.total_return_pct < 0
        ? '回測結果：策略仍為虧損，但跌幅小於買入持有'
        : '回測結果：策略報酬高於買入持有')
    : returnGap < 0
      ? '回測結果：策略報酬低於買入持有'
      : '回測結果：策略報酬與買入持有相同'

  const comparison = returnGap === 0
    ? '策略與買入持有的歷史報酬相同'
    : `策略報酬較買入持有${returnGap > 0 ? '高' : '低'}約 ${gapAbs} 個百分點`

  const evidence = []
  if (oosReturn != null) evidence.push(`後段 40% 固定規則報酬 ${fmtPct(oosReturn)}`)
  if (randomPercentile != null) evidence.push(`隨機進場比較位於第 ${randomPercentile} 百分位`)

  return (
    <div className={`backtest-verdict ${returnGap > 0 && m.total_return_pct >= 0 ? 'good' : 'warn'}`}>
      <div className="verdict-head">
        {headline}
      </div>
      <p className="verdict-body">
        {period} 共進出場 <b>{m.total_trades}</b> 次：策略總報酬 <b>{fmtPct(m.total_return_pct)}</b>、
        買入持有 <b>{fmtPct(m.buy_hold_return_pct)}</b>，{comparison}。
        最大回撤（從高點最多跌幅）策略 <b>{fmtPct(m.max_drawdown_pct)}</b>、買入持有 {fmtPct(m.buy_hold_max_drawdown_pct)}，
        代表策略的歷史峰值至谷底跌幅{ddEqual ? '相同' : ddBetter ? '較小' : '較大'}。
      </p>
      {evidence.length > 0 && (
        <p className="verdict-note"><b>穩定性／基準摘要：</b>{evidence.join('；')}。</p>
      )}
      <p className="verdict-note">※ 這是已扣手續費與滑價的「歷史模擬」，訊號採日線波段，過去績效不代表未來。</p>
    </div>
  )
}

// 買賣點規則 + 三基準比較 + 驗證方法白話說明
// 目的：讓決策者分得出「賺錢是選時的功勞，還是市場本來就在漲」，且每一步可稽核
function MethodologySection({ data, hideRules = false }) {
  const m = data?.metrics
  if (!m || m.error) return null
  const rb  = data.random_baseline           // 舊版後端無此欄位 → 優雅降級
  const pct = rb?.strategy_percentile

  let verdict = null
  if (pct != null) {
    if (pct >= 95)      verdict = { cls: 'good', text: `策略總報酬位於隨機進場的第 ${pct} 百分位；此歷史樣本中的排名明顯偏高，但交易筆數與單一市場區間仍限制推論。` }
    else if (pct >= 75) verdict = { cls: 'mid',  text: `策略總報酬位於隨機進場的第 ${pct} 百分位；歷史排名偏高，但證據仍有限。` }
    else if (pct >= 40) verdict = { cls: 'warn', text: `策略總報酬位於隨機進場的第 ${pct} 百分位；結果接近中段，尚未呈現明確選時優勢。` }
    else                verdict = { cls: 'warn', text: `策略總報酬位於隨機進場的第 ${pct} 百分位；此歷史樣本中的排名偏低。` }
  }

  return (
    <div className="mini-table-wrap methodology">
      <div className="key-chart-title">
        買賣點規則與比較方法
        <Info text="把買賣規則、比較基準、驗證方法攤開講清楚：賺錢要分得出是「選時機的功勞」還是「市場本來就在漲」。" />
      </div>

      {/* 買賣點規則（白話、與 src/backtest.py 的實際邏輯一字一句對齊）。
          hideRules：併入「買賣策略」面板時，規則已在上方「進出場規則」講過，這裡不重複。 */}
      {!hideRules && (
        <div className="method-rules">
          <div><b>買點</b>：6 因子技術分數 ≥65（技術狀態轉為偏多）→ <b>隔天開盤</b>買入</div>
          <div><b>賣點</b>（先到先賣）：當日跌到停損價／漲到停利價 → 以觸發價賣出；訊號翻空（分數 ≤35）→ 隔天開盤賣出</div>
          <div><b>成本</b>：每筆買賣皆已扣手續費與滑價（雙邊）</div>
          <div className="method-rules-more">完整的 6 因子計分明細與「這顆幣現在幾分」，見上方「進出場規則」。</div>
        </div>
      )}

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
        <li>時間切段穩定性：把相同固定規則分別套在前 60% 與後 40% 資料，比較不同時期是否一致；這不是獨立模型驗證。</li>
        <li>隨機基準用固定亂數種子：任何人重算，數字完全相同（可重現＝可稽核）。</li>
        <li>誠實局限：共 {m.total_trades} 筆交易、樣本有限；「參數探索 Top 5」屬事後挑最好、直接採用會偏樂觀；過去績效不代表未來。</li>
      </ul>
    </div>
  )
}

// 回測資料與參數由父層(App)集中管理,面板為受控元件:
//   - 與 K 線買賣標記共用同一份回測(不再各抓一次)
//   - 調整停損/停利時,K 線上的箭頭會跟著一起變
// 手續費/滑價不再開放調整(後台用合理預設值計算,結果仍有扣成本);只留停損/停利供輸入。
// hideParams：併入「買賣策略」面板後,停損/停利輸入已移到上方「出場規則」,這裡不再重複顯示。
export default function BacktestPanel({ data, loading, params, onParamsChange, hideParams = false }) {
  const [showDetail, setShowDetail] = useState(false)   // 交易明細預設收起
  const [showValidation, setShowValidation] = useState(false)   // 前後期穩定性／參數探索深水區，預設收起
  const panelId = useId()
  const validationDetailsId = `${panelId}-validation-details`
  const tradeDetailsId = `${panelId}-trade-details`

  const m = data?.metrics
  // beatsHold=true 表示策略報酬 > 單純買入持有，用來決定顯示綠色還是警告色
  const beatsHold = m && m.total_return_pct > m.buy_hold_return_pct
  // 報酬差使用百分點，避免把兩個百分率相減後仍誤稱為百分比。
  const diff = m ? m.total_return_pct - m.buy_hold_return_pct : null
  const comparisonClass = beatsHold && m.total_return_pct >= 0
    ? 'key-good'
    : beatsHold ? 'key-neutral' : 'key-warn'

  return (
    <section className="backtest-section">
      {/* 標題列（併入「買賣策略」面板時改標題、且不重複顯示停損停利——那已移到上方出場規則）*/}
      <div className="backtest-header">
        <div>
          <h2 className="section-title">{hideParams ? '回測驗證：這樣進出過去會賺多少 / 賠多少' : '策略回測'}</h2>
          <p className="section-subtitle">
            {hideParams
              ? '用你在上方設定的停損／停利，回測過去 5 年依訊號買賣的假設績效'
              : '模擬過去 5 年依訊號買賣的假設績效'}
          </p>
        </div>
        {!hideParams && (
          <div className="param-col">
            <div className="param-row">
              <label>停損<Info text="跌幅達多少就認賠出場，保護本金。可輸入 1~30；例如 6 = 買進後跌 6% 就賣。" />
                <PctInput
                  value={Math.round(Math.abs(params.stopLoss) * 100)} sign="-" min={1} max={30}
                  onCommit={pct => onParamsChange({ stopLoss: -pct / 100 })}
                />
              </label>
              <label>停利<Info text="漲幅達多少就獲利了結。可輸入 5~100；例如 20 = 買進後漲 20% 就賣。" />
                <PctInput
                  value={Math.round(params.takeProfit * 100)} sign="+" min={5} max={100}
                  onCommit={pct => onParamsChange({ takeProfit: pct / 100 })}
                />
              </label>
            </div>
          </div>
        )}
      </div>

      {loading && (
        <div className="bt-skeleton" role="status" aria-live="polite" aria-label="回測計算中">
          <div className="skeleton" style={{ height: 62, borderRadius: 10 }} />
          <div className="key-metrics">
            <div className="skeleton" style={{ height: 92, borderRadius: 12 }} />
            <div className="skeleton" style={{ height: 92, borderRadius: 12 }} />
            <div className="skeleton" style={{ height: 92, borderRadius: 12 }} />
          </div>
          <div className="skeleton" style={{ height: 180, borderRadius: 8 }} />
        </div>
      )}

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
            <div className={`key-metric ${comparisonClass}`}>
              <div className="key-metric-top">
                <span className="key-metric-label">策略報酬</span>
                <span className="key-metric-badge">
                  {diff === 0
                    ? '與持有報酬相同'
                    : `較持有${diff > 0 ? '高' : '低'} ${Math.abs(diff).toFixed(1)} 個百分點`}
                </span>
              </div>
              <div className="key-metric-value">
                {m.total_return_pct >= 0 ? '+' : ''}{m.total_return_pct}%
              </div>
              <div className="key-metric-compare">
                買入持有 {fmtPct(m.buy_hold_return_pct)}，報酬差 {diff >= 0 ? '+' : ''}{diff.toFixed(1)} 個百分點
                <Info text="報酬差＝策略報酬率－買入持有報酬率，單位是百分點。正值只代表歷史報酬較高；若兩者都虧損，策略仍然是虧損。" />
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
              {/* 夏普原本在這裡以 4 位小數再講一次（0.0777），與下方「風險調整後的對照」
                  的 0.08 上下相鄰、格式還不同。夏普改為只在下方講一次。 */}
              <div className="key-metric-compare">
                策略回撤 vs 持有回撤 {fmtPct(m.buy_hold_max_drawdown_pct)}
              </div>
            </div>
          </div>

          <RiskReality m={m} />

          {/* 三基準比較（買入持有／隨機進場）+ 前後期穩定性 + 參數探索 = 回測「深水區」。
              併入「買賣策略」面板時預設收起（規則已在上方講過，這裡 hideRules 不重複）；
              單獨使用時維持全部攤開。 */}
          {hideParams ? (
            <>
              <button
                className="detail-toggle"
                onClick={() => setShowValidation(v => !v)}
                aria-expanded={showValidation}
                aria-controls={validationDetailsId}
              >
                {showValidation
                  ? '▲ 收起完整回測驗證'
                  : '▼ 展開完整回測驗證（三基準比較・前後期穩定性・參數探索）'}
              </button>
              {showValidation && (
                <div id={validationDetailsId}>
                  <MethodologySection data={data} hideRules />
                  <div className="backtest-grid">
                    <ValidationTable validation={data.validation} />
                    <SweepTable rows={data.parameter_sweep} />
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <MethodologySection data={data} />
              <div className="backtest-grid">
                <ValidationTable validation={data.validation} />
                <SweepTable rows={data.parameter_sweep} />
              </div>
            </>
          )}

          {/* 資產曲線 */}
          <div style={{ marginTop: 16 }}>
            <div className="key-chart-title">
              每日權益曲線：策略 vs 買入持有（依完成日線盯市，1.0 = 本金）
            </div>
            <EquityCurve data={data.equity_curve} />
          </div>

          {/* 展開更多 */}
          <button
            className="detail-toggle"
            onClick={() => setShowDetail(v => !v)}
            aria-expanded={showDetail}
            aria-controls={tradeDetailsId}
          >
            {showDetail ? '▲ 收起交易明細' : `▼ 查看交易記錄（全部 ${data.recent_trades?.length ?? 0} 筆，點列看完整明細）`}
          </button>
          {showDetail && <div id={tradeDetailsId}><TradeTable trades={data.recent_trades} /></div>}
        </>
      )}
    </section>
  )
}
