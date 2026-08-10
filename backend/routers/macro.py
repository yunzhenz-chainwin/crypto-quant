from fastapi import APIRouter, Query

from backend.services.macro import get_macro, get_macro_history

router = APIRouter()


@router.get("/macro")
def macro():
    """
    宏觀環境（規則式，市場整體背景）：DXY/VIX/美債/標普/黃金/BTC主導率/總市值
    → 對加密順風/逆風，另含：
      evidence  這套判斷在歷史上的預測力檢定結果（含不顯著時的照實說明）
      linkage   BTC 與各宏觀序列的 60 日滾動相關（此刻宏觀該給多少權重）
    """
    return get_macro()


@router.get("/macro/history")
def macro_history(days: int = Query(365, ge=30, le=2500)):
    """逐日宏觀環境標籤時間軸（與面板同一套規則重算，供前台看環境變化與自行核對）。"""
    return get_macro_history(days)
