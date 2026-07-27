import requests

from backend.routers import sentiment


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


class _Session:
    def __init__(self, *, data=None, error=None):
        self.trust_env = True
        self._data = data
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _url, timeout):
        assert self.trust_env is False
        assert timeout == 10
        if self._error:
            raise self._error
        return _Response(self._data)


def test_fear_greed_ignores_environment_proxy(monkeypatch):
    sentiment._cache.clear()
    expected = [{"value": "47", "value_classification": "Neutral"}]
    monkeypatch.setattr(
        sentiment.requests,
        "Session",
        lambda: _Session(data=expected),
    )

    assert sentiment.fear_greed(limit=1) == expected


def test_fear_greed_uses_database_when_provider_is_unavailable(monkeypatch):
    sentiment._cache.clear()
    monkeypatch.setattr(
        sentiment.requests,
        "Session",
        lambda: _Session(error=requests.exceptions.ProxyError("proxy unavailable")),
    )
    monkeypatch.setattr(
        sentiment,
        "load_fear_greed_history",
        lambda days: [
            {"date": "2026-07-25", "value": 38, "label": "Fear"},
            {"date": "2026-07-26", "value": 44, "label": "Fear"},
        ],
    )

    result = sentiment.fear_greed(limit=2)

    assert [item["value"] for item in result] == ["44", "38"]
    assert result[0]["timestamp"] == "1785024000"
    assert result[0]["value_classification"] == "Fear"
