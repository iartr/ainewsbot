# Telegram News Bot

Telegram bot that watches OpenAI News RSS, OpenAI Blog, Anthropic Newsroom, Claude Blog, the Telegram Bot API changelog, and selected Apple Podcasts feeds, stores discovered items in Postgres, and broadcasts only new items to subscribed chats.

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
- `OPENAI_API_KEY` - optional. Enables instant alerts for brand-new model releases; without it every non-podcast item waits for the daily digest.
- `OPENAI_CLASSIFIER_MODEL` - cheap OpenAI model used to classify headlines, defaults to `gpt-5.4-nano`.
- `DIGEST_HOUR` / `DIGEST_MINUTE` - daily digest time, defaults to `19:00`.
- `DIGEST_TIMEZONE` - IANA timezone for the digest, defaults to `Europe/Moscow`.

## Delivery Behavior

- **Podcasts** are delivered immediately as they appear.
- **New model releases** (OpenAI, Anthropic, Moonshot/Kimi, …) are detected by the LLM classifier and delivered immediately.
- **All other lab news** is collected into a single **daily digest** sent at `DIGEST_HOUR` (one line per item, newest first). If the classifier is disabled or fails, items simply flow into the digest.

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
