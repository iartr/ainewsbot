from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from newsbot.entities import NormalizedNewsItem, StoredNewsItem, SubscriberRecord, utcnow
from newsbot.models import Delivery, NewsItem, Subscriber

SubscriptionStatus = Literal["created", "reactivated", "unchanged"]


def _stored_news_item(model: NewsItem) -> StoredNewsItem:
    return StoredNewsItem(
        id=model.id,
        source_key=model.source_key,
        title=model.title,
        url=model.url,
        published_at=model.published_at,
        discovered_at=model.discovered_at,
    )


def _unique_news_items(items: Sequence[NormalizedNewsItem]) -> list[NormalizedNewsItem]:
    unique_items: list[NormalizedNewsItem] = []
    seen_keys: set[tuple[str, str]] = set()

    for item in items:
        dedup_key = (item.source_key, item.external_id)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        unique_items.append(item)

    return unique_items


class Repository:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def count_news_items(self) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(select(func.count()).select_from(NewsItem))
            return int(value or 0)

    async def has_news_items_for_source(self, source_key: str) -> bool:
        async with self._session_factory() as session:
            return await session.scalar(select(NewsItem.id).where(NewsItem.source_key == source_key).limit(1)) is not None

    async def insert_news_item(self, item: NormalizedNewsItem) -> StoredNewsItem | None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(NewsItem).where(
                    NewsItem.source_key == item.source_key,
                    NewsItem.external_id == item.external_id,
                )
            )
            if existing is not None:
                return None

            news_item = NewsItem(
                source_key=item.source_key,
                external_id=item.external_id,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                discovered_at=item.discovered_at,
            )
            session.add(news_item)
            await session.commit()
            await session.refresh(news_item)
            return _stored_news_item(news_item)

    async def insert_news_items(self, items: Sequence[NormalizedNewsItem]) -> list[StoredNewsItem]:
        unique_items = _unique_news_items(items)
        if not unique_items:
            return []

        source_items: dict[str, list[NormalizedNewsItem]] = {}
        for item in unique_items:
            source_items.setdefault(item.source_key, []).append(item)

        async with self._session_factory() as session:
            existing_keys: set[tuple[str, str]] = set()
            for source_key, group_items in source_items.items():
                external_ids = [item.external_id for item in group_items]
                existing_external_ids = (
                    await session.scalars(
                        select(NewsItem.external_id).where(
                            NewsItem.source_key == source_key,
                            NewsItem.external_id.in_(external_ids),
                        )
                    )
                ).all()
                existing_keys.update((source_key, external_id) for external_id in existing_external_ids)

            models: list[NewsItem] = []
            for item in unique_items:
                if (item.source_key, item.external_id) in existing_keys:
                    continue
                models.append(
                    NewsItem(
                        source_key=item.source_key,
                        external_id=item.external_id,
                        title=item.title,
                        url=item.url,
                        published_at=item.published_at,
                        discovered_at=item.discovered_at,
                    )
                )

            if not models:
                return []

            session.add_all(models)
            await session.flush()
            stored_items = [_stored_news_item(model) for model in models]
            await session.commit()
            return stored_items

    async def latest_news(self, limit: int) -> list[StoredNewsItem]:
        order_query: Select[tuple[NewsItem]] = (
            select(NewsItem)
            .order_by(NewsItem.published_at.desc().nullslast(), NewsItem.discovered_at.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            models = (await session.scalars(order_query)).all()
        return [_stored_news_item(model) for model in models]

    async def latest_news_per_source(self, limit_per_source: int) -> list[StoredNewsItem]:
        ranked_news = (
            select(
                NewsItem.id.label("id"),
                func.row_number()
                .over(
                    partition_by=NewsItem.source_key,
                    order_by=(NewsItem.published_at.desc().nullslast(), NewsItem.discovered_at.desc()),
                )
                .label("source_rank"),
            )
            .subquery()
        )

        query: Select[tuple[NewsItem]] = (
            select(NewsItem)
            .join(ranked_news, ranked_news.c.id == NewsItem.id)
            .where(ranked_news.c.source_rank <= limit_per_source)
            .order_by(
                NewsItem.source_key.asc(),
                NewsItem.published_at.desc().nullslast(),
                NewsItem.discovered_at.desc(),
            )
        )

        async with self._session_factory() as session:
            models = (await session.scalars(query)).all()
        return [_stored_news_item(model) for model in models]

    async def upsert_subscriber(self, chat_id: int, chat_type: str) -> SubscriptionStatus:
        async with self._session_factory() as session:
            subscriber = await session.get(Subscriber, chat_id)
            if subscriber is None:
                session.add(Subscriber(chat_id=chat_id, chat_type=chat_type, is_active=True))
                await session.commit()
                return "created"

            subscriber.chat_type = chat_type
            subscriber.updated_at = utcnow()
            if not subscriber.is_active:
                subscriber.is_active = True
                await session.commit()
                return "reactivated"

            await session.commit()
            return "unchanged"

    async def deactivate_subscriber(self, chat_id: int) -> bool:
        async with self._session_factory() as session:
            subscriber = await session.get(Subscriber, chat_id)
            if subscriber is None or not subscriber.is_active:
                return False

            subscriber.is_active = False
            subscriber.updated_at = utcnow()
            await session.commit()
            return True

    async def active_subscribers(self) -> list[SubscriberRecord]:
        async with self._session_factory() as session:
            subscribers = (
                await session.scalars(select(Subscriber).where(Subscriber.is_active.is_(True)).order_by(Subscriber.chat_id))
            ).all()
        return [SubscriberRecord(chat_id=item.chat_id, chat_type=item.chat_type) for item in subscribers]

    async def create_delivery(self, news_item_id: int, chat_id: int) -> int | None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Delivery).where(Delivery.news_item_id == news_item_id, Delivery.chat_id == chat_id)
            )
            if existing is not None:
                return None

            delivery = Delivery(news_item_id=news_item_id, chat_id=chat_id)
            session.add(delivery)
            await session.commit()
            await session.refresh(delivery)
            return delivery.id

    async def mark_delivery_sent(self, delivery_id: int) -> None:
        async with self._session_factory() as session:
            delivery = await session.get(Delivery, delivery_id)
            if delivery is None:
                return
            delivery.sent_at = utcnow()
            delivery.error_text = None
            await session.commit()

    async def mark_delivery_failed(self, delivery_id: int, error_text: str) -> None:
        async with self._session_factory() as session:
            delivery = await session.get(Delivery, delivery_id)
            if delivery is None:
                return
            delivery.error_text = error_text[:2000]
            await session.commit()

    async def deliveries_for_chat(self, chat_id: int) -> Sequence[Delivery]:
        async with self._session_factory() as session:
            return tuple(
                (
                    await session.scalars(
                        select(Delivery)
                        .where(Delivery.chat_id == chat_id)
                        .order_by(Delivery.news_item_id.asc(), Delivery.id.asc())
                    )
                ).all()
            )
