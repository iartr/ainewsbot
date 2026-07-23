"""Add digest queue flags to news_items."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_digest_flags"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_items",
        sa.Column("pending_digest", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "news_items",
        sa.Column("is_model_release", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_news_items_pending_digest", "news_items", ["pending_digest"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_news_items_pending_digest", table_name="news_items")
    op.drop_column("news_items", "is_model_release")
    op.drop_column("news_items", "pending_digest")
