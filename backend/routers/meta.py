from fastapi import APIRouter
from backend.services.reader import (
    available_symbols, last_updated, intervals_available, data_versions,
)

router = APIRouter()


@router.get("/symbols")
def get_symbols():
    return available_symbols()


@router.get("/intervals")
def get_intervals():
    """各週期有資料的幣種，例如 {"1d": [...], "1h": ["BTCUSDT","ETHUSDT"]}。"""
    return intervals_available()


@router.get("/status")
def get_status():
    # 附帶「指標交叉驗證」摘要(只給通過數,不含技術細節),供前台信任徽章用
    try:
        from src.verify_indicators import cached_result
        v = cached_result()
        verification = {"ok": v["ok"], "passed": v["passed"], "total": v["total"]}
    except Exception:
        verification = None
    # data_version：各週期最新 K 棒時間戳＋筆數。前端每分鐘輪詢比對，
    # 有變化才重拉重資料（K 線/指標/訊號），做到「不用重整、資料自動更新」。
    return {
        "last_updated": last_updated(),
        "verification": verification,
        "data_version": data_versions(),
    }


@router.get("/verify")
def get_verify():
    """指標交叉驗證的完整結果(公開,供前台彈窗顯示給使用者)。
    內容只有各幣通過與否 + 微小誤差,無敏感資訊。"""
    try:
        from src.verify_indicators import cached_result
        return cached_result()
    except Exception as e:
        return {"ok": False, "error": str(e), "passed": 0, "total": 0, "coins": []}
