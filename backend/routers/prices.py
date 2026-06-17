from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from backend.services.reader import load_prices, available_symbols

router = APIRouter()


@router.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    days:  int           = Query(default=180, ge=7, le=1825),
    start: Optional[str] = Query(default=None),
    end:   Optional[str] = Query(default=None),
):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return load_prices(symbol, days=days, start=start, end=end)
