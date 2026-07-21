import { useEffect, useState } from 'react'
import { fetchForecast } from '../api/client'

const HORIZONS = [1, 5, 10]

const REGIME_LABELS = {
  bull: '偏多趨勢',
  bear: '偏空趨勢',
  sideways: '區間盤整',
  neutral: '方向中性',
  unknown: '狀態未明',
}

const RECOMMENDATION_LABELS = {
  research_watch_upside: '研究模型偏多',
  research_watch_downside: '研究模型偏空',
  wait: '等待更多證據',
}

function numberOrNull(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function probabilityPct(value) {
  const number = numberOrNull(value)
  if (number == null) return null
  return Math.abs(number) <= 1 ? number * 100 : number
}

function flatQuantile(raw, key) {
  const explicitPct = numberOrNull(raw?.[`${key}_pct`])
  if (explicitPct != null) return explicitPct
  const value = numberOrNull(raw?.[key])
  if (value == null) return null
  return raw?.return_unit === 'pct' || raw?.quantile_unit === 'pct'
    ? value
    : (Math.abs(value) <= 1 ? value * 100 : value)
}

function normalizeEvidence(items) {
  if (!Array.isArray(items)) return []
  return items.map((item, index) => {
    if (typeof item === 'string') return { id: `${index}-${item}`, label: item, detail: '' }
    const label = item?.label ?? item?.title ?? item?.feature ?? item?.name ?? '模型證據'
    const detail = item?.detail ?? item?.reason ?? item?.description ?? item?.value ?? ''
    return { id: item?.id ?? `${index}-${label}`, label: String(label), detail: String(detail) }
  })
}

function normalizeForecast(payload, requestedHorizon) {
  const raw = payload?.forecast ?? payload ?? {}
  const probabilities = raw.probabilities ?? {}
  const quantiles = raw.return_quantiles_pct ?? raw.return_quantiles ?? {}
  const downside = raw.downside_risk ?? {}
  const evidence = raw.evidence ?? {}
  const quality = raw.data_quality ?? {}
  const confidenceObject = typeof raw.confidence === 'object' && raw.confidence !== null
    ? raw.confidence
    : {}
  const confidenceScore = numberOrNull(
    confidenceObject.score ?? raw.confidence_score ?? (
      typeof raw.confidence === 'number' ? raw.confidence : null
    ),
  )

  return {
    symbol: raw.symbol,
    horizon: numberOrNull(raw.horizon_days ?? raw.horizon) ?? requestedHorizon,
    status: String(raw.status ?? 'unknown').toLowerCase(),
    research: raw.research !== false,
    asOf: raw.as_of ?? raw.data_as_of ?? null,
    generatedAt: raw.generated_at ?? null,
    modelVersion: raw.model_version ?? '—',
    regime: String(raw.regime ?? 'unknown').toLowerCase(),
    confidenceScore,
    confidenceLevel: String(confidenceObject.level ?? raw.confidence_level ?? '').toLowerCase(),
    recommendation: raw.recommendation ?? null,
    abstainReason: raw.abstain_reason ?? null,
    pUp: probabilityPct(probabilities.up ?? raw.p_up),
    pDown: probabilityPct(probabilities.down ?? raw.p_down),
    q10: numberOrNull(quantiles.q10) ?? flatQuantile(raw, 'q10'),
    q50: numberOrNull(quantiles.q50) ?? flatQuantile(raw, 'q50'),
    q90: numberOrNull(quantiles.q90) ?? flatQuantile(raw, 'q90'),
    downsideThreshold: numberOrNull(downside.threshold_pct ?? raw.downside_threshold_pct),
    downsideProbability: probabilityPct(downside.probability ?? raw.downside_risk_probability ?? raw.drawdown_probability),
    supports: normalizeEvidence(evidence.for ?? evidence.supporting ?? raw.supporting_evidence),
    concerns: normalizeEvidence(evidence.against ?? evidence.opposing ?? raw.opposing_evidence),
    stale: Boolean(quality.stale ?? raw.stale),
    observations: numberOrNull(quality.observations ?? raw.observations),
  }
}

function pct(value, { signed = false } = {}) {
  if (value == null) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(1)}%`
}

function formatTime(value) {
  if (!value) return '—'
  // A daily candle's as_of value is a calendar date, not midnight UTC.
  // Rendering it through Date would misleadingly display 08:00 in Taiwan.
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

function stateOf(forecast) {
  if (forecast.stale) {
    return { kind: 'stale', title: '資料已過期，暫停解讀', note: '等待資料更新後重新產生預測。' }
  }
  if (forecast.status === 'insufficient' || forecast.status === 'insufficient_data') {
    return { kind: 'insufficient', title: '資料不足，無法形成預測', note: forecast.abstainReason || '累積足夠樣本後會自動重試。' }
  }
  if (forecast.status !== 'ready' || forecast.abstainReason) {
    return { kind: 'abstain', title: '模型選擇不判斷', note: forecast.abstainReason || '目前證據不足或模型分歧過大。' }
  }
  return { kind: 'ready', title: RECOMMENDATION_LABELS[forecast.recommendation] || '研究預測已產生', note: '請搭配反對證據與風險區間判讀。' }
}

function StateMessage({ kind, title, note }) {
  return (
    <div className={`forecast-state forecast-state-${kind}`} role="status">
      <strong>{title}</strong>
      <span>{note}</span>
    </div>
  )
}

function EvidenceList({ title, tone, items }) {
  return (
    <div className={`forecast-evidence forecast-evidence-${tone}`}>
      <h4>{title}</h4>
      {items.length ? (
        <ul>
          {items.map(item => (
            <li key={item.id}>
              <span>{item.label}</span>
              {item.detail && <small>{item.detail}</small>}
            </li>
          ))}
        </ul>
      ) : <p>目前沒有足夠證據。</p>}
    </div>
  )
}

export default function ForecastDecisionCard({ symbol, refreshKey = '' }) {
  const [horizon, setHorizon] = useState(5)
  const [retry, setRetry] = useState(0)
  const [result, setResult] = useState({ key: '', data: null, error: null })
  const requestKey = `${symbol}:${horizon}:${refreshKey}:${retry}`

  useEffect(() => {
    if (!symbol) return undefined
    const controller = new AbortController()
    let active = true

    fetchForecast(symbol, horizon, { signal: controller.signal })
      .then(data => {
        if (active) setResult({ key: requestKey, data, error: null })
      })
      .catch(error => {
        if (active && error?.name !== 'AbortError') {
          setResult({ key: requestKey, data: null, error })
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [symbol, horizon, refreshKey, retry, requestKey])

  const current = result.key === requestKey ? result : null
  const forecast = current?.data ? normalizeForecast(current.data, horizon) : null
  const forecastState = forecast ? stateOf(forecast) : null
  const confidenceLabel = forecast?.confidenceLevel
    ? ({ low: '低', medium: '中', high: '高' }[forecast.confidenceLevel] ?? forecast.confidenceLevel)
    : null

  return (
    <section className="forecast-card" aria-labelledby="forecast-card-title">
      <header className="forecast-head">
        <div>
          <div className="forecast-title-row">
            <h2 id="forecast-card-title">未來情境預測</h2>
            <span className="forecast-research-badge">研究模式 · 非交易建議</span>
          </div>
          <p>以封存資料估計方向機率與可能區間；沒有足夠優勢時，模型會拒絕判斷。</p>
        </div>
        <div className="forecast-tabs" role="tablist" aria-label="預測期限">
          {HORIZONS.map(days => (
            <button
              key={days}
              type="button"
              role="tab"
              aria-selected={horizon === days}
              className={horizon === days ? 'active' : ''}
              onClick={() => setHorizon(days)}
            >
              {days} 日
            </button>
          ))}
        </div>
      </header>

      {!current && (
        <div className="forecast-loading" role="status" aria-live="polite">
          <span className="forecast-spinner" aria-hidden="true" />
          正在載入 {horizon} 日研究預測…
        </div>
      )}

      {current?.error && (
        <div className="forecast-error" role="alert">
          <div>
            <strong>預測服務暫時無法取得</strong>
            <span>其他市場資料仍可查看；此區不會沿用上一筆結果。</span>
          </div>
          <button type="button" onClick={() => setRetry(value => value + 1)}>重新載入</button>
        </div>
      )}

      {forecast && forecastState && (
        <div className="forecast-content">
          <StateMessage {...forecastState} />

          <div className="forecast-metrics" aria-label={`${forecast.horizon} 日預測數據`}>
            <div className="forecast-metric forecast-metric-up">
              <span>上漲機率</span>
              <strong>{pct(forecast.pUp)}</strong>
            </div>
            <div className="forecast-metric forecast-metric-down">
              <span>下跌機率</span>
              <strong>{pct(forecast.pDown)}</strong>
            </div>
            <div className="forecast-metric">
              <span>下行風險</span>
              <strong>{pct(forecast.downsideProbability)}</strong>
              <small>{forecast.downsideThreshold == null ? '門檻未提供' : `跌幅 ≤ ${pct(forecast.downsideThreshold)}`}</small>
            </div>
            <div className="forecast-metric">
              <span>模型信心</span>
              <strong>{forecast.confidenceScore == null ? '—' : `${forecast.confidenceScore.toFixed(0)}/100`}</strong>
              {confidenceLabel && <small>{confidenceLabel}信心</small>}
            </div>
          </div>

          <div className="forecast-range" aria-label="預測報酬區間">
            <div className="forecast-range-head">
              <h3>{forecast.horizon} 日報酬情境</h3>
              <span>{REGIME_LABELS[forecast.regime] ?? forecast.regime}</span>
            </div>
            <div className="forecast-range-values">
              <div><span>悲觀 q10</span><strong>{pct(forecast.q10, { signed: true })}</strong></div>
              <div><span>中位 q50</span><strong>{pct(forecast.q50, { signed: true })}</strong></div>
              <div><span>樂觀 q90</span><strong>{pct(forecast.q90, { signed: true })}</strong></div>
            </div>
          </div>

          <div className="forecast-evidence-grid">
            <EvidenceList title="支持證據" tone="for" items={forecast.supports} />
            <EvidenceList title="反對證據" tone="against" items={forecast.concerns} />
          </div>

          <footer className="forecast-meta">
            <span>模型：{forecast.modelVersion}</span>
            <span>資料截至：{formatTime(forecast.asOf)}</span>
            <span>產生時間：{formatTime(forecast.generatedAt)}</span>
            {forecast.observations != null && <span>樣本：{forecast.observations.toLocaleString()} 筆</span>}
          </footer>
        </div>
      )}
    </section>
  )
}
