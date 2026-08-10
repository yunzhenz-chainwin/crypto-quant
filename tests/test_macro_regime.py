"""宏觀環境規則核心與檢定工具的行為測試。

重點在「證據會不會被悄悄灌水」：
  - 判讀只能用當日與更早的資料（無前視）
  - 湊不齊驅動因子時不得表態
  - 美股假日的缺值要沿用前值，不能憑空製造環境轉折
  - 重疊視窗的 t 值必須被 HAC 修正壓下來（否則面板會拿灌水的顯著性背書）
"""
import numpy as np
import pandas as pd
import pytest

from src.macro_eval import mean_with_hac_t, non_overlap_t
from src.macro_regime import DRIVER_KEYS, aggregate, build_factor, classify, regime_series


def _frame(n=40, **overrides):
    """平盤的宏觀序列（所有因子皆判 NEUTRAL），再由測試逐一覆寫想測的欄位。"""
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    data = {"dxy": 100.0, "vix": 20.0, "us10y": 4.0, "spx": 5000.0}
    data.update(overrides)
    return pd.DataFrame({k: [v] * n for k, v in data.items()}, index=idx)


def test_vix_uses_level_not_change():
    assert classify("VIX", 30.0, 0.0)[0] == "HEADWIND"
    assert classify("VIX", 12.0, 0.0)[0] == "TAILWIND"
    assert classify("VIX", 20.0, 99.0)[0] == "NEUTRAL"


def test_missing_input_is_not_neutral():
    """沒抓到資料 ≠ 判定中性：回 None 才不會稀釋彙總的分母。"""
    assert classify("DXY", None, None) == (None, None)
    assert build_factor("DXY", None, None) is None


def test_aggregate_needs_two_net_votes():
    assert aggregate(dict.fromkeys(DRIVER_KEYS, "TAILWIND"))["verdict"] == "RISK_ON"
    assert aggregate(dict.fromkeys(DRIVER_KEYS, "HEADWIND"))["verdict"] == "RISK_OFF"
    # 1 比 0 只是雜訊，不該被講成方向
    assert aggregate({"DXY": "TAILWIND", "VIX": "NEUTRAL"})["verdict"] == "NEUTRAL"


def test_regime_series_is_causal():
    """把未來某天改成極端值，不得改變在那之前任何一天的判讀。"""
    frame = _frame(60)
    baseline = regime_series(frame)["verdict"].tolist()

    # 同時衝擊兩個驅動（美股大漲＋美元大跌）才會讓彙總真的翻成 RISK_ON，
    # 只動一個因子淨值僅 +1、依規則仍是 NEUTRAL，測不出「之後有反映」。
    shocked = frame.copy()
    shocked.iloc[50:, shocked.columns.get_loc("spx")] = 9999.0
    shocked.iloc[50:, shocked.columns.get_loc("dxy")] = 50.0
    after = regime_series(shocked)["verdict"].tolist()

    assert baseline[:50] == after[:50]      # 未來的資料不得回頭改寫過去的判讀
    assert baseline[50:] != after[50:]      # 但衝擊發生之後本來就該反映出來


def test_incomplete_drivers_do_not_take_a_side():
    """開頭沒有 5 日基準 → 湊不齊 4 個驅動 → 一律 NEUTRAL。"""
    reg = regime_series(_frame(10))
    assert (reg["verdict"].iloc[:5] == "NEUTRAL").all()
    assert (reg["n_drivers"].iloc[:5] < len(DRIVER_KEYS)).all()


def test_market_holiday_gap_does_not_flip_regime():
    """
    美股休市、黃金與美元照常交易的那一天不得被判成環境轉折。
    情境：連續放空風險（VIX 高）→ 中間一天股債缺值，判讀必須沿用前值。
    """
    frame = _frame(30, vix=30.0)
    frame.iloc[20, frame.columns.get_loc("vix")] = np.nan
    frame.iloc[20, frame.columns.get_loc("spx")] = np.nan
    frame.iloc[20, frame.columns.get_loc("us10y")] = np.nan

    reg = regime_series(frame)
    assert reg["verdict"].iloc[20] == reg["verdict"].iloc[19]
    assert reg["n_drivers"].iloc[20] == len(DRIVER_KEYS)

    # 關掉補值就會出現那個假轉折——這正是補值要修掉的東西
    raw = regime_series(frame, ffill_limit=0)
    assert raw["n_drivers"].iloc[20] < len(DRIVER_KEYS)


def test_hac_t_is_smaller_than_naive_on_overlapping_data():
    """
    重疊視窗會讓普通 t 值灌水；HAC 修正後必須明顯變小，
    否則前台會拿一個假的顯著性當證據。
    """
    rng = np.random.default_rng(20260810)
    daily = rng.normal(0.05, 1.0, 1200)
    overlapping = pd.Series(daily).rolling(5).sum().dropna().to_numpy()

    naive_t = overlapping.mean() / (overlapping.std(ddof=1) / np.sqrt(len(overlapping)))
    _, hac_t = mean_with_hac_t(overlapping, lag=5)

    assert abs(hac_t) < abs(naive_t)
    assert abs(hac_t) == pytest.approx(abs(naive_t) / np.sqrt(5), rel=0.5)


def test_non_overlap_subsample_thins_the_series():
    series = pd.Series(np.arange(100, dtype=float))
    _, _, n = non_overlap_t(series, h=5)
    assert n == 20
