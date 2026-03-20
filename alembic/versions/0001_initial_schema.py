"""Initial schema for Telegram news bot."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", "external_id", name="uq_news_items_source_external"),
    )
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"], unique=False)
    op.create_index("ix_news_items_discovered_at", "news_items", ["discovered_at"], unique=False)

    op.create_table(
        "subscribers",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_type", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscribers_is_active", "subscribers", ["is_active"], unique=False)

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("news_item_id", sa.Integer(), sa.ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), sa.ForeignKey("subscribers.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.UniqueConstraint("news_item_id", "chat_id", name="uq_deliveries_news_chat"),
    )


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_index("ix_subscribers_is_active", table_name="subscribers")
    op.drop_table("subscribers")
    op.drop_index("ix_news_items_discovered_at", table_name="news_items")
    op.drop_index("ix_news_items_published_at", table_name="news_items")
    op.drop_table("news_items")

