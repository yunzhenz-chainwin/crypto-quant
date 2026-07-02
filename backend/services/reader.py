"""
reader.py — 前台資料讀取層（單一資料來源：SQLite）

資料來源：data/app.db 的 prices / indicators 表。
（2026-07 起由「讀 CSV」改為「讀 DB」，前後台統一資料來源；CSV 仍由每日排程
 產出，退居中繼／備援，不再是前台的讀取來源。）

為什麼要對映欄位名：
  DB 存的是小寫欄名 + `ts`（例如 ma20、rsi、hist、ts），但前端圖表與 src/scoring
  沿用舊 CSV 的大寫欄名（MA20、RSI、HIST、date）。因此所有查詢一律用 SQL alias
  把欄名還原成前端既有的大寫 / date，確保「換資料來源、但回傳形狀 100% 不變」，
  前端與訊號引擎零改動。

為什麼 indicators 要 JOIN prices：
  indicators 表只存指標欄（close + 各指標），沒有 open/high/low/volume；
  舊的 reports CSV 卻含這些欄。故 load_indicators 以 (symbol, interval, ts) JOIN
  prices 表補回 OHLCV，維持與舊 CSV 相同的 16 欄輸出。

日期範圍語意：沿用舊版「end 往後含一天」的邊界行為（見 _range_clause），
  確保與改動前輸出逐列一致，是可驗證的等價替換、非行為變更。
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

ROOT    = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "app.db"
INTERVAL = "1d"
VALID_INTERVALS = ("1d", "1h")

# 每個週期一天有幾根 K 棒：API 的 days 參數語意固定是「天」，
# 小時線取最近 N 天時 LIMIT 要乘上 24（見 _bars_per_day 用法）。
_BARS_PER_DAY = {"1d": 1, "1h": 24}

# ts 欄輸出格式：日線沿用舊的 YYYY-MM-DD（前端相容）；小時線帶完整時間。
def _date_expr(interval: str, tscol: str = "ts") -> str:
    return f"substr({tscol},1,10)" if interval == "1d" else f"substr({tscol},1,19)"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _range_clause(days: int | None, start: str | None, end: str | None,
                  tscol: str = "ts", interval: str = "1d") -> tuple[str, list, bool]:
    """
    依 days / start / end 產生時間篩選 SQL 片段。
    回傳 (sql_tail, params, reverse)：
      - start/end：範圍過濾，升冪；end 用 date(?, '+1 day') 沿用舊版含界行為。
      - days     ：取最近 N 天 → DESC LIMIT（小時線一天 24 根，LIMIT 乘 24），
                   呼叫端需再反轉回升冪（reverse=True）。
      - 皆無     ：全部，升冪。
    tscol 讓 load_indicators 能指定用 i.ts（JOIN 後需限定表別名）。
    """
    if start or end:
        tail, params = "", []
        if start:
            tail += f" AND date({tscol}) >= date(?)"; params.append(start)
        if end:
            tail += f" AND date({tscol}) <= date(?, '+1 day')"; params.append(end)
        return tail + f" ORDER BY {tscol}", params, False
    if days:
        bars = days * _BARS_PER_DAY.get(interval, 1)
        return f" ORDER BY {tscol} DESC LIMIT ?", [bars], True
    return f" ORDER BY {tscol}", [], False


def available_symbols(interval: str = INTERVAL) -> list[str]:
    # 只回傳「設定啟用 + DB 有資料」的幣種:啟用清單(app_config 的 coins)為單一來源,
    # 已停用的幣即使 DB 仍有歷史也不顯示(例如已停止交易、換代號的 MATIC)。
    from backend.services.app_db import get_enabled_symbols
    with _connect() as conn:
        have = {r["symbol"] for r in conn.execute(
            "SELECT DISTINCT symbol FROM prices WHERE interval=?", (interval,)).fetchall()}
    return sorted(s for s in get_enabled_symbols() if s in have)


def intervals_available() -> dict:
    """各週期有資料的幣種清單，例如 {"1d": [...15 幣...], "1h": ["BTCUSDT","ETHUSDT"]}。"""
    return {iv: available_symbols(iv) for iv in VALID_INTERVALS}


def data_versions() -> dict:
    """各週期最新一根 K 棒的時間戳（前端輪詢比對「資料有沒有變」用，很便宜）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT interval, MAX(ts) AS m, COUNT(*) AS n FROM prices GROUP BY interval"
        ).fetchall()
    return {r["interval"]: f'{r["m"]}#{r["n"]}' for r in rows}


def load_prices(symbol: str, days: int = None,
                start: str = None, end: str = None,
                interval: str = INTERVAL) -> list[dict]:
    tail, rparams, reverse = _range_clause(days, start, end, tscol="ts", interval=interval)
    sql = (
        f"SELECT {_date_expr(interval)} AS date, open, high, low, close, volume "
        "FROM prices WHERE symbol=? AND interval=?" + tail
    )
    with _connect() as conn:
        rows = conn.execute(sql, [symbol, interval, *rparams]).fetchall()
    if reverse:
        rows = rows[::-1]           # DESC LIMIT 取最近 N 筆後，反轉回升冪
    return [dict(r) for r in rows]


def load_indicators(symbol: str, days: int = None,
                    start: str = None, end: str = None,
                    interval: str = INTERVAL) -> list[dict]:
    tail, rparams, reverse = _range_clause(days, start, end, tscol="i.ts", interval=interval)
    # indicators 只有指標欄 → JOIN prices 補 open/high/low/volume；
    # 欄名一律 alias 回舊 CSV 的大寫，close 取自 prices（與 indicators 同一根 K 棒，值相同）。
    sql = (
        f"SELECT {_date_expr(interval, 'i.ts')} AS date, p.open, p.high, p.low, p.close, p.volume, "
        "i.ma20 AS MA20, i.ma60 AS MA60, i.ma200 AS MA200, i.rsi AS RSI, "
        "i.macd AS MACD, i.signal AS SIGNAL, i.hist AS HIST, "
        "i.bb_upper AS BB_UPPER, i.bb_lower AS BB_LOWER, i.vol_ma20 AS VOL_MA20 "
        "FROM indicators i "
        "JOIN prices p ON p.symbol=i.symbol AND p.interval=i.interval AND p.ts=i.ts "
        "WHERE i.symbol=? AND i.interval=?" + tail
    )
    with _connect() as conn:
        rows = conn.execute(sql, [symbol, interval, *rparams]).fetchall()
    if reverse:
        rows = rows[::-1]
    # DB 的 NULL → Python None（缺值如暖身期 MA200），與舊版 NaN→None 語意一致
    return [dict(r) for r in rows]


def load_correlation() -> dict:
    # 逐幣取 close 序列（以日期字串為索引；ISO 日期字串排序即時間序），
    # 沿用舊版：以 available_symbols() 順序建 dict，確保相關性矩陣欄位順序一致。
    closes = {}
    with _connect() as conn:
        for sym in available_symbols():
            rows = conn.execute(
                "SELECT substr(ts,1,10) AS date, close FROM prices "
                "WHERE symbol=? AND interval=? ORDER BY ts",
                (sym, INTERVAL),
            ).fetchall()
            closes[sym.replace("USDT", "")] = pd.Series(
                {r["date"]: r["close"] for r in rows}
            )

    wide = pd.DataFrame(closes).dropna()
    returns = wide.pct_change().dropna()
    corr = returns.corr().round(4)
    vol = (returns.std() * np.sqrt(365) * 100).round(2)

    return {
        "symbols": list(corr.columns),
        "matrix": corr.values.tolist(),
        "volatility": vol.to_dict(),
        "period": {
            "start": str(wide.index.min()),
            "end": str(wide.index.max()),
            "days": len(wide),
        },
    }


def last_updated() -> dict:
    # 與 available_symbols() 一致:只回傳「啟用中」的幣種(不含已停用的 MATIC 等)
    avail = set(available_symbols())
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol, substr(MAX(ts),1,10) AS d FROM prices "
            "WHERE interval=? GROUP BY symbol ORDER BY symbol",
            (INTERVAL,),
        ).fetchall()
    return {r["symbol"]: r["d"] for r in rows if r["symbol"] in avail}


def load_signal_history(symbol: str, days: int = None,
                        start: str = None, end: str = None) -> list[dict]:
    """
    信心分數歷史(每日多空訊號 + 0~100 分數),供前台走勢圖。
    來源:daily_signal 表(排程 backfill_daily_signals 用歷史指標逐日重算填入)。
    date 欄本身即 'YYYY-MM-DD',故時間篩選直接用 date 欄。
    """
    tail, rparams, reverse = _range_clause(days, start, end, tscol="date")
    sql = "SELECT date, signal, score, close, rsi FROM daily_signal WHERE symbol=?" + tail
    with _connect() as conn:
        rows = conn.execute(sql, [symbol, *rparams]).fetchall()
    if reverse:
        rows = rows[::-1]
    return [dict(r) for r in rows]


def load_fear_greed_history(days: int = None,
                            start: str = None, end: str = None) -> list[dict]:
    """
    恐懼貪婪指數歷史(0=極度恐慌,100=極度貪婪),全市場單一序列。
    來源:fear_greed 表(排程從 alternative.me 回補,可追溯至 2018)。
    """
    tail, rparams, reverse = _range_clause(days, start, end, tscol="date")
    sql = "SELECT date, value, label FROM fear_greed WHERE 1=1" + tail
    with _connect() as conn:
        rows = conn.execute(sql, rparams).fetchall()
    if reverse:
        rows = rows[::-1]
    return [dict(r) for r in rows]
