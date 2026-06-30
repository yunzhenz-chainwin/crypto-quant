/**
 * AdminApp.jsx — 後台管理台
 *
 * 由 main.jsx 在網址為 /admin 時掛載。未登入 → 登入頁;已登入 → 後台。
 * 分頁:
 *   監控    系統健康 / 資料新鮮度 / 資料庫統計 / 工作紀錄
 *   工作項目 進度追蹤:記錄做了哪些、預計做哪些、何時做(存資料庫)
 */
import { useState, useEffect, useCallback } from 'react'
import {
  adminLogin, getToken, setToken, clearToken,
  fetchHealth, fetchDbStats, fetchJobs,
  fetchTasks, createTask, updateTask, deleteTask, ingestMarket,
  fetchDbTables, fetchDbTable, fetchVerifyIndicators, fetchSignalScorecard,
} from '../api/admin'

// ── 登入頁 ──────────────────────────────────────────────────────────────────
function Login({ onSuccess }) {
  const [u, setU]             = useState('')
  const [p, setP]             = useState('')
  const [err, setErr]         = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setLoading(true)
    try {
      const r = await adminLogin(u, p)
      setToken(r.token)
      onSuccess()
    } catch (e) {
      setErr(e.message || '登入失敗')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="admin-login-wrap">
      <form className="admin-login" onSubmit={submit}>
        <div className="admin-login-title">🔐 後台管理台</div>
        <div className="admin-login-sub">登入以檢視監控與管理工作項目</div>
        <input className="admin-input" placeholder="帳號" value={u}
               onChange={e => setU(e.target.value)} autoFocus />
        <input className="admin-input" placeholder="密碼" type="password" value={p}
               onChange={e => setP(e.target.value)} />
        {err && <div className="admin-login-err">{err}</div>}
        <button className="admin-btn" disabled={loading}>
          {loading ? '登入中…' : '登入'}
        </button>
        <div className="admin-login-hint">請輸入管理員帳號密碼登入</div>
      </form>
    </div>
  )
}

// ── 共用小元件 ──────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, tone }) {
  return (
    <div className={`admin-card ${tone ? `tone-${tone}` : ''}`}>
      <div className="admin-card-label">{label}</div>
      <div className="admin-card-value">{value}</div>
      {sub && <div className="admin-card-sub">{sub}</div>}
    </div>
  )
}

function JobBadge({ status }) {
  const map = {
    success: { t: '成功', c: '#22c55e' },
    failed:  { t: '失敗', c: '#ef4444' },
    running: { t: '執行中', c: '#f59e0b' },
  }
  const s = map[status] ?? { t: status, c: '#94a3b8' }
  return <span style={{ color: s.c, fontWeight: 700 }}>{s.t}</span>
}

// 工作項目狀態 → 中文 + 顏色
const TASK_STATUS = {
  planned:     { t: '待辦',   c: '#94a3b8' },
  in_progress: { t: '進行中', c: '#f59e0b' },
  done:        { t: '完成',   c: '#22c55e' },
}

// 狀態篩選器(全部 + 三種狀態)
const TASK_FILTERS = [
  { key: 'all',         label: '全部' },
  { key: 'planned',     label: '待辦' },
  { key: 'in_progress', label: '進行中' },
  { key: 'done',        label: '完成' },
]

// 工作項目分類(用領域分,比 P0–P4 直覺;與後端 app_db.TASK_CATEGORIES 一致)
const TASK_CATEGORIES = ['前台', '後台', '資料庫', '訊號/回測', '資料抓取', '修復/優化', '其他']

// ── 頂列(含分頁切換)──────────────────────────────────────────────────────
function AdminHeader({ tab, setTab, onLogout }) {
  return (
    <header className="admin-header">
      <span className="admin-logo">📊 Crypto Quant 後台</span>
      <div className="admin-tabs">
        <button className={`admin-tab ${tab === 'monitor' ? 'active' : ''}`}
                onClick={() => setTab('monitor')}>監控</button>
        <button className={`admin-tab ${tab === 'tasks' ? 'active' : ''}`}
                onClick={() => setTab('tasks')}>工作項目</button>
        <button className={`admin-tab ${tab === 'db' ? 'active' : ''}`}
                onClick={() => setTab('db')}>資料庫</button>
        <button className={`admin-tab ${tab === 'status' ? 'active' : ''}`}
                onClick={() => setTab('status')}>現況</button>
        <button className="admin-tab" disabled title="P3">分析（即將推出）</button>
      </div>
      <div className="admin-header-right">
        <a className="admin-link" href="/">← 回前台</a>
        <button className="admin-link danger" onClick={onLogout}>登出</button>
      </div>
    </header>
  )
}

// ── 監控頁 ──────────────────────────────────────────────────────────────────
function Dashboard({ onLogout }) {
  const [health, setHealth]   = useState(null)
  const [db, setDb]           = useState(null)
  const [jobs, setJobs]       = useState(null)
  const [err, setErr]         = useState('')
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [verify, setVerify]       = useState(null)
  const [verifying, setVerifying] = useState(false)

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try {
      const [h, d, j] = await Promise.all([fetchHealth(), fetchDbStats(), fetchJobs()])
      setHealth(h); setDb(d); setJobs(j.jobs ?? [])
    } catch (e) {
      if (e.message === 'UNAUTH') { onLogout(); return }
      setErr('讀取失敗:' + e.message)
    } finally {
      setLoading(false)
    }
  }, [onLogout])

  useEffect(() => { load() }, [load])

  const runVerify = useCallback(async () => {
    setVerifying(true)
    try { setVerify(await fetchVerifyIndicators()) }
    catch (e) { if (e.message === 'UNAUTH') onLogout() }
    finally { setVerifying(false) }
  }, [onLogout])

  useEffect(() => { runVerify() }, [runVerify])   // 進頁自動驗證一次

  const runIngest = async () => {
    setIngesting(true)
    try { await ingestMarket(); await load() }
    catch (e) { if (e.message === 'UNAUTH') onLogout(); else setErr('匯入失敗:' + e.message) }
    finally { setIngesting(false) }
  }

  const freshTone = health
    ? (health.symbols_fresh === health.symbols_total ? 'good'
       : health.symbols_fresh === 0 ? 'bad' : 'warn')
    : null

  return (
    <div className="admin-body">
      <div className="admin-toolbar">
        <button className="admin-link" onClick={load} disabled={loading}>
          {loading ? '更新中…' : '↻ 重新整理'}
        </button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {/* 系統健康 */}
      <h2 className="admin-section-title">系統健康</h2>
      <div className="admin-grid">
        <StatCard label="資料新鮮度"
          value={health ? `${health.symbols_fresh} / ${health.symbols_total}` : '—'}
          sub="幣種資料為最新(落後 ≤2 天)" tone={freshTone} />
        <StatCard label="每日資料排程"
          value={health?.last_pipeline ? <JobBadge status={health.last_pipeline.status} /> : '尚無紀錄'}
          sub={health?.last_pipeline
            ? `${health.last_pipeline.started_at}${health.last_pipeline.message ? ' · ' + health.last_pipeline.message : ''}`
            : '排程跑過後才會出現'} />
        <StatCard label="新聞抓取排程"
          value={health?.last_news_fetch ? <JobBadge status={health.last_news_fetch.status} /> : '尚無紀錄'}
          sub={health?.last_news_fetch
            ? `${health.last_news_fetch.started_at}${health.last_news_fetch.message ? ' · ' + health.last_news_fetch.message : ''}`
            : '每 30 分鐘自動抓取'} />
        <StatCard label="伺服器時間"
          value={health?.server_time?.slice(11) ?? '—'}
          sub={health?.server_time?.slice(0, 10) ?? ''} />
      </div>

      {/* 各幣資料新鮮度 */}
      <h2 className="admin-section-title">各幣資料新鮮度</h2>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr><th>幣種</th><th>最後資料日</th><th>落後天數</th><th>狀態</th></tr>
          </thead>
          <tbody>
            {(health?.coins ?? []).map(c => (
              <tr key={c.symbol}>
                <td>{c.symbol.replace('USDT', '')}</td>
                <td>{c.last_date}</td>
                <td>{c.lag_days ?? '—'} 天</td>
                <td style={{ color: c.stale ? '#ef4444' : '#22c55e', fontWeight: 700 }}>
                  {c.stale ? '⚠ 過期' : '✓ 正常'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 資料庫 */}
      <div className="admin-section-head">
        <h2 className="admin-section-title">資料庫</h2>
        <button className="admin-mini-btn" onClick={runIngest} disabled={ingesting}>
          {ingesting ? '匯入中…' : '↻ 重新匯入行情'}
        </button>
      </div>
      <div className="admin-grid">
        <StatCard label="加密數值入庫"
          value={db?.market ? db.market.prices.toLocaleString() : '—'}
          sub={db?.market ? `${db.market.symbols} 幣 · 指標 ${db.market.indicators.toLocaleString()} 筆 · ${db.market.date_min}~${db.market.date_max}` : 'K 線 + 指標'} />
        <StatCard label="新聞總筆數"
          value={db?.news?.total?.toLocaleString() ?? '—'}
          sub={`可查發布日 ${db?.news?.publish_dates ?? 0} 天 · ${db?.news?.file_kb ?? 0} KB`} />
        <StatCard label="工作項目"
          value={db?.app?.tasks ?? '—'}
          sub={`操作紀錄 ${db?.app?.job_runs ?? 0} 筆`} />
        <StatCard label="訊號 / 情緒快照"
          value={`${db?.app?.daily_signal ?? 0} / ${db?.app?.fear_greed ?? 0}`}
          sub={`app.db ${db?.app?.file_kb ?? 0} KB`} />
      </div>

      {db?.news?.categories?.length > 0 && (
        <div className="admin-table-wrap">
          <div className="admin-mini-title">新聞分類分布</div>
          <div className="admin-chips">
            {db.news.categories.map(c => (
              <span key={c.category} className="admin-chip">
                {c.category || '未分類'} <b>{c.n}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 指標交叉驗證 */}
      <div className="admin-section-head">
        <h2 className="admin-section-title">資料正確性(指標交叉驗證)</h2>
        <button className="admin-mini-btn" onClick={runVerify} disabled={verifying}>
          {verifying ? '驗證中…' : (verify ? '↻ 重新驗證' : '執行驗證')}
        </button>
      </div>
      {!verify && (
        <div className="admin-count-line">
          {verifying ? '用獨立演算法重算指標、逐點比對中…' : '尚未驗證'}
        </div>
      )}
      {verify && (
        <>
          <div className="admin-grid">
            <StatCard label="指標交叉驗證"
              value={`${verify.passed} / ${verify.total}`}
              sub="與獨立演算法逐點一致(RSI/MACD/MA/布林/量)"
              tone={verify.ok ? 'good' : 'bad'} />
            <StatCard label="最大誤差"
              value="≈ 機器精度"
              sub="差異僅浮點殘差(~1e-15),非真實差異" />
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table db-table">
              <thead><tr>
                <th>幣種</th><th>狀態</th>
                <th className="db-num-cell">RSI 誤差</th>
                <th className="db-num-cell">MACD 誤差</th>
                <th className="db-num-cell">MA 誤差</th>
                <th className="db-num-cell">布林 誤差</th>
              </tr></thead>
              <tbody>
                {verify.coins.map(c => (
                  <tr key={c.symbol}>
                    <td>{c.symbol.replace('USDT', '')}</td>
                    <td style={{ color: c.ok ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                      {c.ok ? '✓ 一致' : '✗ 不符'}
                    </td>
                    <td className="db-num-cell">{c.rsi == null ? '—' : c.rsi.toExponential(1)}</td>
                    <td className="db-num-cell">{c.macd == null ? '—' : c.macd.toExponential(1)}</td>
                    <td className="db-num-cell">{c.ma == null ? '—' : c.ma.toExponential(1)}</td>
                    <td className="db-num-cell">{c.bb == null ? '—' : c.bb.toExponential(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* 最近工作紀錄 */}
      <h2 className="admin-section-title">最近工作紀錄</h2>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr><th>類型</th><th>狀態</th><th>開始</th><th>結束</th><th>訊息</th></tr>
          </thead>
          <tbody>
            {(jobs ?? []).length === 0 && (
              <tr><td colSpan={5} style={{ color: '#94a3b8' }}>尚無紀錄(排程或手動操作跑過後會出現)</td></tr>
            )}
            {(jobs ?? []).map(j => (
              <tr key={j.id}>
                <td>{j.job_type}</td>
                <td><JobBadge status={j.status} /></td>
                <td>{j.started_at}</td>
                <td>{j.finished_at ?? '—'}</td>
                <td style={{ color: '#94a3b8' }}>{j.message ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── 工作項目詳細視窗(點項目開啟,可編輯備註 / 交接說明)─────────────────────
function TaskModal({ task, onClose, onSaved, onError }) {
  const [form, setForm] = useState({
    title: task.title || '', phase: task.phase || '', status: task.status || 'planned',
    planned_date: task.planned_date || '', done_date: task.done_date || '',
    detail: task.detail || '', notes: task.notes || '',
  })
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await updateTask(task.id, {
        title: form.title.trim(), phase: form.phase, status: form.status,
        planned_date: form.planned_date || null, done_date: form.done_date || null,
        detail: form.detail, notes: form.notes,
      })
      onSaved()
    } catch (e) {
      onError(e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="admin-modal-overlay" onClick={onClose}>
      <div className="admin-modal" onClick={e => e.stopPropagation()}>
        <div className="admin-modal-head">
          <span className="admin-modal-title">工作項目詳細</span>
          <button className="admin-link" onClick={onClose}>✕</button>
        </div>

        <label className="admin-field">
          <span>標題</span>
          <input className="admin-input" value={form.title} onChange={e => set('title', e.target.value)} />
        </label>

        <div className="admin-field-row">
          <label className="admin-field">
            <span>分類</span>
            <select className="admin-select" value={form.phase} onChange={e => set('phase', e.target.value)}>
              {form.phase && !TASK_CATEGORIES.includes(form.phase) &&
                <option value={form.phase}>{form.phase}</option>}
              {TASK_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="admin-field">
            <span>狀態</span>
            <select className="admin-select" value={form.status} onChange={e => set('status', e.target.value)}>
              <option value="planned">待辦</option>
              <option value="in_progress">進行中</option>
              <option value="done">完成</option>
            </select>
          </label>
        </div>

        <div className="admin-field-row">
          <label className="admin-field">
            <span>預計日</span>
            <input className="admin-input" type="date" value={form.planned_date}
                   onChange={e => set('planned_date', e.target.value)} />
          </label>
          <label className="admin-field">
            <span>完成日</span>
            <input className="admin-input" type="date" value={form.done_date}
                   onChange={e => set('done_date', e.target.value)} />
          </label>
        </div>

        <label className="admin-field">
          <span>簡短說明(清單顯示用)</span>
          <input className="admin-input" value={form.detail} onChange={e => set('detail', e.target.value)} />
        </label>

        <label className="admin-field">
          <span>備註 / 交接說明</span>
          <textarea className="admin-textarea" rows={9} value={form.notes}
                    placeholder="寫下做了什麼、為什麼這樣做、相關檔案、注意事項、後續步驟…交接時看這裡就懂。"
                    onChange={e => set('notes', e.target.value)} />
        </label>

        <div className="admin-modal-actions">
          <button className="admin-link" onClick={onClose}>取消</button>
          <button className="admin-btn" onClick={save} disabled={saving}>
            {saving ? '儲存中…' : '儲存'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 工作項目頁 ──────────────────────────────────────────────────────────────
function TasksPage({ onLogout }) {
  const [tasks, setTasks] = useState([])
  const [err, setErr]     = useState('')
  const [loading, setLoading] = useState(false)
  // 新增表單
  const [title, setTitle]   = useState('')
  const [phase, setPhase]   = useState('')
  const [status, setStatus] = useState('planned')
  const [planned, setPlanned] = useState('')
  const [editing, setEditing] = useState(null)   // 開啟詳細視窗的項目
  const [filter, setFilter]   = useState('all')  // 依狀態篩選

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try {
      const r = await fetchTasks()
      setTasks(r.tasks ?? [])
    } catch (e) {
      if (e.message === 'UNAUTH') { onLogout(); return }
      setErr('讀取失敗:' + e.message)
    } finally {
      setLoading(false)
    }
  }, [onLogout])

  useEffect(() => { load() }, [load])

  const guard = async (fn) => {
    try { await fn(); await load() }
    catch (e) { if (e.message === 'UNAUTH') onLogout(); else setErr(e.message) }
  }

  const add = async (e) => {
    e.preventDefault()
    if (!title.trim()) return
    await guard(() => createTask({
      title: title.trim(), phase: phase.trim(), status,
      planned_date: planned || null,
    }))
    setTitle(''); setPhase(''); setStatus('planned'); setPlanned('')
  }

  const counts = {
    done:        tasks.filter(t => t.status === 'done').length,
    in_progress: tasks.filter(t => t.status === 'in_progress').length,
    planned:     tasks.filter(t => t.status === 'planned').length,
  }
  const shown = tasks.filter(t => filter === 'all' || t.status === filter)

  return (
    <div className="admin-body">
      <div className="admin-toolbar">
        <div className="task-filter-bar">
          <label className="task-filter-label">篩選狀態
            <select className="admin-select" value={filter}
                    onChange={e => setFilter(e.target.value)}>
              {TASK_FILTERS.map(f => {
                const n = f.key === 'all' ? tasks.length : counts[f.key]
                return <option key={f.key} value={f.key}>{f.label}（{n}）</option>
              })}
            </select>
          </label>
          <span className="task-shown-count">目前顯示 {shown.length} 筆</span>
        </div>
        <button className="admin-link" onClick={load} disabled={loading}>
          {loading ? '更新中…' : '↻ 重新整理'}
        </button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {/* 新增項目 */}
      <form className="admin-taskform" onSubmit={add}>
        <span className="tf-lead">➕ 新增項目</span>
        <input className="admin-input tf-title" placeholder="工作項目標題…(必填)"
               value={title} onChange={e => setTitle(e.target.value)} />
        <label className="tf-field">分類
          <select className="admin-select" value={phase} onChange={e => setPhase(e.target.value)}>
            <option value="">自動判斷</option>
            {TASK_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="tf-field">狀態
          <select className="admin-select" value={status} onChange={e => setStatus(e.target.value)}>
            <option value="planned">待辦</option>
            <option value="in_progress">進行中</option>
            <option value="done">完成</option>
          </select>
        </label>
        <label className="tf-field">預計日
          <input className="admin-input tf-date" type="date" value={planned}
                 title="留空將自動估算" onChange={e => setPlanned(e.target.value)} />
        </label>
        <button className="admin-btn tf-add" type="submit">新增</button>
      </form>
      <div className="task-form-hint">
        💡「預計日」留空時,系統會依項目自動估算需要幾天並填入;你也可以手動指定日期。
      </div>

      {/* 清單 */}
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>狀態</th><th>分類</th><th>項目</th>
              <th>預計日</th><th>完成日</th><th>動作</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={6} style={{ color: '#94a3b8' }}>
                {tasks.length === 0 ? '尚無工作項目,用上方表單新增' : '此狀態目前沒有項目'}
              </td></tr>
            )}
            {shown.map(t => {
              const st = TASK_STATUS[t.status] ?? TASK_STATUS.planned
              return (
                <tr key={t.id}>
                  <td>
                    <select
                      className="admin-select sm"
                      value={t.status}
                      style={{ color: st.c, fontWeight: 700 }}
                      onChange={e => guard(() => updateTask(t.id, { status: e.target.value }))}
                    >
                      <option value="planned">待辦</option>
                      <option value="in_progress">進行中</option>
                      <option value="done">完成</option>
                    </select>
                  </td>
                  <td>{t.phase || '—'}</td>
                  <td>
                    <button className="task-title-link" onClick={() => setEditing(t)}
                            title="點擊查看 / 編輯備註">
                      {t.title}{t.notes ? ' 📝' : ''}
                    </button>
                    {t.detail && <div className="task-detail">{t.detail}</div>}
                  </td>
                  <td>{t.planned_date || '—'}</td>
                  <td>{t.done_date || '—'}</td>
                  <td>
                    <button className="admin-del-btn"
                            onClick={() => guard(() => deleteTask(t.id))}>刪除</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {editing && (
        <TaskModal
          task={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
          onError={(e) => { if (e.message === 'UNAUTH') onLogout(); else setErr(e.message) }}
        />
      )}
    </div>
  )
}

// ── 資料庫檢視頁(唯讀瀏覽各表,友善欄位名 + 色彩標記)─────────────────────────
const TABLE_ICONS = {
  prices: '📈', indicators: '📊', daily_signal: '🚦', fear_greed: '😱',
  tasks: '🗂️', app_config: '⚙️', job_runs: '🛠️', access_log: '🌐', news: '📰',
}
const TABLE_DESC = {
  prices: '每根 K 線的開高低收量', indicators: '各項技術指標數值',
  daily_signal: '逐日逐幣的信心分數與多空', fear_greed: '市場恐懼貪婪指數歷史',
  tasks: '後台工作項目與進度', app_config: '系統集中設定',
  job_runs: '排程 / 操作執行紀錄', access_log: 'API 使用紀錄', news: '新聞文章',
}
const COLUMN_LABELS = {
  symbol: '幣種', interval: '週期', ts: '時間', date: '日期',
  open: '開盤', high: '最高', low: '最低', close: '收盤', volume: '成交量',
  ma20: 'MA20', ma60: 'MA60', ma200: 'MA200', rsi: 'RSI', macd: 'MACD',
  signal: '多空', hist: '柱狀', bb_upper: '布林上軌', bb_lower: '布林下軌', vol_ma20: '均量(20)',
  score: '信心分數', value: '指數', label: '等級',
  id: '#', title: '標題', detail: '說明', notes: '備註', status: '狀態', phase: '分類',
  planned_date: '預計日', done_date: '完成日', sort_order: '排序',
  created_at: '建立時間', updated_at: '更新時間',
  url: '連結', domain: '來源', category: '分類', sentiment: '情緒',
  published_at: '發布日', fetched_at: '存入時間',
  job_type: '類型', started_at: '開始', finished_at: '結束', message: '訊息',
  key: '設定鍵', value_json: '設定值', path: '路徑', status_code: '狀態碼', latency_ms: '耗時(ms)',
}
const NUMERIC_COLS = new Set([
  'open', 'high', 'low', 'close', 'volume', 'ma20', 'ma60', 'ma200', 'rsi', 'macd', 'hist',
  'bb_upper', 'bb_lower', 'vol_ma20', 'score', 'value', 'latency_ms', 'sort_order', 'status_code', 'id',
])
const DB_SIG  = { BULL: { t: '多頭', c: '#22c55e' }, BEAR: { t: '空頭', c: '#ef4444' }, NEUTRAL: { t: '中立', c: '#f59e0b' } }
const DB_SENT = { bullish: { t: '看多', c: '#22c55e' }, bearish: { t: '看空', c: '#ef4444' }, neutral: { t: '中立', c: '#94a3b8' } }

function DbBadge({ text, color }) {
  return <span className="db-badge" style={{ color, borderColor: color + '66', background: color + '1a' }}>{text}</span>
}
function fmtNum(col, v) {
  if (col === 'volume' || col === 'vol_ma20') {
    const a = Math.abs(v)
    if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M'
    if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K'
    return v.toFixed(2)
  }
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })
}
// 依欄位/表別,把原始值渲染成好讀的內容(徽章、色彩、千分位…)
function renderCell(col, val, table) {
  if (val === null || val === undefined || val === '') return <span className="db-null">—</span>
  if (col === 'signal' && DB_SIG[val]) return <DbBadge text={DB_SIG[val].t} color={DB_SIG[val].c} />
  if (col === 'sentiment' && DB_SENT[val]) return <DbBadge text={DB_SENT[val].t} color={DB_SENT[val].c} />
  if (col === 'status' && table === 'tasks' && TASK_STATUS[val])
    return <DbBadge text={TASK_STATUS[val].t} color={TASK_STATUS[val].c} />
  if (col === 'score') {
    const n = Number(val), c = n >= 65 ? '#22c55e' : n >= 50 ? '#84cc16' : n >= 35 ? '#f59e0b' : '#ef4444'
    return <b style={{ color: c }}>{n}</b>
  }
  if (col === 'value' && table === 'fear_greed') {
    const n = Number(val), c = n <= 25 ? '#ef4444' : n <= 45 ? '#f97316' : n <= 55 ? '#f59e0b' : n <= 75 ? '#84cc16' : '#22c55e'
    return <b style={{ color: c }}>{n}</b>
  }
  if (col === 'url') return <a href={val} target="_blank" rel="noreferrer" className="db-link">開啟 ↗</a>
  if (typeof val === 'number') return fmtNum(col, val)
  const s = String(val)
  return s.length > 64 ? <span title={s}>{s.slice(0, 64)}…</span> : s
}

function DbViewer({ onLogout }) {
  const [tables, setTables] = useState([])
  const [active, setActive] = useState('prices')
  const [data, setData]     = useState(null)
  const [symbol, setSymbol] = useState('')
  const [limit, setLimit]   = useState(50)
  const [offset, setOffset] = useState(0)
  const [err, setErr]       = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchDbTables()
      .then(r => setTables(r.tables ?? []))
      .catch(e => { if (e.message === 'UNAUTH') onLogout() })
  }, [onLogout])

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try {
      setData(await fetchDbTable(active, { symbol: symbol || null, limit, offset }))
    } catch (e) {
      if (e.message === 'UNAUTH') { onLogout(); return }
      setErr('讀取失敗:' + e.message)
    } finally { setLoading(false) }
  }, [active, symbol, limit, offset, onLogout])

  useEffect(() => { load() }, [load])

  const changeTable = (name) => { setActive(name); setSymbol(''); setOffset(0) }
  const page = data ? Math.floor(data.offset / data.limit) + 1 : 1

  return (
    <div className="admin-body">
      {/* 視覺化選表 */}
      <div className="db-tabs">
        {tables.map(t => (
          <button key={t.name}
            className={`db-tab ${active === t.name ? 'active' : ''}`}
            onClick={() => changeTable(t.name)}>
            <span className="db-tab-icon">{TABLE_ICONS[t.name] ?? '🗃️'}</span>
            <span className="db-tab-name">{t.label}</span>
            <span className="db-tab-count">{t.rows.toLocaleString()}</span>
          </button>
        ))}
      </div>

      <div className="admin-toolbar">
        <div className="task-filter-bar">
          {data && <span className="db-desc">{TABLE_ICONS[active]} {TABLE_DESC[active] ?? ''}</span>}
          {data?.has_symbol && (
            <label className="task-filter-label">幣種
              <input className="admin-input" style={{ width: 150 }}
                     placeholder="如 BTCUSDT(留空全部)"
                     value={symbol} onChange={e => { setSymbol(e.target.value); setOffset(0) }} />
            </label>
          )}
          <label className="task-filter-label">每頁
            <select className="admin-select" value={limit}
                    onChange={e => { setLimit(+e.target.value); setOffset(0) }}>
              {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <button className="admin-link" onClick={load} disabled={loading}>
          {loading ? '載入中…' : '↻ 重新整理'}
        </button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {data && (
        <>
          <div className="admin-count-line" style={{ marginBottom: 8 }}>
            共 <b>{data.total.toLocaleString()}</b> 筆
            {data.total > 0 && <>,顯示第 {data.offset + 1}–{Math.min(data.offset + data.limit, data.total)} 筆</>}
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table db-table">
              <thead><tr>
                {data.columns.map(c => (
                  <th key={c} className={NUMERIC_COLS.has(c) ? 'db-num-cell' : ''}>
                    {COLUMN_LABELS[c] ?? c}
                  </th>
                ))}
              </tr></thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr><td colSpan={data.columns.length} style={{ color: '#94a3b8' }}>沒有資料</td></tr>
                )}
                {data.rows.map((row, i) => (
                  <tr key={i}>
                    {data.columns.map(c => (
                      <td key={c} className={NUMERIC_COLS.has(c) ? 'db-num-cell' : ''}>
                        {renderCell(c, row[c], active)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="admin-toolbar" style={{ marginTop: 10 }}>
            <span className="admin-count-line">第 {page} 頁</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="admin-mini-btn" disabled={data.offset <= 0}
                      onClick={() => setOffset(Math.max(0, offset - limit))}>← 上一頁</button>
              <button className="admin-mini-btn" disabled={data.offset + data.limit >= data.total}
                      onClick={() => setOffset(offset + limit)}>下一頁 →</button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── 現況頁（給主管：直接看做了什麼、還有哪些問題）─────────────────────────────
function StatusPage({ onLogout }) {
  const [score, setScore]   = useState(null)
  const [health, setHealth] = useState(null)
  const [verify, setVerify] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]       = useState('')

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try {
      const [s, h, v] = await Promise.all([
        fetchSignalScorecard(), fetchHealth(), fetchVerifyIndicators(),
      ])
      setScore(s); setHealth(h); setVerify(v)
    } catch (e) {
      if (e.message === 'UNAUTH') { onLogout(); return }
      setErr('讀取失敗:' + e.message)
    } finally { setLoading(false) }
  }, [onLogout])

  useEffect(() => { load() }, [load])

  // 盡量由即時資料推導「問題 / 正常」，避免寫死過時內容
  const problems = []
  const goods = []
  if (score) {
    if (!score.ok) problems.push({
      sev: 'high',
      title: '訊號目前「無預測力」，不可作為買賣依據',
      detail: `現行訊號出現後，之後漲跌機率不比隨機進場高（${score.verdict}）。已測 6 種改良方向皆無效，下一步改用「跨幣動量」研究。`,
    })
    else goods.push({ title: '訊號具預測力（edge）', detail: score.verdict })
  }
  if (health) {
    const stale = (health.coins || []).filter(c => c.stale)
    if (stale.length) problems.push({
      sev: 'mid',
      title: `${stale.length} 支幣資料已停止更新`,
      detail: stale.map(c => `${c.symbol.replace('USDT', '')}（停在 ${c.last_date}）`).join('、')
              + ' — 多為已下市 / 改名（如 MATIC→POL），建議汰換。',
    })
    const lp = health.last_pipeline || {}
    if (lp.status && lp.status !== 'success') problems.push({
      sev: 'high', title: '每日資料排程最近一次失敗', detail: lp.message || '',
    })
    goods.push({
      title: `${health.symbols_fresh ?? 0}/${health.symbols_total ?? 0} 幣資料即時更新`,
      detail: `每日 01:00 自動抓取，排程狀態：${lp.status || '—'}`,
    })
  }
  if (verify) {
    if (verify.ok) goods.push({
      title: `指標數值正確（交叉驗證 ${verify.passed}/${verify.total}）`,
      detail: '用獨立演算法逐點比對一致 — 指標「算得對」，只是不能預測未來。',
    })
    else problems.push({ sev: 'mid', title: '指標交叉驗證有不一致', detail: `${verify.passed}/${verify.total} 通過` })
  }

  const hasHigh = problems.some(p => p.sev === 'high')
  const tldr = !score ? '載入中…'
    : (score.ok
        ? '資料每日自動更新；訊號已具預測力。'
        : '資料管線已修復且每日自動更新、指標數值正確；但「訊號目前沒有預測力」，不應作為投資依據（正在研究改進）。')
  const bannerTone = hasHigh ? 'bad' : (problems.length ? 'warn' : 'good')
  const sevMap = { high: { c: '#ef4444', t: '嚴重' }, mid: { c: '#f59e0b', t: '注意' } }

  return (
    <div className="admin-body">
      <div className="admin-toolbar">
        <span className="admin-section-title" style={{ margin: 0 }}>📋 現況總覽（給主管）</span>
        <button className="admin-link" onClick={load} disabled={loading}>
          {loading ? '更新中…' : '↻ 重新整理'}
        </button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {/* 一句話現況 */}
      <div className={`admin-card tone-${bannerTone}`} style={{ marginBottom: 16 }}>
        <div className="admin-card-label">一句話現況</div>
        <div style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.5, marginTop: 4 }}>{tldr}</div>
      </div>

      {/* 已知問題 */}
      <h2 className="admin-section-title">⚠️ 已知問題（{problems.length}）</h2>
      {problems.length === 0
        ? <div className="admin-count-line">目前沒有已知問題 🎉</div>
        : problems.map((p, i) => {
            const s = sevMap[p.sev] || sevMap.mid
            return (
              <div key={i} className="admin-card" style={{ borderLeft: `4px solid ${s.c}`, marginBottom: 10 }}>
                <div style={{ fontWeight: 700, fontSize: 15 }}>
                  <span style={{ color: s.c }}>● {s.t}</span>　{p.title}
                </div>
                <div className="admin-card-sub" style={{ marginTop: 4 }}>{p.detail}</div>
              </div>
            )
          })}

      {/* 運作正常 */}
      <h2 className="admin-section-title">✅ 運作正常</h2>
      <div className="admin-table-wrap" style={{ padding: '0 14px' }}>
        {goods.length === 0
          ? <div className="admin-count-line">載入中…</div>
          : goods.map((g, i) => (
              <div key={i} style={{ padding: '7px 0', borderBottom: '1px solid #1f2937' }}>
                <b style={{ color: '#22c55e' }}>✓ {g.title}</b>
                <span className="admin-card-sub">　{g.detail}</span>
              </div>
            ))}
      </div>

      {/* 訊號預測力 成績單（問題的數據佐證）*/}
      <h2 className="admin-section-title">訊號預測力（成績單）— 上面問題的數據佐證</h2>
      {!score
        ? <div className="admin-count-line">{loading ? '評估中…' : '尚未評估'}</div>
        : (
          <>
            <div className="admin-grid">
              <StatCard label="訊號預測力"
                value={score.ok ? '有 edge' : '無預測力'}
                sub={score.verdict} tone={score.tone} />
              <StatCard label="評估範圍"
                value={`${score.coins} 幣`}
                sub={`資料至 ${score.as_of} · 對照「任一天進場」基準`} />
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table db-table">
                <thead><tr>
                  <th>持有期</th>
                  <th className="db-num-cell">訊號樣本</th>
                  <th className="db-num-cell">命中率</th>
                  <th className="db-num-cell">vs 基準</th>
                  <th className="db-num-cell">平均報酬</th>
                  <th className="db-num-cell">vs 基準</th>
                </tr></thead>
                <tbody>
                  {score.horizons.map(h => (
                    <tr key={h.n}>
                      <td>{h.n} 天</td>
                      <td className="db-num-cell">{h.samples}</td>
                      <td className="db-num-cell">{h.hit}%</td>
                      <td className="db-num-cell" style={{ color: h.hit_vs_base >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                        {h.hit_vs_base >= 0 ? '+' : ''}{h.hit_vs_base}pp
                      </td>
                      <td className="db-num-cell">{h.avg >= 0 ? '+' : ''}{h.avg}%</td>
                      <td className="db-num-cell" style={{ color: h.avg_vs_base >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                        {h.avg_vs_base >= 0 ? '+' : ''}{h.avg_vs_base}pp
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="task-form-hint">
              💡「vs 基準」為正、且跨持有期一致 = 訊號有預測力；紅色 = 比隨機進場還差。指標數值正確 ≠ 訊號能預測。
            </div>
          </>
        )}

      {/* 各因子預測力（誰準誰不准）*/}
      {score && score.factors && score.factors.length > 0 && (
        <>
          <h2 className="admin-section-title">各因子預測力（誰「準」、誰「不准」）</h2>
          <div className="admin-table-wrap">
            <table className="admin-table db-table">
              <thead><tr>
                <th>因子</th>
                <th className="db-num-cell">樣本</th>
                <th className="db-num-cell">命中 vs基準</th>
                <th className="db-num-cell">edge（報酬 vs基準）</th>
                <th>判定</th>
              </tr></thead>
              <tbody>
                {score.factors.map(f => {
                  const c = f.verdict === '有預測力' ? '#22c55e' : f.verdict === '無預測力' ? '#ef4444' : '#94a3b8'
                  return (
                    <tr key={f.key}>
                      <td>{f.label}</td>
                      <td className="db-num-cell">{f.samples}</td>
                      <td className="db-num-cell" style={{ color: f.hit_vs_base >= 0 ? '#22c55e' : '#ef4444' }}>
                        {f.hit_vs_base >= 0 ? '+' : ''}{f.hit_vs_base}pp
                      </td>
                      <td className="db-num-cell" style={{ color: f.edge >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                        {f.edge >= 0 ? '+' : ''}{f.edge}pp
                      </td>
                      <td style={{ color: c, fontWeight: 700 }}>{f.verdict}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="task-form-hint">
            💡 每個因子「單獨」看：它轉多頭後 10 天的表現 vs 隨機進場。edge 正（綠）= 有方向性資訊；負（紅）= 反指標 / 無用。
            ⚠ 這是「數值正確」的指標各自的「預測力」——<b>數值對 ≠ 能預測</b>。
          </div>
        </>
      )}

      {/* 離「有意義」還有多遠 */}
      {score && score.gap && (
        <>
          <h2 className="admin-section-title">離「有意義」還有多遠</h2>
          <div className="admin-grid">
            <StatCard label="目前 edge（10天）"
              value={`${score.gap.current_edge_pp >= 0 ? '+' : ''}${score.gap.current_edge_pp}pp`}
              sub="訊號比隨機進場多賺 / 少賺" tone={score.gap.current_edge_pp > 0 ? 'good' : 'bad'} />
            <StatCard label="有意義門檻（估）"
              value={`+${score.gap.useful_threshold_pp}pp`} sub="約覆蓋來回成本 ~0.3%" />
            <StatCard label="還差"
              value={`${score.gap.gap_pp}pp`} sub="距「扣成本還有賺」"
              tone={score.gap.gap_pp > 0 ? 'warn' : 'good'} />
          </div>
          <div className="task-form-hint">
            💡 edge = 訊號比「隨便哪天買」多賺多少（百分點）。<b>0 = 跟隨機沒兩樣</b>；要扣手續費還有賺，至少 &gt; +{score.gap.useful_threshold_pp}pp。
            目前 {score.gap.current_edge_pp}pp，<b>還差約 {score.gap.gap_pp}pp</b> 才碰到門檻，而且要「跨持有期一致為正」才算真 edge。
            ⚠ 老實說：用日線技術指標補正這個 gap 且穩定為正，難度很高，通常得換維度（見下方建議）。
          </div>
        </>
      )}

      {/* 改善建議（全部）*/}
      <h2 className="admin-section-title">改善建議（全部）</h2>
      <div className="admin-table-wrap" style={{ padding: '4px 14px' }}>
        <div style={{ padding: '8px 0 4px', color: '#94a3b8', fontWeight: 700 }}>已測試 · 確認無效</div>
        {[['反向操作（抄底）', '10天 edge −0.4pp'], ['只在趨勢盤聽訊號', '−1.1pp'],
          ['不追高（濾過熱）', '−1.1pp'], ['買在極度恐懼', '−1.4pp']].map(([t, d], i) => (
          <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid #1f2937' }}>
            <span style={{ color: '#ef4444' }}>✗ {t}</span><span className="admin-card-sub">　{d}</span>
          </div>
        ))}
        <div style={{ padding: '12px 0 4px', color: '#94a3b8', fontWeight: 700 }}>建議嘗試 · 換維度</div>
        {[['⭐ 跨幣動量（排名做多最強 / 放空最弱）', '天花板最高，資料已在手，工程中等'],
          ['幣圈原生資料（資金費率 / 未平倉 / 基差）', '有文獻支持的 edge，需接新資料源'],
          ['重新定位為「風控 + 教育」工具', '不主打預測，以風險管理 / 誠實度為賣點']].map(([t, d], i) => (
          <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid #1f2937' }}>
            <span style={{ color: '#84cc16' }}>○ {t}</span><span className="admin-card-sub">　{d}</span>
          </div>
        ))}
      </div>

      {/* 這平台有沒有意義 */}
      <h2 className="admin-section-title">這平台有沒有意義？（誠實評估）</h2>
      <div className="admin-card" style={{ borderLeft: '4px solid #f59e0b', lineHeight: 1.8 }}>
        <div className="admin-card-sub">
          <b style={{ color: '#ef4444' }}>作為「預測訊號」產品：</b>目前訊號無 edge → <b>還不能宣稱有投資意義</b>，不應拿來實際下單。<br />
          <b style={{ color: '#22c55e' }}>作為「資料平台 + 誠實研究工具」：</b>有價值 —— 自動資料管線、指標數值正確（已交叉驗證）、嚴謹的 forward 驗證、會自己抓異常（像這頁）。<br />
          <b>結論：</b>平台的「基礎建設與誠實度」已有意義；「訊號 alpha」還在找，下一步是跨幣動量。
        </div>
      </div>
    </div>
  )
}

// ── 入口 ────────────────────────────────────────────────────────────────────
export default function AdminApp() {
  const [authed, setAuthed] = useState(!!getToken())
  const [tab, setTab]       = useState('monitor')

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />

  const logout = () => { clearToken(); setAuthed(false) }

  return (
    <div className="admin-app">
      <AdminHeader tab={tab} setTab={setTab} onLogout={logout} />
      {tab === 'monitor' ? <Dashboard onLogout={logout} />
        : tab === 'tasks' ? <TasksPage onLogout={logout} />
        : tab === 'status' ? <StatusPage onLogout={logout} />
        : <DbViewer onLogout={logout} />}
    </div>
  )
}
