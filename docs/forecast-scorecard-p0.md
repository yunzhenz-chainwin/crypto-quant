# Forecast Scorecard P0：研究預測成績單規格

> 文件版本：P0 / 2026-07-21
> 適用系統：crypto-quant 研究預測服務
> 性質：外部可閱讀的功能、資料與驗收規格；不是投資建議，也不是報酬承諾。

## 1. 摘要

Forecast Scorecard 的任務不是證明模型「會賺錢」，而是用不可回寫、可重播、完全樣本外的資料回答以下問題：

1. 模型給出的機率是否誠實，例如長期被預測為 70% 的事件是否約有 70% 發生？
2. 模型是否優於當時可取得的簡單基準，而不是只看方向命中率？
3. 模型拒答後是否真的降低錯誤，代價又是多少發布覆蓋率？
4. q10–q90 區間是否有接近標稱 80% 的實際覆蓋率，且寬度是否仍有決策價值？
5. 證據是否足以讓某個 `model_version + horizon_days` 從「研究中」進入人工發布審查？

P0 只建立可信成績單與發布閘門，不修改模型、不自動升級模型，也不把統計預測轉成買賣指令。

## 2. 目標與非目標

### 2.1 P0 目標

- 僅使用已封存的預測快照與之後成熟的結果計分。
- 可依 `model_version`、1／5／10 日 horizon、symbol 與日曆時間窗即時計算，並固定輸出各 horizon 明細。
- 提供 Brier score、Brier Skill Score、log loss、校準表、方向命中率、發布覆蓋率、risk–coverage 與區間評估。
- 對重疊 horizon、同日多幣種相關性與資料修訂採明確、一致的處理規則。
- 對模型相對基準的 paired Brier advantage，以預測日聚合後的 deterministic moving-block bootstrap 提供 95% 信賴區間。
- 樣本不足、資料不完整或來源衝突時 fail closed，回傳「資料不足／不可發布」，不補造數字。
- 產出帶完整 provenance 的 JSON 契約，供後台模型成績頁使用；相同資料與 seed 的分數可重現，只有 `generated_at` 會變動。
- outcome 解析後在同一排程內立即衍生成績摘要，不另寫入或回填不可變 ledger。

### 2.2 P0 非目標

- 不重新訓練、調參或校準現有 forecast model。
- 不建立深度學習、ensemble、HMM 或新的市場 regime 模型。
- 不宣稱 conformal coverage；現有 q10／q90 在 P0 僅接受實證檢驗。
- 不用回測 PnL 取代機率評分，也不以同一測試區間挑選交易成本、信心門檻或策略參數。
- 不因 scorecard 結果自動下單、自動調整部位或提供個人化投資建議。
- 不覆寫既有 snapshot、outcome、model registry 或歷史 scorecard。
- 不把 in-sample 同 regime 歷史比例稱為已驗證的未來準確率。

## 3. 現況實測基線

以下是 2026-07-21 對工作區 `data/app.db` 與本機 API 的唯讀實測；它是 P0 上線後第一個必須能如實重現的狀態快照，而不是長期績效結論。

| 項目 | 實測結果 |
|---|---:|
| `model_registry` | 2 個版本：`historical-baseline-v1`、`historical-baseline-v2`，皆為 `research` |
| legacy `forecast_snapshot` | 90 筆 |
| `forecast_snapshot_v2` | 45 筆 |
| v2 日期範圍 | 只有 `2026-07-20` |
| v2 幣種數 | 15 |
| v2 狀態 | 45 筆全部 `abstain` |
| legacy / v2 outcome | 0 / 0 筆 |
| `GET /api/forecast/BTCUSDT?horizon=5` | HTTP 200；`historical-baseline-v2`；`as_of=2026-07-20`；未過期 |
| BTC 5 日研究值 | 1,845 根可用日線；`p_up=0.515`；q10 = -6.58%；q90 = +7.90%；狀態為 `abstain` |
| 完整 Python 測試 | `62 passed` |
| 前端驗證 | production build 成功；ESLint 0 errors、21 個既有 warnings |

因此現況的唯一正確 scorecard 結論是：

```json
{
  "status": "unverifiable",
  "data_as_of": null,
  "overall": {
    "resolved_count": 0,
    "observations": 0,
    "metrics": null
  }
}
```

在第一批 outcome 成熟前，Brier、命中率、校準誤差與區間覆蓋率都不得顯示為 0；`0` 代表實際量測值，`null` 才代表尚不能估計。

現況測試命令如下：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
Set-Location frontend
npm run lint
npm run build
```

### 3.1 Strict replay 冒煙結果（不是發布證據）

為確認 P0 不只「有程式、沒數字」，另以明確 universe 執行：BTCUSDT、1 日 horizon、issue date `2026-01-01..2026-06-30`、2,000 次 bootstrap、seed `20260721`。來源為目前工作區的修訂後 CSV（SHA-256 `2b851ce2…31d`），因此 `vintage_exact=false`。

| 指標 | 結果 |
|---|---:|
| resolved observations / issue dates | 181 / 181 |
| model Brier / forecast-time baseline Brier | 0.251390 / 0.249862 |
| Brier Skill Score | -0.611% |
| paired Brier advantage | -0.001528 |
| 95% block-bootstrap CI | [-0.004064, 0.000991] |
| ECE | 9.52% |
| q10–q90 coverage / nominal | 85.08% / 80% |
| ready publication coverage | 0%（181 筆皆 abstain） |

這個有限、非 exact-vintage 切片沒有證據顯示目前模型優於簡單 forecast-time baseline；觀測數也未達 1,000 筆 gate。它證明先建可信量測是值得的：下一步不應直接宣稱「提高準確率」，而應先擴大 live outcomes／predeclared replay，再在 untouched 時段比較校準器與 challenger model。

## 4. 名詞與評估單位

| 名詞 | 定義 |
|---|---|
| forecast origin | 快照的 `as_of`；只能使用該日及以前已完成的 UTC 日線 |
| matured outcome | `as_of` 後第 N 根已完成日線已存在，N 等於 `horizon_days` |
| raw probability | 快照當時封存的 `probabilities.up`；不可依結果事後改寫 |
| publication coverage | 可計分預測中 `status=ready` 的比例；與區間 coverage 不同 |
| interval coverage | 實際報酬落在 q10–q90 之間的比例；標稱值為 80% |
| selective risk | 只在通過指定信心閾值的預測上計算的錯誤率 |
| prequential baseline | 對每一筆預測，只用它之前已成熟的 outcome 建立的基準機率 |
| model release | 允許某個模型／horizon 進入人工審查，不代表自動公開或交易 |

模型發布的最小單位是 `(model_version, horizon_days)`。不同 horizon 可分別通過或被阻擋；不得用 1 日表現替 10 日模型背書。

## 5. 來源資料契約

### 5.1 `model_registry`

每個模型版本至少包含：

- `model_version`：不可變主鍵。
- `name`、`status`。
- `research=1`：目前 forecast model 必須明確標記為研究用途。
- `methodology_json`：輸入、regime、估計器、horizon、限制與 point-in-time 聲明。
- `created_at`。

模型方法、特徵、校準器、訓練窗、閾值或輸入處理只要有一項改變，就必須建立新 `model_version`，不能沿用舊版本。

### 5.2 `forecast_snapshot_v2`

P0 的主要計分來源是 v2，不預設混用 legacy 快照。必要欄位如下：

| 欄位 | 約束與用途 |
|---|---|
| `forecast_id` | content-addressed 主鍵 |
| `symbol` | 大寫交易對 |
| `horizon_days` | 只允許 1、5、10 |
| `as_of` | 最後一根被模型使用的已完成 UTC 日線日期 |
| `generated_at` | 實際封存時間，UTC |
| `model_version` | 連到 registry |
| `input_hash` | 正規化輸入的 lowercase SHA-256 |
| `data_version` | `as_of:observations:hash-prefix` |
| `reference_close` | 封存的基準收盤價，必須為正數 |
| `status` | `ready` 或 `abstain` |
| `payload_json` | 完整研究預測契約 |
| `created_at` | 資料庫寫入時間 |

`payload_json` 計分至少會使用：

- `probabilities.up`、`probabilities.down`
- `return_quantiles_pct.q10/q50/q90`
- `downside_risk.threshold_pct`、`downside_risk.probability`
- `regime`
- `confidence.score`、`confidence.level`
- `status`、`abstain_reason`
- `data_quality.stale`、`data_quality.observations`

資料庫已有 no-update、no-delete trigger；P0 不得繞過。

### 5.3 `forecast_outcome_v2`

outcome 只能在 horizon 成熟後 append，不能回寫 snapshot。必要欄位如下：

| 欄位 | 定義 |
|---|---|
| `forecast_id` | 一對一連到 snapshot |
| `target_as_of` | `as_of` 後第 N 根已完成日線日期 |
| `resolved_at` | 寫入結果時間，UTC |
| `realized_return_pct` | `(outcome_close / sealed reference_close - 1) × 100` |
| `actual_direction` | `up`、`down` 或 `flat` |
| `payload_json.outcome_up` | 報酬大於 0 為 1，否則為 0 |
| `payload_json.reference_close` | 必須與 snapshot 封存值一致 |
| `payload_json.model_version/input_hash` | 必須與 snapshot 一致 |

若未到第 N 根完成日線、價格缺口尚未補齊或 snapshot 無有效基準價，維持 pending，不得用日曆日近似、不做內插。

### 5.4 legacy 資料

legacy `forecast_snapshot`／`forecast_outcome` 預設排除於正式 P0 閘門，因其缺少完整 `input_hash` 與 sealed `reference_close` 身分。`include_legacy=true` 只供相容性研究：API 會在同一 diagnostic metrics 中納入 legacy，但 provenance 分列 v2／legacy counts、加入 warning，且 `v2_only_provenance` gate 失敗、`release_eligible=false`；這份混合結果不能成為發布證據。

### 5.5 P0 scorecard 輸出契約

`GET /api/forecast/scorecard` 的實際回應如下。數值無法估計時使用 `null`，不使用 0、空字串或假資料代替；`overall` 與每個 `by_horizon` 元素使用相同 group shape。

```json
{
  "status": "unverifiable",
  "filters": {
    "horizon": 5,
    "model_version": "historical-baseline-v2",
    "symbol": null,
    "window": 365,
    "include_legacy": false
  },
  "provenance": {
    "snapshot_tables": ["forecast_snapshot_v2"],
    "outcome_tables": ["forecast_outcome_v2"],
    "selection_rule": "first_issued_per_symbol_horizon_asof_model_and_schema",
    "baseline": "beta_1_1_expanding_prior_mature_symbol_horizon_outcomes",
    "include_legacy": false,
    "release_eligible": true,
    "snapshots": 0,
    "canonical_snapshots": 0,
    "revisions_excluded": 0,
    "pending": 0,
    "v2_snapshots": 0,
    "legacy_snapshots": 0
  },
  "overall": {
    "status": "unverifiable",
    "resolved_count": 0,
    "observations": 0,
    "unscorable_count": 0,
    "issue_dates": 0,
    "date_range": {"start": null, "end": null},
    "ready_count": 0,
    "coverage": null,
    "metrics": null,
    "intervals": null,
    "brier_advantage_ci": null,
    "promotion_gates": [
      {"gate": "v2_only_provenance", "status": "pass", "actual": true, "required": true},
      {"gate": "all_resolved_scorable", "status": "pass", "actual": 0, "required": 0},
      {"gate": "minimum_observations", "status": "failed", "actual": 0, "required": 1000},
      {"gate": "minimum_issue_dates", "status": "failed", "actual": 0, "required": 180},
      {"gate": "positive_brier_skill", "status": "not_testable", "actual": null, "required": "> 0"},
      {"gate": "brier_advantage_ci", "status": "not_testable", "actual": null, "required": "lower > 0"}
    ]
  },
  "by_horizon": [
    {
      "horizon_days": 5,
      "status": "unverifiable",
      "resolved_count": 0,
      "observations": 0,
      "unscorable_count": 0,
      "issue_dates": 0,
      "date_range": {"start": null, "end": null},
      "ready_count": 0,
      "coverage": null,
      "metrics": null,
      "intervals": null,
      "brier_advantage_ci": null,
      "promotion_gates": [
        {"gate": "v2_only_provenance", "status": "pass", "actual": true, "required": true},
        {"gate": "all_resolved_scorable", "status": "pass", "actual": 0, "required": 0},
        {"gate": "minimum_observations", "status": "failed", "actual": 0, "required": 1000},
        {"gate": "minimum_issue_dates", "status": "failed", "actual": 0, "required": 180},
        {"gate": "positive_brier_skill", "status": "not_testable", "actual": null, "required": "> 0"},
        {"gate": "brier_advantage_ci", "status": "not_testable", "actual": null, "required": "lower > 0"}
      ]
    }
  ],
  "generated_at": "2026-07-21T12:00:00Z",
  "data_as_of": null,
  "warnings": []
}
```

有可評分資料時，`metrics` 會包含 Brier／BSS、log loss、ECE、calibration bins、confidence-threshold selective metrics、`status_metrics.ready|abstain` 與 risk–coverage curve；`intervals` 包含 q10–q90 coverage、width、pinball loss、interval score 與 WIS。`brier_advantage_ci` 使用 `{estimate, lower, upper, confidence_level, block_size, n_resamples, random_seed}`。原始計數與 coverage 必須保留，讓使用者能辨別漂亮百分比是否只來自少量案例。

## 6. Point-in-time 與 replay 方法

### 6.1 線上真實成績

正式成績以實際封存 snapshot 為準，流程如下：

1. 取得 `model_version + horizon_days` 的 v2 snapshots。
2. 同一 `(symbol, horizon_days, as_of, model_version)` 因歷史 K 線修訂而有多個 `input_hash` 時，以 `created_at` 最早的第一個實際發布版本作 canonical record。
3. 其他版本列入 `revisions_excluded`，可供資料品質診斷，但不得重複增加樣本數。
4. 以 `forecast_id` inner join outcome；無 outcome 者計入 pending，不進入已成熟指標。
5. 檢查 snapshot 與 outcome 的 symbol、horizon、model version、input hash、reference close 一致。
6. 使用 snapshot 內的原始機率、分位數、狀態與當時 regime 計分。

若未來加入「同日修訂後確實再次曝光給使用者」的 exposure ledger，才可改以 exposure 為計分單位。在沒有 exposure 證據前，不得把同日所有修訂快照都視為獨立預測。

### 6.2 歷史 replay／回填研究

replay 用於快速累積 pseudo-OOS 研究證據，但必須與線上真實成績分欄呈現：

1. 依日期遞增選取 forecast origin `t`。
2. 每次只傳入 `date <= t` 的完成日線；先排序、日期去重、移除非正價格，再計算輸入 hash。
3. 以該模型版本當時固定的方法產生預測；模型或閾值改變即建立新版本。
4. 對 1／5／10 日分別等待後續第 N 根完成日線結算。
5. 訓練、校準或選門檻只可使用 origin `t` 之前已成熟的結果；不能使用同一 fold 或未成熟 label。
6. replay 寫入隔離的研究 store 或純衍生記錄，不能冒充當時實際送達使用者的 production snapshot。

目前 DB 保存的是最新／修訂後行情，且 `data/raw` 僅有短期保存政策，因此不能聲稱多年 replay 完整重現每一天當時可見的交易所資料 vintage。P0 必須在 replay 結果標記 `vintage_exact=false`；只有未來保存每日原始資料版本後才能改為 true。

### 6.3 決定性要求

在相同 snapshot、outcome、查詢條件、scorecard schema、bootstrap seed 下，JSON 中除 `generated_at` 外的結果必須一致。排序固定為：

1. `as_of`
2. `symbol`
3. `horizon_days`
4. `model_version`
5. `forecast_id`

## 7. 防止資料洩漏與錯誤放大

以下逐項標示本次已落地的防線與 P1 不得違反的 guardrail：

1. **完成 K 線限定**：當天尚未收完的 UTC 日線不可進 snapshot。
2. **時間截斷**：改動 `as_of` 之後的任意價格，原預測結果必須逐位元相同。
3. **基準價封存**：realized return 永遠使用 snapshot 的 `reference_close`，不能回頭讀已修訂的 `as_of` close。
4. **append-only**：snapshot、outcome 與 model registry 禁止 UPDATE／DELETE。
5. **明確版本**：模型版本、來源 table、selection rule、baseline、查詢條件與 replay source hashes 均需入輸出 provenance。
6. **prequential baseline**：Brier Skill 的基準機率只能由該 origin 之前已成熟 outcome 建立。發布閘門不得使用評估區間的事後正例率當基準。
7. **校準資料隔離（P1 guardrail）**：未來的校準器只能在較早時間窗擬合，再到較晚時間窗測試。
8. **門檻隔離（P1 guardrail）**：若未來調整 confidence threshold、最小 coverage 或成本假設，不能在最終測試段挑選。
9. **修訂去重**：同 origin 多個 input hash 預設只算第一個實際發布版本。
10. **相關性保留**：bootstrap 時同日所有 symbol 一起被抽樣，不把高度相關的幣種當成獨立樣本。
11. **重疊 horizon**：本次使用 horizon-aware calendar-date moving blocks；每 N 日取一個 origin 的敏感度檢查列入 P1。
12. **拒答不可隱藏弱模型**：只要 snapshot 有原始機率，就同時計入 all-forecast 成績；另行計算 ready 子集。
13. **缺值不可補造**：機率為 `null` 的不足樣本預測只計狀態與數量，不填成 0.5 後參與模型評分。
14. **多重切片透明**：本次固定輸出 horizon 與 ready/abstain，symbol 可重現查詢；regime 與完整 symbol matrix 列入 P1，屆時不得只展示最佳切片。

## 8. 指標定義

方向命中率只是輔助指標。機率模型的首要指標應使用 proper scoring rules，因為它們會懲罰不誠實的過度自信。[Brier 原始論文](https://journals.ametsoc.org/abstract/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml)與 [Gneiting、Raftery 的 proper scoring rules](https://doi.org/10.1198/016214506000001437)提供理論基礎。

### 8.1 Binary probability

令 `p_i` 為封存的上漲機率，`y_i` 為 `outcome_up`：

**Brier score**，越低越好：

```text
BS = mean((p_i - y_i)^2)
```

**Log loss**，越低越好；計算前只為數值穩定把機率 clip 到 `[1e-15, 1-1e-15]`，不得修改資料庫原值：

```text
LL = -mean(y_i log(p_i) + (1-y_i) log(1-p_i))
```

### 8.2 Prequential baseline 與 skill

主要基準是 expanding prequential positive rate。對每筆 snapshot，只使用相同 `symbol + horizon`、且 `target_as_of <= issue_date` 的較早成熟市場結果；同一市場事件即使被多個模型預測，也只計一次。以 `(up_count + 1) / (resolved_count + 2)` 做 Beta(1,1)／Laplace shrinkage，因此完全沒有歷史結果時自然回到 `p=0.5`。篩選 `model_version` 或時間窗是在建立完整 point-in-time baseline 之後進行，避免查詢條件改寫歷史基準。

若每筆基準機率為 `b_i`：

```text
BSS = 1 - sum((p_i-y_i)^2) / sum((b_i-y_i)^2)
```

`BSS > 0` 才表示優於基準。發布判定使用 paired block bootstrap 的差值，不用兩個互不相關的信賴區間相減。

### 8.3 Calibration

P0 使用 10 個等寬 bins，輸出每 bin 的：

- `count`
- `mean_probability`
- `observed_rate`
- `absolute_gap` 可由前兩欄相減；目前 API 不另存重複欄位

ECE 定義為各 bin gap 依樣本比例加權的平均。ECE 對 bin 選擇與小樣本敏感，只能作輔助門檻，不能單獨證明模型可信；每個 bin 的計數必須一起顯示。[校準指標研究](https://www.jmlr.org/papers/v23/22-0658.html)指出 histogram／kernel 方法必須在解析度與統計信心間取捨。

### 8.4 Direction 與 selective prediction

- 預測方向：`p_i >= 0.5` 為 up，否則為 non-up。
- all-forecast accuracy：由 `p_i >= 0.5` 的方向與 outcome 比較；UI 不把它當主要模型分數。
- ready accuracy：`metrics.status_metrics.ready.accuracy`，只計 snapshot 原始 `status=ready` 的子集。
- `publication_coverage = ready_resolved / scorable_probabilities`。

另有 confidence-policy 診斷：以 `max(p_i, 1-p_i)` 排序，在每個實際出現的 confidence tie 後輸出 coverage、classification risk、selective accuracy 與 Brier；同 confidence 的預測不會被任意拆開。這與 snapshot 的 `ready/abstain` 發布狀態是兩個不同概念，後台明確分開呈現。拒答提升的命中率必須與 coverage 同時報告。[Geifman、El-Yaniv](https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html)

### 8.5 Downside event（後續項目）

每個 horizon 使用 snapshot 當時封存的 downside threshold：

- 1 日：`return <= -3%`
- 5 日：`return <= -7%`
- 10 日：`return <= -10%`

snapshot 已封存 `downside_risk.probability`，但本次 P0 API 尚未輸出 downside 專屬成績；它列入 P1，屆時必須對實際事件分別計算 Brier、log loss 與 BSS，不能以方向上漲模型的成績代替尾部風險成績。

### 8.6 Return interval

現有 q10–q90 的標稱 coverage 為 80%。P0 計算：

- `coverage`：`q10 <= realized_return_pct <= q90` 的比例。
- `mean_width`／`median_width`：`q90 - q10` 的平均與中位數。
- 80% interval score，`alpha=0.2`，越低越好：

```text
IS = (upper-lower)
     + (2/alpha)*(lower-y) if y < lower
     + (2/alpha)*(y-upper) if y > upper
```

只追求 coverage 會得到無限寬、沒有決策價值的區間，因此 coverage、width 與 interval score 必須一起報告。

### 8.7 切片與查詢範圍

本次 P0 固定輸出 1／5／10 日 `by_horizon`，並可用 `symbol`、`model_version` 與 90／365／自訂日曆日 window 查詢。`ready`／`abstain` 以 `status_metrics` 同時輸出，不依結果挑選。

regime 與一次輸出所有 symbol 的固定切片尚未納入 API；這些是 P1 項目。在此之前，單一 symbol 可用 query 分開檢視，但不得事後只展示最好看的幣種。任何範圍未達 1,000 筆有效預測或 180 個 issue dates，都只能是 `insufficient_evidence`。

## 9. 相依樣本與信賴區間

加密貨幣同日高度相關，5／10 日 forward return 又因每日起點而重疊。把每筆 row 當獨立 Bernoulli 會使信賴區間過窄。

P0 對 paired Brier advantage 採 calendar-date circular moving-block bootstrap：

- 抽樣單位保留同一 `as_of` 的全部 symbols。
- block 長度為 `max(7, 2 × horizon_days)` 個日曆日。
- API 使用 2,000 次重抽樣與固定 seed `20260721`；CLI 預設 1,000 次、seed 0，均可由參數覆寫。
- 若可用 issue dates 少於要求的 block，計算時縮短到可用日期數並在結果回傳實際 `block_size`。
- 同日先保留 row count 作權重，再以連續日期 block 重抽；因此 CI 的 estimate 與 headline 的逐 row Brier advantage 是同一估計量。
- 本次只對 `baseline Brier - model Brier` 輸出 percentile 95% CI；其他比例不宣稱已有 CI。

non-overlapping sensitivity、其他指標的 cluster CI 與自相關驅動 block 選擇列入 P1。現有 block 長度是保守操作值，不是市場永遠不變的統計常數。

## 10. API 與排程操作

### 10.1 現行可用介面

| 操作 | 介面 | 說明 |
|---|---|---|
| 取得單幣研究預測 | `GET /api/forecast/{symbol}?horizon=1|5|10` | 使用完成 UTC 日線；快取未命中時會封存 immutable snapshot |
| 查看 forecast 成績單 | `GET /api/forecast/scorecard` | 需後台登入；純讀取 v2 ledger 並即時計分，不新增 snapshot/outcome |
| 執行每日資料管線 | `POST /api/admin/ops/run/daily` | 需後台登入；背景執行行情、指標、入庫、forecast 與 outcome 解析 |
| 查看工作紀錄 | `GET /api/admin/jobs` | 需後台登入；目前回傳最近 50 筆 |
| 直接執行 forecast pipeline | `.\.venv\Scripts\python.exe -c "from backend.scheduler import run_forecast_pipeline; print(run_forecast_pipeline())"` | 維運用；會封存今日預測並解析已成熟 outcome |

每日排程為 Asia/Taipei 09:00，即 UTC 日線收盤後一小時。`run_pipeline()` 在行情新鮮度檢查後呼叫 `run_forecast_pipeline()`；它先封存 snapshot、解析成熟 outcome，再即時計算 scorecard 摘要。scorecard 計算失敗會記在該摘要中，但不回寫或丟棄已完成的 snapshot/outcome。

### 10.2 已實作 scorecard API

`GET /api/forecast/scorecard` 需要 `Authorization: Bearer <admin-token>`。query：

- `model_version`：選填；後台目前明確傳入 `historical-baseline-v2`。
- `horizon`：1、5、10，選填；後台預設 5。
- `symbol`：選填，省略代表全體。
- `window`：正整數日曆日；省略代表全部，後台提供 90／365／全部。
- `include_legacy`：預設 false；正式 release gate 強制 false。

未登入或 token 無效回 HTTP 401；未知 horizon 回 422。合法但沒有成熟 outcome、或 model filter 沒有資料時回 HTTP 200 + `status=unverifiable`，不把「沒有資料」當 0 分。

沒有同時明確指定單一 `model_version + horizon` 時，overall 只屬 aggregate diagnostic view，`single_model_horizon_scope=not_applicable`，不得拿它作升級依據。指定單一 model、但查看全部 horizon 時，可逐一閱讀 `by_horizon[].promotion_gates`，不能用跨 horizon overall 掩蓋弱項。

排程順序：

```text
daily market data completed
  -> seal today's snapshots
  -> resolve every matured pending outcome
  -> derive current model scorecard summary on demand
  -> attach summary to forecast_pipeline job result
  -> never mutate snapshot/outcome
```

scorecard 不另建可被誤認為真相的 cache table。同一 ledger 與參數重算時，除 `generated_at` 外的數值與 gate 結果必須一致。

### 10.3 已實作 strict replay CLI

```powershell
.\.venv\Scripts\python.exe -m src.forecast_replay `
  --symbols BTCUSDT,ETHUSDT `
  --horizons 1,5,10 `
  --start-date 2025-01-01 `
  --end-date 2026-06-30 `
  --bootstrap-samples 2000 `
  --seed 20260721 `
  --output reports/forecast_replay.json
```

正式研究報告應明確傳 `--symbols`，不要依「今天啟用中的幣」決定歷史 universe。完整 JSON 會記錄 `vintage_exact=false`、universe source、模型版本、maturity rule、參數與每個來源 CSV 的 SHA-256。這能讓研究可追蹤，但不能消除目前 CSV 已經過修訂、缺少歷史資料 vintage 與可能的 survivorship bias；因此 replay 是 pseudo-OOS 研究證據，不能冒充當時真正送達使用者的 live forecast。

## 11. 模型發布門檻

以下是 API 已實作的 P0 gate。它們只在明確的 `(model_version, horizon_days)` 上有意義，不決定買賣，也不自動取代 champion；門檻是初始操作 guardrails，不是文獻保證的宇宙常數。

| Gate | P0 要求 | 失敗結果 |
|---|---|---|
| Scope | 必須明確指定單一 model version 與 horizon | aggregate 只供診斷，`not_applicable` |
| Provenance | 預設只用 v2；`include_legacy=true` 必定失敗 | legacy 可研究，不可當發布證據 |
| Sample | 至少 1,000 筆 scorable observations | `failed`，top-level 至多 `insufficient_evidence` |
| Independent dates | 至少 180 個不同 issue dates | `failed`，top-level 至多 `insufficient_evidence` |
| Point skill | Brier Skill Score > 0 | `failed` 或樣本不足時 `not_testable` |
| Uncertainty | paired Brier advantage 95% CI lower > 0 | `failed`／`not_testable` |

top-level 證據狀態：

```text
unverifiable         沒有可評分的成熟預測
insufficient_evidence 有成熟預測，但未達 1,000 筆或 180 個 issue dates
evaluated             已達證據量門檻；仍需逐 gate 判斷，不等於已通過或可發布
```

`provenance.release_eligible=true` 只表示沒有混入 legacy，絕不等於模型通過。即使所有已實作 gate 都通過，也只能進入人工審查；實際升級仍需要：

1. 人工確認資料來源、模型版本與限制。
2. 確認沒有在測試段挑門檻或模型。
3. 與既有 champion 做同期間 paired 比較。
4. 保留回退版本與書面批准紀錄。

log-loss delta CI、校準 bin gate、ready coverage/value、區間 coverage CI、non-overlap sensitivity、regime/symbol stability 與完整資料品質 gate 尚未自動化，列入 P1。後台已顯示這些可觀察指標，但不得把「顯示了」誤寫成「已通過發布門檻」。

## 12. 限制

- 目前沒有成熟 outcome，任何準確度值都尚不可估。
- 方向正確不代表報酬為正；P0 不評估部位大小、槓桿與個人風險承受度。
- Brier 與 log loss 衡量機率品質，但不等同扣除手續費與滑價後的經濟價值。
- ECE 依 bin 與樣本量改變，只能作診斷。
- q10／q90 是歷史經驗分位數，P0 的實測 coverage 不構成 distribution-free 保證。
- block bootstrap 只能減輕已知時間／跨幣相依造成的過度自信，不能消除所有 regime shift。
- aggregate calibration 可能掩蓋特定 symbol 或 bear regime 失效；P0 可逐 symbol 查詢，P1 必須補上固定 regime/symbol matrix。
- 歷史 replay 使用現有資料版本，不一定等於當時交易所實際可見 vintage。
- 多次模型與切片比較會增加 data snooping 風險；P0 不允許挑最好看的切片發布。

## 13. 故障處理

| 故障 | P0 行為 | 禁止行為 |
|---|---|---|
| 0 筆成熟 outcome | HTTP 200 + `unverifiable` + null metrics | 顯示 0% 錯誤或 100% 準確 |
| snapshot 尚未成熟 | 保持 pending | 用日曆日或現價提前結算 |
| outcome 找不到 snapshot | 外鍵拒絕寫入；scorecard 不建立 orphan | 關閉外鍵後硬塞資料 |
| 同 origin 多個修訂 | 先依 `created_at + SQLite rowid` 保留實際第一筆；其餘列 revision count | 挑事後表現較好或已先成熟的版本 |
| 機率、日期或 outcome 不可評分 | 增加 `unscorable_count`，`all_resolved_scorable` gate 失敗 | clip／補值後假裝原始資料正確 |
| q10 > q50 或 q50 > q90 | 該筆不進 interval metrics | 交換上下界掩蓋錯誤 |
| scorecard GET 發生 DB 錯誤 | request 失敗；GET 本身不寫 ledger | 用空白成功物件掩蓋故障 |
| 排程中的 scorecard 計算失敗 | 摘要標 `failed`，已封存 snapshot/outcome 與核心行情流程保留 | 回寫或刪除研究歷史 |
| issue dates 少於 block 長度 | 將實際 block 縮到可用日期數；樣本 gate 仍失敗 | 假裝已有 180 個獨立日期 |

所有錯誤 log 應包含 job ID、model version、horizon、資料截止日與受影響 forecast IDs；不得記錄管理員密碼或 token。

## 14. P0 驗收清單

### 14.1 資料與 replay

- [x] 同一輸入、版本與 seed 重跑，分數與 bootstrap CI 一致。
- [x] 在 `as_of` 後加入未來價格，既有 forecast ID、hash、機率、區間、狀態與 baseline 不變。
- [x] replay 與 production `generate_forecast()` 的 scoring fields 對照一致。
- [x] DB helper 與 SQLite trigger 拒絕 snapshot／outcome UPDATE、DELETE（既有測試持續通過）。
- [x] 同 origin 的第二個 input hash 不增加 canonical sample count；原版未成熟時也不能用新版取代。
- [x] 同秒寫入的修訂以 SQLite rowid 保留實際第一筆。
- [x] pending 只在第 N 根完成日線存在時成熟。
- [x] 預設只讀 v2；明確混入 legacy 時 provenance gate 失敗。
- [x] replay 輸出資料檔 hash、universe source 與 `vintage_exact=false`。

### 14.2 指標

- [x] perfect probabilities 的 Brier／log loss 為 0。
- [x] BSS 與逐筆 prequential baseline 公式一致，不偷用完整測試集正例率。
- [x] probability 1.0 正確落入最後 calibration bin。
- [x] confidence risk–coverage 不拆 confidence ties，且 ready status 指標分開計算。
- [x] q10／q90 邊界值視為 covered；pinball、interval score 與 WIS 有公式測試。
- [x] block bootstrap 保留同日群組，固定 seed 可重現，CI estimate 與 row-weighted headline 一致。
- [x] 0 outcome 回 null metrics，不產生 NaN／Infinity。

### 14.3 API 與排程

- [x] scorecard GET 需要有效 admin token，且前後 ledger row counts 不變。
- [x] 不支援的 horizon 回 422；未知 model／合法空結果回 200 + `unverifiable`。
- [x] 未指定單一 model+horizon 時，aggregate promotion gate 為 `not_applicable`。
- [x] 每日 outcome 解析完成後才計算 scorecard 摘要。
- [x] scorecard 計算失敗不阻斷或回寫已完成的 forecast pipeline。
- [x] 目前資料庫實測回 `resolved_count=0`、`status=unverifiable`、`metrics=null`。
- [x] 最終 commit 前驗證：Python 62 passed、ESLint 0 errors、Vite production build 成功。

### 14.4 發布與呈現

- [x] 後台同時顯示 resolved count、ready coverage 與 ready accuracy。
- [x] BSS 清楚標示 forecast-time expanding baseline。
- [x] 空樣本 formatter 顯示 `—`，不把 JavaScript `null` 轉成 0。
- [x] 區間同時顯示 coverage、平均 width 與 WIS。
- [x] gate 使用後端實際 `gate` key；aggregate view 不冒充正式升級門檻。
- [x] 介面只描述「可進入人工審查」，不使用「保證準確」或交易績效宣稱。

## 15. P1／P2 路線

### P1：校準、區間與線上監控

1. 以 chronological validation 為每個 horizon 比較 logistic／Platt 與 beta calibration；小樣本不使用高自由度 isotonic。Beta calibration 的 identity mapping 與小樣本風險可參考[原始 AISTATS 論文](https://proceedings.mlr.press/v54/kull17a.html)。
2. 增加 calibration intercept／slope、equal-mass reliability diagram 與 rolling Brier／log loss。
3. 用真正 OOS residual 建立時間序列適用的區間；先比較 rolling conformal、[Adaptive Conformal Inference](https://papers.neurips.cc/paper_files/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html)與 [EnbPI](https://proceedings.mlr.press/v139/xu21h.html)。
4. 若加入 quantile model，以 [Conformalized Quantile Regression](https://proceedings.neurips.cc/paper_files/paper/2019/hash/5103c3584b063c431bd1268e9b5e76fb-Abstract.html)改善異質波動下的區間效率。
5. 對校準殘差、Brier 與 interval misses 加 rolling drift monitor；ADWIN 的原始方法見 [Bifet、Gavaldà](https://epubs.siam.org/doi/10.1137/1.9781611972771.42)。警報先觸發擴大拒答／回退，不直接自動重訓上線。

### P2：模型組合與決策價值

1. 建立誤差來源不同的 champion／challenger models，所有 component 先產生真正 OOS probability。
2. ensemble 從等權平均開始；有限樣本下複雜權重常受估計誤差影響。預測組合可追溯至 [Bates、Granger](https://www.tandfonline.com/doi/abs/10.1057/jors.1969.103)。
3. ensemble probability 完成後重新做獨立校準，不能假設多個已校準模型平均後仍然校準。
4. 加入階層式 symbol／regime shrinkage，避免稀少 regime 直接退回全歷史或被 30 筆樣本主導。
5. 將方向機率升級為完整／多分位報酬分布，使用預先聲明的手續費、滑價、損失容忍與 expected utility 評估人類決策價值。
6. 只有在 untouched 時間段、paired block-bootstrap 與固定成本壓力測試都優於 champion 時，才允許人工升級。

## 16. 主要一手文獻

- Glenn W. Brier, 1950, [Verification of Forecasts Expressed in Terms of Probability](https://journals.ametsoc.org/abstract/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml)
- Tilmann Gneiting、Adrian E. Raftery, 2007, [Strictly Proper Scoring Rules, Prediction, and Estimation](https://doi.org/10.1198/016214506000001437)
- Leonard J. Tashman, 2000, [Out-of-sample tests of forecasting accuracy: an analysis and review](https://www.sciencedirect.com/science/article/abs/pii/S0169207000000650)
- Meelis Kull、Telmo Silva Filho、Peter Flach, 2017, [Beta calibration](https://proceedings.mlr.press/v54/kull17a.html)
- Yonatan Geifman、Ran El-Yaniv, 2017, [Selective Classification for Deep Neural Networks](https://papers.neurips.cc/paper_files/paper/2017/hash/4a8423d5e91fda00bb7e46540e2b0cf1-Abstract.html)
- Isaac Gibbs、Emmanuel Candès, 2021, [Adaptive Conformal Inference Under Distribution Shift](https://papers.neurips.cc/paper_files/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html)
- Yaniv Romano、Evan Patterson、Emmanuel Candès, 2019, [Conformalized Quantile Regression](https://proceedings.neurips.cc/paper_files/paper/2019/hash/5103c3584b063c431bd1268e9b5e76fb-Abstract.html)
- Chen Xu、Yao Xie, 2021, [Conformal Prediction Interval for Dynamic Time-Series](https://proceedings.mlr.press/v139/xu21h.html)
- Albert Bifet、Ricard Gavaldà, 2007, [Learning from Time-Changing Data with Adaptive Windowing](https://epubs.siam.org/doi/10.1137/1.9781611972771.42)
- J. M. Bates、C. W. J. Granger, 1969, [The Combination of Forecasts](https://www.tandfonline.com/doi/abs/10.1057/jors.1969.103)
