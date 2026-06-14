"""情绪二期（社媒聚合情绪）合规开关测试（设计 §4.1.2 二期 + §16 合规）。

合规要点：
- 合规开关默认关，需用户显式知情开启；
- 不存可识别个人内容（仅匿名化聚合指标）；
- force 不可绕过合规前置。
"""
from __future__ import annotations

import pytest

from quant.factor.factors.sentiment_v2 import (
    ComplianceConfig,
    SentimentProviderV2,
    SocialSentiment,
)


def test_default_disabled():
    """默认 ComplianceConfig → is_enabled=False。"""
    provider = SentimentProviderV2()
    assert provider.is_enabled() is False


def test_requires_user_acknowledged():
    """enabled=True 但 user_acknowledged=False → is_enabled=False。"""
    cfg = ComplianceConfig(enabled=True, user_acknowledged=False)
    provider = SentimentProviderV2(cfg)
    assert provider.is_enabled() is False


def test_store_personal_blocks():
    """store_personal_content=True → is_enabled=False（合规违规禁用）。"""
    cfg = ComplianceConfig(
        enabled=True, user_acknowledged=True, store_personal_content=True
    )
    provider = SentimentProviderV2(cfg)
    assert provider.is_enabled() is False


def test_enabled_when_all_compliant():
    """enabled+acknowledged+not store_personal → is_enabled=True。"""
    cfg = ComplianceConfig(
        enabled=True, user_acknowledged=True, store_personal_content=False
    )
    provider = SentimentProviderV2(cfg)
    assert provider.is_enabled() is True


def test_fetch_disabled_returns_none():
    """未开启 fetch → None。"""
    provider = SentimentProviderV2()  # 默认关
    assert provider.fetch("茅台") is None


def test_fetch_enabled_stub():
    """开启 → fetch 返回 SocialSentiment（stub 聚合）。"""
    cfg = ComplianceConfig(
        enabled=True, user_acknowledged=True, store_personal_content=False,
        platforms=["douyin", "xiaohongshu", "weibo"],
    )
    provider = SentimentProviderV2(cfg)
    result = provider.fetch("茅台")
    assert isinstance(result, SocialSentiment)
    assert result.discussion_count >= 0
    assert isinstance(result.keyword_freq, dict)
    assert -1.0 <= result.bullish_score <= 1.0


def test_force_cannot_bypass_compliance():
    """force=True 但未合规 → None（合规不可绕过）。"""
    provider = SentimentProviderV2()  # 默认关
    assert provider.fetch("茅台", force=True) is None


def test_aggregate_strips_personal():
    """aggregate(raw_posts 含 user_id/nickname) → 仅聚合统计，无个人字段。"""
    raw_posts = [
        {"user_id": "u_001", "nickname": "小明", "text": "茅台涨疯了 牛逼"},
        {"user_id": "u_002", "nickname": "老王", "text": "茅台要见顶 跑路"},
        {"user_id": "u_003", "nickname": "阿强", "text": "茅台继续看好"},
    ]
    cfg = ComplianceConfig(
        enabled=True, user_acknowledged=True, store_personal_content=False
    )
    provider = SentimentProviderV2(cfg)
    result = provider.aggregate(raw_posts)
    assert isinstance(result, SocialSentiment)
    # 讨论数 = 帖子数
    assert result.discussion_count == 3
    # 关键词词频仅聚合，非个人
    assert isinstance(result.keyword_freq, dict)
    assert result.keyword_freq.get("茅台", 0) == 3
    # 情绪分在 [-1, 1]
    assert -1.0 <= result.bullish_score <= 1.0
    # 返回对象本身无任何个人字段（dataclass 字段集合仅为聚合三件套）
    field_names = {f.name for f in result.__dataclass_fields__.values()}
    assert field_names == {"discussion_count", "keyword_freq", "bullish_score"}


def test_compliance_note():
    """模块 docstring 注明合规开关默认关 + 不存个人内容 + 用户显式开启。"""
    from quant.factor.factors import sentiment_v2

    doc = sentiment_v2.__doc__ or ""
    assert "合规开关默认关" in doc
    assert "不存" in doc and "个人" in doc
    assert "用户显式开启" in doc or "显式知情开启" in doc
