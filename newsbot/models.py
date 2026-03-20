from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from newsbot.entities import utcnow


class Base(DeclarativeBase):
    pass


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("source_key", "external_id", name="uq_news_items_source_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        index=True,
    )

    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="news_item", cascade="all, delete-orphan")


class Subscriber(Base):
    __tablename__ = "subscribers"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    deliveries: Mapped[list["Delivery"]] = relationship(back_populates="subscriber", cascade="all, delete-orphan")


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("news_item_id", "chat_id", name="uq_deliveries_news_chat"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False)
    chat_id: Mapped[int] = mapped_column(ForeignKey("subscribers.chat_id", ondelete="CASCADE"), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    news_item: Mapped[NewsItem] = relationship(back_populates="deliveries")
    subscriber: Mapped[Subscriber] = relationship(back_populates="deliveries")

