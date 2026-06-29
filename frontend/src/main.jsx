import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import AdminApp from './admin/AdminApp.jsx'

// 網址以 /admin 開頭 → 載入後台;否則載入一般前台。
// 後端 serve_spa 對所有路徑都回 index.html,所以 /admin 也會載到同一個 bundle。
const isAdmin = window.location.pathname.startsWith('/admin')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isAdmin ? <AdminApp /> : <App />}
  </StrictMode>,
)
