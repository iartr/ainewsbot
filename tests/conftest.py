from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from newsbot.db import create_engine, create_schema
from newsbot.repository import Repository


@pytest_asyncio.fixture
async def db_bundle(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database_url)
    await create_schema(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = Repository(session_factory)

    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
            "repository": repository,
        }
    finally:
        await engine.dispose()

