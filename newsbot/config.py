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
    openai_api_key: str | None = None
    classifier_model: str = "gpt-5.4-nano"
    digest_hour: int = 19
    digest_minute: int = 0
    digest_timezone: str = "Europe/Moscow"

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
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            classifier_model=os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-5.4-nano"),
            digest_hour=int(os.getenv("DIGEST_HOUR", "19")),
            digest_minute=int(os.getenv("DIGEST_MINUTE", "0")),
            digest_timezone=os.getenv("DIGEST_TIMEZONE", "Europe/Moscow"),
        )

