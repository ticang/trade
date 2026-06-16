from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
loaded_quant = sys.modules.get("quant")
if loaded_quant is not None and "tests" in str(getattr(loaded_quant, "__file__", "")):
    sys.modules.pop("quant", None)

from quant.api.app import create_app


def test_readonly_api_serves_monitor_trade_research_contracts():
    client = TestClient(create_app())

    markets = client.get("/api/markets")
    assert markets.status_code == 200
    assert markets.json()[0] == {
        "symbol": "000001",
        "name": "平安银行",
        "last": 11.34,
        "change": 0.89,
        "volume": 234_000_000,
    }

    kline = client.get("/api/kline/600519")
    assert kline.status_code == 200
    first_bar = kline.json()[0]
    assert set(first_bar) == {"ts", "open", "high", "low", "close", "volume"}
    assert len(kline.json()) == 240

    sentiment = client.get("/api/sentiment/600519")
    assert sentiment.status_code == 200
    assert set(sentiment.json()[0]) == {"ts", "score"}

    for path in [
        "/api/account",
        "/api/positions",
        "/api/orders",
        "/api/fills",
        "/api/risk",
        "/api/alerts",
        "/api/strategies",
        "/api/factor-eval",
        "/api/backtest",
        "/api/strategy-lifecycle",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.json()


def test_readonly_api_rejects_symbols_outside_current_main_board_scope():
    client = TestClient(create_app())

    resp = client.get("/api/kline/688981")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "symbol outside current main-board scope"
