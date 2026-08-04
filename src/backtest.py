"""
backtest.py
把現有的 BULL/BEAR 訊號邏輯跑過歷史資料，計算每筆交易的損益與整體績效。

交易規則（訊號 signals[t] 用到第 t 根收盤，只有收盤後可知 → 依訊號的動作一律
         延到「下一根開盤」成交，買點與賣點都不偷看未來，無前視偏誤）：
  進場：訊號從「非 BULL」→「BULL」，於「隔天開盤」買入
  出場（同一根依時間先後判定）：
    1. 訊號：訊號從「非 BEAR」→「BEAR」，於「隔天開盤」賣出（與進場對稱）
    2. 停損：持倉期間（含進場當根）當天最低價 <= 進場價 * (1 + stop_loss)，以停損價出場
    3. 停利：持倉期間（含進場當根）當天最高價 >= 進場價 * (1 + take_profit)，以停利價出場
  （同一根：先看開盤的訊號出場；未觸發才看盤中停損→停利，兩者同根皆觸及取保守先停損。）

用法：
  python src/backtest.py                    # 預設 BTCUSDT
  python src/backtest.py ETHUSDT
  python src/backtest.py BTCUSDT -0.08 0.25 # 自訂停損 -8%、停利 +25%
"""

import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
INTERVAL = "1d"

# 與前端 signal_engine 共用同一套 6 因子計分（兩種執行方式都要能 import）：
#   python src/backtest.py      → sys.path[0] 是 src/，走 `from scoring`
#   from src.backtest import …  → 專案根在 path，走 `from src.scoring`
try:
    from src.scoring import score_row, signal_from_score
except ImportError:
    from scoring import score_row, signal_from_score


# ── 資料載入 ──────────────────────────────────────────────────────────
def load_indicators(symbol: str) -> pd.DataFrame:
    path = REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv"
    if not path.exists():
        sys.exit(f"找不到 {path}，請先執行：python src/indicators.py {symbol}")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── 訊號計算（與前端共用 src/scoring 的 6 因子計分）──────────────────
def _col(df, key):
    """取欄位的 numpy 陣列;欄位不存在則回傳全 NaN(視為缺值)。"""
    return df[key].to_numpy() if key in df.columns else np.full(len(df), np.nan)


def _num(v):
    """numpy 值 → float;NaN / 缺值回 None。"""
    return float(v) if (v is not None and v == v) else None


def compute_signals(df: pd.DataFrame, sentiment_by_date: dict = None) -> list[str]:
    """逐日計算訊號，回傳與 df 等長的訊號清單。
    sigs[i] = 第 i 天收盤後可得知的訊號（用第 i 天 vs 第 i-1 天資料計算）。
    進場條件：sigs[i-1]=='BULL' and sigs[i-2]!='BULL' → 第 i 天開盤買入（隔日開盤）。

    使用與前端「信心分數」完全相同的計分（src/scoring.score_row），
    確保回測驗證的策略 == 畫面上建議的策略（分數 ≥65 視為 BULL）。

    sentiment_by_date：可選 {'YYYY-MM-DD': 情緒分數 -100~100}。給了就把「當日
      情緒」當第 7 因子餵進 score_row（回測「技術 + 新聞」用）；不給則維持純
      6 因子、結果與原本完全相同。查無當日情緒的列 → news_score=None（不計分），
      且只用「當根 K 棒當日或更早」的分數，不會製造前視偏誤（look-ahead bias）。
    """
    n = len(df)
    if n == 0:
        return []
    # 一次取出所有欄位為 numpy 陣列,迴圈內用整數索引(不逐列 .iloc,快很多)
    rsi = _col(df, "RSI");   hist = _col(df, "HIST");  close = _col(df, "close")
    ma20 = _col(df, "MA20"); ma60 = _col(df, "MA60");  ma200 = _col(df, "MA200")
    vol = _col(df, "volume"); vma = _col(df, "VOL_MA20")
    bbu = _col(df, "BB_UPPER"); bbl = _col(df, "BB_LOWER")
    # 只有要疊情緒時才算日期字串（對齊每日情緒表的 key）
    dstr = None
    if sentiment_by_date:
        raw = df["date"].tolist()
        dstr = [d.date().isoformat() if hasattr(d, "date") else str(d)[:10] for d in raw]

    sigs = ["NEUTRAL"]  # index 0：第一天無前日資料，給預設 NEUTRAL
    for i in range(1, n):
        ns = sentiment_by_date.get(dstr[i]) if sentiment_by_date else None
        score, _ = score_row(
            _num(rsi[i]), _num(hist[i]), _num(hist[i - 1]),
            _num(close[i]), _num(ma20[i]), _num(ma60[i]), _num(ma200[i]),
            _num(vol[i]), _num(vma[i]), _num(bbu[i]), _num(bbl[i]),
            news_score=ns,
        )
        sigs.append(signal_from_score(score))
    return sigs


# ── 回測核心 ──────────────────────────────────────────────────────────
def run_backtest(df: pd.DataFrame,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20,
                 fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005,
                 signals: list[str] = None) -> list[dict]:
    """
    回傳交易明細清單，每筆包含：
      entry_date, exit_date, entry_price, exit_price,
      return_pct, hold_days, exit_reason

    ── 時序約定：無前視偏誤（look-ahead bias）────────────────────────────
    訊號 signals[t] 用到第 t 根的 close[t]/RSI[t]/HIST[t]…，只有「第 t 根收盤後」
    才可得知。因此所有「依訊號」的動作一律延到「下一根開盤」成交，進出場完全對稱：
        進場：signals[t] 首次轉 BULL → 第 t+1 根開盤買入
        出場：signals[t] 首次轉 BEAR → 第 t+1 根開盤賣出
    迴圈以「當前根 i」為準，看的是「前一根收盤」的訊號轉折（sig_prev / sig_prev2），
    成交在「第 i 根開盤」opens[i]，故買點與賣點都不會用到當根收盤的未來資訊。
    （修正前的舊版賣出用 signals[i] 卻成交在 opens[i]，等於拿當根收盤才知道的訊號、
      回頭用當根開盤價賣出 → 前視偏誤，會高估訊號出場的報酬。）

    停損 / 停利＝預先掛單，於「每一根（含進場當根）」盤中觸價即成交（非依訊號、無前視）。

    同一根的出場優先序（依當根時間先後）：
      1) 開盤：訊號出場（前一根收盤首次轉 BEAR）→ 以開盤價成交
      2) 盤中：停損（先）→ 停利（後）＝同根兩者皆觸及時取保守（先算停損）
    """
    signals = signals or compute_signals(df)
    # 一次取出價格欄位為陣列(不逐列 .iloc),日期保留為 Timestamp 清單
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows  = df["low"].to_numpy(dtype=float)
    dates = df["date"].tolist()
    trades = []
    position = None  # None = 空倉；dict = 持倉中

    def _record_exit(i: int, raw_exit_price: float, exit_reason: str) -> None:
        """以 raw 出場價結算目前持倉、寫入 trades、清空 position。"""
        nonlocal position
        ep_fill = position["entry_price"]                     # 進場價（已含滑價）
        fill_exit_price = raw_exit_price * (1 - slippage_rate)
        gross_ret = (raw_exit_price - position["entry_trigger_price"]) / position["entry_trigger_price"]
        net_ret = (fill_exit_price * (1 - fee_rate)) / (ep_fill * (1 + fee_rate)) - 1
        entry_dt = pd.Timestamp(position["entry_date"])
        exit_dt  = dates[i]
        # 統一為 tz-naive 才能相減
        if hasattr(exit_dt, "tz_convert"):
            exit_dt = exit_dt.tz_convert(None)
        trades.append({
            "entry_date":  position["entry_date"],
            "exit_date":   str(exit_dt.date()),
            # 價位存 8 位小數：低價幣（DOGE $0.07、SHIB…）4 位會失真、與原始開盤價對不上；
            # 損益本就用「未捨入」的價格計算，這裡只是讓「記錄的成交價」忠實可稽核。
            "entry_price": float(round(ep_fill, 8)),
            "exit_price":  float(round(fill_exit_price, 8)),
            "entry_trigger_price": float(round(position["entry_trigger_price"], 8)),
            "exit_trigger_price":  float(round(raw_exit_price, 8)),
            "gross_return_pct": float(round(gross_ret * 100, 3)),
            "return_pct":  float(round(net_ret * 100, 3)),
            "cost_pct":    float(round((gross_ret - net_ret) * 100, 3)),
            "hold_days":   int((exit_dt - entry_dt).days),
            "exit_reason": exit_reason,
            "profit":      bool(net_ret > 0),  # 明確轉成 Python bool
        })
        position = None

    for i in range(2, len(df)):
        sig_prev  = signals[i - 1]   # 前一根收盤訊號（第 i 根開盤前即可得知）
        sig_prev2 = signals[i - 2]
        o  = opens[i]
        lo = lows[i]
        hi = highs[i]
        lo_valid = lo == lo          # 非 NaN（nan==nan 為 False）
        hi_valid = hi == hi

        if position is None:
            # 進場：前一根收盤首次轉 BULL（前兩根非 BULL）→ 本根開盤買入
            if sig_prev == "BULL" and sig_prev2 != "BULL":
                if o != o or o <= 0:              # NaN 或非正值 → 不進場
                    continue
                position = {
                    "entry_date":  str(dates[i].date()),
                    "entry_price": float(o) * (1 + slippage_rate),
                    "entry_trigger_price": float(o),
                    "stop_price":  o * (1 + stop_loss),
                    "tp_price":    o * (1 + take_profit),
                }
                # 進場當根盤中也可能觸價（買在開盤，之後的盤中高低都算）：先停損後停利＝保守
                if lo_valid and lo <= position["stop_price"]:
                    _record_exit(i, position["stop_price"], "stop_loss")
                elif hi_valid and hi >= position["tp_price"]:
                    _record_exit(i, position["tp_price"], "take_profit")
        else:
            # 1) 開盤：訊號出場（前一根收盤首次轉 BEAR）— 與進場對稱、無前視
            if sig_prev == "BEAR" and sig_prev2 != "BEAR":
                _record_exit(i, float(o), "signal_exit")
            # 2) 盤中：停損（先）
            elif lo_valid and lo <= position["stop_price"]:
                _record_exit(i, position["stop_price"], "stop_loss")
            # 3) 盤中：停利（後）
            elif hi_valid and hi >= position["tp_price"]:
                _record_exit(i, position["tp_price"], "take_profit")

    return trades


# ── 績效指標計算 ──────────────────────────────────────────────────────
def _date_key(value) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(None)
    return str(stamp.date())


def _daily_mark_to_market(trades: list[dict], df: pd.DataFrame, include_curve=True):
    """Build a full-period daily strategy/cash equity curve.

    While a trade is open, capital is marked to the completed daily close. On
    the exit date the stored net trade return is applied exactly, preserving the
    fees/slippage already calculated by ``run_backtest``. Before entry and after
    exit the portfolio stays in cash.
    """
    ordered_df = df.sort_values("date").reset_index(drop=True).copy()
    if ordered_df.empty:
        return pd.Series(dtype=float), []

    dates = pd.to_datetime(ordered_df["date"])
    date_keys = dates.dt.strftime("%Y-%m-%d").to_numpy()
    date_to_index = {date: index for index, date in enumerate(date_keys)}
    closes_series = pd.to_numeric(ordered_df["close"], errors="coerce").ffill().bfill()
    closes = closes_series.to_numpy(dtype=float)
    if not np.isfinite(closes).any():
        closes = np.ones(len(ordered_df), dtype=float)

    equity_values = np.ones(len(ordered_df), dtype=float)
    in_position = np.zeros(len(ordered_df), dtype=bool)
    completion_events = np.zeros(len(ordered_df), dtype=int)
    cash = 1.0
    cursor = 0
    ordered_trades = sorted(
        trades,
        key=lambda trade: (_date_key(trade["entry_date"]), _date_key(trade["exit_date"])),
    )

    for trade in ordered_trades:
        entry_index = date_to_index.get(_date_key(trade["entry_date"]))
        exit_index = date_to_index.get(_date_key(trade["exit_date"]))
        if entry_index is None or exit_index is None:
            raise ValueError("trade date is outside the metric dataframe")
        if exit_index < entry_index or entry_index < cursor:
            raise ValueError("trades must be chronological and non-overlapping")

        equity_values[cursor:entry_index] = cash
        entry_price = float(trade["entry_price"])
        exit_price = float(trade.get("exit_price", 0.0) or 0.0)
        net_factor = max(0.0, 1.0 + float(trade["return_pct"]) / 100.0)
        inferred_fee = 0.0
        if entry_price > 0 and exit_price > 0:
            fee_ratio = net_factor * entry_price / exit_price
            if fee_ratio > 0:
                inferred_fee = float(
                    np.clip((1.0 - fee_ratio) / (1.0 + fee_ratio), 0.0, 0.1)
                )
        entry_basis = entry_price * (1.0 + inferred_fee)

        if exit_index > entry_index:
            if entry_basis > 0:
                equity_values[entry_index:exit_index] = (
                    cash * closes[entry_index:exit_index] / entry_basis
                )
            else:
                equity_values[entry_index:exit_index] = cash
            in_position[entry_index:exit_index] = True

        cash *= net_factor
        equity_values[exit_index] = cash
        completion_events[exit_index] += 1
        cursor = exit_index + 1

    equity_values[cursor:] = cash
    daily_equity = pd.Series(equity_values, index=dates, dtype=float)
    if not include_curve:
        return daily_equity, []

    first_close = float(closes[0]) if len(closes) and closes[0] > 0 else 1.0
    buy_hold = closes / first_close
    completed = np.cumsum(completion_events)
    curve = [
        {
            "trade": int(index),
            "equity": float(round(equity_values[index], 6)),
            "bh": float(round(buy_hold[index], 6)) if np.isfinite(buy_hold[index]) else None,
            "date": str(date_keys[index]),
            "completed_trades": int(completed[index]),
            "in_position": bool(in_position[index]),
        }
        for index in range(len(ordered_df))
    ]
    return daily_equity, curve


def compute_metrics(trades: list[dict], df: pd.DataFrame, include_curve: bool = True) -> dict:
    if not trades:
        return {"error": "無交易記錄，可能訊號條件太嚴格"}

    rets = [t["return_pct"] / 100 for t in trades]
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    win_rate     = len(wins) / len(rets) * 100
    avg_win      = float(np.mean(wins) * 100)   if wins   else 0.0
    avg_loss     = float(np.mean(losses) * 100) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0

    # Full-period daily mark-to-market equity, including cash-only days.
    daily_equity, equity_curve = _daily_mark_to_market(
        trades, df, include_curve=include_curve,
    )
    total_return = (float(daily_equity.iloc[-1]) - 1.0) * 100
    ordered_dates = pd.to_datetime(df["date"]).sort_values()
    years = (ordered_dates.iloc[-1] - ordered_dates.iloc[0]).days / 365.25
    if years <= 0:
        cagr = 0.0
    elif daily_equity.iloc[-1] <= 0:
        cagr = -100.0
    else:
        cagr = (float(daily_equity.iloc[-1]) ** (1.0 / years) - 1.0) * 100
    # Include the starting cash value so a first-day loss is not hidden merely
    # because there is no earlier dataframe observation.
    metric_equity = pd.Series(
        np.concatenate(([1.0], daily_equity.to_numpy(dtype=float))),
        dtype=float,
    )
    peaks = metric_equity.cummax()
    drawdown = (metric_equity - peaks) / peaks
    max_dd = float(drawdown.min() * 100)

    # Sharpe is based on daily changes in the marked equity curve.
    hold_days = [t["hold_days"] for t in trades]
    avg_hold  = float(np.mean(hold_days))
    daily_returns = metric_equity.pct_change(fill_method=None).dropna()
    daily_std = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    if len(daily_returns) > 1 and np.isfinite(daily_std) and daily_std > 0:
        sharpe = float(daily_returns.mean()) / daily_std * math.sqrt(365.0)
    else:
        sharpe = 0.0

    # Buy-and-hold uses the same complete dataframe period.
    bh_close = pd.to_numeric(df.sort_values("date")["close"], errors="coerce").ffill().bfill()
    bh_equity = bh_close / float(bh_close.iloc[0])
    bh_return = (float(bh_equity.iloc[-1]) - 1.0) * 100
    bh_peak = bh_equity.cummax()
    bh_dd = (bh_equity - bh_peak) / bh_peak
    bh_max_dd = float(bh_dd.min() * 100)

    # 買入持有的 Sharpe，用與策略 Sharpe 完全相同的算法，兩個數字才可直接對照。
    # 少了這根柱子，策略 Sharpe 0.08 會被讀成「還行」，而同期買入持有其實是 0.49。
    bh_daily = bh_equity.pct_change(fill_method=None).dropna()
    bh_std = float(bh_daily.std(ddof=1)) if len(bh_daily) > 1 else 0.0
    if len(bh_daily) > 1 and np.isfinite(bh_std) and bh_std > 0:
        bh_sharpe = float(bh_daily.mean()) / bh_std * math.sqrt(365.0)
    else:
        bh_sharpe = 0.0

    # 曝險比例＝實際持倉天數 / 期間總天數。策略多數時間空手時，「贏過大盤」
    # 有可能只是因為沒參與到下跌，而不是選時有效；沒有這個數字看不出差別。
    span_days = (ordered_dates.iloc[-1] - ordered_dates.iloc[0]).days
    exposure = min(100.0, sum(hold_days) / span_days * 100.0) if span_days > 0 else 0.0

    # 每筆報酬的 t 統計量：平均報酬是否顯著不為零（慣例 |t| > 2 才算有統計證據）。
    # 只看勝率與總報酬無法判斷樣本數夠不夠，交易次數少時很容易只是運氣。
    trade_rets = np.array([t["return_pct"] for t in trades], dtype=float)
    if len(trade_rets) > 1:
        tr_std = float(trade_rets.std(ddof=1))
        tstat = (float(trade_rets.mean()) / (tr_std / math.sqrt(len(trade_rets)))
                 if tr_std > 0 else 0.0)
    else:
        tstat = 0.0

    # 全部轉成 Python 原生型別，避免 FastAPI 序列化 numpy 類型失敗
    def f(v): return float(round(float(v), 4))

    return {
        "total_trades":        int(len(trades)),
        "win_rate":            f(win_rate),
        "avg_win_pct":         f(avg_win),
        "avg_loss_pct":        f(avg_loss),
        "profit_factor":       f(profit_factor),
        "total_return_pct":    f(total_return),
        "cagr_pct":            f(cagr),
        "max_drawdown_pct":    f(max_dd),
        "sharpe_ratio":        f(sharpe),
        "avg_hold_days":       f(avg_hold),
        "buy_hold_return_pct": f(bh_return),
        "buy_hold_max_drawdown_pct": f(bh_max_dd),
        "buy_hold_sharpe_ratio": f(bh_sharpe),
        "excess_return_pct":   f(total_return - bh_return),
        "exposure_pct":        f(exposure),
        "mean_trade_return_tstat": f(tstat),
        "avg_cost_pct":        f(float(np.mean([t.get("cost_pct", 0.0) for t in trades]))),
        "stop_loss_exits":     int(sum(1 for t in trades if t["exit_reason"] == "stop_loss")),
        "take_profit_exits":   int(sum(1 for t in trades if t["exit_reason"] == "take_profit")),
        "signal_exits":        int(sum(1 for t in trades if t["exit_reason"] == "signal_exit")),
        "equity_curve":        equity_curve,
    }


# ── 隨機進場基準（蒙地卡羅）──────────────────────────────────────────
def _build_non_overlapping_schedule_counts(durations, n_rows, opens, start_index=2):
    """Count every feasible ordered, non-overlapping schedule exactly.

    ``ways[k][cursor]`` is the number of schedules for trades ``k:`` when the
    next trade may start at or after ``cursor``. Invalid entry opens contribute
    zero schedules, so no rejection step can distort the target distribution.
    """
    durations = tuple(int(duration) for duration in durations)
    if not durations or any(duration < 0 for duration in durations):
        return None
    if n_rows <= start_index:
        return None

    open_values = np.asarray(opens, dtype=float)
    eligible = np.zeros(n_rows, dtype=bool)
    available = min(n_rows, len(open_values))
    eligible[:available] = np.isfinite(open_values[:available]) & (open_values[:available] > 0)

    n_trades = len(durations)
    ways = [[0] * (n_rows + 1) for _ in range(n_trades + 1)]
    ways[n_trades] = [1] * (n_rows + 1)

    for trade_index in range(n_trades - 1, -1, -1):
        length = durations[trade_index] + 1
        next_ways = ways[trade_index + 1]
        current = ways[trade_index]
        suffix_count = 0
        for start in range(n_rows - 1, -1, -1):
            if start + length <= n_rows and eligible[start]:
                suffix_count += next_ways[start + length]
            current[start] = suffix_count

    if ways[0][start_index] == 0:
        return None
    return {
        "durations": durations,
        "n_rows": int(n_rows),
        "start_index": int(start_index),
        "eligible": eligible,
        "ways": ways,
    }


def _rng_randbelow(rng, upper):
    """Exact uniform integer in ``[0, upper)`` for arbitrary-size counts."""
    upper = int(upper)
    if upper <= 0:
        raise ValueError("upper must be positive")
    if upper <= np.iinfo(np.int64).max:
        return int(rng.integers(0, upper))

    bit_count = upper.bit_length()
    word_count = (bit_count + 63) // 64
    mask = (1 << bit_count) - 1
    while True:
        candidate = 0
        for word_index in range(word_count):
            candidate |= int(rng.bit_generator.random_raw()) << (64 * word_index)
        candidate &= mask
        if candidate < upper:
            return candidate


def _sample_non_overlapping_schedule(schedule_counts, rng):
    """Sample one schedule uniformly from the exact DP counts."""
    durations = schedule_counts["durations"]
    n_rows = schedule_counts["n_rows"]
    eligible = schedule_counts["eligible"]
    ways = schedule_counts["ways"]
    cursor = schedule_counts["start_index"]
    starts = []

    for trade_index, duration in enumerate(durations):
        total = ways[trade_index][cursor]
        draw = _rng_randbelow(rng, total)
        length = duration + 1
        chosen = None
        for start in range(cursor, n_rows - length + 1):
            if not eligible[start]:
                continue
            completions = ways[trade_index + 1][start + length]
            if draw < completions:
                chosen = start
                break
            draw -= completions
        if chosen is None:
            raise RuntimeError("schedule count/sample mismatch")
        starts.append(chosen)
        cursor = chosen + length
    return starts


def _random_non_overlapping_starts(durations, n_rows, rng, opens, start_index=2):
    """Uniformly sample all feasible ordered, non-overlapping schedules."""
    schedule_counts = _build_non_overlapping_schedule_counts(
        durations, n_rows, opens, start_index=start_index,
    )
    if schedule_counts is None:
        return None
    return _sample_non_overlapping_schedule(schedule_counts, rng)


def random_entry_baseline(df: pd.DataFrame, trades: list[dict],
                          strategy_return_pct: float,
                          stop_loss: float = -0.06,
                          take_profit: float = 0.20,
                          fee_rate: float = 0.001,
                          slippage_rate: float = 0.0005,
                          n_sims: int = 500,
                          seed: int = 20260706) -> dict | None:
    """
    「隨機進場」基準：回答『策略的選時，有沒有贏過亂選日子？』

    設計（對照組只隨機化「進場日」，其餘與策略完全相同）：
      - 交易筆數 = 實際回測筆數；每筆持有上限 = 該筆實際持有的 K 棒數
      - 停損 / 停利觸價、手續費、滑價與 run_backtest 同一套數學
      - 進出場都以開盤價成交（進場含滑價、出場含滑價）
      - 隨機交易彼此不重疊，避免同一時間重複投入全部資本
      - 同日出場交易不丟棄；從進場棒起套用與正式策略相同的停損/停利順序
      - 固定亂數種子 → 結果可重現（公正性要求：任何人重跑數字相同）

    回傳 strategy_percentile = 策略總報酬在 n_sims 次隨機模擬中的百分位：
      ~50 代表選時與亂選無異（賺賠主要來自市場本身）；越高代表選時越可能有價值。
    回傳 None 表示無法計算（無交易或資料不足）。
    """
    if not trades or len(df) < 10:
        return None
    dates = [str(d.date()) if hasattr(d, "date") else str(d)[:10] for d in df["date"]]
    idx_of = {d: i for i, d in enumerate(dates)}
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows  = df["low"].to_numpy(dtype=float)
    n = len(df)

    # 每筆實際持有的 K 棒數（進場列 → 出場列）；對不上日期的交易略過
    trade_specs = []
    for t in trades:
        i = idx_of.get(str(t["entry_date"])[:10])
        j = idx_of.get(str(t["exit_date"])[:10])
        if i is not None and j is not None and j >= i:
            trade_specs.append((j - i, str(t.get("exit_reason", "signal_exit"))))
    if len(trade_specs) != len(trades):
        return None
    durations = [duration for duration, _ in trade_specs]
    schedule_counts = _build_non_overlapping_schedule_counts(durations, n, opens)
    if schedule_counts is None:
        return None

    rng = np.random.default_rng(seed)
    totals = np.empty(n_sims)
    for s in range(n_sims):
        eq = 1.0
        starts = _sample_non_overlapping_schedule(schedule_counts, rng)
        for i, (d, exit_reason) in zip(starts, trade_specs):
            ep = opens[i]
            fill_entry = ep * (1 + slippage_rate)
            stop_price = ep * (1 + stop_loss)
            tp_price   = ep * (1 + take_profit)
            raw_exit = None
            # Include the entry bar. For a scheduled exit, the final bar exits
            # at its open before intraday stop/take-profit checks. A zero-day
            # trade still checks its entry bar, matching ``run_backtest``.
            if d == 0:
                risk_bars = (i,)
            elif exit_reason == "signal_exit":
                risk_bars = range(i, i + d)
            else:
                risk_bars = range(i, i + d + 1)
            for k in risk_bars:
                lo = lows[k]  if lows[k]  == lows[k]  else ep
                hg = highs[k] if highs[k] == highs[k] else ep
                if lo <= stop_price:
                    raw_exit = stop_price
                    break
                if hg >= tp_price:
                    raw_exit = tp_price
                    break
            if raw_exit is None:               # 未觸價 → 持有期滿以開盤價出場
                planned_exit = opens[i + d]
                raw_exit = planned_exit if np.isfinite(planned_exit) and planned_exit > 0 else 0.0
            fill_exit = raw_exit * (1 - slippage_rate)
            eq *= (fill_exit * (1 - fee_rate)) / (fill_entry * (1 + fee_rate))
        totals[s] = (eq - 1) * 100

    below = float((totals < strategy_return_pct).sum())
    equal = float((totals == strategy_return_pct).sum())
    percentile = (below + 0.5 * equal) / n_sims * 100
    return {
        "n_sims":              int(n_sims),
        "n_trades":            len(durations),
        "median_return_pct":   float(round(np.median(totals), 2)),
        "p05_return_pct":      float(round(np.percentile(totals, 5), 2)),
        "p95_return_pct":      float(round(np.percentile(totals, 95), 2)),
        "strategy_return_pct": float(round(strategy_return_pct, 2)),
        "strategy_percentile": float(round(percentile, 1)),
    }


def split_dataframe(df: pd.DataFrame, train_ratio: float = 0.60) -> tuple[pd.DataFrame, pd.DataFrame]:
    """依時間順序切成 in-sample / out-of-sample，不打亂資料。"""
    if df.empty:
        return df.copy(), df.copy()
    split_idx = max(1, min(len(df) - 1, int(len(df) * train_ratio)))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


def run_backtest_report(df: pd.DataFrame,
                        stop_loss: float = -0.06,
                        take_profit: float = 0.20,
                        fee_rate: float = 0.001,
                        slippage_rate: float = 0.0005,
                        signals: list[str] = None,
                        include_curve: bool = False) -> dict:
    trades = run_backtest(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )
    metrics = compute_metrics(trades, df, include_curve=include_curve)
    return {"trades": trades, "metrics": metrics}


def walk_forward_split_report(df: pd.DataFrame,
                              stop_loss: float = -0.06,
                              take_profit: float = 0.20,
                              fee_rate: float = 0.001,
                              slippage_rate: float = 0.0005,
                              train_ratio: float = 0.60) -> dict:
    train_df, test_df = split_dataframe(df, train_ratio=train_ratio)
    train = run_backtest_report(
        train_df,
        stop_loss,
        take_profit,
        fee_rate,
        slippage_rate,
        signals=compute_signals(train_df),
        include_curve=False,
    )
    test = run_backtest_report(
        test_df,
        stop_loss,
        take_profit,
        fee_rate,
        slippage_rate,
        signals=compute_signals(test_df),
        include_curve=False,
    )

    def compact(metrics: dict) -> dict:
        return {k: v for k, v in metrics.items() if k != "equity_curve"}

    return {
        "train_ratio": train_ratio,
        "in_sample": {
            "period": {
                "start": str(train_df["date"].min().date()),
                "end": str(train_df["date"].max().date()),
            },
            "metrics": compact(train["metrics"]),
        },
        "out_of_sample": {
            "period": {
                "start": str(test_df["date"].min().date()),
                "end": str(test_df["date"].max().date()),
            },
            "metrics": compact(test["metrics"]),
        },
    }


def parameter_sweep(df: pd.DataFrame,
                    stop_losses: list[float] = None,
                    take_profits: list[float] = None,
                    fee_rate: float = 0.001,
                    slippage_rate: float = 0.0005,
                    signals: list[str] = None) -> list[dict]:
    stop_losses = stop_losses or [-0.03, -0.05, -0.06, -0.08, -0.10]
    take_profits = take_profits or [0.10, 0.15, 0.20, 0.25, 0.30]
    rows = []
    # 訊號只與指標有關、與停損停利無關 → 整個掃描共用同一份(可由外部傳入避免重算)
    signals = signals or compute_signals(df)
    for stop_loss in stop_losses:
        for take_profit in take_profits:
            report = run_backtest_report(
                df,
                stop_loss=stop_loss,
                take_profit=take_profit,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
                signals=signals,
                include_curve=False,
            )
            metrics = report["metrics"]
            if "error" in metrics:
                continue
            rows.append({
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "total_trades": metrics["total_trades"],
                "total_return_pct": metrics["total_return_pct"],
                "buy_hold_return_pct": metrics["buy_hold_return_pct"],
                "excess_return_pct": metrics["excess_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "profit_factor": metrics["profit_factor"],
                "win_rate": metrics["win_rate"],
            })
    return sorted(rows, key=lambda r: (r["sharpe_ratio"], r["excess_return_pct"]), reverse=True)


# ── CLI 報告輸出 ──────────────────────────────────────────────────────
def print_report(symbol: str, metrics: dict, trades: list[dict], df: pd.DataFrame):
    if "error" in metrics:
        print(f"\n[ERROR] {metrics['error']}")
        return

    sep = "=" * 58
    print(f"\n{sep}")
    print(f"  {symbol} Backtest Report")
    print(f"  Period : {df['date'].min().date()} ~ {df['date'].max().date()}")
    print(sep)
    print(f"  Total Trades      : {metrics['total_trades']}")
    print(f"  Win Rate          : {metrics['win_rate']}%")
    print(f"  Avg Win           : +{metrics['avg_win_pct']}%")
    print(f"  Avg Loss          : {metrics['avg_loss_pct']}%")
    print(f"  Profit Factor     : {metrics['profit_factor']}  (>1 = overall profitable)")
    print(f"{'-'*58}")
    print(f"  Total Return      : {metrics['total_return_pct']:+.2f}%")
    print(f"  CAGR              : {metrics['cagr_pct']:+.2f}%")
    print(f"  Max Drawdown      : {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio      : {metrics['sharpe_ratio']}")
    print(f"  Avg Hold Days     : {metrics['avg_hold_days']} days")
    print(f"{'-'*58}")
    print(f"  Buy & Hold Return : {metrics['buy_hold_return_pct']:+.2f}%  (benchmark)")
    print(f"{'-'*58}")
    print(f"  Exits: stop_loss {metrics['stop_loss_exits']} / "
          f"take_profit {metrics['take_profit_exits']} / "
          f"signal {metrics['signal_exits']}")
    print(f"{sep}")

    print(f"\nLast 5 Trades (for manual verification):")
    print(f"{'#':<4} {'Entry':<12} {'Exit':<12} {'EntryPx':>12} {'ExitPx':>12} "
          f"{'Ret%':>8} {'Days':>5} Result  Reason")
    print("-" * 80)
    for n, t in enumerate(trades[-5:], start=len(trades) - 4):
        flag = "WIN " if t["profit"] else "LOSS"
        print(f"{n:<3} {t['entry_date']:<12} {t['exit_date']:<12} "
              f"{t['entry_price']:>12,.2f} {t['exit_price']:>12,.2f} "
              f"{t['return_pct']:>+7.2f}% {t['hold_days']:>4}d "
              f"{flag} {t['exit_reason']}")


def regenerate_reports(symbols: list[str] = None) -> int:
    """
    重產 reports/backtest_trades_*.csv 與 backtest_metrics_*.json 靜態報表。

    與即時 API（backtest_engine.get_backtest）走完全相同的 load_indicators / run_backtest /
    compute_metrics（皆用預設停損停利），因此重產後「靜態報表 == API 結果」，
    也讓 verify_backtest.py 對得起來（修 #111 / #116 的報表漂移）。

    symbols 不給 → 掃 reports/ 內所有 indicators_*_1d.csv 的幣種。回傳成功處理的幣數。
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if symbols is None:
        symbols = sorted(
            p.stem.replace("indicators_", "").replace(f"_{INTERVAL}", "")
            for p in REPORT_DIR.glob(f"indicators_*_{INTERVAL}.csv")
        )
    done = 0
    for sym in symbols:
        try:
            df = load_indicators(sym)
            trades = run_backtest(df)
            metrics = compute_metrics(trades, df, include_curve=False)
            pd.DataFrame(trades).to_csv(
                REPORT_DIR / f"backtest_trades_{sym}_{INTERVAL}.csv", index=False)
            metrics_out = {k: v for k, v in metrics.items() if k != "equity_curve"}
            with open(REPORT_DIR / f"backtest_metrics_{sym}_{INTERVAL}.json",
                      "w", encoding="utf-8") as f:
                json.dump(metrics_out, f, indent=2, ensure_ascii=False)
            done += 1
        except SystemExit:
            continue  # load_indicators 找不到該幣指標檔（理論上不會，因幣種取自現有檔）
        except Exception as e:
            print(f"[reports] {sym} 重產失敗：{e}")
            continue
    return done


def main():
    args = sys.argv[1:]
    symbol     = args[0].upper() if args else "BTCUSDT"
    stop_loss  = float(args[1]) if len(args) > 1 else -0.06
    take_profit= float(args[2]) if len(args) > 2 else 0.20

    df     = load_indicators(symbol)
    trades = run_backtest(df, stop_loss=stop_loss, take_profit=take_profit)
    metrics= compute_metrics(trades, df, include_curve=False)

    print_report(symbol, metrics, trades, df)

    # 儲存交易明細與指標 JSON
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(
        REPORT_DIR / f"backtest_trades_{symbol}_{INTERVAL}.csv", index=False)

    metrics_out = {k: v for k, v in metrics.items() if k != "equity_curve"}
    with open(REPORT_DIR / f"backtest_metrics_{symbol}_{INTERVAL}.json",
              "w", encoding="utf-8") as f:
        json.dump(metrics_out, f, indent=2, ensure_ascii=False)

    print(f"\n已儲存：reports/backtest_trades_{symbol}_{INTERVAL}.csv")
    print(f"已儲存：reports/backtest_metrics_{symbol}_{INTERVAL}.json")


if __name__ == "__main__":
    main()
