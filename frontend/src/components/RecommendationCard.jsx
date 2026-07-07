/**
 * RecommendationCard.jsx — 買賣策略「綜合建議」結論卡（可單獨放圖片右側欄位）
 *
 * 訊號(現在分數) × 回測(這訊號在本幣的歷史依據) 融成一個結論：該不該做、
 * 做了預期賺賠、風險多大。回測當訊號的「可信度把關」——多數幣回測是輸的，
 * 卡片就會誠實說「依據薄弱／避開」，而不是一味喊進場。
 *
 * 已把「信心分數量表」併進來（原本獨立的信心分數卡移除，兩者不再重複顯示 72）；
 * 卡片底部兩個連結 onDetail('score'|'backtest') → 開計分明細 / 回測驗證彈窗。
 */
import { ScoreGauge } from './HeroSignal'
const fmtPct1 = (v) =>
  (v == null || Number.isNaN(Number(v))) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`

// 回測可信度：把「這套訊號在本幣過去到底靈不靈」評成 高/中/低——當作訊號的把關。
// 依據：是否贏過買入持有(主)、樣本外是否也贏(穩健)、贏過多少隨機進場(非運氣)、樣本數。
function assessCredibility(m, rb, oos) {
  if (!m || m.error || m.excess_return_pct == null) return null
  const excess = m.excess_return_pct
  const beatHold = excess > 0
  const oosBeat = (oos && oos.total_return_pct != null && oos.buy_hold_return_pct != null)
    ? oos.total_return_pct > oos.buy_hold_return_pct : null
  const pct = rb?.strategy_percentile
  const enough = (m.total_trades ?? 0) >= 20

  const parts = []
  parts.push(beatHold
    ? `過去 ${m.total_trades} 筆贏過買入持有（超額 ${fmtPct1(excess)}）`
    : `過去 ${m.total_trades} 筆輸給買入持有（超額 ${fmtPct1(excess)}）`)
  // 樣本外只在「與全期一致」時才提，避免「輸大盤…樣本外也贏」這種混淆訊息
  if (beatHold && oosBeat === true) parts.push('樣本外也贏')
  else if (!beatHold && oosBeat === false) parts.push('樣本外也輸')
  if (beatHold && pct != null) parts.push(`贏過 ${Math.round(pct)}% 隨機進場`)   // 只在贏過大盤時才提隨機檢定

  let level
  if (!beatHold) level = 'low'
  else if (enough && (oosBeat === true || (pct != null && pct >= 75))) level = 'high'
  else level = 'mid'
  const label = { high: '依據中上', mid: '依據普通', low: '依據薄弱' }[level]
  const color = { high: '#22c55e', mid: '#f59e0b', low: '#ef4444' }[level]
  return { level, label, color, why: parts.join('、') }
}

export default function RecommendationCard({ signal, backtest, params, onDetail }) {
  const score = signal?.score
  if (score == null) return null
  const m = backtest?.metrics
  const cred = assessCredibility(m, backtest?.random_baseline, backtest?.validation?.out_of_sample?.metrics)

  const stage = score >= 65 ? 'enter' : score <= 35 ? 'exit' : 'wait'
  const stanceZh = score >= 65 ? '偏多' : score <= 35 ? '偏空' : '中立'
  const stageNote = stage === 'enter' ? '已達進場門檻（≥65）'
    : stage === 'exit' ? '已轉偏空（≤35）'
    : `未達進場門檻（需 ≥65，還差 ${65 - score} 分）`

  // 綜合結論：進場訊號 × 回測可信度
  let verdict
  if (stage === 'enter') {
    verdict = cred?.level === 'low'
      ? { color: '#f59e0b', title: '訊號偏多，但這訊號在本幣依據薄弱 → 謹慎、暫不建議追進' }
      : { color: '#22c55e', title: '可考慮進場（訊號偏多，且有回測依據）' }
  } else if (stage === 'exit') {
    verdict = { color: '#ef4444', title: '偏空 → 避開；持有中則留意出場' }
  } else {
    verdict = { color: '#94a3b8', title: `觀望——未達進場點（分數需 ≥65，現在 ${score} 分）` }
  }

  const stopPct = params ? `-${Math.round(Math.abs(params.stopLoss) * 100)}%` : '—'
  const takePct = params ? `+${Math.round(params.takeProfit * 100)}%` : '—'

  return (
    <div
      className="strat-reco strat-reco-click"
      style={{ borderLeftColor: verdict.color, background: `${verdict.color}10` }}
      role="button" tabIndex={0}
      onClick={() => onDetail?.('all')}
      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onDetail?.('all')}
      title="點看計分明細與回測驗證"
    >
      <div className="strat-reco-head">
        <span className="strat-reco-eyebrow">買賣策略 · 綜合建議</span>
        {cred && (
          <span className="strat-reco-cred" style={{ color: cred.color, borderColor: `${cred.color}66` }}>
            回測可信度：{cred.label}
          </span>
        )}
      </div>

      <div className="strat-reco-verdict" style={{ color: verdict.color }}>
        <span className="strat-reco-dot" style={{ background: verdict.color }} />
        {verdict.title}
      </div>

      <div className="strat-reco-body">
        <div className="strat-reco-gauge">
          <ScoreGauge score={score} />
        </div>
        <div className="strat-reco-lines">
          <div>
            <b>訊號</b>：分數 <b style={{ color: verdict.color }}>{score}</b> · {stanceZh}，{stageNote}
          </div>
          {cred ? (
            <div>
              <b>回測</b>：{cred.why} → 這訊號在本幣<b style={{ color: cred.color }}>{cred.label}</b>
            </div>
          ) : (
            <div className="strat-reco-muted"><b>回測</b>：計算中…</div>
          )}
          {stage === 'enter' && m && !m.error && (
            <div>
              <b>若進場</b>（停損 {stopPct}／停利 {takePct}）：上檔平均賺
              <b style={{ color: '#22c55e' }}> {fmtPct1(m.avg_win_pct)}</b>、下檔
              <b style={{ color: '#ef4444' }}> {fmtPct1(m.avg_loss_pct)}</b>、
              平均持有 {Math.round(m.avg_hold_days ?? 0)} 天、最壞回撤 {fmtPct1(m.max_drawdown_pct)}
            </div>
          )}
        </div>
      </div>

      <div className="strat-reco-more">點看計分明細＋回測驗證 →</div>

      <div className="strat-reco-disc">※ 系統依規則＋歷史回測的建議，非投資建議；過去績效不代表未來。</div>
    </div>
  )
}
