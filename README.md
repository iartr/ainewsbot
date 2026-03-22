# Telegram News Bot

Telegram bot that watches OpenAI News RSS, OpenAI Blog, Anthropic Newsroom, Claude Blog, and the Telegram Bot API changelog, stores discovered items in Postgres, and broadcasts only new items to subscribed chats.

## Features

- `/start` subscribes the current chat and sends the latest 3 stored news items on the first subscription.
- `/stop` disables future broadcasts for the current chat.
- `/sources` lists active sources.
- `/latest` returns the latest 3 stored items.
- First startup seeds current source items into the database without broadcasting them.
- Deduplicates persisted news items and per-chat deliveries.

## Runtime

- Python 3.12
- `python-telegram-bot` with long polling
- SQLAlchemy + Alembic
- Postgres on Railway

## Environment Variables

- `TELEGRAM_BOT_TOKEN` - Telegram bot token from BotFather.
- `DATABASE_URL` - async SQLAlchemy URL, for example `postgresql+asyncpg://...`.
- `POLL_INTERVAL_MINUTES` - source polling cadence, defaults to `15`.
- `REQUEST_TIMEOUT_SECONDS` - HTTP timeout per request, defaults to `20`.
- `LOG_LEVEL` - defaults to `INFO`.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m newsbot.main
```

The app applies Alembic migrations automatically on startup.

## Tests

```bash
source .venv/bin/activate
pytest
```

## Railway Notes

- Deploy this repository as a dedicated worker service.
- Add a Railway Postgres service and wire its `DATABASE_URL` into the worker.
- Set `TELEGRAM_BOT_TOKEN` before starting the worker.
- No public domain or webhook is required because the bot uses Telegram long polling.
