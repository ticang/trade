# Instrument 基础数据（ST/可转债路由）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox tracking。

**Goal:** 补全 instrument 基础数据，使 M0.5 的 ST/可转债规则（`st_main`/`convertible_bond`）可经 symbol 路由命中——当前 `classify_symbol` 仅按前缀，看不出 ST（时变状态）与可转债品种。交付 InstrumentProvider（含时变 ST 状态查询）+ classify 扩展（可转债前缀 + ST 经 instrument 查询）+ seed 数据集（已知 ST/可转债）+ 接入 rules_for。

**Architecture:** instrument 表（M0 DuckDB schema）补 `is_st`/ST 时变状态（st_periods: symbol→[(start,end)]）与可转债品种（product_type=bond）。InstrumentProvider.load(seed/DbStore) 提供 `is_st(symbol,date)` 与 `classify(symbol,date)->(market,board,product_type)`（合并前缀规则 + instrument 数据）。TradingRuleProvider.rules_for 支持传 instrument_provider，ST/可转债经其路由命中对应规则。真实数据导入（AkShare）留 ③。

**Tech Stack:** Python 3.11+ · 复用 M0/M0.5。无新依赖

**关联：** §4.1.3（基础数据/交易规则）、§6（instrument 表）、M0.5（st_main/convertible_bond 规则种子）

**前置：** main（含 simplify cleanup）。本计划在 `feat/instrument-st-convertible`。

---

## Task 1: Instrument 数据模型 + ST 时变状态
**Files:** `quant/data/instrument.py`, `tests/quant/test_instrument_model.py`
- [ ] ST 时变：`StPeriod(symbol, start, end)`；`Instrument` 扩 `is_st: bool`（当前简化）或 `st_periods: list`。InstrumentProvider.is_st(symbol, date) 查时变。可转债 product_type=bond/market=BOND/board=bond。
- [ ] commit `add instrument model with time-varying st status`

## Task 2: classify 扩展（可转债前缀 + ST 经 instrument）
**Files:** `quant/providers/trading_rule.py`（扩 classify_symbol）, `tests/quant/test_classify_extend.py`
- [ ] classify_symbol 扩：11x/113x/123x → (BOND,bond,bond)；保留既有 6/688/00/30/8/9/5。加 `classify_with_instrument(symbol, date, instrument_provider)`：ST 股 → (SSE/SZSE, st, stock)；跨境 ETF 经 instrument flag → etp_crossborder。
- [ ] commit `extend classify for convertible bonds and st via instrument`

## Task 3: InstrumentProvider + seed 数据
**Files:** `quant/data/instrument_provider.py`, `quant/data/instrument_seed.yaml`, `tests/quant/test_instrument_provider.py`
- [ ] InstrumentProvider.load(seed_yaml or store)：载 instrument + ST 时变。is_st(symbol,date)/classify(symbol,date)。seed 含已知 ST 股（如 *ST 历史）+ 可转债样本（占位，真实 AkShare 留 ③）。
- [ ] commit `add instrument provider with seed dataset`

## Task 4: rules_for 接 instrument（ST/可转债命中）
**Files:** `quant/providers/trading_rule.py`（rules_for 扩 optional instrument_provider）, `tests/quant/test_rules_with_instrument.py`
- [ ] rules_for(symbol, decision_time, *, instrument_provider=None)：若提供，classify 经 instrument（ST/可转债命中 st_main/convertible_bond）；否则用旧 classify_symbol（向后兼容）。
- [ ] commit `route st and convertible rules via instrument provider`

## Task 5: 集成验收
**Files:** `tests/quant/test_instrument_acceptance.py`
- [ ] ST 股经 instrument 命中 st_main(±5%)；可转债命中 convertible_bond(±20%/T+0/tick0.001)；普通股仍主板。load M0.5 rules + instrument seed 验证。
- [ ] commit `add instrument routing acceptance test`

## Self-Review
1. ST 时变（is_st(symbol,date) 查 st_periods）；可转债前缀路由；rules_for 经 instrument 命中 M0.5 规则
2. 向后兼容（无 instrument_provider 时用旧 classify）
3. seed 占位（真实 AkShare 留 ③）
4. 复用 M0.5 rules_v1.yaml（st_main/convertible_bond 已种子）
