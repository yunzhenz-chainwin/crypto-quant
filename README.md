# crypto-quant

加密貨幣量化分析工具:抓取每日行情、驗證 OHLC 資料、跨來源比對價格、計算技術指標,並產生彙整報告。

## 專案結構

- `src/fetch_binance.py` 從 Binance 抓取每日 K 線資料,輸出 raw JSON 與 clean CSV 兩層檔案。
- `src/validate.py` 驗證 clean 後的 OHLC 資料。
- `src/cross_check.py` 將 Binance 價格與 CoinGecko 資料做跨來源比對。
- `src/indicators.py` 計算 MA、RSI、MACD 等技術指標。
- `src/correlation.py` 產生報酬相關性與累積成長走勢圖。
- `data/` 存放抓取的原始(raw)與清理後(clean)市場資料。
- `reports/` 存放產生的驗證報告與圖表。

## 安裝設定

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 使用方式

在專案根目錄下執行各個腳本:

```powershell
python src\fetch_binance.py
python src\validate.py BTCUSDT
python src\indicators.py BTCUSDT
python src\correlation.py
python src\cross_check.py BTCUSDT
```
