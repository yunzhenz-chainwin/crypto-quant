from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.routers.admin import require_admin
from backend.services import app_db
from backend.services.forecast_scorecard import build_forecast_scorecard
from backend.services.rate_limiter import RATE_LIMITER, enforce_rate_limit
from backend.services.reader import available_symbols, load_prices
from src.forecasting import (
    MODEL_VERSION,
    apply_freshness_guard,
    generate_forecast,
    latest_completed_daily_date,
    model_metadata,
)


router = APIRouter()

# 累積狀態的快取：只隨每日封存變動，但前台每次載入都會問，不快取等於每次重算 1200+ 列
_LEDGER_CACHE: dict = {"ts": 0.0, "data": None}
_LEDGER_TTL = 600


@router.get("/forecast/ledger-status")
def get_forecast_ledger_status():
    """
    研究預測的累積狀態（公開、唯讀、只有彙總數字，不含任何單筆預測內容）。

    給前台「統一判斷摘要」的第②格用。這一格原本寫「研究預測未通過門檻」，
    但那句話沒講出真相：自上線以來從未通過過一次，而且實測連「完全不用模型、
    一律猜較常出現方向」的對照組都贏不了（見 src/forecast_diagnose.py）。
    數字由該診斷模組計算，畫面與診斷永遠是同一組數。
    """
    import time
    from src.forecast_diagnose import ledger_status

    now = time.time()
    if _LEDGER_CACHE["data"] is None or now - _LEDGER_CACHE["ts"] > _LEDGER_TTL:
        try:
            _LEDGER_CACHE["data"] = ledger_status()
            _LEDGER_CACHE["ts"] = now
        except Exception as exc:            # noqa: BLE001 — 加值資訊，不該讓主畫面壞掉
            # 真正的例外細節只印在伺服器端（與其他 handler 一致），對外一律回通用
            # 訊息，避免把內部錯誤字串洩漏給未驗證的呼叫端。
            print(f"[forecast] ledger-status error: {exc}")
            if _LEDGER_CACHE["data"] is None:
                return {"ok": False, "error": "累積狀態暫時無法取得"}
    return {"ok": True, **_LEDGER_CACHE["data"]}


@router.get("/forecast/scorecard")
def get_forecast_scorecard(
    request: Request,
    horizon: int | None = Query(
        default=None,
        description="Optional scorecard horizon: 1, 5, or 10 days",
    ),
    model_version: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    window: int | None = Query(
        default=None,
        ge=1,
        le=36500,
        description="Trailing calendar days ending at the ledger data_as_of",
    ),
    include_legacy: bool = Query(
        default=False,
        description="Research-only compatibility view; formal gates require false",
    ),
    _admin: str = Depends(require_admin),
):
    """Evaluate the immutable forecast/outcome ledger without inventing data."""
    enforce_rate_limit(
        request,
        scope="forecast_scorecard",
        limit=12,
        window_seconds=60,
        limiter=RATE_LIMITER,
    )
    if horizon is not None and horizon not in (1, 5, 10):
        raise HTTPException(status_code=422, detail="horizon must be 1, 5, or 10")
    try:
        return build_forecast_scorecard(
            horizon=horizon,
            model_version=model_version,
            symbol=symbol,
            window=window,
            include_legacy=include_legacy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/forecast/{symbol}")
def get_forecast(
    request: Request,
    symbol: str,
    horizon: int = Query(default=5, description="Research forecast horizon: 1, 5, or 10 days"),
):
    """Return an immutable, explicitly research-only forecast snapshot."""
    enforce_rate_limit(
        request,
        scope="forecast_snapshot",
        limit=30,
        window_seconds=60,
        limiter=RATE_LIMITER,
    )
    symbol = symbol.upper()
    if horizon not in (1, 5, 10):
        raise HTTPException(status_code=422, detail="horizon 僅支援 1、5、10 日")
    if symbol not in available_symbols("1d"):
        raise HTTPException(status_code=404, detail=f"{symbol} 無日線資料")

    now = datetime.now(timezone.utc)
    completed_cutoff = latest_completed_daily_date(now)
    all_rows = load_prices(symbol, interval="1d")
    completed_rows = [
        row for row in all_rows
        if row.get("date") and str(row["date"])[:10] <= completed_cutoff.isoformat()
    ]

    # With no completed bar there is no valid as_of key to persist.  Still
    # return the fixed abstention contract instead of fabricating a forecast.
    if not completed_rows:
        return generate_forecast(symbol, horizon, [], now=now)

    as_of = max(str(row["date"])[:10] for row in completed_rows)
    payload = generate_forecast(
        symbol,
        horizon,
        completed_rows,
        as_of=as_of,
        now=now,
    )
    cached = app_db.load_forecast_snapshot(
        symbol, horizon, as_of, MODEL_VERSION, payload["input_hash"]
    )
    if cached is not None:
        return apply_freshness_guard(cached, now=now)

    app_db.register_forecast_model(model_metadata())
    try:
        stored = app_db.save_forecast_snapshot(payload)
    except app_db.AppendOnlyConflict:
        # Two requests can race after the cache miss.  Whichever append won is
        # authoritative; immutable storage ensures neither can overwrite it.
        stored = app_db.load_forecast_snapshot(
            symbol, horizon, as_of, MODEL_VERSION, payload["input_hash"]
        )
        if stored is None:
            raise HTTPException(status_code=409, detail="預測快照寫入衝突")
    return apply_freshness_guard(stored, now=now)
