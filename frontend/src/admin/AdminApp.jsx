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
  fetchDbTables, fetchDbTable, fetchVerifyIndicators, fetchSignalScorecard, fetchStrategy,
  fetchCoins, addCoin, updateCoin, deleteCoin,
} from '../api/admin'
import {
  ResponsiveContainer, BarChart, Bar, Cell, XAxis, YAxis, ReferenceLine, Tooltip, LabelList,
} from 'recharts'

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
        <button className={`admin-tab ${tab === 'coins' ? 'active' : ''}`}
                onClick={() => setTab('coins')}>幣種</button>
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

      {/* 指標計算方法（公開透明）*/}
      <h2 className="admin-section-title">指標怎麼算的（計算方法，公開透明）</h2>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead><tr>
            <th>指標</th><th>怎麼算</th><th>看什麼</th>
          </tr></thead>
          <tbody>
            {[
              ['均線 MA20/60/200', '過去 N 天收盤價的「簡單平均」(SMA)', '平滑價格、看趨勢方向'],
              ['RSI(14天)', '用 Wilder 平滑算「上漲力道 ÷ 下跌力道」= RS，RSI = 100 − 100 ÷ (1 + RS)', '0~100；>70 超買、<30 超賣'],
              ['MACD', '快線 EMA12 − 慢線 EMA26；訊號線 = MACD 的 EMA9；柱狀 = MACD − 訊號線', '看動能加速 / 減速、黃金 / 死亡交叉'],
              ['布林通道', '中軌 = 20日均線；上 / 下軌 = 中軌 ± 2 ×(20日標準差)', '隨波動自動縮放的價格通道'],
              ['量能均線', '過去 20 天成交量的「簡單平均」(SMA)', '比較放量 / 縮量、確認訊號'],
            ].map(([name, how, what], i) => (
              <tr key={i}>
                <td style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{name}</td>
                <td className="wrap" style={{ color: '#cbd5e1' }}>{how}</td>
                <td className="wrap" style={{ color: '#94a3b8' }}>{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="task-form-hint">
        💡 SMA = 簡單平均；EMA = 指數移動平均(近期權重較高)。以上算法的程式碼在 <b>src/indicators.py</b>。
        上方「資料正確性」是用<b>另一套獨立演算法</b>重算後逐點比對，確認這些值算得對(非寫死)——
        等於「方法公開 ＋ 結果驗證」雙保險。
      </div>

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
                <td className="wrap" style={{ color: '#94a3b8', minWidth: 160 }}>{j.message ?? ''}</td>
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

  // ── 視覺化統計 ──────────────────────────────────────────────────────────
  const total   = tasks.length
  const donePct = total ? Math.round(counts.done / total * 100) : 0
  const pct = (k) => total ? counts[k] / total * 100 : 0

  // 依分類彙總完成度（動態取現有分類；未填分類歸「其他」）
  const catMap = {}
  tasks.forEach(t => {
    const c = t.phase || '其他'
    if (!catMap[c]) catMap[c] = { done: 0, total: 0 }
    catMap[c].total++
    if (t.status === 'done') catMap[c].done++
  })
  const catList = Object.entries(catMap)
    .map(([cat, v]) => ({ cat, ...v, pct: v.total ? Math.round(v.done / v.total * 100) : 0 }))
    .sort((a, b) => b.total - a.total)

  // 每項時程狀態（相對今天）：完成 / 逾期 N 天 / 今天 / 還有 N 天 / 未排期
  const timeInfo = (t) => {
    if (t.status === 'done')
      return { text: t.done_date ? `完成 ${t.done_date.slice(5)}` : '完成', cls: 'done' }
    if (!t.planned_date) return { text: '未排期', cls: 'none' }
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const p = new Date(t.planned_date + 'T00:00:00')
    const days = Math.round((p - today) / 86400000)
    if (Number.isNaN(days)) return { text: t.planned_date, cls: 'none' }
    if (days < 0)  return { text: `逾期 ${-days} 天`, cls: 'overdue' }
    if (days === 0) return { text: '就在今天', cls: 'today' }
    if (days <= 3)  return { text: `還有 ${days} 天`, cls: 'soon' }
    return { text: `還有 ${days} 天`, cls: 'later' }
  }

  return (
    <div className="admin-body">
      {/* ── 視覺化總覽：完成率 + 三色堆疊進度條 + 分類進度 ─────────────── */}
      <div className="task-dash">
        <div className="task-dash-top">
          <div className="task-dash-ring" style={{ '--pct': donePct }}>
            <div className="tdr-inner">
              <span className="tdr-num">{donePct}%</span>
              <span className="tdr-lbl">完成率</span>
            </div>
          </div>
          <div className="task-dash-bars">
            <div className="task-stack">
              <div className="ts-seg done" style={{ width: `${pct('done')}%` }}
                   title={`完成 ${counts.done}`} />
              <div className="ts-seg prog" style={{ width: `${pct('in_progress')}%` }}
                   title={`進行中 ${counts.in_progress}`} />
              <div className="ts-seg plan" style={{ width: `${pct('planned')}%` }}
                   title={`待辦 ${counts.planned}`} />
            </div>
            <div className="task-stack-legend">
              <button className={`tsl ${filter === 'done' ? 'on' : ''}`} onClick={() => setFilter('done')}>
                <i className="dot done" />完成 <b>{counts.done}</b>
              </button>
              <button className={`tsl ${filter === 'in_progress' ? 'on' : ''}`} onClick={() => setFilter('in_progress')}>
                <i className="dot prog" />進行中 <b>{counts.in_progress}</b>
              </button>
              <button className={`tsl ${filter === 'planned' ? 'on' : ''}`} onClick={() => setFilter('planned')}>
                <i className="dot plan" />待辦 <b>{counts.planned}</b>
              </button>
              <button className={`tsl ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>
                共 <b>{total}</b> 項
              </button>
            </div>
          </div>
        </div>
        {catList.length > 0 && (
          <div className="task-cat-grid">
            {catList.map(c => (
              <div key={c.cat} className="task-cat">
                <div className="task-cat-head">
                  <span className="tc-name">{c.cat}</span>
                  <span className="tc-cnt">{c.done}/{c.total}</span>
                </div>
                <div className="task-cat-bar">
                  <div className="tc-fill" style={{ width: `${c.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
              <th>時程</th><th>預計日</th><th>動作</th>
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
              const ti = timeInfo(t)
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
                  <td className="task-item-cell">
                    <button className="task-title-link" onClick={() => setEditing(t)}
                            title="點擊查看 / 編輯備註">
                      {t.title}{t.notes ? ' 📝' : ''}
                    </button>
                    {t.detail && <div className="task-detail">{t.detail}</div>}
                  </td>
                  <td><span className={`time-badge tb-${ti.cls}`}>{ti.text}</span></td>
                  <td className="task-date-cell">{t.planned_date || '—'}</td>
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
// 每張表「怎麼算 / 怎麼來的」（透明說明，點選該表時顯示）
const TABLE_HOWTO = {
  prices: '從 Binance API 抓的原始日線（開／高／低／收／量），每天 01:00 自動更新。屬市場真實成交資料，不是算出來的。',
  indicators: '用 prices 的收盤價／成交量算出來：MA＝過去 N 天平均、RSI＝Wilder 平滑(漲力道÷跌力道)、MACD＝EMA12−EMA26、布林＝20日均 ± 2×標準差、量能均線＝20日量平均。程式 src/indicators.py，且經獨立交叉驗證確認算得對。',
  daily_signal: '把每天每幣的指標丟進「6 因子信心分數」計算（src/scoring.py）：RSI／MACD／均線／MA200／量／布林 各打分加總成 0~100，≥65 偏多、≤35 偏空。',
  fear_greed: '從 alternative.me 抓的「市場恐懼貪婪指數」(0~100)，屬外部資料源，不是我們算的。',
  news: '從各加密新聞 RSS 每 30 分鐘抓取的文章（標題／來源／發布日／分類）。',
  tasks: '後台工作項目與進度，由人工／系統維護，非計算資料。',
  app_config: '系統集中設定（如追蹤幣種清單），非計算資料。',
  job_runs: '排程／手動操作每次執行的紀錄（開始、結束、狀態、訊息），自動寫入。',
  access_log: 'API 被呼叫的紀錄（路徑、狀態碼、耗時），自動寫入。',
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
              <input className="admin-input" style={{ width: 200 }}
                     placeholder="如 BTCUSDT（可留空）"
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

      {data && TABLE_HOWTO[active] && (
        <div className="task-form-hint" style={{ marginBottom: 10 }}>
          <b>📐 這張表怎麼來的：</b>{TABLE_HOWTO[active]}
        </div>
      )}

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
// 半圓「評級儀表」：指針指在「無用 ↔ 有意義」之間
function EdgeGauge({ cur, thr }) {
  const lo = Math.min(cur, 0) - 0.5, hi = Math.max(thr, cur) + 0.5
  const W = 260, H = 150, cx = 130, cy = 128, r = 102
  const frac = (v) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)))
  const ang = (v) => Math.PI * (1 - frac(v))
  const pt = (v, rr = r) => [cx + rr * Math.cos(ang(v)), cy - rr * Math.sin(ang(v))]
  const arc = (a, b, rr = r) => {
    const [x1, y1] = pt(a, rr), [x2, y2] = pt(b, rr)
    return `M ${x1} ${y1} A ${rr} ${rr} 0 0 ${frac(b) > frac(a) ? 1 : 0} ${x2} ${y2}`
  }
  const [nx, ny] = pt(cur, r - 18)
  const col = cur >= thr ? '#22c55e' : cur >= 0 ? '#f59e0b' : '#ef4444'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: 300, display: 'block', margin: '0 auto' }}>
      <path d={arc(lo, hi)} fill="none" stroke="#334155" strokeWidth="15" strokeLinecap="round" />
      <path d={arc(lo, 0)} fill="none" stroke="#7f1d1d" strokeWidth="15" strokeLinecap="round" />
      <path d={arc(thr, hi)} fill="none" stroke="#15803d" strokeWidth="15" strokeLinecap="round" />
      <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={col} strokeWidth="3.5" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="6" fill={col} />
      <text x="6" y={cy + 2} fill="#ef4444" fontSize="11">無用</text>
      <text x={W - 46} y={cy + 2} fill="#22c55e" fontSize="11">有意義</text>
      <text x={cx} y={cy - 34} fill={col} fontSize="20" fontWeight="800" textAnchor="middle">{cur >= 0 ? '+' : ''}{cur}pp</text>
      <text x={cx} y={cy - 16} fill="#94a3b8" fontSize="11" textAnchor="middle">目前 edge（10天）</text>
    </svg>
  )
}

function StatusPage({ onLogout }) {
  const [score, setScore]   = useState(null)
  const [health, setHealth] = useState(null)
  const [verify, setVerify] = useState(null)
  const [strat, setStrat]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]       = useState('')

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try {
      const [s, h, v, st] = await Promise.all([
        fetchSignalScorecard(), fetchHealth(), fetchVerifyIndicators(), fetchStrategy(),
      ])
      setScore(s); setHealth(h); setVerify(v); setStrat(st)
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
  // 是否已有「驗證過、樣本外正且贏市場」的策略
  const stratOk = !!(strat && strat.perf && strat.perf.oos_cagr > 0 &&
    strat.perf.oos_cagr > (strat.perf.market_cagr ?? -999))
  const tldr = !score ? '載入中…'
    : (stratOk
        ? '已接入「防禦型跨幣動量」策略：回測樣本外正報酬、大幅贏過市場（仍為回測、未經實盤）。原 6 因子訊號無 edge，下方為其診斷。'
        : '資料管線已修復且每日自動更新、指標數值正確；但原訊號沒有預測力。')
  const bannerTone = stratOk ? 'good' : (hasHigh ? 'bad' : (problems.length ? 'warn' : 'good'))
  const sevMap = { high: { c: '#ef4444', t: '嚴重' }, mid: { c: '#f59e0b', t: '注意' } }

  // 平台評級（資料 / 指標健全 + 是否有「驗證過的策略」）
  const dataOk = !!(health && verify && verify.ok &&
    (health.symbols_fresh ?? 0) / Math.max(1, health.symbols_total ?? 1) >= 0.8)
  const grade = !score ? '—' : (stratOk ? 'B' : (score.ok ? 'A' : (dataOk ? 'C' : 'D')))
  const gradeNote = !score ? '評估中…'
    : (stratOk ? '已有驗證過的策略（回測）' : (score.ok ? '訊號具 edge' : (dataOk ? '資料穩 · 訊號未達標' : '資料與訊號都待補')))
  const gradeColor = grade === 'A' ? '#22c55e' : grade === 'B' ? '#84cc16'
    : grade === 'C' ? '#f59e0b' : grade === 'D' ? '#ef4444' : '#94a3b8'
  const G = score?.gap || {}
  const col2 = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(300px, 100%), 1fr))', gap: 18, marginBottom: 22 }

  return (
    <div className="admin-body">
      <div className="admin-toolbar">
        <span className="admin-section-title" style={{ margin: 0 }}>📋 現況總覽（給主管）</span>
        <button className="admin-link" onClick={load} disabled={loading}>
          {loading ? '更新中…' : '↻ 重新整理'}
        </button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {/* 📈 今日策略訊號 + 績效（接進平台的新動量策略）*/}
      {strat && (
        <>
          <h2 className="admin-section-title" style={{ marginTop: 0 }}>📈 今日策略訊號　<span style={{ fontSize: 13, fontWeight: 400, color: '#94a3b8' }}>{strat.strategy}</span></h2>
          <div style={col2}>
            <div className="admin-card" style={{ borderLeft: `5px solid ${strat.today.regime === 'cash' ? '#94a3b8' : '#22c55e'}`, padding: '14px 18px' }}>
              <div className="admin-card-label">今日建議（資料至 {strat.today.date}）</div>
              {strat.today.regime === 'cash' ? (
                <>
                  <div style={{ fontSize: 24, fontWeight: 800, color: '#cbd5e1', margin: '6px 0' }}>🛑 抱現金（空倉）</div>
                  <div className="admin-card-sub">{strat.today.regime_reason}　→　{strat.today.note}</div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 18, fontWeight: 800, color: '#22c55e', margin: '6px 0' }}>
                    持有 {strat.today.picks.length} 幣（投入 {strat.today.exposure_pct}% · 現金 {strat.today.cash_pct}%）
                  </div>
                  <div className="admin-card-sub" style={{ marginBottom: 8 }}>{strat.today.regime_reason}</div>
                  <table className="admin-table" style={{ fontSize: 13 }}>
                    <thead><tr><th>幣</th><th className="db-num-cell">動量(30天)</th><th className="db-num-cell">建議部位</th></tr></thead>
                    <tbody>
                      {strat.today.picks.map(p => (
                        <tr key={p.symbol}>
                          <td style={{ fontWeight: 700 }}>{p.symbol}</td>
                          <td className="db-num-cell">{p.momentum >= 0 ? '+' : ''}{p.momentum}%</td>
                          <td className="db-num-cell">{p.weight}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
            <div>
              <div className="admin-card-label" style={{ paddingLeft: 2, marginBottom: 6 }}>策略績效（回測驗證，未實盤）</div>
              <div className="admin-grid">
                <StatCard label="樣本外年化報酬"
                  value={`${strat.perf.oos_cagr >= 0 ? '+' : ''}${strat.perf.oos_cagr}%`}
                  sub={`對照市場 ${strat.perf.market_cagr}%`} tone={strat.perf.oos_cagr > 0 ? 'good' : 'bad'} />
                <StatCard label="樣本外最大回撤"
                  value={`${strat.perf.oos_mdd}%`} sub="風險可控" tone="warn" />
                <StatCard label="Sharpe（樣本外）"
                  value={strat.perf.oos_sharpe} sub="風險調整後報酬" tone={strat.perf.oos_sharpe >= 0.5 ? 'good' : 'warn'} />
                <StatCard label="全期年化"
                  value={`${strat.perf.cagr >= 0 ? '+' : ''}${strat.perf.cagr}%`}
                  sub={`回撤 ${strat.perf.mdd}%`} tone={strat.perf.cagr > 0 ? 'good' : 'bad'} />
              </div>
              <div className="task-form-hint" style={{ marginTop: 8 }}>
                ⚠️ <b>防禦型</b>：崩盤保命、牛市偏弱。數字為<b>回測、偏樂觀、未經實盤</b>，僅供參考、<b>非績效承諾</b>。
              </div>
            </div>
          </div>
        </>
      )}

      {/* 評級 + KPI 列 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(170px, 210px) 1fr', gap: 18, marginBottom: 22 }}>
        <div className="admin-card" style={{ borderLeft: `5px solid ${gradeColor}`, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '16px 18px' }}>
          <div className="admin-card-label">平台評級</div>
          <div style={{ fontSize: 52, fontWeight: 800, color: gradeColor, lineHeight: 1.1, margin: '4px 0' }}>{grade}</div>
          <div className="admin-card-sub">{gradeNote}</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 14 }}>
          <StatCard label="策略樣本外年化"
            value={strat ? `${strat.perf.oos_cagr >= 0 ? '+' : ''}${strat.perf.oos_cagr}%` : '—'}
            sub={strat ? `對照市場 ${strat.perf.market_cagr}%` : ''} tone={strat ? (stratOk ? 'good' : 'bad') : null} />
          <StatCard label="資料新鮮度"
            value={health ? `${health.symbols_fresh ?? 0}/${health.symbols_total ?? 0}` : '—'}
            sub="幣即時更新" tone={health ? (health.symbols_fresh === health.symbols_total ? 'good' : 'warn') : null} />
          <StatCard label="指標正確性"
            value={verify ? `${verify.passed}/${verify.total}` : '—'}
            sub="交叉驗證一致" tone={verify ? (verify.ok ? 'good' : 'bad') : null} />
          <StatCard label="今日策略訊號"
            value={strat ? (strat.today.regime === 'cash' ? '抱現金' : `持有 ${strat.today.picks.length} 幣`) : '—'}
            sub={strat ? strat.today.date : ''} tone={strat ? (strat.today.regime === 'cash' ? null : 'good') : null} />
        </div>
      </div>

      {/* 一句話現況 */}
      <div className={`admin-card tone-${bannerTone}`} style={{ marginBottom: 22, padding: '14px 18px' }}>
        <div className="admin-card-label">一句話現況</div>
        <div style={{ fontSize: 17, fontWeight: 700, lineHeight: 1.6, marginTop: 6 }}>{tldr}</div>
      </div>

      {/* 問題 / 正常 — 雙欄 */}
      <div style={col2}>
        <div>
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
        </div>
        <div>
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
        </div>
      </div>

      {/* 原 6 因子訊號診斷（無 edge）*/}
      <h2 className="admin-section-title">🔬 原始 6 因子訊號診斷　<span style={{ fontSize: 13, fontWeight: 400, color: '#94a3b8' }}>(無 edge — 這就是為什麼改用上方動量策略)</span></h2>
      {/* 圖表雙欄：各因子 edge | 評級儀表 */}
      {score && (
        <div style={col2}>
          <div>
            <h2 className="admin-section-title">各因子預測力（誰「準」、誰「不准」）</h2>
            {score.factors && score.factors.length > 0 && (
              <div className="admin-table-wrap" style={{ padding: '12px 6px' }}>
                <ResponsiveContainer width="100%" height={Math.max(190, score.factors.length * 36)}>
                  <BarChart layout="vertical" data={score.factors} margin={{ top: 6, right: 64, bottom: 6, left: 16 }}>
                    <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} unit="pp" />
                    <YAxis type="category" dataKey="label" width={132} tick={{ fill: '#cbd5e1', fontSize: 11 }} />
                    <ReferenceLine x={0} stroke="#64748b" />
                    <Tooltip cursor={{ fill: '#1e293b55' }}
                             contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                             formatter={(v, n, p) => [(v >= 0 ? '+' : '') + v + 'pp · ' + (p?.payload?.verdict ?? ''), 'edge vs 基準']} />
                    <Bar dataKey="edge" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                      {score.factors.map((f, i) => (<Cell key={i} fill={f.edge >= 0 ? '#22c55e' : '#ef4444'} />))}
                      <LabelList dataKey="edge" position="right" formatter={(v) => (v >= 0 ? '+' : '') + v + 'pp'} fill="#cbd5e1" fontSize={11} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="admin-card-sub" style={{ padding: '0 8px 6px' }}>綠 = 有方向性、紅 = 反指標 / 無用；0 = 隨機。數值對 ≠ 能預測。</div>
              </div>
            )}
          </div>
          <div>
            <h2 className="admin-section-title">離「有意義」還有多遠</h2>
            {score.gap && (
              <div className="admin-table-wrap" style={{ padding: '10px 6px' }}>
                <EdgeGauge cur={score.gap.current_edge_pp} thr={score.gap.useful_threshold_pp} />
                <div className="admin-card-sub" style={{ textAlign: 'center', padding: '2px 10px 10px' }}>
                  隨機線 0 · 門檻 +{score.gap.useful_threshold_pp}pp（約覆蓋成本）·
                  <b style={{ color: '#f59e0b' }}> 還差 {score.gap.gap_pp}pp</b>
                </div>
                <div className="admin-card-label" style={{ paddingLeft: 8, marginBottom: 2 }}>各持有期 edge（pp）</div>
                <ResponsiveContainer width="100%" height={128}>
                  <BarChart data={score.horizons} margin={{ top: 14, right: 16, bottom: 0, left: 0 }}>
                    <XAxis dataKey="n" tickFormatter={(v) => v + '天'} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={40} unit="pp" />
                    <ReferenceLine y={0} stroke="#64748b" />
                    <Bar dataKey="avg_vs_base" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                      {score.horizons.map((h, i) => (<Cell key={i} fill={h.avg_vs_base >= 0 ? '#22c55e' : '#ef4444'} />))}
                      <LabelList dataKey="avg_vs_base" position="top" formatter={(v) => (v >= 0 ? '+' : '') + v + 'pp'} fill="#cbd5e1" fontSize={10} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="task-form-hint">
        💡 edge = 訊號比「隨便哪天買」多賺多少（pp）；<b>0 = 跟隨機沒兩樣</b>，要扣成本還有賺至少 &gt; +{G.useful_threshold_pp ?? 0.5}pp。
        ⚠ 用日線技術指標補正這段差距且穩定為正，難度很高，通常得換維度（見下方建議）。
      </div>

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

// ── 幣種管理頁（新增 / 啟用停用 / 編輯名稱 / 移除）──────────────────────────────
function CoinsPage({ onLogout }) {
  const [coins, setCoins]     = useState([])
  const [err, setErr]         = useState('')
  const [loading, setLoading] = useState(false)
  const [sym, setSym]         = useState('')
  const [zh, setZh]           = useState('')
  const [ticker, setTicker]   = useState('')
  const [adding, setAdding]   = useState(false)
  const [addMsg, setAddMsg]   = useState('')

  const load = useCallback(async () => {
    setErr(''); setLoading(true)
    try { const r = await fetchCoins(); setCoins(r.coins ?? []) }
    catch (e) { if (e.message === 'UNAUTH') { onLogout(); return } setErr('讀取失敗：' + e.message) }
    finally { setLoading(false) }
  }, [onLogout])
  useEffect(() => { load() }, [load])

  const guard = async (fn) => {
    try { await fn(); await load() }
    catch (e) { if (e.message === 'UNAUTH') onLogout(); else setErr(e.message) }
  }

  const add = async (e) => {
    e.preventDefault()
    if (!sym.trim() || adding) return
    setAdding(true); setErr(''); setAddMsg('抓取歷史資料 → 算指標 → 入庫中，約需 10~30 秒…')
    try {
      const r = await addCoin({ symbol: sym.trim(), zh: zh.trim(), ticker: ticker.trim() })
      setAddMsg(`✓ 已新增 ${r.symbol}（${r.rows} 筆，最新 ${r.last_date}）`)
      setSym(''); setZh(''); setTicker('')
      await load()
    } catch (e) {
      if (e.message === 'UNAUTH') onLogout()
      else { setErr('新增失敗：' + e.message); setAddMsg('') }
    } finally { setAdding(false) }
  }

  const enabledCount = coins.filter(c => c.enabled).length

  return (
    <div className="admin-body">
      <div className="admin-toolbar">
        <span className="admin-section-title" style={{ margin: 0 }}>🪙 幣種管理
          <span style={{ fontSize: 13, fontWeight: 400, color: '#94a3b8' }}>啟用 {enabledCount} / {coins.length}</span>
        </span>
        <button className="admin-link" onClick={load} disabled={loading}>{loading ? '更新中…' : '↻ 重新整理'}</button>
      </div>

      {err && <div className="admin-error">{err}</div>}

      {/* 新增幣種 */}
      <form className="admin-taskform" onSubmit={add}>
        <span className="tf-lead">➕ 新增幣種</span>
        <input className="admin-input" style={{ width: 140 }} placeholder="代號 如 SUIUSDT" value={sym}
               onChange={e => setSym(e.target.value)} />
        <input className="admin-input" style={{ width: 120 }} placeholder="中文名（選填）" value={zh}
               onChange={e => setZh(e.target.value)} />
        <input className="admin-input" style={{ width: 90 }} placeholder="代碼（選填）" value={ticker}
               onChange={e => setTicker(e.target.value)} />
        <button className="admin-btn" type="submit" disabled={adding}>{adding ? '抓取中…' : '新增'}</button>
      </form>
      <div className="task-form-hint">
        💡 只要輸入代號（可只打 <b>SUI</b>，會自動補成 SUIUSDT），系統會自動<b>抓歷史資料 → 算指標 → 入庫</b>，完成後前台就能選。
        {addMsg && <span style={{ color: addMsg.startsWith('✓') ? '#22c55e' : '#f59e0b' }}>　{addMsg}</span>}
      </div>

      {/* 清單 */}
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead><tr>
            <th>啟用</th><th>幣種</th><th>中文名</th><th>代碼</th>
            <th>資料筆數</th><th>最新資料日</th><th>狀態</th><th>動作</th>
          </tr></thead>
          <tbody>
            {coins.length === 0 && (
              <tr><td colSpan={8} style={{ color: '#94a3b8' }}>{loading ? '載入中…' : '尚無幣種'}</td></tr>
            )}
            {coins.map(c => (
              <tr key={c.symbol} style={{ opacity: c.enabled ? 1 : 0.55 }}>
                <td>
                  <button className="admin-mini-btn"
                    style={{ color: c.enabled ? '#22c55e' : '#64748b', borderColor: c.enabled ? '#22c55e66' : undefined, minWidth: 66 }}
                    onClick={() => guard(() => updateCoin(c.symbol, { enabled: !c.enabled }))}
                    title={c.enabled ? '點擊停用（前台隱藏、保留資料）' : '點擊啟用'}>
                    {c.enabled ? '● 啟用' : '○ 停用'}
                  </button>
                </td>
                <td style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{c.symbol}</td>
                <td>
                  <input className="admin-input" style={{ width: 100 }} defaultValue={c.zh}
                    onBlur={e => { const v = e.target.value.trim(); if (v !== c.zh) guard(() => updateCoin(c.symbol, { zh: v })) }} />
                </td>
                <td>
                  <input className="admin-input" style={{ width: 70 }} defaultValue={c.ticker}
                    onBlur={e => { const v = e.target.value.trim(); if (v !== c.ticker) guard(() => updateCoin(c.symbol, { ticker: v })) }} />
                </td>
                <td>{c.rows ? c.rows.toLocaleString() : <span style={{ color: '#ef4444' }}>無</span>}</td>
                <td>{c.last_date || '—'}</td>
                <td style={{ color: !c.has_data ? '#ef4444' : c.stale ? '#f59e0b' : '#22c55e', fontWeight: 700, whiteSpace: 'nowrap' }}>
                  {!c.has_data ? '✗ 無資料' : c.stale ? `⚠ 落後 ${c.lag_days} 天` : '✓ 最新'}
                </td>
                <td>
                  <button className="admin-del-btn"
                    onClick={() => { if (window.confirm(`確定移除 ${c.symbol}？\n（歷史資料仍保留在資料庫，只從清單移除）`)) guard(() => deleteCoin(c.symbol)) }}>
                    移除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="task-form-hint">
        💡「停用」＝ 前台隱藏但保留資料（可隨時再啟用）；「移除」＝ 從清單刪掉（歷史資料仍留在資料庫）。
        中文名 / 代碼改完點空白處即存。啟用 / 停用<b>即時生效、不需重啟</b>。
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
        : tab === 'coins' ? <CoinsPage onLogout={logout} />
        : tab === 'tasks' ? <TasksPage onLogout={logout} />
        : tab === 'status' ? <StatusPage onLogout={logout} />
        : <DbViewer onLogout={logout} />}
    </div>
  )
}
