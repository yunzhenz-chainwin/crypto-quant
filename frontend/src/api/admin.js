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

export const fetchHealth  = () => adminGet('/health')
export const fetchDbStats = () => adminGet('/db/stats')
export const fetchJobs    = () => adminGet('/jobs')
