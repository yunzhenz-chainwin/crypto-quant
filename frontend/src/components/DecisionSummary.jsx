import { FORECAST_HORIZONS, stateOfForecast } from '../lib/forecastViewModel'

const MIN_HISTORY_TRADES = 20
const MIN_OOS_TRADES = 8

function finiteNumber(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function signedPct(value) {
  if (value == null) return '未提供'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function forecastGate(forecast) {
  const state = stateOfForecast(forecast)
  const sampleText = forecast.observations == null
    ? '可用日線樣本數未提供'
    : `可用日線 ${forecast.observations.toLocaleString()} 根`

  if (state.kind !== 'ready') {
    return {
      kind: state.kind,
      label: state.title,
      detail: `${state.note}；${sampleText}。`,
      direction: null,
    }
  }

  let direction = null
  if (forecast.recommendation === 'research_watch_upside') direction = 'up'
  else if (forecast.recommendation === 'research_watch_downside') direction = 'down'
  else if (forecast.pUp != null && forecast.pDown != null && forecast.pUp !== forecast.pDown) {
    direction = forecast.pUp > forecast.pDown ? 'up' : 'down'
  }

  const directionLabel = direction === 'up' ? '研究預測偏多'
    : direction === 'down' ? '研究預測偏空'
      : '研究預測方向未明'
  const probability = direction === 'up' ? forecast.pUp : direction === 'down' ? forecast.pDown : null
  const detail = [
    probability == null ? null : `類似歷史情境${direction === 'up' ? '上漲' : '下跌'}比例 ${probability.toFixed(1)}%`,
    forecast.confidenceScore == null
      ? '證據充分度未提供'
      : `證據充分度 ${forecast.confidenceScore.toFixed(0)}/100（門檻 ${forecast.confidenceThreshold.toFixed(0)}）`,
    sampleText,
  ].filter(Boolean).join('；')

  return { kind: 'ready', label: directionLabel, detail: `${detail}。`, direction }
}

function technicalState(signal) {
  if (!signal) return { label: '技術狀態載入中', detail: '等待六項技術因子資料。', direction: null }
  const score = finiteNumber(signal.score)
  const scoreText = score == null ? '' : `（${score.toFixed(0)} 分）`
  if (signal.signal === 'BULL') return { label: `技術偏多${scoreText}`, detail: '描述目前技術因子，不是未來報酬預測。', direction: 'up' }
  if (signal.signal === 'BEAR') return { label: `技術偏空${scoreText}`, detail: '描述目前技術因子，不是未來報酬預測。', direction: 'down' }
  return { label: `技術中性${scoreText}`, detail: '目前技術因子沒有形成一致方向。', direction: null }
}

function backtestState(backtest, status) {
  if (status === 'loading') {
    return { kind: 'loading', label: '歷史策略品質計算中', detail: '全期、OOS 時段與交易樣本尚未確認。' }
  }
  if (status === 'error') {
    return { kind: 'error', label: '歷史策略品質無法取得', detail: '未沿用上一個幣種或參數的回測結果。' }
  }

  const metrics = backtest?.metrics
  if (!metrics || metrics.error) {
    return { kind: 'limited', label: '歷史策略品質不可用', detail: '目前沒有可用的回測指標。' }
  }

  const totalReturn = finiteNumber(metrics.total_return_pct)
  const buyHoldReturn = finiteNumber(metrics.buy_hold_return_pct)
  const reportedExcess = finiteNumber(metrics.excess_return_pct)
  const excessReturn = reportedExcess ?? (
    totalReturn != null && buyHoldReturn != null ? totalReturn - buyHoldReturn : null
  )
  const trades = finiteNumber(metrics.total_trades)
  if (totalReturn == null || buyHoldReturn == null || excessReturn == null || trades == null) {
    return {
      kind: 'limited',
      label: '歷史策略品質資料不完整',
      detail: '總報酬、買入持有基準、超額報酬或交易筆數至少一項未提供。',
    }
  }

  const oosMetrics = backtest?.validation?.out_of_sample?.metrics
  const oosReturn = finiteNumber(oosMetrics?.total_return_pct)
  const oosBuyHold = finiteNumber(oosMetrics?.buy_hold_return_pct)
  const oosReportedExcess = finiteNumber(oosMetrics?.excess_return_pct)
  const oosExcess = oosReportedExcess ?? (
    oosReturn != null && oosBuyHold != null ? oosReturn - oosBuyHold : null
  )
  const oosTrades = finiteNumber(oosMetrics?.total_trades)
  const oosAvailable = oosReturn != null && oosBuyHold != null && oosExcess != null && oosTrades != null
  const enoughTrades = trades >= MIN_HISTORY_TRADES
  const enoughOosTrades = oosAvailable && oosTrades >= MIN_OOS_TRADES
  const period = backtest?.period?.start && backtest?.period?.end
    ? `全期 ${backtest.period.start}～${backtest.period.end}`
    : '全期日期未提供'
  const sampleText = enoughTrades
    ? `交易樣本可用：${trades.toFixed(0)} 筆`
    : `交易樣本有限：${trades.toFixed(0)} 筆（低於 ${MIN_HISTORY_TRADES} 筆）`
  const oosText = oosAvailable
    ? `後段 40%（OOS 時段）報酬 ${signedPct(oosReturn)}、相對持有 ${signedPct(oosExcess)}、${oosTrades.toFixed(0)} 筆交易`
    : '後段 40%（OOS 時段）指標不完整'
  const detail = `${period}：策略 ${signedPct(totalReturn)}、買入持有 ${signedPct(buyHoldReturn)}、相對持有 ${signedPct(excessReturn)}；${sampleText}；${oosText}。歷史結果不代表未來。`

  if (totalReturn < 0) {
    return { kind: 'weak', label: '歷史策略為負報酬', detail }
  }
  if (totalReturn === 0) {
    return { kind: 'weak', label: '歷史策略未產生正報酬', detail }
  }
  if (!enoughTrades) {
    return { kind: 'limited', label: '歷史策略有正報酬，但交易樣本有限', detail }
  }
  if (!oosAvailable) {
    return { kind: 'limited', label: '歷史策略有正報酬，但缺少可用 OOS 指標', detail }
  }
  if (!enoughOosTrades) {
    return {
      kind: 'limited',
      label: '歷史策略有正報酬，但 OOS 交易樣本有限',
      detail: `${detail} OOS 至少需要 ${MIN_OOS_TRADES} 筆交易才列為較有利。`,
    }
  }
  if (oosReturn <= 0) {
    return { kind: 'weak', label: '全期有正報酬，但 OOS 時段為非正報酬', detail }
  }
  if (excessReturn <= 0 || oosExcess <= 0) {
    return { kind: 'limited', label: '歷史策略有正報酬，但未穩定優於持有', detail }
  }
  return { kind: 'favorable', label: '歷史策略品質較有利', detail }
}

function historyContext(history) {
  if (history.kind === 'favorable') return '歷史策略品質較有利，但它只描述策略可靠度，不是第三個方向訊號。'
  if (history.kind === 'weak') return `${history.label}，不能把方向一致升級為成功或買賣訊號。`
  return `${history.label}，目前只能視為有限的可靠度背景。`
}

function combinedJudgement(technical, gate, history) {
  if (gate.kind === 'stale') {
    return {
      kind: 'stale',
      label: '預測資料過期，暫不整合方向',
      detail: `技術方向仍可查看，但研究預測不能納入目前判斷。${historyContext(history)}`,
      next: '等待最新日線完成並重新產生研究快照，再比較技術方向與預測方向。',
    }
  }
  if (gate.kind === 'insufficient' || gate.kind === 'abstain') {
    return {
      kind: 'insufficient',
      label: '研究預測未通過門檻，暫不整合方向',
      detail: `不把目前技術偏向當成未來方向。${historyContext(history)}`,
      next: '等待樣本、方向優勢與證據充分度通過門檻；歷史策略品質只用來評估可靠度。',
    }
  }
  if (!technical.direction || !gate.direction) {
    return {
      kind: 'insufficient',
      label: '技術或預測方向未明',
      detail: `目前缺少兩個可比較方向。${historyContext(history)}`,
      next: '等待技術狀態與研究預測都形成方向，再判斷兩者是否一致。',
    }
  }
  if (technical.direction !== gate.direction) {
    return {
      kind: 'conflict',
      label: '技術方向與預測方向衝突',
      detail: `兩個方向來源相反，不形成單一方向結論。${historyContext(history)}`,
      next: '等待後續資料讓技術方向與研究預測重新收斂；另行檢查歷史策略品質是否改善。',
    }
  }
  return {
    kind: history.kind === 'favorable' ? 'aligned' : 'caution',
    label: history.kind === 'favorable'
      ? '技術方向與研究預測一致'
      : history.kind === 'weak'
        ? '技術與預測方向一致，但歷史策略品質偏弱'
        : '技術與預測方向一致，但歷史品質證據有限',
    detail: `一致只代表兩個方向來源同向。${historyContext(history)}`,
    next: '觀察下一次資料更新後兩個方向是否維持，並同步檢查下行情境、反對證據與 OOS 品質。',
  }
}

function EvidenceBlock({ title, label, detail }) {
  return (
    <div className="forecast-evidence" style={{ minHeight: 104 }}>
      <h4 style={{ color: 'var(--text)' }}>{title}</h4>
      <strong style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>{label}</strong>
      <p style={{ lineHeight: 1.55 }}>{detail}</p>
    </div>
  )
}

export default function DecisionSummary({
  signal,
  backtest,
  backtestStatus = 'idle',
  horizon,
  onHorizonChange,
  forecast,
  loading,
  error,
  onRetry,
}) {
  const gate = forecast ? forecastGate(forecast) : null
  const technical = technicalState(signal)
  const historical = backtestState(backtest, backtestStatus)
  const judgement = gate ? combinedJudgement(technical, gate, historical) : null
  const stateClass = judgement?.kind === 'aligned' ? 'forecast-state-ready'
    : judgement?.kind === 'conflict' || judgement?.kind === 'stale' ? 'forecast-state-stale'
      : 'forecast-state-insufficient'

  return (
    <section className="forecast-card" aria-labelledby="decision-summary-title">
      <header className="forecast-head">
        <div>
          <div className="forecast-title-row">
            <h2 id="decision-summary-title">統一判斷摘要</h2>
            <span className="forecast-research-badge">輔助判讀 · 不提供買賣指令</span>
          </div>
          <p>技術方向、研究預測方向與歷史策略品質分開呈現；回測品質不會被當成第三個方向投票。</p>
        </div>
        <div className="forecast-tabs" role="group" aria-label="摘要預測期限">
          {FORECAST_HORIZONS.map(days => (
            <button
              key={days}
              type="button"
              aria-pressed={horizon === days}
              className={horizon === days ? 'active' : ''}
              onClick={() => onHorizonChange(days)}
            >
              {days} 日
            </button>
          ))}
        </div>
      </header>

      {loading && (
        <div className="forecast-loading" role="status" aria-live="polite">
          <span className="forecast-spinner" aria-hidden="true" />
          正在整合 {horizon} 日判斷依據…
        </div>
      )}

      {error && (
        <div className="forecast-error" role="alert">
          <div>
            <strong>統一摘要暫時無法取得研究預測</strong>
            <span>技術狀態與回測仍可查看，但目前不形成整合結論。</span>
          </div>
          <button type="button" onClick={onRetry}>重新載入</button>
        </div>
      )}

      {gate && judgement && (
        <div className="forecast-content">
          <div className={`forecast-state ${stateClass}`} role="status">
            <strong>{judgement.label}</strong>
            <span>{judgement.detail}</span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 9 }}>
            <EvidenceBlock title="① 當前技術方向" label={technical.label} detail={technical.detail} />
            <EvidenceBlock title={`② ${horizon} 日研究預測方向`} label={gate.label} detail={gate.detail} />
            <EvidenceBlock title="③ 歷史策略品質" label={historical.label} detail={historical.detail} />
          </div>

          <div className="forecast-range">
            <div className="forecast-range-head" style={{ marginBottom: 4 }}>
              <h3>下一步觀察條件</h3>
              <span>不是進出場條件</span>
            </div>
            <p style={{ color: 'var(--text)', fontSize: 12, lineHeight: 1.6 }}>{judgement.next}</p>
          </div>
        </div>
      )}
    </section>
  )
}
