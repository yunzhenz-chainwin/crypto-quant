# API 規格與資料庫說明

> 本檔含兩部：**第一部 API 規格**（後端所有 HTTP 端點的參考）、**第二部 資料庫說明**。
> 搭配 [README](../../README.md)、[部署與運維](部署與運維.md)（開發指南見其**第二部**）。
> 最後更新：2026-09-01

---

## 通則

- **Base path**：所有端點都掛在 `/api` 之下（`main.py` 以 `prefix="/api"` 掛載）。例：`GET /api/prices/BTCUSDT`。
- **權限**：🌐 公開（免驗證）／🔒 需後台 token。🔒 端點要帶標頭 `Authorization: Bearer <token>`，token 由 `POST /api/admin/login` 取得（HMAC 簽章、有效 8 小時）。
- **幣種代號**：path 上的 `{symbol}` 大小寫皆可（後端自動轉大寫）；多數接受 `BTC` 或 `BTCUSDT`。
- **共用查詢參數**：`days`（往回天數）、`start`/`end`（`YYYY-MM-DD`）、`interval`（`1d` 預設 / `1h`；僅 BTC、ETH 有 1h）。
- **錯誤格式**：FastAPI 標準 `{"detail": "訊息"}`，搭配 HTTP 狀態碼：

| 碼 | 意思 | 常見情境 |
|---|---|---|
| 400 | 參數錯誤 | `interval` 不支援、問題超長、幣種代號空 |
| 401 | 未登入 / 逾時 | 🔒 端點沒帶 token 或 token 過期 |
| 404 | 找不到 | 幣種無資料、未知資料表 / job |
| 409 | 衝突 | 同型排程任務還在跑（`ops/run`）；預測快照併發寫入衝突（`forecast/{symbol}`，回「預測快照寫入衝突」） |
| 422 | 參數驗證失敗 | forecast 的 `horizon` 只接受 1/5/10（scorecard 與單幣快照皆是）；scorecard 篩選組合不合法（ValueError 一律轉 422） |
| 429 | 請求過多 | 超過端點限流（回應一律含 `Retry-After`）；各端點額度見下方「限流一覽」 |
| 502 | 上游失敗 | 新聞回補時 HackerNews 全數失敗或發生非預期例外 |

- **限流一覽**（皆為每 client 計算，超限回 429＋`Retry-After`）：

| 端點 | 限流 |
|---|---|
| `POST /admin/login` | 嘗試 5 次/60 秒；另計**連續失敗 5 次鎖 15 分**（鎖定期間直接回 429） |
| `GET /ai/analysis/{symbol}` | `force=1`：3 次/分・30 次/日；`gpt=1`：20 次/分・300 次/日；`gpt=0`：60 次/分・1000 次/日 |
| `POST /ai/ask` | 10 次/分・120 次/日 |
| `POST /sentiment/news/backfill` | 2 次/時・10 次/日 |
| `GET /forecast/scorecard` | 12 次/60 秒 |
| `GET /forecast/{symbol}` | 30 次/60 秒 |
| `GET /backtest/{symbol}`（單幣詳細回測） | 12 次/60 秒 |
| `POST /admin/ingest` | 3 次/時 |
| `POST /admin/ops/run/{job}` | 每類 job 各 6 次/時 |
| `POST /admin/coins`（新增幣種） | 5 次/時 |
| `POST /admin/ai/test` | 5 次/10 分 |

- **快取**：部分端點有記憶體快取（恐懼貪婪 1h、新聞 30 分、macro 15 分、AI 分析 15 分、`/forecast/ledger-status` 600 秒），減少外部請求與重算。

---

## 1. `meta` — 中繼 / 心跳（🌐 全公開）

| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /symbols` | 啟用中的幣種清單 | `["BTCUSDT", ...]` |
| `GET /intervals` | 各週期有資料的幣種 | `{"1d":[...], "1h":["BTCUSDT","ETHUSDT"]}` |
| `GET /status` | **前端自動更新心跳** | `{last_updated, verification:{ok,passed,total}, data_version}`；前端每 60 秒輪詢 `data_version`，變了才重拉 |
| `GET /verify` | 指標交叉驗證完整結果（供前台信任徽章彈窗） | `{ok, passed, total, coins:[{symbol, ok, max_err}]}` |

## 2. `prices` — K 線（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /prices/{symbol}` | `days`(1–1825, 預設180)、`start`、`end`、`interval`(預設1d) | OHLCV 陣列 `[{ts, open, high, low, close, volume}]`。400=interval 不支援；404=該幣無此週期資料 |

## 3. `indicators` — 技術指標（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /indicators/{symbol}` | 同 `prices`（`days`/`start`/`end`/`interval`） | `[{ts, close, ma20, ma60, ma200, rsi, macd, signal, hist, bb_upper, bb_lower, vol_ma20}]` |

## 4. `signals` — 6 因子訊號（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /signals` | — | 所有幣的當前訊號陣列 |
| `GET /signals/{symbol}` | — | 單幣訊號：`{symbol, signal(BULL/BEAR/NEUTRAL), score, factors...}` |
| `GET /signals/{symbol}/history` | `days`(7–1825, 預設360)、`start`、`end` | 信心分數歷史走勢（讀 `daily_signal`）`[{date, signal, score, close, rsi}]` |

> ⚠️ 誠實聲明：此 6 因子分數經檢驗**無 forward edge**，屬教學性質（見 [成果匯報](成果匯報.md) 第二部「訊號研究記錄」）。

## 5. `backtest` — 回測（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /backtest` | — | 所有幣**已入庫績效摘要**（`/backtest/db/summary` 的有界別名） |
| `GET /backtest/{symbol}` | `stop_loss`(-0.30~-0.01，每次0.01)、`take_profit`(0.05~1.0，每次0.01)、`fee_rate`(0~0.01，每次0.0001)、`slippage_rate`(0~0.02，每次0.0001) | 單幣即時詳細回測：`{metrics, recent_trades, equity_curve, validation, parameter_sweep...}` |
| `GET /backtest/db/summary` | — | 所有幣**已入庫**績效摘要（依總報酬排序），供跨幣比較 |
| `GET /backtest/db/{symbol}/trades` | `limit`(0–2000, 預設0=全部) | 已入庫逐筆進出場明細 |

> 回測**不前視**：依訊號動作延到隔根開盤成交（見 [部署與運維](部署與運維.md) 第二部「開發指南」）。

> **2026-07-21 相容性註記：** `/backtest` 舊版會同步冷算所有幣的完整物件，已因公開端點資源耗盡風險停止。需要完整資料的 client 請逐幣呼叫 `/backtest/{symbol}`；跨幣列表請使用摘要 shape。單幣結果採 64 組 LRU，圖表最多傳 600 個等距點加極值，但所有績效與風險指標仍使用完整每日曲線計算。

### 5.1 `forecast` — 研究預測（🌐／🔒）

| 端點 | 權限 | 參數 | 回應摘要 |
|---|---|---|---|
| `GET /forecast/ledger-status` | 🌐 | — | 研究預測 ledger 的**累積狀態**（唯讀、只有彙總數字，不含任何單筆預測內容），供前台「統一判斷摘要」第②格：`{ok, ...ledger_status() 各欄}`（數字由 `src/forecast_diagnose.py` 計算，畫面與診斷同一組數）。快取 600 秒；計算失敗且無舊快取時回 `{ok:false, error:"累積狀態暫時無法取得"}` |
| `GET /forecast/scorecard` | 🔒 | `horizon`（1/5/10，選）、`model_version`、`symbol`、`window`（正整數日）、`include_legacy`（預設 false） | v2 不可變 ledger 的 point-in-time 成績單：provenance、樣本數、Brier/BSS、log loss、ECE、F1/Recall/MCC/ROC-AUC/AP、ready coverage/accuracy、risk–coverage、區間/WIS、block-bootstrap CI 與 promotion gates |
| `GET /forecast/{symbol}` | 🌐 | `horizon`（1、5、10，預設5） | 不可變研究快照：漲跌機率、q10/q50/q90、下行風險、regime、confidence、證據、拒答原因、`input_hash`、`data_version`、`reference_close` |

> 預測只使用已完成 UTC 日線；低信心、資料過期或樣本不足時回傳 `status=abstain`。同一 `as_of` 若歷史資料被修訂，會依 SHA-256 輸入雜湊另存新快照，不覆寫舊預測。此功能為研究基準，不是投資建議或報酬承諾。

> Scorecard 靜態路由位於 `{symbol}` 動態路由之前，且只供後台使用。未登入回 401；無成熟 outcome 回 HTTP 200 + `status=unverifiable`、`metrics=null`。正式 promotion gate 必須明確指定單一 `model_version + horizon`，且不得帶 symbol/window 篩選；aggregate 與 filtered view 只供診斷。完整資料契約與方法見 [研究預測評估](研究預測評估.md)（Forecast Scorecard P0）。

## 6. `correlation` — 相關性（🌐）

| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /correlation` | 各幣相關性矩陣 + 年化波動度 | `{symbols:[...], matrix:[[...]], volatility:{...}}` |

## 7. `sentiment` — 市場情緒 / 新聞

| 端點 | 權限 | 參數 | 回應摘要 |
|---|---|---|---|
| `GET /sentiment/fear_greed` | 🌐 | `limit`(預設30, **夾 1–100**) | 恐懼貪婪指數（alternative.me，快取1h）；外部 API 失敗時先回舊快取，沒有才退回讀 DB 的 `fear_greed` 表 |
| `GET /sentiment/fear_greed/history` | 🌐 | `days`(預設365) | 恐懼貪婪歷史（讀 `fear_greed` 表，可追溯2018） |
| `GET /sentiment/summary` | 🌐 | `symbol`(預設MARKET)、`days`(預設30, 夾1–120) | 每日新聞情緒分數 -100~+100（全市場或單幣） |
| `GET /sentiment/news` | 🌐 | `symbol`(選)、`limit`(預設40) | 最新新聞；即時抓 RSS 並入庫。回 `{categories, total, symbol, coin_total, fell_back_to_market}`：`total`=本次實際回傳則數、`coin_total`=標記到該幣的則數；有給 `symbol` 時每則附 `about_this_coin` 旗標。**`fell_back_to_market=true` 表示該幣相關新聞不足 5 則，這頁顯示的是全市場新聞**（相關的排最前面，靠 `about_this_coin` 分辨）。例外時回 200＋`{categories:[], total:0, ..., error:"新聞暫時無法取得，請稍後再試"}` |
| `GET /sentiment/news/history` | 🌐 | `date`(YYYY-MM-DD, **必填**)、`category`(選) | 指定日期歷史新聞（讀 DB、去重） |
| `GET /sentiment/news/dates` | 🌐 | — | 有資料的日期清單 + 總筆數 |
| `GET /sentiment/sources` | 🌐 | — | 新聞實際來源分布（前端「資料來源」標示）：`{rss:[直接訂閱的 9 家], aggregator, aggregator_prefix:"GN:", total, domains, aggregated, top:[{domain, count, via_aggregator}]}`（後四欄查 DB 實況，非寫死清單） |
| `POST /sentiment/news/backfill` | 🔒 | `from_date`、`to_date`(YYYY-MM-DD，**query 參數**非 body) | 從 HackerNews 回補歷史新聞；**寫入型端點需登入**。限流 2 次/時・10 次/日；全數失敗回 502，**非預期例外也回 502**（不假性成功） |

## 8. `ai` — AI 分析機器人（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /ai/analysis/{symbol}` | `gpt`(預設1；0=只跑規則引擎)、`force`(預設0；1=略過快取) | 雙引擎分析：`{local:{...}, gpt:{...}, divergence...}`。404=無此幣 |
| `POST /ai/ask` | body `{question(必填,≤500字), symbol?, context_symbol?, history?}` | 提問：`{answer, source(canned/canned+gpt/local/gpt), symbol, name_zh, detected, guessed}`；命中固定問答庫時另附 `intent`（意圖分類），問到未追蹤幣時誠實拒答並附 `unsupported`（該幣名）。免選幣自動偵測；**全站模式**（聊天室沒綁幣、問題也沒提到幣）回 `symbol`/`name_zh` = `null`，打招呼／反問幣種等罐頭回覆 `source="canned"` |
| `GET /ai/config` | — | 前端探測 GPT 是否啟用：`{gpt_enabled, model}`（不洩漏金鑰） |

## 9. `macro` — 宏觀環境（🌐）

| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /macro` | 規則式市場背景（DXY/VIX/美債/標普/黃金/BTC主導/總市值，另附 **N225（日經225）/KOSPI/JPY（美元兌日圓）** 三個亞股對照因子——一律 NEUTRAL、只顯示不計入判讀） | `{ok, as_of, verdict, verdict_zh, tone, net, n_drivers, summary_zh, note_zh, factors:[{key, label_zh, value, impact, impact_zh, note_zh, group}], groups, evidence, linkage, sources}`；`group` 供前台把「判讀依據／加密自身／背景對照」分區；`evidence`=歷史預測力檢定、`linkage`=BTC 與各宏觀序列的 60 日滾動相關。免金鑰、快取15分 |
| `GET /macro/history` | 逐日宏觀環境標籤時間軸（與面板同一套規則重算，供看環境變化與自行核對） | `days`(預設365, 夾30–2500)；回 `{ok, points:[{date, verdict, net}], counts, days, labels_zh}`；資料不足或失敗回 `{ok:false, error, points:[]}` |

---

## 10. `admin` — 後台管理台（除登入外全 🔒）

**認證流程**：`POST /api/admin/login` 帳密（來自環境變數 `ADMIN_USER`/`ADMIN_PASS`）→ 拿 token → 之後每個 🔒 端點帶 `Authorization: Bearer <token>`（8 小時有效；`ADMIN_SECRET` 換掉會讓所有舊 token 失效）。

### 登入
| 端點 | 權限 | body | 回應 |
|---|---|---|---|
| `POST /admin/login` | 🌐 | `{username, password}` | `{ok, token, user}`；401=帳密錯；每 client 5 次/60 秒，超限 429 |

### 監控
| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /admin/health` | 系統健康 / 資料新鮮度 | `{server_time, symbols_total, symbols_fresh, coins:[{symbol, last_date, lag_days, stale}], last_pipeline, last_news_fetch}` |
| `GET /admin/db/stats` | 兩個 DB 統計 | `{news:{total, categories, top_sources...}, app:{job_runs, daily_signal, tasks...}, market}` |
| `GET /admin/jobs` | 最近 50 筆操作 / 排程紀錄 | `{jobs:[{job_type, status, started_at, finished_at, message}]}` |

### 工作項目（進度追蹤，`tasks` 表）
| 端點 | 用途 | 參數 / body |
|---|---|---|
| `GET /admin/tasks` | 列出所有工作項目 | — |
| `POST /admin/tasks` | 新增（未給分類/預計日會自動估） | `{title(必), detail?, notes?, status?, phase?, planned_date?}` |
| `PUT /admin/tasks/{task_id}` | 更新（只改有給的欄位） | `{title?, detail?, notes?, status?, phase?, planned_date?, done_date?, sort_order?}` |
| `DELETE /admin/tasks/{task_id}` | 刪除 | — |

### 操作觸發
| 端點 | 用途 | 備註 |
|---|---|---|
| `POST /admin/ingest` | 手動把最新 K 線/指標匯入 DB | 同步執行 |
| `POST /admin/ops/run/{job}` | 背景觸發管線，`job` ∈ `daily`/`hourly`/`news` | 409=同型任務還在跑（防並發打 Binance 429） |

### 幣種管理（即時生效，不需重啟）
| 端點 | 用途 | 參數 / body |
|---|---|---|
| `GET /admin/coins` | 幣種清單 + 資料狀態 | 回 `{coins:[{symbol, zh, ticker, enabled, rows, last_date, lag_days, stale}], enabled}` |
| `POST /admin/coins` | 新增幣（會實際抓 Binance 資料） | `{symbol(必), zh?, ticker?}`；抓不到回 400 |
| `PUT /admin/coins/{symbol}` | 改中文名/代號/啟用停用 | `{zh?, ticker?, enabled?}` |
| `DELETE /admin/coins/{symbol}` | 從清單移除（**歷史資料仍留 DB**） | — |

### 資料庫檢視（唯讀、白名單防注入）
| 端點 | 用途 | 參數 |
|---|---|---|
| `GET /admin/db/tables` | 可瀏覽的資料表清單 + 筆數 | 白名單 11 表（prices/indicators/daily_signal/backtest_*/fear_greed/tasks/app_config/job_runs/access_log/news） |
| `GET /admin/db/table/{name}` | 瀏覽某表資料列 | `symbol?`、`interval?`、`limit`(預設50, 最多500)、`offset`(預設0)；404=表不在白名單 |

### AI 設定
| 端點 | 用途 | 備註 |
|---|---|---|
| `GET /admin/ai/config` | GPT 設定（金鑰只回**遮罩**） | `{has_key, key_masked, model, base_url, source(env/db), env_locked}` |
| `PUT /admin/ai/config` | 設定金鑰/模型/base_url | `{api_key?, model?, base_url?}`（api_key 給空字串=清除）；環境變數優先，`env_locked` 時後台改不動 |
| `POST /admin/ai/test` | 測試 GPT 連線 | 回連線結果 |
| `GET /admin/ai/stats` | GPT 用量（今日/近7日呼叫、token）+ 對話/快取筆數 | — |

### 研究 / 策略（即時檢驗）
| 端點 | 用途 | 備註 |
|---|---|---|
| `GET /admin/verify/indicators` | 指標交叉驗證 | `interval`(1d/1h)；與前台 `/status` 共用快取 |
| `GET /admin/signal/scorecard` | 訊號成績單（有無 forward edge） | 快取鍵含 `scoring.py` mtime，改訊號後自動重算 |
| `GET /admin/strategy` | 防禦型跨幣動量「正式策略」今日建議 + 績效 | 來源 `src/momentum_signal.cached_strategy()` |

---

# 第二部：資料庫說明（原獨立文件，2026-09-01 併入）

> 給開發/交接/主管說明用。涵蓋:用哪個 DB、每張表的結構與用途、資料怎麼進來、
> 多週期設計、穩定性與容量。
> 以表結構為準;各表「目前 N 列」為快照,會持續成長。

---

## 一、用哪個資料庫?為什麼?

採用 **SQLite**(Python 內建 `sqlite3`,免安裝、單一檔案)。共兩個資料庫檔:

| 檔案 | 用途 | 大小 |
|---|---|---|
| `data/app.db` | 加密數值 + 系統/後台資料 | ~39.5 MB(實測 2026-09-01) |
| `data/news.db` | 新聞 | ~10.6 MB(實測 2026-09-01) |

> 大小為快照值,兩個檔都會隨時間持續成長(行情/新聞/預測 ledger 每天累積)。

**為什麼選 SQLite**
- 零設定、跟著專案檔案走,部署簡單。
- 支援 **ACID 交易**(寫入要嘛全成功、要嘛回復),斷電/當機有日誌保護。
- 這個資料量(萬~百萬列)綽綽有餘。
- 全世界部署最廣的 DB 引擎(手機/瀏覽器/OS 內建),穩定性經過大量驗證。
- 用標準 SQL,將來若要多人高併發再平滑遷移 PostgreSQL。

**兩層資料架構**
```
抓取/計算階段 → 檔案層(CSV)：data/clean/*.csv、reports/indicators_*.csv
                     │ ingest 匯入
                     ▼
查閱/分析階段 → 資料庫層(SQLite)：app.db / news.db ← 中央儲存,未來新資料也進這裡
```
> 前後台主要查閱 API 已讀 SQLite;CSV 仍保留為抓取/計算中繼、備援與重建來源。

---

## 二、`app.db` 十九張表

### 1. `prices` — K 線(行情)
```sql
prices(
  symbol TEXT, interval TEXT DEFAULT '1d', ts TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, interval, ts)        -- 幣+週期+時間 唯一
)
```
- **用途**:存每根 K 線的開高低收量。
- **多週期**:`interval` 區分 1d / 1h…;`ts` 是完整時間戳(日線為 `00:00:00`)。
- **填入**:`ingest_market_data(interval)` 從 `data/clean/*_<interval>.csv` 匯入(`INSERT OR REPLACE`,重跑只會覆蓋不重複)。
- **目前**:63,119 列(含 1d 啟用幣與 BTC/ETH 1h;快照 2026-07-13)。

### 2. `indicators` — 技術指標
```sql
indicators(
  symbol TEXT, interval TEXT DEFAULT '1d', ts TEXT,
  close, ma20, ma60, ma200, rsi, macd, signal, hist,
  bb_upper, bb_lower, vol_ma20,             -- 皆 REAL
  PRIMARY KEY (symbol, interval, ts)
)
```
- **用途**:存每根 K 線算出的 MA/RSI/MACD/布林/均量。
- **填入**:同 `ingest_market_data`,來源 `reports/indicators_*_<interval>.csv`。
- **目前**:63,119 列(快照 2026-07-13)。

### 3. `daily_signal` — 每日訊號快照(歷史)
```sql
daily_signal(
  date TEXT, symbol TEXT, signal TEXT, score INTEGER,
  close REAL, rsi REAL, PRIMARY KEY (date, symbol)
)
```
- **用途**:逐日逐幣的「信心分數 + 多空」歷史 → 前台可畫**信心分數走勢**。
- **填入**:`backfill_daily_signals()` 用全部歷史指標經 `src/scoring.score_row()` 重算。
- **目前**:27,539 列(快照 2026-07-13)。

### 4. `fear_greed` — 恐懼貪婪指數(歷史)
```sql
fear_greed(date TEXT PRIMARY KEY, value INTEGER, label TEXT)
```
- **用途**:自有的恐懼貪婪歷史,不必每次跟外部 API 還原。
- **填入**:`fetch_fear_greed_history()` 從 alternative.me 抓(可追溯 2018)。
- **目前**:3,081 列。

### 5. `tasks` — 工作項目 / 進度追蹤
```sql
tasks(
  id PK, title, detail, notes,              -- notes=備註/交接說明
  status,        -- planned / in_progress / done
  phase,         -- 分類(前台/後台/資料庫/訊號回測/資料抓取/修復優化/其他)
  planned_date, done_date, sort_order, created_at, updated_at
)
```
- **用途**:後台記錄做了什麼、預計做什麼、何時做、交接備註。
- **填入**:後台 `/admin` →「工作項目」CRUD;首次啟動植入專案預設進度。
- **目前**:137 列;狀態快照為 done 113、in_progress 2、planned 22。

### 6. `app_config` — 集中設定
```sql
app_config(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)
```
- **用途**:集中設定,目前存 `coins`(幣種清單,單一真相來源)。排程/抓取都讀它;`ai` 與 `hourly_symbols` 可存在但目前未設定。
- **目前**:1 列(`coins`)。

### 7. `job_runs` — 操作/排程紀錄
```sql
job_runs(id PK, job_type, status, started_at, finished_at, message)
```
- **用途**:每次排程/手動操作的成功失敗與時間 → 後台「監控」頁顯示。
- **填入**:`start_job()` / `finish_job()`(排程、`/admin/ingest` 等會寫)。

### 8. `access_log` — 使用紀錄
```sql
access_log(id PK, ts, path, symbol, status_code, latency_ms)
```
- **用途**:API 請求紀錄,供未來「使用分析」頁(造訪量/熱門幣)。只記路徑與幣種,不記個資。
- **填入**:`backend/main.py` 的 `access_log_middleware` 已啟用,只記 `/api/*`。
- **目前**:5,755 列;後台「使用分析」圖表仍待補。

### 9. `ai_analysis` — AI 分析快取
```sql
ai_analysis(cache_key PK, symbol, generated_at, json)
```
- **用途**:AI 雙引擎分析結果的持久化快取(重啟不失效)。
- **填入**:`/api/ai/analysis` 產生分析時寫入;`cleanup_ai()` 清過期。

### 10. `ai_chat` — AI 對話紀錄
```sql
ai_chat(id PK, ts, symbol, question, answer, source, model)   -- source = gpt/local/error
```
- **用途**:小Q 問答歷史,保留 90 天。
- **填入**:`/api/ai/ask` 每次問答;`cleanup_ai()` 清 90 天前。

### 11. `ai_usage` — GPT 用量
```sql
ai_usage(id PK, ts, kind, model, prompt_tokens, completion_tokens, ok, error)  -- kind = analysis/ask/test
```
- **用途**:GPT token 用量與成敗,後台「AI 設定」頁統計。

### 12. `backtest_trade` — 回測逐筆進出場
```sql
backtest_trade(symbol, interval, entry_date, exit_date, entry_price, exit_price,
               entry_trigger_price, exit_trigger_price,
               return_pct, gross_return_pct, cost_pct, hold_days, …)
```
- **用途**:每次回測的逐筆交易明細,前台/後台可直接查 DB(`/api/backtest/db/{symbol}/trades`)。
- **填入**:每日排程 `backfill_backtests()`,與 `/api/backtest` 同一套計算(避免靜態報表漂移)。

### 13. `backtest_summary` — 回測整體績效
```sql
backtest_summary(symbol, interval, total_trades, win_rate, total_return_pct, cagr_pct,
                 max_drawdown_pct, sharpe_ratio, avg_hold_days, profit_factor,
                 avg_win_pct, avg_loss_pct, …)
```
- **用途**:各幣回測績效摘要,供 `/api/backtest/db/summary` 跨幣比較。
- **填入**:同 `backfill_backtests()`。

### 14. `macro_daily` — 宏觀市場日資料
```sql
macro_daily(date TEXT PRIMARY KEY, dxy REAL, vix REAL, us10y REAL, spx REAL, gold REAL)
```
- **用途**:美元指數/VIX/美債10Y/標普/黃金的每日收盤。即時面板只看得到「現在」,有這張表宏觀規則才能逐日重建與驗證(`src/macro_eval.py`)。只存原始值不存判讀,改規則不必重抓。
- **填入**:`fetch_macro_history()` 從 Yahoo Finance 抓(逐欄 upsert,單一序列失敗不影響其他);每日排程回補近 1 年並重跑預測力檢定。
- **目前**:2,535 列(快照 2026-09-01)。

### 15. `model_registry` — 預測模型註冊
```sql
model_registry(model_version PK, name, status,
               research INTEGER CHECK (research = 1),   -- 強制只能是研究性質
               methodology_json, created_at)
```
- **用途**:研究預測的模型版本與方法論登記,`forecast_snapshot*` 以外鍵指向它。
- **目前**:2 列。

### 16./17. `forecast_snapshot` / `forecast_outcome` — 研究預測 ledger(舊版 v1)
```sql
forecast_snapshot(forecast_id PK, symbol, horizon_days CHECK IN (1,5,10),
                  as_of, generated_at, model_version, status, payload_json, created_at,
                  UNIQUE (symbol, horizon_days, as_of, model_version))
forecast_outcome(forecast_id PK, target_as_of, resolved_at,
                 realized_return_pct, actual_direction, payload_json, created_at)
```
- **用途**:v1 的不可變預測快照與到期結果。遷移到 v2 時**刻意原封保留**,歷史研究紀錄不重寫。
- **目前**:各 90 列(已凍結,不再新增)。

### 18./19. `forecast_snapshot_v2` / `forecast_outcome_v2` — 研究預測 ledger(現行)
```sql
forecast_snapshot_v2(forecast_id PK, symbol, horizon_days CHECK IN (1,5,10),
                     as_of, generated_at, model_version,
                     input_hash, data_version, reference_close,   -- v2 新增:輸入雜湊入唯一鍵
                     status, payload_json, created_at,
                     UNIQUE (symbol, horizon_days, as_of, model_version, input_hash))
forecast_outcome_v2(forecast_id PK, target_as_of, resolved_at,
                    realized_return_pct, actual_direction, payload_json, created_at)
```
- **用途**:現行預測快照(含 SHA-256 輸入雜湊)與到期結算;`/api/forecast/*` 與 scorecard 都讀這兩張。
- **填入**:每日排程 `run_forecast_pipeline()`(封存當日快照、結算到期 outcome);前台 `/api/forecast/{symbol}` 快照未存在時也會寫入。
- **目前**:snapshot 1,578 列、outcome 1,338 列(快照 2026-09-01)。

> ⚠️ **append-only(不可改不可刪)**:建表時對 `model_registry` 與四張 forecast 表都掛了
> `BEFORE UPDATE` / `BEFORE DELETE` 觸發器,任何 UPDATE/DELETE 直接 ABORT——
> 不可變是資料庫層的性質,不只是 Python 端的約定。歷史資料被修訂時只會依新的
> `input_hash` 另存新快照,舊預測永遠留底。

---

## 三、`news.db` 兩張表

### 1. `news` — 新聞
```sql
news(
  id PK, url TEXT UNIQUE,                   -- URL 唯一,防重複
  title, domain, category, sentiment,
  published_at,   -- 文章發布日(歷史查詢用這欄)
  fetched_at,     -- 系統存入時間
  coins TEXT,     -- 幣種標記(逗號分隔 ticker,如 "BTC,ETH";整字比對算出,是 coin 過濾的唯一依據)
  summary TEXT    -- RSS 摘要純文字(2026-08-12 加入,納入幣種比對;不參與情緒判讀)
)
索引:idx_published、idx_category、idx_fetched
```
- **填入**:排程每 30 分鐘抓 9 家 RSS(CoinTelegraph/CoinDesk/Decrypt/TheBlock/CryptoSlate/Blockworks/BitcoinMagazine/動區BlockTempo/鏈新聞ABMedia)＋Google News 中文聚合(市場級進 30 分排程;幣種級逐幣查詢走每日排程)——**非早期文件寫的 3 家**;後台可從 HackerNews 回補歷史。
- **目前**:4,481 列(快照 2026-07-13)。

### 2. `news_sentiment_daily` — 每日情緒分數
```sql
news_sentiment_daily(date, symbol, score, n_total, n_bull, n_bear, top_json, updated_at)
```
- **用途**:每日×每幣(或 `MARKET`)新聞情緒分數 -100~+100,供前台情緒溫度條與 AI 引用。`symbol`='MARKET'(全市場)或幣種 ticker(BTC/ETH…)。
- **填入**:`aggregate_daily()`(30 分排程滾動更新今日;幣種級新聞每日回補)。
- **目前**:513 列(快照 2026-07-13)。

---

## 四、資料怎麼進到資料庫(資料流)

```
Binance API ──fetch_binance.py──► data/clean/*.csv (OHLCV)
                                       │ indicators.py
                                       ▼
                               reports/indicators_*.csv
                                       │ ingest_market_data()
                                       ▼
                         app.db: prices / indicators
src/scoring ─backfill_daily_signals()─► app.db: daily_signal
alternative.me ─fetch_fear_greed_history()─► app.db: fear_greed
Yahoo Finance ─fetch_macro_history()───────► app.db: macro_daily(每日回補)
run_forecast_pipeline() ───────────────────► app.db: forecast_snapshot_v2 / forecast_outcome_v2(每日)
RSS(9家) / Google News / HackerNews ───────► news.db: news
後台操作 ──────────────────────────────────► app.db: tasks / job_runs
```

**每日 09:00 排程(`scheduler.run_pipeline`；2026-07-06 起，日線 UTC 收盤後 1 小時)自動做**:抓 K 線 → 算指標 → 入庫 `prices`/`indicators` → 重算 `daily_signal` → 重產回測入庫(`backtest_trade`/`backtest_summary`) → 封存研究預測(`run_forecast_pipeline()`:寫 `forecast_snapshot_v2`、結算到期 `forecast_outcome_v2`,記成獨立的 `forecast_pipeline` job) → 更新 `fear_greed` → 回補 `macro_daily` 並重跑宏觀預測力檢定 → 幣種級新聞+情緒彙總,並把這次執行記進 `job_runs`。(舊版的「算相關性」步驟已移除:只產 PNG 熱圖無人用,`/api/correlation` 由 `reader` 直接讀 DB 計算。)

**其他排程**:每小時 :06 的 hourly pipeline 抓 BTC/ETH 的 1h K 線、算指標並入庫 `prices`/`indicators`(interval='1h');每 30 分鐘抓一次新聞;**每日 03:30 `run_sqlite_backup` 對兩個 DB 做 SQLite online backup**(細節見「六、穩定性與資料安全」)。

---

## 五、多週期設計(1d / 1h 如何並存)

主鍵是 **`(symbol, interval, ts)`**:
- `interval`:`'1d'`、`'1h'`…
- `ts`:完整時間戳。日線存到天(`2026-06-17 00:00:00`),小時線存到小時(`2026-06-17 14:00:00`)。

因此同一天的 24 根小時線**不會互相覆蓋**,且 1d 與 1h 可同時存在同一張表,用 `interval` 篩選即可。
> 加 1h 只需:`fetch_binance`/`indicators` 的週期參數化 → 產生 `*_1h.csv` → `ingest_market_data("1h")`。

---

## 六、穩定性與資料安全

| 機制 | 說明 |
|---|---|
| **ACID 交易** | 每次寫入原子性,斷電不會壞半筆 |
| **WAL 模式** | 已開啟(`journal_mode=wal`):更耐當機、讀寫不互相阻塞 |
| **可重建** | `prices`/`indicators`/`daily_signal` 都能從 CSV 或 Binance 重新產生,**遺失不等於永久遺失** |
| **單寫入者** | SQLite 同時一個寫入者;本專案只有排程+少量後台寫,完全足夠 |
| **自動備份** | 每日 03:30 排程以 **SQLite online backup API** 備份兩個 DB(`backend/services/sqlite_backup.py`):快照先寫暫存檔、`PRAGMA quick_check` 驗證通過才原子發布到 `data/backups/sqlite/`,每庫保留 14 份(環境變數 `SQLITE_BACKUP_DIR`/`SQLITE_BACKUP_KEEP` 可覆蓋)。**WAL 模式下禁止直接複製線上 `.db` 檔**——會漏掉還在 `-wal` 檔裡的已提交資料。搬遷換機請用 `scripts/make_migration_bundle.py` 打包 |

「不可重建」的有:`tasks`(工作項目)、`news`(部分)、以及**全部 forecast ledger**(`forecast_snapshot`/`forecast_outcome` 與 v2——append-only 的 point-in-time 紀錄,重跑只會生成新 `input_hash` 的新快照,舊紀錄無法重算)。這幾張是交接時**最不能誤刪**的資料。

---

## 七、容量評估

| 週期 | 每年新增列 | 5 年大小 | 評估 |
|---|---|---|---|
| **日線 1d(現在)** | ~1.1 萬 | ~17 MB | ✅ 十幾年都不用擔心 |
| 小時線 1h | ~26 萬 | ~210 MB | ✅ SQLite 仍輕鬆 |
| 分鐘線 1m | ~1,600 萬 | ~12 GB | ⚠️ 該換 PostgreSQL |

---

## 八、怎麼查看 / 探索

- **後台**:`/admin` →「監控」頁的「資料庫」區會顯示各表筆數、行情日期範圍。
  注意:後台資料庫檢視只開放 **11 張白名單表**(prices/indicators/daily_signal/backtest_trade/backtest_summary/fear_greed/tasks/app_config/job_runs/access_log/news);`macro_daily` 與 forecast/model 各表**不在後台檢視範圍**(查了回 404),要看它們得直接開 SQLite(如下)。
- **直接查詢**(任何 SQLite 工具或指令):
```sql
-- 某幣最近的訊號分數
SELECT date, signal, score FROM daily_signal
WHERE symbol='BTCUSDT' ORDER BY date DESC LIMIT 10;

-- 各週期的行情筆數
SELECT interval, COUNT(*) FROM prices GROUP BY interval;

-- 恐懼貪婪近一週
SELECT date, value, label FROM fear_greed ORDER BY date DESC LIMIT 7;
```
