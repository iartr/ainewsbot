from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from newsbot.entities import NormalizedNewsItem, StoredNewsItem
from newsbot.models import Delivery, NewsItem
from newsbot.service import NewsBotService
from newsbot.sources import build_sources
from newsbot.sources.base import NewsSource


def make_item(
    source_key: str,
    source_label: str,
    external_id: str,
    title: str,
    published_at: datetime | None,
) -> NormalizedNewsItem:
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


def make_stored_item(
    source_key: str,
    title: str,
    external_id: str,
    published_at: datetime | None,
    discovered_at: datetime,
) -> StoredNewsItem:
    return StoredNewsItem(
        id=1,
        source_key=source_key,
        title=title,
        url=f"https://example.com/{external_id}",
        published_at=published_at,
        discovered_at=discovered_at,
    )


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
async def test_bootstrap_seeds_new_source_archive_without_broadcasting_existing_subscribers(db_bundle) -> None:
    repository = db_bundle["repository"]
    await repository.insert_news_item(
        make_item("openai", "OpenAI", "existing", "Existing", datetime(2026, 3, 18, 10, 0, tzinfo=UTC))
    )
    await repository.upsert_subscriber(200, "private")

    source = StaticSource(
        "podcast_zapusk_zavtra",
        "Запуск завтра",
        [
            make_item(
                "podcast_zapusk_zavtra",
                "Запуск завтра",
                "episode-one",
                "Episode One",
                datetime(2026, 3, 19, 10, 0, tzinfo=UTC),
            ),
            make_item(
                "podcast_zapusk_zavtra",
                "Запуск завтра",
                "episode-two",
                "Episode Two",
                datetime(2026, 3, 19, 11, 0, tzinfo=UTC),
            ),
        ],
    )
    service = NewsBotService(repository, [source], request_timeout_seconds=5, latest_on_start_count=3)
    bot = FakeBot()

    try:
        changed = await service.bootstrap()
        sent = await service.broadcast_new_items(bot)
        latest = await repository.latest_news(10)
    finally:
        await service.aclose()

    assert changed is True
    assert sent == 0
    assert bot.messages == []
    assert [item.title for item in latest] == ["Episode Two", "Episode One", "Existing"]


@pytest.mark.asyncio
async def test_poll_after_source_bootstrap_broadcasts_only_new_episode(db_bundle) -> None:
    repository = db_bundle["repository"]
    await repository.upsert_subscriber(1, "private")

    source = StaticSource(
        "podcast_konkurenty",
        "Конкуренты",
        [
            make_item(
                "podcast_konkurenty",
                "Конкуренты",
                "episode-one",
                "Episode One",
                datetime(2026, 3, 19, 10, 0, tzinfo=UTC),
            )
        ],
    )
    service = NewsBotService(repository, [source], request_timeout_seconds=5, latest_on_start_count=3)
    bot = FakeBot()

    try:
        changed = await service.bootstrap()
        source._items = [
            make_item(
                "podcast_konkurenty",
                "Конкуренты",
                "episode-two",
                "Episode Two",
                datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
            ),
            make_item(
                "podcast_konkurenty",
                "Конкуренты",
                "episode-one",
                "Episode One",
                datetime(2026, 3, 19, 10, 0, tzinfo=UTC),
            ),
        ]
        sent = await service.broadcast_new_items(bot)
        latest = await repository.latest_news(10)
    finally:
        await service.aclose()

    assert changed is True
    assert sent == 1
    assert bot.messages == [(1, "Конкуренты\n20.03.2026\nEpisode Two\nhttps://example.com/episode-two")]
    assert [item.title for item in latest] == ["Episode Two", "Episode One"]


def test_build_sources_includes_podcasts_in_order() -> None:
    sources = build_sources()

    assert [(source.key, source.label) for source in sources] == [
        ("openai", "OpenAI"),
        ("openai_blog", "OpenAI Blog"),
        ("anthropic", "Anthropic Newsroom"),
        ("claude_blog", "Claude Blog"),
        ("telegram_bot_api", "Telegram Bot API"),
        ("podcast_zapusk_zavtra", "Запуск завтра"),
        ("podcast_konkurenty", "Конкуренты"),
        ("podcast_pochemu_my_eshche_zhivy", "Почему мы еще живы"),
    ]


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
    assert bot.messages[0][1] == "OpenAI\n20.03.2026\nOne title\nhttps://example.com/same-item"
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
            StaticSource("openai_blog", "OpenAI Blog"),
            StaticSource("anthropic", "Anthropic Newsroom"),
            StaticSource("claude_blog", "Claude Blog"),
            StaticSource("telegram_bot_api", "Telegram Bot API"),
            StaticSource("podcast_zapusk_zavtra", "Запуск завтра"),
            StaticSource("podcast_konkurenty", "Конкуренты"),
            StaticSource("podcast_pochemu_my_eshche_zhivy", "Почему мы еще живы"),
        ],
        request_timeout_seconds=5,
        latest_on_start_count=3,
    )
    try:
        now = datetime(2026, 3, 20, 14, 0, tzinfo=UTC)
        for index in range(4):
            await repository.insert_news_item(
                make_item("openai", "OpenAI", f"openai-{index}", f"OpenAI {index}", now - timedelta(minutes=index))
            )
        for index in range(2):
            await repository.insert_news_item(
                make_item(
                    "openai_blog",
                    "OpenAI Blog",
                    f"openai-blog-{index}",
                    f"OpenAI Blog {index}",
                    now - timedelta(minutes=index + 10),
                )
            )
        for index in range(2):
            await repository.insert_news_item(
                make_item(
                    "anthropic",
                    "Anthropic Newsroom",
                    f"anthropic-{index}",
                    f"Anthropic {index}",
                    now - timedelta(hours=index + 2),
                )
            )
        for index in range(2):
            await repository.insert_news_item(
                make_item(
                    "claude_blog",
                    "Claude Blog",
                    f"claude-blog-{index}",
                    f"Claude Blog {index}",
                    now - timedelta(hours=index + 1),
                )
            )
        await repository.insert_news_item(
            make_item("telegram_bot_api", "Telegram Bot API", "telegram-0", "Telegram 0", now - timedelta(days=1))
        )
        await repository.insert_news_item(
            make_item(
                "podcast_zapusk_zavtra",
                "Запуск завтра",
                "zapusk-0",
                "Запуск 0",
                now - timedelta(days=2),
            )
        )
        await repository.insert_news_item(
            make_item(
                "podcast_konkurenty",
                "Конкуренты",
                "konkurenty-0",
                "Конкуренты 0",
                now - timedelta(days=3),
            )
        )
        await repository.insert_news_item(
            make_item(
                "podcast_pochemu_my_eshche_zhivy",
                "Почему мы еще живы",
                "zhivy-0",
                "Живы 0",
                now - timedelta(days=4),
            )
        )

        latest = await service.latest_news(limit=3)
        grouped = await service.latest_news_per_source(limit_per_source=3)
        labels = service.source_labels()
    finally:
        await service.aclose()

    assert [item.title for item in latest] == ["OpenAI 0", "OpenAI 1", "OpenAI 2"]
    assert [source_label for source_label, _ in grouped] == [
        "OpenAI",
        "OpenAI Blog",
        "Anthropic Newsroom",
        "Claude Blog",
        "Telegram Bot API",
        "Запуск завтра",
        "Конкуренты",
        "Почему мы еще живы",
    ]
    assert [item.title for item in grouped[0][1]] == ["OpenAI 0", "OpenAI 1", "OpenAI 2"]
    assert [item.title for item in grouped[1][1]] == ["OpenAI Blog 0", "OpenAI Blog 1"]
    assert [item.title for item in grouped[2][1]] == ["Anthropic 0", "Anthropic 1"]
    assert [item.title for item in grouped[3][1]] == ["Claude Blog 0", "Claude Blog 1"]
    assert [item.title for item in grouped[4][1]] == ["Telegram 0"]
    assert [item.title for item in grouped[5][1]] == ["Запуск 0"]
    assert [item.title for item in grouped[6][1]] == ["Конкуренты 0"]
    assert [item.title for item in grouped[7][1]] == ["Живы 0"]
    assert labels == [
        "OpenAI",
        "OpenAI Blog",
        "Anthropic Newsroom",
        "Claude Blog",
        "Telegram Bot API",
        "Запуск завтра",
        "Конкуренты",
        "Почему мы еще живы",
    ]


def test_format_news_item_includes_date_when_available() -> None:
    service = NewsBotService(object(), [], request_timeout_seconds=5, latest_on_start_count=3)

    item = make_item(
        "openai",
        "OpenAI",
        "dated-item",
        "Dated title",
        datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
    )

    try:
        formatted = service.format_news_item(item)
    finally:
        asyncio.run(service.aclose())

    assert formatted == "OpenAI\n20.03.2026\nDated title\nhttps://example.com/dated-item"


def test_format_news_item_omits_date_when_missing() -> None:
    service = NewsBotService(object(), [], request_timeout_seconds=5, latest_on_start_count=3)

    item = make_item(
        "openai",
        "OpenAI",
        "undated-item",
        "Undated title",
        None,
    )

    try:
        formatted = service.format_news_item(item)
    finally:
        asyncio.run(service.aclose())

    assert formatted == "OpenAI\nUndated title\nhttps://example.com/undated-item"


def test_format_latest_news_item_includes_date_and_omits_source() -> None:
    service = NewsBotService(object(), [], request_timeout_seconds=5, latest_on_start_count=3)

    item = make_stored_item(
        "openai",
        "Latest title",
        "latest-item",
        datetime(2026, 3, 20, 10, 0, tzinfo=UTC),
        datetime(2026, 3, 20, 10, 5, tzinfo=UTC),
    )

    try:
        formatted = service.format_latest_news_item(item)
    finally:
        asyncio.run(service.aclose())

    assert formatted == "20.03.2026\nLatest title\nhttps://example.com/latest-item"


def test_format_latest_news_item_omits_date_when_missing() -> None:
    service = NewsBotService(object(), [], request_timeout_seconds=5, latest_on_start_count=3)

    item = make_stored_item(
        "openai",
        "Latest without date",
        "latest-item-no-date",
        None,
        datetime(2026, 3, 20, 10, 5, tzinfo=UTC),
    )

    try:
        formatted = service.format_latest_news_item(item)
    finally:
        asyncio.run(service.aclose())

    assert formatted == "Latest without date\nhttps://example.com/latest-item-no-date"
