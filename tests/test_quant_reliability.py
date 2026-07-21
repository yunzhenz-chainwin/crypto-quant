"""Regression tests for point-in-time and performance-measurement guarantees."""

import numpy as np
import pandas as pd
import pytest

from src import backtest as single_asset
from src import cross_sectional as cross
from src import cross_sectional_hardened as hardened
from src import cross_sectional_regime as regime
from src import cross_sectional_robust as robust
from src import cross_sectional_validate as validate
from src import momentum_signal as momentum


def _panels():
    dates = pd.date_range("2025-01-01", periods=8, freq="D")
    coins = ["BTCUSDT", "AUSDT", "BUSDT", "CUSDT", "DUSDT", "ZUSDT"]
    close = pd.DataFrame(100.0, index=dates, columns=coins)
    close.iloc[0] = [90, 90, 90, 90, 90, 90]
    close.iloc[1] = [100, 100, 100, 100, 100, 100]
    close.iloc[2] = [120, 101, 102, 103, 104, 200]
    close.iloc[3:] = close.iloc[2].to_numpy()
    open_ = pd.DataFrame(100.0, index=dates, columns=coins)
    # The highest-ranked symbol disappears only at the future exit. A correct
    # point-in-time backtest must retain and penalize it, not select a runner-up.
    open_.loc[dates[4], "ZUSDT"] = np.nan
    return close, open_


def test_missing_future_exit_is_a_loss_not_a_selection_filter(monkeypatch):
    close, open_ = _panels()

    monkeypatch.setattr(validate, "SKIP", 2)
    validated, _, _ = validate.backtest(close, open_, L=1, K=1, R=1, cost=0.0)
    assert validated.iloc[0] == pytest.approx(-1.0)

    monkeypatch.setattr(regime, "SKIP", 2)
    regime_returns, _, _ = regime.backtest(
        close, open_, L=1, K=1, R=1,
        regime=pd.Series(True, index=close.index), cost=0.0,
    )
    assert regime_returns.iloc[0] == pytest.approx(-1.0)

    monkeypatch.setattr(hardened, "SKIP", 2)
    hardened_returns, _, _ = hardened.backtest(
        close, open_, L=1, K=1, R=1, regimeN=2, target_vol=None,
    )
    assert hardened_returns.iloc[0] < -0.99

    monkeypatch.setattr(robust, "SKIP", 2)
    robust_returns, _ = robust.backtest(
        close, open_, L=1, K=1, R=1, regimeN=2, target_vol=None,
    )
    assert robust_returns.iloc[0] < -0.99

    monkeypatch.setattr(momentum, "SKIP", 2)
    monkeypatch.setattr(momentum, "L", 1)
    monkeypatch.setattr(momentum, "K", 1)
    monkeypatch.setattr(momentum, "R", 1)
    monkeypatch.setattr(momentum, "REGIME_N", 2)
    monkeypatch.setattr(momentum, "TARGET_VOL", 1_000_000.0)
    momentum_returns, _ = momentum._backtest(close, open_)
    assert momentum_returns.iloc[0] < -0.99


def test_cross_sectional_evaluation_ranks_before_future_outcome(monkeypatch):
    columns = ["A", "B", "C", "D", "E", "Z"]
    signal = pd.DataFrame([[1, 2, 3, 4, 5, 100]], columns=columns)
    future = pd.DataFrame([[0, 0, 0, 0, 0, np.nan]], columns=columns)
    monkeypatch.setattr(cross, "SKIP", 0)
    long_short, _, _ = cross.evaluate(signal, future)
    assert long_short.iloc[0] < -0.30


def test_periodic_metrics_count_initial_capital_in_first_period_drawdown():
    first_period_loss = pd.Series([-0.50])
    assert cross.max_drawdown_from_returns(first_period_loss) == pytest.approx(-50.0)
    assert momentum._perf(first_period_loss)["mdd"] == pytest.approx(-50.0)
    assert validate.metrics(first_period_loss, 10)["mdd"] == pytest.approx(-50.0)
    assert regime.metrics(first_period_loss, 10)["mdd"] == pytest.approx(-50.0)
    assert hardened.metrics(first_period_loss, 10)["mdd"] == pytest.approx(-50.0)
    assert robust.perf(first_period_loss, 10)["mdd"] == pytest.approx(-50.0)


def test_today_signal_uses_latest_scheduled_rebalance(monkeypatch):
    dates = pd.date_range("2025-02-01", periods=8, freq="D")
    coins = ["BTCUSDT", "AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT"]
    close = pd.DataFrame(100.0, index=dates, columns=coins)
    close["BTCUSDT"] = [90, 100, 110, 120, 130, 140, 150, 160]
    close.loc[dates[4], "AUSDT"] = 100
    close.loc[dates[5]:, "AUSDT"] = 200
    close.loc[dates[5], "BUSDT"] = 101
    close.loc[dates[6], "BUSDT"] = 500
    close.loc[dates[7], "BUSDT"] = 1000
    open_ = close.copy()

    monkeypatch.setattr(momentum, "SKIP", 2)
    monkeypatch.setattr(momentum, "L", 1)
    monkeypatch.setattr(momentum, "K", 1)
    monkeypatch.setattr(momentum, "R", 3)
    monkeypatch.setattr(momentum, "REGIME_N", 2)
    monkeypatch.setattr(momentum, "TARGET_VOL", 1_000_000.0)

    result = momentum.today_signal(close, open_)
    assert result["data_as_of"] == str(dates[7].date())
    assert result["rebalance_date"] == str(dates[5].date())
    assert result["next_rebalance_in_bars"] == 1
    assert result["picks"][0]["symbol"] == "A"


def test_today_signal_applies_known_entry_open_but_not_unknown_next_open(monkeypatch):
    dates = pd.date_range("2025-02-01", periods=8, freq="D")
    coins = ["BTCUSDT", "AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT"]
    close = pd.DataFrame(100.0, index=dates, columns=coins)
    close["BTCUSDT"] = [90, 100, 110, 120, 130, 140, 150, 160]
    close.loc[dates[4], "AUSDT"] = 100
    close.loc[dates[5]:, "AUSDT"] = 200
    open_ = close.copy()

    monkeypatch.setattr(momentum, "SKIP", 2)
    monkeypatch.setattr(momentum, "L", 1)
    monkeypatch.setattr(momentum, "K", 1)
    monkeypatch.setattr(momentum, "R", 3)
    monkeypatch.setattr(momentum, "REGIME_N", 2)
    monkeypatch.setattr(momentum, "TARGET_VOL", 1_000_000.0)

    # On the decision close, the next open is unknown. Keep the target order.
    pending = momentum.today_signal(close.iloc[:6], open_.iloc[:6])
    assert pending["pending_rebalance"] is True
    assert pending["execution_status"] == "pending_next_open"
    assert pending["picks"][0]["symbol"] == "A"
    assert pending["target_exposure_pct"] == pending["exposure_pct"]

    # Once that entry bar is known to have no A open, mirror the backtest: the
    # unfilled target remains cash and must not be shown as an actual holding.
    open_.loc[dates[6], "AUSDT"] = np.nan
    effective = momentum.today_signal(close, open_)
    assert effective["pending_rebalance"] is False
    assert effective["execution_status"] == "unfilled"
    assert effective["target_exposure_pct"] > 0
    assert effective["exposure_pct"] == 0
    assert effective["picks"] == []
    assert effective["unfilled_symbols"] == ["A"]


def test_random_baseline_keeps_same_day_trade_and_checks_entry_bar():
    dates = pd.date_range("2025-03-01", periods=12, freq="D")
    frame = pd.DataFrame({
        "date": dates,
        "open": 100.0,
        "high": 100.0,
        "low": 90.0,
        "close": 100.0,
    })
    day = str(dates[3].date())
    trades = [{
        "entry_date": day,
        "exit_date": day,
        "hold_days": 0,
        "exit_reason": "stop_loss",
    }]
    baseline = single_asset.random_entry_baseline(
        frame, trades, strategy_return_pct=-6.0, n_sims=20, seed=7,
    )
    assert baseline is not None
    assert baseline["n_trades"] == 1
    assert baseline["median_return_pct"] < -6.0


def test_random_baseline_schedule_never_overlaps():
    rng = np.random.default_rng(42)
    opens = np.full(30, 100.0)
    durations = [3, 0, 4, 2]
    schedule_counts = single_asset._build_non_overlapping_schedule_counts(
        durations, 30, opens,
    )
    assert schedule_counts is not None
    for _ in range(1000):
        starts = single_asset._sample_non_overlapping_schedule(schedule_counts, rng)
        assert len(starts) == len(durations)
        intervals = list(zip(
            starts,
            [start + duration for start, duration in zip(starts, durations)],
        ))
        assert all(left[1] < right[0] for left, right in zip(intervals, intervals[1:]))


def test_single_trade_schedule_is_uniform_across_every_eligible_start():
    n_rows = 30
    start_index = 2
    opens = np.full(n_rows, 100.0)
    opens[[5, 17]] = np.nan
    schedule_counts = single_asset._build_non_overlapping_schedule_counts(
        [0], n_rows, opens, start_index=start_index,
    )
    assert schedule_counts is not None

    eligible_starts = [
        index for index in range(start_index, n_rows)
        if np.isfinite(opens[index]) and opens[index] > 0
    ]
    assert schedule_counts["ways"][0][start_index] == len(eligible_starts)

    rng = np.random.default_rng(20260721)
    draws_per_start = 1000
    observed = np.zeros(n_rows, dtype=int)
    for _ in range(draws_per_start * len(eligible_starts)):
        sampled = single_asset._sample_non_overlapping_schedule(schedule_counts, rng)
        observed[sampled[0]] += 1

    assert observed[5] == 0
    assert observed[17] == 0
    eligible_counts = observed[eligible_starts]
    # Fixed-seed statistical guard: endpoints and middle dates must all receive
    # approximately their exact-uniform expectation, not a binomial center peak.
    assert eligible_counts.min() > draws_per_start * 0.80
    assert eligible_counts.max() < draws_per_start * 1.20


def _trade(entry_date, exit_date, return_pct, hold_days):
    return {
        "entry_date": str(pd.Timestamp(entry_date).date()),
        "exit_date": str(pd.Timestamp(exit_date).date()),
        "entry_price": 100.0,
        "exit_price": 100.0 * (1 + return_pct / 100),
        "return_pct": return_pct,
        "hold_days": hold_days,
        "exit_reason": "signal_exit",
        "cost_pct": 0.0,
    }


def test_metrics_capture_intra_trade_daily_drawdown():
    dates = pd.date_range("2025-04-01", periods=5, freq="D")
    frame = pd.DataFrame({"date": dates, "close": [100, 50, 100, 100, 100]})
    trades = [_trade(dates[0], dates[2], 0.0, 2)]
    metrics = single_asset.compute_metrics(trades, frame)
    assert metrics["max_drawdown_pct"] == pytest.approx(-50.0)
    assert metrics["total_return_pct"] == pytest.approx(0.0)
    assert len(metrics["equity_curve"]) == len(frame)
    assert metrics["equity_curve"][1]["equity"] == pytest.approx(0.5)


def test_cagr_uses_full_dataframe_period_including_cash_days():
    dates = pd.date_range("2025-01-01", periods=366, freq="D")
    frame = pd.DataFrame({"date": dates, "close": 100.0})
    trades = [_trade(dates[0], dates[1], 10.0, 1)]
    metrics = single_asset.compute_metrics(trades, frame)
    assert metrics["total_return_pct"] == pytest.approx(10.0)
    assert metrics["cagr_pct"] == pytest.approx(10.0, abs=0.05)
    assert metrics["equity_curve"][-1]["equity"] == pytest.approx(1.1)


def test_metrics_without_curve_keep_identical_daily_risk_numbers():
    dates = pd.date_range("2025-05-01", periods=20, freq="D")
    closes = np.array([100, 98, 94, 90, 96, 102, 105, 103, 107, 110] * 2, dtype=float)
    frame = pd.DataFrame({"date": dates, "close": closes})
    trades = [_trade(dates[1], dates[8], 8.0, 7)]

    with_curve = single_asset.compute_metrics(trades, frame, include_curve=True)
    without_curve = single_asset.compute_metrics(trades, frame, include_curve=False)
    assert without_curve["equity_curve"] == []
    assert {
        key: value for key, value in with_curve.items() if key != "equity_curve"
    } == {
        key: value for key, value in without_curve.items() if key != "equity_curve"
    }
