# API 規格

> 後端所有 HTTP 端點的參考。共 **48 端點 / 10 個 router**。搭配 [README](../README.md)、[開發指南](開發指南.md)。
> 最後更新：2026-07-08（掃 `backend/routers/*` 產生）

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
| 409 | 衝突 | 同型排程任務還在跑（`ops/run`） |
| 502 | 上游失敗 | 新聞回補時 HackerNews 全數失敗 |

- **快取**：部分端點有記憶體快取（恐懼貪婪 1h、新聞 30 分、macro 15 分、AI 分析 15 分），減少外部請求。

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

> ⚠️ 誠實聲明：此 6 因子分數經檢驗**無 forward edge**，屬教學性質（見 [訊號研究記錄](訊號研究記錄.md)）。

## 5. `backtest` — 回測（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /backtest` | — | 所有幣的預設參數回測（陣列） |
| `GET /backtest/{symbol}` | `stop_loss`(-0.30~-0.01, 預設-0.06)、`take_profit`(0.05~1.0, 預設0.20)、`fee_rate`(0~0.01, 預設0.001)、`slippage_rate`(0~0.02, 預設0.0005) | 即時回測：`{trades, win_rate, total_return, max_drawdown, sharpe, vs_buy_hold, equity_curve...}` |
| `GET /backtest/db/summary` | — | 所有幣**已入庫**績效摘要（依總報酬排序），供跨幣比較 |
| `GET /backtest/db/{symbol}/trades` | `limit`(0–2000, 預設0=全部) | 已入庫逐筆進出場明細 |

> 回測**不前視**：依訊號動作延到隔根開盤成交（見 [開發指南](開發指南.md)）。

## 6. `correlation` — 相關性（🌐）

| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /correlation` | 各幣相關性矩陣 + 年化波動度 | `{symbols:[...], matrix:[[...]], volatility:{...}}` |

## 7. `sentiment` — 市場情緒 / 新聞

| 端點 | 權限 | 參數 | 回應摘要 |
|---|---|---|---|
| `GET /sentiment/fear_greed` | 🌐 | `limit`(預設30) | 恐懼貪婪指數（alternative.me，快取1h） |
| `GET /sentiment/fear_greed/history` | 🌐 | `days`(預設365) | 恐懼貪婪歷史（讀 `fear_greed` 表，可追溯2018） |
| `GET /sentiment/summary` | 🌐 | `symbol`(預設MARKET)、`days`(預設30, 夾1–120) | 每日新聞情緒分數 -100~+100（全市場或單幣） |
| `GET /sentiment/news` | 🌐 | `symbol`(選)、`limit`(預設40) | 最新新聞（分類分組）；即時抓 RSS 並入庫 |
| `GET /sentiment/news/history` | 🌐 | `date`(YYYY-MM-DD, **必填**)、`category`(選) | 指定日期歷史新聞（讀 DB、去重） |
| `GET /sentiment/news/dates` | 🌐 | — | 有資料的日期清單 + 總筆數 |
| `POST /sentiment/news/backfill` | 🔒 | `from_date`、`to_date`(YYYY-MM-DD) | 從 HackerNews 回補歷史新聞；**寫入型端點需登入**。全數失敗回 502 |

## 8. `ai` — AI 分析機器人（🌐）

| 端點 | 參數 | 回應摘要 |
|---|---|---|
| `GET /ai/analysis/{symbol}` | `gpt`(預設1；0=只跑規則引擎)、`force`(預設0；1=略過快取) | 雙引擎分析：`{local:{...}, gpt:{...}, divergence...}`。404=無此幣 |
| `POST /ai/ask` | body `{question(必填,≤500字), symbol?, context_symbol?, history?}` | 提問：`{answer, source(canned/canned+gpt/local/gpt), symbol, name_zh, detected, guessed}`。免選幣自動偵測；未追蹤幣誠實拒答 |
| `GET /ai/config` | — | 前端探測 GPT 是否啟用：`{gpt_enabled, model}`（不洩漏金鑰） |

## 9. `macro` — 宏觀環境（🌐）

| 端點 | 用途 | 回應摘要 |
|---|---|---|
| `GET /macro` | 規則式市場背景（DXY/VIX/美債/標普/黃金/BTC主導/總市值） | `{ok, verdict, verdict_zh, tone, summary_zh, factors:[{key, label_zh, value, impact, impact_zh, note_zh}]}`；免金鑰、快取15分 |

---

## 10. `admin` — 後台管理台（除登入外全 🔒）

**認證流程**：`POST /api/admin/login` 帳密（來自環境變數 `ADMIN_USER`/`ADMIN_PASS`）→ 拿 token → 之後每個 🔒 端點帶 `Authorization: Bearer <token>`（8 小時有效；`ADMIN_SECRET` 換掉會讓所有舊 token 失效）。

### 登入
| 端點 | 權限 | body | 回應 |
|---|---|---|---|
| `POST /admin/login` | 🌐 | `{username, password}` | `{ok, token, user}`；401=帳密錯 |

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
