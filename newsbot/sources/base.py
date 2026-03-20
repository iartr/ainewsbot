from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time

import httpx

from newsbot.entities import NormalizedNewsItem


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_email_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return ensure_utc(parsedate_to_datetime(value))
    except (TypeError, ValueError):
        return None


def parse_struct_time(value: struct_time | None) -> datetime | None:
    if value is None:
        return None
    return datetime(*value[:6], tzinfo=UTC)


class NewsSource(ABC):
    key: str
    label: str

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[NormalizedNewsItem]:
        raise NotImplementedError

