export const FORECAST_HORIZONS = [1, 5, 10]

export const REGIME_LABELS = {
  bull: '偏多趨勢',
  bear: '偏空趨勢',
  sideways: '區間盤整',
  neutral: '方向中性',
  unknown: '狀態未明',
}

const DEFAULT_EVIDENCE_THRESHOLD = 40
const INSUFFICIENT_EVIDENCE_CODES = new Set([
  'no_completed_daily_data',
  'insufficient_observations',
  'insufficient_mature_outcomes',
])

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

function nestedQuantile(raw, key) {
  const explicitPct = numberOrNull(raw?.return_quantiles_pct?.[key])
  if (explicitPct != null) return explicitPct
  const value = numberOrNull(raw?.return_quantiles?.[key])
  if (value == null) return null
  return raw?.return_unit === 'pct'
    || raw?.quantile_unit === 'pct'
    || raw?.return_quantiles_unit === 'pct'
    ? value
    : (Math.abs(value) <= 1 ? value * 100 : value)
}

function evidenceValues(value) {
  if (value == null) return []
  return Array.isArray(value) ? value : [value]
}

function normalizedStatus(item) {
  const rawStatus = String(item?.status ?? '').toLowerCase()
  if (item?.passed === true || ['pass', 'passed', 'ok'].includes(rawStatus)) return 'passed'
  if (item?.passed === false || ['fail', 'failed', 'blocked'].includes(rawStatus)) return 'failed'
  if (['warn', 'warning'].includes(rawStatus)) return 'warning'
  return rawStatus === 'info' ? 'info' : ''
}

function normalizeEvidenceItem(item, index, fallbackBucket, fallbackCategory = 'evidence') {
  if (typeof item === 'string') {
    return {
      id: `legacy-${fallbackBucket}-${index}`,
      code: `legacy_${fallbackBucket}_${index}`,
      label: item,
      detail: '',
      status: '',
      polarity: 'neutral',
      sourceBucket: fallbackBucket,
      category: fallbackCategory,
    }
  }

  const sourceBucket = item?.source_bucket === 'opposing' || item?.sourceBucket === 'opposing'
    ? 'opposing'
    : item?.source_bucket === 'supporting' || item?.sourceBucket === 'supporting'
      ? 'supporting'
      : fallbackBucket
  const label = item?.label ?? item?.title ?? item?.feature ?? item?.name ?? '模型證據'
  const detail = item?.detail ?? item?.reason ?? item?.description ?? item?.value ?? ''
  const code = String(item?.code ?? item?.id ?? `legacy_${sourceBucket}_${index}`)
  return {
    id: `${sourceBucket}-${code}-${index}`,
    code,
    label: String(label),
    detail: String(detail),
    status: normalizedStatus(item),
    polarity: ['bullish', 'bearish', 'neutral'].includes(item?.polarity)
      ? item.polarity
      : 'neutral',
    sourceBucket,
    category: String(item?.category ?? fallbackCategory),
  }
}

function normalizeEvidenceList(values, sourceBucket, category = 'evidence') {
  return evidenceValues(values).map((item, index) => (
    normalizeEvidenceItem(item, index, sourceBucket, category)
  ))
}

export function uniqueEvidence(items) {
  const seen = new Set()
  return items.filter(item => {
    const key = `${item.code}|${item.sourceBucket}|${item.label}|${item.detail}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function evidenceItems(raw, evidence) {
  if (Array.isArray(evidence.items)) {
    return evidence.items.map((item, index) => normalizeEvidenceItem(
      item,
      index,
      item?.source_bucket === 'opposing' ? 'opposing' : 'supporting',
    ))
  }

  const supporting = evidence.supporting ?? evidence.for ?? raw.supporting_evidence
  const opposing = evidence.opposing ?? evidence.against ?? raw.opposing_evidence
  return uniqueEvidence([
    ...normalizeEvidenceList(supporting, 'supporting'),
    ...normalizeEvidenceList(opposing, 'opposing'),
    ...normalizeEvidenceList(evidence.facts, 'supporting', 'observation'),
    ...normalizeEvidenceList(evidence.bullish, 'supporting', 'directional'),
    ...normalizeEvidenceList(evidence.bearish, 'opposing', 'directional'),
    ...normalizeEvidenceList(evidence.risks ?? evidence.risk, 'opposing', 'risk'),
    ...normalizeEvidenceList(evidence.gates ?? evidence.release_gates, 'opposing', 'release_gate'),
  ])
}

function withReleaseGateStatuses(forecast) {
  const releaseGates = [...forecast.releaseGates]
  const confidenceGateIndex = releaseGates.findIndex(item => item.code === 'confidence_release_threshold')
  if (confidenceGateIndex >= 0) {
    const item = releaseGates[confidenceGateIndex]
    const passed = forecast.confidenceScore != null
      && forecast.confidenceScore >= forecast.confidenceThreshold
    releaseGates[confidenceGateIndex] = {
      ...item,
      status: item.status || (passed ? 'passed' : 'failed'),
    }
  } else if (forecast.confidenceScore != null) {
    const passed = forecast.confidenceScore >= forecast.confidenceThreshold
    releaseGates.unshift({
      id: 'release-confidence-threshold',
      code: 'confidence_release_threshold',
      label: `證據充分度 ${forecast.confidenceScore.toFixed(0)} 分 / 門檻 ${forecast.confidenceThreshold.toFixed(0)} 分`,
      detail: passed ? '已達目前研究發布門檻' : '尚未達到研究發布門檻',
      status: passed ? 'passed' : 'failed',
      polarity: 'neutral',
      sourceBucket: passed ? 'supporting' : 'opposing',
      category: 'release_gate',
    })
  }

  if (forecast.confidenceScore == null) {
    releaseGates.push({
      id: 'release-missing-confidence-score',
      code: 'missing_confidence_score',
      label: '證據充分度未提供',
      detail: '缺少必要欄位，暫不形成方向判斷',
      status: 'failed',
      polarity: 'neutral',
      sourceBucket: 'opposing',
      category: 'release_gate',
    })
  }
  if (forecast.pUp == null || forecast.pDown == null) {
    releaseGates.push({
      id: 'release-missing-directional-probabilities',
      code: 'missing_directional_probabilities',
      label: '方向比例資料不完整',
      detail: '上漲與下跌比例必須同時存在，暫不形成方向判斷',
      status: 'failed',
      polarity: 'neutral',
      sourceBucket: 'opposing',
      category: 'release_gate',
    })
  }

  if (forecast.status !== 'ready' && !releaseGates.some(item => item.status === 'failed')) {
    releaseGates.push({
      id: 'release-unpublished-status',
      code: 'unpublished_status',
      label: forecast.abstainReason || '研究發布狀態：未形成方向判斷',
      detail: forecast.abstainReason ? '' : '服務未提供更詳細的門檻原因',
      status: 'failed',
      polarity: 'neutral',
      sourceBucket: 'opposing',
      category: 'release_gate',
    })
  }

  return {
    ...forecast,
    releaseGates: uniqueEvidence(releaseGates),
  }
}

export function normalizeForecast(payload, requestedHorizon) {
  const raw = payload?.forecast ?? payload ?? {}
  const probabilities = raw.probabilities ?? {}
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
  const confidenceThreshold = numberOrNull(
    confidenceObject.threshold
      ?? raw.confidence_threshold
      ?? raw.evidence_threshold
      ?? raw.release_threshold,
  ) ?? DEFAULT_EVIDENCE_THRESHOLD
  const allEvidence = evidenceItems(raw, evidence)
  const releaseGates = allEvidence.filter(item => item.category === 'release_gate')

  if (raw.abstain_reason && raw.status !== 'ready' && releaseGates.length === 0) {
    releaseGates.push({
      id: 'legacy-abstain-reason',
      code: 'legacy_abstain_reason',
      label: String(raw.abstain_reason),
      detail: '',
      status: 'failed',
      polarity: 'neutral',
      sourceBucket: 'opposing',
      category: 'release_gate',
    })
  }

  return withReleaseGateStatuses({
    symbol: raw.symbol,
    horizon: numberOrNull(raw.horizon_days ?? raw.horizon) ?? requestedHorizon,
    status: String(raw.status ?? 'unknown').toLowerCase(),
    research: raw.research !== false,
    asOf: raw.as_of ?? raw.data_as_of ?? null,
    generatedAt: raw.generated_at ?? null,
    modelVersion: raw.model_version ?? '—',
    dataVersion: raw.data_version ?? null,
    regime: String(raw.regime ?? 'unknown').toLowerCase(),
    confidenceScore,
    confidenceThreshold,
    confidenceLevel: String(confidenceObject.level ?? raw.confidence_level ?? '').toLowerCase(),
    recommendation: raw.recommendation ?? null,
    abstainReason: raw.abstain_reason ?? null,
    pUp: probabilityPct(probabilities.up ?? raw.p_up),
    pDown: probabilityPct(probabilities.down ?? raw.p_down),
    q10: nestedQuantile(raw, 'q10') ?? flatQuantile(raw, 'q10'),
    q50: nestedQuantile(raw, 'q50') ?? flatQuantile(raw, 'q50'),
    q90: nestedQuantile(raw, 'q90') ?? flatQuantile(raw, 'q90'),
    downsideThreshold: numberOrNull(downside.threshold_pct ?? raw.downside_threshold_pct),
    downsideProbability: probabilityPct(
      downside.probability ?? raw.downside_risk_probability ?? raw.drawdown_probability,
    ),
    facts: allEvidence.filter(item => item.category === 'observation'),
    supportingEvidence: allEvidence.filter(item => (
      item.sourceBucket === 'supporting'
      && !['release_gate', 'notice', 'observation'].includes(item.category)
    )),
    opposingEvidence: allEvidence.filter(item => (
      item.sourceBucket === 'opposing'
      && !['release_gate', 'notice', 'observation'].includes(item.category)
    )),
    releaseGates,
    notices: allEvidence.filter(item => item.category === 'notice'),
    stale: Boolean(quality.stale ?? raw.stale),
    observations: numberOrNull(quality.observations ?? raw.observations),
  })
}

export function stateOfForecast(forecast) {
  if (forecast.stale) {
    return { kind: 'stale', title: '資料已過期，暫停解讀', note: '等待資料更新後重新產生預測。' }
  }
  const insufficient = forecast.releaseGates.some(item => INSUFFICIENT_EVIDENCE_CODES.has(item.code))
    || (
      forecast.status !== 'ready'
      && forecast.pUp == null
      && forecast.pDown == null
    )
  if (insufficient || forecast.status === 'insufficient' || forecast.status === 'insufficient_data') {
    return {
      kind: 'insufficient',
      title: '資料不足，無法形成預測',
      note: forecast.abstainReason || '累積足夠樣本後會自動重試。',
    }
  }
  const failedReleaseGate = forecast.releaseGates.some(item => item.status === 'failed')
  if (forecast.status !== 'ready' || forecast.abstainReason || failedReleaseGate) {
    return {
      kind: 'abstain',
      title: '暫不形成方向判斷',
      note: '目前未通過研究發布門檻；仍可先查看風險與不足原因。',
    }
  }
  return {
    kind: 'ready',
    title: {
      research_watch_upside: '研究模型偏多',
      research_watch_downside: '研究模型偏空',
      wait: '等待更多證據',
    }[forecast.recommendation] || '研究預測已產生',
    note: '請同時檢查支持、反對證據與歷史分位數。',
  }
}
