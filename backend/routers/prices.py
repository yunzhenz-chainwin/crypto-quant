from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from backend.services.reader import load_prices, available_symbols, VALID_INTERVALS

router = APIRouter()


@router.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    days:  int           = Query(default=180, ge=1, le=1825),
    start: Optional[str] = Query(default=None),
    end:   Optional[str] = Query(default=None),
    interval: str        = Query(default="1d"),
):
    symbol = symbol.upper()
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval 僅支援 {'/'.join(VALID_INTERVALS)}")
    if symbol not in available_symbols(interval):
        raise HTTPException(status_code=404, detail=f"{symbol} 無 {interval} 資料")
    return load_prices(symbol, days=days, start=start, end=end, interval=interval)
