from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from newsbot.sources.anthropic import extract_title_from_listing_text, parse_anthropic_article_title, parse_anthropic_listing
from newsbot.sources.apple_podcasts import (
    merge_podcast_items,
    parse_apple_podcast_listing,
    parse_apple_podcast_lookup_items,
)
from newsbot.sources.claude_blog import (
    parse_claude_blog_article_published_at,
    parse_claude_blog_article_title,
    parse_claude_blog_listing,
)
from newsbot.entities import NormalizedNewsItem
from newsbot.sources.openai import parse_openai_rss
from newsbot.sources.openai_blog import (
    parse_openai_blog_article_published_at,
    parse_openai_blog_article_title,
    parse_openai_blog_listing,
)
from newsbot.sources.rss import parse_rss_items
from newsbot.sources.telegram_api import parse_telegram_changelog

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_openai_rss_returns_items() -> None:
    items = parse_openai_rss(read_fixture("openai_rss.xml"))

    assert len(items) == 2
    assert items[0].source_key == "openai"
    assert items[0].title == "How we monitor internal coding agents for misalignment"
    assert items[0].url == "https://openai.com/index/how-we-monitor-internal-coding-agents-misalignment"


def test_parse_rss_items_parses_transistor_feed_entries() -> None:
    items = parse_rss_items(
        read_fixture("transistor_rss.xml"),
        source_key="podcast_zapusk_zavtra",
        source_label="Запуск завтра",
    )

    assert len(items) == 2
    assert items[0].source_key == "podcast_zapusk_zavtra"
    assert items[0].source_label == "Запуск завтра"
    assert items[0].external_id == "episode-one"
    assert items[0].title == "Episode One"
    assert items[0].url == "https://example.com/podcast/episode-one"
    assert items[0].published_at == datetime(2026, 3, 27, 7, 0, tzinfo=UTC)


def test_parse_apple_podcast_listing_includes_subscribers_only_items() -> None:
    items = parse_apple_podcast_listing(
        read_fixture("apple_podcast_listing.html"),
        source_key="podcast_zapusk_zavtra",
        source_label="Запуск завтра",
        page_url="https://podcasts.apple.com/ru/podcast/%D0%B7%D0%B0%D0%BF%D1%83%D1%81%D0%BA-%D0%B7%D0%B0%D0%B2%D1%82%D1%80%D0%B0/id1488945593?l=en-GB",
        now=datetime(2026, 3, 28, 6, 0, tzinfo=UTC),
    )

    assert [item.title for item in items] == [
        "Гугл-поиск испортился? Как искать в интернете",
        "Главное, что случилось в мире технологий в 2025 году",
    ]
    assert items[1].external_id == "1000743186549"
    assert items[1].url.endswith("i=1000743186549&l=en-GB")
    assert items[1].published_at == datetime(2026, 1, 6, 0, 0, tzinfo=UTC)


def test_parse_apple_podcast_lookup_items_parses_free_episodes() -> None:
    items = parse_apple_podcast_lookup_items(
        read_fixture("apple_podcast_lookup.json"),
        source_key="podcast_zapusk_zavtra",
        source_label="Запуск завтра",
    )

    assert [item.title for item in items] == [
        "Гугл-поиск испортился? Как искать в интернете",
        "Почему всем так нужны видеокарты от NVIDIA",
    ]
    assert items[0].external_id == "1000757525621"
    assert items[0].url.endswith("i=1000757525621")
    assert items[0].published_at == datetime(2026, 3, 26, 15, 19, 39, tzinfo=UTC)


def test_merge_podcast_items_keeps_paid_items_and_deduplicates_free_duplicates() -> None:
    page_items = [
        NormalizedNewsItem(
            source_key="podcast_zapusk_zavtra",
            source_label="Запуск завтра",
            external_id="1000757525621",
            title="Гугл-поиск испортился? Как искать в интернете",
            url="https://podcasts.apple.com/ru/podcast/id1488945593?i=1000757525621&l=en-GB",
            published_at=datetime(2026, 3, 27, 0, 0, tzinfo=UTC),
        ),
        NormalizedNewsItem(
            source_key="podcast_zapusk_zavtra",
            source_label="Запуск завтра",
            external_id="1000743186549",
            title="Главное, что случилось в мире технологий в 2025 году",
            url="https://podcasts.apple.com/ru/podcast/id1488945593?i=1000743186549&l=en-GB",
            published_at=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        ),
    ]
    lookup_items = [
        NormalizedNewsItem(
            source_key="podcast_zapusk_zavtra",
            source_label="Запуск завтра",
            external_id="1000757525621",
            title="Гугл-поиск испортился? Как искать в интернете",
            url="https://podcasts.apple.com/us/podcast/id1488945593?i=1000757525621",
            published_at=datetime(2026, 3, 26, 15, 19, 39, tzinfo=UTC),
        )
    ]
    rss_items = [
        NormalizedNewsItem(
            source_key="podcast_zapusk_zavtra",
            source_label="Запуск завтра",
            external_id="rss-duplicate",
            title="Гугл-поиск испортился? Как искать в интернете",
            url="https://share.transistor.fm/s/34c1e42a",
            published_at=datetime(2026, 3, 26, 18, 19, 39, tzinfo=UTC),
        ),
        NormalizedNewsItem(
            source_key="podcast_zapusk_zavtra",
            source_label="Запуск завтра",
            external_id="rss-archive",
            title="Архивный выпуск",
            url="https://share.transistor.fm/s/archive",
            published_at=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        ),
    ]

    items = merge_podcast_items(page_items, lookup_items, rss_items)

    assert [item.title for item in items] == [
        "Гугл-поиск испортился? Как искать в интернете",
        "Главное, что случилось в мире технологий в 2025 году",
        "Архивный выпуск",
    ]


def test_parse_openai_blog_listing_extracts_unique_article_links_in_order() -> None:
    candidates = parse_openai_blog_listing(read_fixture("openai_blog_listing.html"))

    assert [candidate.url for candidate in candidates] == [
        "https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4",
        "https://developers.openai.com/blog/one-year-of-responses",
        "https://developers.openai.com/blog/building-frontend-uis-with-codex-and-figma",
    ]
    assert [candidate.fallback_title for candidate in candidates] == [
        "Designing delightful frontends with GPT-5.4",
        "From prompts to products: One year of Responses",
        "Building frontend UIs with Codex and Figma",
    ]


def test_parse_openai_blog_article_extracts_title_and_published_at() -> None:
    content = read_fixture("openai_blog_article.html")

    assert parse_openai_blog_article_title(content) == "Designing delightful frontends with GPT-5.4"
    assert parse_openai_blog_article_published_at(content) == datetime(2026, 3, 20, 0, 0, tzinfo=UTC)


def test_parse_claude_blog_listing_extracts_unique_article_links_in_order() -> None:
    candidates = parse_claude_blog_listing(read_fixture("claude_blog_listing.html"))

    assert [candidate.url for candidate in candidates] == [
        "https://claude.com/blog/claude-builds-visuals",
        "https://claude.com/blog/how-enterprises-are-building-ai-agents-in-2026",
        "https://claude.com/blog/improving-frontend-design-through-skills",
    ]
    assert [candidate.fallback_title for candidate in candidates] == [
        "Claude now creates interactive charts, diagrams and visualizations",
        "How enterprises are building AI agents in 2026",
        "Improving frontend design through Skills",
    ]
    assert [candidate.fallback_published_at for candidate in candidates] == [
        datetime(2026, 3, 12, 0, 0, tzinfo=UTC),
        datetime(2025, 12, 9, 0, 0, tzinfo=UTC),
        datetime(2025, 11, 12, 0, 0, tzinfo=UTC),
    ]


def test_parse_claude_blog_article_extracts_visible_title_and_published_at() -> None:
    content = read_fixture("claude_blog_article.html")

    assert parse_claude_blog_article_title(content) == "Claude now creates interactive charts, diagrams and visualizations"
    assert parse_claude_blog_article_published_at(content) == datetime(2026, 3, 12, 0, 0, tzinfo=UTC)


def test_parse_anthropic_listing_extracts_unique_article_links() -> None:
    candidates = parse_anthropic_listing(read_fixture("anthropic_newsroom.html"))

    assert [candidate.url for candidate in candidates[:4]] == [
        "https://www.anthropic.com/81k-interviews",
        "https://www.anthropic.com/news/introducing-claude-sonnet-4-6",
        "https://www.anthropic.com/news/claude-partner-network",
        "https://www.anthropic.com/news/sydney-fourth-office-asia-pacific",
    ]
    assert candidates[0].published_at is not None
    assert candidates[2].published_at is not None


def test_parse_anthropic_article_title_prefers_og_title() -> None:
    title = parse_anthropic_article_title(read_fixture("anthropic_article.html"))

    assert title == "Sydney will become Anthropic’s fourth office in Asia-Pacific"


def test_extract_title_from_listing_text_strips_category_and_excerpt() -> None:
    text = "Product Feb 17, 2026 Introducing Claude Sonnet 4.6 Sonnet 4.6 delivers frontier performance across coding."
    assert extract_title_from_listing_text(text) == "Introducing Claude Sonnet 4.6 Sonnet 4.6 delivers frontier performance across coding"


def test_extract_title_from_listing_text_prefers_title_before_date_for_featured_cards() -> None:
    text = "What 81,000 people want from AI Mar 18, 2026 We invited Claude.ai users to share how they use AI."
    assert extract_title_from_listing_text(text) == "What 81,000 people want from AI"


def test_parse_telegram_changelog_uses_latest_heading() -> None:
    item = parse_telegram_changelog(read_fixture("telegram_changelog.html"))

    assert item.source_key == "telegram_bot_api"
    assert item.title == "March 1, 2026 / Bot API 9.5"
    assert item.url == "https://core.telegram.org/bots/api-changelog#march-1-2026"
