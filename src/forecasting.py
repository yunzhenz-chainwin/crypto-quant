# -*- coding: utf-8 -*-
"""Deterministic, point-in-time research forecasts.

This module deliberately implements a small historical baseline instead of
pretending to be a production trading model.  Every calculation is limited to
rows available at ``as_of`` and the result can explicitly abstain when the
sample, freshness, or historical edge is insufficient.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Iterable

import numpy as np
import pandas as pd


MODEL_VERSION = "historical-baseline-v2"
MODEL_NAME = "Historical regime-conditioned return baseline"
SUPPORTED_HORIZONS = (1, 5, 10)
DOWNSIDE_THRESHOLDS_PCT = {1: -3.0, 5: -7.0, 10: -10.0}
MAX_STALE_DAYS = 2
MIN_OBSERVATIONS = 120
MIN_OUTCOMES = 30
MIN_READY_CONFIDENCE = 40


def model_metadata() -> dict[str, Any]:
    """Serializable registry metadata for the baseline model."""
    return {
        "model_version": MODEL_VERSION,
        "name": MODEL_NAME,
        "status": "research",
        "research": True,
        "methodology": {
            "inputs": ["completed daily close"],
            "regime": "close versus MA60 plus trailing 20-day return",
            "estimator": "Laplace-smoothed empirical returns in the same regime",
            "horizons_days": list(SUPPORTED_HORIZONS),
            "point_in_time": True,
            "limitations": [
                "historical baseline, not a price oracle",
                "not calibrated for position sizing",
                "research output, not financial advice",
            ],
        },
    }


def latest_completed_daily_date(now: datetime | None = None) -> date:
    """Return the last fully closed UTC daily candle date."""
    current = _utc_now(now)
    return current.date() - timedelta(days=1)


def _utc_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _prepare_prices(rows: Iterable[dict[str, Any]], as_of: str | date | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if frame.empty or "date" not in frame or "close" not in frame:
        return pd.DataFrame(columns=["date", "close"])

    frame = frame[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_convert(None)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame[frame["close"] > 0]
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    if as_of is not None:
        cutoff = pd.Timestamp(as_of).normalize()
        frame = frame[frame["date"] <= cutoff]
    return frame.reset_index(drop=True)


def _input_hash(frame: pd.DataFrame) -> str:
    """Hash the exact canonical daily-close history consumed by the model."""
    digest = sha256()
    for row in frame.itertuples(index=False):
        # float.hex preserves the exact IEEE-754 value and is independent of
        # locale/JSON formatting.  Dates have already been normalized above.
        canonical = f"{row.date.strftime('%Y-%m-%d')}|{float(row.close).hex()}\n"
        digest.update(canonical.encode("ascii"))
    return digest.hexdigest()


def _regime(close: pd.Series) -> tuple[str, dict[str, float | None]]:
    if len(close) < 61:
        return "unknown", {"ma60": None, "return_20d_pct": None}
    ma60 = float(close.iloc[-60:].mean())
    return_20 = float((close.iloc[-1] / close.iloc[-21] - 1.0) * 100.0)
    if close.iloc[-1] > ma60 and return_20 > 0:
        label = "bull"
    elif close.iloc[-1] < ma60 and return_20 < 0:
        label = "bear"
    else:
        label = "sideways"
    return label, {"ma60": ma60, "return_20d_pct": return_20}


def _historical_returns(frame: pd.DataFrame, horizon_days: int, current_regime: str) -> tuple[pd.Series, bool]:
    close = frame.set_index("date")["close"]
    ma60 = close.rolling(60, min_periods=60).mean()
    ret20 = close.pct_change(20, fill_method=None)
    regimes = pd.Series("sideways", index=close.index, dtype="object")
    regimes[(close > ma60) & (ret20 > 0)] = "bull"
    regimes[(close < ma60) & (ret20 < 0)] = "bear"
    regimes[ma60.isna() | ret20.isna()] = "unknown"
    future_returns = close.shift(-horizon_days) / close - 1.0

    same_regime = future_returns[(regimes == current_regime) & future_returns.notna()]
    if current_regime != "unknown" and len(same_regime) >= MIN_OUTCOMES:
        return same_regime.astype(float), False
    # A regime can be rare.  The fallback remains point-in-time and is surfaced
    # in evidence rather than silently fabricating confidence.
    all_history = future_returns[(regimes != "unknown") & future_returns.notna()]
    return all_history.astype(float), True


def _empty_contract(
    symbol: str,
    horizon_days: int,
    as_of: str | None,
    generated_at: str,
    observations: int,
    stale: bool,
    reason: str,
    regime: str = "unknown",
    input_hash: str | None = None,
    reference_close: float | None = None,
) -> dict[str, Any]:
    resolved_hash = input_hash or sha256(b"").hexdigest()
    forecast_id = _forecast_id(symbol, horizon_days, as_of or "no-data", resolved_hash)
    return {
        "forecast_id": forecast_id,
        "symbol": symbol,
        "horizon_days": horizon_days,
        "status": "abstain",
        "research": True,
        "as_of": as_of,
        "generated_at": generated_at,
        "model_version": MODEL_VERSION,
        "input_hash": resolved_hash,
        "data_version": _data_version(as_of, observations, resolved_hash),
        "reference_close": reference_close,
        "probabilities": {"up": None, "down": None},
        "return_quantiles_pct": {"q10": None, "q50": None, "q90": None},
        "downside_risk": {
            "threshold_pct": DOWNSIDE_THRESHOLDS_PCT[horizon_days],
            "probability": None,
        },
        "regime": regime,
        "confidence": {"score": 0, "level": "low"},
        "recommendation": "wait",
        "abstain_reason": reason,
        "evidence": {
            "for": [],
            "against": [reason, "研究基準不構成交易建議"],
        },
        "data_quality": {"stale": stale, "observations": observations},
    }


def _data_version(as_of: str | None, observations: int, input_hash: str) -> str:
    return f"{as_of or 'no-data'}:{observations}:{input_hash[:16]}"


def _forecast_id(symbol: str, horizon_days: int, as_of: str, input_hash: str) -> str:
    raw = f"{MODEL_VERSION}|{symbol}|{horizon_days}|{as_of}|{input_hash}".encode("utf-8")
    return "fc_" + sha256(raw).hexdigest()[:24]


def generate_forecast(
    symbol: str,
    horizon_days: int,
    rows: Iterable[dict[str, Any]],
    *,
    as_of: str | date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate a deterministic point-in-time research forecast contract."""
    if horizon_days not in SUPPORTED_HORIZONS:
        raise ValueError(f"horizon_days must be one of {SUPPORTED_HORIZONS}")

    symbol = symbol.upper()
    generated = _utc_now(now)
    generated_at = generated.strftime("%Y-%m-%dT%H:%M:%SZ")
    frame = _prepare_prices(rows, as_of=as_of)
    observations = len(frame)
    input_hash = _input_hash(frame)
    resolved_as_of = frame.iloc[-1]["date"].strftime("%Y-%m-%d") if observations else None
    # Seal the exact float consumed by the model. Presentation can round later,
    # but outcome arithmetic must use the same reference value that was hashed.
    reference_close = float(frame.iloc[-1]["close"]) if observations else None
    stale = (
        resolved_as_of is not None
        and (generated.date() - date.fromisoformat(resolved_as_of)).days > MAX_STALE_DAYS
    )

    if not observations:
        return _empty_contract(
            symbol, horizon_days, resolved_as_of, generated_at, observations, True,
            "沒有可用的已完成日線資料",
            input_hash=input_hash,
            reference_close=reference_close,
        )

    regime, regime_facts = _regime(frame["close"])
    if observations < MIN_OBSERVATIONS:
        return _empty_contract(
            symbol, horizon_days, resolved_as_of, generated_at, observations, stale,
            f"樣本不足：需要至少 {MIN_OBSERVATIONS} 根日線",
            regime,
            input_hash,
            reference_close,
        )

    outcomes, used_fallback = _historical_returns(frame, horizon_days, regime)
    if len(outcomes) < MIN_OUTCOMES:
        return _empty_contract(
            symbol, horizon_days, resolved_as_of, generated_at, observations, stale,
            f"成熟歷史結果不足：需要至少 {MIN_OUTCOMES} 筆",
            regime,
            input_hash,
            reference_close,
        )

    up_probability = float(((outcomes > 0).sum() + 1) / (len(outcomes) + 2))
    down_probability = 1.0 - up_probability
    threshold_pct = DOWNSIDE_THRESHOLDS_PCT[horizon_days]
    downside_probability = float(
        ((outcomes * 100.0 <= threshold_pct).sum() + 1) / (len(outcomes) + 2)
    )
    q10, q50, q90 = (float(v * 100.0) for v in np.quantile(outcomes, [0.1, 0.5, 0.9]))

    edge = abs(up_probability - 0.5) * 2.0
    sample_strength = min(1.0, len(outcomes) / 200.0)
    interval_width_penalty = max(0.25, 1.0 - max(0.0, q90 - q10 - 20.0) / 60.0)
    confidence_score = int(round(100.0 * edge * sample_strength * interval_width_penalty))
    confidence_level = "high" if confidence_score >= 70 else "medium" if confidence_score >= 40 else "low"

    reasons: list[str] = []
    if stale:
        reasons.append(f"資料已過期：最後完成日線為 {resolved_as_of}")
    if abs(up_probability - 0.5) < 0.07:
        reasons.append("歷史上漲機率太接近 50%，方向優勢不足")
    if confidence_score < MIN_READY_CONFIDENCE:
        reasons.append(
            f"模型信心低於研究發布門檻（{confidence_score} < {MIN_READY_CONFIDENCE}）"
        )
    if q90 - q10 > 35.0:
        reasons.append("預測區間過寬，市場不確定性高")

    status = "abstain" if reasons else "ready"
    if status == "abstain":
        recommendation = "wait"
    elif up_probability >= 0.57:
        recommendation = "research_watch_upside"
    elif up_probability <= 0.43:
        recommendation = "research_watch_downside"
    else:
        recommendation = "wait"

    supporting: list[str] = []
    opposing: list[str] = []
    if up_probability >= 0.5:
        supporting.append(f"相同市場狀態的歷史上漲率為 {up_probability * 100:.1f}%")
    else:
        opposing.append(f"相同市場狀態的歷史下跌率為 {down_probability * 100:.1f}%")
    ret20 = regime_facts["return_20d_pct"]
    if ret20 is not None:
        message = f"近 20 日報酬為 {ret20:+.1f}%"
        (supporting if ret20 > 0 else opposing).append(message)
    risk_message = f"跌逾 {abs(threshold_pct):.0f}% 的歷史機率為 {downside_probability * 100:.1f}%"
    (opposing if downside_probability >= 0.25 else supporting).append(risk_message)
    if used_fallback:
        opposing.append("相同狀態樣本不足，已退回全市場歷史基準")
    if reasons:
        opposing.extend(reason for reason in reasons if reason not in opposing)
    opposing.append("研究基準不構成交易建議")

    return {
        "forecast_id": _forecast_id(symbol, horizon_days, resolved_as_of, input_hash),
        "symbol": symbol,
        "horizon_days": horizon_days,
        "status": status,
        "research": True,
        "as_of": resolved_as_of,
        "generated_at": generated_at,
        "model_version": MODEL_VERSION,
        "input_hash": input_hash,
        "data_version": _data_version(resolved_as_of, observations, input_hash),
        "reference_close": reference_close,
        "probabilities": {
            "up": round(up_probability, 4),
            "down": round(down_probability, 4),
        },
        "return_quantiles_pct": {
            "q10": round(q10, 2),
            "q50": round(q50, 2),
            "q90": round(q90, 2),
        },
        "downside_risk": {
            "threshold_pct": threshold_pct,
            "probability": round(downside_probability, 4),
        },
        "regime": regime,
        "confidence": {"score": confidence_score, "level": confidence_level},
        "recommendation": recommendation,
        "abstain_reason": "; ".join(reasons) if reasons else None,
        "evidence": {"for": supporting[:3], "against": opposing[:4]},
        "data_quality": {"stale": stale, "observations": observations},
    }


def apply_freshness_guard(snapshot: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Gate delivery of an immutable snapshot if its source has since gone stale."""
    guarded = {**snapshot}
    guarded["data_quality"] = dict(snapshot.get("data_quality") or {})
    as_of = snapshot.get("as_of")
    if not as_of:
        return guarded
    stale = (_utc_now(now).date() - date.fromisoformat(as_of)).days > MAX_STALE_DAYS
    guarded["data_quality"]["stale"] = stale
    if stale:
        reason = f"資料已過期：最後完成日線為 {as_of}"
        guarded["status"] = "abstain"
        guarded["recommendation"] = "wait"
        guarded["abstain_reason"] = reason
        evidence = dict(snapshot.get("evidence") or {})
        evidence["for"] = list(evidence.get("for") or [])
        evidence["against"] = [reason, *[x for x in evidence.get("against") or [] if x != reason]][:4]
        guarded["evidence"] = evidence
    return guarded


def resolve_forecast_outcome(
    snapshot: dict[str, Any],
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Resolve a matured forecast without modifying the original snapshot.

    Maturity is based on the N-th completed daily observation after ``as_of``.
    Returning ``None`` means that future data is not mature yet.
    """
    as_of = snapshot.get("as_of")
    horizon = int(snapshot.get("horizon_days") or 0)
    if not as_of or horizon not in SUPPORTED_HORIZONS:
        return None
    completed_cutoff = latest_completed_daily_date(now)
    frame = _prepare_prices(rows, as_of=completed_cutoff)
    future_rows = frame[frame["date"] > pd.Timestamp(as_of)]
    if len(future_rows) < horizon:
        return None
    reference_close = snapshot.get("reference_close")
    # Legacy v1 snapshots did not seal the reference close.  Retain a
    # compatibility fallback for those immutable rows only; all newly written
    # snapshots carry reference_close and never depend on a revised as_of row.
    if reference_close is None:
        base_rows = frame[frame["date"] <= pd.Timestamp(as_of)]
        if base_rows.empty:
            return None
        reference_close = float(base_rows.iloc[-1]["close"])
    reference_close = float(reference_close)
    if not np.isfinite(reference_close) or reference_close <= 0:
        return None
    target = future_rows.iloc[horizon - 1]
    realized = float((target["close"] / reference_close - 1.0) * 100.0)
    actual_direction = "up" if realized > 0 else "down" if realized < 0 else "flat"
    return {
        "forecast_id": snapshot["forecast_id"],
        "symbol": snapshot["symbol"],
        "horizon_days": horizon,
        "as_of": as_of,
        "target_as_of": target["date"].strftime("%Y-%m-%d"),
        "resolved_at": _utc_now(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference_close": reference_close,
        "outcome_close": float(target["close"]),
        "realized_return_pct": round(realized, 4),
        "actual_direction": actual_direction,
        "outcome_up": 1 if actual_direction == "up" else 0,
        "input_hash": snapshot.get("input_hash"),
        "model_version": snapshot.get("model_version"),
    }
