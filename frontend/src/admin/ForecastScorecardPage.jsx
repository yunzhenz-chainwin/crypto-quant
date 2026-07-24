import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchCoins, fetchForecastScorecard } from '../api/admin'
import './ForecastScorecardPage.css'

const AUTO_REFRESH_MS = 5 * 60 * 1000

const VERDICT_COPY = {
  unverifiable: { label: '目前無法判定', tone: 'neutral' },
  insufficient_evidence: { label: '證據不足，暫不採信', tone: 'caution' },
  diagnostic_only: { label: '僅供診斷，不可升級', tone: 'caution' },
  not_better_than_baseline: { label: '尚未勝過基準', tone: 'bad' },
  promising_not_confirmed: { label: '有改善訊號，尚未確認', tone: 'caution' },
  release_review_eligible: { label: '可進入發布審查', tone: 'good' },
}

const TRUST_COPY = {
  unverifiable: '不可驗證',
  low: '低',
  medium: '中',
  high: '高',
}

const PERFORMANCE_COPY = {
  unverifiable: '不可驗證',
  below_baseline: '低於基準',
  indistinguishable_from_baseline: '與基準無法區分',
  descriptive_positive: '描述性結果偏正向',
  probability_skill_supported: '機率品質獲支持',
}

const PRIORITY_COPY = {
  high: '優先',
  medium: '次要',
  low: '觀察',
}

const ACTION_COPY = {
  collect_matured_outcomes: '繼續蒐集並封存成熟 outcomes，達門檻前不依短期分數調模。',
  fix_formal_model_scope: '鎖定單一不可變模型版本，再進行正式評估。',
  evaluate_horizons_separately: '分別評估 1、5、10 日預測期，避免事後挑選最佳結果。',
  remove_symbol_filter_for_formal_gate: '清除幣別篩選，再檢查完整適用範圍。',
  remove_window_filter_for_formal_gate: '改用完整歷史，再檢查正式升級門檻。',
  use_full_history_for_formal_gate: '改用完整歷史，再檢查正式升級門檻。',
  compare_calibration_challengers: '以 walk-forward 比較 identity、Platt 與 beta 校準。',
  run_calibration_challengers: '以 walk-forward 比較 identity、Platt 與 beta 校準。',
  validate_threshold_candidates: '在預先鎖定的 walk-forward 驗證上比較分類／拒答閾值。',
  validate_decision_threshold_offline: '在預先鎖定的 walk-forward 驗證上比較分類閾值。',
  test_regime_or_feature_challengers: '註冊新的 regime／特徵候選版本，再做完整 walk-forward 比較。',
  inspect_abstention_evidence: '檢查 abstain 原因與資料充分性，不直接放寬信心門檻。',
  audit_abstention_causes: '檢查 abstain 原因與資料充分性，不直接放寬信心門檻。',
  monitor_without_parameter_change: '維持參數並持續監控新成熟結果。',
  continue_shadow_monitoring: '維持參數並持續監控新成熟結果。',
}

const STATUS_COPY = {
  unverifiable: {
    title: '尚無法驗證',
    note: '目前沒有足夠的已成熟預測；系統不會用空樣本或測試期平均值製造準確率。',
  },
  insufficient_evidence: {
    title: '證據仍不足',
    note: '可以查看暫時性指標，但尚未達到預先設定的獨立日期與樣本門檻。',
  },
  evaluated: {
    title: '已完成樣本外評估',
    note: '指標來自不可變預測與事後結果；是否可升級仍以各項發布門檻為準。',
  },
  verified: {
    title: '已有可評估結果',
    note: '請同時檢查基準、coverage、校準與信賴區間，不以單一命中率判斷。',
  },
}

const GATE_LABELS = {
  single_model_horizon_scope: '單一模型與預測期範圍',
  v2_only_provenance: '僅使用 v2 可追溯帳本',
  all_resolved_scorable: '成熟預測資料完整可評分',
  minimum_observations: '有效樣本數',
  minimum_issue_dates: '獨立預測日期',
  positive_brier_skill: 'Brier skill 優於即時基準',
  brier_advantage_ci: 'Brier 優勢信賴區間',
  brier_skill: 'Brier skill 相對即時基準',
  brier_skill_ci: 'Brier skill 信賴區間下界',
  log_loss: 'Log loss 不劣於基準',
  sample_size: '有效樣本數',
  issue_dates: '獨立預測日期',
  calibration: '機率校準',
  interval_coverage: '預測區間覆蓋',
  selective_coverage: 'Ready coverage',
}

function finite(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function metric(group, key) {
  return group?.[key] ?? group?.metrics?.[key] ?? null
}

function observedMetric(payload, overall, key) {
  const observed = payload?.assessment?.observed_metrics
  if (observed && Object.prototype.hasOwnProperty.call(observed, key)) return observed[key]
  return metric(overall, key)
}

function readyAccuracy(group) {
  return group?.ready_accuracy ?? group?.metrics?.status_metrics?.ready?.accuracy ?? null
}

function gateName(gate) {
  const key = gate?.gate ?? gate?.key ?? gate?.name
  return gate?.label || GATE_LABELS[key] || key || '未命名門檻'
}

function gateDetail(gate) {
  if (gate?.detail || gate?.reason || gate?.threshold) {
    return gate.detail || gate.reason || gate.threshold
  }
  if (gate?.actual === undefined && gate?.required === undefined) return ''
  const display = value => {
    if (value === null || value === undefined) return '—'
    if (typeof value === 'object') {
      const lower = finite(value.lower ?? value.low ?? value.ci_low)
      const upper = finite(value.upper ?? value.high ?? value.ci_high)
      if (lower != null && upper != null) return `[${lower.toFixed(4)}, ${upper.toFixed(4)}]`
      return '詳見 API'
    }
    return String(value)
  }
  return `實際 ${display(gate.actual)}；要求 ${display(gate.required)}`
}

function count(value) {
  const number = finite(value)
  return number == null ? '—' : Math.round(number).toLocaleString()
}

function decimal(value, digits = 4) {
  const number = finite(value)
  return number == null ? '—' : number.toFixed(digits)
}

function percent(value, digits = 1) {
  const number = finite(value)
  return number == null ? '—' : `${(number * 100).toFixed(digits)}%`
}

function skill(value) {
  const number = finite(value)
  if (number == null) return '—'
  return `${number >= 0 ? '+' : ''}${(number * 100).toFixed(2)}%`
}

function metricDecimal(value, digits = 4) {
  const number = finite(value)
  return number == null ? '樣本不足' : number.toFixed(digits)
}

function metricPercent(value, digits = 1) {
  const number = finite(value)
  return number == null ? '樣本不足' : `${(number * 100).toFixed(digits)}%`
}

function metricSkill(value) {
  const number = finite(value)
  if (number == null) return '樣本不足'
  return `${number >= 0 ? '+' : ''}${(number * 100).toFixed(2)}%`
}

function gateStatus(gate) {
  return String(gate?.status || '').toLowerCase()
}

function findGate(gates, name) {
  return gates.find(gate => (gate?.gate ?? gate?.key ?? gate?.name) === name)
}

function requiredNumber(gate) {
  const direct = finite(gate?.required)
  if (direct != null) return direct
  const match = String(gate?.required ?? '').match(/[\d,.]+/)
  return match ? finite(match[0].replaceAll(',', '')) : null
}

function clampProgress(value) {
  const number = finite(value)
  return number == null ? null : Math.max(0, Math.min(1, number))
}

function formatLocalTime(value) {
  if (!value) return '尚未更新'
  const date = value instanceof Date ? value : new Date(value)
  if (!Number.isFinite(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatCountdown(value) {
  const seconds = Math.max(0, Math.round(finite(value) ?? 0))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

function displayEvidence(value) {
  if (value === null || value === undefined || value === '') return ''
  if (Array.isArray(value)) return value.map(displayEvidence).filter(Boolean).join('；')
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${displayEvidence(item)}`)
      .filter(item => !item.endsWith(': '))
      .join('；')
  }
  return String(value)
}

function deriveMaturity(payload, overall, gates) {
  const supplied = payload?.assessment?.data_maturity ?? {}
  const observations = finite(
    supplied.matured_observations ?? supplied.observations ?? metric(overall, 'observations'),
  ) ?? 0
  const issueDates = finite(supplied.issue_dates ?? metric(overall, 'issue_dates')) ?? 0
  const unresolved = finite(
    supplied.unresolved ?? overall?.unscorable_count ?? payload?.provenance?.pending,
  ) ?? 0
  const minimumObservations = finite(supplied.minimum_observations)
    ?? requiredNumber(findGate(gates, 'minimum_observations'))
  const minimumIssueDates = finite(supplied.minimum_issue_dates)
    ?? requiredNumber(findGate(gates, 'minimum_issue_dates'))
  const observationProgress = clampProgress(supplied.observation_progress)
    ?? (minimumObservations ? clampProgress(observations / minimumObservations) : null)
  const issueDateProgress = clampProgress(supplied.issue_date_progress)
    ?? (minimumIssueDates ? clampProgress(issueDates / minimumIssueDates) : null)
  const progressRatio = clampProgress(supplied.progress_ratio)
    ?? (observationProgress != null && issueDateProgress != null
      ? Math.min(observationProgress, issueDateProgress)
      : observationProgress ?? issueDateProgress)
  const ready = (
    (minimumObservations == null || observations >= minimumObservations)
    && (minimumIssueDates == null || issueDates >= minimumIssueDates)
    && observations > 0
  )

  return {
    level: supplied.level || (observations === 0 ? 'none' : ready ? 'mature' : 'growing'),
    observations,
    issueDates,
    unresolved,
    minimumObservations,
    minimumIssueDates,
    observationProgress,
    issueDateProgress,
    progressRatio,
    ready,
    note: supplied.note || (
      observations === 0
        ? '尚無已成熟且可評分的預測。'
        : ready
          ? '已達最低樣本與獨立日期門檻；仍需通過基準與信賴區間檢查。'
          : '資料仍在成熟中；短期 Accuracy、F1 等只可描述，不可當成發布證據。'
    ),
  }
}

function fallbackVerdict(payload, overall, gates, maturity) {
  const scopeGate = findGate(gates, 'single_model_horizon_scope')
  const failed = gates.some(gate => ['fail', 'failed'].includes(gateStatus(gate)))
  const testable = gates.filter(gate => !['not_applicable', 'not_testable', ''].includes(gateStatus(gate)))
  const allPass = testable.length > 0 && testable.every(gate => gateStatus(gate) === 'pass')
  const brierSkill = finite(metric(overall, 'brier_skill_score'))

  if (!maturity.observations || payload?.status === 'unverifiable') return 'unverifiable'
  if (!maturity.ready || payload?.status === 'insufficient_evidence') return 'insufficient_evidence'
  if (gateStatus(scopeGate) === 'not_applicable') return 'diagnostic_only'
  if (brierSkill != null && brierSkill <= 0) return 'not_better_than_baseline'
  if (allPass && !failed) return 'release_review_eligible'
  return 'promising_not_confirmed'
}

function fallbackTrust(verdict) {
  if (verdict === 'unverifiable') return 'unverifiable'
  if (['insufficient_evidence', 'diagnostic_only', 'not_better_than_baseline'].includes(verdict)) return 'low'
  if (verdict === 'release_review_eligible') return 'high'
  return 'medium'
}

function fallbackPerformance(overall, maturity) {
  const brierSkill = finite(metric(overall, 'brier_skill_score'))
  if (!maturity.observations || brierSkill == null) return 'unverifiable'
  if (brierSkill < 0) return 'below_baseline'
  if (brierSkill === 0) return 'indistinguishable_from_baseline'
  return maturity.ready ? 'descriptive_positive' : 'unverifiable'
}

function normalizeReasons(raw) {
  if (!Array.isArray(raw)) return []
  return raw.map((reason, index) => (
    typeof reason === 'string'
      ? { code: `reason-${index}`, title: reason, detail: '', severity: 'info', evidence: '' }
      : {
          code: reason?.code || `reason-${index}`,
          title: reason?.title || reason?.detail || '評估原因',
          detail: reason?.title ? reason?.detail : '',
          severity: reason?.severity === 'blocker' ? 'error' : reason?.severity || 'info',
          evidence: displayEvidence(reason?.evidence),
        }
  ))
}

function fallbackReasons(payload, overall, gates, maturity, verdict) {
  const reasons = []
  const scopeGate = findGate(gates, 'single_model_horizon_scope')
  const brierSkill = finite(metric(overall, 'brier_skill_score'))
  const brierCi = overall?.brier_advantage_ci ?? payload?.brier_advantage_ci
  const ciLower = finite(brierCi?.lower ?? brierCi?.low ?? brierCi?.ci_low)

  if (!maturity.observations) {
    reasons.push({
      code: 'no_matured_outcomes',
      title: '沒有可評分的成熟結果',
      detail: '系統不會用待成熟預測或空樣本製造準確率。',
      severity: 'warning',
      evidence: `成熟樣本 ${count(maturity.observations)} 筆`,
    })
  } else if (!maturity.ready) {
    reasons.push({
      code: 'minimum_evidence_not_met',
      title: '樣本與獨立日期尚未達門檻',
      detail: 'Accuracy、F1、AUC 目前只能視為短期描述值。',
      severity: 'warning',
      evidence: `${count(maturity.observations)}/${count(maturity.minimumObservations)} 筆；${count(maturity.issueDates)}/${count(maturity.minimumIssueDates)} 個 issue dates`,
    })
  }
  if (gateStatus(scopeGate) === 'not_applicable') {
    reasons.push({
      code: 'diagnostic_scope',
      title: '目前篩選範圍只適合診斷',
      detail: '單一幣別或有限視窗會造成選擇偏誤，不能用來決定模型升級。',
      severity: 'warning',
      evidence: gateDetail(scopeGate),
    })
  }
  if (brierSkill != null && brierSkill <= 0) {
    reasons.push({
      code: 'not_better_than_baseline',
      title: '機率品質尚未勝過即時基準',
      detail: '即使方向命中率看似不差，也不能據此宣稱機率預測有效。',
      severity: 'error',
      evidence: `Brier skill ${skill(brierSkill)}`,
    })
  } else if (brierSkill != null && ciLower != null && ciLower <= 0) {
    reasons.push({
      code: 'uncertain_brier_advantage',
      title: '改善仍落在抽樣不確定範圍內',
      detail: 'Brier 優勢的信賴區間下界尚未大於 0。',
      severity: 'warning',
      evidence: `信賴區間下界 ${decimal(ciLower)}`,
    })
  }
  if (!reasons.length && verdict === 'release_review_eligible') {
    reasons.push({
      code: 'formal_gates_passed',
      title: '正式統計門檻已通過',
      detail: '這表示可進入人工發布審查，不代表可自動上線或保證未來績效。',
      severity: 'success',
      evidence: `${gates.filter(gate => gateStatus(gate) === 'pass').length} 項門檻通過`,
    })
  }
  return reasons
}

function normalizeActions(raw) {
  if (!Array.isArray(raw)) return []
  return raw.map((item, index) => ({
    id: item?.id || item?.parameter || `action-${index}`,
    priority: item?.priority ?? 'medium',
    order: finite(item?.order) ?? index + 1,
    parameter: item?.parameter || '模型設定',
    current: displayEvidence(item?.current) || '未提供',
    suggested: displayEvidence(item?.suggested ?? item?.target) || '先保留現況',
    action: ACTION_COPY[item?.action] || item?.action || '進行離線驗證後再決定',
    rationale: item?.rationale || item?.reason || '需要更多樣本外證據。',
    evidence: displayEvidence(item?.evidence),
    status: item?.status || 'diagnostic_only',
    requiresValidation: item?.requires_validation !== false,
    automaticChange: item?.automatic_change === true,
  })).sort((left, right) => left.order - right.order)
}

function priorityDisplay(value) {
  const rank = finite(value)
  if (rank != null) {
    const tone = rank <= 2 ? 'high' : rank <= 4 ? 'medium' : 'low'
    return {
      tone,
      label: PRIORITY_COPY[tone],
    }
  }
  const normalized = String(value || 'medium').toLowerCase()
  return { tone: normalized, label: PRIORITY_COPY[normalized] || String(value) }
}

function fallbackActions(payload, overall, gates, maturity) {
  const actions = []
  const filters = payload?.filters ?? {}
  const brierSkill = finite(metric(overall, 'brier_skill_score'))
  const coverage = finite(metric(overall, 'coverage'))
  const scopeGate = findGate(gates, 'single_model_horizon_scope')

  if (!maturity.ready) {
    actions.push({
      id: 'minimum_evidence', priority: 'high', parameter: 'minimum_evidence',
      current: `${count(maturity.observations)} 筆／${count(maturity.issueDates)} 個日期`,
      suggested: `${count(maturity.minimumObservations)} 筆／${count(maturity.minimumIssueDates)} 個日期`,
      action: '繼續蒐集並封存成熟 outcomes；門檻前不依短期分數改模型。',
      rationale: '降低小樣本波動與跨幣同日相關性造成的假精準。',
      evidence: maturity.note, status: 'collect_matured_outcomes',
      requiresValidation: true, automaticChange: false,
    })
  }
  if (gateStatus(scopeGate) === 'not_applicable' || filters.symbol || filters.window) {
    actions.push({
      id: 'evaluation_filter', priority: 'high', parameter: 'evaluation_filter',
      current: `${filters.symbol || '全部幣別'}／${filters.window ? `${filters.window} 日` : '完整歷史'}`,
      suggested: '單一模型＋單一 horizon＋全部幣別＋完整歷史',
      action: '清除幣別與時間視窗後，再檢查正式升級門檻。',
      rationale: '篩選切片適合找問題，但不適合作為發布證據。',
      evidence: gateDetail(scopeGate), status: 'diagnostic_only',
      requiresValidation: true, automaticChange: false,
    })
  }
  if (brierSkill != null && brierSkill <= 0) {
    actions.push({
      id: 'probability_calibration', priority: 'high', parameter: 'calibration_method',
      current: '原始機率（identity）', suggested: 'identity／Platt／beta 三者逐期比較',
      action: '用嚴格 walk-forward 校準，依同一批成熟樣本比較 Brier 與 log loss。',
      rationale: '目前機率預測未勝過 forecast-time baseline。',
      evidence: `Brier skill ${skill(brierSkill)}`, status: 'offline_validation_required',
      requiresValidation: true, automaticChange: false,
    })
  }
  if (maturity.ready && coverage != null && coverage < 0.1) {
    actions.push({
      id: 'decision_threshold', priority: 'medium', parameter: 'ready_abstain_threshold',
      current: `Ready coverage ${percent(coverage)}`, suggested: '預先宣告 coverage–accuracy 掃描範圍',
      action: '只在鎖定的 walk-forward 驗證上比較閾值；不得用本頁結果直接調參。',
      rationale: '過度拒答可能讓命中率看似漂亮，卻沒有決策覆蓋。',
      evidence: `${count(metric(overall, 'ready_count'))} 筆 Ready`, status: 'offline_validation_required',
      requiresValidation: true, automaticChange: false,
    })
  }
  if (!actions.length) {
    actions.push({
      id: 'monitor', priority: 'low', parameter: 'production_parameters',
      current: '維持現況', suggested: '不自動調整',
      action: '持續累積封存結果並監控校準漂移。',
      rationale: '目前沒有足以支持立即改參數的失敗訊號。',
      evidence: '任何變更仍需獨立 walk-forward 驗證。', status: 'monitor',
      requiresValidation: true, automaticChange: false,
    })
  }
  return actions
}

function deriveAssessment(payload, overall, gates) {
  const supplied = payload?.assessment ?? {}
  const maturity = deriveMaturity(payload, overall, gates)
  const verdict = supplied.verdict || fallbackVerdict(payload, overall, gates, maturity)
  const trustLevel = supplied.trust_level || fallbackTrust(verdict)
  const performanceLevel = supplied.performance_level || fallbackPerformance(overall, maturity)
  const reasons = normalizeReasons(supplied.reasons)
  const actions = normalizeActions(supplied.recommended_actions)
  const trustScore = clampProgress(supplied.trust_score ?? supplied.confidence_score)

  return {
    verdict,
    trustLevel,
    trustScore,
    performanceLevel,
    headline: supplied.headline || VERDICT_COPY[verdict]?.label || '目前狀態待人工判讀',
    supportsProbabilitySkillClaim: supplied.supports_probability_skill_claim === true,
    releaseReviewEligible: supplied.release_review_eligible === true || verdict === 'release_review_eligible',
    maturity,
    reasons: reasons.length ? reasons : fallbackReasons(payload, overall, gates, maturity, verdict),
    actions: actions.length ? actions : fallbackActions(payload, overall, gates, maturity),
    disclaimer: supplied.disclaimer || '此判讀是模型治理證據，不是投資建議，也不保證未來報酬。',
  }
}

function normalizeGroups(raw) {
  if (Array.isArray(raw)) return raw
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw).map(([horizon, value]) => ({
    horizon_days: Number(horizon),
    ...(value || {}),
  }))
}

function normalizeGates(payload) {
  const raw = payload?.promotion_gates ?? payload?.overall?.promotion_gates ?? []
  if (Array.isArray(raw)) return raw
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw).map(([key, value]) => (
    typeof value === 'object' && value !== null
      ? { key, ...value }
      : { key, status: value === true ? 'pass' : value === false ? 'fail' : 'not_testable' }
  ))
}

function coinLabel(coin) {
  const symbol = String(coin?.symbol || '').toUpperCase()
  const ticker = String(coin?.ticker || symbol.replace(/USDT$/, '')).toUpperCase()
  const name = String(coin?.zh || '').trim()
  const status = coin?.enabled === false ? ' · 已停用' : ''
  return `${name ? `${name} ` : ''}${ticker}（${symbol}）${status}`
}

function MetricCard({ label, value, note, tone = '' }) {
  return (
    <div className={`forecast-score-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  )
}

function GateBadge({ status }) {
  const normalized = String(status || 'not_testable').toLowerCase()
  const label = normalized === 'pass'
    ? '通過'
    : normalized === 'fail' || normalized === 'failed'
      ? '未通過'
      : normalized === 'not_applicable'
        ? '不適用'
      : '尚不可判定'
  return <span className={`forecast-gate-badge ${normalized}`}>{label}</span>
}

function AssessmentPanel({ assessment }) {
  const verdictCopy = VERDICT_COPY[assessment.verdict] ?? { label: assessment.headline, tone: 'neutral' }
  const tone = !assessment.maturity.ready && verdictCopy.tone === 'good' ? 'caution' : verdictCopy.tone

  return (
    <section className="forecast-assessment-grid" aria-labelledby="forecast-trust-heading">
      <div className={`forecast-trust-card ${tone}`}>
        <div className="forecast-card-heading">
          <div>
            <p className="forecast-card-kicker">目前是否可信</p>
            <h2 id="forecast-trust-heading">{assessment.headline || verdictCopy.label}</h2>
          </div>
          <span className={`forecast-verdict-badge ${tone}`}>{verdictCopy.label}</span>
        </div>
        <div className="forecast-trust-facts">
          <div>
            <span>證據可信度</span>
            <strong>{TRUST_COPY[assessment.trustLevel] || assessment.trustLevel || '不可驗證'}</strong>
          </div>
          <div>
            <span>相對基準表現</span>
            <strong>{PERFORMANCE_COPY[assessment.performanceLevel] || assessment.performanceLevel || '不可驗證'}</strong>
          </div>
          <div>
            <span>治理結論</span>
            <strong>{assessment.releaseReviewEligible ? '可進人工發布審查' : '維持研究／觀察'}</strong>
          </div>
          <div>
            <span>機率技巧主張</span>
            <strong>{assessment.supportsProbabilitySkillClaim ? '有正式證據支持' : '目前不支持'}</strong>
          </div>
          {assessment.trustScore != null && (
            <div>
              <span>治理證據分數</span>
              <strong>{percent(assessment.trustScore)}</strong>
              <small>不是單筆預測信心</small>
            </div>
          )}
        </div>
        <p className="forecast-assessment-disclaimer">{assessment.disclaimer}</p>
      </div>

      <div className="forecast-maturity-card">
        <div className="forecast-card-heading">
          <div>
            <p className="forecast-card-kicker">DATA MATURITY</p>
            <h2>資料成熟度</h2>
          </div>
          <span className={`forecast-maturity-badge ${assessment.maturity.ready ? 'ready' : 'waiting'}`}>
            {assessment.maturity.ready ? '已達最低門檻' : '持續累積中'}
          </span>
        </div>
        <div className="forecast-maturity-progress" aria-label={`資料成熟度 ${percent(assessment.maturity.progressRatio)}`}>
          <span style={{ width: `${(assessment.maturity.progressRatio ?? 0) * 100}%` }} />
        </div>
        <div className="forecast-maturity-values">
          <div>
            <span>成熟樣本</span>
            <strong>{count(assessment.maturity.observations)} / {count(assessment.maturity.minimumObservations)}</strong>
          </div>
          <div>
            <span>獨立日期</span>
            <strong>{count(assessment.maturity.issueDates)} / {count(assessment.maturity.minimumIssueDates)}</strong>
          </div>
          <div>
            <span>未可評分</span>
            <strong>{count(assessment.maturity.unresolved)}</strong>
          </div>
        </div>
        <p>{assessment.maturity.note}</p>
      </div>

      <div className="forecast-reasons-card">
        <div className="forecast-card-heading">
          <div>
            <p className="forecast-card-kicker">WHY</p>
            <h2>判讀原因</h2>
          </div>
        </div>
        <div className="forecast-reasons-list">
          {assessment.reasons.length ? assessment.reasons.map(reason => (
            <article className={`forecast-reason ${reason.severity}`} key={reason.code}>
              <span className="forecast-reason-dot" aria-hidden="true" />
              <div>
                <strong>{reason.title}</strong>
                {reason.detail && <p>{reason.detail}</p>}
                {reason.evidence && <small>{reason.evidence}</small>}
              </div>
            </article>
          )) : <p className="forecast-scorecard-empty">後端尚未提供可判讀原因。</p>}
        </div>
      </div>
    </section>
  )
}

function RecommendationPanel({ actions }) {
  return (
    <section className="forecast-recommendations" aria-labelledby="forecast-recommendations-heading">
      <div className="forecast-section-heading">
        <div>
          <p className="forecast-card-kicker">CONTROLLED NEXT STEPS</p>
          <h2 id="forecast-recommendations-heading" className="admin-section-title">建議調整</h2>
        </div>
        <p>以下只列出應驗證的參數與方法，不會自動修改模型。</p>
      </div>
      <div className="forecast-action-grid">
        {actions.map(action => {
          const priority = priorityDisplay(action.priority)
          return <article className="forecast-action-card" key={action.id}>
            <div className="forecast-action-header">
              <span className={`forecast-priority ${priority.tone}`}>
                {priority.label}
              </span>
              <code>{action.parameter}</code>
            </div>
            <dl>
              <div><dt>目前</dt><dd>{action.current}</dd></div>
              <div><dt>目標／候選</dt><dd>{action.suggested}</dd></div>
              <div><dt>行動</dt><dd>{action.action}</dd></div>
              <div><dt>原因</dt><dd>{action.rationale}</dd></div>
            </dl>
            {action.evidence && <p className="forecast-action-evidence">依據：{action.evidence}</p>}
            <div className="forecast-action-safety">
              <span>{action.requiresValidation ? '需獨立驗證' : '一般維運'}</span>
              <span>{action.automaticChange ? 'API 標示可自動變更' : '不自動套用'}</span>
            </div>
          </article>
        })}
      </div>
      <div className="forecast-filter-warning" role="note">
        <strong>評估篩選不會改模型。</strong>
        <span>切換幣別、預測期或視窗只改變本頁分析範圍；任何參數變更都必須另做 walk-forward 驗證與人工審查。</span>
      </div>
    </section>
  )
}

export default function ForecastScorecardPage({ onLogout }) {
  const [horizon, setHorizon] = useState('1')
  const [windowDays, setWindowDays] = useState('all')
  const [symbolDraft, setSymbolDraft] = useState('')
  const [symbol, setSymbol] = useState('')
  const [coinOptions, setCoinOptions] = useState([])
  const [coinsLoading, setCoinsLoading] = useState(true)
  const [coinsError, setCoinsError] = useState('')
  const [modelVersionDraft, setModelVersionDraft] = useState('historical-baseline-v2')
  const [modelVersion, setModelVersion] = useState('historical-baseline-v2')
  const [payload, setPayload] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null)
  const [nextRefreshAt, setNextRefreshAt] = useState(null)
  const [countdownSeconds, setCountdownSeconds] = useState(AUTO_REFRESH_MS / 1000)
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState === 'visible')
  const requestRef = useRef(null)

  const load = useCallback(async (reason = 'manual') => {
    const automatic = reason === 'auto' || reason === 'visibility'
    if (automatic && requestRef.current) return
    if (requestRef.current) requestRef.current.abort()

    const controller = new AbortController()
    requestRef.current = controller
    setRefreshing(true)
    if (!automatic) setError('')
    let completed = false
    try {
      const result = await fetchForecastScorecard({
        horizon: horizon === 'all' ? null : Number(horizon),
        symbol: symbol || null,
        modelVersion: modelVersion || null,
        window: windowDays === 'all' ? null : Number(windowDays),
        signal: controller.signal,
      })
      if (requestRef.current !== controller) return
      const updatedAt = new Date()
      setPayload(result)
      setLastUpdatedAt(updatedAt)
      setNextRefreshAt(updatedAt.getTime() + AUTO_REFRESH_MS)
      setCountdownSeconds(AUTO_REFRESH_MS / 1000)
      setError('')
      completed = true
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) return
      if (requestRef.current !== controller) return
      if (err.message === 'UNAUTH') {
        onLogout()
        return
      }
      setError(err.message || '讀取模型成績單失敗')
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null
        setRefreshing(false)
        if (!completed) setNextRefreshAt(Date.now() + AUTO_REFRESH_MS)
      }
    }
  }, [horizon, modelVersion, onLogout, symbol, windowDays])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load('filters') }, 0)
    return () => {
      window.clearTimeout(timer)
      requestRef.current?.abort()
    }
  }, [load])

  useEffect(() => {
    const tick = () => {
      const visible = document.visibilityState === 'visible'
      setPageVisible(visible)
      if (!nextRefreshAt) return
      const remaining = Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000))
      setCountdownSeconds(remaining)
      if (visible && remaining === 0) void load('auto')
    }
    const onVisibilityChange = () => {
      tick()
      if (
        document.visibilityState === 'visible'
        && nextRefreshAt
        && nextRefreshAt <= Date.now()
      ) void load('visibility')
    }

    tick()
    const timer = window.setInterval(tick, 1000)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [load, nextRefreshAt])

  useEffect(() => {
    let active = true
    void fetchCoins()
      .then(result => {
        if (!active) return
        const options = (result?.coins ?? [])
          .filter(coin => coin?.symbol)
          .sort((left, right) => {
            const enabledOrder = Number(right.enabled !== false) - Number(left.enabled !== false)
            return enabledOrder || String(left.symbol).localeCompare(String(right.symbol))
          })
        setCoinOptions(options)
        setCoinsError('')
      })
      .catch(err => {
        if (!active) return
        if (err.message === 'UNAUTH') {
          onLogout()
          return
        }
        setCoinsError('幣別清單載入失敗，請重新整理後再試。')
      })
      .finally(() => {
        if (active) setCoinsLoading(false)
      })
    return () => { active = false }
  }, [onLogout])

  const overall = useMemo(() => payload?.overall ?? {}, [payload])
  const groups = useMemo(() => normalizeGroups(payload?.by_horizon), [payload])
  const gates = useMemo(() => normalizeGates(payload), [payload])
  const status = STATUS_COPY[payload?.status] ?? STATUS_COPY.unverifiable
  const brierSkill = observedMetric(payload, overall, 'brier_skill_score')
  const interval = overall?.interval_metrics ?? overall?.interval ?? overall?.intervals ?? {}
  const filters = payload?.filters ?? {}
  const assessment = useMemo(
    () => deriveAssessment(payload, overall, gates),
    [gates, overall, payload],
  )
  const explainability = payload?.assessment?.explainability ?? {}

  const applyFilters = (event) => {
    event.preventDefault()
    const nextSymbol = symbolDraft
    const nextModelVersion = modelVersionDraft.trim()
    if (nextSymbol === symbol && nextModelVersion === modelVersion) {
      void load('filters')
      return
    }
    setSymbol(nextSymbol)
    setModelVersion(nextModelVersion)
  }

  return (
    <div className="admin-body forecast-scorecard-page">
      <div className="forecast-scorecard-heading">
        <div>
          <p className="forecast-scorecard-eyebrow">POINT-IN-TIME MODEL GOVERNANCE</p>
          <h1>研究預測模型成績單</h1>
          <p>只評分已封存且已成熟的預測，並用預測當時可取得的歷史結果建立基準。</p>
        </div>
        <div className="forecast-refresh-controls">
          <div className="forecast-refresh-status" role="status" aria-live="polite">
            <span className={`forecast-live-dot ${refreshing ? 'refreshing' : ''}`} aria-hidden="true" />
            <span>最後更新：{formatLocalTime(lastUpdatedAt)}</span>
            <span>{pageVisible ? `下次自動更新：${formatCountdown(countdownSeconds)}` : '頁面隱藏，自動更新已暫停'}</span>
          </div>
          <button
            className="admin-link"
            type="button"
            onClick={() => { void load('manual') }}
            disabled={refreshing}
          >
            {refreshing ? '更新中…' : '立即重新整理'}
          </button>
        </div>
      </div>

      <form className="forecast-scorecard-filters" onSubmit={applyFilters}>
        <label>
          <span>預測期</span>
          <select value={horizon} onChange={event => setHorizon(event.target.value)}>
            <option value="all">全部</option>
            <option value="1">1 日</option>
            <option value="5">5 日</option>
            <option value="10">10 日</option>
          </select>
        </label>
        <label>
          <span>評估視窗</span>
          <select value={windowDays} onChange={event => setWindowDays(event.target.value)}>
            <option value="90">最近 90 日</option>
            <option value="365">最近 365 日</option>
            <option value="all">全部紀錄</option>
          </select>
        </label>
        <label className="forecast-symbol-filter">
          <span>幣別</span>
          <select
            value={symbolDraft}
            onChange={event => setSymbolDraft(event.target.value)}
            aria-label="篩選幣別"
            disabled={coinsLoading && coinOptions.length === 0}
          >
            <option value="">全部幣別</option>
            {coinOptions.map(coin => (
              <option key={coin.symbol} value={coin.symbol}>{coinLabel(coin)}</option>
            ))}
          </select>
          <small className={`forecast-filter-hint ${coinsError ? 'error' : ''}`}>
            {coinsError || (coinsLoading ? '正在載入幣別…' : `${coinOptions.length} 個幣別可篩選`)}
          </small>
        </label>
        <label className="forecast-model-filter">
          <span>模型版本（留空為診斷彙總）</span>
          <input
            value={modelVersionDraft}
            onChange={event => setModelVersionDraft(event.target.value)}
            placeholder="historical-baseline-v2"
          />
        </label>
        <button className="forecast-apply-filter" type="submit">套用篩選</button>
      </form>

      {error && (
        <div className="admin-error" role="alert">
          {error}{payload ? '；目前保留顯示上一次成功取得的資料。' : ''}
        </div>
      )}

      <section className={`forecast-scorecard-status ${payload?.status || 'unverifiable'}`}>
        <div>
          <strong>{status.title}</strong>
          <p>{payload?.message || status.note}</p>
        </div>
        <dl>
          <div><dt>資料截至</dt><dd>{payload?.data_as_of || '—'}</dd></div>
          <div><dt>模型版本</dt><dd>{filters.model_version || '全部'}</dd></div>
          <div><dt>產生時間</dt><dd>{payload?.generated_at || '—'}</dd></div>
        </dl>
      </section>

      <AssessmentPanel assessment={assessment} />

      <section>
        <div className="forecast-section-heading">
          <div>
            <p className="forecast-card-kicker">LIVE OUT-OF-SAMPLE METRICS</p>
            <h2 className="admin-section-title">動態準確度與機率品質</h2>
          </div>
          {!assessment.maturity.ready && <p>樣本未達門檻，以下數值不以綠色標示，也不能單獨支持模型升級。</p>}
        </div>
        <div className="forecast-score-metrics">
          <MetricCard label="已成熟預測" value={count(metric(overall, 'observations'))} note="去重後的不可變 forecast/outcome" />
          <MetricCard label="獨立 issue dates" value={count(metric(overall, 'issue_dates'))} note="跨幣同日不當成獨立日期" />
          <MetricCard label="Accuracy" value={metricPercent(observedMetric(payload, overall, 'accuracy'))} note="方向正確比例；門檻為 p ≥ 0.5" />
          <MetricCard label="Precision" value={metricPercent(observedMetric(payload, overall, 'precision'))} note="預測上漲中實際上漲比例" />
          <MetricCard label="Recall" value={metricPercent(observedMetric(payload, overall, 'recall') ?? observedMetric(payload, overall, 'sensitivity'))} note="實際上漲被辨識的比例" />
          <MetricCard label="F1" value={metricDecimal(observedMetric(payload, overall, 'f1_score') ?? observedMetric(payload, overall, 'f1'))} note="Precision 與 Recall 的調和平均" />
          <MetricCard label="ROC-AUC" value={metricDecimal(observedMetric(payload, overall, 'roc_auc'))} note="排序能力；單一類別時無法計算" />
          <MetricCard label="Average Precision" value={metricDecimal(observedMetric(payload, overall, 'average_precision'))} note="正類別不平衡時的排序摘要" />
          <MetricCard label="Brier score" value={metricDecimal(observedMetric(payload, overall, 'brier_score'))} note="機率誤差，越低越好" />
          <MetricCard
            label="Brier skill"
            value={metricSkill(brierSkill)}
            note="相對 forecast-time expanding baseline"
            tone={assessment.maturity.ready ? (finite(brierSkill) > 0 ? 'good' : finite(brierSkill) < 0 ? 'bad' : '') : ''}
          />
          <MetricCard label="Log loss" value={metricDecimal(metric(overall, 'log_loss'))} note="重罰過度自信的錯誤" />
          <MetricCard label="校準誤差 ECE" value={metricPercent(observedMetric(payload, overall, 'expected_calibration_error'))} note="僅作輔助，不單獨判定" />
          <MetricCard label="Ready coverage" value={percent(metric(overall, 'coverage'))} note={`${count(metric(overall, 'ready_count'))} 筆實際發布`} />
          <MetricCard label="Ready 命中率" value={percent(readyAccuracy(overall))} note="必須與 coverage 同看" />
          <MetricCard label="區間覆蓋" value={percent(metric(interval, 'empirical_coverage') ?? metric(interval, 'coverage'))} note={`平均寬度 ${decimal(metric(interval, 'mean_width_pct') ?? metric(interval, 'mean_width'), 2)}%`} />
          <MetricCard label="WIS" value={decimal(metric(interval, 'weighted_interval_score'))} note="兼顧區間寬度與漏包懲罰" />
        </div>
      </section>

      <RecommendationPanel actions={assessment.actions} />

      <section className="forecast-explainability" aria-labelledby="forecast-explainability-heading">
        <div>
          <p className="forecast-card-kicker">EXPLAINABILITY</p>
          <h2 id="forecast-explainability-heading" className="admin-section-title">模型解釋性</h2>
        </div>
        <div className="forecast-explainability-content">
          <span className="forecast-na-badge">SHAP：N/A</span>
          <div>
            <strong>
              {explainability.shap === 'not_applicable' || filters.model_version === 'historical-baseline-v2'
                ? '目前使用歷史統計基準，不產生假的特徵貢獻值。'
                : '目前 scorecard ledger 沒有可用的特徵歸因資料。'}
            </strong>
            <p>{explainability.reason || (
              filters.model_version === 'historical-baseline-v2'
                ? 'historical empirical baseline 沒有可供 SHAP 解釋的 feature matrix 與已訓練模型物件；現階段以資料來源、基準規則、cohort 與 regime 敏感度稽核取代。'
                : '此 API 未提供模型物件、背景資料與 feature matrix，因此 SHAP 目前不可取得；不可把缺值解讀為模型天生不適用 SHAP。'
            )}</p>
            <small>解釋方法：{explainability.method || 'historical_evidence'}；SHAP 狀態：{explainability.shap || 'not_applicable'}</small>
          </div>
        </div>
      </section>

      <section>
        <h2 className="admin-section-title">各預測期明細</h2>
        <div className="admin-table-wrap forecast-scorecard-table-wrap">
          <table className="admin-table forecast-scorecard-table">
            <thead>
              <tr>
                <th>預測期</th><th>樣本</th><th>Issue dates</th><th>Brier</th><th>基準 Brier</th>
                <th>Skill</th><th>Log loss</th><th>ECE</th><th>Coverage</th><th>Ready 命中率</th>
              </tr>
            </thead>
            <tbody>
              {groups.length ? groups.map(group => {
                const groupSkill = metric(group, 'brier_skill_score')
                const groupMature = group?.status === 'evaluated'
                return (
                  <tr key={group.horizon_days ?? group.horizon}>
                    <td>{group.horizon_days ?? group.horizon} 日</td>
                    <td>{count(metric(group, 'observations'))}</td>
                    <td>{count(metric(group, 'issue_dates'))}</td>
                    <td>{decimal(metric(group, 'brier_score'))}</td>
                    <td>{decimal(metric(group, 'baseline_brier_score'))}</td>
                    <td className={groupMature ? (finite(groupSkill) > 0 ? 'score-good' : finite(groupSkill) < 0 ? 'score-bad' : '') : ''}>{skill(groupSkill)}</td>
                    <td>{decimal(metric(group, 'log_loss'))}</td>
                    <td>{percent(metric(group, 'expected_calibration_error'))}</td>
                    <td>{percent(metric(group, 'coverage'))}</td>
                    <td>{percent(readyAccuracy(group))}</td>
                  </tr>
                )
              }) : (
                <tr><td colSpan="10" className="forecast-scorecard-empty">尚無可評分的成熟預測</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="forecast-scorecard-two-col">
        <div>
          <h2 className="admin-section-title">模型升級門檻</h2>
          <div className="forecast-gates">
            {gates.length ? gates.map((gate, index) => (
              <div className="forecast-gate" key={gate.gate || gate.key || gate.name || index}>
                <div>
                  <strong>{gateName(gate)}</strong>
                  <small>{gateDetail(gate)}</small>
                </div>
                <GateBadge status={gate.status} />
              </div>
            )) : <p className="forecast-scorecard-empty">目前樣本不足，升級門檻尚不可判定。</p>}
          </div>
        </div>

        <div className="forecast-scorecard-guide">
          <h2 className="admin-section-title">判讀原則</h2>
          <ul>
            <li><b>Brier skill &gt; 0</b> 才代表機率品質勝過當時可知的基準率。</li>
            <li><b>命中率必須搭配 coverage</b>；大量拒答可以讓命中率看似很高。</li>
            <li><b>ECE 不是單一發布門檻</b>；小樣本與分箱方式都會影響數值。</li>
            <li><b>區間同時看覆蓋與寬度</b>；無限寬的區間沒有決策價值。</li>
            <li><b>本頁不是投資績效</b>；手續費、滑價與期望效用必須另外驗證。</li>
          </ul>
        </div>
      </section>
    </div>
  )
}
