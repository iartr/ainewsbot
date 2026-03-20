from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from newsbot.entities import NormalizedNewsItem
from newsbot.models import Delivery, NewsItem
from newsbot.service import NewsBotService
from newsbot.sources.base import NewsSource


def make_item(source_key: str, source_label: str, external_id: str, title: str, published_at: datetime) -> NormalizedNewsItem:
    return NormalizedNewsItem(
        source_key=source_key,
        source_label=source_label,
        external_id=external_id,
        title=title,
        url=f"https://example.com/{external_id}",
        published_at=published_at,
    )


class StaticSource(NewsSource):
    def __init__(self, key: str, label: str, items=None, error: Exception | None = None):
        self.key = key
        self.label = label
        self._items = list(items or [])
        self._error = error

    async def fetch(self, client):
        if self._error is not None:
            raise self._error
        return list(self._items)


class FakeBot:
    def __init__(self, fail_chat_ids=None):
        self.fail_chat_ids = set(fail_chat_ids or [])
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, disable_web_page_preview: bool = True) -> None:
        if chat_id in self.fail_chat_ids:
            raise RuntimeError(f"send failure for {chat_id}")
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_bootstrap_seeds_empty_database_without_broadcast(db_bundle) -> None:
    repository = db_bundle["repository"]
    source = StaticSource(
        "openai",
        "OpenAI",
        [
            make_item("openai", "OpenAI", "one", "First", datetime(2026, 3, 19, 10, 0, tzinfo=UTC)),
            make_item("openai", "OpenAI", "two", "Second", datetime(2026, 3, 19, 11, 0, tzinfo=UTC)),
        ],
    )
    service = NewsBotService(repository, [source], request_timeout_seconds=5, latest_on_start_count=3)

    try:
        changed = await service.bootstrap()
        latest = await repository.latest_news(10)
    finally:
        await service.aclose()

    assert changed is True
    assert [item.title for item in latest] == ["Second", "First"]


@pytest.mark.asyncio
async def test_start_subscription_returns_latest_three_only_once(db_bundle) -> None:
    repository = db_bundle["repository"]
    now = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
    for index in range(5):
        await repository.insert_news_item(
            make_item(
                "openai",
                "OpenAI",
                f"item-{index}",
                f"Item {index}",
                now - timedelta(minutes=index),
            )
        )

    service = NewsBotService(repository, [], request_timeout_seconds=5, latest_on_start_count=3)
    try:
        status, backlog = await service.subscribe_chat(101, "private")
        status_repeat, backlog_repeat = await service.subscribe_chat(101, "private")
        await service.unsubscribe_chat(101)
        status_reactivated, backlog_reactivated = await service.subscribe_chat(101, "private")
    finally:
        await service.aclose()

    assert status == "created"
    assert [item.title for item in backlog] == ["Item 0", "Item 1", "Item 2"]
    assert status_repeat == "unchanged"
    assert backlog_repeat == []
    assert status_reactivated == "reactivated"
    assert backlog_reactivated == []


@pytest.mark.asyncio
async def test_poll_and_broadcast_is_deduplicated(db_bundle) -> None:
    repository = db_bundle["repository"]
    await repository.upsert_subscriber(200, "private")

    source = StaticSource(
        "openai",
        "OpenAI",
        [make_item("openai", "OpenAI", "same-item", "One title", datetime(2026, 3, 20, 10, 0, tzinfo=UTC))],
    )
    service = NewsBotService(repository, [source], request_timeout_seconds=5, latest_on_start_count=3)
    bot = FakeBot()

    try:
        sent_first = await service.broadcast_new_items(bot)
        sent_second = await service.broadcast_new_items(bot)
        latest = await repository.latest_news(10)
    finally:
        await service.aclose()

    assert sent_first == 1
    assert sent_second == 0
    assert len(bot.messages) == 1
    assert len(latest) == 1


@pytest.mark.asyncio
async def test_delivery_failures_are_recorded_without_blocking_other_chats(db_bundle) -> None:
    repository = db_bundle["repository"]
    session_factory = db_bundle["session_factory"]

    await repository.upsert_subscriber(1, "private")
    await repository.upsert_subscriber(2, "private")

    source = StaticSource(
        "telegram_bot_api",
        "Telegram Bot API",
        [make_item("telegram_bot_api", "Telegram Bot API", "bot-api-9.5", "March 1, 2026 / Bot API 9.5", datetime(2026, 3, 1, 0, 0, tzinfo=UTC))],
    )
    bad_source = StaticSource("broken", "Broken Source", error=RuntimeError("upstream unavailable"))
    service = NewsBotService(repository, [bad_source, source], request_timeout_seconds=5, latest_on_start_count=3)
    bot = FakeBot(fail_chat_ids={2})

    try:
        sent = await service.broadcast_new_items(bot)
        async with session_factory() as session:
            deliveries = list((await session.scalars(select(Delivery).order_by(Delivery.chat_id.asc()))).all())
            news_items = list((await session.scalars(select(NewsItem))).all())
    finally:
        await service.aclose()

    assert sent == 1
    assert len(bot.messages) == 1
    assert bot.messages[0][0] == 1
    assert len(news_items) == 1
    assert len(deliveries) == 2
    assert deliveries[0].chat_id == 1 and deliveries[0].sent_at is not None and deliveries[0].error_text is None
    assert deliveries[1].chat_id == 2 and deliveries[1].sent_at is None
    assert "send failure" in (deliveries[1].error_text or "")


@pytest.mark.asyncio
async def test_latest_and_sources_views_are_available(db_bundle) -> None:
    repository = db_bundle["repository"]
    service = NewsBotService(
        repository,
        [
            StaticSource("openai", "OpenAI"),
            StaticSource("anthropic", "Anthropic Newsroom"),
            StaticSource("telegram_bot_api", "Telegram Bot API"),
        ],
        request_timeout_seconds=5,
        latest_on_start_count=3,
    )
    try:
        await repository.insert_news_item(
            make_item("openai", "OpenAI", "recent", "Recent item", datetime(2026, 3, 20, 14, 0, tzinfo=UTC))
        )
        latest = await service.latest_news(limit=3)
        labels = service.source_labels()
    finally:
        await service.aclose()

    assert [item.title for item in latest] == ["Recent item"]
    assert labels == ["OpenAI", "Anthropic Newsroom", "Telegram Bot API"]
