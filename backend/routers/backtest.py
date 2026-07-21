from fastapi import APIRouter, HTTPException, Query, Request
from backend.services.reader import available_symbols
from backend.services.backtest_engine import get_backtest
from backend.services.app_db import load_backtest_summary, load_backtest_trades
from backend.services.rate_limiter import RATE_LIMITER, enforce_rate_limit

router = APIRouter()


@router.get("/backtest/db/summary")
def backtest_db_summary():
    """所有幣種『已入庫』的回測績效摘要（依總報酬排序），供跨幣比較。"""
    return load_backtest_summary()


@router.get("/backtest/db/{symbol}/trades")
def backtest_db_trades(
    symbol: str,
    limit: int = Query(default=0, ge=0, le=2000,
                       description="只取最近 N 筆；0 = 全部"),
):
    """某幣『已入庫』的回測進出場明細（勝率／報酬／持有天數的原始逐筆資料）。"""
    return load_backtest_trades(symbol.upper(), limit=limit)


@router.get("/backtest/{symbol}")
def backtest_symbol(
    request: Request,
    symbol: str,
    stop_loss:   float = Query(default=-0.06, ge=-0.30, le=-0.01, multiple_of=0.01,
                               description="停損比例，例如 -0.06 = -6%"),
    take_profit: float = Query(default=0.20,  ge=0.05,  le=1.0, multiple_of=0.01,
                               description="停利比例，例如 0.20 = +20%"),
    fee_rate: float = Query(default=0.001, ge=0.0, le=0.01, multiple_of=0.0001,
                            description="單邊手續費率，例如 0.001 = 0.1%"),
    slippage_rate: float = Query(default=0.0005, ge=0.0, le=0.02, multiple_of=0.0001,
                                 description="單邊滑價率，例如 0.0005 = 0.05%"),
):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} no data")
    enforce_rate_limit(
        request,
        scope="backtest_single",
        limit=12,
        window_seconds=60,
        limiter=RATE_LIMITER,
    )
    return get_backtest(
        symbol,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )


@router.get("/backtest")
def backtest_all():
    """Return the persisted daily summary instead of cold-running every coin.

    Detailed parameterized research remains available at ``/backtest/{symbol}``;
    the collection endpoint must stay cheap and bounded for public dashboards.
    """
    return load_backtest_summary()
