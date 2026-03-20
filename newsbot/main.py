from __future__ import annotations

from newsbot.bot import create_application
from newsbot.config import Settings
from newsbot.db import create_session_factory
from newsbot.logging_config import configure_logging
from newsbot.repository import Repository
from newsbot.service import NewsBotService
from newsbot.sources import build_sources


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    engine, session_factory = create_session_factory(settings.database_url)
    repository = Repository(session_factory)
    service = NewsBotService(
        repository=repository,
        sources=build_sources(),
        request_timeout_seconds=settings.request_timeout_seconds,
        latest_on_start_count=settings.latest_on_start_count,
    )

    application = create_application(settings, service, engine)
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
