from __future__ import annotations

import asyncio
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
ANTHROPIC_NEWS_URL = "https://www.anthropic.com/news"
MAX_CANDIDATES = 15

DATE_RE = re.compile(
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) "
    r"(?P<day>\d{1,2}), (?P<year>\d{4})"
)
KNOWN_CATEGORIES = (
    "Announcements",
    "Announcement",
    "Product",
    "Products",
    "Policy",
    "Research",
    "Safety",
    "Company",
)


@dataclass(frozen=True, slots=True)
class AnthropicCandidate:
    url: str
    raw_text: str
    published_at: datetime | None


def parse_anthropic_date(value: str) -> datetime | None:
    match = DATE_RE.search(value)
    if match is None:
        return None

    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(match.group(0), pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _looks_like_article_link(url: str) -> bool:
    path = urlparse(url).path
    return path.startswith("/news/") and path != "/news"


def parse_anthropic_listing(content: str) -> list[AnthropicCandidate]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.find("main") or soup
    seen: set[str] = set()
    candidates: list[AnthropicCandidate] = []

    for anchor in root.select("a[href]"):
        href = anchor.get("href", "")
        absolute_url = urljoin(ANTHROPIC_NEWS_URL, href)
        if not _looks_like_article_link(absolute_url):
            continue
        if absolute_url in seen:
            continue

        raw_text = normalize_whitespace(anchor.get_text(" ", strip=True))
        if not raw_text:
            continue

        seen.add(absolute_url)
        candidates.append(
            AnthropicCandidate(
                url=absolute_url,
                raw_text=raw_text,
                published_at=parse_anthropic_date(raw_text),
            )
        )
    return candidates


def extract_title_from_listing_text(raw_text: str) -> str:
    text = normalize_whitespace(raw_text)

    date_match = DATE_RE.search(text)
    if date_match:
        before = text[: date_match.start()].strip()
        after = text[date_match.end() :].strip()

        for category in KNOWN_CATEGORIES:
            prefix = f"{category} "
            if before == category:
                before = ""
                break
            if after.startswith(prefix):
                after = after[len(prefix) :].strip()
                break

        candidate = after or before or text
    else:
        candidate = text

    if ". " in candidate:
        head, tail = candidate.split(". ", 1)
        if tail and len(tail.split()) > 4:
            candidate = head

    return candidate.strip(" .")


def parse_anthropic_article_title(content: str) -> str | None:
    soup = BeautifulSoup(content, "lxml")
    for selector in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ):
        node = soup.select_one(selector[0])
        if node and node.get(selector[1]):
            return normalize_whitespace(node.get(selector[1], "")).rstrip("\\ ").strip()

    title_tag = soup.find("title")
    if title_tag:
        title = normalize_whitespace(title_tag.get_text(" ", strip=True))
        if title.endswith("\\ Anthropic"):
            title = title.removesuffix("\\ Anthropic").strip()
        return title
    return None


class AnthropicNewsSource(NewsSource):
    key = "anthropic"
    label = "Anthropic Newsroom"

    async def _fetch_title(self, client: httpx.AsyncClient, candidate: AnthropicCandidate) -> str:
        response = await client.get(candidate.url)
        response.raise_for_status()
        return parse_anthropic_article_title(response.text) or extract_title_from_listing_text(candidate.raw_text)

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(ANTHROPIC_NEWS_URL)
        response.raise_for_status()

        candidates = parse_anthropic_listing(response.text)[:MAX_CANDIDATES]
        results = await asyncio.gather(
            *(self._fetch_title(client, candidate) for candidate in candidates),
            return_exceptions=True,
        )

        items: list[NormalizedNewsItem] = []
        for candidate, result in zip(candidates, results, strict=True):
            if isinstance(result, Exception):
                LOGGER.warning("Failed to fetch Anthropic article title for %s: %s", candidate.url, result)
                title = extract_title_from_listing_text(candidate.raw_text)
            else:
                title = result

            if not title:
                continue

            items.append(
                NormalizedNewsItem(
                    source_key=self.key,
                    source_label=self.label,
                    external_id=candidate.url,
                    title=title,
                    url=candidate.url,
                    published_at=candidate.published_at,
                )
            )
        return items
