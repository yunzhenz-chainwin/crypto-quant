import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchCoins, fetchForecastScorecard } from '../api/admin'
import './ForecastScorecardPage.css'

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

export default function ForecastScorecardPage({ onLogout }) {
  const [horizon, setHorizon] = useState('5')
  const [windowDays, setWindowDays] = useState('all')
  const [symbolDraft, setSymbolDraft] = useState('')
  const [symbol, setSymbol] = useState('')
  const [coinOptions, setCoinOptions] = useState([])
  const [coinsLoading, setCoinsLoading] = useState(true)
  const [coinsError, setCoinsError] = useState('')
  const [modelVersionDraft, setModelVersionDraft] = useState('historical-baseline-v2')
  const [modelVersion, setModelVersion] = useState('historical-baseline-v2')
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchForecastScorecard({
        horizon: horizon === 'all' ? null : Number(horizon),
        symbol: symbol || null,
        modelVersion: modelVersion || null,
        window: windowDays === 'all' ? null : Number(windowDays),
      })
      setPayload(result)
    } catch (err) {
      if (err.message === 'UNAUTH') {
        onLogout()
        return
      }
      setError(err.message || '讀取模型成績單失敗')
    } finally {
      setLoading(false)
    }
  }, [horizon, modelVersion, onLogout, symbol, windowDays])

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

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

  const overall = payload?.overall ?? {}
  const groups = useMemo(() => normalizeGroups(payload?.by_horizon), [payload])
  const gates = useMemo(() => normalizeGates(payload), [payload])
  const status = STATUS_COPY[payload?.status] ?? STATUS_COPY.unverifiable
  const brierSkill = metric(overall, 'brier_skill_score')
  const interval = overall?.interval_metrics ?? overall?.interval ?? overall?.intervals ?? {}
  const filters = payload?.filters ?? {}

  const applyFilters = (event) => {
    event.preventDefault()
    setSymbol(symbolDraft)
    setModelVersion(modelVersionDraft.trim())
  }

  return (
    <div className="admin-body forecast-scorecard-page">
      <div className="forecast-scorecard-heading">
        <div>
          <p className="forecast-scorecard-eyebrow">POINT-IN-TIME MODEL GOVERNANCE</p>
          <h1>研究預測模型成績單</h1>
          <p>只評分已封存且已成熟的預測，並用預測當時可取得的歷史結果建立基準。</p>
        </div>
        <button className="admin-link" type="button" onClick={load} disabled={loading}>
          {loading ? '更新中…' : '重新整理'}
        </button>
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

      {error && <div className="admin-error" role="alert">{error}</div>}

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

      <section>
        <h2 className="admin-section-title">整體樣本外表現</h2>
        <div className="forecast-score-metrics">
          <MetricCard label="已成熟預測" value={count(metric(overall, 'observations'))} note="去重後的不可變 forecast/outcome" />
          <MetricCard label="獨立 issue dates" value={count(metric(overall, 'issue_dates'))} note="跨幣同日不當成獨立日期" />
          <MetricCard label="Brier score" value={decimal(metric(overall, 'brier_score'))} note="越低越好" />
          <MetricCard
            label="Brier skill"
            value={skill(brierSkill)}
            note="相對 forecast-time expanding baseline"
            tone={finite(brierSkill) > 0 ? 'good' : finite(brierSkill) < 0 ? 'bad' : ''}
          />
          <MetricCard label="Log loss" value={decimal(metric(overall, 'log_loss'))} note="重罰過度自信的錯誤" />
          <MetricCard label="校準誤差 ECE" value={percent(metric(overall, 'expected_calibration_error'))} note="僅作輔助，不單獨判定" />
          <MetricCard label="Ready coverage" value={percent(metric(overall, 'coverage'))} note={`${count(metric(overall, 'ready_count'))} 筆實際發布`} />
          <MetricCard label="Ready 命中率" value={percent(readyAccuracy(overall))} note="必須與 coverage 同看" />
          <MetricCard label="區間覆蓋" value={percent(metric(interval, 'empirical_coverage') ?? metric(interval, 'coverage'))} note={`平均寬度 ${decimal(metric(interval, 'mean_width_pct') ?? metric(interval, 'mean_width'), 2)}%`} />
          <MetricCard label="WIS" value={decimal(metric(interval, 'weighted_interval_score'))} note="兼顧區間寬度與漏包懲罰" />
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
                return (
                  <tr key={group.horizon_days ?? group.horizon}>
                    <td>{group.horizon_days ?? group.horizon} 日</td>
                    <td>{count(metric(group, 'observations'))}</td>
                    <td>{count(metric(group, 'issue_dates'))}</td>
                    <td>{decimal(metric(group, 'brier_score'))}</td>
                    <td>{decimal(metric(group, 'baseline_brier_score'))}</td>
                    <td className={finite(groupSkill) > 0 ? 'score-good' : finite(groupSkill) < 0 ? 'score-bad' : ''}>{skill(groupSkill)}</td>
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
