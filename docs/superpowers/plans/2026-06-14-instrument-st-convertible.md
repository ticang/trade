# Instrument 基础数据（ST 当前范围，可转债延期）Implementation Plan

> **Scope update (v0.5-scope):** 当前交易范围只做沪深主板股票。ST 主板路由仍属当前范围；可转债、ETF、科创/创业/北交路由已延期，保留数据结构但不得在当前 `rules_for` 中命中可交易规则。

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking。

**Goal:** 补全 instrument 基础数据，使 M0.5 的 ST 主板规则（`st_main`）可经 symbol 路由命中；可转债/ETF 只保留 instrument 表达能力，等待后续扩展计划补规则来源、fixture 与验收后再接入 `rules_for`。

**Architecture:** instrument 表（M0 DuckDB schema）补 `is_st`/ST 时变状态（st_periods: symbol→[(start,end)]）。InstrumentProvider.load(seed/DbStore) 提供 `is_st(symbol,date)` 与 `classify(symbol,date)->(market,board,product_type)`。TradingRuleProvider.rules_for 支持传 instrument_provider；当前只允许 ST 命中 `st_main`，可转债/ETF 因规则表未录入而返回 None。

**Tech Stack:** Python 3.11+ · 复用 M0/M0.5。无新依赖

**关联：** §4.1.3（基础数据/交易规则）、§6（instrument 表）、M0.5（当前 st_main 规则种子）、v0.5-scope

**前置：** main（含 simplify cleanup）。本计划在 `feat/instrument-st-convertible`。

---

## Task 1: Instrument 数据模型 + ST 时变状态
**Files:** `quant/data/instrument.py`, `tests/quant/test_instrument_model.py`
- [ ] ST 时变：`StPeriod(symbol, start, end)`；`Instrument` 扩 `is_st: bool`（当前简化）或 `st_periods: list`。InstrumentProvider.is_st(symbol, date) 查时变。可转债 product_type=bond/market=BOND/board=bond 仅保留为延期数据表达。
- [ ] commit `add instrument model with time-varying st status`

## Task 2: classify 扩展（当前默认主板 + ST 经 instrument）
**Files:** `quant/providers/trading_rule.py`（扩 classify_symbol）, `tests/quant/test_classify_extend.py`
- [ ] classify_symbol：当前默认只支持 6xxxxx/00xxxx 主板；688/30/8/9/5/11x/113x/123x 返回 unsupported。加 `classify_with_instrument(symbol, date, instrument_provider)`：ST 股 → (SSE/SZSE, st, stock)；延期品种可被 instrument 表达但当前不命中规则。
- [ ] commit `extend classify for convertible bonds and st via instrument`

## Task 3: InstrumentProvider + seed 数据
**Files:** `quant/data/instrument_provider.py`, `quant/data/instrument_seed.yaml`, `tests/quant/test_instrument_provider.py`
- [ ] InstrumentProvider.load(seed_yaml or store)：载 instrument + ST 时变。is_st(symbol,date)/classify(symbol,date)。seed 以主板/ST 为当前范围；可转债样本如保留，仅作延期分类样例。
- [ ] commit `add instrument provider with seed dataset`

## Task 4: rules_for 接 instrument（ST 命中，延期品种不命中）
**Files:** `quant/providers/trading_rule.py`（rules_for 扩 optional instrument_provider）, `tests/quant/test_rules_with_instrument.py`
- [ ] rules_for(symbol, decision_time, *, instrument_provider=None)：若提供，classify 经 instrument；ST 命中 st_main；可转债/ETF 因当前规则表未录入而返回 None；否则用当前主板 classify_symbol。
- [ ] commit `route st and convertible rules via instrument provider`

## Task 5: 集成验收
**Files:** `tests/quant/test_instrument_acceptance.py`
- [ ] ST 股经 instrument 命中 st_main(±5%)；可转债/ETF 当前返回 None；普通股仍主板。load M0.5 rules + instrument seed 验证。
- [ ] commit `add instrument routing acceptance test`

## Self-Review
1. ST 时变（is_st(symbol,date) 查 st_periods）；rules_for 经 instrument 命中当前 M0.5 ST 规则；延期品种不命中
2. 当前默认路由（无 instrument_provider 时）只支持沪深主板
3. seed 占位（真实 AkShare 留 ③）
4. 复用 M0.5 rules_v1.yaml（当前仅 sse_main_stock / szse_main_stock / st_main）
