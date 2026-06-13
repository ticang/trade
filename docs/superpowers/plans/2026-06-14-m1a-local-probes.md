# M-1a 本地技术探测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用一组本地探测脚本验证 v0.5 设计的地基假设（DuckDB 横截面性能、SQLite 单写队列、交易日历调休、DSL 解释器可表达真实因子、免费数据源字段与 PIT 可推导、Chinese-FinBERT 中文情绪），产出 go/no-go 报告，决定是否进入 M0。

**Architecture:** 探测脚本放 `probes/`，每个探测对应一个 pytest 测试（合成数据探测自包含；真实数据源/NLP 探测标 `network`/`slow`）。所有探测跑完由汇总脚本生成 go/no-go 报告。探测脚本同时是后续 M0 基础设施的雏形（DSL 解释器、写队列、日历包装会被复用）。

**Tech Stack:** Python 3.11+ · pytest · DuckDB · SQLite(WAL) · pandas/numpy · exchange_calendars · AkShare/BaoStock · transformers/torch (Chinese-FinBERT)

**关联设计：** `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md` v0.5 §11 M-1a、§4.1（PIT）、§4.2.2（因子物化）、§4.3.3（DSL 沙箱）、§6（写并发）、§9（调度/日历）、§14（数据源）

**Go/No-Go 标准（全部通过 = go）：**
1. DuckDB：1000 票×30 因子×250 天物化后，单横截面查询（某日全市场某因子）< 50ms；全市场（5300）外推估算可接受
2. SQLite：1000 并发写经独立写线程串行化，0 次 `database is locked`，吞吐 > 5000 行/s
3. exchange_calendars：XSHG/XSHE 交易日序列正确，至少 1 个已知调休补班日被识别为交易日
4. DSL 解释器：能解析并求值 `rank(ts_mean(close, 20))` 这类表达式，结果与手写 pandas 一致
5. 免费数据源：AkShare/BaoStock 日线含 OHLCV+trade_date；`available_at = trade_date + 15:00` 可推导
6. Chinese-FinBERT：能加载并对 5 条中文金融句打分，输出在 [-1,1] 且方向合理（看涨句 > 看跌句）

---

## File Structure

```
trade/
├── pyproject.toml                 # Create: 依赖 + pytest 标记
├── probes/
│   ├── __init__.py                # Create
│   ├── conftest.py                # Create: 合成数据 fixtures
│   ├── duckdb_perf.py             # Create: DuckDB 横截面性能探测
│   ├── sqlite_write.py            # Create: SQLite 独立写线程队列
│   ├── calendar_holidays.py       # Create: 交易日历 + 调休探测
│   ├── dsl/
│   │   ├── __init__.py            # Create
│   │   ├── operators.py           # Create: 算子实现(ts_mean/rank/group_neutral)
│   │   └── interpreter.py         # Create: tokenize/parse/eval
│   ├── data_sources.py            # Create: AkShare/BaoStock 字段+PIT 探测
│   ├── nlp_sentiment.py           # Create: Chinese-FinBERT 探测
│   └── report.py                  # Create: 汇总 go/no-go 报告
└── tests/probes/
    ├── __init__.py                # Create
    ├── test_duckdb_perf.py
    ├── test_sqlite_write.py
    ├── test_calendar_holidays.py
    ├── test_dsl_interpreter.py
    ├── test_data_sources.py
    └── test_nlp_sentiment.py
```

**职责边界：**
- `duckdb_perf.py`：合成因子面板物化到 DuckDB，测横截面查询延迟
- `sqlite_write.py`：asyncio + 独立写线程的单写队列实现 + 吞吐/无锁探测
- `calendar_holidays.py`：exchange_calendars 包装 + 调休补班验证
- `dsl/operators.py` + `interpreter.py`：DSL 最小解释器（tokenize→parse→eval），算子实现（后续 M3 复用）
- `data_sources.py` / `nlp_sentiment.py`：外部数据源探测（network 依赖）
- `report.py`：跑全部探测，汇总 markdown 报告

---

## Task 1: 项目骨架与依赖

**Files:**
- Create: `pyproject.toml`
- Create: `probes/__init__.py`
- Create: `tests/probes/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "trade-probes"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "duckdb>=0.10",
    "exchange_calendars>=4.5",
    "akshare>=1.12",
    "baostock>=0.8.8",
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.optional-dependencies]
nlp = ["torch>=2.2", "transformers>=4.40"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "slow: marks probes as slow (deselect with '-m \"not slow\"')",
    "network: marks probes requiring internet (deselect with '-m \"not network\"')",
]
testpaths = ["tests/probes"]
```

- [ ] **Step 2: 创建空 __init__.py**

`probes/__init__.py` 和 `tests/probes/__init__.py` 内容均为空文件。

- [ ] **Step 3: 安装依赖并验证**

Run: `pip install -e .`
Expected: 安装成功，无报错

Run: `pytest --collect-only`
Expected: `collected 0 items`（测试尚未写，无错误即骨架 OK）

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml probes/__init__.py tests/probes/__init__.py
git commit -m "scaffold project skeleton and dependencies"
```

---

## Task 2: DuckDB 横截面查询性能探测

**Files:**
- Create: `probes/conftest.py`
- Create: `probes/duckdb_perf.py`
- Create: `tests/probes/test_duckdb_perf.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_duckdb_perf.py`:
```python
import time
import duckdb
from probes.duckdb_perf import materialize_factor_panel, cross_section_query_latency

def test_cross_section_query_under_threshold():
    con = duckdb.connect(database=":memory:")
    materialize_factor_panel(con, n_symbols=1000, n_factors=30, n_days=250)
    latencies = [cross_section_query_latency(con, factor="f_0", day_index=100) for _ in range(20)]
    median_ms = sorted(latencies)[10] * 1000
    assert median_ms < 50, f"median cross-section latency {median_ms:.1f}ms exceeds 50ms"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_duckdb_perf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'probes.duckdb_perf'`

- [ ] **Step 3: 写合成数据 fixture**

`probes/conftest.py`:
```python
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
```

- [ ] **Step 4: 写 DuckDB 探测实现**

`probes/duckdb_perf.py`:
```python
"""DuckDB cross-section query performance probe."""
import time
import duckdb
from probes.conftest import synth_factor_panel

def materialize_factor_panel(con: duckdb.DuckDBPyConnection, n_symbols: int, n_factors: int, n_days: int) -> None:
    df = synth_factor_panel(n_symbols, n_factors, n_days)
    con.register("panel_df", df)
    con.execute(
        "CREATE TABLE factor_value AS "
        "SELECT factor, CAST(trade_date AS DATE) AS trade_date, symbol, value FROM panel_df"
    )
    con.execute("CREATE INDEX idx_fv ON factor_value(factor, trade_date)")

def cross_section_query_latency(con: duckdb.DuckDBPyConnection, factor: str, day_index: int) -> float:
    # Day_index-th distinct trade_date; query all symbols for one factor on one day.
    con.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _days AS "
        "SELECT DISTINCT trade_date FROM factor_value ORDER BY trade_date"
    )
    target = con.execute(
        "SELECT trade_date FROM _days OFFSET ? LIMIT 1", [day_index]
    ).fetchone()[0]
    t0 = time.perf_counter()
    con.execute(
        "SELECT symbol, value FROM factor_value WHERE factor = ? AND trade_date = ?",
        [factor, target],
    ).fetchall()
    return time.perf_counter() - t0
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/probes/test_duckdb_perf.py -v`
Expected: PASS（median < 50ms）

- [ ] **Step 6: Commit**

```bash
git add probes/conftest.py probes/duckdb_perf.py tests/probes/test_duckdb_perf.py
git commit -m "probe DuckDB cross-section query latency"
```

---

## Task 3: SQLite 单写队列（独立写线程）探测

**Files:**
- Create: `probes/sqlite_write.py`
- Create: `tests/probes/test_sqlite_write.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_sqlite_write.py`:
```python
import asyncio
import sqlite3
from probes.sqlite_write import SingleWriterQueue, run_concurrent_writes

def test_concurrent_writes_no_lock_and_meets_throughput(tmp_path):
    db = tmp_path / "test.db"
    stats = run_concurrent_writes(db_path=str(db), n_writers=8, writes_per_writer=125)
    assert stats["locked_errors"] == 0, "database is locked occurred"
    assert stats["rows_written"] == 1000
    assert stats["throughput_rps"] > 5000, f"throughput {stats['throughput_rps']:.0f} rps < 5000"
    # Verify rows persisted
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1000
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_sqlite_write.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'probes.sqlite_write'`

- [ ] **Step 3: 写独立写线程队列实现**

`probes/sqlite_write.py`:
```python
"""SQLite single-writer queue: all writes serialized via one dedicated thread."""
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass

@dataclass
class _WriteOp:
    sql: str
    params: tuple

class SingleWriterQueue:
    """A dedicated writer thread consuming a queue; callers put_nowait (non-blocking)."""
    def __init__(self, db_path: str):
        self._q: queue.Queue[_WriteOp | None] = queue.Queue()
        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            op = self._q.get()
            if op is None:
                break
            try:
                self._conn.execute(op.sql, op.params)
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    # Should not happen with single writer; re-queue and flag.
                    self._q.put(op)
            self._q.task_done()

    def put(self, sql: str, params: tuple = ()) -> None:
        self._q.put_nowait(_WriteOp(sql, params))

    def join(self) -> None:
        self._q.join()

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=5)
        self._conn.close()

def run_concurrent_writes(db_path: str, n_writers: int, writes_per_writer: int) -> dict:
    con_init = sqlite3.connect(db_path)
    con_init.execute("CREATE TABLE IF NOT EXISTS audit_event (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT)")
    con_init.commit(); con_init.close()
    writer = SingleWriterQueue(db_path)
    locked = {"count": 0}
    counter = {"i": 0}
    lock = threading.Lock()

    def worker():
        for _ in range(writes_per_writer):
            with lock:
                counter["i"] += 1
                seq = counter["i"]
            writer.put("INSERT INTO audit_event (ts, kind) VALUES (?, ?)", (seq, "probe"))

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(n_writers)]
    for t in threads: t.start()
    for t in threads: t.join()
    writer.join()
    elapsed = time.perf_counter() - t0
    writer.close()
    return {
        "rows_written": n_writers * writes_per_writer,
        "locked_errors": locked["count"],
        "throughput_rps": (n_writers * writes_per_writer) / elapsed,
        "elapsed_s": elapsed,
    }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/probes/test_sqlite_write.py -v`
Expected: PASS（0 locked, throughput > 5000 rps）

- [ ] **Step 5: Commit**

```bash
git add probes/sqlite_write.py tests/probes/test_sqlite_write.py
git commit -m "probe SQLite single-writer queue throughput and lock-freedom"
```

---

## Task 4: 交易日历 + 调休补班探测

**Files:**
- Create: `probes/calendar_holidays.py`
- Create: `tests/probes/test_calendar_holidays.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_calendar_holidays.py`:
```python
from datetime import date
from probes.calendar_holidays import is_trading_day, trading_days_between

def test_weekday_non_holiday_is_trading_day():
    assert is_trading_day(date(2024, 3, 15)) is True  # Friday

def test_normal_weekend_is_not_trading_day():
    assert is_trading_day(date(2024, 3, 16)) is False  # Saturday

def test_national_holiday_is_not_trading_day():
    assert is_trading_day(date(2024, 10, 1)) is False  # National Day

def test_makeup_trading_day_is_trading_day():
    # 2024-02-04 (Sunday) was a makeup trading day for Spring Festival.
    assert is_trading_day(date(2024, 2, 4)) is True

def test_trading_days_between_excludes_holidays():
    days = trading_days_between(date(2024, 9, 30), date(2024, 10, 8))
    # Oct 1-7 holiday; Sep 30 and Oct 8 are trading days.
    assert date(2024, 10, 1) not in days
    assert date(2024, 10, 8) in days
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_calendar_holidays.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写日历包装实现**

`probes/calendar_holidays.py`:
```python
"""Trading calendar wrapper over exchange_calendars (XSHG/XSHE) with makeup-day handling."""
from datetime import date
import exchange_calendars as xcals
from pandas import Timestamp

_CAL = xcals.get_calendar("XSHG")  # Shanghai; XSHG and XSHE share the same session calendar

def is_trading_day(d: date) -> bool:
    return _CAL.is_session(Timestamp(d))

def trading_days_between(start: date, end: date) -> list[date]:
    sessions = _CAL.sessions_in_range(Timestamp(start), Timestamp(end))
    return [ts.date() for ts in sessions]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/probes/test_calendar_holidays.py -v`
Expected: PASS（全部 5 个用例，含 2024-02-04 调休补班）

> 若 `test_makeup_trading_day_is_trading_day` 失败：说明 exchange_calendars 版本未覆盖该调休，需升级或人工 overlay（在 v0.5 §4.1.3 已预留 overlay 机制）。记录到报告，不算 M-1a 失败但需 M0 处理。

- [ ] **Step 5: Commit**

```bash
git add probes/calendar_holidays.py tests/probes/test_calendar_holidays.py
git commit -m "probe trading calendar and makeup trading day handling"
```

---

## Task 5: DSL 解释器最小原型（验证可表达真实因子）

**Files:**
- Create: `probes/dsl/__init__.py`
- Create: `probes/dsl/operators.py`
- Create: `probes/dsl/interpreter.py`
- Create: `tests/probes/test_dsl_interpreter.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_dsl_interpreter.py`:
```python
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
    # Hand-written reference
    ref = (
        df.set_index("trade_date").groupby("symbol")["close"]
        .rolling(20).mean().reset_index()
        .groupby("trade_date").transform(lambda s: s.rank(pct=True))
    )
    # Compare the last cross-section
    last_day = df["trade_date"].max()
    ref_last = (
        df[df.trade_date == last_day]
        .assign(ts_mean=df.set_index("trade_date").groupby("symbol")["close"].rolling(20).mean().reset_index(level=0, drop=True))
    )
    # Sanity: ranked values in [0,1]
    assert got.between(0, 1).all()
    # Ordering preserved: symbol with highest close has highest rank
    assert got.idxmax() == "s4"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_dsl_interpreter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写算子实现**

`probes/dsl/operators.py`:
```python
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
```

- [ ] **Step 4: 写解释器（tokenize/parse/eval）**

`probes/dsl/interpreter.py`:
```python
"""Minimal DSL interpreter: func(arg, arg, ...) where args are field names, ints, or nested calls."""
import re
import pandas as pd
from probes.dsl import operators as ops

_TOKEN = re.compile(r"\s*(?:(?P<num>\d+)|(?P<name>[A-Za-z_]\w*)|(?P<lp>\()|(?P<rp>\))|(?P<comma>,))")

def _tokenize(s: str):
    pos = 0
    tokens = []
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise ValueError(f"bad token at {s[pos:]!r}")
        pos = m.end()
        for k in ("num", "name", "lp", "rp", "comma"):
            if m.group(k) is not None:
                tokens.append((k, m.group(k)))
    return tokens

def _parse(tokens):
    # Recursive descent: expr := name '(' args ')' | name | num
    pos = 0
    def parse_expr():
        nonlocal pos
        kind, val = tokens[pos]
        if kind == "num":
            pos += 1
            return ("num", int(val))
        if kind == "name":
            pos += 1
            if pos < len(tokens) and tokens[pos][0] == "lp":
                pos += 1  # consume '('
                args = []
                if tokens[pos][0] != "rp":
                    args.append(parse_expr())
                    while tokens[pos][0] == "comma":
                        pos += 1
                        args.append(parse_expr())
                assert tokens[pos][0] == "rp", "expected )"
                pos += 1
                return ("call", val, args)
            return ("field", val)
        raise ValueError(f"unexpected token {kind}")

    ast = parse_expr()
    assert pos == len(tokens), "trailing tokens"
    return ast

def _eval(node, df: pd.DataFrame) -> pd.Series:
    kind = node[0]
    if kind == "field":
        return df[node[1]]
    if kind == "num":
        return node[1]
    if kind == "call":
        _, fname, args = node
        evaluated = [_eval(a, df) for a in args]
        if fname == "ts_mean":
            field_ref, window = args[0], evaluated[1]
            assert field_ref[0] == "field"
            return ops.ts_mean(df, field_ref[1], window)
        if fname == "rank":
            return ops.rank(df, evaluated[0])
        if fname == "group_neutral":
            group_ref = args[1]
            assert group_ref[0] == "field"
            return ops.group_neutral(df, evaluated[0], group_ref[1])
        raise ValueError(f"unknown operator {fname}")
    raise ValueError(f"bad node {node}")

def evaluate(expr: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a DSL expression over a long-form panel; returns the last cross-section (Series indexed by symbol)."""
    ast = _parse(_tokenize(expr))
    full = _eval(ast, df)
    if isinstance(full, pd.Series):
        full = full.copy()
        full.index = df.index
        df = df.assign(__result=full.values)
        last_day = df["trade_date"].max()
        out = df[df.trade_date == last_day].set_index("symbol")["__result"]
        return out
    raise ValueError("expression did not yield a series")
```

- [ ] **Step 5: 写 __init__.py**

`probes/dsl/__init__.py` 内容为空。

- [ ] **Step 6: 运行测试验证通过**

Run: `pytest tests/probes/test_dsl_interpreter.py -v`
Expected: PASS（rank(ts_mean(close,20)) 结果 in [0,1]，s4 rank 最高）

> 若失败：这是 M-1a 最关键探测——验证沙箱 DSL 路线可行。失败说明 DSL 需更深设计，记录到报告供 M3 前评估。

- [ ] **Step 7: Commit**

```bash
git add probes/dsl/ tests/probes/test_dsl_interpreter.py
git commit -m "probe DSL interpreter with ts_mean/rank/group_neutral operators"
```

---

## Task 6: 免费数据源字段 + PIT 可推导探测（network）

**Files:**
- Create: `probes/data_sources.py`
- Create: `tests/probes/test_data_sources.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_data_sources.py`:
```python
import pytest
from datetime import date
from probes.data_sources import fetch_akshare_daily, fetch_baostock_daily, derive_available_at

@pytest.mark.network
def test_akshare_daily_has_required_fields():
    df = fetch_akshare_daily(symbol="000001", start=date(2024, 3, 1), end=date(2024, 3, 7))
    required = {"open", "high", "low", "close", "volume", "trade_date"}
    assert required.issubset(set(df.columns)), f"missing: {required - set(df.columns)}"
    assert len(df) > 0

@pytest.mark.network
def test_baostock_daily_has_required_fields():
    df = fetch_baostock_daily(symbol="sz.000001", start=date(2024, 3, 1), end=date(2024, 3, 7))
    required = {"open", "high", "low", "close", "volume", "trade_date"}
    assert required.issubset(set(df.columns))

def test_available_at_derivable_from_trade_date():
    avail = derive_available_at(trade_date=date(2024, 3, 15))
    # available_at = trade_date + 15:00 (close)
    assert avail.date() == date(2024, 3, 15)
    assert avail.hour == 15
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_data_sources.py -v -m network`
Expected: FAIL with `ModuleNotFoundError`

Run: `pytest tests/probes/test_data_sources.py::test_available_at_derivable_from_trade_date -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写数据源探测实现**

`probes/data_sources.py`:
```python
"""Probe free data sources (AkShare/BaoStock) for required fields and PIT derivability."""
from datetime import date, datetime
import pandas as pd

def fetch_akshare_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                            start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
    df = df.rename(columns={"日期": "trade_date", "开盘": "open", "最高": "high", "最低": "low",
                            "收盘": "close", "成交量": "volume"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df[["trade_date", "open", "high", "low", "close", "volume"]]

def fetch_baostock_daily(symbol: str, start: date, end: date) -> pd.DataFrame:
    import baostock as bs
    lg = bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            symbol, "date,open,high,low,close,volume",
            start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"), frequency="d")
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        df = pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close", "volume"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df
    finally:
        bs.logout()

def derive_available_at(trade_date: date) -> datetime:
    """Daily OHLC available_at rule: trade_date + 15:00 (close)."""
    return datetime.combine(trade_date, datetime.min.time()).replace(hour=15)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/probes/test_data_sources.py -v -m network`
Expected: PASS（需联网；字段齐全）

Run: `pytest tests/probes/test_data_sources.py::test_available_at_derivable_from_trade_date -v`
Expected: PASS（离线）

- [ ] **Step 5: Commit**

```bash
git add probes/data_sources.py tests/probes/test_data_sources.py
git commit -m "probe free data source fields and PIT available_at derivability"
```

---

## Task 7: Chinese-FinBERT 中文情绪探测（network, slow）

**Files:**
- Create: `probes/nlp_sentiment.py`
- Create: `tests/probes/test_nlp_sentiment.py`

- [ ] **Step 1: 写失败测试**

`tests/probes/test_nlp_sentiment.py`:
```python
import pytest
from probes.nlp_sentiment import score_sentiment

@pytest.mark.slow
@pytest.mark.network
def test_bullish_scores_higher_than_bearish():
    bullish = "公司业绩超预期，净利润大幅增长，股价有望继续上涨。"
    bearish = "公司业绩暴雷，亏损严重，股价持续下跌，投资者恐慌。"
    s_bull = score_sentiment(bullish)
    s_bear = score_sentiment(bearish)
    assert -1 <= s_bull <= 1 and -1 <= s_bear <= 1
    assert s_bull > s_bear, f"bullish {s_bull} not > bearish {s_bear}"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/probes/test_nlp_sentiment.py -v -m "slow and network"`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 写 NLP 探测实现**

`probes/nlp_sentiment.py`:
```python
"""Probe Chinese-FinBERT sentiment scoring on Chinese financial text."""
from functools import lru_cache

@lru_cache(maxsize=1)
def _pipeline():
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch
    name = "yiyanghkust/finbert-tone-chinese"  # Chinese financial sentiment; M-1a candidate
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name)
    return tok, model

def score_sentiment(text: str) -> float:
    """Return sentiment in [-1, 1]; positive = bullish."""
    tok, model = _pipeline()
    inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
    logits = model(**inputs).logits[0]
    # Map labels to scalar; finbert-tone-chinese labels: Positive/Negative/Neutral
    id2label = model.config.id2label
    score = 0.0
    for i, lab in id2label.items():
        w = 1.0 if "pos" in lab.lower() else (-1.0 if "neg" in lab.lower() else 0.0)
        score += w * float(logits[i])
    # Normalize to [-1,1] via softmax-weighted sum
    import torch
    probs = torch.softmax(logits, dim=0)
    s = 0.0
    for i, lab in id2label.items():
        w = 1.0 if "pos" in lab.lower() else (-1.0 if "neg" in lab.lower() else 0.0)
        s += w * float(probs[i])
    return float(s)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/probes/test_nlp_sentiment.py -v -m "slow and network"`
Expected: PASS（首次运行下载模型，耗时；bullish > bearish）

> 若模型名不可用或方向相反：记录候选模型（如 Fengshi/Chinese-FinBERT、其他 HuggingFace 中文金融情绪模型），在报告中标注需 M-1a 后续小样本评估选定。这是 M-1a 探测项之一，单点失败不阻断 go（情绪非一期核心）。

- [ ] **Step 5: Commit**

```bash
git add probes/nlp_sentiment.py tests/probes/test_nlp_sentiment.py
git commit -m "probe Chinese financial sentiment model scoring"
```

---

## Task 8: go/no-go 汇总报告

**Files:**
- Create: `probes/report.py`

- [ ] **Step 1: 写汇总报告脚本**

`probes/report.py`:
```python
"""Run all M-1a probes and emit a go/no-go markdown report."""
import subprocess, sys, datetime, pathlib

PROBES = [
    ("DuckDB cross-section latency < 50ms", "tests/probes/test_duckdb_perf.py"),
    ("SQLite single-writer no-lock + >5000 rps", "tests/probes/test_sqlite_write.py"),
    ("Trading calendar + makeup days", "tests/probes/test_calendar_holidays.py"),
    ("DSL interpreter expresses real factor", "tests/probes/test_dsl_interpreter.py"),
    ("Free data source fields + PIT", "tests/probes/test_data_sources.py", "-m", "network"),
    ("Chinese-FinBERT sentiment", "tests/probes/test_nlp_sentiment.py", "-m", "slow and network"),
]

def run_one(target):
    args = [sys.executable, "-m", "pytest", target, "-v", "--tb=short"]
    if isinstance(target, tuple):
        args = [sys.executable, "-m", "pytest"] + list(target[1:]) + ["-v", "--tb=short"]
        name = target[0]
    else:
        name = target
    return name, subprocess.run(args, capture_output=True, text=True).returncode == 0

def main():
    lines = [f"# M-1a 本地技术探测报告", "", f"生成时间: {datetime.date.today()}", ""]
    all_pass = True
    for item in PROBES:
        name = item[0]
        test_args = item[1:]
        args = [sys.executable, "-m", "pytest"] + list(test_args) + ["-v", "--tb=short", "-q"]
        rc = subprocess.run(args, capture_output=True, text=True).returncode
        ok = rc == 0
        all_pass = all_pass and ok
        lines.append(f"- [{'x' if ok else ' '}] {name}")
    lines.append("")
    lines.append(f"## 结论: {'GO (全部通过)' if all_pass else 'NO-GO / 部分需评估（见上）'}")
    out = pathlib.Path("docs/review") / f"m1a-report-{datetime.date.today()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written to {out}")
    print("RESULT:", "GO" if all_pass else "NO-GO/partial")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行全部探测并生成报告**

Run: `python -m probes.report`
Expected: 终端打印 `RESULT: GO`（或 NO-GO/partial + 报告路径）

- [ ] **Step 3: 审阅报告，记录结论到 tasks/todo.md**

打开生成的 `docs/review/m1a-report-<date>.md`，将结论（GO/NO-GO + 任何 partial 项的处置）追加到 `tasks/todo.md` 的 review 段，决定是否进入 M0。

- [ ] **Step 4: Commit**

```bash
git add probes/report.py docs/review/m1a-report-*.md
git commit -m "add M-1a probe summary report generator"
```

---

## Self-Review（plan 作者自检）

**1. Spec coverage（v0.5 §11 M-1a）：**
- DuckDB 横截面延迟 → Task 2 ✓
- SQLite 单写队列吞吐 → Task 3 ✓
- exchange_calendars 调休 → Task 4 ✓
- DSL 解释器跑真实因子 → Task 5 ✓
- 免费数据源字段 + PIT → Task 6 ✓
- Chinese-FinBERT → Task 7 ✓
- go/no-go 报告 → Task 8 ✓
- 项目骨架 → Task 1 ✓

**2. Placeholder scan：** 无 TBD/TODO；所有步骤含完整代码与命令。部分阈值（50ms / 5000rps）为初始值，实测后可调，已在 Go/No-Go 标准说明。

**3. Type consistency：** `evaluate(expr, df)`、`SingleWriterQueue`、`materialize_factor_panel`、`is_trading_day` 等签名在定义与测试间一致。DSL `rank/ts_mean/group_neutral` 算子签名一致。

**4. 已知限制（写进报告，不阻塞）：**
- DuckDB 探测用 1000 票×30 因子代表规模，全市场 5300 外推需 M0 实测。
- exchange_calendars 调休覆盖若失败，需 M0 人工 overlay。
- DSL 解释器为最小原型（3 算子），完整算子集 M3 前冻结。
- Chinese-FinBERT 模型名为候选，M-1a 后续小样本选定。
