# -*- coding: utf-8 -*-
"""
macro_eval.py — 宏觀環境有沒有預測力？（唯讀研究腳本，不改任何線上資料）

為什麼要有這支：
  宏觀面板原本只顯示「現在順風/逆風」，沒有任何證據支持這個標籤和後續報酬有關。
  沒驗證就把它寫進判讀，只是再多一個沒有預測力卻在影響使用者的因子（同 6 因子的覆轍）。
  這支把 src/macro_regime.py 的規則套回歷史，逐日重建環境，然後老實檢定：
  在 RISK_ON / RISK_OFF 的日子之後，加密的報酬到底有沒有系統性差別。

無前視偏誤（與 src/backtest.py 同一套時序約定）：
  regime[t] 只用第 t 根（含）以前的宏觀收盤算出 → 隔天開盤 open[t+1] 才進場，
  報酬衡量 open[t+1] → open[t+1+h]。宏觀是美股行事曆（無週末），對齊到加密日曆
  時只用 ffill（往前補、只會用到更早的值），不可能用到未來。

統計上的誠實處理：
  1) h 日報酬逐日重疊 → 樣本不獨立，普通 t 值會灌水約 sqrt(h) 倍。
     主要數字一律用 Newey-West HAC（lag=h）修正，並額外附「不重疊子樣本」對照。
  2) regime 有極強持續性（一段行情連續好幾週同一標籤）→ 真正的獨立樣本數是
     「區段數（episodes）」而非天數。報表兩個都列，讀的人才不會被 1000+ 天誤導。
  3) 多重檢定：事先指定主檢定＝等權籃子、h=5、RISK_ON 減 RISK_OFF。其餘（各幣、
     各 horizon、各單一因子）皆為探索性，看到 |t|>2 也不該當成獨立證據。
  4) 門檻沒有被這份資料調過（見 src/macro_regime.py 的凍結說明）；若日後有人依這裡
     的結果回頭調門檻，這份檢定就失效，必須重新宣告 holdout。

重跑：python src/macro_eval.py
輸出：reports/macro_evidence.json（前台 /api/macro 讀這份當「證據」）
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

try:
    from src.macro_regime import DRIVER_KEYS, regime_series
except ImportError:
    from macro_regime import DRIVER_KEYS, regime_series

CLEAN = ROOT / "data" / "clean"
DB_PATH = ROOT / "data" / "app.db"
REPORT_DIR = ROOT / "reports"
INTERVAL = "1d"

HORIZONS = (1, 5, 20)         # 持有天數；主檢定用 5
PRIMARY_HORIZON = 5
REGIMES = ("RISK_ON", "NEUTRAL", "RISK_OFF")
MAX_FFILL_DAYS = 5            # 宏觀最多往前補 5 天（長假可接受，更久視為缺資料）


# ── 資料載入 ──────────────────────────────────────────────────────────
def load_macro() -> pd.DataFrame:
    """macro_daily → 以日期為索引的寬表（美股行事曆，含缺值）。"""
    with sqlite3.connect(str(DB_PATH)) as conn:
        df = pd.read_sql_query(
            "SELECT date, dxy, vix, us10y, spx, gold FROM macro_daily ORDER BY date", conn)
    if df.empty:
        sys.exit("macro_daily 沒有資料，請先執行：python -c "
                 "\"from backend.services.app_db import fetch_macro_history as f; print(f())\"")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _naive_days(values) -> pd.DatetimeIndex:
    """K 線日期帶 UTC 時區、宏觀日期不帶 → 一律轉成 tz-naive 的「日」才對得起來。"""
    idx = pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    return idx.tz_convert(None).normalize()


def load_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    """data/clean 的日線 → (收盤寬表, 開盤寬表)，欄位為幣種。"""
    closes, opens = {}, {}
    for path in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        sym = path.stem.replace(f"_{INTERVAL}", "")
        df = pd.read_csv(path).sort_values("date")
        df.index = _naive_days(df["date"])
        closes[sym] = df["close"].astype(float)
        opens[sym] = df["open"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    O = pd.DataFrame(opens).sort_index().reindex(C.index)
    return C, O


def align_regime(macro: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """
    宏觀（美股行事曆）→ 加密日曆（每天）。

    只用 ffill：週末與美股假日沿用「最後一次真正收盤」的環境，正是當下交易者
    實際掌握的資訊。limit 上限避免長期斷線時還在沿用過期標籤。
    """
    reg = regime_series(macro)
    keep = [c for c in reg.columns if c.endswith("_impact")] + ["verdict", "net", "n_drivers"]
    out = reg[keep].reindex(macro.index.union(calendar)).sort_index()
    out = out.ffill(limit=MAX_FFILL_DAYS).reindex(calendar)
    return out


# ── 統計工具 ──────────────────────────────────────────────────────────
def _newey_west_var(u: np.ndarray, X: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West HAC 的三明治中層 S = Ω₀ + Σ w_k (Ω_k + Ω_kᵀ)。"""
    h = X * u[:, None]
    S = h.T @ h
    for k in range(1, lag + 1):
        if k >= len(h):
            break
        w = 1.0 - k / (lag + 1.0)
        G = h[k:].T @ h[:-k]
        S = S + w * (G + G.T)
    return S


def ols_hac(y: np.ndarray, X: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """
    OLS + Newey-West 標準誤 → (係數, 標準誤)。X 需自帶截距欄。

    注意：這裡的樣本在時間上可能不連續（例如只取 RISK_ON ∪ RISK_OFF 的日子），
    自相關修正把「相鄰的樣本列」視為相鄰時點，屬近似；重疊視窗造成的膨脹是主要
    問題、也確實被修掉，剩下的近似誤差遠小於完全不修正。
    """
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    S = _newey_west_var(u, X, lag)
    V = XtX_inv @ S @ XtX_inv
    return beta, np.sqrt(np.maximum(np.diag(V), 0.0))


def mean_with_hac_t(r: np.ndarray, lag: int) -> tuple[float, float]:
    """單一序列平均值的 HAC t 值。"""
    if len(r) < 3:
        return float("nan"), float("nan")
    X = np.ones((len(r), 1))
    beta, se = ols_hac(r, X, lag)
    t = beta[0] / se[0] if se[0] > 0 else float("nan")
    return float(beta[0]), float(t)


def episodes(labels: pd.Series) -> dict:
    """連續同標籤視為一個區段 → 各 regime 的區段數（真正的獨立樣本量級）。"""
    lab = labels.dropna()
    if lab.empty:
        return {}
    runs = (lab != lab.shift()).cumsum()
    return lab.groupby(runs).first().value_counts().to_dict()


def non_overlap_t(r: pd.Series, h: int) -> tuple[float, float, int]:
    """不重疊子樣本（每 h 天取一筆）的簡單 t 值，當作 HAC 的對照。"""
    sub = r.iloc[::h].dropna()
    n = len(sub)
    if n < 3:
        return float("nan"), float("nan"), n
    sd = float(sub.std(ddof=1))
    t = float(sub.mean() / (sd / np.sqrt(n))) if sd > 0 else float("nan")
    return float(sub.mean()), t, n


# ── 主要分析 ──────────────────────────────────────────────────────────
def forward_returns(O: pd.DataFrame, h: int) -> pd.DataFrame:
    """
    第 t 天收盤可知的訊號 → 隔天開盤進場、h 天後開盤出場的報酬（%），對齊回第 t 天。
    open[t+1+h] / open[t+1] − 1，再 shift(-1) 讓索引回到訊號日 t。
    """
    fwd = (O.shift(-h) / O - 1.0) * 100.0     # 索引 t：open[t+h]/open[t]
    return fwd.shift(-1)                       # 索引 t：open[t+1+h]/open[t+1]


def basket(fwd: pd.DataFrame) -> pd.Series:
    """等權籃子：每天對「當天有報酬的幣」取平均（幣數會隨上市/下市變動）。"""
    return fwd.mean(axis=1, skipna=True)


def regime_table(ret: pd.Series, labels: pd.Series, h: int) -> dict:
    """逐 regime 的報酬統計（HAC t 值 + 不重疊對照 + 區段數）。"""
    df = pd.DataFrame({"r": ret, "g": labels}).dropna()
    eps = episodes(labels.reindex(ret.dropna().index))
    rows = {}
    for g in REGIMES:
        sub = df[df["g"] == g]["r"]
        if sub.empty:
            continue
        mean, t = mean_with_hac_t(sub.to_numpy(dtype=float), lag=h)
        nl_mean, nl_t, nl_n = non_overlap_t(sub, h)
        rows[g] = {
            "days": int(len(sub)),
            "episodes": int(eps.get(g, 0)),
            "mean_pct": round(mean, 3),
            "median_pct": round(float(sub.median()), 3),
            "hit_rate_pct": round(float((sub > 0).mean() * 100), 1),
            "t_hac": round(t, 2) if t == t else None,
            "non_overlap": {"n": nl_n,
                            "mean_pct": round(nl_mean, 3) if nl_mean == nl_mean else None,
                            "t": round(nl_t, 2) if nl_t == nl_t else None},
        }
    return rows


def contrast(ret: pd.Series, labels: pd.Series, h: int,
             a: str = "RISK_ON", b: str = "RISK_OFF") -> dict:
    """
    a 減 b 的差異檢定：在 a∪b 的日子上，把報酬對「是不是 a」的虛擬變數做 OLS+HAC。
    係數即平均差、t 值即這個差是否顯著不為零。
    """
    df = pd.DataFrame({"r": ret, "g": labels}).dropna()
    df = df[df["g"].isin([a, b])]
    if len(df) < 30 or df["g"].nunique() < 2:
        return {"available": False, "reason": "樣本不足"}
    y = df["r"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(df)), (df["g"] == a).to_numpy(dtype=float)])
    beta, se = ols_hac(y, X, lag=h)
    t = beta[1] / se[1] if se[1] > 0 else float("nan")
    return {
        "available": True,
        "a": a, "b": b,
        "diff_pct": round(float(beta[1]), 3),
        "t_hac": round(float(t), 2) if t == t else None,
        "n_days": int(len(df)),
        "significant": bool(abs(t) > 2) if t == t else False,
    }


def factor_tables(fwd_basket: pd.Series, reg: pd.DataFrame, h: int) -> dict:
    """
    拆開看：到底是哪個宏觀因子帶資訊？（探索性）
    每個驅動因子各自的 TAILWIND / HEADWIND 日之後的籃子報酬。
    """
    out = {}
    for key in DRIVER_KEYS:
        col = f"{key}_impact"
        if col not in reg.columns:
            continue
        labels = reg[col]
        rows = {}
        for imp in ("TAILWIND", "HEADWIND"):
            sub = pd.DataFrame({"r": fwd_basket, "g": labels}).dropna()
            sub = sub[sub["g"] == imp]["r"]
            if len(sub) < 30:
                continue
            mean, t = mean_with_hac_t(sub.to_numpy(dtype=float), lag=h)
            rows[imp] = {"days": int(len(sub)), "mean_pct": round(mean, 3),
                         "t_hac": round(t, 2) if t == t else None}
        diff = contrast(fwd_basket, labels, h, a="TAILWIND", b="HEADWIND")
        out[key] = {"by_impact": rows, "tailwind_minus_headwind": diff}
    return out


# ── 連動強度：此刻宏觀對加密的影響力有多大 ───────────────────────────
LINK_WINDOW = 60            # 滾動視窗（交易日）
LINK_SERIES = ("spx", "dxy", "vix", "gold")


def linkage(crypto_close: pd.Series, macro: pd.DataFrame,
            window: int = LINK_WINDOW) -> dict:
    """
    加密與各宏觀序列的「滾動相關性」＋ 目前值在歷史中的百分位。

    這是描述性事實，不是預測宣稱：它回答的是「現在該不該把宏觀當一回事」。
    相關性高 → 加密正被總經帶著走，宏觀讀值值得看重；接近 0 → 加密走自己的邏輯，
    此時把宏觀講得斬釘截鐵就是過度解讀。

    對齊只取「兩邊都有交易」的日子（美股行事曆），日報酬取變動率；
    全部只用當日與更早的資料，逐日滾動，無前視。
    """
    close = crypto_close.dropna()
    close.index = pd.DatetimeIndex(close.index)
    out = {"window_days": window, "series": []}
    if close.empty or macro.empty:
        return out

    crypto_ret = close.pct_change()
    for key in LINK_SERIES:
        if key not in macro.columns:
            continue
        m = pd.to_numeric(macro[key], errors="coerce").dropna()
        joined = pd.DataFrame({"c": crypto_ret, "m": m.pct_change()}).dropna()
        if len(joined) < window * 2:
            continue
        roll = joined["c"].rolling(window).corr(joined["m"]).dropna()
        if roll.empty:
            continue
        current = float(roll.iloc[-1])
        pct_rank = float((roll <= current).mean() * 100)
        out["series"].append({
            "key": key.upper(),
            "corr": round(current, 3),
            "percentile": round(pct_rank, 1),
            "history_min": round(float(roll.min()), 3),
            "history_max": round(float(roll.max()), 3),
            "as_of": str(roll.index[-1].date()),
            "n_obs": int(len(roll)),
        })
    return out


# ── 策略疊加：宏觀當風控閘門 ─────────────────────────────────────────
def regime_overlay_backtest(reg: pd.DataFrame) -> dict:
    """
    把宏觀環境當「不在逆風時才開新倉」的閘門疊在現有策略上，看實際績效差多少。

    無前視：regime[t] 於第 t 根收盤已知，而進場本來就發生在 open[t+1]；
    閘門只是把「前一根收盤的 BULL 訊號」在逆風時改成不進場，時序完全不變。
    出場規則完全不動（停損/停利/訊號出場），只擋新倉，不做任何額外賣出。

    這是探索性比較（15 幣 × 1 種閘門），不是被獨立驗證過的策略。
    """
    try:
        from src.backtest import compute_signals, compute_metrics, run_backtest
    except ImportError:
        from backtest import compute_signals, compute_metrics, run_backtest

    rows = []
    for path in sorted(REPORT_DIR.glob(f"indicators_*_{INTERVAL}.csv")):
        sym = path.stem.replace("indicators_", "").replace(f"_{INTERVAL}", "")
        df = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
        if len(df) < 250:
            continue
        base_signals = compute_signals(df)
        verdicts = reg["verdict"].reindex(_naive_days(df["date"])).to_numpy()
        gated = [
            "NEUTRAL" if (s == "BULL" and v == "RISK_OFF") else s
            for s, v in zip(base_signals, verdicts)
        ]
        try:
            base = compute_metrics(run_backtest(df, signals=base_signals), df, include_curve=False)
            over = compute_metrics(run_backtest(df, signals=gated), df, include_curve=False)
        except Exception:
            continue
        if "error" in base or "error" in over:
            continue
        rows.append({
            "symbol": sym,
            "base_return_pct": base["total_return_pct"],
            "gated_return_pct": over["total_return_pct"],
            "buy_hold_return_pct": base["buy_hold_return_pct"],
            "base_trades": base["total_trades"],
            "gated_trades": over["total_trades"],
            "base_sharpe": base["sharpe_ratio"],
            "gated_sharpe": over["sharpe_ratio"],
            "base_max_dd_pct": base["max_drawdown_pct"],
            "gated_max_dd_pct": over["max_drawdown_pct"],
        })
    if not rows:
        return {"available": False}

    def avg(key):
        return round(float(np.mean([r[key] for r in rows])), 2)

    improved = sum(1 for r in rows if r["gated_return_pct"] > r["base_return_pct"])
    return {
        "available": True,
        "n_symbols": len(rows),
        "improved_symbols": improved,
        "avg_base_return_pct": avg("base_return_pct"),
        "avg_gated_return_pct": avg("gated_return_pct"),
        "avg_buy_hold_return_pct": avg("buy_hold_return_pct"),
        "avg_base_sharpe": avg("base_sharpe"),
        "avg_gated_sharpe": avg("gated_sharpe"),
        "avg_base_max_dd_pct": avg("base_max_dd_pct"),
        "avg_gated_max_dd_pct": avg("gated_max_dd_pct"),
        "per_symbol": rows,
    }


# ── 組裝報告 ──────────────────────────────────────────────────────────
def build_evidence() -> dict:
    macro = load_macro()
    C, O = load_panels()
    reg = align_regime(macro, C.index)
    verdicts = reg["verdict"]

    coverage = verdicts.dropna()
    period = {"start": str(coverage.index.min().date()), "end": str(coverage.index.max().date()),
              "days": int(len(coverage))}
    distribution = {g: int((coverage == g).sum()) for g in REGIMES}
    eps = episodes(coverage)

    by_horizon, per_coin = {}, {}
    for h in HORIZONS:
        fwd = forward_returns(O, h)
        bk = basket(fwd)
        by_horizon[str(h)] = {
            "basket": regime_table(bk, verdicts, h),
            "contrast": contrast(bk, verdicts, h),
            "factors": factor_tables(bk, reg, h),
        }
        if h == PRIMARY_HORIZON:
            for sym in fwd.columns:
                c = contrast(fwd[sym], verdicts, h)
                tbl = regime_table(fwd[sym], verdicts, h)
                per_coin[sym] = {
                    "risk_on_mean_pct": (tbl.get("RISK_ON") or {}).get("mean_pct"),
                    "risk_off_mean_pct": (tbl.get("RISK_OFF") or {}).get("mean_pct"),
                    "diff_pct": c.get("diff_pct"),
                    "t_hac": c.get("t_hac"),
                }

    primary = by_horizon[str(PRIMARY_HORIZON)]["contrast"]
    return {
        "generated_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
        "period": period,
        "regime_days": distribution,
        "regime_episodes": {k: int(v) for k, v in eps.items()},
        "primary_test": {
            "description": "等權籃子、持有 5 日、RISK_ON 減 RISK_OFF（事先指定的唯一主檢定）",
            **primary,
        },
        "by_horizon": by_horizon,
        "per_coin_h5": per_coin,
        "linkage_btc": linkage(C["BTCUSDT"], macro) if "BTCUSDT" in C.columns else {},
        "overlay": regime_overlay_backtest(reg),
        "caveats": [
            "宏觀 regime 具強持續性，真正的獨立樣本是區段數（episodes）而非天數。",
            "h 日報酬逐日重疊，t 值一律以 Newey-West（lag=h）修正並附不重疊子樣本對照。",
            "主檢定只有一個（籃子 × h=5 × RISK_ON−RISK_OFF）；其餘為探索性，勿當獨立證據。",
            "規則門檻訂於本檢定之前且未依本結果調整；若日後回頭調參，本檢定即失效。",
            "樣本期只涵蓋 2021 年以來一輪多空，無法涵蓋不同的升降息循環。",
        ],
    }


def print_report(ev: dict) -> None:
    p = ev["period"]
    print("=" * 72)
    print(f"  宏觀環境預測力檢定  {p['start']} ~ {p['end']}（{p['days']} 天）")
    print("=" * 72)
    print("  環境分布（天數 / 區段數）：")
    for g in REGIMES:
        print(f"    {g:9s} {ev['regime_days'].get(g, 0):5d} 天 / "
              f"{ev['regime_episodes'].get(g, 0):4d} 段")

    for h in HORIZONS:
        tbl = ev["by_horizon"][str(h)]["basket"]
        c = ev["by_horizon"][str(h)]["contrast"]
        print("-" * 72)
        print(f"  等權籃子・持有 {h} 日（隔日開盤進、{h} 日後開盤出）")
        print(f"    {'環境':<10}{'天數':>6}{'平均%':>9}{'勝率%':>8}{'HAC t':>8}"
              f"{'不重疊 t':>10}")
        for g in REGIMES:
            r = tbl.get(g)
            if not r:
                continue
            nt = r["non_overlap"]["t"]
            print(f"    {g:<10}{r['days']:>6}{r['mean_pct']:>9.2f}{r['hit_rate_pct']:>8.1f}"
                  f"{(r['t_hac'] if r['t_hac'] is not None else float('nan')):>8.2f}"
                  f"{(nt if nt is not None else float('nan')):>10.2f}")
        if c.get("available"):
            mark = "顯著" if c["significant"] else "不顯著"
            print(f"    RISK_ON − RISK_OFF = {c['diff_pct']:+.2f}%  "
                  f"HAC t = {c['t_hac']}  → {mark}")

    print("-" * 72)
    print(f"  單因子拆解（h={PRIMARY_HORIZON}，順風 減 逆風，探索性）")
    for key, f in ev["by_horizon"][str(PRIMARY_HORIZON)]["factors"].items():
        d = f["tailwind_minus_headwind"]
        if d.get("available"):
            print(f"    {key:<7}{d['diff_pct']:>+8.2f}%   HAC t = {d['t_hac']:>6}"
                  f"   n = {d['n_days']}")

    link = ev.get("linkage_btc") or {}
    if link.get("series"):
        print("-" * 72)
        print(f"  BTC 與宏觀的連動強度（{link['window_days']} 日滾動相關，描述性）")
        for s in link["series"]:
            print(f"    {s['key']:<6}{s['corr']:>+7.2f}   歷史百分位 {s['percentile']:>5.1f}%"
                  f"   區間 [{s['history_min']:+.2f}, {s['history_max']:+.2f}]")

    ov = ev.get("overlay") or {}
    if ov.get("available"):
        print("-" * 72)
        print("  策略疊加：逆風時不開新倉（探索性，出場規則不變）")
        print(f"    {ov['n_symbols']} 幣中 {ov['improved_symbols']} 幣總報酬改善")
        print(f"    平均總報酬  原始 {ov['avg_base_return_pct']:+.2f}%  →  "
              f"加閘門 {ov['avg_gated_return_pct']:+.2f}%   "
              f"（買入持有 {ov['avg_buy_hold_return_pct']:+.2f}%）")
        print(f"    平均 Sharpe 原始 {ov['avg_base_sharpe']:.2f}  →  "
              f"加閘門 {ov['avg_gated_sharpe']:.2f}")
        print(f"    平均最大回檔 原始 {ov['avg_base_max_dd_pct']:.2f}%  →  "
              f"加閘門 {ov['avg_gated_max_dd_pct']:.2f}%")
    print("=" * 72)
    for c in ev["caveats"]:
        print(f"  ※ {c}")


def save_evidence(ev: dict | None = None) -> Path:
    """產生（或沿用）檢定結果並寫入 reports/macro_evidence.json。排程與 CLI 共用。"""
    ev = build_evidence() if ev is None else ev
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "macro_evidence.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    return out


def main() -> None:
    ev = build_evidence()
    print_report(ev)
    out = save_evidence(ev)
    print(f"\n已儲存：reports/{out.name}")


if __name__ == "__main__":
    main()
