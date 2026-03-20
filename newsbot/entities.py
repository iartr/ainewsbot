from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class NormalizedNewsItem:
    source_key: str
    source_label: str
    external_id: str
    title: str
    url: str
    published_at: datetime | None
    discovered_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class StoredNewsItem:
    id: int
    source_key: str
    title: str
    url: str
    published_at: datetime | None
    discovered_at: datetime


@dataclass(frozen=True, slots=True)
class SubscriberRecord:
    chat_id: int
    chat_type: str

