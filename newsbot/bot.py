from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from newsbot.config import Settings
from newsbot.db import run_migrations
from newsbot.service import NewsBotService

LOGGER = logging.getLogger(__name__)
SERVICE_KEY = "service"
ENGINE_KEY = "engine"
SETTINGS_KEY = "settings"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    service: NewsBotService = context.application.bot_data[SERVICE_KEY]
    status, latest_items = await service.subscribe_chat(update.effective_chat.id, update.effective_chat.type)

    if status == "created":
        await update.effective_message.reply_text("Подписка включена. Ниже 3 последние сохранённые новости.")
        if not latest_items:
            await update.effective_message.reply_text("Сохранённых новостей пока нет.")
            return
        for item in latest_items:
            await update.effective_message.reply_text(
                service.format_news_item(item),
                disable_web_page_preview=True,
            )
        return

    if status == "reactivated":
        await update.effective_message.reply_text("Подписка снова включена.")
        return

    await update.effective_message.reply_text("Этот чат уже подписан на новости.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    service: NewsBotService = context.application.bot_data[SERVICE_KEY]
    stopped = await service.unsubscribe_chat(update.effective_chat.id)
    if stopped:
        await update.effective_message.reply_text("Подписка отключена.")
    else:
        await update.effective_message.reply_text("Этот чат и так не подписан.")


async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    service: NewsBotService = context.application.bot_data[SERVICE_KEY]
    items = await service.latest_news(limit=3)
    if not items:
        await update.effective_message.reply_text("Сохранённых новостей пока нет.")
        return

    text = "\n\n".join(service.format_news_item(item) for item in items)
    await update.effective_message.reply_text(text, disable_web_page_preview=True)


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    service: NewsBotService = context.application.bot_data[SERVICE_KEY]
    sources = "\n".join(f"• {label}" for label in service.source_labels())
    await update.effective_message.reply_text(f"Активные источники:\n{sources}")


async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    service: NewsBotService = context.application.bot_data[SERVICE_KEY]
    sent = await service.broadcast_new_items(context.bot)
    LOGGER.info("Polling cycle finished, delivered %s notifications", sent)


async def post_init(application: Application) -> None:
    settings: Settings = application.bot_data[SETTINGS_KEY]
    service: NewsBotService = application.bot_data[SERVICE_KEY]

    await asyncio.to_thread(run_migrations, settings.database_url)
    await service.bootstrap()

    if application.job_queue is None:
        raise RuntimeError("python-telegram-bot JobQueue is not available")

    application.job_queue.run_repeating(
        poll_job,
        interval=settings.poll_interval_minutes * 60,
        first=5,
        name="news-poller",
    )
    LOGGER.info("Scheduled polling every %s minutes", settings.poll_interval_minutes)


async def post_shutdown(application: Application) -> None:
    service: NewsBotService = application.bot_data[SERVICE_KEY]
    engine = application.bot_data[ENGINE_KEY]
    await service.aclose()
    await engine.dispose()


def create_application(settings: Settings, service: NewsBotService, engine) -> Application:
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.bot_data[SERVICE_KEY] = service
    application.bot_data[SETTINGS_KEY] = settings
    application.bot_data[ENGINE_KEY] = engine

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("latest", latest_command))
    application.add_handler(CommandHandler("sources", sources_command))
    return application

