from fastapi import APIRouter
from backend.services.reader import available_symbols, last_updated

router = APIRouter()


@router.get("/symbols")
def get_symbols():
    return available_symbols()


@router.get("/status")
def get_status():
    # 附帶「指標交叉驗證」摘要(只給通過數,不含技術細節),供前台信任徽章用
    try:
        from src.verify_indicators import cached_result
        v = cached_result()
        verification = {"ok": v["ok"], "passed": v["passed"], "total": v["total"]}
    except Exception:
        verification = None
    return {"last_updated": last_updated(), "verification": verification}


@router.get("/verify")
def get_verify():
    """指標交叉驗證的完整結果(公開,供前台彈窗顯示給使用者)。
    內容只有各幣通過與否 + 微小誤差,無敏感資訊。"""
    try:
        from src.verify_indicators import cached_result
        return cached_result()
    except Exception as e:
        return {"ok": False, "error": str(e), "passed": 0, "total": 0, "coins": []}
