from __future__ import annotations

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.rss import RssFeedSource, parse_rss_items

OPENAI_RSS_URL = "https://openai.com/news/rss.xml"


def parse_openai_rss(content: str) -> list[NormalizedNewsItem]:
    return parse_rss_items(content, source_key="openai", source_label="OpenAI")


class OpenAINewsSource(RssFeedSource):
    def __init__(self):
        super().__init__(key="openai", label="OpenAI", feed_url=OPENAI_RSS_URL)
