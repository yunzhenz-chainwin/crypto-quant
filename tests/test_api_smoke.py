"""
API smoke test — 確認主要端點在應用組裝後可正常回應。

用 FastAPI TestClient（不使用 with，故不觸發 lifespan＝不啟動背景排程），
只驗證路由 / 序列化 / 主要服務可運作，屬最輕量的煙霧測試。

執行：
  .venv\\Scripts\\python.exe -m pytest            # 全部
  .venv\\Scripts\\python.exe -m pytest tests -q
"""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_symbols_returns_list():
    r = client.get("/api/symbols")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_signals_all():
    r = client.get("/api/signals")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_backtest_btc_shape():
    r = client.get("/api/backtest/BTCUSDT")
    assert r.status_code == 200
    body = r.json()
    assert body.get("symbol") == "BTCUSDT"
    assert "metrics" in body


def test_backtest_rejects_unbounded_float_parameter_variants():
    response = client.get("/api/backtest/BTCUSDT?stop_loss=-0.055")
    assert response.status_code == 422


def test_unknown_symbol_404():
    r = client.get("/api/backtest/NOTACOIN")
    assert r.status_code == 404
