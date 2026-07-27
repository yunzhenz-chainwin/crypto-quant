import { useId, useState } from 'react'
import {
  FORECAST_HORIZONS,
  REGIME_LABELS,
  stateOfForecast,
  uniqueEvidence,
} from '../lib/forecastViewModel'

function pct(value, { signed = false } = {}) {
  if (value == null) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(1)}%`
}

function formatTime(value) {
  if (!value) return '—'
  // A daily candle's as_of value is a calendar date, not midnight UTC.
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return String(value).replaceAll('-', '/')
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function StateMessage({ kind, title, note }) {
  return (
    <div className={`forecast-state forecast-state-${kind}${kind === 'abstain' ? ' forecast-state-neutral' : ''}`} role="status">
      <strong>{title}</strong>
      <span>{note}</span>
    </div>
  )
}

function EvidenceList({ title, tone, items, emptyMessage = '目前沒有相關資訊。' }) {
  const statusLabels = { passed: '通過', failed: '未通過', warning: '注意', info: '資訊' }
  return (
    <div className={`forecast-evidence forecast-evidence-${tone}`}>
      <h4>{title}</h4>
      {items.length ? (
        <ul>
          {items.map(item => (
            <li key={item.id}>
              <span>{item.label}</span>
              {(item.status || item.detail) && (
                <small className={item.status ? `forecast-evidence-status forecast-evidence-status-${item.status}` : ''}>
                  {item.status && statusLabels[item.status]}
                  {item.status && item.detail && ' · '}
                  {item.detail}
                </small>
              )}
            </li>
          ))}
        </ul>
      ) : <p>{emptyMessage}</p>}
    </div>
  )
}

function DirectionMetrics({ forecast }) {
  return (
    <div className="forecast-metrics forecast-direction-metrics" aria-label={`${forecast.horizon} 日類似歷史情境比例`}>
      <div className="forecast-metric forecast-metric-up">
        <span>類似情境上漲比例</span>
        <strong>{pct(forecast.pUp)}</strong>
      </div>
      <div className="forecast-metric forecast-metric-down">
        <span>類似情境下跌比例</span>
        <strong>{pct(forecast.pDown)}</strong>
      </div>
    </div>
  )
}

function DownsideRiskMetric({ forecast }) {
  return (
    <div className="forecast-metric forecast-risk-summary">
      <span>下行風險</span>
      <strong>{pct(forecast.downsideProbability)}</strong>
      <small>{forecast.downsideThreshold == null ? '門檻未提供' : `歷史報酬 ≤ ${pct(forecast.downsideThreshold)}`}</small>
    </div>
  )
}

function EvidenceAdequacyMetric({ forecast }) {
  return (
    <div className="forecast-metric forecast-evidence-adequacy">
      <span>證據充分度</span>
      <strong>{forecast.confidenceScore == null ? '—' : `${forecast.confidenceScore.toFixed(0)} 分`}</strong>
      <small>研究發布門檻 {forecast.confidenceThreshold.toFixed(0)} 分</small>
    </div>
  )
}

function ForecastRange({ forecast }) {
  return (
    <div className="forecast-range" aria-label="類似歷史情境報酬分位數">
      <div className="forecast-range-head">
        <h3>{forecast.horizon} 日歷史報酬分位數</h3>
        <span>{REGIME_LABELS[forecast.regime] ?? forecast.regime}</span>
      </div>
      <div className="forecast-range-values">
        <div><span>較低 q10</span><strong>{pct(forecast.q10, { signed: true })}</strong></div>
        <div><span>中位 q50</span><strong>{pct(forecast.q50, { signed: true })}</strong></div>
        <div><span>較高 q90</span><strong>{pct(forecast.q90, { signed: true })}</strong></div>
      </div>
    </div>
  )
}

function EvidenceGroups({ forecast, includeGates = true }) {
  const facts = uniqueEvidence([
    {
      id: 'market-regime',
      code: 'market_regime',
      label: '目前市場狀態',
      detail: REGIME_LABELS[forecast.regime] ?? forecast.regime,
      status: '',
      polarity: 'neutral',
      sourceBucket: 'supporting',
      category: 'observation',
    },
    ...forecast.facts,
  ])
  const nonScoreGates = forecast.releaseGates.filter(
    item => item.code !== 'confidence_release_threshold',
  )

  return (
    <div className="forecast-evidence-grid forecast-evidence-categories">
      <EvidenceList title="觀察事實" tone="facts" items={facts} emptyMessage="未提供其他觀察事實。" />
      <EvidenceList title="支持證據" tone="bullish" items={forecast.supportingEvidence} emptyMessage="目前沒有額外支持證據。" />
      <EvidenceList title="反對與風險證據" tone="risk" items={forecast.opposingEvidence} emptyMessage="目前沒有額外反對或風險證據。" />
      {includeGates && (
        <EvidenceList title="發布門檻檢查" tone="gates" items={nonScoreGates} emptyMessage="目前沒有其他未通過的發布門檻。" />
      )}
    </div>
  )
}

function handleTabKeyDown(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const tabs = Array.from(event.currentTarget.parentElement?.querySelectorAll('[role="tab"]') ?? [])
  if (!tabs.length) return
  const currentIndex = tabs.indexOf(event.currentTarget)
  let nextIndex = currentIndex
  if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
  if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = tabs.length - 1
  event.preventDefault()
  tabs[nextIndex]?.focus()
  tabs[nextIndex]?.click()
}

export default function ForecastDecisionCard({
  symbol,
  horizon,
  onHorizonChange,
  forecast,
  loading,
  error,
  onRetry,
}) {
  const instanceId = useId()
  const [expandedResearchKey, setExpandedResearchKey] = useState('')
  const tabPanelId = `${instanceId}-forecast-panel`
  const activeTabId = `${instanceId}-forecast-tab-${horizon}`
  const researchKey = `${symbol}:${horizon}:${forecast?.dataVersion ?? 'pending'}`
  const researchDetailsId = `${instanceId}-forecast-research-${horizon}`
  const forecastState = forecast ? stateOfForecast(forecast) : null
  const researchExpanded = expandedResearchKey === researchKey

  return (
    <section className="forecast-card" aria-labelledby="forecast-card-title">
      <header className="forecast-head">
        <div>
          <div className="forecast-title-row">
            <h2 id="forecast-card-title">未來情境預測</h2>
            <span className="forecast-research-badge">研究模式 · 非交易建議</span>
          </div>
          <p>以封存資料呈現類似歷史情境比例與可能區間；未通過發布門檻時不形成方向判斷。</p>
        </div>
        <div className="forecast-tabs" role="tablist" aria-label="預測期限">
          {FORECAST_HORIZONS.map(days => (
            <button
              key={days}
              type="button"
              role="tab"
              id={`${instanceId}-forecast-tab-${days}`}
              aria-selected={horizon === days}
              aria-controls={tabPanelId}
              tabIndex={horizon === days ? 0 : -1}
              className={horizon === days ? 'active' : ''}
              onClick={() => onHorizonChange(days)}
              onKeyDown={handleTabKeyDown}
            >
              {days} 日
            </button>
          ))}
        </div>
      </header>

      <div id={tabPanelId} role="tabpanel" aria-labelledby={activeTabId} className="forecast-tabpanel">
        {loading && (
          <div className="forecast-loading" role="status" aria-live="polite">
            <span className="forecast-spinner" aria-hidden="true" />
            正在載入 {horizon} 日研究預測…
          </div>
        )}

        {error && (
          <div className="forecast-error" role="alert">
            <div>
              <strong>預測服務暫時無法取得</strong>
              <span>其他市場資料仍可查看；此區不會沿用上一筆結果。</span>
            </div>
            <button type="button" onClick={onRetry}>重新載入</button>
          </div>
        )}

        {forecast && forecastState && (
          <div className="forecast-content">
            <StateMessage {...forecastState} />

            {forecastState.kind === 'abstain' && (
              <>
                <div className="forecast-evidence-grid forecast-priority-grid">
                  <EvidenceList title="發布門檻檢查" tone="gates" items={forecast.releaseGates} emptyMessage="目前沒有可辨識的門檻資訊。" />
                  <DownsideRiskMetric forecast={forecast} />
                </div>
                <button
                  type="button"
                  className="detail-toggle forecast-research-toggle"
                  aria-expanded={researchExpanded}
                  aria-controls={researchDetailsId}
                  onClick={() => setExpandedResearchKey(researchExpanded ? '' : researchKey)}
                >
                  {researchExpanded ? '▲ 收起研究細節' : '▼ 展開研究細節（類似歷史情境比例與分位數）'}
                </button>
                {researchExpanded && (
                  <div id={researchDetailsId} className="forecast-research-details forecast-content" role="region" aria-label={`${forecast.horizon} 日研究細節`}>
                    <DirectionMetrics forecast={forecast} />
                    <ForecastRange forecast={forecast} />
                    <EvidenceGroups forecast={forecast} includeGates={false} />
                  </div>
                )}
              </>
            )}

            {forecastState.kind === 'ready' && (
              <>
                <div className="forecast-metrics" aria-label={`${forecast.horizon} 日研究預測摘要`}>
                  <div className="forecast-metric forecast-metric-up"><span>類似情境上漲比例</span><strong>{pct(forecast.pUp)}</strong></div>
                  <div className="forecast-metric forecast-metric-down"><span>類似情境下跌比例</span><strong>{pct(forecast.pDown)}</strong></div>
                  <DownsideRiskMetric forecast={forecast} />
                  <EvidenceAdequacyMetric forecast={forecast} />
                </div>
                <ForecastRange forecast={forecast} />
                <EvidenceGroups forecast={forecast} />
              </>
            )}

            {(forecastState.kind === 'stale' || forecastState.kind === 'insufficient') && (
              <EvidenceList title="發布門檻檢查" tone="gates" items={forecast.releaseGates} emptyMessage="等待取得足夠且最新的資料。" />
            )}

            <footer className="forecast-meta">
              <span>模型：{forecast.modelVersion}</span>
              <span>資料截至：{formatTime(forecast.asOf)}</span>
              <span>產生時間：{formatTime(forecast.generatedAt)}</span>
              {forecast.observations != null && <span>可用日線：{forecast.observations.toLocaleString()} 根</span>}
            </footer>
          </div>
        )}
      </div>
    </section>
  )
}
