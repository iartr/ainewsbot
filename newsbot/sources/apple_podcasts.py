from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from newsbot.entities import NormalizedNewsItem, utcnow
from newsbot.sources.base import NewsSource, ensure_utc, normalize_whitespace
from newsbot.sources.rss import parse_rss_items

APPLE_PODCASTS_LOOKUP_URL = "https://itunes.apple.com/lookup"
APPLE_PODCASTS_EPISODE_LIMIT = 200
APPLE_PODCASTS_SUBSCRIBERS_ONLY_MARKER = "SUBSCRIBERS ONLY"
APPLE_PODCASTS_TRAILER_MARKER = "TRAILER"
APPLE_PODCASTS_DAY_AGO_RE = re.compile(r"^(?P<days>\d+)\s+DAYS?\s+AGO$")
APPLE_PODCASTS_SHORT_DATE_RE = re.compile(r"^(?P<day>\d{1,2})\s+(?P<month>[A-Z]{3})$")
APPLE_PODCASTS_FULL_DATE_RE = re.compile(r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})$")
APPLE_PODCASTS_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def normalize_apple_podcast_episode_url(value: str) -> str:
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    filtered_query = []
    for key in ("i", "l"):
        for item in query.get(key, []):
            filtered_query.append((key, item))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/") or parsed.path,
            "",
            "&".join(f"{key}={item}" for key, item in filtered_query),
            "",
        )
    )


def extract_apple_podcast_episode_id(value: str) -> str:
    parsed = urlparse(value)
    episode_ids = parse_qs(parsed.query).get("i")
    if episode_ids:
        return episode_ids[0]
    return value


def parse_apple_podcast_published_at(value: str, *, now: datetime | None = None) -> datetime | None:
    now = ensure_utc(now or utcnow())
    date_label = normalize_whitespace(value).upper()
    if not date_label:
        return None

    date_label = date_label.split("•", 1)[0].strip()
    if not date_label or date_label == APPLE_PODCASTS_TRAILER_MARKER:
        return None
    if date_label == "TODAY":
        return datetime(now.year, now.month, now.day, tzinfo=UTC)
    if date_label == "YESTERDAY":
        day = now - timedelta(days=1)
        return datetime(day.year, day.month, day.day, tzinfo=UTC)

    if day_ago_match := APPLE_PODCASTS_DAY_AGO_RE.fullmatch(date_label):
        day = now - timedelta(days=int(day_ago_match.group("days")))
        return datetime(day.year, day.month, day.day, tzinfo=UTC)

    if full_date_match := APPLE_PODCASTS_FULL_DATE_RE.fullmatch(date_label):
        return datetime(
            int(full_date_match.group("year")),
            int(full_date_match.group("month")),
            int(full_date_match.group("day")),
            tzinfo=UTC,
        )

    if short_date_match := APPLE_PODCASTS_SHORT_DATE_RE.fullmatch(date_label):
        month = APPLE_PODCASTS_MONTHS[short_date_match.group("month")]
        day = int(short_date_match.group("day"))
        year = now.year
        if month > now.month or (month == now.month and day > now.day):
            year -= 1
        return datetime(year, month, day, tzinfo=UTC)

    return None


def parse_apple_podcast_listing(
    content: str,
    *,
    source_key: str,
    source_label: str,
    page_url: str,
    now: datetime | None = None,
) -> list[NormalizedNewsItem]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.find("main") or soup
    items: list[NormalizedNewsItem] = []
    seen_external_ids: set[str] = set()

    for anchor in root.select('a[data-testid="click-action"][href*="?i="]'):
        title_node = anchor.select_one('[data-testid="episode-lockup-title"]')
        eyebrow_node = anchor.select_one('[data-testid="episode-details__published-date"]')
        if title_node is None or eyebrow_node is None:
            continue

        eyebrow = normalize_whitespace(eyebrow_node.get_text(" ", strip=True))
        if APPLE_PODCASTS_TRAILER_MARKER in eyebrow.upper():
            continue

        title = normalize_whitespace(title_node.get_text(" ", strip=True))
        href = urljoin(page_url, anchor.get("href", ""))
        if not title or not href:
            continue

        url = normalize_apple_podcast_episode_url(href)
        external_id = extract_apple_podcast_episode_id(url)
        if external_id in seen_external_ids:
            continue

        seen_external_ids.add(external_id)
        items.append(
            NormalizedNewsItem(
                source_key=source_key,
                source_label=source_label,
                external_id=external_id,
                title=title,
                url=url,
                published_at=parse_apple_podcast_published_at(eyebrow, now=now),
            )
        )

    return items


def parse_apple_podcast_lookup_items(
    content: str,
    *,
    source_key: str,
    source_label: str,
) -> list[NormalizedNewsItem]:
    payload = json.loads(content)
    items: list[NormalizedNewsItem] = []
    seen_external_ids: set[str] = set()

    for result in payload.get("results", [])[1:]:
        title = normalize_whitespace(result.get("trackName") or "")
        href = (result.get("trackViewUrl") or "").strip()
        if not title or not href or "?i=" not in href:
            continue

        url = normalize_apple_podcast_episode_url(href)
        external_id = extract_apple_podcast_episode_id(url)
        if external_id in seen_external_ids:
            continue

        published_at = ensure_utc(datetime.fromisoformat(result["releaseDate"].replace("Z", "+00:00")))
        seen_external_ids.add(external_id)
        items.append(
            NormalizedNewsItem(
                source_key=source_key,
                source_label=source_label,
                external_id=external_id,
                title=title,
                url=url,
                published_at=published_at,
            )
        )

    return items


def _podcast_merge_key(item: NormalizedNewsItem) -> tuple[str, str]:
    return item.source_key, normalize_whitespace(item.title).casefold()


def merge_podcast_items(*collections: list[NormalizedNewsItem]) -> list[NormalizedNewsItem]:
    items: list[NormalizedNewsItem] = []
    seen_external_ids: set[str] = set()
    seen_merge_keys: set[tuple[str, str]] = set()

    for collection in collections:
        for item in collection:
            merge_key = _podcast_merge_key(item)
            if item.external_id in seen_external_ids or merge_key in seen_merge_keys:
                continue

            seen_external_ids.add(item.external_id)
            seen_merge_keys.add(merge_key)
            items.append(item)

    return items


class ApplePodcastSource(NewsSource):
    def __init__(self, *, key: str, label: str, page_url: str, lookup_id: str, feed_url: str):
        self.key = key
        self.label = label
        self.page_url = page_url
        self.lookup_id = lookup_id
        self.feed_url = feed_url

    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        page_items: list[NormalizedNewsItem] = []
        lookup_items: list[NormalizedNewsItem] = []
        rss_items: list[NormalizedNewsItem] = []
        errors: list[Exception] = []

        try:
            response = await client.get(self.page_url)
            response.raise_for_status()
            page_items = parse_apple_podcast_listing(
                response.text,
                source_key=self.key,
                source_label=self.label,
                page_url=self.page_url,
            )
        except Exception as exc:
            errors.append(exc)

        try:
            response = await client.get(
                APPLE_PODCASTS_LOOKUP_URL,
                params={"id": self.lookup_id, "entity": "podcastEpisode", "limit": APPLE_PODCASTS_EPISODE_LIMIT},
            )
            response.raise_for_status()
            lookup_items = parse_apple_podcast_lookup_items(
                response.text,
                source_key=self.key,
                source_label=self.label,
            )
        except Exception as exc:
            errors.append(exc)

        try:
            response = await client.get(self.feed_url)
            response.raise_for_status()
            rss_items = parse_rss_items(
                response.text,
                source_key=self.key,
                source_label=self.label,
            )
        except Exception as exc:
            errors.append(exc)

        items = merge_podcast_items(page_items, lookup_items, rss_items)
        if items:
            return items
        if errors:
            raise errors[-1]
        return []
