# crypto-quant frontend

React + Vite 前端，包含前台市場分析介面與 `/admin` 後台。正式環境由 FastAPI 直接服務 `frontend/dist/`。

## 開發

```powershell
cd frontend
npm install
npm run start   # 同時啟動 uvicorn :8000 與 Vite :5173
```

也可以分開跑：

```powershell
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000 --reload
cd frontend
npm run ui
```

Vite dev server 會把 `/api` proxy 到 `http://localhost:8000`，設定在 `vite.config.js`。

## Build

```powershell
cd frontend
npm run build
```

產物在 `frontend/dist/`。正式站不是跑 Vite，而是由 `backend/main.py` 的 FastAPI 靜態服務讀取這個目錄；改前端後要重新 build。

## 主要結構

- `src/App.jsx`：前台總覽/詳細頁、60 秒輪詢、日線/時線切換。
- `src/main.jsx`：依 URL 掛載前台或 `/admin` 後台。
- `src/api/client.js`：公開 API client。
- `src/api/admin.js`：後台 API client 與 token storage。
- `src/admin/AdminApp.jsx`：後台監控、幣種、工作項目、DB、AI 設定。
- `src/components/`：圖表、訊號、回測、情緒、AI 面板等 UI。
- `src/lib/useLivePrices.js`：前端直連 Binance WebSocket 的即時報價。

## 目前暫停掛載但保留

以下元件程式仍在，`App.jsx` 內註解保留恢復方式：

- `AIAnalystPanel`
- `BotWidget`
- `OnboardingTour`
- `MacroPanel`
- `CorrelationHeatmap`

## 檢查

```powershell
npm run build
```

後端 API smoke test 在專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```
