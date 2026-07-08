from fastapi import APIRouter
from backend.services.macro import get_macro

router = APIRouter()


@router.get("/macro")
def macro():
    """宏觀環境（規則式，市場整體背景）：DXY/VIX/美債/標普/黃金/BTC主導率/總市值 → 對加密順風/逆風。"""
    return get_macro()
