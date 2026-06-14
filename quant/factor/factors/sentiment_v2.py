"""情绪二期：社媒聚合情绪（设计 v0.5 §4.1.2 二期 + §16 合规）。

合规要点（合规开关默认关）：
- **合规开关默认关**，需用户**显式知情开启**（enabled + user_acknowledged 双确认）；
- **不存可识别个人内容**：仅保留匿名化聚合指标（讨论数、关键词词频、情绪分），
  原始帖子中的 user_id / nickname 等个人字段在 aggregate 阶段即剥离；
- 散户情绪反向 alpha 的真正数据源（抖音 / 小红书 / 微博热门聚合），
  真实抓取为合规敏感操作，留待用户开启后接入；未开启时 fetch 返回 None。

二期与一期边界：一期市场宽度因子已交付（见 breadth.py），
二期专注社媒聚合情绪，互不替代。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# 简单中文情绪关键词表（stub 用，真实接入由用户开启后扩展）
_BULLISH_KEYWORDS = frozenset({"涨", "牛", "看好", "加仓", "买入", "强势", "继续"})
_BEARISH_KEYWORDS = frozenset({"跌", "熊", "看空", "减仓", "卖出", "跑路", "见顶"})


@dataclass
class ComplianceConfig:
    """合规配置：开关默认关，需用户显式知情开启。

    enabled：用户主观开关；
    user_acknowledged：用户已读合规说明并同意（双确认，避免误开）；
    platforms：抓取平台子集 ['douyin','xiaohongshu','weibo']，None 表示全部默认；
    store_personal_content：是否存可识别个人内容，**默认 False 且不应改 True**。
    """

    enabled: bool = False
    user_acknowledged: bool = False
    platforms: list | None = None
    store_personal_content: bool = False


@dataclass
class SocialSentiment:
    """社媒聚合情绪（匿名化，无个人可识别字段）。

    discussion_count：讨论数（聚合，非个人）；
    keyword_freq：关键词词频（聚合，非个人）；
    bullish_score：聚合情绪分，取值 [-1, 1]（正为偏多，负为偏空，0 中性）。
    """

    discussion_count: int
    keyword_freq: dict
    bullish_score: float = 0.0


class SentimentProviderV2:
    """情绪二期：社媒聚合情绪提供方。合规开关默认关。"""

    def __init__(self, compliance: ComplianceConfig | None = None):
        self.compliance = compliance or ComplianceConfig()

    def is_enabled(self) -> bool:
        """合规前置：enabled AND user_acknowledged AND NOT store_personal_content。

        store_personal_content=True 视为合规违规，强制禁用。
        """
        return (
            self.compliance.enabled
            and self.compliance.user_acknowledged
            and not self.compliance.store_personal_content
        )

    def fetch(self, keyword: str, *, force: bool = False) -> SocialSentiment | None:
        """抓取社媒聚合情绪。

        未开启（is_enabled False）→ 返回 None（合规禁用）。
        force=True 仍需 is_enabled（不可绕过合规前置）。
        开启 → stub 抓取（占位聚合指标，真实抓取合规敏感留用户开启后接入）。
        """
        # force 不绕过合规：合规未满足一律 None
        if not self.is_enabled():
            return None
        return self._stub_fetch(keyword)

    def aggregate(
        self, raw_posts: list[dict], *, keyword: str | None = None
    ) -> SocialSentiment:
        """聚合原始帖子 → 讨论数 / 关键词词频 / 情绪分。

        剥离个人可识别信息：丢弃 user_id / nickname 等字段，
        仅保留 text 的关键词词频聚合与情绪分计算。
        keyword：可选标的代称，若提供则计入 keyword_freq（命中次数）。
        """
        discussion_count = len(raw_posts)
        keyword_freq: Counter = Counter()
        bullish_hits = 0
        bearish_hits = 0

        # 标的代称命中次数（聚合，非个人）
        if keyword:
            keyword_freq[keyword] = sum(
                1 for p in raw_posts if keyword in (p.get("text", "") or "")
            )

        # 自动识别重复出现的中文词（CJK 2-gram），命中≥2 次视为讨论标的/主题词
        bigram: Counter = Counter()
        for post in raw_posts:
            cjk = re.findall(r"[一-鿿]", post.get("text", "") or "")
            for i in range(len(cjk) - 1):
                bigram["".join(cjk[i : i + 2])] += 1
        for token, cnt in bigram.items():
            if cnt >= 2 and token not in keyword_freq:
                keyword_freq[token] = cnt

        for post in raw_posts:
            text = post.get("text", "") or ""
            # 情绪关键词整词匹配，匿名化聚合到词频
            for kw in _BULLISH_KEYWORDS | _BEARISH_KEYWORDS:
                if kw and kw in text:
                    keyword_freq[kw] += 1
            # 情绪命中计数（用于情绪分）
            for kw in _BULLISH_KEYWORDS:
                if kw in text:
                    bullish_hits += 1
            for kw in _BEARISH_KEYWORDS:
                if kw in text:
                    bearish_hits += 1

        # 情绪分 = (看多命中 - 看空命中) / 总命中，无命中则中性
        total_hits = bullish_hits + bearish_hits
        bullish_score = (
            (bullish_hits - bearish_hits) / total_hits if total_hits > 0 else 0.0
        )

        return SocialSentiment(
            discussion_count=discussion_count,
            keyword_freq=dict(keyword_freq),
            bullish_score=round(bullish_score, 4),
        )

    def _stub_fetch(self, keyword: str) -> SocialSentiment:
        """stub 抓取：返回固定聚合占位指标。

        真实抓取涉及第三方平台合规与限流，留待用户开启后接入。
        """
        return self.aggregate(
            [
                {"text": f"{keyword} 涨 看好"},
                {"text": f"{keyword} 强势 继续"},
                {"text": f"{keyword} 加仓"},
            ],
            keyword=keyword,
        )
