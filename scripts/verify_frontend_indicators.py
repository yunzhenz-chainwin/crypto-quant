"""
verify_frontend_indicators.py — 前端指標正確性驗證(可重複執行)

驗證 frontend/src/lib/indicators.js 裡「實際上線」的指標計算是否正確:
  用 Node 跑那份真實函式算出 SMA/EMA/KDJ/DMI/BIAS,
  再用獨立的第三方庫 pandas_ta 算同樣指標,逐點比對最大誤差。

跳過前 SKIP 根「暖身期」(RSI/KDJ/DMI 這類遞迴平滑指標,不同實作的起始慣例
會造成前段小差異,但會收斂;ADX 為雙重平滑,約 200 根後即完全吻合)。

用法：
  python scripts/verify_frontend_indicators.py              # 驗全部 data/clean 幣種
  python scripts/verify_frontend_indicators.py BTCUSDT ETHUSDT
需求：Node(執行 .mjs)、pandas_ta(pip install -r requirements-dev.txt)
"""
import json
import subprocess
import sys
import glob
import os

import pandas as pd
import pandas_ta as ta

# Windows 主控台預設 cp950 無法輸出 ✅/⚠ 等符號 → 先把 stdout/stderr 轉 UTF-8，
# 避免驗證結果印到一半 UnicodeEncodeError 崩潰（#112）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MJS = os.path.join(ROOT, "scripts", "verify_frontend_indicators.mjs")

SKIP = 200      # 跳過暖身根數(ADX 雙重平滑約此後收斂)
TOL_ABS = 0.05  # 0~100 類指標(KDJ/DMI)容忍絕對誤差
TOL_REL = 1e-3  # 價格類(SMA/EMA)與 BIAS 容忍相對誤差


def js_calc(sym: str) -> dict:
    """呼叫 Node,用 lib/indicators.js 算出指標,回傳 JSON。"""
    out = subprocess.run(["node", MJS, sym], capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        raise RuntimeError(f"node 執行失敗：{(out.stderr or '')[-300:]}")
    return json.loads(out.stdout)


def _col(dfr, prefix):
    for c in dfr.columns:
        if c.upper().startswith(prefix):
            return dfr[c]
    raise KeyError(f"{prefix} 找不到,欄位={list(dfr.columns)}")


def _compare(dates, jsmap, field, ref):
    ad = rd = 0.0
    n = 0
    for i in range(len(dates)):
        if i < SKIP:
            continue
        rec = jsmap.get(dates[i])
        if rec is None:
            continue
        jv = rec.get(field) if field else rec.get("value")
        rv = ref.iloc[i]
        if jv is None or pd.isna(rv):
            continue
        a = abs(jv - rv)
        ad = max(ad, a)
        if abs(rv) > 1e-9:
            rd = max(rd, a / abs(rv))
        n += 1
    ok = n > 0 and (rd < TOL_REL or ad < TOL_ABS)
    return ok, ad, rd, n


def verify(sym: str):
    js = js_calc(sym)
    df = pd.read_csv(os.path.join(ROOT, "data", "clean", f"{sym}_1d.csv"))
    df["d"] = df["date"].astype(str).str[:10]
    h, l, c = df["high"], df["low"], df["close"]
    dates = df["d"].tolist()
    kdj = ta.kdj(h, l, c, length=9, signal=3)
    adx = ta.adx(h, l, c, length=14)
    checks = [
        ("SMA20",  js["sma20"], None, ta.sma(c, 20)),
        ("EMA20",  js["ema20"], None, ta.ema(c, 20)),
        ("KDJ.K",  js["kdj"], "k", _col(kdj, "K")),
        ("KDJ.D",  js["kdj"], "d", _col(kdj, "D")),
        ("KDJ.J",  js["kdj"], "j", _col(kdj, "J")),
        ("+DI",    js["dmi"], "pdi", _col(adx, "DMP")),
        ("-DI",    js["dmi"], "mdi", _col(adx, "DMN")),
        ("ADX",    js["dmi"], "adx", _col(adx, "ADX")),
        ("BIAS6",  js["bias6"], None, ta.bias(c, 6) * 100),   # pandas_ta 回傳比率,×100 對齊
        ("BIAS24", js["bias24"], None, ta.bias(c, 24) * 100),
    ]
    results, allok = [], True
    for name, m, f, ref in checks:
        ok, ad, rd, n = _compare(dates, m, f, ref)
        allok &= ok
        results.append((name, ok, ad, rd))
    return allok, results


def main():
    syms = sys.argv[1:]
    if not syms:
        syms = sorted(
            os.path.basename(p).replace("_1d.csv", "")
            for p in glob.glob(os.path.join(ROOT, "data", "clean", "*_1d.csv"))
        )
    print(f"前端指標驗證(vs pandas_ta,跳過前 {SKIP} 根暖身)— 共 {len(syms)} 幣\n")
    overall = True
    for sym in syms:
        try:
            ok, results = verify(sym)
        except Exception as e:
            print(f"[ERROR] {sym}: {e}")
            overall = False
            continue
        overall &= ok
        bad = [r for r in results if not r[1]]
        tag = "PASS ✅" if ok else "FAIL ⚠"
        line = f"[{tag}] {sym:10} {len(results) - len(bad)}/{len(results)} 指標吻合"
        if bad:
            line += "  不符: " + ", ".join(f"{r[0]}(絕誤{r[2]:.2e})" for r in bad)
        print(line)
    print("\n總結:", "全部指標計算正確 ✅" if overall else "有指標不符,請檢查 ⚠")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
