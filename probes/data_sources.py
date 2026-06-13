"""Probe free data sources (AkShare/BaoStock) for required fields and PIT derivability."""
from datetime import date, datetime

import pandas as pd


def fetch_akshare_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",
    )
    df = df.rename(
        columns={
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df[["trade_date", "open", "high", "low", "close", "volume"]]


def fetch_baostock_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    import baostock as bs

    bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            symbol,
            "date,open,high,low,close,volume",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            frequency="d",
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(
            rows, columns=["trade_date", "open", "high", "low", "close", "volume"]
        )
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df
    finally:
        bs.logout()


def derive_available_at(trade_date: date) -> datetime:
    """Daily OHLC available_at rule: trade_date + 15:00 (close)."""
    return datetime.combine(trade_date, datetime.min.time()).replace(hour=15)
