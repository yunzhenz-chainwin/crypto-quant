# crypto-quant — 加密貨幣量化分析平台

> **這份文件是專案的入口**：接手開發、回顧架構、或讓 AI 助手了解專案之前，先讀這一份。
> 最後更新：2026-07-08

一句話介紹：一個自架的加密貨幣分析網站 — 自動抓行情與新聞、算技術指標與訊號、
用「規則引擎 + GPT」雙 AI 解讀盤勢，附**即時報價**與**宏觀環境**背景，配有管理後台，前台資料自動更新。

---

## 📑 文件地圖（要找什麼看哪份）

| 想做的事 | 看這份 |
|---|---|
| **快速了解 / 接手** | 本檔 README（你在這） |
| **部署、重啟、改前端、輪密鑰、排錯** | [`docs/部署與運維.md`](docs/部署與運維.md) |
| **呼叫 API（前台/後台端點規格）** | [`docs/API規格.md`](docs/API規格.md) |
| **本地開發、開發鐵律、測試怎麼跑** | [`docs/開發指南.md`](docs/開發指南.md) |
| **資料庫每張表結構與資料流** | [`docs/資料庫說明.md`](docs/資料庫說明.md) |
| **給主管的成果匯報 / 驗證數據** | [`docs/匯報.md`](docs/匯報.md)、[`docs/驗證成果表.md`](docs/驗證成果表.md) |
| **未來路線圖 / 訊號改良與 ML 計畫** | [`docs/專案路線圖.md`](docs/專案路線圖.md)、[`docs/訊號增準計畫.md`](docs/訊號增準計畫.md)、[`docs/ML訊號研究計畫.md`](docs/ML訊號研究計畫.md) |

> 進度的**單一真相來源**是後台「工作項目」（`app.db` 的 `tasks` 表），本檔與路線圖是規劃視角的快照。

---

## 1. 功能總覽

| 區塊 | 內容 |
|---|---|
| 市場總覽 | 15 幣訊號卡片牆、**即時報價**（前端直連 Binance WebSocket、秒級跳動）、恐懼貪婪指數、市場摘要列 |
| 幣種詳細頁 | 蠟燭圖（**日線 / 時線** 切換，MA/布林/成交量/RSI/MACD/KDJ/DMI/BIAS/**ATR/OBV**）、回測面板、相關性熱圖 |
| 宏觀環境 | 規則式市場背景（DXY/VIX/美債/標普/黃金/BTC主導率/總市值 → 對加密順風/逆風）；`/api/macro`，免金鑰、快取 15 分（**前端面板現隱藏保留**，見 §9） |
| AI 智能分析 | **雙引擎**：🧮 規則引擎（6 因子白話分析，免費永遠可用）+ 🤖 GPT 深度解讀（需金鑰）；立場不一致會標「觀點分歧」；可提問（多輪對話） |
| 市場情緒 | 恐懼貪婪錶盤+歷史、**新聞情緒溫度**（每日 -100~+100，全市場+單幣）、新聞牆（10 個來源、中英文） |
| 自動更新 | 前端每 60 秒輪詢資料版本，有新資料才重拉 — 不用手動重整 |
| 管理後台 `/admin` | 監控儀表板、幣種管理、工作項目追蹤、資料庫檢視、訊號成績單、策略現況、AI 設定（金鑰/用量） |

> **暫時下架但程式保留**（取消 `App.jsx` 對應註解即可恢復）：吉祥物小Q 漂浮聊天小幫手 `BotWidget`（2026-07-06，使用者為主管/老闆）、新手導覽 `OnboardingTour`、宏觀面板 `MacroPanel`（2026-07-07，價值待議）。

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
- **正式部署（開機自啟/看門狗/服務化）詳見 [`docs/部署與運維.md`](docs/部署與運維.md)。**

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

**旁路即時資料（不進排程管線、即時取用）**：
- 即時報價：前端**直連 Binance WebSocket**（`lib/useLivePrices.js`），免經後端。
- 宏觀環境：前端打 `/api/macro`，後端**當下**抓 Yahoo Finance + CoinGecko（快取 15 分），不落 DB。

### 設計決策（為什麼這樣做）

- **雙 SQLite（`app.db` / `news.db`）**：零設定、ACID、開 WAL（耐當機、讀寫不互鎖）；資料量萬~百萬列綽綽有餘；`prices`/`indicators`/`daily_signal` 全可由 CSV 或 Binance 重建，遺失≠永久遺失。詳見 [`docs/資料庫說明.md`](docs/資料庫說明.md)。
- **CSV 中繼 + DB 中央**：抓取/計算落 CSV（可備援、可肉眼查），再 ingest 進 DB 當查閱與分析中心。
- **6 因子計分單一真相（`src/scoring.py`）**：前台訊號與回測**共用同一把尺**，回測才能佐證畫面建議（否則兩套邏輯各說各話）。
- **雙 AI 引擎互輔**：GPT 吃規則引擎整理好的結構化事實 + 固定提示詞，被本地數據錨定防幻覺；立場不一致標「觀點分歧」。
- **資料正確性鐵律**：只存**已收盤** K 棒（避免半根 K 棒污染尾端指標）；回測**不前視**（依訊號動作延到隔根開盤成交）。
- **設定集中 `app_config`**：幣種清單、時線幣種、AI 金鑰等單一來源，不寫死在程式，後台可改。

## 4. 目錄地圖

```
backend/
  main.py                FastAPI 入口（掛路由、服務 frontend/dist）
  scheduler.py           排程：每日 pipeline(09:00,UTC日棒收盤後)、每小時 1h 線(:06)、新聞(每30分)
  routers/               （10 個 router，共 48 端點；規格見 docs/API規格.md）
    meta.py              /symbols /intervals /status(data_version=自動更新的心跳) /verify
    prices.py            /prices/{sym}?interval=1d|1h
    indicators.py        /indicators/{sym}?interval=
    signals.py           /signals（6 因子訊號）/signals/{sym}/history
    backtest.py          /backtest/{sym}（日線策略回測）/backtest/db/*（入庫結果）
    correlation.py       /correlation
    sentiment.py         新聞抓取+情緒詞庫(中英)+幣種標記；/sentiment/*（news、summary、fear_greed）
    ai.py                /ai/analysis /ai/ask /ai/config（AI 機器人）
    macro.py             /macro（規則式宏觀環境，免金鑰、快取15分）
    admin.py             /admin/*（登入、監控、幣種、任務、DB 檢視、AI 設定、成績單、策略、操作）
  services/
    app_db.py            data/app.db 全部表與存取（設定/任務/K線/指標/訊號/AI 快取…）
    reader.py            前台讀取層（多週期查詢、data_versions；停用幣如 MATIC 自動隱藏）
    signal_engine.py     6 因子訊號（計分核心在 src/scoring.py）
    ai_analyst.py        ★AI 雙引擎：build_context→規則分析→GPT(固定提示詞)→交叉檢核
    news_store.py        news.db 存取＋news_sentiment_daily 每日情緒彙總
    backtest_engine.py   回測引擎
    macro.py             ★宏觀環境規則引擎（Yahoo+CoinGecko，英文邏輯/中文顯示）
    coin_facts.py        幣種基本資料（含 MATIC→POL 等歷史脈絡）
    canned_qa.py         AI 固定問答庫
src/
  fetch_binance.py       抓 K 線（多幣/多週期/增量/過濾未收盤K棒）── scheduler 用
  indicators.py          算指標（--interval 1d|1h --no-plot）── scheduler 用
  scoring.py             ★6 因子計分單一真相來源（前台訊號與回測共用）
  backtest.py            ★回測核心（scheduler/app_db/backtest_engine 共用）
  momentum_signal.py     ★防禦型跨幣動量策略（已驗證有效；後台「現況」頁）
  signal_eval.py         訊號成績單（forward edge 檢驗；後台即時）
  verify_indicators.py   指標交叉驗證（前台信任徽章；後台即時）
  correlation.py         相關性矩陣（手動分析；排程已不再呼叫）
  verify_backtest.py     回測驗證器（改訊號/回測後必跑）
  cross_sectional*.py …  跨幣動量研究血脈（收斂成 momentum_signal.py，見 docs/訊號研究記錄.md）
frontend/src/
  App.jsx                根元件：總覽/詳細切換、60 秒輪詢自動更新、時線切換
  api/client.js          公開 API client；api/admin.js 後台 client
  lib/useLivePrices.js   ★Binance WebSocket 即時報價 hook
  components/
    CandlestickChart.jsx 主圖（lightweight-charts，多週期時間軸）
    AIAnalystPanel.jsx   AI 分析面板（雙引擎+提問）
    MarketOverview.jsx   總覽卡片牆；MarketSummary.jsx 市場摘要列
    MacroPanel.jsx       宏觀環境面板（現隱藏保留，見 §9）
    SentimentPanel.jsx   情緒面板（恐懼貪婪+新聞情緒溫度+新聞牆）
    BotMascot.jsx / BotWidget.jsx  小Q吉祥物（暫時下架，保留可恢復）
    HeroSignal / BacktestPanel / CorrelationHeatmap / IndicatorCards ...
  admin/AdminApp.jsx     整個後台（分頁：監控/幣種/工作項目/資料庫/現況/AI 設定）
docs/                    見上方「文件地圖」
data/  clean/*.csv（K線）raw/（原始JSON,gitignore）app.db news.db（gitignore）
reports/ indicators_*.csv backtest_*（json/csv；圖 png 不追蹤）
```

## 5. 資料庫（SQLite×2，皆 WAL）

> 完整表結構、資料流、容量評估見 **[`docs/資料庫說明.md`](docs/資料庫說明.md)**。

**data/app.db**：`prices`/`indicators`（多週期 K 線與指標，PK=symbol+interval+ts）、
`daily_signal`（每日訊號歷史）、`fear_greed`、`app_config`（幣種清單/hourly_symbols/AI 設定 — 集中設定，後台可改）、
`tasks`（★工作項目=**進度的單一真相來源**）、`job_runs`（排程紀錄）、`access_log`、
`ai_analysis`（AI 分析快取，重啟不失效）、`ai_chat`（對話 90 天）、`ai_usage`（GPT token 用量）。

**data/news.db**：`news`（url 唯一、標題、來源、情緒、分類、`coins` 幣種標記）、
`news_sentiment_daily`（每日×每幣情緒分數 -100~+100）。

## 6. 排程一覽（scheduler.py，隨 FastAPI 啟動）

| 時間 | 工作 | 內容 |
|---|---|---|
| 每日 09:00（台灣，=UTC 01:00） | daily_pipeline | 抓各啟用幣日線→算指標→入庫 `prices`/`indicators`→重算 `daily_signal`→重產回測報表並入庫→新鮮度檢查→恐懼貪婪→幣種級新聞+情緒彙總→AI 紀錄清理→`data/raw` 清理 |
| 每小時 :06 | hourly_pipeline | BTC/ETH 1h 增量抓取→指標→入庫（幣種清單在 `app_config.hourly_symbols`） |
| 每 30 分 | news_fetch | 9 家 RSS + Google News 中文 → 詞庫標註 → 去重入庫 → 滾動更新今日情緒彙總 |

> 每步都經結束碼檢查 + 收尾「資料新鮮度」防線，任一步失敗整個 job 標 `failed`，不再假性成功。
> （舊版有的「算相關性」步驟已移除：只產 PNG 熱圖無人用，`/api/correlation` 由 `reader` 直接讀 DB 計算。）

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
- 已驗證有效的是後台**防禦型跨幣動量策略**（動量選幣+BTC>100MA regime+波動目標）；研究血脈見 `src/cross_sectional*`、`docs/訊號研究記錄.md`。
- 宏觀環境面板（`MacroPanel` + `/api/macro`）已完成但**前台先隱藏**（價值待議，程式與 API 保留）。
- 修復路線見 `docs/訊號增準計畫.md`（等確認）→ 之後才評估 `docs/ML訊號研究計畫.md`。

## 10. 開發慣例與注意事項

> 完整版（環境設定、開發鐵律、測試怎麼跑）見 **[`docs/開發指南.md`](docs/開發指南.md)**。

- **進度追蹤**：後台「工作項目」（app.db `tasks` 表）是唯一真相來源 — 做完標 done、新待辦即時補上，notes 欄寫交接說明。
- 設定集中：幣種清單、時線幣種、AI 金鑰等都在 `app_config`，別寫死在程式裡。
- 資料正確性鐵律：只存**已收盤** K 棒；訊號計分只改 `src/scoring.py`（改完要重跑回測與 verify）；回測**不前視**。
- 版控：單人 repo，直接 commit＋push `main`；只提交當次工作的檔，**別把排程器改的 `data/`、`reports/` 一起提交**。
- 安全（對外前必做）：改掉 `ADMIN_PASS`/`ADMIN_SECRET` 預設值；其餘強化見任務 #70。
- 已知待辦重點：#64 服務化（開機自啟）、#70 安全強化、#79 訊號增準（待確認）、#77 GPT 情緒標註（待金鑰）、#71 到價通知、#72 投資組合。

## 11. 各腳本手動執行

```powershell
python src\fetch_binance.py BTCUSDT --interval 1h    # 抓 K 線（增量）
python src\indicators.py BTCUSDT --interval 1h --no-plot
python src\backtest.py BTCUSDT                        # 回測
python src\verify_backtest.py                         # 回測驗證（改訊號/回測後必跑）
python src\verify_indicators.py 1d                    # 指標交叉驗證
python src\correlation.py                             # 相關性（手動分析）
# 手動觸發排程等價動作：後台監控頁「重新匯入行情」或 python -c 呼叫 scheduler 函式
```
