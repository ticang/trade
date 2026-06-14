"""DSL 解释器测试（设计 v0.5 §4.3.3）。

覆盖点：
- tokenizer / parser / evaluator：field / num / call 三种 AST 节点
- 时序算子调度（field 参数传字段名）
- 横截面算子调度（expr 参数先递归求值为 Series 再传入）
- 嵌套表达式：横截面(时序(field, n))
- 沙箱边界：未知算子拒绝、参数数校验

合成 panel：3 symbol × 10 trade_date（与 test_dsl_operators 同款），close/volume 已知。

TDD：本文件先于 quant/dsl/interpreter.py 编写，import 失败为预期红线。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.dsl import operators as ops
from quant.dsl.interpreter import DslError, evaluate
from quant.dsl.sandbox import Sandbox


# ---------------------------------------------------------------------------
# 合成 panel：3 symbol × 10 trade_date（与 test_dsl_operators 同款）
# ---------------------------------------------------------------------------
def _build_panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    rows = []
    for sym, base, step in [("S0", 10.0, 0.5), ("S1", 20.0, -0.5), ("S2", 5.0, 1.0)]:
        for j, d in enumerate(dates):
            close = base + step * j
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": d,
                    "close": close,
                    "volume": close * 1000 + j,
                    "g": int(sym[-1]) % 2,
                }
            )
    df = pd.DataFrame(rows).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    return df


@pytest.fixture
def panel() -> pd.DataFrame:
    return _build_panel()


def _norm(s: pd.Series) -> pd.Series:
    """重置索引与 name，便于与参考实现比对。"""
    return s.reset_index(drop=True)


# ===========================================================================
# 基础节点
# ===========================================================================
def test_evaluate_simple_field(panel: pd.DataFrame) -> None:
    """field 节点直接取列。"""
    got = evaluate("close", panel)
    pd.testing.assert_series_equal(_norm(got), _norm(panel["close"]), check_names=False)


def test_evaluate_unknown_field_raises(panel: pd.DataFrame) -> None:
    """未在 df 中出现的字段名 → DslError。"""
    with pytest.raises(DslError):
        evaluate("not_a_field", panel)


# ===========================================================================
# 时序算子（field 参数传字段名）
# ===========================================================================
def test_evaluate_ts_mean(panel: pd.DataFrame) -> None:
    got = evaluate("ts_mean(close, 3)", panel)
    expected = ops.ts_mean(panel, "close", 3)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_delay(panel: pd.DataFrame) -> None:
    got = evaluate("delay(close, 2)", panel)
    expected = ops.delay(panel, "close", 2)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_ts_delta(panel: pd.DataFrame) -> None:
    got = evaluate("ts_delta(close, 2)", panel)
    expected = ops.ts_delta(panel, "close", 2)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_ts_corr(panel: pd.DataFrame) -> None:
    """双字段时序算子 ts_corr(close, volume, 5)。"""
    got = evaluate("ts_corr(close, volume, 5)", panel)
    expected = ops.ts_corr(panel, "close", "volume", 5)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_decay_linear(panel: pd.DataFrame) -> None:
    got = evaluate("decay_linear(close, 3)", panel)
    expected = ops.decay_linear(panel, "close", 3)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


# ===========================================================================
# 嵌套：横截面(时序(...))
# ===========================================================================
def test_evaluate_nested(panel: pd.DataFrame) -> None:
    """rank(ts_delta(close, 5))：时序结果先求值再进横截面算子。"""
    got = evaluate("rank(ts_delta(close, 5))", panel)
    inner = ops.ts_delta(panel, "close", 5)
    expected = ops.rank(panel, inner)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_arithmetic_in_call(panel: pd.DataFrame) -> None:
    """signed_power(rank(close), 2)：expr 参数先求值再传。"""
    got = evaluate("signed_power(rank(close), 2)", panel)
    inner = ops.rank(panel, panel["close"])
    expected = ops.signed_power(inner, 2)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_arithmetic_mul_of_ranks(panel: pd.DataFrame) -> None:
    """mul(rank(close), rank(ts_delta(close,5)))：两个 expr 求值后相乘。"""
    expr = "mul(rank(close), rank(ts_delta(close, 5)))"
    got = evaluate(expr, panel)
    lhs = ops.rank(panel, panel["close"])
    rhs = ops.rank(panel, ops.ts_delta(panel, "close", 5))
    expected = ops.mul(lhs, rhs)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_arithmetic_sub(panel: pd.DataFrame) -> None:
    """sub(rank(close), rank(volume))：横截面 rank 相减。"""
    got = evaluate("sub(rank(close), rank(volume))", panel)
    expected = ops.sub(ops.rank(panel, panel["close"]), ops.rank(panel, panel["volume"]))
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_zscore_of_ts_mean(panel: pd.DataFrame) -> None:
    got = evaluate("zscore(ts_mean(close, 3))", panel)
    inner = ops.ts_mean(panel, "close", 3)
    expected = ops.zscore(panel, inner)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_group_neutral(panel: pd.DataFrame) -> None:
    """group_neutral(rank(close), g)：expr + field 混合参数。"""
    got = evaluate("group_neutral(rank(close), g)", panel)
    inner = ops.rank(panel, panel["close"])
    expected = ops.group_neutral(panel, inner, "g")
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


# ===========================================================================
# 错误处理
# ===========================================================================
def test_unknown_operator_raises(panel: pd.DataFrame) -> None:
    """未注册算子 → DslError。"""
    with pytest.raises(DslError):
        evaluate("foobar(close)", panel)


def test_arity_mismatch_raises(panel: pd.DataFrame) -> None:
    """参数数不符（少参数）→ DslError。"""
    with pytest.raises(DslError):
        evaluate("ts_mean(close)", panel)


def test_arity_mismatch_too_many_raises(panel: pd.DataFrame) -> None:
    """参数数不符（多参数）→ DslError。"""
    with pytest.raises(DslError):
        evaluate("rank(close, 3)", panel)


def test_field_arg_must_be_name_raises(panel: pd.DataFrame) -> None:
    """field 参数位置若传入非字段表达式（嵌套算子）→ DslError。"""
    with pytest.raises(DslError):
        evaluate("ts_mean(rank(close), 3)", panel)


def test_syntax_error_raises(panel: pd.DataFrame) -> None:
    """解析失败（括号不匹配 / 非法 token）→ DslError。"""
    with pytest.raises(DslError):
        evaluate("ts_mean(close, 3", panel)
    with pytest.raises(DslError):
        evaluate("ts_mean(close, )", panel)
    with pytest.raises(DslError):
        evaluate("123 @#$", panel)


# ===========================================================================
# 沙箱
# ===========================================================================
def test_sandbox_validate_allowed() -> None:
    """只含已注册算子 → True。"""
    assert Sandbox().validate("rank(ts_mean(close, 5))") is True


def test_sandbox_validate_rejects_unknown() -> None:
    """含未注册算子 → False。"""
    assert Sandbox().validate("rank(foobar(close, 5))") is False


def test_sandbox_validate_syntax_error() -> None:
    """语法错误也视为不可信 → False（不抛）。"""
    assert Sandbox().validate("rank(ts_mean(close, 5)") is False


def test_sandbox_validate_simple_field() -> None:
    """单字段也算合法（无 call）。"""
    assert Sandbox().validate("close") is True


def test_sandbox_validate_accepts_arithmetic() -> None:
    """含已注册算术算子（add/sub/mul/div）的表达式 → True。"""
    assert (
        Sandbox().validate("mul(rank(close), rank(ts_delta(close, 5)))") is True
    )
    assert Sandbox().validate("sub(rank(close), rank(volume))") is True


# ===========================================================================
# 一元负号（LLM 习惯产 rank(-ts_mean(close,20))），映射为 neg 算子
# ===========================================================================
def test_evaluate_neg_of_field(panel: pd.DataFrame) -> None:
    """neg(close) == -close。"""
    got = evaluate("neg(close)", panel)
    expected = -panel["close"]
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_unary_minus_of_field(panel: pd.DataFrame) -> None:
    """一元 `-` 前缀 → neg：-close 与 neg(close) 等价。"""
    got = evaluate("-close", panel)
    expected = -panel["close"]
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_evaluate_unary_minus_of_call(panel: pd.DataFrame) -> None:
    """一元 `-` 套在算子调用上 → neg(call)：rank(-ts_mean(close,5))。"""
    got = evaluate("rank(-ts_mean(close, 5))", panel)
    inner = ops.ts_mean(panel, "close", 5)
    expected = ops.rank(panel, -inner)
    pd.testing.assert_series_equal(_norm(got), _norm(expected), check_names=False)


def test_sandbox_validate_accepts_unary_minus() -> None:
    """Sandbox 接受 -expr 形式（因为会展开为已注册 neg）。"""
    assert Sandbox().validate("-close") is True
    assert Sandbox().validate("rank(-ts_mean(close, 5))") is True


def test_sandbox_validate_accepts_neg_call() -> None:
    """Sandbox 接受显式 neg(...) 形式。"""
    assert Sandbox().validate("neg(close)") is True
    assert Sandbox().validate("rank(neg(ts_mean(close, 5)))") is True
