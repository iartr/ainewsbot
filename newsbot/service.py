from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from newsbot.entities import NormalizedNewsItem, StoredNewsItem
from newsbot.repository import Repository, SubscriptionStatus
from newsbot.sources.base import NewsSource

LOGGER = logging.getLogger(__name__)


class NewsBotService:
    def __init__(
        self,
        repository: Repository,
        sources: Iterable[NewsSource],
        request_timeout_seconds: int,
        latest_on_start_count: int,
    ):
        self._repository = repository
        self._sources = list(sources)
        self._source_labels = {source.key: source.label for source in self._sources}
        self._latest_on_start_count = latest_on_start_count
        self._http_client = httpx.AsyncClient(
            timeout=request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "newsbot/1.0"},
        )

    async def aclose(self) -> None:
        await self._http_client.aclose()

    def source_labels(self) -> list[str]:
        return [source.label for source in self._sources]

    def format_news_item(self, item: StoredNewsItem | NormalizedNewsItem) -> str:
        source_label = getattr(item, "source_label", self._source_labels.get(item.source_key, item.source_key))
        return f"{source_label}\n{item.title}\n{item.url}"

    async def bootstrap(self) -> bool:
        if await self._repository.count_news_items() > 0:
            return False

        LOGGER.info("News database is empty, seeding current items without broadcasting")
        for source in self._sources:
            try:
                items = await source.fetch(self._http_client)
            except Exception:
                LOGGER.exception("Bootstrap fetch failed for source %s", source.key)
                continue

            for item in items:
                await self._repository.insert_news_item(item)
        return True

    async def subscribe_chat(self, chat_id: int, chat_type: str) -> tuple[SubscriptionStatus, list[StoredNewsItem]]:
        status = await self._repository.upsert_subscriber(chat_id, chat_type)
        latest_items = await self._repository.latest_news(self._latest_on_start_count) if status == "created" else []
        return status, latest_items

    async def unsubscribe_chat(self, chat_id: int) -> bool:
        return await self._repository.deactivate_subscriber(chat_id)

    async def latest_news(self, limit: int = 3) -> list[StoredNewsItem]:
        return await self._repository.latest_news(limit)

    async def poll_sources(self) -> list[StoredNewsItem]:
        discovered: list[StoredNewsItem] = []
        for source in self._sources:
            try:
                items = await source.fetch(self._http_client)
            except Exception:
                LOGGER.exception("Source fetch failed for %s", source.key)
                continue

            for item in items:
                created = await self._repository.insert_news_item(item)
                if created is not None:
                    LOGGER.info("Discovered new item from %s: %s", source.key, item.title)
                    discovered.append(created)

        discovered.sort(
            key=lambda item: (item.published_at or item.discovered_at, item.discovered_at),
            reverse=True,
        )
        return discovered

    async def broadcast_new_items(self, bot) -> int:
        new_items = await self.poll_sources()
        if not new_items:
            return 0

        subscribers = await self._repository.active_subscribers()
        deliveries_sent = 0
        for item in new_items:
            text = self.format_news_item(item)
            for subscriber in subscribers:
                delivery_id = await self._repository.create_delivery(item.id, subscriber.chat_id)
                if delivery_id is None:
                    continue

                try:
                    await bot.send_message(
                        chat_id=subscriber.chat_id,
                        text=text,
                        disable_web_page_preview=True,
                    )
                except Exception as exc:
                    LOGGER.warning("Failed to deliver item %s to chat %s: %s", item.id, subscriber.chat_id, exc)
                    await self._repository.mark_delivery_failed(delivery_id, str(exc))
                    continue

                await self._repository.mark_delivery_sent(delivery_id)
                deliveries_sent += 1

        return deliveries_sent

