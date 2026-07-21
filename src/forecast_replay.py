"""Point-in-time replay for the immutable research forecast contract.

The central invariant is explicit: for an issue row ``t`` and horizon ``h``,
the forecast and its forecast-time baseline may only use historical outcomes
whose origin ``j`` satisfies ``j + h <= t``.  The outcome at ``t + h`` is
attached only after the prediction has been generated from the prefix ending
at ``t``.

Library example::

    records = replay_forecasts("BTCUSDT", rows, horizons=(1, 5, 10))
    scorecard = evaluate_replay_records(records)

The CLI reads ``data/clean/*_1d.csv`` by default and prints a JSON scorecard.
Use ``--output`` to atomically persist the scorecard together with its records.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:  # Supports both ``python -m src.forecast_replay`` and direct execution.
    from src.forecast_evaluation import evaluate_replay_records
    from src.forecasting import (
        MIN_OUTCOMES,
        MIN_OBSERVATIONS,
        MIN_READY_CONFIDENCE,
        MODEL_VERSION,
        SUPPORTED_HORIZONS,
        _data_version,
        _forecast_id,
        _prepare_prices,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by CLI smoke usage.
    from forecast_evaluation import evaluate_replay_records
    from forecasting import (
        MIN_OUTCOMES,
        MIN_OBSERVATIONS,
        MIN_READY_CONFIDENCE,
        MODEL_VERSION,
        SUPPORTED_HORIZONS,
        _data_version,
        _forecast_id,
        _prepare_prices,
    )


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data" / "clean"


def _validate_horizons(horizons: Iterable[int]) -> tuple[int, ...]:
    resolved = tuple(dict.fromkeys(int(value) for value in horizons))
    if not resolved:
        raise ValueError("horizons must contain at least one value")
    unsupported = [value for value in resolved if value not in SUPPORTED_HORIZONS]
    if unsupported:
        raise ValueError(f"unsupported horizons {unsupported}; expected {SUPPORTED_HORIZONS}")
    return resolved


def _date_bound(value: str | None, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"{name} must be a valid date")
    return pd.Timestamp(parsed).tz_convert(None).normalize()


def _regime_labels(closes: np.ndarray) -> np.ndarray:
    """Vectorized copy of the production model's point-in-time regime rule."""

    close = pd.Series(closes, dtype=float)
    ma60 = close.rolling(60, min_periods=60).mean()
    return20 = close.pct_change(20, fill_method=None)
    regimes = np.full(close.size, "sideways", dtype=object)
    regimes[((close > ma60) & (return20 > 0)).to_numpy()] = "bull"
    regimes[((close < ma60) & (return20 < 0)).to_numpy()] = "bear"
    regimes[(ma60.isna() | return20.isna()).to_numpy()] = "unknown"
    return regimes


def _prefix_hashes(dates: Sequence[pd.Timestamp], closes: np.ndarray) -> list[str]:
    """Hash every available prefix using forecasting._input_hash's encoding."""

    digest = sha256()
    hashes: list[str] = []
    for date_value, close in zip(dates, closes):
        canonical = f"{date_value.strftime('%Y-%m-%d')}|{float(close).hex()}\n"
        digest.update(canonical.encode("ascii"))
        hashes.append(digest.hexdigest())
    return hashes


def _snapshot_from_mature_history(
    *,
    symbol: str,
    horizon: int,
    issue_date: str,
    observations: int,
    reference_close: float,
    input_hash: str,
    current_regime: str,
    all_history: Sequence[float],
    same_regime_history: Sequence[float],
) -> dict[str, Any]:
    """Reproduce the scoring fields of ``generate_forecast`` without reparsing.

    A full replay invokes this tens of thousands of times. Rebuilding a pandas
    frame for every issue date is both slow and harder to audit; the caller
    incrementally supplies only outcomes that have matured by that date.
    """

    generated_at = f"{issue_date}T00:00:00Z"
    base: dict[str, Any] = {
        "forecast_id": _forecast_id(symbol, horizon, issue_date, input_hash),
        "symbol": symbol,
        "horizon_days": horizon,
        "as_of": issue_date,
        "generated_at": generated_at,
        "model_version": MODEL_VERSION,
        "input_hash": input_hash,
        "data_version": _data_version(issue_date, observations, input_hash),
        "reference_close": reference_close,
        "regime": current_regime,
    }
    if observations < MIN_OBSERVATIONS:
        return {
            **base,
            "status": "abstain",
            "abstain_reason": f"observations {observations} < {MIN_OBSERVATIONS}",
            "probabilities": {"up": None, "down": None},
            "return_quantiles_pct": {"q10": None, "q50": None, "q90": None},
            "confidence": {"score": 0, "level": "low"},
        }

    selected = (
        same_regime_history
        if current_regime != "unknown" and len(same_regime_history) >= MIN_OUTCOMES
        else all_history
    )
    if len(selected) < MIN_OUTCOMES:
        return {
            **base,
            "status": "abstain",
            "abstain_reason": f"mature outcomes {len(selected)} < {MIN_OUTCOMES}",
            "probabilities": {"up": None, "down": None},
            "return_quantiles_pct": {"q10": None, "q50": None, "q90": None},
            "confidence": {"score": 0, "level": "low"},
        }

    outcomes = np.asarray(selected, dtype=float)
    up_probability = float(((outcomes > 0).sum() + 1) / (outcomes.size + 2))
    q10, q50, q90 = (float(value * 100.0) for value in np.quantile(outcomes, [0.1, 0.5, 0.9]))
    edge = abs(up_probability - 0.5) * 2.0
    sample_strength = min(1.0, outcomes.size / 200.0)
    width = q90 - q10
    interval_width_penalty = max(0.25, 1.0 - max(0.0, width - 20.0) / 60.0)
    confidence_score = int(round(100.0 * edge * sample_strength * interval_width_penalty))
    reasons: list[str] = []
    if abs(up_probability - 0.5) < 0.07:
        reasons.append("directional edge below 7 percentage points")
    if confidence_score < MIN_READY_CONFIDENCE:
        reasons.append(f"confidence {confidence_score} < {MIN_READY_CONFIDENCE}")
    if width > 35.0:
        reasons.append("q10-q90 interval wider than 35 percentage points")
    status = "abstain" if reasons else "ready"
    level = "high" if confidence_score >= 70 else "medium" if confidence_score >= 40 else "low"
    return {
        **base,
        "status": status,
        "abstain_reason": "; ".join(reasons) if reasons else None,
        "probabilities": {
            "up": round(up_probability, 4),
            "down": round(1.0 - up_probability, 4),
        },
        "return_quantiles_pct": {
            "q10": round(q10, 2),
            "q50": round(q50, 2),
            "q90": round(q90, 2),
        },
        "confidence": {"score": confidence_score, "level": level},
    }


def build_replay_record(
    snapshot: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
    outcome: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Flatten an immutable forecast, point-in-time baseline, and outcome."""

    probabilities = snapshot.get("probabilities") or {}
    quantiles = snapshot.get("return_quantiles_pct") or {}
    confidence = snapshot.get("confidence") or {}
    record: dict[str, Any] = {
        "forecast_id": snapshot.get("forecast_id"),
        "symbol": snapshot.get("symbol"),
        "model_version": snapshot.get("model_version"),
        "horizon_days": snapshot.get("horizon_days"),
        "issue_date": snapshot.get("as_of"),
        "as_of": snapshot.get("as_of"),
        "status": snapshot.get("status"),
        "abstain_reason": snapshot.get("abstain_reason"),
        "probability_up": probabilities.get("up"),
        "probability_down": probabilities.get("down"),
        "confidence_score": confidence.get("score"),
        "return_q10_pct": quantiles.get("q10"),
        "return_q50_pct": quantiles.get("q50"),
        "return_q90_pct": quantiles.get("q90"),
        "reference_close": snapshot.get("reference_close"),
        "input_hash": snapshot.get("input_hash"),
        "data_version": snapshot.get("data_version"),
        "baseline_probability_up": baseline.get("probability_up"),
        "baseline_observations": baseline.get("observations"),
        "baseline_latest_origin_date": baseline.get("latest_origin_date"),
        "baseline_latest_target_date": baseline.get("latest_target_date"),
        "baseline_maturity_rule": baseline.get("maturity_rule"),
        "baseline_smoothing": baseline.get("smoothing"),
        "target_date": None,
        "outcome_up": None,
        "realized_return_pct": None,
        "outcome_close": None,
    }
    if outcome is not None:
        record.update(
            {
                "target_date": outcome.get("target_as_of"),
                "outcome_up": outcome.get("outcome_up"),
                "realized_return_pct": outcome.get("realized_return_pct"),
                "outcome_close": outcome.get("outcome_close"),
            }
        )
    return record


def replay_forecasts(
    symbol: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    horizons: Iterable[int] = SUPPORTED_HORIZONS,
    start_date: str | None = None,
    end_date: str | None = None,
    min_observations: int = MIN_OBSERVATIONS,
    include_unresolved: bool = False,
) -> list[dict[str, Any]]:
    """Replay the current forecast model through a completed daily series.

    ``start_date`` and ``end_date`` constrain issue dates, not training history:
    all rows before ``start_date`` remain available to the model.  By default,
    unresolved tail forecasts are omitted because they cannot be scored.
    Passing ``include_unresolved=True`` retains them with null outcome fields.
    """

    resolved_horizons = _validate_horizons(horizons)
    if not isinstance(min_observations, int) or min_observations < 1:
        raise ValueError("min_observations must be a positive integer")
    start = _date_bound(start_date, "start_date")
    end = _date_bound(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date cannot be after end_date")

    frame = _prepare_prices(rows)
    if frame.empty:
        return []
    dates = [pd.Timestamp(value) for value in frame["date"]]
    closes = frame["close"].to_numpy(dtype=float)
    regimes = _regime_labels(closes)
    input_hashes = _prefix_hashes(dates, closes)
    model_history: dict[int, dict[str, Any]] = {
        horizon: {
            "all": [],
            "by_regime": {"bull": [], "bear": [], "sideways": []},
            "baseline_count": 0,
            "baseline_up": 0,
        }
        for horizon in resolved_horizons
    }

    records: list[dict[str, Any]] = []
    first_index = min_observations - 1
    for issue_index in range(len(frame)):
        issue_timestamp = dates[issue_index].normalize()
        if end is not None and issue_timestamp > end:
            break
        for horizon in resolved_horizons:
            history = model_history[horizon]
            mature_origin = issue_index - horizon
            if mature_origin >= 0:
                matured_return = float(
                    closes[issue_index] / closes[mature_origin] - 1.0
                )
                history["baseline_count"] += 1
                history["baseline_up"] += int(matured_return > 0)
                origin_regime = str(regimes[mature_origin])
                if origin_regime != "unknown":
                    history["all"].append(matured_return)
                    history["by_regime"][origin_regime].append(matured_return)

        if issue_index < first_index:
            continue
        if start is not None and issue_timestamp < start:
            continue
        issue_date = issue_timestamp.strftime("%Y-%m-%d")
        for horizon in resolved_horizons:
            history = model_history[horizon]
            target_index = issue_index + horizon
            if target_index >= len(frame) and not include_unresolved:
                continue
            current_regime = str(regimes[issue_index])
            snapshot = _snapshot_from_mature_history(
                symbol=symbol.upper(),
                horizon=horizon,
                issue_date=issue_date,
                observations=issue_index + 1,
                reference_close=float(closes[issue_index]),
                input_hash=input_hashes[issue_index],
                current_regime=current_regime,
                all_history=history["all"],
                same_regime_history=history["by_regime"].get(current_regime, []),
            )
            baseline_observations = int(history["baseline_count"])
            baseline = {
                "probability_up": float(
                    (history["baseline_up"] + 1)
                    / (baseline_observations + 2)
                ),
                "observations": baseline_observations,
                "latest_origin_date": (
                    dates[issue_index - horizon].strftime("%Y-%m-%d")
                    if baseline_observations
                    else None
                ),
                "latest_target_date": issue_date if baseline_observations else None,
                "maturity_rule": "j + horizon <= issue_index",
                "smoothing": "Laplace(1,1)",
            }
            outcome = None
            if target_index < len(frame):
                realized = float((closes[target_index] / closes[issue_index] - 1.0) * 100.0)
                outcome = {
                    "target_as_of": dates[target_index].strftime("%Y-%m-%d"),
                    "outcome_close": float(closes[target_index]),
                    "realized_return_pct": round(realized, 4),
                    "outcome_up": 1 if realized > 0 else 0,
                }
            records.append(build_replay_record(snapshot, baseline=baseline, outcome=outcome))
    return records


def _enabled_symbols(data_dir: Path) -> tuple[list[str], str, str | None]:
    available = {path.stem.removesuffix("_1d") for path in data_dir.glob("*_1d.csv")}
    try:
        from backend.services.app_db import get_enabled_symbols

        enabled = get_enabled_symbols()
        return (
            [symbol for symbol in enabled if symbol in available],
            "current_enabled_symbols_intersect_csv",
            None,
        )
    except Exception as error:
        # Standalone research copies may not have the application database.
        return (
            sorted(available),
            "all_csv_files_after_enabled_symbol_lookup_failed",
            type(error).__name__,
        )


def _parse_symbols(value: str | None, data_dir: Path) -> tuple[list[str], str, str | None]:
    if value is None:
        return _enabled_symbols(data_dir)
    symbols = [part.strip().upper() for part in value.split(",") if part.strip()]
    if not symbols:
        raise ValueError("--symbols must contain at least one comma-separated symbol")
    return list(dict.fromkeys(symbols)), "explicit_cli_symbols", None


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_horizons(value: str) -> tuple[int, ...]:
    try:
        return _validate_horizons(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Leakage-safe point-in-time replay of research forecasts."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="directory containing SYMBOL_1d.csv files (default: data/clean)",
    )
    parser.add_argument(
        "--symbols",
        help="comma-separated symbols; default is enabled symbols with daily CSV data",
    )
    parser.add_argument(
        "--horizons",
        type=_parse_horizons,
        default=SUPPORTED_HORIZONS,
        help="comma-separated horizons from 1,5,10 (default: 1,5,10)",
    )
    parser.add_argument("--start-date", help="first forecast issue date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="last forecast issue date (YYYY-MM-DD)")
    parser.add_argument(
        "--block-size",
        type=int,
        default=None,
        help="issue-date bootstrap block size (default: max(7, 2*largest horizon))",
    )
    parser.add_argument(
        "--bootstrap-samples", type=int, default=1000, help="bootstrap resamples"
    )
    parser.add_argument("--seed", type=int, default=0, help="deterministic bootstrap seed")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON path; writes scorecard and replay records atomically",
    )
    return parser


def _compact_scorecard(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    """Keep stdout useful while an optional output retains full curve data."""

    compact = {
        key: scorecard.get(key)
        for key in (
            "records_received",
            "resolved_records",
            "excluded_records",
            "baseline_fallback_records",
            "neutral_baseline_records",
            "intervals",
            "brier_advantage_ci",
        )
    }
    metric_keys = (
        "observations",
        "positive_rate",
        "brier_score",
        "baseline_brier_score",
        "brier_skill_score",
        "log_loss",
        "baseline_log_loss",
        "expected_calibration_error",
        "coverage",
        "selective_accuracy",
        "status_metrics",
    )
    overall = scorecard.get("overall")
    compact["overall"] = (
        {key: overall.get(key) for key in metric_keys}
        if isinstance(overall, Mapping)
        else None
    )
    compact["by_horizon"] = {
        horizon: {key: metrics.get(key) for key in metric_keys}
        for horizon, metrics in (scorecard.get("by_horizon") or {}).items()
    }
    return compact


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = args.data_dir.resolve()
    try:
        symbols, universe_source, universe_error = _parse_symbols(args.symbols, data_dir)
        if not symbols:
            parser.error(f"no enabled *_1d.csv symbols found in {data_dir}")
        records: list[dict[str, Any]] = []
        missing: list[str] = []
        source_files: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            source = data_dir / f"{symbol}_1d.csv"
            if not source.is_file():
                missing.append(symbol)
                continue
            frame = pd.read_csv(source, usecols=["date", "close"])
            source_files[symbol] = {
                "file": source.name,
                "sha256": _file_sha256(source),
                "rows_read": int(len(frame)),
            }
            records.extend(
                replay_forecasts(
                    symbol,
                    frame.to_dict("records"),
                    horizons=args.horizons,
                    start_date=args.start_date,
                    end_date=args.end_date,
                )
            )
        block_size = (
            max(7, 2 * max(args.horizons))
            if args.block_size is None else args.block_size
        )
        scorecard = evaluate_replay_records(
            records,
            block_size=block_size,
            bootstrap_samples=args.bootstrap_samples,
            random_seed=args.seed,
        )
    except (OSError, ValueError, pd.errors.ParserError) as error:
        parser.error(str(error))

    summary: dict[str, Any] = {
        "symbols_requested": symbols,
        "symbols_missing": missing,
        "horizons_days": list(args.horizons),
        "records": len(records),
        "provenance": {
            "model_version": MODEL_VERSION,
            "vintage_exact": False,
            "universe_source": universe_source,
            "universe_lookup_error": universe_error,
            "historical_universe_exact": False,
            "maturity_rule": "origin_index + horizon <= issue_index",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "block_size": block_size,
            "bootstrap_samples": args.bootstrap_samples,
            "random_seed": args.seed,
            "source_files": source_files,
        },
        "warnings": [
            "CSV files represent the current/revised data vintage, not exact historical vintages",
            *(
                ["default universe uses symbols enabled today; pass --symbols for a predeclared research universe"]
                if args.symbols is None else []
            ),
            *(
                [f"enabled-symbol lookup failed ({universe_error}); universe fell back to all CSV files"]
                if universe_error else []
            ),
        ],
        "scorecard": _compact_scorecard(scorecard),
    }
    if args.output is not None:
        _atomic_json_write(
            args.output,
            {**summary, "scorecard": scorecard, "replay_records": records},
        )
        summary["output"] = str(args.output.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess use.
    raise SystemExit(main())
