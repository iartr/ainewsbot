from __future__ import annotations

from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.base import NewsSource, normalize_whitespace

CHANGELOG_URL = "https://core.telegram.org/bots/api-changelog"


def parse_telegram_changelog(content: str) -> NormalizedNewsItem:
    soup = BeautifulSoup(content, "lxml")
    recent_heading = soup.find("h3", string=lambda value: value and "Recent changes" in value)
    first_entry = recent_heading.find_next("h4") if recent_heading else soup.find("h4")
    if first_entry is None:
        raise ValueError("Telegram changelog page does not contain an h4 entry")

    anchor = first_entry.find("a", class_="anchor")
    anchor_name = ""
    if anchor is not None:
        anchor_name = anchor.get("name") or anchor.get("href", "").lstrip("#")
    if not anchor_name:
        raise ValueError("Telegram changelog entry does not expose an anchor name")

    date_text = normalize_whitespace(first_entry.get_text(" ", strip=True))
    version_block = first_entry.find_next("p")
    version_text = normalize_whitespace(version_block.get_text(" ", strip=True)) if version_block else ""
    if not version_text:
        raise ValueError("Telegram changelog entry does not contain a version block")

    published_at = datetime.strptime(date_text, "%B %d, %Y").replace(tzinfo=UTC)
    url = f"{CHANGELOG_URL}#{anchor_name}"
    title = f"{date_text} / {version_text}"

    return NormalizedNewsItem(
        source_key="telegram_bot_api",
        source_label="Telegram Bot API",
        external_id=f"{url}::{version_text}",
        title=title,
        url=url,
        published_at=published_at,
    )


class TelegramBotApiSource(NewsSource):
    key = "telegram_bot_api"
    label = "Telegram Bot API"

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(CHANGELOG_URL)
        response.raise_for_status()
        return [parse_telegram_changelog(response.text)]

