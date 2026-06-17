from fastapi import APIRouter, HTTPException, Query
from backend.services.reader import load_indicators, available_symbols

router = APIRouter()


@router.get("/indicators/{symbol}")
def get_indicators(symbol: str, days: int = Query(default=180, ge=7, le=1825)):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return load_indicators(symbol, days)
