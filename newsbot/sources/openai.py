from __future__ import annotations

import feedparser
import httpx

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.base import NewsSource, parse_struct_time

OPENAI_RSS_URL = "https://openai.com/news/rss.xml"


def parse_openai_rss(content: str) -> list[NormalizedNewsItem]:
    feed = feedparser.parse(content)
    items: list[NormalizedNewsItem] = []
    for entry in feed.entries:
        link = (entry.get("link") or "").strip()
        external_id = (entry.get("id") or entry.get("guid") or link).strip()
        title = (entry.get("title") or "").strip()
        if not link or not external_id or not title:
            continue

        items.append(
            NormalizedNewsItem(
                source_key="openai",
                source_label="OpenAI",
                external_id=external_id,
                title=title,
                url=link,
                published_at=parse_struct_time(entry.get("published_parsed") or entry.get("updated_parsed")),
            )
        )
    return items


class OpenAINewsSource(NewsSource):
    key = "openai"
    label = "OpenAI"

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(OPENAI_RSS_URL)
        response.raise_for_status()
        return parse_openai_rss(response.text)

