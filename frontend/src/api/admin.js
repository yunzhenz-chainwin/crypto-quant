/**
 * admin.js — 後台 API client
 *
 * 登入後把 token 存在 localStorage,之後每個請求帶 Authorization。
 * 401(逾時/無效)時自動清掉 token,讓畫面退回登入頁。
 */
const BASE = '/api/admin'
const TOKEN_KEY = 'cq_admin_token'

export const getToken   = () => localStorage.getItem(TOKEN_KEY)
export const setToken   = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

export async function adminLogin(username, password) {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const msg = (await res.json().catch(() => ({})))?.detail || '登入失敗'
    throw new Error(msg)
  }
  return res.json()
}

async function adminGet(path) {
  const res = await fetch(BASE + path, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) {
    clearToken()
    throw new Error('UNAUTH')   // 讓呼叫端退回登入頁
  }
  if (!res.ok) throw new Error(`API ${path} 回應 ${res.status}`)
  return res.json()
}

// 帶 body 的請求(POST / PUT / DELETE)
async function adminSend(path, method, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) { clearToken(); throw new Error('UNAUTH') }
  if (!res.ok) throw new Error(`API ${path} 回應 ${res.status}`)
  return res.json()
}

export const fetchHealth  = () => adminGet('/health')
export const fetchDbStats = () => adminGet('/db/stats')
export const fetchJobs    = () => adminGet('/jobs')

// 指標交叉驗證(用獨立演算法逐點比對)
export const fetchVerifyIndicators = () => adminGet('/verify/indicators')

// 訊號預測力(成績單:現行訊號有沒有 forward edge)
export const fetchSignalScorecard = () => adminGet('/signal/scorecard')

// 防禦型跨幣動量「正式策略訊號」(今日建議 + 績效)
export const fetchStrategy = () => adminGet('/strategy')

// 工作項目 / 進度追蹤
export const fetchTasks  = () => adminGet('/tasks')
export const createTask  = (task)       => adminSend('/tasks', 'POST', task)
export const updateTask  = (id, fields) => adminSend(`/tasks/${id}`, 'PUT', fields)
export const deleteTask  = (id)         => adminSend(`/tasks/${id}`, 'DELETE')

// 手動把最新 K 線 / 指標匯入資料庫
export const ingestMarket = () => adminSend('/ingest', 'POST')

// 資料庫檢視:列出資料表 / 讀某表的資料列
export const fetchDbTables = () => adminGet('/db/tables')
export const fetchDbTable = (name, { symbol = null, interval = null, limit = 50, offset = 0 } = {}) => {
  const p = new URLSearchParams()
  if (symbol)   p.set('symbol', symbol)
  if (interval) p.set('interval', interval)
  p.set('limit', limit); p.set('offset', offset)
  return adminGet(`/db/table/${name}?${p}`)
}
