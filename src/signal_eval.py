# -*- coding: utf-8 -*-
"""
signal_eval.py — 訊號預測力評估（結構化輸出，給後台即時儀表板用）

與 signal_scorecard.py 同一套方法（onset 進場、隔日 open 買、N 天後 open 結算，
對照「任一天進場」基準），但回傳結構化 dict 而非列印，並加快取，供 /api/admin 即時顯示。

回傳內容：
  ok / verdict / tone / as_of / coins
  horizons[]  — 整體訊號 5/10/20 天的命中率、平均報酬 vs 基準
  factors[]   — 6 個因子各自的 10 天 edge（誰「準」誰「不准」）
  gap         — 目前 edge 距離「有意義門檻」還差多少（量化「離準有多遠」）

快取鍵 = 指標檔 + scoring.py + backtest.py 的最新 mtime
→ 改了訊號邏輯（scoring.py）或資料更新後，結果會自動重算。

用法：python src/signal_eval.py     # 印出 JSON
供後台 API：cached_scorecard() → dict
"""
from pathlib import Path
import numpy as np
import pandas as pd

# 兩種執行路徑都要能 import（直接跑 / 被後端 import）
try:
    from src.backtest import load_indicators
    from src.scoring import score_row, signal_from_score
except ImportError:
    from backtest import load_indicators
    from scoring import score_row, signal_from_score

ROOT = Path(__file__).resolve().parent.parent
REP = ROOT / "reports"
INTERVAL = "1d"
SKIP = 200
HORIZONS = [5, 10, 20]
FACTOR_N = 10                       # 因子單獨評估用 10 天持有期
USEFUL_THRESHOLD_PP = 0.5           # 10 天 edge 要 > 此值（約覆蓋來回成本 ~0.3%）才談得上「有意義」

FACTOR_KEYS = ["RSI", "MACD", "MA", "MA200", "Volume", "BB"]
FACTOR_LABEL = {"RSI": "RSI 動量", "MACD": "MACD", "MA": "均線排列",
                "MA200": "長期趨勢 MA200", "Volume": "成交量", "BB": "布林通道"}


def _symbols():
    return sorted(p.stem[len("indicators_"):].replace(f"_{INTERVAL}", "")
                  for p in REP.glob(f"indicators_*_{INTERVAL}.csv"))


def _num(v):
    return float(v) if (v is not None and v == v) else None


def evaluate_signal(symbols=None) -> dict:
    symbols = symbols or _symbols()
    comb = {N: {"bull": [], "base": []} for N in HORIZONS}
    fbase = []                                   # 因子分析共用的基準（10 天）
    fbull = {k: [] for k in FACTOR_KEYS}
    as_of, used = "", 0

    for sym in symbols:
        try:
            df = load_indicators(sym)
        except SystemExit:
            continue
        if df is None or df.empty:
            continue
        used += 1
        n = len(df)

        def col(k):
            return df[k].to_numpy(dtype=float) if k in df.columns else np.full(n, np.nan)

        rsi = col("RSI"); hist = col("HIST"); close = col("close")
        ma20 = col("MA20"); ma60 = col("MA60"); ma200 = col("MA200")
        vol = col("volume"); vma = col("VOL_MA20"); bbu = col("BB_UPPER"); bbl = col("BB_LOWER")
        opens = df["open"].to_numpy(dtype=float)
        d = str(pd.to_datetime(df["date"]).max())[:10]
        if d > as_of:
            as_of = d

        # 一次算出：整體訊號 + 每個因子是否「轉多頭」
        sigs = np.empty(n, dtype=object); sigs[0] = "NEUTRAL"
        fb = {k: np.zeros(n, dtype=bool) for k in FACTOR_KEYS}
        for i in range(1, n):
            score, factors = score_row(
                _num(rsi[i]), _num(hist[i]), _num(hist[i - 1]),
                _num(close[i]), _num(ma20[i]), _num(ma60[i]), _num(ma200[i]),
                _num(vol[i]), _num(vma[i]), _num(bbu[i]), _num(bbl[i]))
            sigs[i] = signal_from_score(score)
            for k in FACTOR_KEYS:
                fb[k][i] = factors.get(k, {}).get("score", 0) > 0

        # 整體訊號 5/10/20 天
        for N in HORIZONS:
            for i in range(SKIP, n - 1 - N):
                e, x = opens[i + 1], opens[i + 1 + N]
                if not (e > 0 and x > 0):
                    continue
                r = x / e - 1.0
                comb[N]["base"].append(r)
                if sigs[i] == "BULL" and sigs[i - 1] != "BULL":
                    comb[N]["bull"].append(r)

        # 各因子（10 天）
        for i in range(SKIP, n - 1 - FACTOR_N):
            e, x = opens[i + 1], opens[i + 1 + FACTOR_N]
            if not (e > 0 and x > 0):
                continue
            r = x / e - 1.0
            fbase.append(r)
            for k in FACTOR_KEYS:
                if fb[k][i] and not fb[k][i - 1]:        # 該因子「轉多頭」的首日
                    fbull[k].append(r)

    # ── 整體訊號彙總 ──
    horizons, flags = [], []
    for N in HORIZONS:
        base = np.array(comb[N]["base"]); bull = np.array(comb[N]["bull"])
        bh = float((base > 0).mean() * 100) if len(base) else 0.0
        ba = float(base.mean() * 100) if len(base) else 0.0
        uh = float((bull > 0).mean() * 100) if len(bull) else 0.0
        ua = float(bull.mean() * 100) if len(bull) else 0.0
        horizons.append({"n": N, "samples": int(len(bull)),
                         "hit": round(uh, 1), "base_hit": round(bh, 1), "hit_vs_base": round(uh - bh, 1),
                         "avg": round(ua, 2), "base_avg": round(ba, 2), "avg_vs_base": round(ua - ba, 2)})
        flags.append((ua - ba) > 0 and (uh - bh) > 0 and len(bull) >= 100)
    has_edge = len(flags) > 0 and all(flags)

    # ── 各因子彙總 ──
    fb_arr = np.array(fbase)
    fb_hit = float((fb_arr > 0).mean() * 100) if len(fb_arr) else 0.0
    fb_avg = float(fb_arr.mean() * 100) if len(fb_arr) else 0.0
    factors_out = []
    for k in FACTOR_KEYS:
        arr = np.array(fbull[k])
        if len(arr) == 0:
            factors_out.append({"key": k, "label": FACTOR_LABEL[k], "samples": 0,
                                "edge": 0.0, "hit_vs_base": 0.0, "verdict": "無資料"})
            continue
        avg = float(arr.mean() * 100); hit = float((arr > 0).mean() * 100)
        edge = avg - fb_avg; hv = hit - fb_hit
        if edge > 0.2 and hv > 0:
            verdict = "有預測力"
        elif edge < -0.2:
            verdict = "無預測力"
        else:
            verdict = "中性"
        factors_out.append({"key": k, "label": FACTOR_LABEL[k], "samples": int(len(arr)),
                            "edge": round(edge, 2), "hit_vs_base": round(hv, 1), "verdict": verdict})
    factors_out.sort(key=lambda f: f["edge"], reverse=True)

    # ── 離「有意義」多遠（以 10 天整體 edge 為準）──
    h10 = next((h for h in horizons if h["n"] == 10), None)
    cur_edge = h10["avg_vs_base"] if h10 else 0.0
    gap = {"current_edge_pp": cur_edge, "useful_threshold_pp": USEFUL_THRESHOLD_PP,
           "gap_pp": round(USEFUL_THRESHOLD_PP - cur_edge, 2)}

    if has_edge:
        verdict, tone = "有預測力（edge）", "good"
    elif h10 and h10["avg_vs_base"] < -0.001:
        verdict, tone = "無預測力 — 訊號出現後略遜於隨機進場（追高型）", "bad"
    else:
        verdict, tone = "無明顯 edge — 訊號出現後 ≈ 隨機進場", "warn"

    return {"ok": has_edge, "verdict": verdict, "tone": tone, "as_of": as_of, "coins": used,
            "horizons": horizons, "factors": factors_out, "gap": gap}


def scorecard_version() -> float:
    files = list(REP.glob(f"indicators_*_{INTERVAL}.csv"))
    files += [ROOT / "src" / "scoring.py", ROOT / "src" / "backtest.py"]
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


_CACHE: dict = {}


def cached_scorecard() -> dict:
    v = scorecard_version()
    if _CACHE.get("ver") != v:
        _CACHE["ver"] = v
        _CACHE["data"] = evaluate_signal()
    return _CACHE["data"]


def main():
    import json
    print(json.dumps(cached_scorecard(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
