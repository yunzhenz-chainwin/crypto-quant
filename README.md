# crypto-quant — 加密貨幣量化分析平台

> **這份文件是專案的入口**：接手開發、回顧架構、或讓 AI 助手了解專案之前，先讀這一份。
> 最後更新：2026-07-02

一句話介紹：一個自架的加密貨幣分析網站 — 自動抓行情與新聞、算技術指標與訊號、
用「規則引擎 + GPT」雙 AI 解讀盤勢，配有管理後台與吉祥物小Q，前台資料自動更新。

---

## 1. 功能總覽

| 區塊 | 內容 |
|---|---|
| 市場總覽 | 15 幣訊號卡片牆、恐懼貪婪指數、市場摘要列 |
| 幣種詳細頁 | 蠟燭圖（**日線 / 時線** 切換，MA/布林/成交量/RSI/MACD/KDJ/DMI/BIAS）、回測面板、相關性熱圖 |
| AI 智能分析 | **雙引擎**：🧮 規則引擎（6 因子白話分析，免費永遠可用）+ 🤖 GPT 深度解讀（需金鑰）；立場不一致會標「觀點分歧」；可提問（多輪對話） |
| 吉祥物小Q | 漂浮聊天小幫手（2026-07-06 暫時下架：使用者為主管/老闆；程式保留於 BotWidget.jsx，取消 App.jsx 兩處註解即可恢復） |
| 市場情緒 | 恐懼貪婪錶盤+歷史、**新聞情緒溫度**（每日 -100~+100，全市場+單幣）、新聞牆（10 個來源、中英文） |
| 自動更新 | 前端每 60 秒輪詢資料版本，有新資料才重拉 — 不用手動重整 |
| 管理後台 `/admin` | 監控儀表板、幣種管理、工作項目追蹤、資料庫檢視、訊號成績單、策略現況、AI 設定（金鑰/用量） |

## 2. 快速啟動

```powershell
# 後端 + 前端一起（開發模式）
cd frontend
npm run start          # = uvicorn(8000, --reload) + vite(5173)

# 或分開跑
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run ui

# 正式：build 後由 FastAPI 直接服務（單一 8000 埠）
cd frontend && npm run build
```

- 前台：`http://localhost:8000`（或 vite 開發埠 5173）
- 後台：`/admin`，帳密來自環境變數 `ADMIN_USER` / `ADMIN_PASS`（由 `secrets.local.cmd` 注入強密碼與 `ADMIN_SECRET`，2026-07-06 已改掉預設值；該檔已 gitignore）
- GPT 金鑰：後台「AI 設定」頁填入，或環境變數 `OPENAI_API_KEY`（優先）；不填則 AI 只用規則引擎
- 對外公開：Cloudflare Quick Tunnel 指向 8000（每次重啟 tunnel 網址會變；根治方案見待辦 #64）

> ⚠️ Windows 上 `.venv\Scripts\python.exe` 是啟動器殼，工作管理員會看到
> 「venv + 系統 Python **成對**的 uvicorn」— 那是**一台**伺服器，不是重複執行；殺掉子進程=殺掉整台。

## 3. 系統架構與資料流

```
Binance API ──每日09:00──▶ src/fetch_binance.py ──▶ data/clean/*_1d.csv ─┐
            ──每小時:06──▶（--interval 1h,增量,只存已收盤K棒）*_1h.csv ─┤
                                                                         ▼
                          src/indicators.py ──▶ reports/indicators_*.csv ─▶ app_db.ingest_market_data()
                                                                         ▼
RSS×9 + Google News ──每30分──▶ sentiment._fetch_and_save() ──▶ data/news.db（情緒詞庫標註+幣種標記+去重）
alternative.me（恐懼貪婪）──▶ fear_greed 表                              │
                                                                         ▼
                                    SQLite: data/app.db（單一資料來源）+ data/news.db
                                                                         ▼
                                    FastAPI backend/（/api/*）＋排程 scheduler.py
                                                                         ▼
                                    React frontend/（vite build 後由 FastAPI 服務）
```

原則：**CSV 是中繼/備援，前後台一律讀 SQLite**；所有排程都記錄到 `job_runs` 表（後台監控頁可看成功/失敗）。

## 4. 目錄地圖

```
backend/
  main.py                FastAPI 入口（掛路由、服務 frontend/dist）
  scheduler.py           排程：每日 pipeline(09:00，UTC日棒收盤後)、每小時 1h 線(:06)、新聞(每30分)
  routers/
    meta.py              /symbols /intervals /status(data_version=自動更新的心跳)
    prices.py            /prices/{sym}?interval=1d|1h
    indicators.py        /indicators/{sym}?interval=
    signals.py           /signals（6 因子訊號）/signals/{sym}/history
    backtest.py          /backtest/{sym}（日線策略回測）
    correlation.py       /correlation
    sentiment.py         新聞抓取+情緒詞庫(中英)+幣種標記；/sentiment/*（news、summary、fear_greed）
    ai.py                /ai/analysis /ai/ask /ai/config（AI 機器人）
    admin.py             /admin/*（登入、監控、幣種、任務、DB 檢視、AI 設定、成績單、策略）
  services/
    app_db.py            data/app.db 全部表與存取（設定/任務/K線/指標/訊號/AI 快取…）
    reader.py            前台讀取層（多週期查詢、data_versions）
    signal_engine.py     6 因子訊號（計分核心在 src/scoring.py）
    ai_analyst.py        ★AI 雙引擎：build_context→規則分析→GPT(固定提示詞)→交叉檢核
    news_store.py        news.db 存取＋news_sentiment_daily 每日情緒彙總
    backtest_engine.py   回測引擎
src/
  fetch_binance.py       抓 K 線（多幣/多週期/增量/過濾未收盤K棒）
  indicators.py          算指標（--interval 1d|1h --no-plot）
  scoring.py             ★6 因子計分單一真相來源（前台訊號與回測共用）
  backtest.py            回測 CLI
  momentum_signal.py     ★防禦型跨幣動量策略（已驗證有效；後台「現況」頁）
  signal_eval.py         訊號成績單（forward edge 檢驗）
  verify_indicators.py   指標交叉驗證（前台信任徽章）
  correlation.py         相關性矩陣
frontend/src/
  App.jsx                根元件：總覽/詳細切換、60 秒輪詢自動更新、時線切換
  api/client.js          公開 API client；api/admin.js 後台 client
  components/
    CandlestickChart.jsx 主圖（lightweight-charts，多週期時間軸）
    AIAnalystPanel.jsx   AI 分析面板（雙引擎+提問）
    BotMascot.jsx        ★小Q吉祥物（SVG 表情狀態機）
    BotWidget.jsx        全站漂浮聊天小幫手（暫時下架，保留可恢復）
    SentimentPanel.jsx   情緒面板（恐懼貪婪+新聞情緒溫度+新聞牆）
    MarketOverview / HeroSignal / BacktestPanel / CorrelationHeatmap ...
  admin/AdminApp.jsx     整個後台（分頁：監控/幣種/工作項目/資料庫/現況/AI 設定）
docs/
  訊號增準計畫.md/.docx   ★規則式訊號修復計畫（白話+技術；待確認執行）
  ML訊號研究計畫.md/.docx ★ML 路線評估（LightGBM+walk-forward；待 Go/No-Go）
  情緒詞庫範本.docx       ★詞庫審核範本（主管核可後才加詞）
  PROJECT_PLAN.md         歷史總規劃、資料庫說明.md、訊號成績單分析.md 等
data/  clean/*.csv（K線）raw/（原始JSON,gitignore）app.db news.db（gitignore）
reports/ indicators_*.csv backtest_*.csv（圖 png 不追蹤）
```

## 5. 資料庫（SQLite×2，皆 WAL）

**data/app.db**（26MB）：`prices`/`indicators`（多週期 K 線與指標，PK=symbol+interval+ts）、
`daily_signal`（每日訊號歷史）、`fear_greed`、`app_config`（幣種清單/hourly_symbols/AI 設定 — 集中設定，後台可改）、
`tasks`（★工作項目=**進度的單一真相來源**）、`job_runs`（排程紀錄）、`access_log`、
`ai_analysis`（AI 分析快取，重啟不失效）、`ai_chat`（對話 90 天）、`ai_usage`（GPT token 用量）。

**data/news.db**（1MB）：`news`（url 唯一、標題、來源、情緒、分類、`coins` 幣種標記）、
`news_sentiment_daily`（每日×每幣情緒分數 -100~+100）。

## 6. 排程一覽（scheduler.py，隨 FastAPI 啟動）

| 時間 | 工作 | 內容 |
|---|---|---|
| 每日 01:00 UTC | daily_pipeline | 抓 15 幣日線→指標→相關性→入庫→訊號回填→新鮮度檢查→恐懼貪婪→幣種級新聞→AI 紀錄清理 |
| 每小時 :06 | hourly_pipeline | BTC/ETH 1h 增量抓取→指標→入庫（幣種清單在 app_config.hourly_symbols） |
| 每 30 分 | news_fetch | 9 家 RSS + Google News 中文 → 詞庫標註 → 去重入庫 → 滾動更新今日情緒彙總 |

## 7. AI 系統設計（雙引擎互輔）

1. **規則引擎**（`ai_analyst.local_analysis`）：把 6 因子、日/時線指標、恐懼貪婪、新聞情緒整理成白話分析 — 零成本、永遠可用。
2. **GPT**（`ai_analyst.gpt_analysis`）：吃規則引擎整理好的結構化事實 + **固定提示詞**（`SYSTEM_PROMPT_ANALYSIS/QA`：禁止捏造、必須引用數據、嚴格 JSON），被本地數據錨定防幻覺。
3. **交叉檢核**：兩邊立場不一致 → 前台標「⚠ 觀點分歧」。
4. 成本控制：每小時 80 次上限、15 分鐘快取（入庫持久化）、token 用量後台可視。
5. 提問走 `/api/ai/ask`，自動帶最近 3 輪對話；無金鑰時降級回規則引擎摘要。

## 8. 新聞情緒管線

真實來源（只搬運不創作，每則帶原始網址）：CoinTelegraph、CoinDesk、Decrypt、TheBlock、
CryptoSlate、Blockworks、BitcoinMagazine、動區、鏈新聞 + Google News 中文聚合（市場級+幣種級）。
標題經**中英雙語加權詞庫**判讀（詞庫改動需先過 `docs/情緒詞庫範本.docx` 審核流程），
每日彙總成情緒分數供前台溫度條與 AI 引用。GPT 批次標註為下一階段（待金鑰，任務 #77）。

## 9. 訊號現況（誠實聲明）與路線圖

- 目前前台 6 因子「信心分數」經成績單檢驗**無預測力**（5 日勝率 45.2% vs 隨機 47.4%），屬教學性質。
- 已驗證有效的是後台**防禦型跨幣動量策略**（動量選幣+BTC>100MA regime+波動目標）。
- 修復路線見 `docs/訊號增準計畫.md`（等確認）→ 之後才評估 `docs/ML訊號研究計畫.md`。

## 10. 開發慣例與注意事項

- **進度追蹤**：後台「工作項目」（app.db `tasks` 表）是唯一真相來源 — 做完標 done、新待辦即時補上，notes 欄寫交接說明。
- 設定集中：幣種清單、時線幣種、AI 金鑰等都在 `app_config`，別寫死在程式裡。
- 資料正確性鐵律：只存**已收盤** K 棒；訊號計分只改 `src/scoring.py`（改完要重跑回測與 verify）。
- 安全（對外前必做）：改掉 `ADMIN_PASS`/`ADMIN_SECRET` 預設值；其餘強化見任務 #70。
- 已知待辦重點：#64 服務化（開機自啟）、#70 安全強化、#79 訊號增準（待確認）、#77 GPT 情緒標註（待金鑰）、#71 到價通知、#72 投資組合。

## 11. 各腳本手動執行

```powershell
python src\fetch_binance.py BTCUSDT --interval 1h    # 抓 K 線（增量）
python src\indicators.py BTCUSDT --interval 1h --no-plot
python src\backtest.py BTCUSDT                        # 回測
python src\correlation.py                             # 相關性
# 手動觸發排程等價動作：後台監控頁「重新匯入行情」或 python -c 呼叫 scheduler 函式
```
