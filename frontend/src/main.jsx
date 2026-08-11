import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// 後台改為動態載入（code splitting #29）：一般訪客不會下載後台程式碼與其相依
// （AdminApp + recharts 圖表庫），前台首屏 bundle 因此小一大截。
const AdminApp = lazy(() => import('./admin/AdminApp.jsx'))

// 網址以 /admin 開頭 → 載入後台;否則載入一般前台。
// 後端 serve_spa 對所有路徑都回 index.html,所以 /admin 也會載到同一個 bundle。
// BASE_URL 是 Vite 的部署基底路徑:獨立部署為 '/'(→ /admin);掛在入口網站子路徑下
// 建置時為 '/crypto/'(→ /crypto/admin)。兩種路徑都要認得為後台。
const pathname = window.location.pathname
const isAdmin = pathname.startsWith('/admin')
  || pathname.startsWith(`${import.meta.env.BASE_URL}admin`)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isAdmin
      ? (
        <Suspense fallback={<div style={{ padding: 40, color: '#94a3b8' }}>載入後台…</div>}>
          <AdminApp />
        </Suspense>
      )
      : <App />}
  </StrictMode>,
)
