from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
loaded_quant = sys.modules.get("quant")
if loaded_quant is not None and "tests" in str(getattr(loaded_quant, "__file__", "")):
    sys.modules.pop("quant", None)

from quant.api.app import create_app
from quant.runtime.paper import run_paper_session


def test_readonly_api_serves_runtime_state_contracts(tmp_path, monkeypatch):
    state_path = tmp_path / "latest_state.json"
    run_paper_session(n_days=20, n_symbols=5, accounts=["acct-a"], state_path=state_path)
    monkeypatch.setenv("TRADE_RUNTIME_STATE", str(state_path))
    client = TestClient(create_app())

    markets = client.get("/api/markets")
    assert markets.status_code == 200
    assert set(markets.json()[0]) == {"symbol", "name", "last", "change", "volume"}

    symbol = markets.json()[0]["symbol"]
    kline = client.get(f"/api/kline/{symbol}")
    assert kline.status_code == 200
    first_bar = kline.json()[0]
    assert set(first_bar) == {"ts", "open", "high", "low", "close", "volume"}
    assert len(kline.json()) == 20

    sentiment = client.get(f"/api/sentiment/{symbol}")
    assert sentiment.status_code == 200
    assert set(sentiment.json()[0]) == {"ts", "score"}

    signals = client.get(f"/api/signals/{symbol}")
    assert signals.status_code == 200
    if signals.json():
        assert set(signals.json()[0]) == {"ts", "direction", "label", "price"}

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


def test_readonly_api_rejects_symbols_outside_current_runtime_state(tmp_path, monkeypatch):
    state_path = tmp_path / "latest_state.json"
    run_paper_session(n_days=20, n_symbols=5, accounts=["acct-a"], state_path=state_path)
    monkeypatch.setenv("TRADE_RUNTIME_STATE", str(state_path))
    client = TestClient(create_app())

    resp = client.get("/api/kline/688981")

    assert resp.status_code == 404


def test_readonly_api_returns_503_when_runtime_state_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_RUNTIME_STATE", str(tmp_path / "missing.json"))
    client = TestClient(create_app())

    resp = client.get("/api/markets")

    assert resp.status_code == 503
    assert "run trade-paper-run first" in resp.json()["detail"]
