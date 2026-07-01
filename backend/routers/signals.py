from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from backend.services.reader import available_symbols, load_signal_history
from backend.services.signal_engine import get_signal

router = APIRouter()


@router.get("/signals/{symbol}")
def get_signals(symbol: str):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return get_signal(symbol)


@router.get("/signals/{symbol}/history")
def get_signal_history(
    symbol: str,
    days:  int           = Query(default=360, ge=7, le=1825),
    start: Optional[str] = Query(default=None),
    end:   Optional[str] = Query(default=None),
):
    """信心分數歷史走勢(每日多空 + 分數),讀 DB daily_signal 表。"""
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return load_signal_history(symbol, days=days, start=start, end=end)


@router.get("/signals")
def get_all_signals():
    return [get_signal(sym) for sym in available_symbols()]
