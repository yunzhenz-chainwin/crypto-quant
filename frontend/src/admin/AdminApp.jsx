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
        <button className="admin-tab" disabled title="P3">管理（即將推出）</button>
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

// ── 入口 ────────────────────────────────────────────────────────────────────
export default function AdminApp() {
  const [authed, setAuthed] = useState(!!getToken())
  const [tab, setTab]       = useState('monitor')

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />

  const logout = () => { clearToken(); setAuthed(false) }

  return (
    <div className="admin-app">
      <AdminHeader tab={tab} setTab={setTab} onLogout={logout} />
      {tab === 'monitor' ? <Dashboard onLogout={logout} /> : <TasksPage onLogout={logout} />}
    </div>
  )
}
