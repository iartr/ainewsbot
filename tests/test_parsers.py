from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from newsbot.sources.anthropic import extract_title_from_listing_text, parse_anthropic_article_title, parse_anthropic_listing
from newsbot.sources.openai import parse_openai_rss
from newsbot.sources.openai_blog import (
    parse_openai_blog_article_published_at,
    parse_openai_blog_article_title,
    parse_openai_blog_listing,
)
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
