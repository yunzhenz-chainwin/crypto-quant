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
    question: str
    symbol: str | None = None           # 舊呼叫相容（指定幣）
    context_symbol: str | None = None   # 聊天室目前的幣（黏性；問題沒提到幣時沿用）
    history: list[dict] | None = None   # 最近幾輪對話 [{"q":…, "a":…}]，做連續追問


@router.post("/ai/ask")
def post_ask(body: AskReq):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="請輸入問題")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="問題請控制在 500 字內")

    avail = available_symbols()
    fallback = next((s for s in ((body.symbol or "").upper(),
                                 (body.context_symbol or "").upper(), "BTCUSDT")
                     if s and s in avail), None)
    if not fallback:
        raise HTTPException(status_code=404, detail="無可用幣種資料")

    # 免選幣三層防護：
    # ① 精確/錯字容忍偵測幣種 ② 偵測不到但「像在問某顆沒追蹤的幣」→ 誠實說沒資料，
    #    絕不默默用別的幣回答（答非所問比不回答更糟）③ 都不是 → 沿用聊天室目前的幣
    detected, guessed = ai_analyst.detect_symbol(q)
    # 全站模式：聊天室沒綁定幣（總覽頁）且問題也沒提到幣 → 小Q 是「整個網站的」
    # 小幫手，不預設任何一顆幣：行情/知識類反問哪顆幣、教學類以比特幣為例並註明。
    market_mode = (not detected and not (body.symbol or "").strip()
                   and not (body.context_symbol or "").strip())
    if not detected:
        unknown = ai_analyst.find_unknown_coin(q)
        if unknown:
            from backend.services.app_db import log_ai_chat
            answer = ai_analyst.unsupported_coin_reply(unknown)
            log_ai_chat("MARKET" if market_mode else fallback, q, answer, "local")
            return {"answer": answer, "source": "local",
                    "symbol": None if market_mode else fallback,
                    "name_zh": None if market_mode else ai_analyst._coin_zh(fallback),
                    "detected": False, "unsupported": unknown}

    if market_mode:
        from backend.services import canned_qa
        from backend.services.app_db import log_ai_chat
        mk = canned_qa.match_kind(q)
        info = canned_qa.entry_info(mk) if mk else None
        base = {"symbol": None, "name_zh": None, "detected": False, "guessed": False}

        # 打招呼 → 全市場版開場白（不提任何單一幣）
        if info and info["category"] == "閒聊" and info["example"].startswith("你好"):
            answer = canned_qa.market_greeting()
            log_ai_chat("MARKET", q, answer, "canned")
            return {**base, "answer": answer, "source": "canned", "intent": "閒聊:全站打招呼"}

        # 行情建議 / 幣種知識類但沒講幣 → 反問哪顆幣，絕不擅自替使用者選
        if info and info["coin_specific"] and (info["kind"] == "knowledge"
                                               or info["category"] == "行情"):
            answer = canned_qa.ask_which_coin(q)
            log_ai_chat("MARKET", q, answer, "canned")
            return {**base, "answer": answer, "source": "canned", "intent": "全站:反問幣種"}

        # 教學/觀念/平台/大盤等通用問題 → 照答；若引用了數據，註明以比特幣為例
        note = "\n\n※ 以上數據以**比特幣**為例；想看特定幣，把幣名加進問題即可。"
        canned = canned_qa.try_answer("BTCUSDT", q)
        if canned:
            answer = canned["answer"] + (note if canned.get("coin_specific") else "")
            enhanced = ai_analyst.enhance_answer(q, answer, canned["intent"], "MARKET",
                                                 ctx=canned.get("ctx"))
            source = "canned+gpt" if enhanced else "canned"
            log_ai_chat("MARKET", q, enhanced or answer, source)
            return {**base, "answer": enhanced or answer, "source": source,
                    "intent": canned["intent"]}

        # 沒命中固定庫 → 走一般問答（以 BTC 數據為底），同樣註明
        out = ai_analyst.ask("BTCUSDT", q, history=(body.history or [])[-3:])
        out["answer"] = out["answer"] + note
        out.update(base)
        return out

    symbol = detected if (detected and detected in avail) else fallback

    # 第 1 層：固定問答庫（54 條 + 幣種知識）。命中 → 豐富固定答案為骨幹；
    # GPT 可用時再做「優化潤飾」（鐵則：不得改數據/立場），失敗自動退回固定答案。
    from backend.services import canned_qa
    canned = canned_qa.try_answer(symbol, q)
    if canned:
        from backend.services.app_db import log_ai_chat
        answer = canned["answer"]
        source = "canned"
        enhanced = ai_analyst.enhance_answer(q, answer, canned["intent"], symbol,
                                             ctx=canned.get("ctx"))
        if enhanced:
            answer = enhanced
            source = "canned+gpt"
        if guessed:
            tk = symbol.replace("USDT", "")
            answer = (f"（你說的應該是 **{ai_analyst._coin_zh(symbol)} {tk}**）\n\n" + answer)
        log_ai_chat(symbol, q, answer, source)
        return {"answer": answer, "source": source, "intent": canned["intent"],
                "symbol": symbol, "name_zh": ai_analyst._coin_zh(symbol),
                "detected": bool(detected), "guessed": guessed}

    history = (body.history or [])[-3:]   # 最多帶 3 輪，控制 token 與濫用
    out = ai_analyst.ask(symbol, q, history=history)
    if guessed:
        # 錯字猜測要明講，避免使用者沒發現答的是哪顆幣
        tk = symbol.replace("USDT", "")
        out["answer"] = (f"（你說的應該是 **{ai_analyst._coin_zh(symbol)} {tk}**，"
                         f"以下是它的狀況）\n\n" + out["answer"])
    out["symbol"] = symbol                            # 告訴前端實際回答的幣
    out["name_zh"] = ai_analyst._coin_zh(symbol)
    out["detected"] = bool(detected)                  # 是否由問題文字自動偵測
    out["guessed"] = guessed                          # 是否為錯字猜測
    return out


@router.get("/ai/config")
def get_ai_config():
    cfg = ai_analyst.gpt_config()
    return {"gpt_enabled": bool(cfg["api_key"]), "model": cfg["model"]}
