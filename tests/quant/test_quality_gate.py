from quant.quality.gate import DataQualityGate, Verdict


def _clean_bar(close=100.0):
    # 构造一个合法的 bar
    return {
        "symbol": "000001.SZ",
        "open": 100.0,
        "high": 105.0,
        "low": 98.0,
        "close": close,
        "volume": 10000,
        "trade_date": "2024-01-05",
    }


def test_clean_bar_passes():
    # 合法 bar 应通过
    gate = DataQualityGate()
    result = gate.validate_bar(_clean_bar())
    assert result.decision is Verdict.PASS


def test_missing_volume_denied():
    # volume=None 应被拒
    gate = DataQualityGate()
    bar = _clean_bar()
    bar["volume"] = None
    result = gate.validate_bar(bar)
    assert result.decision is Verdict.DENY
    assert "volume" in result.reason


def test_missing_field_denied():
    # 缺 close 键应被拒
    gate = DataQualityGate()
    bar = _clean_bar()
    del bar["close"]
    result = gate.validate_bar(bar)
    assert result.decision is Verdict.DENY


def test_ohlc_inconsistent_denied():
    # high<low 或 high<close 应被拒
    gate = DataQualityGate()
    bar = _clean_bar()
    bar["high"] = 90.0  # high < close(100)
    result = gate.validate_bar(bar)
    assert result.decision is Verdict.DENY
    assert "ohlc" in result.reason


def test_negative_value_denied():
    # 负量或负价应被拒
    gate = DataQualityGate()
    bar = _clean_bar()
    bar["volume"] = -1
    result = gate.validate_bar(bar)
    assert result.decision is Verdict.DENY


def test_deny_default_unknown_dataset():
    # 未知 dataset 默认拒绝
    gate = DataQualityGate()
    result = gate.validate("unknown", {})
    assert result.decision is Verdict.DENY
    assert "unknown" in result.reason


def test_validate_dispatches_bar():
    # validate 对 bar dataset 分派到 validate_bar
    gate = DataQualityGate()
    result = gate.validate("bar", _clean_bar())
    assert result.decision is Verdict.PASS


def test_cross_section_outlier_denied():
    # 截面 z-score：一个离群点应被拒，其余通过
    gate = DataQualityGate()
    bars = [_clean_bar(close=100.0) for _ in range(30)] + [_clean_bar(close=1000000.0)]
    results = gate.validate_bars_cross_section(bars, field="close", z_threshold=5.0)
    assert len(results) == 31
    assert results[-1].decision is Verdict.DENY
    assert "outlier" in results[-1].reason
    for r in results[:-1]:
        assert r.decision is Verdict.PASS


def test_cross_section_small_sample_all_pass():
    # 样本<2 时无法算 z，全部通过
    gate = DataQualityGate()
    bars = [_clean_bar(close=100.0)]
    results = gate.validate_bars_cross_section(bars, field="close")
    assert len(results) == 1
    assert all(r.decision is Verdict.PASS for r in results)
