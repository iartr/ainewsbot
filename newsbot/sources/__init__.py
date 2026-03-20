from __future__ import annotations

from newsbot.sources.anthropic import AnthropicNewsSource
from newsbot.sources.openai import OpenAINewsSource
from newsbot.sources.telegram_api import TelegramBotApiSource


def build_sources() -> list:
    return [
        OpenAINewsSource(),
        AnthropicNewsSource(),
        TelegramBotApiSource(),
    ]

