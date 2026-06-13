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
