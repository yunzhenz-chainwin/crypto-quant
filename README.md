# crypto-quant

Python scripts for fetching daily crypto market data, validating OHLC data, cross-checking prices, calculating technical indicators, and generating summary reports.

## Project layout

- `src/fetch_binance.py` fetches Binance daily kline data and writes raw JSON plus clean CSV files.
- `src/validate.py` validates clean OHLC data.
- `src/cross_check.py` compares Binance prices against CoinGecko data.
- `src/indicators.py` calculates MA, RSI, and MACD indicators.
- `src/correlation.py` generates return correlation and cumulative growth charts.
- `data/` contains fetched raw and cleaned market data.
- `reports/` contains generated validation reports and charts.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Usage

Run scripts from the project root:

```powershell
python src\fetch_binance.py
python src\validate.py BTCUSDT
python src\indicators.py BTCUSDT
python src\correlation.py
python src\cross_check.py BTCUSDT
```
