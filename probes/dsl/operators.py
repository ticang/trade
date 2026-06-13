"""DSL operators over a long-form panel DataFrame (columns: symbol, trade_date, <fields>)."""
import pandas as pd

def ts_mean(df: pd.DataFrame, field: str, window: int) -> pd.Series:
    return df.sort_values(["symbol", "trade_date"]).groupby("symbol")[field].rolling(window).mean().reset_index(level=0, drop=True)

def rank(df: pd.DataFrame, series: pd.Series) -> pd.Series:
    # Cross-sectional percentile rank within each trade_date.
    tmp = df[["trade_date"]].copy()
    tmp["__v"] = series.values
    return tmp.groupby("trade_date")["__v"].rank(pct=True)

def group_neutral(df: pd.DataFrame, series: pd.Series, group_field: str) -> pd.Series:
    tmp = df[[group_field]].copy()
    tmp["__v"] = series.values
    return tmp.groupby(group_field)["__v"].transform(lambda s: s - s.mean())
