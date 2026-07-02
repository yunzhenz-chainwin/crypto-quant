"""
verify_indicators.py — 指標交叉驗證

用『獨立演算法』重算 RSI / MACD / 均線 / 布林 / 均量(明確的 Wilder / EMA 遞迴、
numpy 自算 SMA 與母體標準差,不重用 src/indicators.py 的程式),再跟
reports/indicators_*.csv 的值『逐點比對』。兩邊一致 → 指標計算正確。

為避免暖身期(MA200 需 200 根、EMA 種子差異)干擾,從第 250 列起比對。

用法:
  python src/verify_indicators.py          # CLI 印出每幣結果
供後台 API 呼叫:cross_check_indicators() → dict
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
REP = ROOT / "reports"
INTERVAL = "1d"          # 預設週期(前台徽章用);函式皆可傳 interval 驗證 1h
SKIP = 250


def _sma(x, w):
    c = np.concatenate([[0.0], np.cumsum(x)])
    out = np.full(len(x), np.nan)
    out[w - 1:] = (c[w:] - c[:-w]) / w
    return out


def _rstd(x, w):  # 母體標準差(ddof=0)
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])
    out = np.full(len(x), np.nan)
    s = c1[w:] - c1[:-w]
    var = (c2[w:] - c2[:-w]) / w - (s / w) ** 2
    out[w - 1:] = np.sqrt(np.clip(var, 0, None))
    return out


def _ema(x, span):
    a = 2.0 / (span + 1)
    out = np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = (1 - a) * out[i - 1] + a * x[i]
    return out


def _rsi(close, n=14):
    d = np.diff(close)
    gain = np.clip(d, 0, None)
    loss = np.clip(-d, 0, None)
    a = 1.0 / n
    ag = np.empty(len(d)); al = np.empty(len(d))
    ag[0] = gain[0]; al[0] = loss[0]
    for i in range(1, len(d)):
        ag[i] = (1 - a) * ag[i - 1] + a * gain[i]
        al[i] = (1 - a) * al[i - 1] + a * loss[i]
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + ag / al)
    out = np.full(len(close), np.nan)
    out[1:] = rsi
    return out


def _cmp(ours, indep, absol=None, rel=1e-3):
    a, b = ours[SKIP:], indep[SKIP:]
    m = ~(np.isnan(a) | np.isnan(b))
    a, b = a[m], b[m]
    if len(a) == 0:
        return True, 0.0
    md = float(np.abs(a - b).max())
    if absol is not None:
        return md <= absol, md
    scale = max(float(np.abs(b).mean()), 1e-9)
    return md <= rel * scale, md


def _symbols(interval=INTERVAL):
    return sorted(p.stem.replace(f"_{interval}", "") for p in CLEAN.glob(f"*_{interval}.csv"))


def indicators_version(interval=INTERVAL) -> float:
    """所有指標檔的最新 mtime,給後台做快取鍵用(資料更新後驗證會重跑)。"""
    return max((p.stat().st_mtime for p in REP.glob(f"indicators_*_{interval}.csv")),
               default=0.0)


def cross_check_indicators(symbols=None, interval=INTERVAL) -> dict:
    symbols = symbols or _symbols(interval)
    coins = []
    for sym in symbols:
        clean_p = CLEAN / f"{sym}_{interval}.csv"
        rep_p = REP / f"indicators_{sym}_{interval}.csv"
        if not (clean_p.exists() and rep_p.exists()):
            coins.append({"symbol": sym, "ok": False, "error": "缺少資料檔"})
            continue
        raw = pd.read_csv(clean_p)
        our = pd.read_csv(rep_p)
        close = raw["close"].to_numpy(float)
        vol = raw["volume"].to_numpy(float)

        ind = {
            "MA20": _sma(close, 20), "MA60": _sma(close, 60), "MA200": _sma(close, 200),
            "VOL_MA20": _sma(vol, 20), "RSI": _rsi(close, 14),
        }
        e12, e26 = _ema(close, 12), _ema(close, 26)
        ind["MACD"] = e12 - e26
        ind["SIGNAL"] = _ema(ind["MACD"], 9)
        ind["HIST"] = ind["MACD"] - ind["SIGNAL"]
        mid, sd = _sma(close, 20), _rstd(close, 20)
        ind["BB_UPPER"] = mid + 2 * sd
        ind["BB_LOWER"] = mid - 2 * sd

        coin_ok, diffs = True, {}
        for col, indep in ind.items():
            ok, md = _cmp(our[col].to_numpy(float), indep,
                          absol=0.05 if col == "RSI" else None)
            diffs[col] = md
            coin_ok = coin_ok and ok
        coins.append({
            "symbol": sym, "ok": coin_ok,
            "rsi": diffs["RSI"], "macd": diffs["MACD"],
            "ma": diffs["MA200"], "bb": diffs["BB_UPPER"],
        })

    passed = sum(1 for c in coins if c.get("ok"))
    return {"ok": passed == len(coins), "total": len(coins),
            "passed": passed, "coins": coins, "interval": interval}


_RESULT_CACHE: dict = {}


def cached_result(interval: str = INTERVAL) -> dict:
    """有快取的交叉驗證結果(快取鍵=指標檔版本,資料更新後自動重算)。
    供後台 API 與前台公開摘要共用,避免每次請求都重算。interval 可傳 "1h"。"""
    v = indicators_version(interval)
    slot = _RESULT_CACHE.setdefault(interval, {})
    if slot.get("ver") != v:
        slot["ver"] = v
        slot["data"] = cross_check_indicators(interval=interval)
    return slot["data"]


def main():
    import sys
    interval = sys.argv[1] if len(sys.argv) > 1 else INTERVAL
    r = cross_check_indicators(interval=interval)
    print(f"\n指標交叉驗證(用獨立演算法逐點比對)")
    print(f"{'幣種':<9} 結果   最大誤差 RSI / MACD / MA200 / BB")
    for c in r["coins"]:
        if "error" in c:
            print(f"{c['symbol']:<9} ERR   {c['error']}")
            continue
        print(f"{c['symbol']:<9} {'PASS' if c['ok'] else 'FAIL':<5}  "
              f"{c['rsi']:.2e} / {c['macd']:.2e} / {c['ma']:.2e} / {c['bb']:.2e}")
    print(f"\n===> {r['passed']}/{r['total']} 通過", "全數通過" if r["ok"] else "有 FAIL")


if __name__ == "__main__":
    main()
