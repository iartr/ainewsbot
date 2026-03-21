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
OPENAI_BLOG_URL = "https://developers.openai.com/blog"
OPENAI_BLOG_ALLOWED_HOSTS = {"", "developers.openai.com"}
MAX_CANDIDATES = 15
OPENAI_BLOG_TITLE_SUFFIX = " | OpenAI Developers"
SHORT_DATE_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$"
)
FULL_DATE_RE = re.compile(
    r"(?P<date>"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) "
    r"\d{1,2}, \d{4})"
)


@dataclass(frozen=True, slots=True)
class OpenAIBlogCandidate:
    url: str
    fallback_title: str


def normalize_openai_blog_title(value: str) -> str:
    title = normalize_whitespace(value)
    if title.endswith(OPENAI_BLOG_TITLE_SUFFIX):
        title = title.removesuffix(OPENAI_BLOG_TITLE_SUFFIX).strip()
    return title


def normalize_openai_blog_url(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def parse_openai_blog_date(value: str | None) -> datetime | None:
    if not value:
        return None

    match = FULL_DATE_RE.search(value)
    if match is None:
        return None

    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(match.group("date"), pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _is_openai_blog_article_link(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in OPENAI_BLOG_ALLOWED_HOSTS:
        return False

    path = parsed.path.rstrip("/")
    if not path or path == "/blog":
        return False
    if not path.startswith("/blog/"):
        return False
    if path.startswith("/blog/topic/"):
        return False
    return True


def extract_openai_blog_listing_title(anchor) -> str | None:
    for selector in ("h1", "h2", "h3", "h4", "h5", "h6"):
        node = anchor.find(selector)
        if node is None:
            continue
        title = normalize_openai_blog_title(node.get_text(" ", strip=True))
        if title:
            return title

    seen: set[str] = set()
    for node in anchor.find_all(["div", "span"], recursive=True):
        text = normalize_openai_blog_title(node.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)

        if SHORT_DATE_RE.fullmatch(text) or FULL_DATE_RE.fullmatch(text):
            continue
        return text

    title = normalize_openai_blog_title(anchor.get_text(" ", strip=True))
    return title or None


def parse_openai_blog_listing(content: str) -> list[OpenAIBlogCandidate]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.find("main") or soup
    seen: set[str] = set()
    candidates: list[OpenAIBlogCandidate] = []

    for anchor in root.select("a[href]"):
        href = anchor.get("href", "")
        absolute_url = normalize_openai_blog_url(urljoin(OPENAI_BLOG_URL, href))
        if not _is_openai_blog_article_link(absolute_url):
            continue
        if absolute_url in seen:
            continue

        fallback_title = extract_openai_blog_listing_title(anchor)
        if not fallback_title:
            continue

        seen.add(absolute_url)
        candidates.append(
            OpenAIBlogCandidate(
                url=absolute_url,
                fallback_title=fallback_title,
            )
        )
    return candidates


def parse_openai_blog_article_title(content: str) -> str | None:
    soup = BeautifulSoup(content, "lxml")
    for selector, attribute in (
        ('meta[property="og:title"]', "content"),
        ('meta[name="twitter:title"]', "content"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            title = normalize_openai_blog_title(node.get(attribute, ""))
            if title:
                return title

    heading = soup.find("h1")
    if heading:
        title = normalize_openai_blog_title(heading.get_text(" ", strip=True))
        if title:
            return title
    return None


def parse_openai_blog_article_published_at(content: str) -> datetime | None:
    soup = BeautifulSoup(content, "lxml")

    for node in soup.select("time[datetime]"):
        published_at = parse_openai_blog_date(node.get("datetime"))
        if published_at is not None:
            return published_at

    header = soup.find("header")
    if header is not None:
        published_at = parse_openai_blog_date(header.get_text(" ", strip=True))
        if published_at is not None:
            return published_at

    for node in soup.select("time"):
        published_at = parse_openai_blog_date(node.get_text(" ", strip=True))
        if published_at is not None:
            return published_at

    return None


class OpenAIBlogSource(NewsSource):
    key = "openai_blog"
    label = "OpenAI Blog"

    async def _fetch_article_item(
        self,
        client: httpx.AsyncClient,
        candidate: OpenAIBlogCandidate,
    ) -> NormalizedNewsItem:
        response = await client.get(candidate.url)
        response.raise_for_status()

        title = parse_openai_blog_article_title(response.text) or candidate.fallback_title
        if not title:
            raise ValueError(f"Unable to determine title for {candidate.url}")

        return NormalizedNewsItem(
            source_key=self.key,
            source_label=self.label,
            external_id=candidate.url,
            title=title,
            url=candidate.url,
            published_at=parse_openai_blog_article_published_at(response.text),
        )

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(OPENAI_BLOG_URL)
        response.raise_for_status()

        candidates = parse_openai_blog_listing(response.text)[:MAX_CANDIDATES]
        results = await asyncio.gather(
            *(self._fetch_article_item(client, candidate) for candidate in candidates),
            return_exceptions=True,
        )

        items: list[NormalizedNewsItem] = []
        for candidate, result in zip(candidates, results, strict=True):
            if isinstance(result, Exception):
                LOGGER.warning("Failed to fetch OpenAI blog article %s: %s", candidate.url, result)
                if not candidate.fallback_title:
                    continue

                items.append(
                    NormalizedNewsItem(
                        source_key=self.key,
                        source_label=self.label,
                        external_id=candidate.url,
                        title=candidate.fallback_title,
                        url=candidate.url,
                        published_at=None,
                    )
                )
                continue

            items.append(result)

        return items
