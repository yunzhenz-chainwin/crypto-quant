from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"
INTERVAL = "1d"


def available_symbols() -> list[str]:
    return sorted([
        p.stem.replace(f"_{INTERVAL}", "")
        for p in CLEAN_DIR.glob(f"*_{INTERVAL}.csv")
    ])


def load_prices(symbol: str, days: int = None) -> list[dict]:
    path = CLEAN_DIR / f"{symbol}_{INTERVAL}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if days:
        df = df.tail(days)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.to_dict(orient="records")


def load_indicators(symbol: str, days: int = None) -> list[dict]:
    path = REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if days:
        df = df.tail(days)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.replace({np.nan: None})
    return df.to_dict(orient="records")


def load_correlation() -> dict:
    closes = {}
    symbols = available_symbols()
    for sym in symbols:
        path = CLEAN_DIR / f"{sym}_{INTERVAL}.csv"
        df = pd.read_csv(path, parse_dates=["date"])
        s = df.set_index("date")["close"]
        s.index = s.index.tz_convert(None)  # UTC-aware → naive
        closes[sym.replace("USDT", "")] = s

    wide = pd.DataFrame(closes).dropna()
    returns = wide.pct_change().dropna()
    corr = returns.corr().round(4)
    vol = (returns.std() * np.sqrt(365) * 100).round(2)

    return {
        "symbols": list(corr.columns),
        "matrix": corr.values.tolist(),
        "volatility": vol.to_dict(),
        "period": {
            "start": str(wide.index.min().date()),
            "end": str(wide.index.max().date()),
            "days": len(wide),
        },
    }


def last_updated() -> dict:
    result = {}
    for sym in available_symbols():
        path = CLEAN_DIR / f"{sym}_{INTERVAL}.csv"
        df = pd.read_csv(path, parse_dates=["date"])
        result[sym] = str(df["date"].max().date())
    return result
