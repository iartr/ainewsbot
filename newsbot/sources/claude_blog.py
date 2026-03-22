from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from newsbot.entities import NormalizedNewsItem
from newsbot.sources.base import NewsSource, ensure_utc, normalize_whitespace

LOGGER = logging.getLogger(__name__)
CLAUDE_BLOG_URL = "https://claude.com/blog"
CLAUDE_BLOG_ALLOWED_HOSTS = {"", "claude.com", "www.claude.com"}
MAX_CANDIDATES = 15
FULL_DATE_RE = re.compile(
    r"(?P<date>"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) "
    r"\d{1,2}, \d{4})"
)


@dataclass(frozen=True, slots=True)
class ClaudeBlogCandidate:
    url: str
    fallback_title: str
    fallback_published_at: datetime | None


def normalize_claude_blog_title(value: str) -> str:
    return normalize_whitespace(value)


def normalize_claude_blog_url(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def parse_claude_blog_date(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = normalize_whitespace(value)

    try:
        return ensure_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
    except ValueError:
        pass

    match = FULL_DATE_RE.search(normalized)
    if match is None:
        return None

    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(match.group("date"), pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _is_claude_blog_article_link(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in CLAUDE_BLOG_ALLOWED_HOSTS:
        return False

    path = parsed.path.rstrip("/")
    if not path or path == "/blog":
        return False
    if not path.startswith("/blog/"):
        return False
    if path.startswith("/blog/category/"):
        return False
    return True


def extract_claude_blog_listing_title(container) -> str | None:
    for selector in ("h1", "h2", "h3", "h4", "h5", "h6"):
        heading = container.find(selector)
        if heading is None:
            continue

        title = normalize_claude_blog_title(heading.get_text(" ", strip=True))
        if title:
            return title
    return None


def extract_claude_blog_listing_published_at(container) -> datetime | None:
    for text in container.stripped_strings:
        published_at = parse_claude_blog_date(text)
        if published_at is not None:
            return published_at
    return None


def _collect_container_article_links(container) -> set[str]:
    urls: set[str] = set()
    if getattr(container, "name", None) == "a" and container.get("href"):
        absolute_url = normalize_claude_blog_url(urljoin(CLAUDE_BLOG_URL, container.get("href", "")))
        if _is_claude_blog_article_link(absolute_url):
            urls.add(absolute_url)

    for anchor in container.select("a[href]"):
        href = anchor.get("href", "")
        absolute_url = normalize_claude_blog_url(urljoin(CLAUDE_BLOG_URL, href))
        if _is_claude_blog_article_link(absolute_url):
            urls.add(absolute_url)
    return urls


def _extract_candidate_from_anchor(anchor, url: str) -> ClaudeBlogCandidate | None:
    fallback_candidate: ClaudeBlogCandidate | None = None

    for parent in (anchor, *anchor.parents):
        if getattr(parent, "name", None) is None:
            continue

        title = extract_claude_blog_listing_title(parent)
        if not title:
            if parent.name == "main":
                break
            continue

        article_links = _collect_container_article_links(parent)
        if url not in article_links:
            if parent.name == "main":
                break
            continue

        candidate = ClaudeBlogCandidate(
            url=url,
            fallback_title=title,
            fallback_published_at=extract_claude_blog_listing_published_at(parent),
        )

        if len(article_links) == 1:
            return candidate
        if fallback_candidate is None:
            fallback_candidate = candidate

        if parent.name == "main":
            break

    return fallback_candidate


def parse_claude_blog_listing(content: str) -> list[ClaudeBlogCandidate]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.find("main") or soup
    seen: set[str] = set()
    candidates: list[ClaudeBlogCandidate] = []

    for anchor in root.select("a[href]"):
        href = anchor.get("href", "")
        absolute_url = normalize_claude_blog_url(urljoin(CLAUDE_BLOG_URL, href))
        if not _is_claude_blog_article_link(absolute_url):
            continue
        if absolute_url in seen:
            continue

        candidate = _extract_candidate_from_anchor(anchor, absolute_url)
        if candidate is None:
            continue

        seen.add(absolute_url)
        candidates.append(candidate)

    return candidates


def _iter_json_ld_objects(content: str):
    soup = BeautifulSoup(content, "lxml")
    for node in soup.select('script[type="application/ld+json"]'):
        payload = node.string or node.get_text(strip=True)
        if not payload:
            continue

        try:
            parsed = json.loads(payload)
        except JSONDecodeError:
            continue

        yield from _flatten_json_ld(parsed)


def _flatten_json_ld(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _flatten_json_ld(item)
        return

    if not isinstance(payload, dict):
        return

    graph = payload.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _flatten_json_ld(item)
        return

    yield payload


def _json_ld_has_type(payload: dict, expected_type: str) -> bool:
    payload_type = payload.get("@type")
    if isinstance(payload_type, str):
        return payload_type == expected_type
    if isinstance(payload_type, list):
        return expected_type in payload_type
    return False


def parse_claude_blog_article_title(content: str) -> str | None:
    for payload in _iter_json_ld_objects(content):
        if not _json_ld_has_type(payload, "BlogPosting"):
            continue

        title = normalize_claude_blog_title(str(payload.get("headline", "")))
        if title:
            return title

    soup = BeautifulSoup(content, "lxml")
    heading = soup.find("h1")
    if heading is None:
        return None

    title = normalize_claude_blog_title(heading.get_text(" ", strip=True))
    return title or None


def parse_claude_blog_article_published_at(content: str) -> datetime | None:
    for payload in _iter_json_ld_objects(content):
        if not _json_ld_has_type(payload, "BlogPosting"):
            continue

        published_at = parse_claude_blog_date(str(payload.get("datePublished", "")))
        if published_at is not None:
            return published_at

    soup = BeautifulSoup(content, "lxml")
    for text_node in soup.find_all(string=True):
        if normalize_whitespace(text_node) != "Date":
            continue

        container = text_node.parent.parent if text_node.parent is not None else None
        if container is None:
            continue

        for text in container.stripped_strings:
            if normalize_whitespace(text) == "Date":
                continue

            published_at = parse_claude_blog_date(text)
            if published_at is not None:
                return published_at

    return None


class ClaudeBlogSource(NewsSource):
    key = "claude_blog"
    label = "Claude Blog"

    async def _fetch_article_item(
        self,
        client: httpx.AsyncClient,
        candidate: ClaudeBlogCandidate,
    ) -> NormalizedNewsItem:
        response = await client.get(candidate.url)
        response.raise_for_status()

        title = parse_claude_blog_article_title(response.text) or candidate.fallback_title
        if not title:
            raise ValueError(f"Unable to determine title for {candidate.url}")

        published_at = parse_claude_blog_article_published_at(response.text)
        if published_at is None:
            published_at = candidate.fallback_published_at

        return NormalizedNewsItem(
            source_key=self.key,
            source_label=self.label,
            external_id=candidate.url,
            title=title,
            url=candidate.url,
            published_at=published_at,
        )

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        response = await client.get(CLAUDE_BLOG_URL)
        response.raise_for_status()

        candidates = parse_claude_blog_listing(response.text)[:MAX_CANDIDATES]
        results = await asyncio.gather(
            *(self._fetch_article_item(client, candidate) for candidate in candidates),
            return_exceptions=True,
        )

        items: list[NormalizedNewsItem] = []
        for candidate, result in zip(candidates, results, strict=True):
            if isinstance(result, Exception):
                LOGGER.warning("Failed to fetch Claude blog article %s: %s", candidate.url, result)
                if not candidate.fallback_title:
                    continue

                items.append(
                    NormalizedNewsItem(
                        source_key=self.key,
                        source_label=self.label,
                        external_id=candidate.url,
                        title=candidate.fallback_title,
                        url=candidate.url,
                        published_at=candidate.fallback_published_at,
                    )
                )
                continue

            items.append(result)

        return items
