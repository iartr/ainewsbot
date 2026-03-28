from __future__ import annotations

import feedparser
import httpx

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.base import NewsSource, parse_struct_time


def parse_rss_items(content: str, *, source_key: str, source_label: str) -> list[NormalizedNewsItem]:
    feed = feedparser.parse(content)
    items: list[NormalizedNewsItem] = []
    seen_external_ids: set[str] = set()

    for entry in feed.entries:
        link = (entry.get("link") or "").strip()
        external_id = (entry.get("id") or entry.get("guid") or link).strip()
        title = (entry.get("title") or "").strip()
        if not link or not external_id or not title or external_id in seen_external_ids:
            continue

        seen_external_ids.add(external_id)
        items.append(
            NormalizedNewsItem(
                source_key=source_key,
                source_label=source_label,
                external_id=external_id,
                title=title,
                url=link,
                published_at=parse_struct_time(entry.get("published_parsed") or entry.get("updated_parsed")),
            )
        )

    return items


class RssFeedSource(NewsSource):
    def __init__(self, *, key: str, label: str, feed_url: str):
        self.key = key
        self.label = label
        self.feed_url = feed_url

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(self.feed_url)
        response.raise_for_status()
        return parse_rss_items(response.text, source_key=self.key, source_label=self.label)
