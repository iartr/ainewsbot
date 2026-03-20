from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from newsbot.models import Base

ROOT_DIR = Path(__file__).resolve().parent.parent


def to_sync_database_url(database_url: str) -> str:
    return (
        database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        .replace("sqlite+aiosqlite://", "sqlite://")
    )


def create_engine(database_url: str) -> AsyncEngine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite+aiosqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    return create_async_engine(database_url, **kwargs)


def create_session_factory(database_url: str) -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_engine(database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def build_alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", to_sync_database_url(database_url))
    return config


def run_migrations(database_url: str) -> None:
    command.upgrade(build_alembic_config(database_url), "head")

