# -*- coding: utf-8 -*-
"""Defensive cross-sectional momentum strategy.

The live recommendation and historical backtest deliberately share the same
rebalance calendar and target-weight function.  A recommendation therefore
describes the strategy that produced the displayed performance, rather than a
separate daily re-ranking rule.
"""

from pathlib import Path

import numpy as np
import pandas as pd

try:
    from src.cross_sectional import realized_holding_returns, max_drawdown_from_returns
except ImportError:
    from cross_sectional import realized_holding_returns, max_drawdown_from_returns


ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
L, K, R = 30, 5, 10
REGIME_N, VOLWIN = 100, 20
TARGET_VOL, COST = 0.30, 0.0015
ANN = np.sqrt(365.0)
SKIP = 200


def load_panels():
    closes, opens = {}, {}
    for path in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        symbol = path.stem.replace(f"_{INTERVAL}", "")
        frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
        indexed = frame.set_index("date")
        closes[symbol] = indexed["close"].astype(float)
        opens[symbol] = indexed["open"].astype(float)

    close_panel = pd.DataFrame(closes).sort_index()
    # Do not let a longer, inactive series extend the strategy past BTC's data.
    last_btc = close_panel["BTCUSDT"].last_valid_index() if "BTCUSDT" in close_panel else None
    if last_btc is not None:
        close_panel = close_panel.loc[:last_btc]
    open_panel = pd.DataFrame(opens).sort_index().reindex(close_panel.index)
    return close_panel, open_panel


def _momentum_at(close_panel: pd.DataFrame, decision_index: int) -> pd.Series:
    if decision_index < L or decision_index >= len(close_panel):
        return pd.Series(dtype=float)
    momentum = close_panel.iloc[decision_index] / close_panel.iloc[decision_index - L] - 1.0
    return momentum.replace([np.inf, -np.inf], np.nan).dropna()


def _target_weights(close_panel: pd.DataFrame, decision_index: int):
    """Return point-in-time target weights and auditable decision details."""
    coins = list(close_panel.columns)
    weights = pd.Series(0.0, index=coins, dtype=float)
    details = {
        "risk_on": False,
        "reason": "insufficient_history",
        "btc_price": None,
        "btc_ma": None,
        "momentum": pd.Series(dtype=float),
        "topk": [],
        "exposure": 0.0,
    }
    if "BTCUSDT" not in close_panel or decision_index < 0 or decision_index >= len(close_panel):
        return weights, details

    btc = close_panel["BTCUSDT"]
    btc_ma = btc.rolling(REGIME_N).mean()
    btc_price = btc.iloc[decision_index]
    ma_price = btc_ma.iloc[decision_index]
    details["btc_price"] = float(btc_price) if pd.notna(btc_price) else None
    details["btc_ma"] = float(ma_price) if pd.notna(ma_price) else None
    if pd.isna(btc_price) or pd.isna(ma_price) or not (btc_price > ma_price):
        details["reason"] = "btc_below_regime_ma"
        return weights, details

    details["risk_on"] = True
    momentum = _momentum_at(close_panel, decision_index)
    details["momentum"] = momentum
    if len(momentum) < 6:
        details["reason"] = "insufficient_universe"
        return weights, details

    topk = list(momentum.sort_values(ascending=False).head(K).index)
    daily_returns = close_panel.pct_change(fill_method=None)
    window = daily_returns[topk].iloc[max(0, decision_index - VOLWIN + 1):decision_index + 1]
    basket = window.mul(1.0 / len(topk)).sum(axis=1, min_count=1)
    basket_vol = float(basket.std() * ANN)
    exposure = min(1.0, TARGET_VOL / basket_vol) if np.isfinite(basket_vol) and basket_vol > 0 else 0.0
    for coin in topk:
        weights[coin] = exposure / len(topk)

    details.update({
        "reason": "risk_on" if exposure > 0 else "invalid_volatility",
        "topk": topk,
        "exposure": exposure,
    })
    return weights, details


def _latest_rebalance_index(n_rows: int):
    latest = n_rows - 1
    if latest < SKIP:
        return None
    return SKIP + ((latest - SKIP) // R) * R


def today_signal(close_panel, open_panel):
    """Describe holdings from the latest R-bar rebalance, not a daily re-rank."""
    if close_panel.empty:
        return {
            "date": None,
            "data_as_of": None,
            "rebalance_date": None,
            "effective_from": None,
            "pending_rebalance": False,
            "execution_status": "not_available",
            "unfilled_symbols": [],
            "regime": "cash",
            "regime_reason": "沒有可用資料",
            "target_exposure_pct": 0,
            "exposure_pct": 0,
            "cash_pct": 100,
            "picks": [],
            "note": "資料不足，維持現金",
        }

    latest_index = len(close_panel) - 1
    decision_index = _latest_rebalance_index(len(close_panel))
    data_as_of = str(close_panel.index[latest_index])[:10]
    if decision_index is None:
        return {
            "date": data_as_of,
            "data_as_of": data_as_of,
            "rebalance_date": None,
            "effective_from": None,
            "pending_rebalance": False,
            "execution_status": "not_available",
            "unfilled_symbols": [],
            "next_rebalance_in_bars": None,
            "regime": "cash",
            "regime_reason": f"至少需要 {SKIP + 1} 根完成 K 棒",
            "target_exposure_pct": 0,
            "exposure_pct": 0,
            "cash_pct": 100,
            "picks": [],
            "note": "歷史資料不足，維持現金",
        }

    target_weights, details = _target_weights(close_panel, decision_index)
    rebalance_date = str(close_panel.index[decision_index])[:10]
    pending_rebalance = decision_index == latest_index
    effective_from = (
        "next_open" if pending_rebalance
        else str(close_panel.index[decision_index + 1])[:10]
    )
    if pending_rebalance:
        # The next open is not known yet: publish the intended order, without
        # pretending that it has filled.
        displayed_weights = target_weights.copy()
        unfilled_symbols = []
        execution_status = "pending_next_open"
    else:
        # Once the entry bar is known, mirror the backtest execution rule. A
        # missing/non-positive entry open leaves that target weight in cash.
        entry = pd.to_numeric(open_panel.iloc[decision_index + 1], errors="coerce")
        executable = entry.notna() & np.isfinite(entry) & (entry > 0)
        displayed_weights = target_weights.where(executable, 0.0)
        unfilled_symbols = [
            coin for coin in details["topk"]
            if target_weights.get(coin, 0.0) > 0 and not bool(executable.get(coin, False))
        ]
        if unfilled_symbols:
            execution_status = (
                "unfilled" if float(displayed_weights.sum()) == 0.0 else "partially_filled"
            )
        else:
            execution_status = "executed"

    momentum = details["momentum"]
    picks = []
    for coin in details["topk"]:
        weight = float(displayed_weights.get(coin, 0.0))
        if weight <= 0:
            continue
        picks.append({
            "symbol": coin.replace("USDT", ""),
            "momentum": round(float(momentum[coin]) * 100, 1),
            "weight": round(weight * 100, 1),
        })

    target_exposure = float(target_weights.sum())
    exposure = float(displayed_weights.sum())
    btc_price = details["btc_price"]
    ma_price = details["btc_ma"]
    if details["risk_on"]:
        reason = (
            f"BTC {btc_price:,.0f} > {REGIME_N} 日均線 {ma_price:,.0f}；"
            f"依 {R} 日換倉節奏沿用 {rebalance_date} 的決策"
        )
    elif btc_price is not None and ma_price is not None:
        reason = (
            f"BTC {btc_price:,.0f} <= {REGIME_N} 日均線 {ma_price:,.0f}；"
            f"依 {R} 日換倉節奏維持現金"
        )
    else:
        reason = "均線或可投資標的資料不足"

    return {
        "date": rebalance_date,
        "data_as_of": data_as_of,
        "rebalance_date": rebalance_date,
        "effective_from": effective_from,
        "pending_rebalance": pending_rebalance,
        "execution_status": execution_status,
        "unfilled_symbols": [coin.replace("USDT", "") for coin in unfilled_symbols],
        "next_rebalance_in_bars": R - (latest_index - decision_index),
        "regime": "invested" if exposure > 0 else "cash",
        "regime_reason": reason,
        "target_exposure_pct": round(target_exposure * 100),
        "exposure_pct": round(exposure * 100),
        "cash_pct": round((1.0 - exposure) * 100),
        "picks": picks,
        "note": (
            (
                f"下一根開盤執行；目標投入 {round(exposure * 100)}%"
                if pending_rebalance
                else f"持有至下一個 {R} 日換倉點；目標投入 {round(exposure * 100)}%"
            )
            if exposure > 0
            else (
                "目標標的在換倉開盤缺價，未成交權重保留為現金"
                if unfilled_symbols else "本換倉週期維持現金"
            )
        ),
    }


def _backtest(close_panel, open_panel):
    coins = list(close_panel.columns)
    previous_weights = pd.Series(0.0, index=coins, dtype=float)
    strategy_returns, benchmark_returns, periods = [], [], []
    decision_index = SKIP

    while decision_index + 1 + R < len(close_panel):
        target_weights, _ = _target_weights(close_panel, decision_index)
        entry = open_panel.iloc[decision_index + 1]
        exit_ = open_panel.iloc[decision_index + 1 + R]
        coin_returns = realized_holding_returns(entry, exit_)

        # Ranking was already completed with decision-date information.  An
        # unavailable next-open quote simply leaves that intended weight in cash.
        executed_weights = target_weights.where(coin_returns.notna(), 0.0)
        turnover = float((executed_weights - previous_weights).abs().sum())
        gross_portfolio_return = float(
            (executed_weights * coin_returns.reindex(coins).fillna(0.0)).sum()
        )
        portfolio_return = max(-1.0, gross_portfolio_return - COST * turnover)
        benchmark_return = (
            float(coin_returns.dropna().mean()) if coin_returns.notna().any() else 0.0
        )

        strategy_returns.append(portfolio_return)
        benchmark_returns.append(benchmark_return)
        periods.append(close_panel.index[decision_index])
        previous_weights = executed_weights
        decision_index += R

    return (
        pd.Series(strategy_returns, index=periods, dtype=float),
        pd.Series(benchmark_returns, index=periods, dtype=float),
    )


def _perf(returns):
    if len(returns) == 0:
        return {"cagr": 0, "mdd": 0, "sharpe": 0}
    equity = (1 + returns).cumprod()
    years = len(returns) * R / 365.0
    cagr = (float(equity.iloc[-1]) ** (1 / years) - 1) * 100 if years > 0.3 else 0.0
    max_drawdown = max_drawdown_from_returns(returns)
    sharpe = (
        float(returns.mean() / returns.std() * np.sqrt(365.0 / R))
        if returns.std() > 0 else 0.0
    )
    return {"cagr": cagr, "mdd": max_drawdown, "sharpe": sharpe}


def strategy_metrics(close_panel, open_panel):
    strategy, benchmark = _backtest(close_panel, open_panel)
    split = int(len(strategy) * 0.6)
    full = _perf(strategy)
    out_of_sample = _perf(strategy.iloc[split:])
    market = _perf(benchmark)
    return {
        "as_of": str(close_panel.index[-1])[:10],
        "cagr": round(full["cagr"], 1),
        "mdd": round(full["mdd"], 1),
        "sharpe": round(full["sharpe"], 2),
        "oos_cagr": round(out_of_sample["cagr"], 1),
        "oos_mdd": round(out_of_sample["mdd"], 1),
        "oos_sharpe": round(out_of_sample["sharpe"], 2),
        "market_cagr": round(market["cagr"], 1),
    }


_CACHE: dict = {}


def _version():
    return max((path.stat().st_mtime for path in CLEAN.glob(f"*_{INTERVAL}.csv")), default=0.0)


def cached_strategy():
    version = _version()
    if _CACHE.get("ver") != version:
        close_panel, open_panel = load_panels()
        _CACHE["ver"] = version
        _CACHE["data"] = {
            "strategy": "防守型動量：30 日動量 + BTC 100 日均線 + top5 + 30% 波動目標",
            "today": today_signal(close_panel, open_panel),
            "perf": strategy_metrics(close_panel, open_panel),
        }
    return _CACHE["data"]


if __name__ == "__main__":
    import json

    print(json.dumps(cached_strategy(), ensure_ascii=False, indent=2))
