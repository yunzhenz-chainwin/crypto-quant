# 預測模型指標基準報告

最後更新：2026-07-21
模型版本：`historical-baseline-v2`
報告狀態：研究基準；不是上線核准或投資績效保證

## 1. 結論先行

本報告用嚴格 point-in-time replay 評估目前的 regime-conditioned empirical
baseline。固定 15 個交易對、1／5／10 日 horizon，共得到 73,881 筆已成熟預測。

- 主要指標 Brier score 為 `0.252671`，forecast-time baseline 為
  `0.251558`，Brier Skill Score（BSS）為 `-0.4424%`。負值表示目前模型略差於
  可在預測當時取得的簡單基準。
- ROC-AUC 為 `0.504585`、AP（step-wise precision-recall area）為
  `0.470341`，接近無有效排序能力；AP 還應和正類比例 `0.473139` 一起看。
- 固定 `p(up) >= 0.5` 時，Recall 為 `0.372554`、F1 為 `0.418699`、MCC
  為 `0.007275`。這些 threshold 指標不能取代機率品質評分。
- 95% moving-block bootstrap 的「baseline Brier loss 減 model Brier loss」區間為
  `[-0.003007, 0.000843]`，跨過 0，沒有優於基準的統計證據。
- replay 中沒有任何預測通過模型本身的 `ready` policy；ready coverage 是
  `0 / 73,881 = 0%`。因此 ready-only 的 F1、Recall、AUC 等全部是 `null`，不能
  用 all-forecast 數值冒充 ready 績效。

目前最誠實的判斷是：系統已有可稽核的評估能力，但現行模型尚未證明有可發布的
預測優勢。F1、AUC 或 SHAP 都不應改變這個結論。後續 Platt／Beta 實驗也維持
`keep_identity`，詳見[預測機率校準研究報告](forecast-calibration.md)。

## 2. 評估問題與事件定義

每筆 issue date 為 `t`、horizon 為 `h` 的預測，事件定義如下：

```text
y = 1  if realized_return_pct(t -> t+h) > 0
y = 0  if realized_return_pct(t -> t+h) <= 0
```

因此：

- positive class 是 `up`；
- 報酬剛好為 0 的 flat outcome 歸為 non-up；
- 分類 label 固定使用 `probability_up >= 0.5`，機率剛好等於 0.5 時判為 up；
- `confidence_threshold = 0.60` 的 committed coverage 是另一個 abstention
  診斷，不能和模型輸出的 `status == ready` coverage 混用；
- threshold 沒有在本 replay 上調參，避免用測試資料選出看似最佳的 F1。

## 3. 四類指標不能混在一起

### 3.1 Proper probability scores：主要模型選擇依據

| 指標 | 定義 | 判讀 |
|---|---|---|
| Brier score | `mean((p - y)^2)` | 越低越好；同時懲罰校準與解析度錯誤 |
| Brier Skill Score | `1 - BS_model / BS_baseline` | 大於 0 才表示優於 forecast-time baseline |
| Log loss | `-mean(y log p + (1-y) log(1-p))` | 越低越好；重罰過度自信且錯誤的機率 |
| ECE | 10 個 equal-width bins 的加權絕對 calibration gap | 越低越好，但受分箱影響，只作診斷 |

Brier 與 log loss 是 proper scores：長期而言，誠實提交真正機率才會得到最佳期望分數。
因此模型比較與校準的主判據仍是 Brier、log loss 及相對 baseline 的 paired
confidence interval，而不是 F1。ECE 不是 proper score，也不單獨作 promotion gate。

### 3.2 Threshold classification metrics：特定決策規則的結果

先在 `p(up) >= 0.5` 建立 TP、FP、TN、FN：

```text
Precision    = TP / (TP + FP)
Recall       = Sensitivity = TP / (TP + FN)
Specificity  = TN / (TN + FP)
F1           = 2TP / (2TP + FP + FN)
Balanced Acc = (Recall + Specificity) / 2
MCC          = (TP*TN - FP*FN) /
               sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN))
```

Precision 回答「預測上漲時有多少真的上漲」，Recall 回答「真正上漲有多少被抓到」。
F1 是 Precision 與 Recall 的 harmonic mean，沒有納入 TN，也沒有概率校準資訊。
Balanced accuracy 與 MCC 在 class imbalance 下比單純 accuracy 更有資訊，但仍依賴
threshold。實際交易 threshold 應由預先宣告的誤判成本、交易成本及獨立 validation
期間決定，不能在 test replay 上最大化 F1。

### 3.3 Ranking metrics：跨所有 threshold 的排序能力

- ROC-AUC 使用 Mann-Whitney rank 定義；相同 probability score 採平均 rank，等同
  正負樣本同分貢獻 0.5。
- 本實作的 PR 指標明確稱為 **Average Precision（AP）**：先按 probability 降序，
  每個相同分數的 tie group 一起納入，再計算
  `sum((recall_k - recall_(k-1)) * precision_k)`。它是 step-wise PR area，不是
  trapezoidal PR-AUC。
- ROC-AUC 要和 0.5 比；AP 必須和該資料切片的 positive prevalence 一起看。

AUC/AP 衡量排序而非校準。一個 AUC 高的模型仍可能輸出錯誤機率；反之，校準後的
機率可能不改變排序，因此 AUC 不變。

### 3.4 Explainability：SHAP 不是績效分數

SHAP 是對明確預測函數 `f(X)` 的 feature attribution 方法，不是 accuracy、F1 或
AUC 類型的績效指標。它回答「某個模型的某些 feature 如何把輸出從背景值推到目前
預測」，不回答「預測是否準確」。

## 4. 實測結果

### 4.1 全部 horizon 合併

| 類別 | 指標 | 實測值 |
|---|---|---:|
| 樣本 | 已成熟預測 | 73,881 |
| 樣本 | Up / non-up support | 34,956 / 38,925 |
| Proper | Brier / baseline Brier | 0.252671 / 0.251558 |
| Proper | Brier Skill Score | -0.4424% |
| Proper | Log loss / baseline log loss | 0.698954 / 0.696363 |
| Calibration | ECE（10 bins） | 0.035678 |
| Threshold | Accuracy | 0.510551 |
| Threshold | Precision | 0.477891 |
| Threshold | Recall / Sensitivity | 0.372554 |
| Threshold | Specificity | 0.634477 |
| Threshold | F1 | 0.418699 |
| Threshold | Balanced accuracy | 0.503515 |
| Threshold | MCC | 0.007275 |
| Ranking | ROC-AUC | 0.504585 |
| Ranking | AP / positive prevalence | 0.470341 / 0.473139 |
| Explainability | SHAP | N/A；目前不是具固定 feature schema 的 ML model |

Confusion matrix（row universe 全部合併、threshold 0.5）：

| TP | FP | TN | FN |
|---:|---:|---:|---:|
| 13,023 | 14,228 | 24,697 | 21,933 |

### 4.2 各 horizon：proper、calibration 與 ranking

| Horizon | N | Positive rate | Brier | Baseline Brier | BSS | Log loss | ECE | ROC-AUC | AP |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 日 | 24,692 | 0.488093 | 0.250876 | 0.250380 | -0.1979% | 0.694919 | 0.022802 | 0.500261 | 0.488347 |
| 5 日 | 24,632 | 0.471419 | 0.252440 | 0.251355 | -0.4319% | 0.698269 | 0.033197 | 0.503384 | 0.469506 |
| 10 日 | 24,557 | 0.459828 | 0.254709 | 0.252947 | -0.6963% | 0.703699 | 0.051114 | 0.496079 | 0.449828 |

三個 horizon 的 BSS 都是負值。1 日 AUC/AP 幾乎等於隨機排序與 prevalence；10 日
AUC 低於 0.5，且 Brier、log loss、ECE 都是三者中最差。不能用 5 日 accuracy 稍高
等局部數字宣稱模型有效。

### 4.3 各 horizon：固定 threshold 0.5

| Horizon | Accuracy | Precision | Recall | Specificity | F1 | Balanced accuracy | MCC |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 日 | 0.501093 | 0.488463 | 0.468968 | 0.531725 | 0.478517 | 0.500346 | 0.000694 |
| 5 日 | 0.516077 | 0.482250 | 0.360317 | 0.654992 | 0.412461 | 0.507655 | 0.015999 |
| 10 日 | 0.514517 | 0.455026 | 0.282235 | 0.712250 | 0.348382 | 0.497243 | -0.006087 |

| Horizon | TP | FP | TN | FN |
|---:|---:|---:|---:|---:|
| 1 日 | 5,652 | 5,919 | 6,721 | 6,400 |
| 5 日 | 4,184 | 4,492 | 8,528 | 7,428 |
| 10 日 | 3,187 | 3,817 | 9,448 | 8,105 |

10 日的 specificity 較高不是「更準」的充分證據；它主要來自更常預測 non-up，並以
低 Recall 為代價。Balanced accuracy 與 MCC 顯示整體判別能力仍接近零。

### 4.4 Ready subset 與 interval forecast

| 項目 | 實測值 |
|---|---:|
| Ready observations | 0 |
| Ready coverage | 0.0000% |
| Ready F1 / Recall / AUC / AP | `null` |
| q10–q90 nominal coverage | 80% |
| q10–q90 empirical coverage | 82.6775% |
| Mean interval width | 22.9604 percentage points |
| Weighted interval score | 4.504830 |

Ready 為 0 表示現有 policy 選擇全部 abstain；它不是「0% accuracy」。在至少有一筆
ready 且 outcome 已成熟前，ready-only 的績效必須保持 `null`。

### 4.5 現況判讀與「多少才有參考意義」

先區分三件事：**有統計訊號**、**能輔助決策**、**可以上線**不是同一件事。以下數字是
本專案的內部研究里程碑，不是跨市場通用的「及格線」，也不是獲利保證。正式判定必須
針對每個 `model_version × horizon` 分開進行；跨 horizon pooled 數字只能用來描述現況，
不能掩蓋某個 horizon 的退步。

目前整體判定是 **尚無可依賴的方向預測優勢**：

- BSS 為負，且 log loss 高於 forecast-time baseline；主要 proper scores 都沒有勝過基準；
- ROC-AUC 僅 `0.504585`、MCC 僅 `0.007275`，實務上仍接近無排序／無判別能力；
- AP `0.470341` 低於事件 prevalence `0.473139`，尚未產生 precision-recall lift；
- Accuracy `0.510551` 低於永遠預測 non-up 的 majority baseline `0.526861`；
- ECE `0.035678` 可粗略讀成 10 個固定機率區間內，預測與實際頻率的加權差約
  `3.57` 個百分點；它比其他指標接近可改善範圍，但不能抵銷負 BSS；
- 80% interval 的 empirical coverage 是 `82.6775%`，落在下表暫定的 `77%–83%`
  容許帶內；但平均寬度達 `22.9604` 個百分點，且尚無同口徑 interval baseline，
  所以只能說 coverage 尚可，不能說區間已經實用；
- ready observations 是 `0`。因此目前結果只能作 all-forecast 研究診斷，不能宣稱為
  使用者實際會收到的預測表現。

#### 建議的最低證據與下一階段目標

下表多數是尚未程式化的 **P1 研究門檻**，不是現行自動 promotion gate。現行
calibration gate 對 AUC 的要求是 challenger 相對 identity 最多退步 `0.002`，對 log
loss 則是 challenger 相對 identity non-inferior；下表要求 AUC 顯著高於隨機、log loss
顯著優於 forecast-time baseline，是針對後續 source model 的較強目標。所有未來 CI 都應
使用 issue-date clustered block bootstrap；重抽 AP lift 時也要在每次 resample 同步重算
prevalence。

| 指標／條件 | 現在 | 最低「有參考意義」條件 | 建議的下一階段內部目標 | 現況 |
|---|---:|---|---|---|
| 證據量與 provenance | pooled `N=73,881`；`vintage_exact=false`；ready `N=0` | 每個 model+horizon 至少 1,000 筆、180 個 issue dates、正負類各 100 筆；完整 universe、唯一 forecast ID、exact immutable vintage | 將前述條件設為 hard gate，另累積相同規模的 live/shadow matured outcomes | 樣本列數足夠，但 exact-vintage 與 live/ready 證據不合格 |
| Brier / BSS | `0.252671` / `-0.4424%` | BSS `>0`，且日期 block-bootstrap 的「baseline − model」95% CI 下界 `>0` | 每個 horizon BSS 至少 `+1%`；依各自 baseline 換算，1／5／10 日 Brier 約需 `<=0.247876`／`<=0.248841`／`<=0.250418`。overall 的示意值是 `<=0.249042`，不可拿來取代各 horizon gate | 不合格 |
| Log loss | `0.698954`；baseline `0.696363` | 低於同一批 forecast IDs 的 baseline，且 paired improvement 95% CI 下界 `>0` | 先以至少 `0.5%` relative improvement 作研究里程碑；依目前 baseline 約為 `<=0.692881` | 不合格 |
| ECE | `0.035678` | 在相同 paired OOS rows 上，challenger 對 identity 的 equal-width 與 tie-preserving equal-mass ECE 都改善、各 bin support 足夠，且 Brier/AUC 不退步 | 兩種分箱 ECE 皆 `<=0.02`；`<=0.01` 可視為較強校準，但仍不可單獨升級模型 | 尚未達標；不可單看 |
| ROC-AUC | `0.504585` | 95% 日期 block-bootstrap CI 下界 `>0.5`，並在各 horizon／regime 穩定 | point AUC `>=0.53` 作第一個弱訊號里程碑；`>=0.55` 作較強目標 | 接近隨機 |
| AP | `0.470341`；prevalence `0.473139` | AP 高於同切片 prevalence，且 AP lift 的 95% CI 下界 `>0` | AP 至少比 prevalence 高 `5%` relative；依目前 prevalence 約為 `>=0.496796` | 無 lift |
| Accuracy | `0.510551`；majority baseline `0.526861` | 高於同切片 majority baseline，且不能伴隨 Recall 或 Specificity 崩潰 | 至少 `>0.526861`，並同時通過 Balanced accuracy 與 MCC 目標；不設單獨 promotion gate | 低於簡單基準 |
| Balanced accuracy | `0.503515` | 95% CI 下界 `>0.5` | point estimate `>=0.52`；較強目標 `>=0.55` | 接近隨機 |
| MCC | `0.007275` | 95% CI 下界 `>0` | point estimate `>=0.05`；較強目標 `>=0.10` | 接近零 |
| Precision / Recall / F1 @0.5 | `0.477891` / `0.372554` / `0.418699` | threshold 必須在 training/validation 事先固定，並與相同 coverage、成本政策的 baseline 比較 | 暫定聯合篩選：Precision `>= prevalence + 0.02`（目前約 `0.493139`）、Recall `>=0.50`、Specificity `>=0.50`、F1 `>=0.50`；仍須同時滿足 BSS、Balanced accuracy、MCC 與成本條件 | Recall/F1 偏低，且沒有決策優勢證據 |
| Ready coverage | `0%` | 先預先登錄可接受的 coverage floor，再評分至少 1,000 筆／180 dates 的 matured ready outcomes | 若產品尚未定義頻率，可先用 `>=10%` 作 shadow 可用性里程碑；不得在測試結果後調低 | 不可評估 ready 績效 |
| 80% prediction interval | coverage `82.6775%`；width `22.9604pp`；WIS `4.504830` | coverage 落在預先登錄的 `77%–83%` 產品容許帶，且 WIS／width 優於同口徑 forecast-time interval baseline | 保持 coverage 在暫定規劃帶內，同時讓 WIS 至少相對改善 `5%`；不設跨 horizon 的固定 width | pooled coverage 落在暫定規劃帶；尚無 baseline／cluster CI，sharpness 與 skill 未證明 |
| SHAP | `N/A` | 先有固定 feature schema、model object、background dataset 與 frozen OOS set | 報告 feature direction、mean absolute SHAP、跨 chronological folds 的穩定性；SHAP 數值本身沒有「越高越好」門檻 | 現階段不適用 |

表中的 `+1% BSS`、`AUC 0.53`、`ECE 0.02` 等是用來管理研發進度的**規劃值**；真正的
最低證據仍是「優於正確的 forecast-time baseline，而且 paired confidence interval
排除無改善」。若只達到 point target、CI 仍跨過基準，結論仍是「值得繼續研究」，不是
「已經可靠」。同樣地，即使統計 gate 全部通過，也還要在未觸碰的 exact-vintage test、
live shadow、交易成本／滑價與風險限制下通過，才有資格進入人工發布審查。

#### 為什麼 F1、Recall 與 SHAP 不能單獨訂漂亮數字

以目前 prevalence 計算，永遠預測 up 會得到 Precision `0.473139`、Recall `1.0`、F1
`0.642355`，卻完全沒有辨別何時上漲的能力。這表示 F1 或 Recall 很高也可能只是退化成
單一類別策略。因此本專案只接受預先固定 threshold 下的聯合條件，並同時查看
Specificity、Balanced accuracy、MCC、coverage 與成本。SHAP 則是「模型為什麼這樣
預測」的 attribution，不是「模型預測得多準」的分數，所以不應設定越大越好的 target。

## 5. Null 與邊界規則

輸出契約使用 JSON `null`，不使用 NaN、Infinity 或偷偷補 0：

- 空樣本：support 與 confusion counts 為 0；所有比率、AUC、AP 與 proper scores
  為 `null`；
- 只有單一 outcome class：ROC-AUC 與 AP 為 `null`；Balanced accuracy 和 MCC
  因缺少另一類別也為 `null`；
- Precision、Recall、Specificity、F1 各自只在分母非 0 時輸出數值，否則 `null`；
- probability ties 在 AUC 使用平均 rank，在 AP 使用整個 tie group，結果不受資料列
  順序影響；
- 所有表格都必須同時帶 `positive_support`、`negative_support`、threshold 與
  positive class，避免脫離事件定義解讀。

## 6. Replay 方法與防洩漏條件

對 issue index `t` 與 horizon `h`，模型和 forecast-time baseline 只能使用 origin
`j` 滿足：

```text
j + h <= t
```

也就是 outcome 在預測發出前已成熟，才可進入 empirical history。`t+h` 的結果只能
在預測完成後附加供評分。baseline 依 symbol × horizon 個別計算，使用 Laplace(1,1)
smoothing；不能以最終全樣本上漲率取代 forecast-time baseline。

其他固定條件：

- 模型：`historical-baseline-v2`；
- universe：`ADAUSDT, ATOMUSDT, AVAXUSDT, BNBUSDT, BTCUSDT, DOGEUSDT,
  DOTUSDT, ETHUSDT, LINKUSDT, LTCUSDT, NEARUSDT, POLUSDT, SOLUSDT,
  UNIUSDT, XRPUSDT`；
- horizon：`1,5,10` 日；
- issue date：`2021-10-30` 至 `2026-07-19`；
- 最大 target date：`2026-07-20`；
- bootstrap：issue-date clustered circular moving blocks，block size 20、1,000
  resamples、seed 0；
- `vintage_exact = false`：CSV 是 2026-07-21 當下可得／可能經修訂的歷史資料，不是
  每個歷史 issue date 當時的原始資料快照；
- POLUSDT 原始資料從 2024-09-13 起，其餘本次 universe 檔案從 2021-07-03 起；
- 本報告沒有搜尋最佳 threshold、沒有訓練新模型，也沒有自動部署。

各 horizon 實際 issue window：

| Horizon | Issue date min | Issue date max | Resolved observations |
|---:|---|---|---:|
| 1 日 | 2021-10-30 | 2026-07-19 | 24,692 |
| 5 日 | 2021-10-30 | 2026-07-15 | 24,632 |
| 10 日 | 2021-10-30 | 2026-07-10 | 24,557 |

95% paired Brier advantage CI 的 estimate 是 `-0.001113`、區間
`[-0.003007, 0.000843]`。估計值小於 0，且區間含 0，不符合「有統計證據優於
forecast-time baseline」的門檻。

## 7. 資料雜湊與重現

### 7.1 Manifest hash

下列 aggregate hash 的 canonical input 是依本節表格順序排列的
`SYMBOL:FILE_SHA256\n` ASCII 字串：

```text
manifest_sha256 = 9315c60b65772ed5ae495a5442ead39df06f14b5b329e7bc8d77baaf7338d000
```

| Symbol | Rows | SHA-256 |
|---|---:|---|
| ADAUSDT | 1,844 | `e4e3f482a6fec602fe41422ccdddd8bdf02bbbfcfc1da64096543bf39c33a64d` |
| ATOMUSDT | 1,844 | `8da69cbd56f3e9f0dc8874aed5fac70901f64c85340695e414c328e2bd4ee0a8` |
| AVAXUSDT | 1,844 | `8d13a6588dce2b62b70a049810977e6f3602e66ee145b221945a990bab169964` |
| BNBUSDT | 1,844 | `f7294236452cd721130fa455525d530a38d24ef079b9940f47e2c48d36631b98` |
| BTCUSDT | 1,844 | `2b851ce201873a697191e5be096b28cb7b593333771766b3d7efb7ff8fff731d` |
| DOGEUSDT | 1,844 | `8d7a263d188ff7a24b2846cd306b9086d2ec1cefb74ea1fa3233a6cdc00c3250` |
| DOTUSDT | 1,844 | `d929ad5bc17d7f6c5aa54d587097efaf4e9287ae2fa5405c4d270765ff8a82a4` |
| ETHUSDT | 1,844 | `30cd3384a8891f30d5eff468acebbdb1a7fad409ad5ddbb69b666779d4aff675` |
| LINKUSDT | 1,844 | `c881452de6b7ac06650cef7d377629b7c703642f61e7f2bcc59c5e3503c89f53` |
| LTCUSDT | 1,844 | `13ee2f4444a35c7f2d8186a44956e6748674756538dad34700d960f2fbcf15ee` |
| NEARUSDT | 1,844 | `64a915ddc2e501cf34fce06c3f6e4524e749c4405ac0dadaf65177386437e69c` |
| POLUSDT | 676 | `b5a5ed7fc16ba0e100f18a8e7356db4eead7a2b0d4043c850323ef202b89a92c` |
| SOLUSDT | 1,844 | `6756d4cb3b4e158c2a963db7cfbe36734f68ece0282d04e95137dfb9003fb580` |
| UNIUSDT | 1,844 | `47a5a5e693ac18b9258713ce5eb59d1c43d379658bb74cb0f8dbd5ec25607465` |
| XRPUSDT | 1,844 | `43f470b1bed62ab516d06b692d0ada12d5776d0c3fe3a74ec0f4abfb33f645c6` |

只要任一 CSV 改變，必須重跑 replay、更新表格和 manifest hash；不可沿用本報告數字。

### 7.2 重現命令

從 repository root 執行：

```powershell
.venv\Scripts\python.exe -m src.forecast_replay `
  --symbols ADAUSDT,ATOMUSDT,AVAXUSDT,BNBUSDT,BTCUSDT,DOGEUSDT,DOTUSDT,ETHUSDT,LINKUSDT,LTCUSDT,NEARUSDT,POLUSDT,SOLUSDT,UNIUSDT,XRPUSDT `
  --horizons 1,5,10 `
  --block-size 20 `
  --bootstrap-samples 1000 `
  --seed 0 `
  --output reports/forecast-model-metrics-replay.json
```

`--output` 的完整 scorecard 才是稽核依據；console compact summary 只供快速閱讀。若要
正式比較新舊模型，應鎖定 code commit、資料 snapshot 與 universe，再執行相同 replay。

## 8. 為什麼現在不應輸出 SHAP 數值

現行 `historical-baseline-v2` 不是以固定 feature matrix 訓練出的 tree、linear 或
neural model。它的流程是：

1. 從歷史 close 計算 60 日均線與 20 日報酬，決定 bull／bear／sideways regime；
2. 僅納入 issue time 已成熟的 historical returns；
3. regime 樣本足夠時使用同 regime empirical outcomes，否則 fallback 到全 history；
4. 用 Laplace-smoothed empirical up rate 及 empirical return quantiles 產生預測。

這個流程目前沒有穩定的 `X -> f(X)` feature schema，也沒有定義 SHAP 所需的 background
distribution、缺失 feature coalition 或 correlated-feature intervention。硬把 MA60、
return20、regime 等中間值丟進 Kernel SHAP，會把人為 wrapper 的行為誤稱為原模型的
feature contribution；數字雖然可產生，但不具可靠語義。

目前可用、且忠於模型機制的替代解釋是：

- **Audit trace**：顯示 issue date、regime、mature sample count、是否使用 same-regime
  cohort、最新可用 origin/target date、input hash；
- **Rule contribution**：列出 MA60 與 return20 如何觸發 regime，不以黑盒 attribution
  取代規則本身；
- **Counterfactual cohort**：同時報告 same-regime 與 all-history 的 `p(up)`、q10/q50/q90
  差值，說明 cohort selection 對輸出的影響；
- **Leave-one-block-out sensitivity**：逐段移除歷史區塊，量化少數時期是否支配預測；
- **Calibration/risk evidence**：使用 calibration bins、Brier decomposition、
  risk-coverage curve 說明模型在哪些機率區間失準。

未來若建立有版本化 feature schema、固定 preprocessing、獨立訓練／validation／test
切分的 challenger ML model，才可在 frozen test set 上加入 SHAP。即使如此，SHAP 仍
只作解釋，不能作 promotion gate，也不能取代 leakage-safe Brier/AUC/F1 評估。

## 9. 發布與後續模型校準的使用方式

本報告新增的 F1、Recall、AUC、AP、MCC 是診斷面板，不新增 promotion gate。下一階段
做 calibration model 時應遵守：

1. calibration 僅用當時已成熟的 training outcomes fit；
2. 每個 evaluation issue date 都只能套用之前 fit 的 calibrator；
3. 同時保留 raw probability 與 calibrated probability；
4. 主要比較 paired Brier/log-loss 與其 temporal block-bootstrap CI；
5. AUC 理論上不應因單調 calibration 明顯改變；若改變，要檢查 ties 或資料切分；
6. F1/Recall 僅在事先固定 threshold 或成本政策後報告；
7. 沒有成熟 outcome 或只有單一 class 時保持 `null`；
8. 通過離線門檻也只代表可進入 shadow/challenger，不等於自動部署。

## 10. 方法來源

- Brier, 1950, [Verification of Forecasts Expressed in Terms of Probability](https://journals.ametsoc.org/doi/10.1175/1520-0493%281950%29078%3C0001%3AVOFEIT%3E2.0.CO%3B2)
- Gneiting & Raftery, 2007, [Strictly Proper Scoring Rules, Prediction, and Estimation](https://doi.org/10.1198/016214506000001437)
- Murphy, 1973, [A New Vector Partition of the Probability Score](https://doi.org/10.1175/1520-0450%281973%29012%3C0595%3AANVPOT%3E2.0.CO%3B2)
- Fawcett, 2006, [An Introduction to ROC Analysis](https://doi.org/10.1016/j.patrec.2005.10.010)
- Davis & Goadrich, 2006, [The Relationship Between Precision-Recall and ROC Curves](https://doi.org/10.1145/1143844.1143874)
- van Rijsbergen, 1979, [Information Retrieval, 2nd edition](https://shop.elsevier.com/books/information-retrieval/van-rijsbergen/978-0-408-70929-3)
- Matthews, 1975, [Comparison of the Predicted and Observed Secondary Structure of T4 Phage Lysozyme](https://doi.org/10.1016/0005-2795%2875%2990109-9)
- Brodersen et al., 2010, [The Balanced Accuracy and Its Posterior Distribution](https://doi.org/10.1109/ICPR.2010.764)
- Guo et al., 2017, [On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a.html)
- Lundberg & Lee, 2017, [A Unified Approach to Interpreting Model Predictions](https://papers.neurips.cc/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html)

## 11. 實作位置與測試契約

- 指標實作：`src/forecast_evaluation.py`
- point-in-time replay：`src/forecast_replay.py`
- 單元測試：`tests/test_forecast_evaluation.py`

測試涵蓋公式、threshold tie、score ties、空樣本、單一 class、零分母、JSON
`allow_nan=False`、all-vs-ready 分離，以及 ledger `target_as_of` baseline maturity。
