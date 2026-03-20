from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    database_url: str
    poll_interval_minutes: int = 15
    request_timeout_seconds: int = 20
    latest_on_start_count: int = 3
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        database_url = os.getenv("DATABASE_URL")

        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", telegram_bot_token),
                ("DATABASE_URL", database_url),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variables: {joined}")

        return cls(
            telegram_bot_token=telegram_bot_token,
            database_url=database_url,
            poll_interval_minutes=int(os.getenv("POLL_INTERVAL_MINUTES", "15")),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            latest_on_start_count=int(os.getenv("LATEST_ON_START_COUNT", "3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

