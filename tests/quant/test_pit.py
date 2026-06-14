from datetime import date, datetime

from quant.data.pit import derive_available_at, max_available_at, pit_confidence_for


def test_daily_ohlc_live_15():
    assert derive_available_at("daily_ohlc", date(2024, 3, 15), live=True) == datetime(2024, 3, 15, 15, 0)


def test_longhubang_18():
    assert derive_available_at("longhubang", date(2024, 3, 15), live=True) == datetime(2024, 3, 15, 18, 0)


def test_margin_next_day():
    assert derive_available_at("margin", date(2024, 3, 15), live=True) == datetime(2024, 3, 16, 0, 0)


def test_financial_needs_disclose_at():
    assert derive_available_at("financial", date(2024, 3, 31), live=False, disclose_at=date(2024, 4, 28)) == datetime(2024, 4, 28, 0, 0)
    try:
        derive_available_at("financial", date(2024, 3, 31), live=False)
        assert False
    except NotImplementedError:
        pass


def test_unknown_dataset_raises():
    try:
        derive_available_at("xxx", date(2024, 1, 1), live=True)
        assert False
    except ValueError:
        pass


def test_pit_confidence_for_live_flag():
    assert pit_confidence_for(True) == "live"
    assert pit_confidence_for(False) == "rule_inferred"


def test_max_available_at_takes_latest():
    assert max_available_at([datetime(2024, 3, 15, 15), datetime(2024, 3, 15, 18), datetime(2024, 3, 16, 9)]) == datetime(2024, 3, 16, 9)


def test_max_available_at_empty_raises():
    try:
        max_available_at([])
        assert False
    except ValueError:
        pass
