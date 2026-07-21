# 預測機率校準研究報告

評估日期：2026-07-21；原始模型：`historical-baseline-v2`；校準器版本：`monotone-platt-beta-v1`。

狀態：**研究 challenger；不可上線；production 未變更**

## 1. 結論先行

本階段已完成 leakage-safe 的 Platt 與 Beta 機率校準實驗，但六個正式比較（3 個 horizon × 2 個方法）全部判定為 `keep_identity`。沒有自動選 winner，也沒有修改 production model、路由、門檻或 `MODEL_VERSION`。

在 69,877 筆可校準的 paired walk-forward 樣本上，Platt 與 Beta 都改善了 raw probability 的 Brier、log loss 與 10-bin equal-width ECE；但是這個改善**不能解讀成預測方向更準**：

- pooled ROC-AUC 由 `0.509037` 降至約 `0.49302`；
- AP 由 `0.479344` 降至約 `0.4704`；
- 以 `p(up) >= 0.5` 判定上漲時，Recall 由 `0.364464` 幾乎歸零；
- F1 由 `0.416146` 降至 Platt `0.001796`、Beta `0.003167`；
- 所有 horizon 的 paired Brier improvement 95% block-bootstrap CI 都跨過 0；
- 5 日與 10 日 challenger 對 forecast-time baseline 的 BSS 為負；
- 資料不是 exact historical vintage，且尚未完成決策門檻／政策影響驗證。

因此目前正確決策是：**保留 identity/raw probability，校準器僅保留為研究產物。**

## 2. 評估範圍與樣本

| 項目 | 值 |
|---|---:|
| Replay records | 73,881 |
| 成功套用校準器 | 69,877（94.5805%） |
| Warmup 時保留 raw probability | 4,004 |
| 因無效輸入而 abstain | 0 |
| Model version | `historical-baseline-v2` |
| Horizons | 1、5、10 日 |
| Symbols | 15 |
| Issue date | 2021-10-30 至 2026-07-19 |
| Target date | 2021-10-31 至 2026-07-20 |
| 最新可用 training cutoff | 2026-07-18 |

15 個 symbols 為：`ADAUSDT, ATOMUSDT, AVAXUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, DOTUSDT, ETHUSDT, LINKUSDT, LTCUSDT, NEARUSDT, POLUSDT, SOLUSDT, UNIUSDT, XRPUSDT`。

指標表只比較同一批 `fit_status == calibrated` 的 paired observations；warmup 的 4,004 筆不混入 challenger 成績，也沒有事後按表現篩資料。

| Horizon | 全部 records | Paired calibrated | Warmup fallback | Paired issue dates | 第一個 calibrated issue date |
|---:|---:|---:|---:|---:|---|
| 1 日 | 24,692 | 23,418 | 1,274 | 1,633 | 2022-01-29 |
| 5 日 | 24,632 | 23,302 | 1,330 | 1,625 | 2022-02-02 |
| 10 日 | 24,557 | 23,157 | 1,400 | 1,615 | 2022-02-07 |

## 3. 校準方法

### 3.1 Identity

Identity 是控制組，不改變原始模型機率：

```text
g_identity(p) = p
```

### 3.2 Monotone Platt scaling

```text
z = log(p / (1 - p))
g_platt(p) = sigmoid(a * z + b),  a >= 0
```

`a >= 0` 保證同一個 issue-date batch 內映射不會顛倒排序。Identity prior 為 `a=1, b=0`。

### 3.3 Monotone Beta calibration

```text
g_beta(p) = sigmoid(alpha * log(p) - beta * log(1 - p) + c)
alpha >= 0, beta >= 0
```

Identity prior 為 `alpha=1, beta=1, c=0`。Platt 與 Beta 都先把 `p` clip 到 `[1e-6, 1-1e-6]`，再用 NumPy IRLS/Newton 最佳化；L2 固定為 `1.0`，沒有在本次 test replay 上調參。Warm start 只把前一個 issue date 的參數當作同一完整目標函數的初始值，不會刪除舊資料或改變統計目標。

## 4. Strict walk-forward：如何避免未來資料洩漏

對目前 issue date `t`，校準訓練資料必須滿足：

```text
target_date < t
```

這裡刻意使用嚴格小於，而不是 `<=`。同一天所有 symbols 的預測先以同一份 fit 轉換；target 恰好在當天才成熟的 outcome，不會進入當天 fit，只能從下一個 issue date 開始使用。

隔離與 pooling 規則如下：

- fit key 是 `(model_version, horizon_days)`；不同 model version、1／5／10 日 horizon 絕不共用 fit；
- 同一 key 內跨 symbols pooling，以增加有效樣本；
- 同 issue date 的 fit 會 cache，一整批 symbols 使用完全相同參數；
- 輸入順序先 canonicalize，結果不依賴原始 record order；
- 原始機率、Platt、Beta 都以相同 outcome 與相同 paired rows 比較；
- 每個 `forecast_id` 與 `(model, symbol, horizon, issue_date)` 只能有一筆 first-issued
  row；重複 ID 或 revision 會 fail closed，不能灌大 warmup／promotion 樣本；
- 本次 run 使用開始前選定的預設參數，沒有依結果自動挑 winner；但模組無法
  證明呼叫端是否事前登錄設定，因此 artifact 會標示
  `caller_supplied_externally_unverified`，正式 gate 仍要求外部 protocol 證據。

跨 symbol pooling 雖能降低小樣本變異，但會假設不同幣種可共享校準映射；這是之後必須做 cohort／regime sensitivity 的建模假設，不是已證明的事實。

## 5. Warmup 與 fail-safe 行為

一個 `(model, horizon)` 必須同時具備下列資料量才 fit：

- 至少 180 筆 matured outcomes；
- 至少 90 個不同 calibration issue dates；
- 正、負 outcome 各至少 30 筆。

條件不足或 optimizer fit 失敗時，challenger 會 `fallback_raw`，即輸出原始 `p`；無效 probability、issue date、horizon 或缺少明確 model version 才會 abstain。本次沒有 invalid-input abstention，也沒有把 warmup 樣本偽裝成「已校準」。

本次 4,004 筆 fallback 的主要限制是 `calibration_issue_dates < 90`；分 horizon 為 1 日 1,274 筆、5 日 1,330 筆、10 日 1,400 筆。

## 6. Raw vs Platt vs Beta：實際結果

### 6.1 全部 horizon pooled（僅描述性）

以下三列使用完全相同的 69,877 筆 outcomes。ECE 是從 v2 artifact 的逐筆 records 以目前 evaluator 重算的 10-bin **equal-width** ECE；v2 snapshot 的 comparison serializer 尚未直接保存該值。

| 方法 | Brier ↓ | Log loss ↓ | ECE ↓ | ROC-AUC ↑ | AP ↑ | F1 @0.5 ↑ | Recall @0.5 ↑ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Raw / Identity | 0.252097 | 0.697751 | 0.032438 | 0.509037 | 0.479344 | 0.416146 | 0.364464 |
| Platt | 0.250821 | 0.694863 | 0.010666 | 0.493021 | 0.470363 | 0.001796 | 0.000901 |
| Beta | 0.250822 | 0.694866 | 0.010777 | 0.493027 | 0.470590 | 0.003167 | 0.001593 |

這個 pooled 表不能作為正式 promotion gate，因為正式 gate 必須一次只比較一個 model version 與一個 horizon。它仍清楚揭示決策風險：校準把大多數機率壓到 0.5 以下，proper scores 改善，但固定 0.5 門檻的 up prediction 幾乎消失。

每個 issue-date mapping 都是 monotone，只保證**同一天內** ranking 不反轉；不同日期使用不同 mapping，因此把所有日期混在一起計算的 pooled AUC 仍可能改變。本次 AUC 的明顯下降就是必須額外設 gate 的理由。

### 6.2 各 horizon paired 指標

| Horizon | 方法 | N | Brier ↓ | Log loss ↓ | ECE ↓ | ROC-AUC ↑ | AP ↑ | F1 @0.5 ↑ | Recall @0.5 ↑ |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Raw | 23,418 | 0.250667 | 0.694497 | 0.020339 | 0.502879 | 0.491772 | 0.474077 | 0.458311 |
| 1 | Platt | 23,418 | 0.250106 | 0.693360 | 0.003039 | 0.481109 | 0.469303 | 0.005182 | 0.002622 |
| 1 | Beta | 23,418 | 0.250107 | 0.693361 | 0.003045 | 0.481599 | 0.470076 | 0.009113 | 0.004632 |
| 5 | Raw | 23,302 | 0.251919 | 0.697202 | 0.030558 | 0.507701 | 0.476885 | 0.410388 | 0.353553 |
| 5 | Platt | 23,302 | 0.250696 | 0.694571 | 0.008802 | 0.470426 | 0.447067 | 0.000000 | 0.000000 |
| 5 | Beta | 23,302 | 0.250699 | 0.694578 | 0.008794 | 0.470272 | 0.446400 | 0.000000 | 0.000000 |
| 10 | Raw | 23,157 | 0.253721 | 0.701595 | 0.046564 | 0.503668 | 0.465090 | 0.347653 | 0.276009 |
| 10 | Platt | 23,157 | 0.251670 | 0.696677 | 0.023112 | 0.457781 | 0.423580 | 0.000000 | 0.000000 |
| 10 | Beta | 23,157 | 0.251670 | 0.696677 | 0.023112 | 0.457781 | 0.423580 | 0.000000 | 0.000000 |

需要注意 ECE 對分箱方式敏感。上表固定 equal-width bins，結果改善；同一份逐筆資料若用現行「不切開相同 probability ties」的 10 個 equal-mass reliability bins，把各 bin 的 absolute gap 加權，pooled raw 約 `0.034404`、Platt `0.035085`、Beta `0.035162`，沒有改善。這種診斷不一致不能被隱藏，也表示不能只看單一 ECE 數字決定上線。

## 7. Forecast-time baseline、BSS 與不確定性

完整 73,881 筆 raw replay 的基準結果已固定於 [crypto-quant 文件合集](crypto-quant_文件合集.docx)第陸章「預測模型指標與參考門檻」：

- Raw Brier：`0.252671`
- Forecast-time baseline Brier：`0.251558`
- Raw BSS：`-0.4424%`
- baseline loss − raw loss 的 95% moving-block bootstrap CI：`[-0.003007, 0.000843]`

也就是原始模型尚未證明勝過 forecast-time baseline。

下表改用各 horizon 的 calibrated paired subset，BSS 定義為 `1 - BS_challenger / BS_forecast_time_baseline`。CI 的 estimand 是「每個 issue date 先平均，再對日期等權重」的 reference Brier advantage；因此 CI point estimate 與逐列加權的 Brier 差可能有微小不同。

| Horizon | 方法 | Challenger BSS vs baseline | Identity − challenger Brier 95% CI | Baseline − challenger Brier 95% CI | Block |
|---:|---|---:|---:|---:|---:|
| 1 | Platt | +0.0412% | [-0.000012, 0.001104] | [-0.000291, 0.000501] | 7 |
| 1 | Beta | +0.0410% | [-0.000007, 0.001106] | [-0.000291, 0.000500] | 7 |
| 5 | Platt | -0.0630% | [-0.000238, 0.002722] | [-0.002450, 0.001941] | 10 |
| 5 | Beta | -0.0644% | [-0.000242, 0.002718] | [-0.002454, 0.001940] | 10 |
| 10 | Platt | -0.2738% | [-0.000530, 0.005130] | [-0.005838, 0.004179] | 20 |
| 10 | Beta | -0.2738% | [-0.000530, 0.005130] | [-0.005838, 0.004179] | 20 |

Bootstrap 使用 issue-date clustered circular moving blocks、1,000 resamples、95% CI、seed 0；block size 採 `max(7, 2*horizon)`。所有 Brier advantage CI 都跨過 0，所以「Brier point estimate 較好」仍不是足夠證據。

Log-loss 的 identity − challenger CI：

- 1 日 Platt `[0.000044, 0.002195]`、Beta `[0.000046, 0.002193]`；
- 5 日 Platt `[-0.000091, 0.005587]`、Beta `[-0.000095, 0.005576]`；
- 10 日兩者約 `[-0.000097, 0.010449]`。

只有 1 日的 log-loss CI 完整高於 0；5 日與 10 日仍跨 0。

## 8. Promotion gate：六組全部 `keep_identity`

Fail-closed gate 要求：所有 paired rows 都有有效日期、明確 symbol、唯一 forecast ID／
forecast unit，以及明確且唯一的 model+horizon；至少 1,000 筆／180 個日期／正負類各 100 筆、predeclared
evaluation protocol、exact historical vintage、決策政策影響已確認、Brier 改善及其
CI 下界大於 0、log loss non-inferior、對 forecast-time baseline 有正 BSS 且 CI
下界大於 0，以及 pooled ROC-AUC 下降不超過 `0.002`。formal v1 固定使用 95% CI、
1,000 次 bootstrap、seed 0 與 `max(7, 2*horizon)` block；不可換 seed、resample
數或放大 block 挑選有利區間，設定另有 `gate_policy_sha256` 可供稽核。

本次資料量、單一 group、point Brier 與 point log loss checks 都通過；但 protocol
沒有由獨立 registry／untouched test 登錄機制驗證，因此
`evaluation_protocol_confirmed=false`。其他失敗 checks 如下：

| Horizon | 方法 | Gate decision | 所有失敗原因 |
|---:|---|---|---|
| 1 | Platt | `keep_identity` | protocol 未外部確認；非 exact vintage；未確認 decision-policy impact；Brier improvement CI 跨 0；對 baseline 的 Brier CI 跨 0；AUC degradation 超過 0.002 |
| 1 | Beta | `keep_identity` | protocol 未外部確認；非 exact vintage；未確認 decision-policy impact；Brier improvement CI 跨 0；對 baseline 的 Brier CI 跨 0；AUC degradation 超過 0.002 |
| 5 | Platt | `keep_identity` | 上述六項，加上 log-loss non-inferiority CI 跨 0、BSS vs baseline 非正 |
| 5 | Beta | `keep_identity` | 上述六項，加上 log-loss non-inferiority CI 跨 0、BSS vs baseline 非正 |
| 10 | Platt | `keep_identity` | 上述六項，加上 log-loss non-inferiority CI 跨 0、BSS vs baseline 非正 |
| 10 | Beta | `keep_identity` | 上述六項，加上 log-loss non-inferiority CI 跨 0、BSS vs baseline 非正 |

即使未來某次全部 checks 通過，函式也只會回傳 `eligible_for_manual_review`，不會自動部署。

## 9. SHAP 為何仍是 N/A

SHAP 不是 F1、AUC 或 Brier 這類效能指標，而是針對 `f(X)` 的 feature attribution。現行 `historical-baseline-v2` 是 regime-conditioned empirical baseline，沒有固定的 ML feature matrix、可解釋的 feature schema 與對應 model object；校準器的輸入也只有一個 scalar raw probability。因此：

- SHAP 應標示 `N/A`，不能填 0，也不能偽造 feature importance；
- Platt/Beta 能解釋的是 raw→calibrated mapping、參數、training cutoff 與 reliability，不是原始市場因子的貢獻；
- 機率校準不會自動補上 source model 的 SHAP；
- 等未來建立有固定 `X -> f(X)` 的 challenger model，再於 frozen OOS set 產出 SHAP stability／directionality 報告。

現階段較誠實的替代證據是 audit trace、regime/cohort sensitivity、raw-to-calibrated curve、calibration parameters、risk-coverage 與 leave-one-time-block-out sensitivity。

## 10. Provenance 與可重現性

### 10.1 固定 artifact

| Artifact | 值 |
|---|---|
| Calibration report v2 SHA-256 | `e63ed429c5eebaa993ea8f26998320d806e1f40cb29a5dc7c9b44dd090fd9a50` |
| Canonical input records SHA-256 | `dc80514ecf41308e4a4b4c1bb50a9d741b987033be10348895ececbcbd20fb75` |
| Replay input file SHA-256 | `05541ec2cb861afb19c02c79374c02de5d44c560e9a3f32e5919047f67f69e82` |
| Source CSV manifest SHA-256 | `9315c60b65772ed5ae495a5442ead39df06f14b5b329e7bc8d77baaf7338d000` |
| Calibration report v2 size | 172,806,445 bytes（172.81 MB／164.80 MiB） |

來源 CSV 的 aggregate manifest SHA-256 已列在 [crypto-quant 文件合集](crypto-quant_文件合集.docx)第陸章；每個檔案的 row count 與 SHA-256 保留於本次 machine-readable replay artifact。Report hash 固定的是本次 snapshot；若 evaluator schema 或 serializer 增加欄位，即使逐筆預測相同，輸出檔 hash 仍會不同。現行程式另輸出由 calibrator family、canonical input hash 與完整設定 hash 組成的 `artifact_id`／`configuration_sha256`；所以用本 commit 重跑時，完整 report file hash 預期會因新增欄位而不同，不能拿上表舊 serializer hash硬比。

### 10.2 重跑 replay

```powershell
.venv\Scripts\python.exe -m src.forecast_replay `
  --symbols ADAUSDT,ATOMUSDT,AVAXUSDT,BNBUSDT,BTCUSDT,DOGEUSDT,DOTUSDT,ETHUSDT,LINKUSDT,LTCUSDT,NEARUSDT,POLUSDT,SOLUSDT,UNIUSDT,XRPUSDT `
  --horizons 1,5,10 `
  --block-size 20 `
  --bootstrap-samples 1000 `
  --seed 0 `
  --output reports/forecast-calibration-replay.json
```

### 10.3 重跑 walk-forward calibration

```powershell
.venv\Scripts\python.exe -m src.forecast_calibration `
  --input reports/forecast-calibration-replay.json `
  --output reports/forecast-calibration-research.json `
  --min-samples 180 `
  --min-issue-dates 90 `
  --min-class-samples 30 `
  --probability-clip 0.000001 `
  --l2 1.0 `
  --reliability-bins 10

Get-FileHash reports/forecast-calibration-research.json -Algorithm SHA256
```

Promotion gate 需針對 report 中單一 `model_version + horizon_days` 的 records 呼叫 `paired_promotion_gate(...)`，並明確傳入是否已確認 evaluation protocol、exact vintage 與 decision-policy impact。不能把三個 horizons 混成一個正式 gate；布林值仍屬呼叫端聲明，production 流程應再綁定不可回寫的 protocol registry，而不是信任任意手工 records。

## 11. 已知限制

1. **Current-vintage bias**：來源 CSV 是 2026-07-21 取得的 current/revised vintage，不是每個歷史 issue date 當下能看到的 exact vintage，因此 `exact_vintage_confirmed=false`。
2. **Survivorship／universe bias**：使用今天明確指定的 15-symbol universe；POLUSDT 較晚才有資料。這不是每個歷史日期的精確可投資 universe。
3. **Live evidence 尚未建立**：live ledger 目前沒有已成熟 ready outcomes；這份結果是 replay research，不能冒充 live performance。
4. **門檻政策未校準**：0.5 固定門檻下 Recall/F1 崩潰。任何新 threshold、abstention 或 cost matrix 都必須只用 training fold 決定，再在 untouched fold 評估。
5. **Pooling 假設**：跨 symbol 共用校準器可能遮蔽幣種與 regime 差異；分群分析只能當診斷，不能事後挑贏家作正式 gate。
6. **Pooled AUC 可能改變**：單日 monotonicity 不等於跨日期 global ranking 不變。本次結果已實際觀察到 AUC/AP 惡化。
7. **ECE 分箱敏感**：equal-width ECE 改善，但 equal-mass reliability gap 未改善，不能只挑有利的分箱報告。
8. **計算與 artifact 體積**：本機全量執行約 5 分鐘；逐筆保存兩種參數與證據使 artifact 約 169–173 MB（v2 精確為 172.81 MB）。這不適合放在線上 request path。
9. **未計交易效用**：本報告沒有納入 fee、slippage、position sizing、turnover、drawdown 或 asymmetric decision cost。

## 12. 下一步

1. 先建置 immutable point-in-time data snapshots 與歷史 universe membership，消除 exact-vintage／survivorship gate blocker。
2. 預先指定單一 challenger 與固定 evaluation window；若要測 rolling window、decay、intercept-only 或 hierarchical shrinkage，必須在 nested walk-forward validation 內選定，再鎖定 untouched test。
3. 把 probability calibration 與 decision policy 分開：proper scores 評機率，threshold/cost curve 評決策；禁止因 Recall 太低就直接在 test set 上調 0.5。
4. 補齊 live outcome ledger，先 shadow 運行，累積每個 model+horizon 的成熟 outcomes；沒有足夠 live evidence 就 fail closed。
5. 增加按 issue-date 的 calibration drift、parameter drift、risk-coverage、regime/cohort sensitivity 與 data-quality alarms。
6. 將研究 artifact 改成 compact summary 加 Parquet/columnar row output，避免每列重複參數造成約 173 MB JSON。
7. 只有在 Brier／log-loss CI、positive BSS vs forecast-time baseline、AUC non-inferiority、決策政策與 exact-vintage checks 全部通過後，才進入人工 review；仍先 shadow，不直接 production。
8. 若新增真正的 feature-based ML challenger，再建立 frozen feature schema、SHAP 與 attribution stability 報告；SHAP 不取代 leakage-safe OOS 指標。

## 13. 實作與相關文件

- 校準實作：`src/forecast_calibration.py`
- 校準測試：`tests/test_forecast_calibration.py`
- 指標定義、完整 raw replay 與參考門檻：[crypto-quant 文件合集](crypto-quant_文件合集.docx)第陸章
- Scorecard 與 promotion policy：[Forecast Scorecard P0](forecast-scorecard-p0.md)
- 方法背景：Kull et al., 2017, [Beta calibration: a well-founded and easily implemented improvement on logistic calibration for binary classifiers](https://proceedings.mlr.press/v54/kull17a.html)
