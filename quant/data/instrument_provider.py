"""Instrument 基础数据 Provider：从 seed YAML 加载并查询（设计 v0.5 §4.1.3）。

职责：
- from_seed：读 instrument_seed.yaml（或 store）构造 Instrument dict
- get / is_st / classify：供 rules_for 精分类使用
  * ST 时段命中 → board 改 'st'
  * 跨境 ETF → board 改 'etp_crossborder'
  * 未命中回退 classify_symbol 前缀映射
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from quant.data.instrument import Instrument, StPeriod
from quant.providers.trading_rule import classify_symbol, classify_with_instrument

# 默认 seed 路径：quant/data/instrument_seed.yaml
DEFAULT_SEED_YAML = Path(__file__).parent / "instrument_seed.yaml"


def _parse_date(raw: str | None) -> date | None:
    """YAML 日期串（'YYYY-MM-DD'）→ date；None→None。"""
    if raw is None:
        return None
    return date.fromisoformat(str(raw))


def _build_instrument(item: dict) -> Instrument:
    """YAML 单条 dict → Instrument（含 StPeriod 时段序列）。"""
    st_periods = [
        StPeriod(
            symbol=p["symbol"],
            start=_parse_date(p["start"]),  # type: ignore[arg-type]
            end=_parse_date(p.get("end")),
            kind=p.get("kind", "ST"),
        )
        for p in item.get("st_periods") or []
    ]
    return Instrument(
        symbol=item["symbol"],
        market=item["market"],
        board=item["board"],
        product_type=item["product_type"],
        list_date=_parse_date(item.get("list_date")),
        delist_date=_parse_date(item.get("delist_date")),
        status=item.get("status", "active"),
        st_periods=st_periods,
        etf_crossborder=bool(item.get("etf_crossborder", False)),
    )


class InstrumentProvider:
    """instrument 基础数据查询。load 自 seed yaml 或 store。"""

    def __init__(self, instruments: dict[str, Instrument] | None = None) -> None:
        self.instruments: dict[str, Instrument] = instruments or {}

    @classmethod
    def from_seed(cls, path: str | Path | None = None) -> "InstrumentProvider":
        """读 YAML 构造 Instrument dict（默认 quant/data/instrument_seed.yaml）。

        YAML 结构：list of {symbol, market, board, product_type,
        list_date, delist_date, status, st_periods:[{start,end,kind}],
        etf_crossborder}。
        """
        seed_path = Path(path) if path is not None else DEFAULT_SEED_YAML
        with seed_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        items = raw or []
        instruments = {_it["symbol"]: _build_instrument(_it) for _it in items}
        return cls(instruments=instruments)

    def get(self, symbol: str) -> Instrument | None:
        """查 instrument；未命中返回 None。"""
        return self.instruments.get(symbol)

    def is_st(self, symbol: str, on: date) -> bool:
        """on 时刻是否 ST：instrument 存在→Instrument.is_st(on)；否则 False。"""
        inst = self.instruments.get(symbol)
        if inst is None:
            return False
        return inst.is_st(on)

    def classify(self, symbol: str, on: date) -> tuple[str, str, str]:
        """经 instrument 精分类：命中→(market,board,product_type)
        （ST 时 board='st'，跨境 ETF board='etp_crossborder'）；
        未命中→回退 classify_symbol。复用 classify_with_instrument。
        """
        return classify_with_instrument(symbol, on, self.instruments)
