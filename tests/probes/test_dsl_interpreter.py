import numpy as np
import pandas as pd
from probes.dsl.interpreter import evaluate

def _panel():
    # 5 symbols, 30 days; close prices increasing per symbol.
    symbols = [f"s{i}" for i in range(5)]
    days = pd.date_range("2024-01-02", periods=30, freq="B").date
    rows = []
    for i, s in enumerate(symbols):
        base = 10.0 + i
        for j, d in enumerate(days):
            rows.append({"symbol": s, "trade_date": d, "close": base + j * 0.1})
    return pd.DataFrame(rows)

def test_rank_of_ts_mean_matches_pandas():
    df = _panel()
    expr = "rank(ts_mean(close, 20))"
    got = evaluate(expr, df)  # Series indexed by symbol
    # Hand-written reference: per-symbol rolling mean, then cross-sectional pct rank.
    ts_mean_ref = (
        df.sort_values(["symbol", "trade_date"]).groupby("symbol")["close"]
        .rolling(20).mean().reset_index(level=0, drop=True)
    )
    ts_mean_ref.index = df.index
    ref = df.assign(_ts_mean=ts_mean_ref.values)
    ref["_rank"] = ref.groupby("trade_date")["_ts_mean"].rank(pct=True)
    last_day = df["trade_date"].max()
    ref_last = ref[ref.trade_date == last_day].set_index("symbol")["_rank"]
    # Sanity: ranked values in [0,1]
    assert got.between(0, 1).all()
    # Ordering preserved: symbol with highest close has highest rank
    assert got.idxmax() == "s4"
    # DSL output matches the hand-written pandas reference on the last cross-section.
    np.testing.assert_array_almost_equal(got.values, ref_last.reindex(got.index).values)
