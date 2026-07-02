"""
ai.py — AI 分析機器人 API

  GET  /api/ai/analysis/{symbol}?gpt=1&force=0   完整分析（規則引擎 + GPT）
       gpt=0 → 只跑規則引擎（即時、免費），前端先顯示這份，再補 GPT 深度分析
  POST /api/ai/ask                               針對幣種提問（GPT，無金鑰時降級本地）
  GET  /api/ai/config                            前端探測：GPT 有沒有啟用（不洩漏金鑰）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.reader import available_symbols
from backend.services import ai_analyst

router = APIRouter()


@router.get("/ai/analysis/{symbol}")
def get_analysis(symbol: str, gpt: int = 1, force: int = 0):
    symbol = symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    return ai_analyst.analyze(symbol, use_gpt=bool(gpt), force=bool(force))


class AskReq(BaseModel):
    symbol: str
    question: str
    history: list[dict] | None = None   # 最近幾輪對話 [{"q":…, "a":…}]，做連續追問


@router.post("/ai/ask")
def post_ask(body: AskReq):
    symbol = body.symbol.upper()
    if symbol not in available_symbols():
        raise HTTPException(status_code=404, detail=f"{symbol} 無資料")
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="請輸入問題")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="問題請控制在 500 字內")
    history = (body.history or [])[-3:]   # 最多帶 3 輪，控制 token 與濫用
    return ai_analyst.ask(symbol, q, history=history)


@router.get("/ai/config")
def get_ai_config():
    cfg = ai_analyst.gpt_config()
    return {"gpt_enabled": bool(cfg["api_key"]), "model": cfg["model"]}
