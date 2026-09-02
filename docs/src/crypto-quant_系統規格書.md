crypto-quant 系統規格書
===

> 版本：v1.1（定稿）｜建立：2026-09-01｜最後更新：2026-09-02
> 基準：`main` @ f71f464（2026-09-01）＋2026-09-02 文件改版；資料截止 2026-09-01（收盤日線）
> 內容：系統概述 × 初步設計 × 細部設計 × 需求追溯 × 附錄

---

# 目錄

**1. 簡介**
　　1.1 文件目的
　　1.2 文件範圍
　　1.3 現況註記標註
**2. 系統概述**
　　2.1 系統目標
　　2.2 系統範圍
　　2.3 系統架構
　　2.4 軟體需求概述
　　2.5 軟體環境需求
　　2.6 設計限制
**3. 系統初步設計**
　　3.1 使用者介面結構層次圖
　　3.2 模組功能架構圖
　　3.3 類別初步描述
**4. 系統細部設計**
　　4.1 使用者介面流程
　　4.2 模組功能
　　4.3 類別細部描述
　　4.4 資料結構
　　4.5 成員函數（關鍵服務函式與公開介面）
**5. 系統需求至系統設計之追溯**
　　5.1 追溯工具（GitHub）
　　5.2 需求 ↔ 設計 ↔ 驗證追溯表
**6. 附錄**
　　6.1 參考書目
　　6.2 專有名詞解釋
　　6.3 中英對照

# 1. 簡介

## 1.1 文件目的

本文件為 crypto-quant（加密貨幣量化分析平台）之軟體系統規格書（SDD），涵蓋系統之初步設計與細部設計，使系統開發者、維護者與交接者得以確認系統的實際需求與設計決策，並作為後續開發與維運時遵循的準繩。本文件內容整理自《crypto-quant 系統文件與交接手冊》（docs/crypto-quant_交接手冊.docx，2026-09-02 定版）並與 2026-09-02 之程式碼現況核對（後端 15 個服務模組、11 個路由、`src/` 28 個模組逐一盤點）。

## 1.2 文件範圍

本文件範圍包含：系統目標與範圍、系統架構、前後端模組設計、資料庫類別設計、核心流程（行情管線、訊號與回測、研究預測、新聞情緒與宏觀、AI 雙引擎）、需求至設計之追溯方式。**不含**：操作手冊等級的維運指令（見交接手冊第 10 章與附錄 B）、安全政策細節（見交接手冊第 08 章）、逐端點 API 契約（見交接手冊第 05 章；非對外模式下以 FastAPI OpenAPI 為準）、研究結論與誠實聲明全文（見交接手冊第 11 章）。

## 1.3 現況註記標註

全文以「⚪【現況註記】」引言區塊標示**設計與目前實作的已查證落差**（例如規劃保留但尚未建置的能力、依決策暫停掛載的元件、尚未拍板的管理決策）。內容均已對照程式碼查證屬實，交接後若實作補齊或決策拍板，更新對應註記即可。

# 2. 系統概述

## 2.1 系統目標

crypto-quant 是一個自架、自動運作的加密貨幣分析平台，把「看盤＋算指標＋查新聞＋做研究」做成一條不用人顧的自動化流水線：

1. **自動化資料管線**：每日自動抓 15 幣行情與新聞、算指標、算訊號、入庫；前台每 60 秒偵測新資料自動更新。
2. **資料正確可驗證**：只存已收盤 K 棒；指標以獨立演算法逐點交叉驗證並在前台掛信任徽章。
3. **訊號誠實可檢驗**：前台建議與回測共用同一把計分尺；回測依訊號動作延到隔根開盤成交（無前視）；成績單即時檢驗有沒有預測力。
4. **研究預測可稽核**：預測快照內容定址、資料庫層 append-only；成熟後自動結算並有發布閘門，信心不足即拒答。
5. **白話解讀**：規則引擎把數字翻成白話（永遠可用），GPT 深度解讀選配且被本地數據錨定，觀點分歧會標示。
6. **可維運可交接**：開機自啟＋看門狗、每日備份、換機搬遷包、單一入口文件。

效益指標（KPI）：

| 指標 | 立項現況（2026-06） | 目標 | 現況（2026-09-02） |
|---|---|---|---|
| 行情與指標更新 | 手動抓、手動算 | 全自動、每日 09:00 前台自動刷新 | 達成（`daily_pipeline` 27 成功／1 失敗） |
| 指標正確率（獨立交叉驗證） | 未驗證 | 100% | 達成（16/16；1h 2/2） |
| 訊號預測力（5 日勝率 vs 隨機基準） | 未知 | ≥ 基準 +0.5pp | 未達（45.2% vs 47.4%）；六因子降為教學用途，改推動量策略 |
| 新聞來源 | 3 家（英文） | ≥ 10 家、含中文、可標單幣 | 達成（9 家 RSS＋Google News；15,359 篇） |
| 研究預測可稽核 | 無 | 每筆可回溯、不可竄改、有成績單 | 達成（v2 ledger 1,623 快照／1,383 成熟結果） |
| 服務可用性 | 人工啟動 | 開機自啟、崩潰 30 秒自癒、每日備份 | 達成 |

KPI 現況欄為 2026-09-02 唯讀實測；正式驗收時以後台「監控」與「現況」頁重讀。

## 2.2 系統範圍

**本期範圍（In Scope）**：行情（15 幣日線 5 年、BTC／ETH 小時線 2 年，Binance 公開 API，只存已收盤 K 棒，增量抓取）；指標（後端 MA20／60／200、RSI、MACD、布林、量均；前端 KDJ、DMI、BIAS、ATR、OBV 即時計算並以 pandas_ta 驗證）；訊號（六因子計分單一真相、每日歷史入庫）；回測（無前視、含成本、停損停利、隨機進場對照、參數掃描、每日重產入庫）；研究預測（1／5／10 日機率、分位、下行風險、信心、拒答、append-only ledger、成績單與發布閘門）；市場情緒（恐懼貪婪、9 家 RSS＋Google News 新聞牆、中英詞庫每日情緒分數）；宏觀環境（DXY／VIX／US10Y／SPX／GOLD 規則式判讀、十年歷史、預測力檢定、BTC 連動強度）；AI（規則引擎、GPT 選配、固定問答庫與幣種知識庫）；管理後台（監控、幣種、工作項目、資料庫檢視、現況、模型成績、AI 設定）；維運（Windows 開機自啟＋看門狗、macOS launchd、每日 SQLite 線上備份、搬遷包、版控產物防線）。

**本期不做（Out of Scope）**：下單或任何真實資金操作；保證或宣稱預測績效；會員系統與多使用者權限；分鐘線與高頻資料；自動登入交易所帳號或爬非公開資料。

> ⚪【現況註記】立項後新增且已交付：即時報價（Binance WebSocket）、宏觀環境面板、研究預測 ledger 與成績單、macOS 支援。程式保留但**依 2026-07-06 決策暫停掛載**：AI 智能分析面板、幣種相關性熱圖、小Q 聊天小幫手、新手導覽（取消 `App.jsx` 對應註解即恢復）。**規劃中尚未建立**：公開端點 `GET /api/strategy/today`（訊號增準 Phase A）、`src/factor_lab.py`、`src/ml/`、使用分析後台圖表。

## 2.3 系統架構

```
┌──────────────────────── 使用者看到的畫面 ────────────────────────┐
│  訪客 → 前台（React，免登入；首頁即 BTC 詳細頁）                 │
│  管理者 → 後台 /admin（同一個 SPA，登入取 token）                │
│  即時報價：瀏覽器直連 Binance WebSocket（不經後端）              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ /api/*　·　Authorization: Bearer <token>（後台）
                             ▼
┌──────────────────────── 系統處理中心 ────────────────────────────┐
│  FastAPI（Python 3.12）＋APScheduler（同一 uvicorn 進程）        │
│  驗證參數與 token → 限流 → 讀取層（只讀 SQLite）→ 回應           │
│  排程：抓 K 線 → 算指標 → 入庫 → 訊號／回測 → 預測封存 → 備份    │
└───────────────────────┬───────────────────┬──────────────────────┘
                        │ 行情／訊號／研究   │ 新聞
                        ▼                   ▼
              ┌──────────────────┐  ┌──────────────────────────┐
              │ data/app.db      │  │ data/news.db             │
              │ 19 張表（WAL）   │  │ 2 張表（WAL）            │
              │ 研究表 append-only│  │ url 唯一、coins 標記     │
              └──────────────────┘  └──────────────────────────┘
                        ▲
              data/clean/*.csv、reports/*.csv（抓取／計算中繼與備援）
   外部來源（皆公開免金鑰）：Binance REST／WebSocket、alternative.me、Yahoo Finance、CoinGecko、RSS×9＋Google News
```

**元件一覽**：

| 元件 | 目錄／服務 | 用途 |
|---|---|---|
| 前台與後台 | `frontend/` | 同一個 React SPA；`/admin` lazy 載入後台；build 後由 FastAPI 服務 `dist/` |
| Backend API 與排程 | `backend/` | 11 個 router、15 個服務模組、4 個排程；啟動安全檢查、安全標頭、存取紀錄 |
| 資料管線與研究 | `src/` | 抓 K 線、算指標、計分、回測、研究預測、動量策略、宏觀規則與檢定、驗證器（28 個模組） |
| 資料庫 | SQLite ×2（WAL） | `app.db` 行情／訊號／回測／研究／宏觀／設定／進度；`news.db` 新聞與情緒 |
| 部署 | `start_backend.cmd`／`.sh`、Task Scheduler、launchd | 開機自啟＋30 秒看門狗；單一進程 |
| 區網入口 | quant-portal（另一倉庫，`:8080`） | `/crypto/` 為本前端另外建置的一份；`/api` 反向代理至 `:8000` |

**程式碼目錄結構**：

```
crypto-quant/
├── backend/                 # FastAPI 應用
│   ├── main.py              # 入口：掛 11 個 router（/api）、middleware、靜態檔、lifespan
│   ├── scheduler.py         # APScheduler：daily 09:00 / hourly :06 / news 30 分 / backup 03:30
│   ├── routers/             # meta、prices、indicators、signals、backtest、forecast、correlation、sentiment、ai、macro、admin
│   ├── services/            # app_db、news_store、reader、signal_engine、backtest_engine、ai_analyst、canned_qa、
│   │                        # coin_facts、macro、forecast_scorecard、security_hardening、rate_limiter、sqlite_backup、venv_python
│   └── requirements.txt     # 跑 app 必裝
├── src/                     # 計算核心與研究（非 package；雙路徑匯入）
│   ├── fetch_binance.py、indicators.py、scoring.py、backtest.py
│   ├── forecasting.py、forecast_evaluation.py、forecast_replay.py、forecast_calibration.py、forecast_diagnose.py
│   ├── momentum_signal.py、macro_regime.py、macro_eval.py、macro_longrun.py
│   ├── verify_backtest.py、verify_indicators.py、signal_eval.py、validate.py、cross_check.py、correlation.py
│   └── cross_sectional*.py、signal_scorecard.py、signal_experiments.py、backtest_sentiment_ab.py（研究血脈）
├── frontend/                # React 19＋Vite 8（前台＋/admin 後台）
│   └── src/ App.jsx、main.jsx、components/、admin/、lib/、api/、constants/
├── tests/                   # pytest 141 項
├── scripts/                 # dev_api.mjs、make_migration_bundle.py、check_staged_runtime_artifacts.py、
│                            # verify_frontend_indicators.*、export_qa_docs.py、md2docx.py、build_docs.py、update_docx_fields.ps1
├── data/                    # clean/*.csv、raw/、app.db、news.db、backups/（皆 gitignore）
├── reports/                 # indicators_*.csv、backtest_*、macro_evidence.json（產物不追蹤）
├── docs/                    # 交接手冊 docx、本文件 docx、情緒詞庫範本.docx；src/ 為 Markdown 原始檔；images/
├── start_backend.cmd / .sh、setup.sh、secrets.example.sh   # 啟動器與環境建置
└── requirements.txt、requirements-dev.txt
```

## 2.4 軟體需求概述

| 模組 | 功能需求摘要 |
|---|---|
| 行情管線 | 每日 09:00 抓 15 幣日線、每小時 :06 抓 BTC／ETH 時線；只存已收盤 K 棒；增量、去重、原子落盤；新鮮度檢查 |
| 技術指標 | 後端 MA／RSI／MACD／布林／量均，前端 KDJ／DMI／BIAS／ATR／OBV；獨立交叉驗證 |
| 買賣訊號 | 六因子計分（單一真相 `src/scoring.py`）；BULL／BEAR／NEUTRAL；歷史入庫；成績單檢驗 |
| 回測 | 隔根開盤成交、含手續費與滑價、停損停利、隨機進場對照、走勢前後段、參數掃描；每日重產入庫 |
| 研究預測 | 1／5／10 日機率與分位；內容定址、append-only；拒答；成熟結算；point-in-time 成績單與發布閘門 |
| 市場情緒 | 恐懼貪婪；9 家 RSS＋Google News；中英詞庫判讀；幣種標記；每日情緒分數 |
| 宏觀環境 | 規則式判讀（門檻凍結）；十年歷史；預測力檢定；BTC 連動強度；每格出處 |
| AI 解讀 | 規則引擎恆可用；GPT 選配（固定提示詞、強制 JSON、被本地數據錨定、觀點分歧標示）；固定問答庫 65 條＋知識庫 |
| 即時報價 | 前端直連 Binance WebSocket，秒級跳動 |
| 管理後台 | 登入（HMAC token 8 小時）、監控、幣種、工作項目、資料庫檢視、現況、模型成績、AI 設定 |
| 自動備份 | 每日 03:30 SQLite 線上備份、`quick_check`、原子發布、保留 14 份 |

核心使用情境（User Stories，驗收條件見交接手冊第 01 章 §5）：

| # | 身分 | 情境 |
|---|---|---|
| US-01 | 訪客 | 打開網站立刻看到 BTC 即時報價與蠟燭圖，不需登入 |
| US-02 | 訪客 | 切換幣種、日線／時線、區間，圖表與指標同步 |
| US-03 | 訪客 | 看到買賣訊號，同時看到它「有沒有預測力」的誠實標示 |
| US-04 | 訪客 | 看研究預測決策卡；信心不足時看到明確拒答而非假精準數字 |
| US-05 | 訪客 | 看恐懼貪婪、新聞情緒溫度與新聞牆，並能追回原始出處 |
| US-06 | 訪客 | 看宏觀環境判讀，並知道證據有多強 |
| US-07 | 管理者 | 登入後台看每次排程成功／失敗與各幣資料新鮮度 |
| US-08 | 管理者 | 新增或停用一顆幣，不改程式、不重啟 |
| US-09 | 管理者 | 維護工作項目，作為全專案進度的唯一真相 |
| US-10 | 管理者 | 看訊號成績單與動量策略今日建議 |
| US-11 | 管理者 | 設定 GPT 金鑰、看用量 |
| US-12 | 系統 | 每日自動抓取、計算、封存預測、備份，失敗不假性成功 |
| US-13 | 接手者 | 換一台機器後一小時內恢復服務與歷史資料 |

## 2.5 軟體環境需求

**開發／執行環境**：

| 項目 | 需求 |
|---|---|
| 後端 | Python 3.12（`.venv`）、FastAPI 0.137、Uvicorn、APScheduler 3.11、pandas 3.0、numpy 2.2、feedparser、requests |
| 前端 | Node.js（主機 v24.14.1、npm 11）、React 19.2、Vite 8.0、lightweight-charts 5.2、recharts 3.8 |
| 資料庫 | SQLite（Python 內建 `sqlite3`），WAL 模式 |
| 研究與驗證 | matplotlib（指標 PNG）、pandas_ta（前端指標驗證）、pytest＋httpx2 |
| 文件 | python-docx、mermaid-cli（npx）、Microsoft Word（COM 更新目錄頁碼；無 Word 時退回開檔自動更新） |
| 作業系統 | Windows Server 2022（現行主機，`10.201.7.12`）／macOS（`setup.sh`、launchd）／Linux |
| 瀏覽器支援 | Chrome／Edge 最新版；手機 RWD |

**連接埠規劃**：

| 情境 | 服務與埠 |
|---|---|
| 本機開發 | API `127.0.0.1:8001`（`--reload`）、Vite `5174`（proxy `/api` → 8001） |
| 正式（本站） | `10.201.7.12:8000`（uvicorn 單進程，同時服務 API 與 `frontend/dist`） |
| 區網主入口 | `10.201.7.12:8080`（quant-portal，排程工作 `Portal-LAN-Web`） |
| 同機其他服務 | 台股平台 `:8011`／`:5188`（維運時勿誤殺） |
| 對外（選用） | Cloudflare Quick Tunnel → `:8000`（手動、非常駐、網址會變） |

**組態管理**：所有設定走環境變數；密鑰檔 `secrets.local.cmd`（Windows，純 ASCII＋CRLF）／`secrets.local.sh`（macOS）不進版控，由啟動器載入 `ADMIN_USER`／`ADMIN_PASS`／`ADMIN_SECRET`（`OPENAI_*` 選填）。對外模式判定：`CRYPTO_QUANT_MODE` 為 `external`／`production`／`public`／`staging`，或 bind 非 loopback；對外模式自動關閉 `/docs`、`/redoc`、`/openapi.json`。本機 loopback 開發沿用預設帳密須明示 `ALLOW_INSECURE_ADMIN_DEFAULTS=1`。幣種清單、時線幣種、AI 設定集中於 `app_config` 表（後台可改，不寫死）。`SQLITE_BACKUP_DIR`／`SQLITE_BACKUP_KEEP`、`AI_HOURLY_CAP`、`CRYPTO_QUANT_APP_DB`／`CRYPTO_QUANT_NEWS_DB` 皆選填有安全預設。

## 2.6 設計限制

1. **資料正確性鐵律**：僅儲存已收盤 K 棒（抓取端以 `close_time` 過濾）；回測不前視（訊號動作延至 `open[t+1]` 成交）；改動訊號或回測後必須重跑 `src/verify_backtest.py` 與 `src/verify_indicators.py`。
2. **研究紀錄不可竄改**：`model_registry` 與四張 forecast 表掛 `BEFORE UPDATE／DELETE` 觸發器（10 個），重跑只能產生新快照；此類資料不可重建，依賴每日備份保全。
3. **宏觀規則凍結**：`src/macro_regime.py` 門檻訂於檢定之前，不得依 `macro_eval` 結果回頭調整；若要納入買賣分數須另行宣告新 holdout。
4. **安全 fail-closed**：對外模式下 `ADMIN_SECRET` 未達 32 字元或為預設值即拒絕啟動；`ADMIN_PASS` 須 12 字元以上（唯一例外：明確設定的 legacy 密碼放行但記高風險警告）；限流與登入鎖定為行程內狀態。
5. **單機單進程**：SQLite 單寫入者；四個排程 `max_instances=1`、`coalesce=True`，手動與排程共用互斥鎖；排程使用系統本地時區（設計基準台灣），主機時區改變會使抓取時間點漂移；錯過的排程不補跑。
6. **版控紀律**：`data/`、`reports/` 執行期產物不進版控；提交前以 `scripts/check_staged_runtime_artifacts.py` 唯讀檢查；`.cmd` 檔純 ASCII＋CRLF、`*.sh`／`*.mjs`／`*.plist` 一律 LF。
7. **誠實揭露**：所有績效數字附聲明（動量策略樣本外含選參保留、會漂移、未實盤）；預測信心不足即拒答；宏觀不顯著即標不顯著。

> ⚪【現況註記】尚未拍板的管理決策（2026-09-02）：①策略去向 A／B／C（後台 #79，研究端建議 B → A）；②GPT 金鑰是否申請（#63，未設定，系統以規則引擎模式運作）；③對外固定網址（#165，需網域與 Cloudflare 權限）；④後台密碼輪替（#166，仍為 legacy 密碼）。拍板後更新本註記、交接手冊主管摘要 §5 與後台任務。

# 3. 系統初步設計

## 3.1 使用者介面結構層次圖

```
crypto-quant
├─ 前台 /（免登入；首頁即 BTCUSDT 詳細頁）
│   ├─ 報價列：即時價（WebSocket）、24h 漲跌、多空判讀
│   ├─ 選幣區：主題分類籤（全部／主流幣／公鏈平台／DeFi 基礎／支付轉帳／迷因幣）＋下拉
│   ├─ 蠟燭圖面板：日線／時線、區間、MA／布林／量、擺盪指標槽（RSI／MACD／KDJ／DMI／BIAS／ATR／OBV）、放大彈窗
│   ├─ 統一判斷摘要（四格）：①六因子訊號 ②研究預測累積狀態 ③回測證據 ④宏觀環境
│   │   ├─ 詳細資訊彈窗：買賣判斷依據（六因子計分明細、自訂訊號實驗室）＋回測面板／指標說明
│   │   └─ 研究預測決策卡：1／5／10 日機率、區間、下行風險、信心、證據、拒答原因
│   ├─ 宏觀環境面板（可開關）：判讀依據／加密自身／背景對照、證據強度、連動強度、環境時間軸
│   ├─ 市場情緒面板（可開關）：恐懼貪婪錶盤與歷史、新聞情緒溫度、新聞牆
│   └─ 名詞小辭典彈窗
└─ 後台 /admin（登入）
    ├─ 監控：健康與新鮮度、最近 50 筆排程、DB 統計；重新匯入、一鍵跑 daily／hourly／news
    ├─ 幣種：清單與資料狀態；新增／編輯／停用／移除
    ├─ 工作項目：進度單一真相（全部／待辦／進行中／完成）
    ├─ 資料庫：11 張白名單表唯讀瀏覽
    ├─ 現況：動量策略今日建議與績效、訊號成績單、指標交叉驗證、指標計算方法
    ├─ 模型成績：研究預測成績單（篩選、治理判讀、promotion gates）
    └─ 分析（即將推出，停用）
```

角色 × 頁面權限矩陣（權限由後端 `require_admin` 強制，前端僅隱藏入口）：

| 頁面 | 訪客 | 管理者 |
|---|---|---|
| 前台全部 | ✔ | ✔ |
| 後台六個分頁 | ✖（401） | ✔ |
| 寫入型 API（回補新聞、觸發管線、改幣種、改設定） | ✖ | ✔（各有限流） |
| `GET /api/forecast/scorecard` | ✖ | ✔ |

**關鍵畫面版面示意**（欄位值皆為示意）：

研究預測決策卡（本系統關鍵畫面：可拒答）——

```
┌─ 研究預測（非投資建議）  [1 日] [5 日] [10 日] ───────────────────┐
│ 狀態：拒答（abstain）    原因：方向優勢不足（|p−0.5| < 0.07）      │
│ 上漲機率 51.5%   下跌機率 48.5%   regime：sideways   信心：低 12 分 │
│ q10 −6.58%   q50 +0.40%   q90 +7.90%   下行風險（≤−7%）18%          │
│ 證據：支持 2 條 / 反對 3 條   as_of 2026-09-01   data_version …    │
│ input_hash fc_…   model historical-baseline-v2   reference_close …  │
└──────────────────────────────────────────────────────────────────┘
```

後台監控（排程與新鮮度）——

```
┌─ 監控 ── 系統時間 2026-09-02 10:30 ── [重新匯入行情] [daily] [hourly] [news] ─┐
│ 幣種   最後日期     落後   狀態      │ 最近排程                                 │
│ BTCUSDT 2026-09-01  1 天  ✔        │ news_fetch     success 02:22 199 篇      │
│ ETHUSDT 2026-09-01  1 天  ✔        │ hourly_pipeline success 02:06 2 幣 38014 │
│ …                                  │ daily_pipeline  success 09:00 …          │
│ DB：prices 66,334 / news 15,359 / forecast_snapshot_v2 1,623                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3.2 模組功能架構圖

後端模組（backend/、src/）與其呼叫關係：

```
scheduler ──► fetch_binance.py ──► indicators.py ──► app_db.ingest_market_data（prices／indicators）
scheduler ──► app_db.backfill_daily_signals ──► scoring.score_row（daily_signal）
scheduler ──► backtest.regenerate_reports／app_db.backfill_backtests（backtest_trade／summary）
scheduler ──► forecasting.generate_forecast ──► app_db.save_forecast_snapshot（append-only）
          ──► app_db.resolve_mature_forecast_outcomes ──► forecast_scorecard.build_forecast_scorecard
scheduler ──► sentiment._fetch_and_save ──► news_store.save_articles ──► news_store.aggregate_daily
scheduler ──► app_db.fetch_fear_greed_history／fetch_macro_history ──► macro_eval.save_evidence
scheduler ──► sqlite_backup.backup_sqlite_databases ──► prune_managed_backups
routers ──► reader（只讀 SQLite；停用幣自動隱藏）
routers/signals ──► signal_engine.get_signal ──► scoring（同一把尺）
routers/backtest ──► backtest_engine.get_backtest ──► backtest.run_backtest（LRU 64）
routers/forecast ──► forecasting／app_db（快照未命中則封存）／forecast_scorecard
routers/ai ──► ai_analyst（build_context → local_analysis → gpt_analysis → 交叉檢核）──► canned_qa／coin_facts
routers/macro ──► services/macro（Yahoo／CoinGecko 即時）──► macro_regime（凍結規則）／load_evidence
routers/admin ──► security_hardening.require_admin ──► app_db／momentum_signal／signal_eval／verify_indicators
main ──(SecurityHeadersMiddleware、access_log_middleware、rate_limiter)──► 所有 router
```

| 模組 | 職責摘要 |
|---|---|
| main／scheduler | 入口、middleware、靜態檔、lifespan；四個排程與互斥鎖、關鍵／非關鍵步驟語意 |
| fetch_binance／indicators | 抓 K 線（分段、429 重試、只存已收盤、原子落盤）、算指標（純 pandas） |
| scoring／signal_engine | 六因子計分單一真相；前台訊號 |
| backtest／backtest_engine | 無前視回測、績效、隨機基準、參數掃描；LRU 與圖表壓縮 |
| forecasting／forecast_evaluation／forecast_scorecard | 內容定址預測、拒答、結算；評分指標庫；point-in-time 成績單與六道 gate |
| momentum_signal | 防禦型跨幣動量今日建議與績效（後台現況） |
| macro_regime／macro_eval／services.macro | 凍結規則、HAC 檢定、即時面板與連動強度 |
| sentiment／news_store | RSS 抓取、詞庫判讀、幣種標記、去重入庫、每日彙總、恐懼貪婪 |
| ai_analyst／canned_qa／coin_facts | 規則引擎、GPT、交叉檢核、固定問答、知識庫 |
| reader／app_db／news_store | 只讀查詢層；兩庫建表、遷移、觸發器、全部讀寫 API |
| security_hardening／rate_limiter／sqlite_backup | fail-closed 啟動檢查、安全標頭；限流與登入鎖定；線上備份 |
| verify_backtest／verify_indicators／signal_eval | 回測驗證器、指標交叉驗證、訊號成績單 |
| frontend | App（前台）、AdminApp（後台）、components、lib（indicators、useLivePrices、signalLab、forecastViewModel）、api |

> ⚪【現況註記】所有背景工作皆在 API 進程內以子行程或執行緒執行，無訊息佇列、無獨立 worker；限流與鎖為行程內狀態（多進程部署需 #167）。前端 `CoinSidebar.jsx`、`MarketOverview.jsx` 為無 import 的死碼。

## 3.3 類別初步描述

系統共 19 張應用資料表（`app.db`，另 SQLite 內部 `sqlite_sequence`）＋2 張（`news.db`），依領域分五群：

| 群組 | 類別（資料表） | 描述 |
|---|---|---|
| 行情與訊號 | `prices`、`indicators`、`daily_signal`、`backtest_trade`、`backtest_summary` | 多週期 K 線與指標（PK symbol＋interval＋ts）；每日訊號歷史；回測逐筆與摘要；皆可由 CSV／Binance 重建 |
| 研究預測 | `model_registry`、`forecast_snapshot_v2`、`forecast_outcome_v2`、`forecast_snapshot`／`forecast_outcome`（v1 凍結） | 模型登錄（`research` 強制 1）；內容定址快照與成熟結果；10 個 append-only 觸發器；不可重建 |
| 情緒與宏觀 | `fear_greed`、`macro_daily`；`news`、`news_sentiment_daily`（news.db） | 恐懼貪婪歷史；宏觀五序列原始值；新聞（url 唯一、coins 標記、summary）；每日 × 每幣情緒分數 |
| 設定與進度 | `app_config`、`tasks` | 集中設定（`coins` 單一真相）；工作項目（進度唯一真相，不可重建） |
| 紀錄與 AI | `job_runs`、`access_log`、`ai_analysis`、`ai_chat`、`ai_usage` | 排程／操作紀錄與 API 存取（30 天）；AI 快取（7 天）、對話與用量（90 天） |

> ⚪【現況註記】`app_config` 目前只有 `coins` 一鍵；`hourly_symbols`（預設 BTC／ETH）與 `ai`（含金鑰）可存在但未設定。訊號增準與 ML 規劃的 `ml_signal` 表、詞庫管理化的 `lexicon` 表尚未建立。

# 4. 系統細部設計

## 4.1 使用者介面流程

### 流程一：訪客看盤 → 判斷摘要 → 研究預測

```
進站（/）→ 首頁即 BTCUSDT 詳細頁：報價列（WebSocket 秒級）＋蠟燭圖（預設日線 180 天）
  → 切幣（分類籤／下拉）／切日線・時線／切區間 → /api/prices、/api/indicators、/api/signals/{sym}、/api/backtest/{sym} 重拉
  → 統一判斷摘要四格：①訊號（教學用途）②預測累積狀態（/forecast/ledger-status）③回測證據 ④宏觀（/api/macro）
  → 展開研究預測決策卡（/api/forecast/{sym}?horizon=5）：ready 顯示機率與區間；abstain 顯示原因
  → 展開詳細資訊彈窗：六因子計分明細、回測面板（可調停損停利）
  → 每 60 秒輪詢 /api/status.data_version，變了才重拉；回前景立即檢查
```

### 流程二：每日資料管線（系統）

```
09:00 觸發 → fetch_binance（15 幣，只存已收盤，原子落盤）→ indicators（逐幣）
  → ingest_market_data → backfill_daily_signals → regenerate_reports／backfill_backtests
  → _assert_data_fresh（落後 > 2 天即 failed）
  ├─ 核心步驟任一失敗 ────────────────────────────► job = failed（不假性成功）
  └─ 通過 → run_forecast_pipeline（獨立 job：封存快照 → 結算成熟 outcome → 成績單摘要）
          → 恐懼貪婪 → 宏觀回補＋macro_eval → 幣種新聞＋aggregate_daily → cleanup_ai／logs／raw
          （附屬步驟失敗只記警告）→ job = success
```

（各步驟程式與失敗語意見 §4.2.1。）

### 流程三：管理者維運（登入 → 監控 → 操作）

```
/admin 登入（帳密 → HMAC token 8 小時；5 次/60 秒；連續失敗 5 次鎖 15 分）
  → 監控：各幣新鮮度（落後 > 2 天 stale）、最近 50 筆 job_runs、DB 統計
  → 需要時：重新匯入行情（3 次/時）／一鍵跑 daily・hourly・news（6 次/時；同型執行中 409）
  → 幣種：新增（實際抓 Binance 入庫，5 次/時）／停用／移除
  → 工作項目：完成標 done、新待辦補上、notes 寫交接
  → 現況：動量策略今日建議、訊號成績單；模型成績：成績單與 gates
  → token 逾時 401 → 前端清 localStorage 回登入頁
```

### 認證流程

1. 使用者輸入帳密 → `POST /api/admin/login`（帳密來自環境變數，常數時間比對）。
2. 取得 token（HMAC-SHA256 簽章，payload 為 `user:到期秒數`，8 小時）；前端存 `localStorage` 鍵 `cq_admin_token`。
3. 之後每個後台請求帶 `Authorization: Bearer <token>`；`require_admin` 驗簽與到期。
4. 401（逾時或無效）→ 前端清除 token 退回登入頁；沒有 refresh token，重新登入即可。
5. 換 `ADMIN_SECRET` 並重啟 → 所有舊 token 立即失效（等同全站登出）。

## 4.2 模組功能

### 4.2.1 行情管線（fetch_binance＋indicators＋app_db）

`fetch_binance.py`：以既有 clean CSV 最後一根時間增量續抓（`startTime` 分段，單次上限 1,000 根，間隔 2 秒，每幣 5 秒），HTTP 429 依 `Retry-After` 重試最多 5 次；只保留 `close_time <= now` 的 K 棒；原始 JSON 落 `data/raw/`（7 天）；新舊以 `date` 去重（新值為準）後先寫 `.csv.tmp` 再 `os.replace()` 原子落盤。`indicators.py`：純 pandas 算 MA20／60／200、RSI(14)（Wilder `alpha=1/14`）、MACD(12,26,9)、布林 20 期 ±2σ（`ddof=0`）、VOL_MA20，同樣原子寫出。`app_db.ingest_market_data(interval)` 以 `INSERT OR REPLACE` 匯入（`_ts()` 只接受兩種時間格式，格式不符跳過該列）；`backfill_daily_signals()` 先清表再用全部歷史指標經 `scoring.score_row()` 重算；`backfill_backtests()` 與 `/api/backtest` 同一套計算。排程 `_run_step()` 檢查子行程結束碼，非 0 即帶 stderr 末 8 行拋錯；`_assert_data_fresh()` 只看日線最新日期，落後超過 2 天視為抓取失敗。

### 4.2.2 六因子計分與回測（scoring＋backtest）

`scoring.score_row()` 以 50 為中立基準加總七項（RSI、MACD、均線排列、MA200、成交量、布林、選用的新聞情緒）夾在 0–100；`signal_from_score()` ≥ 65 BULL、≤ 35 BEAR；前台 `signal_engine.get_signal()` 與回測 `compute_signals()` 共用。`run_backtest()`：`signals[t]` 延到 `open[t+1]` 成交；停損停利為預掛單含進場當根；同根優先序訊號出場 → 停損 → 停利；成本 `fee_rate=0.001`、`slippage_rate=0.0005`；全額單一持倉逐筆複利。`compute_metrics()` 產勝率、CAGR、最大回撤（含起始資本為峰值）、Sharpe（日報酬 ×√365）、買入持有對照（報酬／回撤／Sharpe）、曝險占比、每筆報酬 t 統計量、三類出場次數與權益曲線；`random_entry_baseline()` 以 DP 精確計數不重疊排程並均勻抽樣（500 次、固定種子）產生「亂選日子」的百分位；`parameter_sweep()` 掃 5×5 組停損停利依 Sharpe 排序；`walk_forward_split_report()` 前 60%／後 40% 各自重算。`backtest_engine.get_backtest()` 以（幣、量化參數、指標檔 mtime）為鍵 LRU 64 筆，權益曲線等距抽 600 點並保留極值。

### 4.2.3 研究預測與成績單（forecasting＋forecast_evaluation＋forecast_scorecard）

`generate_forecast()`：清洗收盤（只留 > 0、去重、截到 `as_of`）→ SHA-256 內容定址 → regime（`close vs MA60`＋近 20 日報酬）→ 同 regime 的 h 日報酬（不足 30 筆退回全歷史並標 fallback）→ Laplace 機率、q10／q50／q90、下跌風險（−3／−7／−10%）→ 信心 `100×edge×sample_strength×width_penalty` → 拒答閘門（過期 > 2 天、`|p−0.5|<0.07`、信心 < 40、區間 > 35pp）→ 契約（含 schema v2 證據）；`apply_freshness_guard()` 交付時再驗過期；`resolve_forecast_outcome()` 以第 N 根完成日線結算。`app_db.save_forecast_snapshot()` 驗 horizon、64 位 hash、正 reference_close 後 append；`AppendOnlyConflict` 防覆寫。`forecast_scorecard.build_forecast_scorecard()`：`deduplicate_forecast_ledger()` 每個邏輯預測機會只留首次發行 → `_scoreable()` 過濾 → `_forecast_time_baselines()` Beta(1,1) 擴張式 → `forecast_evaluation.evaluate_replay_records()`（Brier／BSS、log loss、ECE、方向與選擇性、區間／WIS、分類指標）→ `deterministic_block_bootstrap_ci()`（2,000 次、seed 20260721、block `max(7,2h)`）→ `_promotion_gates()` 六道 → `_build_performance_assessment()` 六級 verdict 與 `trust_score`。研究 CLI：`forecast_replay.py`（`j+h<=t` 不變式、`vintage_exact=false`、來源 SHA-256）、`forecast_calibration.py`（monotone Platt／Beta strict walk-forward、`paired_promotion_gate` fail-closed）、`forecast_diagnose.py`（為何永遠拒答；`ledger_status()` 供前台）。

### 4.2.4 新聞情緒與宏觀（sentiment＋news_store＋macro）

新聞：每 30 分抓 9 家 RSS＋Google News（市場級），每日幣種級逐幣查詢；標題經中英雙語加權詞庫判讀（英 105 詞、中 101 詞，權重 1／2）；`_match_coins()` 整字比對標題與摘要寫 `coins`；`save_articles()` URL `INSERT OR IGNORE`＋近 7 日正規化標題去重；`aggregate_daily()` 算 `(多−空)÷總數×100` 夾 −100～+100（30 分更新今昨、每日回補近 3 天）；`/sentiment/news` 快取 30 分，幣種不足 5 則退回全市場並標示；恐懼貪婪快取 1 小時、外部失敗退回 DB。宏觀：`services/macro._compute()` 抓 Yahoo（DXY、VIX、TNX、GSPC、GC=F、N225、KS11、JPY=X）與 CoinGecko global，快取 15 分；`macro_regime.classify()`／`aggregate()` 凍結門檻（DXY 5 日 ±0.5%、VIX 25／16、US10Y 5 日 ±2%、SPX 5 日 ∓1%、黃金中立）、`net ≥ 2` RISK_ON／`≤ −2` RISK_OFF、四驅動齊備才表態；`regime_series()` 由 `macro_daily` 逐日重建（`ffill(limit=5)`）；`macro_eval` 主檢定（籃子 5 日 RISK_ON−RISK_OFF、Newey–West `lag=h`、不重疊對照、區段數）寫 `reports/macro_evidence.json`，`load_evidence()` 連不顯著也原樣帶出；`_compute_linkage()` 60 日滾動相關與歷史百分位（HIGH ≥ 0.5、MEDIUM ≥ 0.3）。

### 4.2.5 AI 雙引擎與後台安全（ai_analyst＋canned_qa＋security_hardening＋rate_limiter）

`ai_analyst.build_context()` 蒐集六因子、近 31 天日線、近 3 天時線、幣種知識檔、恐懼貪婪、宏觀摘要、近 3 天新聞（優先該幣，8 則）；`local_analysis()` 純規則產立場與逐面向解讀；`gpt_analysis()` 固定提示詞、強制 JSON、45 秒逾時；`analyze()` 兩層快取（記憶體 200 筆＋DB 7 天，鍵含資料版本與模型，15 分 TTL）、每小時上限 80、`agreement` 交叉檢核；`ask()` 先 `canned_qa.try_answer()`（歷史查詢優先、最長關鍵詞命中，65 條＋5 類知識意圖）→ 命中則 `enhance_answer()` 潤飾（數字與立場原封保留）→ 未命中才 GPT 自由回答（帶 3 輪對話）或規則引擎摘要；未追蹤幣誠實拒答。`security_hardening.load_admin_security_config()` 啟動時 fail-closed（對外模式密鑰 ≥ 32、密碼 ≥ 12、預設值拒絕；legacy 密碼例外並警告；本機 fallback 需 loopback＋override）；`SecurityHeadersMiddleware` CSP 與安全標頭、敏感路徑 `no-store`；`rate_limiter.SlidingWindowRateLimiter`（`max_entries=4096`，槽位滿寧可拒絕新客戶端）與 `FailedLoginLockout`（5 次／900 秒鎖 900 秒）；`client_identity()` 只採 `request.client.host`。`sqlite_backup.backup_sqlite_database()` 唯讀 URI 開來源、`backup(pages=256)`、`quick_check`、`fsync`、SHA-256、`os.replace()`。

## 4.3 類別細部描述

以下為核心類別（資料表）的欄位級設計；完整定義以 `backend/services/app_db.py`、`news_store.py` 的 `init_db()` 為準。

### prices／indicators（行情主表）

| 欄位群 | 主要欄位 | 說明 |
|---|---|---|
| 主鍵 | `symbol`、`interval`（預設 `'1d'`）、`ts` | 日線 `YYYY-MM-DD 00:00:00`、小時線到小時；索引 `idx_prices_sym`／`idx_ind_sym` |
| OHLCV | `open`、`high`、`low`、`close`、`volume` REAL | 只存已收盤 K 棒 |
| 指標 | `close`、`ma20`、`ma60`、`ma200`、`rsi`、`macd`、`signal`、`hist`、`bb_upper`、`bb_lower`、`vol_ma20` REAL | 由 `indicators.py` 計算 |

### daily_signal（每日訊號歷史）

PK `(date, symbol)`；`signal`（BULL／BEAR／NEUTRAL）、`score` INTEGER、`close`、`rsi`。由 `backfill_daily_signals()` 全歷史重算，前台信心分數走勢讀此表。

### backtest_trade／backtest_summary（回測入庫）

`backtest_trade` PK `(symbol, interval, entry_date)`：`exit_date`、`entry_price`／`exit_price`、`entry_trigger_price`／`exit_trigger_price`、`return_pct`／`gross_return_pct`／`cost_pct`、`hold_days`、`exit_reason`、`profit`。`backtest_summary` PK `(symbol, interval)`：`total_trades`、`win_rate`、`total_return_pct`、`cagr_pct`、`max_drawdown_pct`、`sharpe_ratio`、`avg_hold_days`、`profit_factor`、`avg_win_pct`／`avg_loss_pct`、`buy_hold_return_pct`、`excess_return_pct`、三類出場次數、四個參數、期間、`updated_at`。

### model_registry（模型登錄）

PK `model_version`；`name`、`status`、`research INTEGER CHECK (research = 1)`、`methodology_json`、`created_at`；觸發器 `model_registry_no_update`／`_no_delete`。現行兩版 `historical-baseline-v1`／`v2`。

### forecast_snapshot_v2（研究預測快照）

| 欄位群 | 主要欄位 | 說明 |
|---|---|---|
| 識別 | `forecast_id` PK（`fc_`＋24 位 hash） | 內容定址 |
| 範圍 | `symbol`、`horizon_days CHECK IN (1,5,10)`、`as_of`、`generated_at`、`model_version` FK | UNIQUE `(symbol, horizon_days, as_of, model_version, input_hash)` |
| 來源身分 | `input_hash`（64 位 lowercase SHA-256）、`data_version`、`reference_close`（> 0） | 修訂即新列 |
| 內容 | `status`（ready／abstain）、`payload_json`、`created_at` | 機率、分位、風險、regime、信心、證據、拒答原因 |
| 保護 | 觸發器 `forecast_snapshot_v2_no_update`／`_no_delete`；索引 `idx_forecast_v2_lookup`、`idx_forecast_v2_scorecard` | |

### forecast_outcome_v2（成熟結果）

PK `forecast_id` FK → snapshot；`target_as_of`、`resolved_at`、`realized_return_pct`、`actual_direction`（up／down／flat）、`payload_json`（`outcome_up`、`reference_close`、`model_version`、`input_hash` 須與快照一致）、`created_at`；觸發器禁改禁刪。v1 的 `forecast_snapshot`／`forecast_outcome` 欄位相同但無 `input_hash`／`data_version`／`reference_close`，各 90 列已凍結。

### fear_greed／macro_daily（外部序列）

`fear_greed(date PK, value INTEGER, label)`；`macro_daily(date PK, dxy, vix, us10y, spx, gold REAL)`，逐欄 `COALESCE` upsert，只存原始值不存判讀。

### app_config／tasks／job_runs／access_log（設定、進度、紀錄）

`app_config(key PK, value_json, updated_at)`；`tasks(id PK AUTOINCREMENT, title, detail, notes, status DEFAULT 'planned', phase, planned_date, done_date, sort_order, created_at, updated_at)` 索引 `idx_tasks_status`，`update_task()` 白名單欄位、改 done 自動補完成日；`job_runs(id, job_type, status, started_at, finished_at, message)` 索引 `idx_job_started`；`access_log(id, ts, path, symbol, status_code, latency_ms)` 索引 `idx_access_ts`。

### ai_analysis／ai_chat／ai_usage（AI）

`ai_analysis(cache_key PK, symbol, generated_at, json)`；`ai_chat(id, ts, symbol, question ≤500 字, answer ≤4000 字, source, model)`；`ai_usage(id, ts, kind, model, prompt_tokens, completion_tokens, ok, error ≤300 字)`。

### news／news_sentiment_daily（news.db）

`news(id PK, url UNIQUE, title NOT NULL, domain, category, sentiment, published_at, fetched_at NOT NULL, coins, summary)` 索引 `idx_fetched`、`idx_category`、`idx_published`；`sentiment` 只依標題判讀、`summary`（≤ 500 字）只用於幣種比對。`news_sentiment_daily(date, symbol, score, n_total, n_bull, n_bear, top_json, updated_at)` PK `(date, symbol)`，`symbol='MARKET'` 為全市場。

## 4.4 資料結構

### 核心 ER 關聯

```
app_config（coins 清單）─決定抓取範圍─► prices ──同鍵──► indicators ──重算──► daily_signal
indicators ──回測──► backtest_trade ──彙總──► backtest_summary
model_registry ──< forecast_snapshot_v2 ──1:1──> forecast_outcome_v2
model_registry ──< forecast_snapshot（v1）──1:1──> forecast_outcome（v1，凍結）
fear_greed、macro_daily（獨立外部序列；macro_daily → macro_eval → reports/macro_evidence.json）
tasks、job_runs、access_log、ai_*（獨立紀錄表）
news ──彙總──► news_sentiment_daily（news.db）

（──< ＝一對多；1:1 ＝主鍵對主鍵；append-only：model_registry 與四張 forecast 表）
```

### 排程工作狀態機

```
start_job() ──► running ──成功──► success（finish_job）
                  │
                  └──任一核心步驟拋錯──► failed（message 含 stderr 末 8 行）
（進程被砍：留在 running 的殭屍紀錄；後台以排程模組的鎖判定執行狀態，不看此欄）
```

### 研究預測狀態機

`sealed`（封存，status ready／abstain）→ `pending`（等第 N 根完成日線）→ `resolved`（outcome append，一對一）；歷史 K 線修訂 → 新 `input_hash` 另存新快照 → 成績單只採 `created_at`＋rowid 最早的首次發行版本，其餘列入 `revisions_excluded`；任何狀態皆不可 UPDATE／DELETE。

### 關鍵 JSON 結構

| 結構 | 所在欄位 | 內容 |
|---|---|---|
| `payload_json`（快照） | forecast_snapshot_v2 | `probabilities.up/down`、`return_quantiles_pct.q10/q50/q90`、`downside_risk.threshold_pct/probability`、`regime`、`confidence.score/level`、`status`、`abstain_reason`、`data_quality.stale/observations`、`evidence{schema_version:2, supporting[], opposing[]}` |
| `payload_json`（結果） | forecast_outcome_v2 | `outcome_up`、`reference_close`、`model_version`、`input_hash` |
| `methodology_json` | model_registry | 輸入、regime（MA60＋20 日報酬）、估計器（Laplace）、horizons、限制、`point_in_time: true` |
| `value_json`（`coins`） | app_config | `[{symbol, zh, ticker, enabled}]` 15 筆 |
| `top_json` | news_sentiment_daily | 代表性標題最多 3 則（優先非中立） |
| `json` | ai_analysis | `{local, gpt, gpt_status, agreement, …}` |
| `factors` | `/api/signals` 回應 | 六（七）因子逐項加減與理由字串 |
| `linkage`／`evidence` | `/api/macro` 回應 | 60 日滾動相關與百分位；檢定摘要與 `SUPPORTED`／`DIRECTIONAL_ONLY` |

### 主要索引

`prices`／`indicators`：`(symbol, interval, ts)`；`tasks(status)`；`job_runs(started_at)`；`access_log(ts)`；`ai_chat(ts)`、`ai_usage(ts)`；`backtest_trade(symbol, interval, entry_date)`；forecast v2：`lookup(symbol, horizon_days, as_of, model_version, input_hash)`、`scorecard(model_version, horizon_days, symbol, as_of)`；news：`fetched_at`、`category`、`published_at`。

## 4.5 成員函數（關鍵服務函式與公開介面）

### API 公開介面（摘要）

完整契約以非對外模式 `/docs`（OpenAPI）為準，導覽見交接手冊第 05 章：

| 路由群組 | 用途 | 權限 |
|---|---|---|
| `/symbols`、`/intervals`、`/status`、`/verify` | 幣種清單、週期、資料版本心跳、指標驗證 | 公開 |
| `/prices/{sym}`、`/indicators/{sym}` | K 線與指標（`days`／`start`／`end`／`interval`） | 公開 |
| `/signals*` | 六因子訊號與歷史 | 公開 |
| `/backtest*` | 即時回測（12 次／分）、入庫摘要與逐筆 | 公開 |
| `/forecast/{sym}`、`/forecast/ledger-status`、`/forecast/scorecard` | 快照（30 次／分）、累積狀態、成績單 | 公開／公開／需登入 |
| `/sentiment/*` | 恐懼貪婪、情緒分數、新聞牆、來源；`news/backfill` | 公開；回補需登入 |
| `/ai/analysis/{sym}`、`/ai/ask`、`/ai/config` | 雙引擎分析、問答、GPT 探測 | 公開（限流） |
| `/macro`、`/macro/history`、`/correlation` | 宏觀即時與歷史、相關性 | 公開 |
| `/admin/*`（23 個） | 登入、監控、工作項目、操作、幣種、資料庫、AI 設定、驗證、成績單、策略 | 除 login 外需登入 |

（共 53 個端點：30 公開、23 需登入。）

### 逐模組服務函式一覽

以下自 `backend/services/`、`backend/scheduler.py` 與 `src/` 程式碼逐字抽取（2026-09-02）；僅列公開函式與核心機制、私有輔助函式略過，完整簽章以程式碼為準。

### scheduler.py — 背景排程與互斥

| 函式 | 職責 |
|---|---|
| `start_scheduler()` | 建 `BackgroundScheduler`，註冊 4 個固定 id 工作（`replace_existing`、`max_instances=1`、`coalesce=True`）並啟動 |
| `run_pipeline()` | 每日管線 14 步：核心 1–4、7 失敗即 failed；5、6、9–14 非關鍵只警告；8 為獨立 forecast job |
| `run_hourly_pipeline()` | 對 `get_hourly_symbols()` 增量抓 1h、算指標、入庫；全部關鍵 |
| `run_forecast_pipeline()` | 每幣 × 3 天期產快照（已存在沿用不覆寫）→ 結算成熟結果 → 成績單摘要 |
| `fetch_news_job()` | 抓 RSS 存庫並記 `job_runs` |
| `run_sqlite_backup()` | 備份兩庫並 `prune_managed_backups`（保留 `SQLITE_BACKUP_KEEP`，預設 14、夾 1–365） |
| `job_is_running(job_type)` | 只探詢不取鎖，供後台先擋重複觸發（409） |
| `_exclusive(job_type)`／`_job_slot()` | 關鍵機制：非阻塞獨占槽位，排程與手動觸發互斥，取不到即跳過該輪 |
| `_run_step(name, args, env)` | 跑子行程並檢查結束碼，非 0 帶 stderr 末 8 行拋 `RuntimeError` |
| `_assert_data_fresh()` | 日線最新日期落後 > `MAX_DATA_LAG_DAYS=2` 即視為抓取失敗 |

### app_db.py — 主資料庫建表與讀寫

| 函式 | 職責 |
|---|---|
| `ensure_ready()`／`init_db()` | 延遲建表（lifespan 呼叫）；建 19 張表、13 個索引、10 個 append-only 觸發器；補 `tasks.notes` 遷移 |
| `get_config(key)`／`set_config(key, value)` | `app_config` JSON 讀寫（upsert） |
| `get_coins()`／`get_enabled_symbols()`／`get_hourly_symbols()` | 幣種設定（預設 15 檔）；啟用清單為排程單一真相；時線清單（預設 BTC／ETH） |
| `start_job()`／`finish_job()`／`recent_jobs(limit=50)` | `job_runs` 寫入與查詢 |
| `log_access(path, symbol, status_code, latency_ms)` | `access_log` 寫入，不記個資 |
| `list_tasks()`／`create_task()`／`update_task()`／`delete_task()` | 工作項目 CRUD；白名單欄位；改 done 自動補完成日；`estimate_days()`／`suggest_category()` 自動估 |
| `ingest_market_data(interval)` | CSV → `prices`／`indicators`，`INSERT OR REPLACE`；`_ts()` 格式防線 |
| `fetch_and_ingest_symbol(symbol)` | 後台新增幣：以 venv Python 跑抓取＋指標再入庫 |
| `backfill_daily_signals()`／`backfill_backtests(symbols, …)` | 清表重算訊號；逐幣回測入庫（與 API 同一套） |
| `load_backtest_summary()`／`load_backtest_trades()` | 入庫回測讀取 |
| `register_forecast_model(metadata)` | 登錄模型（`research` 必 True）；內容不同即 `AppendOnlyConflict` |
| `save_forecast_snapshot(payload)`／`load_forecast_snapshot()`／`load_forecast_by_id()` | 追加 v2 快照（驗 horizon、64 位 hash、正 reference_close）；內容定址讀取 |
| `pending_forecast_snapshots()`／`save_forecast_outcome()`／`load_forecast_outcome()` | 未結算快照；追加結果（冪等或衝突） |
| `load_forecast_ledger(horizon, model_version, symbol, include_legacy)` | 快照 LEFT JOIN 結果的完整帳本（預設只 v2） |
| `resolve_mature_forecast_outcomes(price_loader, limit)` | 結算所有到期預測；掃描量 `max(10000, limit×10)` |
| `fetch_fear_greed_history(limit)`／`fetch_macro_history(range_)` | alternative.me 全量回補；Yahoo 五序列逐欄 upsert |
| `save_ai_analysis()`／`load_ai_analysis()`／`log_ai_chat()`／`log_ai_usage()`／`ai_stats()` | AI 快取、對話、用量與統計 |
| `cleanup_ai(90, 7)`／`cleanup_logs(30)` | 保留政策 |
| `market_stats()`／`coin_data_status(interval)` | 筆數、日期跨度、各幣狀態 |

### news_store.py — 新聞資料庫

| 函式 | 職責 |
|---|---|
| `init_db()` | WAL、兩表三索引；`_ensure_column` 補 `coins`、`summary` |
| `save_articles(articles)` | URL `INSERT OR IGNORE`＋近 7 日正規化標題去重（`_norm_title`），回實際新增數 |
| `query_by_date()`／`query_recent()`／`available_dates()`／`total_count()` | 依發布日、依存入時間、有資料日期（最近 90 個）、總數 |
| `source_stats(top=12)` | 來源實況（總數、網域數、聚合筆數、前 12） |
| `aggregate_daily(dates)`／`load_sentiment_daily(symbol, days)` | 每日 × 每幣情緒彙總與讀取 |

### reader.py — 前台只讀層

| 函式 | 職責 |
|---|---|
| `available_symbols(interval)`／`intervals_available()`／`data_range()` | 啟用中 ∩ 有資料的幣；週期清單；起訖 |
| `data_versions()`／`last_updated()` | 各週期 `MAX(ts)#COUNT` 心跳；各幣最新日線 |
| `load_prices()`／`load_indicators()`／`load_signal_history()`／`load_macro_history()`／`load_fear_greed_history()` | SQL alias 還原大寫 CSV 欄名，回傳形狀不變 |
| `load_correlation()` | 日報酬相關矩陣與年化波動 |
| `_range_clause(days, start, end, tscol, interval)` | 關鍵機制：`start`／`end` 閉區間（`end+1 day`）；`days` 走 `DESC LIMIT`（小時線 ×24）再反轉 |

### signal_engine.py／scoring.py — 訊號

| 函式 | 職責 |
|---|---|
| `signal_engine.get_signal(symbol)` | 取近 5 天指標算分與訊號，附因子理由；無資料回 UNKNOWN／50 |
| `signal_engine._latest_news_score(symbol)` | 近 5 天新聞情緒（幣種 → MARKET 退回） |
| `scoring.score_row(rsi, hist, prev_hist, close, ma20, ma60, ma200, volume, vol_ma20, bb_upper, bb_lower, news_score=None, news_scoring=True)` | 七項加總夾 0–100，回 `(score, factors)` |
| `scoring.signal_from_score(score)` | ≥ 65 BULL、≤ 35 BEAR、其餘 NEUTRAL |

### backtest.py／backtest_engine.py — 回測

| 函式 | 職責 |
|---|---|
| `compute_signals(df, sentiment_by_date)` | 逐根以 `score_row` 算訊號，`sigs[i]` 只用第 `i` 根及更早 |
| `run_backtest(df, stop_loss=-0.06, take_profit=0.20, fee_rate=0.001, slippage_rate=0.0005, signals)` | 隔根開盤成交、預掛停損停利、逐筆明細 |
| `compute_metrics(trades, df, include_curve)` | 全套績效含買入持有對照、曝險、t 統計量、權益曲線 |
| `random_entry_baseline(df, trades, …, n_sims=500, seed=20260706)` | DP 計數＋均勻抽樣不重疊排程的隨機進場百分位 |
| `parameter_sweep()`／`walk_forward_split_report(train_ratio=0.60)`／`regenerate_reports()` | 5×5 掃描；前後段對照；重產靜態報表 |
| `backtest_engine.get_backtest(symbol, …)` | 主入口：訊號算一次共用，LRU 64（鍵含指標檔 mtime），曲線壓 600 點 |

### forecasting.py — 研究預測

| 函式 | 職責 |
|---|---|
| `model_metadata()` | 版本、`status="research"`、方法論與限制 |
| `latest_completed_daily_date(now)` | 最後一根完整收盤 UTC 日線（今天 −1） |
| `generate_forecast(symbol, horizon_days, rows, as_of, now)` | 完整契約：機率、分位、下跌風險、信心、建議、證據；拒答閘門 |
| `apply_freshness_guard(snapshot, now)` | 交付時過期改判 abstain／wait 並插 `data_stale` 證據，原快照不動 |
| `resolve_forecast_outcome(snapshot, rows, now)` | 第 N 根完成日線結算；未成熟回 None |
| `_input_hash(frame)`／`_forecast_id(…)`／`_regime(close)`／`_historical_returns(…)` | 內容定址；id 派生；MA60＋20 日報酬 regime；同 regime 樣本（< 30 退回全歷史） |

### forecast_evaluation.py／forecast_scorecard.py — 成績單

| 函式 | 職責 |
|---|---|
| `evaluate_binary_forecasts(probabilities, outcomes, baseline_probability, classification_threshold=0.5, confidence_threshold=0.60, bins=10, statuses)` | Brier、BSS、log loss、ECE、校準分箱、選擇性指標、逐 status |
| `binary_classification_metrics()`／`risk_coverage_curve()` | 混淆矩陣、F1、BA、MCC、ROC-AUC、AP；tie-preserving risk–coverage |
| `evaluate_prediction_intervals(lower, upper, outcomes, nominal_coverage=0.80, medians)` | coverage、width、pinball、interval score、WIS |
| `deterministic_block_bootstrap_ci(values, weights, block_size, n_resamples, confidence_level, random_seed)` | 循環移動區塊 bootstrap，固定種子 |
| `evaluate_replay_records(records, …)` | 由重播紀錄組計分卡（overall、intervals、CI、by_horizon） |
| `forecast_scorecard.build_forecast_scorecard(horizon, model_version, symbol, window, include_legacy, now)` | 對外主入口；即時計算不落地 |
| `deduplicate_forecast_ledger(rows)` | 關鍵機制：每個邏輯預測機會只留首次發行（去重先於剔除未解決列） |
| `_forecast_time_baselines(rows)`／`_promotion_gates(…)`／`_build_performance_assessment(…)` | Beta(1,1) 擴張式基準；六道 gate；六級 verdict 與 `trust_score` |

### momentum_signal.py — 動量策略

| 函式 | 職責 |
|---|---|
| `load_panels()` | 讀 `data/clean/*_1d.csv` 組收盤／開盤寬表，截到 BTC 最後有效日 |
| `_target_weights(close_panel, decision_index)` | point-in-time 目標權重與決策細節（regime、topK、曝險、理由碼） |
| `today_signal(close_panel, open_panel)` | 最近一次換倉持倉與執行狀態（pending／executed／partially_filled／unfilled） |
| `_backtest(close_panel, open_panel)`／`strategy_metrics(…)` | 每 R 根 `open[t+1]` 進、`open[t+1+R]` 出，扣 0.15% 換手；全期與後 40% 績效及市場 CAGR |
| `cached_strategy()` | 以 clean CSV mtime 為鍵快取 `{strategy, today, perf}` |

常數：`L=30`、`K=5`、`R=10`、`REGIME_N=100`、`VOLWIN=20`、`TARGET_VOL=0.30`、`COST=0.0015`、`SKIP=200`、切分 60/40。

### macro_regime.py／macro_eval.py／services/macro.py — 宏觀

| 函式 | 職責 |
|---|---|
| `macro_regime.classify(key, value, change_pct)`／`aggregate(impacts)`／`build_factor()`／`summary_zh()` | 單因子判讀（凍結門檻）；`net` 與 verdict（±2）；顯示物件；抬頭句 |
| `macro_regime.regime_series(frame, lookback=5, ffill_limit=5)` | 宏觀日資料 → 逐日 verdict 序列，無前視、四驅動齊備才表態 |
| `macro_eval.build_evidence()`／`save_evidence()` | 主檢定（籃子 5 日 RISK_ON−RISK_OFF）、逐 horizon 表、區段數、連動、overlay → `reports/macro_evidence.json` |
| `macro_eval.ols_hac()`／`mean_with_hac_t()`／`non_overlap_t()`／`episodes()` | Newey–West；不重疊對照；區段計數 |
| `services.macro.get_macro()`／`get_macro_history(days)`／`macro_snapshot_for_analysis()` | 面板（快取 15 分、失敗回舊或安全空結構）；歷史標籤；AI 用摘要（不等外部 API） |
| `services.macro.load_evidence()`／`_compute_linkage()`／`_linkage_reading()` | 讀證據（不顯著照回）；60 日滾動相關；HIGH／MEDIUM／LOW 與百分位 |

### ai_analyst.py／canned_qa.py／coin_facts.py — AI

| 函式 | 職責 |
|---|---|
| `gpt_config()`／`gpt_enabled()` | 環境變數優先於 `app_config['ai']`；無金鑰全站降級 |
| `detect_symbol(question)`／`find_unknown_coin()`／`unsupported_coin_reply()` | 三段式幣種偵測（含錯字容忍）；未追蹤幣誠實拒答 |
| `build_context(symbol)`／`local_analysis(ctx)`／`gpt_analysis(ctx, local)` | 結構化事實；規則引擎；GPT（固定提示詞、JSON、45 秒） |
| `enhance_answer(question, base_answer, intent, symbol, ctx)`／`gpt_history_fallback()` | 固定答案潤飾（數字與立場原封）；範圍外歷史唯一允許動用訓練知識 |
| `ask(symbol, question, history)`／`analyze(symbol, use_gpt, force)`／`test_gpt()` | 問答入口（≤ 500 字、3 輪）；分析主入口（兩層快取、`agreement`）；後台測試連線 |
| `_rate_ok()`／`_chat(messages, want_json, kind)`／`_parse_json()` | 每小時 80 次滑動視窗；統一呼叫並記 `ai_usage`；容錯解析 |
| `canned_qa.try_answer(symbol, question)`／`match_kind()`／`market_greeting()`／`ask_which_coin()` | 固定問答主入口（歷史優先、最長關鍵詞）；命中查詢；全站模式打招呼與反問 |
| `canned_qa._history_answer()`／`_knowledge_answer()`／`_build_vars()` | 歷史查詢直接查 DB（零幻覺、範圍外三層回覆）；知識型答案；約 30 個模板變數 |
| `coin_facts.get_facts(symbol)` | 15 幣七欄位知識檔；未收錄回 None 交棒 |

### security_hardening.py／rate_limiter.py／sqlite_backup.py — 安全與備份

| 函式 | 職責 |
|---|---|
| `load_admin_security_config(environ)` | fail-closed 憑證檢查，回 `AdminSecurityConfig`（含 `external`、`weak_external_password`） |
| `SecurityHeadersMiddleware` | CSP 等安全標頭；HTTPS 加 HSTS；敏感路徑 `no-store` |
| `SlidingWindowRateLimiter.check(scope, client, limit, window_seconds)` | 滑動視窗限流，回 `allowed`／`retry_after`／`remaining` |
| `FailedLoginLockout.status()`／`record_failure()`／`record_success()` | 5 次失敗鎖 900 秒 |
| `enforce_rate_limit(request, scope, limit, window_seconds)`／`client_identity(request)` | 超限拋 429＋`Retry-After`；只採 `request.client.host` |
| `backup_sqlite_database(source, destination, timeout_seconds=30)` | 唯讀 URI、`backup(pages=256)`、`quick_check`、`fsync`、SHA-256、原子換上 |
| `backup_sqlite_databases(sources, backup_directory, now)`／`prune_managed_backups(dir, keep_per_database=14)` | 多庫備份與命名；只刪受管檔名 |

### src 驗證與研究模組

| 函式 | 職責 |
|---|---|
| `verify_indicators.cross_check_indicators(symbols, interval)`／`cached_result(interval)` | 獨立演算法逐點比對（RSI 絕對 0.05、其餘相對 1e-3、跳過 250 列）；以指標檔版本快取 |
| `verify_backtest.main()` | 十組 PASS／FAIL（檔案、欄位、無重疊、勝率與總報酬手算、進場價＝原始開盤、停損停利方向、出場相加、時序無前視） |
| `signal_eval.evaluate_signal(symbols)`／`cached_scorecard()` | onset 進場、隔日 open、5／10／20 天 vs 任一天進場；快取鍵含 `scoring.py` mtime |
| `fetch_binance.fetch_history()`／`save_clean()`／`merge_with_existing()` | 分段抓、只存已收盤、原子落盤、去重合併 |
| `indicators.add_indicators(df)` | MA、RSI（Wilder）、MACD、布林（ddof=0）、VOL_MA20 |
| `forecast_replay.replay_forecasts(symbol, rows, horizons, start_date, end_date, min_observations)` | `j+h<=t` 無洩漏重播；`vintage_exact=False`；來源 SHA-256 |
| `forecast_calibration.walk_forward_calibrate(records, min_samples=180, min_issue_dates=90, min_class_samples=30, …)`／`paired_promotion_gate(…)` | monotone Platt／Beta strict walk-forward；fail-closed 人工複核閘門 |
| `forecast_diagnose.ledger_status()`／`report_scale()`／`report_skill()` | 前台累積狀態摘要；信心三乘項分布；命中率與 Brier vs 最笨對照 |
| `macro_longrun.run(label, start)` | 2017 起 8 年旁路重跑檢定 |
| `cross_sectional*.evaluate()`／`backtest()` | 研究血脈（掃描、驗證、regime、風控、穩健度、健全性），唯讀 |

# 5. 系統需求至系統設計之追溯

## 5.1 追溯工具（GitHub）

| 項目 | 內容 |
|---|---|
| Repository | `origin`：`git@github.com:yunzhenz-chainwin/crypto-quant.git`（SSH）；`newremote`：`https://github.com/Chungyunzhenz/crypto-quant.git`（HTTPS）；同步推送兩個遠端 |
| 主線分支 | `main`；單人倉庫直接 commit＋push，不開功能分支；無標籤 |
| CI | 無 `.github/`；驗證以本機為主：`pytest tests -q`（141 項）、`npm run lint`／`build`／`test:forecast`、`verify_backtest`、`verify_indicators`、`check_staged_runtime_artifacts.py`（提交前唯讀檢查） |
| 進度追溯 | 後台「工作項目」（`tasks` 表：done 137、in_progress 2、planned 44）；commit 訊息與任務編號互相對照 |
| 執行追溯 | `job_runs`（1,742 列）；研究 ledger 的 `input_hash`／`data_version`／`model_version`；`reports/macro_evidence.json` |

**Commit 訊息格式**：

格式：

```
<type>: <subject>          # 中文或英文皆可，主旨一行
```

`type` 使用：`feat`（功能）、`fix`（修正）、`docs`（文件）、`research`／`analysis`（研究結論）、`data`（資料回補）、`perf`（效能）、`deploy`（部署）。

範例（取自實際 git 歷史）：

```
feat: add auditable forecasts and harden quant reliability
fix: stop one torn CSV row from silently killing both pipelines
docs: 交接文件總體檢修正＋新增系統規格書＋大合併精簡為 9 章
research: 跨幣動量找 edge（掃描→驗證→regime→風控→健全性→穩健度）
analysis: 訊號改良實驗（6 變體確認無 forward edge）
```

2026-06-17 啟動至 2026-09-01 共 121 個 commit（6 月 24、7 月 73、8 月 18、9 月 6）。未走 PR：單人開發無第二審查者，由 repo 權責者直接合併；提交前本機驗證全綠，且只提交當次工作的檔（排程產物不入版控）。

## 5.2 需求 ↔ 設計 ↔ 驗證追溯表

| 需求（US／能力） | 設計落點（本文件） | 實作模組 | 驗證 | 現況 |
|---|---|---|---|---|
| US-01 即時報價與蠟燭圖 | §3.1、§4.1 流程一 | `lib/useLivePrices.js`、`CandlestickChart.jsx` | 前端直連驗證；`npm run build` | 已上線 |
| US-02 多幣多週期切換 | §4.2.1、§4.3 prices | `reader.py`、`fetch_binance.py`、`indicators.py` | `test_reader_date_range.py`；指標交叉驗證 16/16 | 已上線 |
| US-03 訊號與誠實標示 | §4.2.2 | `scoring.py`、`signal_engine.py`、`signal_eval.py` | 成績單（無 edge，降教學）；`verify_backtest.py` | 已上線（教學定位） |
| 回測無前視 | §4.2.2 | `backtest.py`、`backtest_engine.py` | `verify_backtest.py` 第十組；`test_backtest_cache.py`、`test_quant_reliability.py` | 已上線 |
| US-04 研究預測可拒答 | §4.2.3、§4.3 forecast_* | `forecasting.py`、`app_db` ledger | `test_forecast_api.py`（10）；觸發器測試 | 已上線（持續拒答，#191） |
| 成績單與發布閘門 | §4.2.3、§4.4 狀態機 | `forecast_evaluation.py`、`forecast_scorecard.py` | `test_forecast_evaluation.py`（18）、`test_forecast_scorecard_api.py`（6）、`test_forecast_replay.py`、`test_forecast_calibration.py`（22） | 已上線（`insufficient_evidence`） |
| US-05 情緒與新聞出處 | §4.2.4、§4.3 news | `sentiment.py`、`news_store.py` | `test_sentiment_fear_greed.py`；來源統計端點 | 已上線 |
| US-06 宏觀與證據強度 | §4.2.4 | `macro_regime.py`、`macro_eval.py`、`services/macro.py` | `test_macro_regime.py`（8）；主檢定不顯著、長樣本複核 | 已上線（僅背景） |
| AI 解讀與問答 | §4.2.5 | `ai_analyst.py`、`canned_qa.py`、`coin_facts.py` | 固定問答測試（11/11、10/10、7/7）；`test_api_smoke.py` | 後端就緒；面板暫停；金鑰未設 |
| US-07 排程監控 | §4.1 流程三、§4.4 排程狀態機 | `scheduler.py`、`routers/admin.py` | `test_forecast_scheduler.py`；`job_runs` 實況 | 已上線 |
| US-08 幣種管理即時生效 | §2.5 組態、§4.5 app_db | `app_db.get_coins()`／`fetch_and_ingest_symbol()` | 後台實測；`app_config` 單一真相 | 已上線 |
| US-09 工作項目 | §4.3 tasks | `app_db` tasks CRUD | 後台實測 | 已上線 |
| US-10 成績單與動量策略 | §4.5 momentum_signal | `momentum_signal.py`、`signal_eval.py` | 後台現況頁；研究血脈 `cross_sectional*` | 已上線（後台） |
| US-11 GPT 設定與用量 | §4.2.5 | `routers/admin.py` `/ai/*` | 金鑰遮罩；`ai_usage` | 已上線（金鑰未設） |
| US-12 每日管線不假性成功 | §4.1 流程二 | `scheduler._run_step`、`_assert_data_fresh` | `job_runs` failed 語意；撕裂 CSV 修復 | 已上線 |
| 安全 fail-closed 與限流 | §2.6 第 4 點、§4.2.5 | `security_hardening.py`、`rate_limiter.py` | `test_security_hardening.py`（12）、`test_rate_limiter.py`（11） | 已上線；#165–#167 待辦 |
| 自動備份 | §4.2.5 | `sqlite_backup.py` | `test_sqlite_backup.py`（5） | 已上線 |
| US-13 換機搬遷 | §2.5 環境 | `make_migration_bundle.py`、`setup.sh` | 手動演練（macOS 支援 commit） | 已交付 |
| 版控產物防線 | §2.6 第 6 點 | `check_staged_runtime_artifacts.py` | `test_check_staged_runtime_artifacts.py`（5） | 已上線 |
| 動量策略上前台 | §2.2 現況註記 | （規劃：`/api/strategy/today`） | 訊號增準 Phase A 驗收門檻（樣本外 5 日勝率 ≥ 基準 +0.5pp） | 待主管拍板（#79） |

# 6. 附錄

## 6.1 參考書目

1. 《crypto-quant 系統文件與交接手冊》docs/crypto-quant_交接手冊.docx（2026-09-02，本文件主要來源：主管摘要＋導讀＋第 01–13 章＋附錄 A–D）
2. 《crypto-quant README》README.md（活文件：快速啟動、架構、目錄地圖、排程、AI 設計、訊號現況、開發慣例、未來規劃）
3. 後台「工作項目」（`data/app.db` 的 `tasks` 表，進度單一真相；本文件引用的 #編號皆指此表）
4. Binance Spot REST API（`klines`）與 WebSocket 行情串流官方文件；alternative.me Crypto Fear and Greed Index；Yahoo Finance chart API；CoinGecko Global API
5. FastAPI、Uvicorn、APScheduler、SQLite（WAL 模式、Online Backup API）、React、Vite、TradingView lightweight-charts、Recharts 官方文件
6. Brier（1950）；Gneiting & Raftery（2007）；Kull, Silva Filho & Flach（2017）Beta calibration；Newey & West（1987）；Jegadeesh & Titman（1993）；Moskowitz, Ooi & Pedersen（2012）；Tashman（2000）——見交接手冊第 11 章參考與第 13 章

## 6.2 專有名詞解釋

| 名詞 | 意思 |
|---|---|
| K 棒（K 線） | 一段時間內開高低收與量；本系統只儲存已收盤的 K 棒 |
| 前視偏誤 | 回測用了當下不可能取得的未來資訊使績效虛高；本系統以「隔根開盤成交」避免 |
| 六因子信心分數 | 0–100 綜合分數（RSI、MACD、均線排列、MA200、成交量、布林）；經檢驗無預測力，前台標教學用途 |
| onset 進場 | 訊號首次出現那天才進場，避免同一段行情被重複計數 |
| 樣本外／選參保留 | 未參與設計的資料段；動量策略挑參數時看過檢驗段，其樣本外成績偏樂觀 |
| regime | 市場狀態；動量策略用 BTC 是否高於 100 日均線；研究預測用 MA60＋20 日報酬；宏觀用四驅動因子順逆風 |
| 波動目標 | 依近期波動調整曝險使組合波動貼近目標（動量策略 30%） |
| abstain（拒答） | 預測信心不足、資料過期、方向優勢不足或區間過寬時明確不給結論 |
| append-only | 只可新增不可修改刪除；研究 ledger 以資料庫觸發器強制 |
| 內容定址 | 以輸入資料的 SHA-256 決定紀錄身分；同輸入必得同 id |
| prequential baseline | 對每筆預測只用它之前已成熟的結果建立的基準機率 |
| Brier score／BSS／ECE | 機率預測的誤差平方；相對基準的技巧分數（> 0 才優於基準）；宣稱機率與實際頻率的加權落差 |
| block bootstrap | 保留同日與相鄰日相關性的重抽樣，用來算誠實的信賴區間 |
| HAC t 值 | 對自相關與異質變異穩健的 t 統計量；宏觀主檢定 t=0.72 未達顯著 |
| WAL | SQLite 寫前日誌模式；耐當機、讀寫不互鎖；禁止直接複製執行中的資料庫檔 |
| fail-closed | 安全設定不合格時直接拒絕啟動或拒絕服務，而非降級放行 |
| 看門狗 | 服務崩潰後 30 秒自動重啟的迴圈（Windows 批次檔／launchd KeepAlive） |
| 搬遷包 | 帳密、兩庫一致快照與資料的 zip，用於換機 |

## 6.3 中英對照

| 中文 | English |
|---|---|
| 蠟燭圖／K 線 | candlestick chart |
| 移動平均線 | moving average（MA） |
| 布林通道 | Bollinger Bands |
| 相對強弱指標 | Relative Strength Index（RSI） |
| 指數平滑異同移動平均線 | MACD |
| 平均真實區間／能量潮 | Average True Range（ATR）／On-Balance Volume（OBV） |
| 回測 | backtest |
| 前視偏誤 | look-ahead bias |
| 樣本外 | out-of-sample（OOS） |
| 選擇偏誤 | selection bias |
| 跨幣動量 | cross-sectional momentum |
| 市場狀態過濾 | regime filter |
| 波動目標 | volatility targeting |
| 最大回撤 | maximum drawdown（MDD） |
| 夏普比率 | Sharpe ratio |
| 年化報酬率 | CAGR |
| 拒答 | abstain |
| 內容定址 | content-addressed |
| 不可變帳本 | append-only ledger |
| 觸發器 | trigger |
| 分位數 | quantile |
| 校準 | calibration |
| 逐步向前驗證 | walk-forward validation |
| 發布閘門 | promotion gate／release gate |
| 統計顯著性 | statistical significance |
| 滾動相關 | rolling correlation |
| 等權 | equal-weight |
| 恐懼貪婪指數 | Fear and Greed Index |
| 單一真相來源 | single source of truth |
| 增量抓取 | incremental fetch |
| 資料版本 | data version |
| 排程器 | scheduler |
| 看門狗 | watchdog |
| 限流 | rate limiting |
| 反向代理 | reverse proxy |
| 搬遷包 | migration bundle |
| 開機自啟 | auto-start on boot |
| 排程工作 | scheduled task |

---

*本文件由交接手冊內容重組而成；與程式碼或手冊不一致時，以程式碼與 OpenAPI 為準，並請回報修正本文件。Word 版由 `scripts/build_docs.py` 自 `docs/src/` 產生。*
