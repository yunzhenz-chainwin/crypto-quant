from fastapi import APIRouter, HTTPException
from backend.services.reader import available_symbols
from backend.services.signal_engine import get_signal

router = APIRouter()


@router.get("/signals/{symbol}")
def get_signals(symbol: str):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return get_signal(symbol)


@router.get("/signals")
def get_all_signals():
    return [get_signal(sym) for sym in available_symbols()]
