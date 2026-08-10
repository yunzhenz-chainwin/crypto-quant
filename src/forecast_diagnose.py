# -*- coding: utf-8 -*-
"""
forecast_diagnose.py — 研究預測「為何永遠拒答、以及它到底準不準」（唯讀診斷）

起因（2026-08-10）：forecast_snapshot_v2 累積 723 筆，狀態 100% abstain，
前台「統一判斷摘要」的「① 技術方向 vs ② 研究預測方向」因此從未真正比對過。
這支把兩個問題一次查清楚，且完全不寫入任何資料：

  Q1 分數為什麼上不去？
     信心分數 = 100 × edge × sample_strength × interval_width_penalty
     （見 src/forecasting.py）。拆開三個乘項的實際分布，並反推「要多極端才會及格」。

  Q2 就算讓它開口，它講得準嗎？
     拿已到期結算的 forecast_outcome_v2 對真實漲跌，跟「最笨的對照組——
     完全不用模型、一律猜較常出現的方向」比較。這個對照組是必要的：
     在下跌居多的期間，一個幾乎只喊跌的模型也會有漂亮的命中率。

── 2026-08-10 首次執行結果 ─────────────────────────────────────────────
  Q1：信心分數 min 0 / 中位 6 / max 29，門檻 40，0/723 及格。
      反推：要 40 分需要「歷史上漲機率 ≥ 70%」，而實際觀察到的最高是 56.8%。
      → 不是標準訂得嚴，是尺度訂錯了：真實有用的預測長得像 55% vs 50%。
  Q2：528 筆已結算，1／5／10 日三個天期的命中率全部輸給「一律猜跌」
      （-1.8 / -3.6 / -8.1 個百分點），Brier 也全部輸給「一律猜基準率」。
      且 5 日那組看似 168 筆，實為 12 個預測日 × 15 幣、且預測日彼此重疊 5 天，
      真正獨立的樣本只有兩三個。
  結論：模型的「拒答」是對的——它誠實地說自己沒把握。
      壞的是產品設計（讓一個注定天天說同一句話的框佔著版面正中央）。
      ⚠ 不可用「把門檻從 40 降到 25」來解決：那是為了畫面好看而放水，
        而且 Q2 顯示它現在根本沒有勝過最笨對照組的能力。

重跑：python src/forecast_diagnose.py
（資料越久越有價值；等獨立樣本夠多，再重新檢討尺度與是否可發布。）
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "app.db"
RELEASE_THRESHOLD = 40      # src/forecasting.py 的 MIN_READY_CONFIDENCE


def _pct(values, q):
    return float(np.percentile(values, q)) if len(values) else float("nan")


def load_snapshots(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT horizon_days, payload_json FROM forecast_snapshot_v2 ORDER BY as_of").fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        out.append({
            "h": row["horizon_days"],
            "score": (payload.get("confidence") or {}).get("score"),
            "p_up": (payload.get("probabilities") or {}).get("up"),
            "status": payload.get("status"),
        })
    return out


def load_resolved(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT s.horizon_days h, s.as_of, s.symbol, s.payload_json sp, o.realized_return_pct ret
        FROM forecast_snapshot_v2 s
        JOIN forecast_outcome_v2 o ON o.forecast_id = s.forecast_id
    """).fetchall()
    out = []
    for row in rows:
        p_up = (json.loads(row["sp"]).get("probabilities") or {}).get("up")
        if p_up is None or row["ret"] is None:
            continue
        out.append({"h": row["h"], "p_up": float(p_up),
                    "up": 1 if row["ret"] > 0 else 0,
                    "as_of": row["as_of"][:10], "symbol": row["symbol"]})
    return out


def report_scale(snaps: list[dict]) -> None:
    print("=" * 72)
    print("  Q1 信心分數為什麼上不去？")
    print("=" * 72)
    scores = [s["score"] for s in snaps if s["score"] is not None]
    if not scores:
        print("  沒有可用的信心分數")
        return
    passed = sum(1 for s in scores if s >= RELEASE_THRESHOLD)
    print(f"  分數分布：min {min(scores)} / 中位 {_pct(scores, 50):.0f} / "
          f"p90 {_pct(scores, 90):.0f} / max {max(scores)}   （門檻 {RELEASE_THRESHOLD}）")
    print(f"  及格筆數：{passed} / {len(scores)}")

    p_ups = [s["p_up"] for s in snaps if isinstance(s["p_up"], (int, float))]
    if p_ups:
        edges = [abs(p - 0.5) * 2 for p in p_ups]
        print(f"\n  edge = |P(上漲) − 0.5| × 2")
        print(f"    P(上漲)：min {min(p_ups):.3f} / 中位 {_pct(p_ups, 50):.3f} / max {max(p_ups):.3f}")
        print(f"    edge   ：中位 {_pct(edges, 50):.3f} / max {max(edges):.3f}")
        print("\n  反推：分數要及格需要什麼條件（假設樣本充足、無區間懲罰）")
        need = RELEASE_THRESHOLD / 100.0
        print(f"    需要 edge ≥ {need:.2f}，即 P(上漲) ≥ {0.5 + need / 2:.0%} "
              f"或 ≤ {0.5 - need / 2:.0%}")
        print(f"    實際觀察到的最極端 P(上漲) = {max(p_ups):.1%} / {min(p_ups):.1%}")


def report_skill(resolved: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("  Q2 它講得準嗎？（對照組＝完全不用模型，一律猜較常出現的方向）")
    print("=" * 72)
    if not resolved:
        print("  尚無已結算的預測")
        return
    for h in sorted({r["h"] for r in resolved}):
        sub = [r for r in resolved if r["h"] == h]
        y = np.array([r["up"] for r in sub])
        p = np.array([r["p_up"] for r in sub])
        model_hit = float(((p > 0.5) == (y == 1)).mean())
        dumb_hit = float(max(y.mean(), 1 - y.mean()))
        brier = float(((p - y) ** 2).mean())
        brier_base = float(((y.mean() - y) ** 2).mean())
        days = len({r["as_of"] for r in sub})
        symbols = len({r["symbol"] for r in sub})
        gap = (model_hit - dumb_hit) * 100
        print(f"\n  持有 {h} 日：{len(sub)} 筆 = {days} 個預測日 × {symbols} 個幣")
        print(f"    模型命中率            {model_hit:6.1%}")
        print(f"    一律猜{'跌' if y.mean() < 0.5 else '漲'}（不用模型）  {dumb_hit:6.1%}")
        print(f"    → {'模型勝出' if gap > 0 else '模型輸給最笨對照組'}（{gap:+.1f} 個百分點）")
        print(f"    Brier {brier:.4f} vs 一律猜基準率 {brier_base:.4f}"
              f"（{'贏' if brier < brier_base else '輸'}，越低越好）")
        if h > 1:
            print(f"    ⚠ 預測日彼此重疊 {h} 天，實質獨立樣本遠少於 {len(sub)} 筆")


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    snaps = load_snapshots(conn)
    resolved = load_resolved(conn)
    print(f"\n研究預測診斷：快照 {len(snaps)} 筆、已結算 {len(resolved)} 筆\n")
    report_scale(snaps)
    report_skill(resolved)
    print("\n" + "=" * 72)
    print("  ⚠ 修法禁忌：不可為了讓畫面有結論而調低門檻。")
    print("     Q2 顯示它目前連最笨的對照組都贏不了，讓它開口只是把雜訊講成結論。")
    print("=" * 72)


if __name__ == "__main__":
    main()
