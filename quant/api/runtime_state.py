"""API data source backed by the latest runtime state file."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quant.runtime.paper import default_state_path


class RuntimeStateUnavailable(RuntimeError):
    pass


def load_state() -> dict[str, Any]:
    path = Path(os.environ.get("TRADE_RUNTIME_STATE", str(default_state_path())))
    if not path.exists():
        raise RuntimeStateUnavailable(
            f"runtime state not found: {path}; run trade-paper-run first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def get_collection(name: str) -> Any:
    state = load_state()
    if name not in state:
        raise RuntimeStateUnavailable(f"runtime state missing collection: {name}")
    return state[name]


def get_symbol_collection(name: str, symbol: str) -> list[dict]:
    collection = get_collection(name)
    if symbol not in collection:
        raise ValueError("symbol outside current runtime state")
    return collection[symbol]
