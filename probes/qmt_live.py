"""Read-only QMT/xtquant live environment probe.

This probe is intentionally safe: it never places or cancels orders. It checks
whether xtquant imports, whether the market-data API can be called, and, only
when QMT_USERDATA_PATH is provided, whether a trader session can be constructed
for read-only account inspection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True)
class QmtLiveProbeConfig:
    account_id: str | None
    userdata_path: str | None
    symbol: str = "600519.SH"


@dataclass(frozen=True)
class QmtLiveProbeResult:
    status: str
    reason: str
    checks: dict[str, bool] = field(default_factory=dict)


def load_config(env: Mapping[str, str] | None = None) -> QmtLiveProbeConfig:
    source = os.environ if env is None else env
    return QmtLiveProbeConfig(
        account_id=_blank_to_none(source.get("QMT_ACCOUNT")),
        userdata_path=_blank_to_none(source.get("QMT_USERDATA_PATH")),
        symbol=source.get("QMT_PROBE_SYMBOL") or "600519.SH",
    )


def import_xtquant():
    try:
        import xtquant.xtdata as xtdata  # type: ignore[import-not-found]
        import xtquant.xttrader as xttrader  # type: ignore[import-not-found]
    except Exception:
        return None
    return xtdata, xttrader


def run_readonly_probe(
    config: QmtLiveProbeConfig,
    *,
    importer: Callable[[], object | None] = import_xtquant,
) -> QmtLiveProbeResult:
    checks = {
        "xtquant_import": False,
        "market_data_read": False,
        "market_data_health": False,
        "trader_readonly_handshake": False,
    }

    mods = importer()
    if mods is None:
        return QmtLiveProbeResult(
            status="blocked",
            reason="xtquant is not installed in the active Python environment",
            checks=checks,
        )

    xtdata, xttrader = mods  # type: ignore[misc]
    checks["xtquant_import"] = True

    try:
        xtdata.get_market_data_ex(
            field_list=["open", "high", "low", "close", "volume"],
            stock_list=[config.symbol],
            period="1d",
            count=1,
            dividend_type="none",
            fill_data=True,
        )
        checks["market_data_read"] = True
    except Exception as exc:
        return QmtLiveProbeResult(
            status="blocked",
            reason=f"market data read failed: {type(exc).__name__}: {exc}",
            checks=checks,
        )

    checks["market_data_health"] = _market_data_health(
        xtdata,
        config.symbol,
        config.userdata_path,
    )

    if not config.userdata_path:
        return QmtLiveProbeResult(
            status="blocked",
            reason="QMT_USERDATA_PATH is required for trader readonly handshake",
            checks=checks,
        )

    try:
        trader = xttrader.XtQuantTrader(config.userdata_path, 1)
        trader.start()
        trader.connect()
        if config.account_id and hasattr(trader, "get_stock_account"):
            trader.get_stock_account(config.account_id)
        elif hasattr(trader, "query_account_infos"):
            trader.query_account_infos()
        checks["trader_readonly_handshake"] = True
    except Exception as exc:
        return QmtLiveProbeResult(
            status="blocked",
            reason=f"trader readonly handshake failed: {type(exc).__name__}: {exc}",
            checks=checks,
        )

    return QmtLiveProbeResult(
        status="pass",
        reason="xtquant readonly probe passed",
        checks=checks,
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _market_data_health(xtdata, symbol: str, userdata_path: str | None) -> bool:  # noqa: ANN001
    get_full_tick = getattr(xtdata, "get_full_tick", None)
    if callable(get_full_tick):
        try:
            tick = get_full_tick([symbol]) or {}
            if isinstance(tick, dict) and tick:
                return True
        except Exception:
            pass

    kwargs = {
        "field_list": ["open", "high", "low", "close", "volume", "amount"],
        "stock_list": [symbol],
        "period": "1m",
        "count": 1,
        "dividend_type": "none",
        "fill_data": True,
    }
    if userdata_path:
        kwargs["data_dir"] = str(os.path.join(userdata_path, "datadir"))
    try:
        data = xtdata.get_market_data_ex(**kwargs)
    except Exception:
        return False
    if data is None:
        return False
    if isinstance(data, dict):
        value = data.get(symbol)
        if value is None:
            return False
        return len(value) > 0 if hasattr(value, "__len__") else True
    return len(data) > 0 if hasattr(data, "__len__") else True


def main() -> None:
    result = run_readonly_probe(load_config())
    print(f"status={result.status}")
    print(f"reason={result.reason}")
    for name, passed in result.checks.items():
        print(f"{name}={'PASS' if passed else 'BLOCKED'}")


if __name__ == "__main__":
    main()
