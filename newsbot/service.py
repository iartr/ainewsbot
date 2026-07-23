from __future__ import annotations

import html
import logging
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from datetime import datetime

import httpx

from newsbot.classifier import ModelReleaseClassifier
from newsbot.entities import NormalizedNewsItem, StoredNewsItem
from newsbot.repository import Repository, SubscriptionStatus
from newsbot.sources.base import NewsSource

LOGGER = logging.getLogger(__name__)
# Telegram hard-caps messages at 4096 chars; stay safely under it when chunking.
DIGEST_MAX_CHARS = 3800


class NewsBotService:
    def __init__(
        self,
        repository: Repository,
        sources: Iterable[NewsSource],
        request_timeout_seconds: int,
        latest_on_start_count: int,
        openai_api_key: str | None = None,
        classifier_model: str = "gpt-5.4-nano",
        classifier: ModelReleaseClassifier | None = None,
    ):
        self._repository = repository
        self._sources = list(sources)
        self._source_labels = {source.key: source.label for source in self._sources}
        self._immediate_source_keys = {
            source.key for source in self._sources if getattr(source, "broadcast_immediately", False)
        }
        self._latest_on_start_count = latest_on_start_count
        self._http_client = httpx.AsyncClient(
            timeout=request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "newsbot/1.0"},
        )
        self._classifier = classifier or ModelReleaseClassifier(
            api_key=openai_api_key,
            model=classifier_model,
            client=self._http_client,
        )

    async def aclose(self) -> None:
        await self._http_client.aclose()

    def source_labels(self) -> list[str]:
        return [source.label for source in self._sources]

    def _format_item_date(self, item: StoredNewsItem | NormalizedNewsItem) -> str | None:
        published_at = getattr(item, "published_at", None)
        if published_at is None:
            return None
        if not isinstance(published_at, datetime):
            return None
        return published_at.strftime("%d.%m.%Y")

    def format_news_item(self, item: StoredNewsItem | NormalizedNewsItem) -> str:
        source_label = getattr(item, "source_label", self._source_labels.get(item.source_key, item.source_key))
        parts = [source_label]
        formatted_date = self._format_item_date(item)
        if formatted_date is not None:
            parts.append(formatted_date)
        parts.extend([item.title, item.url])
        return "\n".join(parts)

    def format_latest_news_item(self, item: StoredNewsItem | NormalizedNewsItem) -> str:
        parts: list[str] = []
        formatted_date = self._format_item_date(item)
        if formatted_date is not None:
            parts.append(formatted_date)
        parts.extend([item.title, item.url])
        return "\n".join(parts)

    def format_digest_line(self, item: StoredNewsItem | NormalizedNewsItem) -> str:
        source_label = getattr(item, "source_label", self._source_labels.get(item.source_key, item.source_key))
        link = f'<a href="{html.escape(item.url, quote=True)}">{html.escape(item.title)}</a>'
        parts = [html.escape(source_label)]
        formatted_date = self._format_item_date(item)
        if formatted_date is not None:
            parts.append(formatted_date)
        parts.append(link)
        return " — ".join(parts)

    def build_digest_messages(self, items: Sequence[StoredNewsItem | NormalizedNewsItem]) -> list[str]:
        messages: list[str] = []
        current: list[str] = []
        current_len = 0
        for item in items:
            line = self.format_digest_line(item)
            extra = len(line) + (1 if current else 0)
            if current and current_len + extra > DIGEST_MAX_CHARS:
                messages.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += extra
        if current:
            messages.append("\n".join(current))
        return messages

    async def bootstrap(self) -> bool:
        seeded_any = False
        for source in self._sources:
            if await self._repository.has_news_items_for_source(source.key):
                continue

            LOGGER.info("Source %s has no stored items, seeding current items without broadcasting", source.key)
            try:
                items = await source.fetch(self._http_client)
            except Exception:
                LOGGER.exception("Bootstrap fetch failed for source %s", source.key)
                continue

            inserted_items = await self._repository.insert_news_items(items)
            seeded_any = seeded_any or bool(inserted_items)
        return seeded_any

    async def subscribe_chat(self, chat_id: int, chat_type: str) -> tuple[SubscriptionStatus, list[StoredNewsItem]]:
        status = await self._repository.upsert_subscriber(chat_id, chat_type)
        latest_items = await self._repository.latest_news(self._latest_on_start_count) if status == "created" else []
        return status, latest_items

    async def unsubscribe_chat(self, chat_id: int) -> bool:
        return await self._repository.deactivate_subscriber(chat_id)

    async def latest_news(self, limit: int = 3) -> list[StoredNewsItem]:
        return await self._repository.latest_news(limit)

    async def latest_news_per_source(self, limit_per_source: int = 3) -> list[tuple[str, list[StoredNewsItem]]]:
        items = await self._repository.latest_news_per_source(limit_per_source)
        grouped: OrderedDict[str, list[StoredNewsItem]] = OrderedDict((source.key, []) for source in self._sources)

        for item in items:
            grouped.setdefault(item.source_key, []).append(item)

        return [
            (self._source_labels.get(source_key, source_key), source_items)
            for source_key, source_items in grouped.items()
            if source_items
        ]

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

    async def _classify_new_items(self, new_items: list[StoredNewsItem]) -> list[StoredNewsItem]:
        """Split newly discovered items into an immediate-broadcast list.

        Podcast items always broadcast immediately. Other items are sent to the LLM
        classifier: model releases broadcast immediately, everything else is held
        for the daily digest.
        """
        immediate_items: list[StoredNewsItem] = []
        for item in new_items:
            if item.source_key in self._immediate_source_keys:
                immediate_items.append(item)
                continue

            is_release = await self._classifier.is_model_release(
                title=item.title,
                source_label=self._source_labels.get(item.source_key, item.source_key),
            )
            if is_release:
                await self._repository.mark_model_release(item.id)
                immediate_items.append(item)
            else:
                await self._repository.mark_pending_digest(item.id)

        return immediate_items

    async def broadcast_new_items(self, bot) -> int:
        new_items = await self.poll_sources()
        if not new_items:
            return 0

        immediate_items = await self._classify_new_items(new_items)
        if not immediate_items:
            return 0

        subscribers = await self._repository.active_subscribers()
        deliveries_sent = 0
        for item in immediate_items:
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

    async def send_daily_digest(self, bot) -> int:
        items = await self._repository.pending_digest_items()
        if not items:
            LOGGER.info("Daily digest: no pending items")
            return 0

        subscribers = await self._repository.active_subscribers()
        if not subscribers:
            # Keep the pending flags so a future subscriber still receives these items.
            LOGGER.info("Daily digest: %s pending items but no active subscribers", len(items))
            return 0

        messages = self.build_digest_messages(items)
        item_ids = [item.id for item in items]
        subscribers_delivered = 0

        for subscriber in subscribers:
            delivery_ids: list[int] = []
            for item_id in item_ids:
                delivery_id = await self._repository.create_delivery(item_id, subscriber.chat_id)
                if delivery_id is not None:
                    delivery_ids.append(delivery_id)

            error: str | None = None
            for text in messages:
                try:
                    await bot.send_message(
                        chat_id=subscriber.chat_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception as exc:
                    error = str(exc)
                    LOGGER.warning("Failed to deliver digest to chat %s: %s", subscriber.chat_id, exc)
                    break

            for delivery_id in delivery_ids:
                if error is None:
                    await self._repository.mark_delivery_sent(delivery_id)
                else:
                    await self._repository.mark_delivery_failed(delivery_id, error)

            if error is None:
                subscribers_delivered += 1

        await self._repository.clear_pending_digest(item_ids)
        LOGGER.info(
            "Daily digest: sent %s items to %s/%s chats",
            len(items),
            subscribers_delivered,
            len(subscribers),
        )
        return subscribers_delivered
