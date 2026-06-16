from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from quant.api import sample_data


def create_app() -> FastAPI:
    app = FastAPI(title="Trade Read-only API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/markets")
    def get_markets() -> list[dict]:
        return sample_data.markets()

    @app.get("/api/kline/{symbol}")
    def get_kline(symbol: str) -> list[dict]:
        try:
            return sample_data.kline(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sentiment/{symbol}")
    def get_sentiment(symbol: str) -> list[dict]:
        try:
            return sample_data.sentiment(symbol)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/account")
    def get_account() -> list[dict]:
        return sample_data.account()

    @app.get("/api/positions")
    def get_positions() -> list[dict]:
        return sample_data.positions()

    @app.get("/api/orders")
    def get_orders() -> list[dict]:
        return sample_data.orders()

    @app.get("/api/fills")
    def get_fills() -> list[dict]:
        return sample_data.fills()

    @app.get("/api/risk")
    def get_risk() -> dict:
        return sample_data.risk()

    @app.get("/api/alerts")
    def get_alerts() -> list[dict]:
        return sample_data.alerts()

    @app.get("/api/strategies")
    def get_strategies() -> list[dict]:
        return sample_data.strategies()

    @app.get("/api/factor-eval")
    def get_factor_eval() -> list[dict]:
        return sample_data.factor_eval()

    @app.get("/api/backtest")
    def get_backtest() -> dict:
        return sample_data.backtest()

    @app.get("/api/strategy-lifecycle")
    def get_strategy_lifecycle() -> list[dict]:
        return sample_data.strategy_lifecycle()

    return app


app = create_app()
