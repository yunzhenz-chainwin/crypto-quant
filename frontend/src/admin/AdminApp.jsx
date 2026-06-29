/**
 * AdminApp.jsx — 後台管理台（P2 v1:登入 + 監控儀表板）
 *
 * 由 main.jsx 在網址為 /admin 時掛載。
 * 未登入 → 顯示登入頁;已登入 → 顯示監控儀表板。
 * 之後的「操作 / 管理 / 分析」分頁會接續加在同一個 tab 列。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  adminLogin, getToken, setToken, clearToken,
  fetchHealth, fetchDbStats, fetchJobs,
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
        <div className="admin-login-sub">登入以檢視系統監控與資料庫狀態</div>
        <input className="admin-input" placeholder="帳號" value={u}
               onChange={e => setU(e.target.value)} autoFocus />
        <input className="admin-input" placeholder="密碼" type="password" value={p}
               onChange={e => setP(e.target.value)} />
        {err && <div className="admin-login-err">{err}</div>}
        <button className="admin-btn" disabled={loading}>
          {loading ? '登入中…' : '登入'}
        </button>
        <div className="admin-login-hint">
          請輸入管理員帳號密碼登入
        </div>
      </form>
    </div>
  )
}

// ── 小卡片 ──────────────────────────────────────────────────────────────────
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

// ── 監控儀表板 ──────────────────────────────────────────────────────────────
function Dashboard({ onLogout }) {
  const [health, setHealth] = useState(null)
  const [db, setDb]         = useState(null)
  const [jobs, setJobs]     = useState(null)
  const [err, setErr]       = useState('')
  const [loading, setLoading] = useState(false)

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

  const freshTone = health
    ? (health.symbols_fresh === health.symbols_total ? 'good'
       : health.symbols_fresh === 0 ? 'bad' : 'warn')
    : null

  return (
    <div className="admin-app">
      {/* 頂列 */}
      <header className="admin-header">
        <span className="admin-logo">📊 Crypto Quant 後台</span>
        <div className="admin-tabs">
          <button className="admin-tab active">監控</button>
          <button className="admin-tab" disabled title="P2 後續">操作（即將推出）</button>
          <button className="admin-tab" disabled title="P3">管理（即將推出）</button>
          <button className="admin-tab" disabled title="P3">分析（即將推出）</button>
        </div>
        <div className="admin-header-right">
          <button className="admin-link" onClick={load} disabled={loading}>
            {loading ? '更新中…' : '↻ 重新整理'}
          </button>
          <a className="admin-link" href="/">← 回前台</a>
          <button className="admin-link danger" onClick={onLogout}>登出</button>
        </div>
      </header>

      <div className="admin-body">
        {err && <div className="admin-error">{err}</div>}

        {/* 系統健康 */}
        <h2 className="admin-section-title">系統健康</h2>
        <div className="admin-grid">
          <StatCard
            label="資料新鮮度"
            value={health ? `${health.symbols_fresh} / ${health.symbols_total}` : '—'}
            sub="幣種資料為最新(落後 ≤2 天)"
            tone={freshTone}
          />
          <StatCard
            label="每日資料排程"
            value={health?.last_pipeline
              ? <JobBadge status={health.last_pipeline.status} /> : '尚無紀錄'}
            sub={health?.last_pipeline
              ? `${health.last_pipeline.started_at}${health.last_pipeline.message ? ' · ' + health.last_pipeline.message : ''}`
              : '排程跑過後才會出現'}
          />
          <StatCard
            label="新聞抓取排程"
            value={health?.last_news_fetch
              ? <JobBadge status={health.last_news_fetch.status} /> : '尚無紀錄'}
            sub={health?.last_news_fetch
              ? `${health.last_news_fetch.started_at}${health.last_news_fetch.message ? ' · ' + health.last_news_fetch.message : ''}`
              : '每 30 分鐘自動抓取'}
          />
          <StatCard
            label="伺服器時間"
            value={health?.server_time?.slice(11) ?? '—'}
            sub={health?.server_time?.slice(0, 10) ?? ''}
          />
        </div>

        {/* 資料新鮮度明細 */}
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

        {/* 資料庫統計 */}
        <h2 className="admin-section-title">資料庫</h2>
        <div className="admin-grid">
          <StatCard label="新聞總筆數" value={db?.news?.total?.toLocaleString() ?? '—'}
                    sub={`可查發布日 ${db?.news?.publish_dates ?? 0} 天 · ${db?.news?.file_kb ?? 0} KB`} />
          <StatCard label="操作 / 排程紀錄" value={db?.app?.job_runs ?? '—'}
                    sub={`access_log ${db?.app?.access_log ?? 0} 筆`} />
          <StatCard label="訊號快照" value={db?.app?.daily_signal ?? '—'}
                    sub={`恐懼貪婪歷史 ${db?.app?.fear_greed ?? 0} 筆`} />
          <StatCard label="幣種設定" value={db?.app?.coins_config ?? '—'}
                    sub={`app.db ${db?.app?.file_kb ?? 0} KB`} />
        </div>

        {/* 新聞分類分布 */}
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
    </div>
  )
}

export default function AdminApp() {
  const [authed, setAuthed] = useState(!!getToken())
  if (!authed) return <Login onSuccess={() => setAuthed(true)} />
  return <Dashboard onLogout={() => { clearToken(); setAuthed(false) }} />
}
