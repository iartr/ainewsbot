from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.base import NewsSource, normalize_whitespace

LOGGER = logging.getLogger(__name__)
MOONSHOT_BLOG_URL = "https://www.kimi.com/blog/"
MOONSHOT_BLOG_ALLOWED_HOSTS = {"", "kimi.com", "www.kimi.com"}
MAX_CANDIDATES = 15
MOONSHOT_DATE_RE = re.compile(r"(?P<year>20\d{2})/(?P<month>\d{1,2})/(?P<day>\d{1,2})")


@dataclass(frozen=True, slots=True)
class MoonshotBlogItem:
    url: str
    title: str
    published_at: datetime | None


def normalize_moonshot_url(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def parse_moonshot_date(value: str | None) -> datetime | None:
    if not value:
        return None

    match = MOONSHOT_DATE_RE.search(value)
    if match is None:
        return None

    try:
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _is_moonshot_article_link(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in MOONSHOT_BLOG_ALLOWED_HOSTS:
        return False

    path = parsed.path.rstrip("/")
    if not path or path == "/blog":
        return False
    return path.startswith("/blog/")


def _article_anchor_in(container) -> tuple[object, str] | None:
    for anchor in container.select("a[href]"):
        absolute_url = normalize_moonshot_url(urljoin(MOONSHOT_BLOG_URL, anchor.get("href", "")))
        if _is_moonshot_article_link(absolute_url):
            return anchor, absolute_url
    return None


def _anchor_title(anchor) -> str:
    aria_label = normalize_whitespace(anchor.get("aria-label") or "")
    if aria_label:
        return aria_label

    text = normalize_whitespace(anchor.get_text(" ", strip=True))
    if "|" in text:
        text = text.split("|", 1)[0].strip()
    return text


def parse_moonshot_blog_listing(content: str) -> list[MoonshotBlogItem]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.find("main") or soup
    items: list[MoonshotBlogItem] = []
    seen: set[str] = set()

    # Each post renders as a card whose date lives in a ``card-date`` node and
    # whose link/title live in an overlay anchor pointing at ``/blog/<slug>``.
    for date_node in root.select('[class*="card-date"]'):
        published_at = parse_moonshot_date(date_node.get_text(" ", strip=True))

        anchor_info = None
        node = date_node
        for _ in range(6):
            node = node.parent
            if node is None:
                break
            anchor_info = _article_anchor_in(node)
            if anchor_info is not None:
                break

        if anchor_info is None:
            continue

        anchor, url = anchor_info
        if url in seen:
            continue

        title = _anchor_title(anchor)
        if not title:
            continue

        seen.add(url)
        items.append(MoonshotBlogItem(url=url, title=title, published_at=published_at))

    # Fallback: if the card layout changes and no dated cards are found, degrade
    # to plain article anchors so the source keeps working (without dates).
    if not items:
        for anchor in root.select("a[href]"):
            url = normalize_moonshot_url(urljoin(MOONSHOT_BLOG_URL, anchor.get("href", "")))
            if not _is_moonshot_article_link(url) or url in seen:
                continue

            title = _anchor_title(anchor)
            if not title:
                continue

            seen.add(url)
            items.append(MoonshotBlogItem(url=url, title=title, published_at=None))

    return items


class MoonshotNewsSource(NewsSource):
    key = "moonshot"
    label = "Moonshot AI"

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(MOONSHOT_BLOG_URL)
        response.raise_for_status()

        listing = parse_moonshot_blog_listing(response.text)[:MAX_CANDIDATES]
        return [
            NormalizedNewsItem(
                source_key=self.key,
                source_label=self.label,
                external_id=item.url,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
            )
            for item in listing
        ]
