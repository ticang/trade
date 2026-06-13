"""Shared fixtures and synthetic data helpers for probes."""
import numpy as np
import pandas as pd

def synth_factor_panel(n_symbols: int, n_factors: int, n_days: int) -> pd.DataFrame:
    """Generate a synthetic factor panel: (factor, trade_date, symbol, value)."""
    rng = np.random.default_rng(42)
    symbols = [f"s{i:05d}" for i in range(n_symbols)]
    days = pd.date_range("2024-01-02", periods=n_days, freq="B").date
    rows = []
    for f in range(n_factors):
        vals = rng.standard_normal(n_days * n_symbols).astype("float32")
        rows.append(pd.DataFrame({
            "factor": f"f_{f}",
            "trade_date": np.tile(days, n_symbols),
            "symbol": np.repeat(symbols, n_days),
            "value": vals,
        }))
    return pd.concat(rows, ignore_index=True)
