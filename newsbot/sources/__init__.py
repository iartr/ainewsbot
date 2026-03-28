from __future__ import annotations

from newsbot.sources.anthropic import AnthropicNewsSource
from newsbot.sources.claude_blog import ClaudeBlogSource
from newsbot.sources.openai import OpenAINewsSource
from newsbot.sources.openai_blog import OpenAIBlogSource
from newsbot.sources.rss import RssFeedSource
from newsbot.sources.telegram_api import TelegramBotApiSource

PODCAST_FEEDS = (
    (
        "podcast_zapusk_zavtra",
        "Запуск завтра",
        "https://feeds.transistor.fm/5f1e0bb2-458b-4ac4-8d85-f464a505f813",
    ),
    (
        "podcast_konkurenty",
        "Конкуренты",
        "https://feeds.transistor.fm/f06f5c52-b4c8-48be-8dff-7b8e529c5bdc",
    ),
    (
        "podcast_pochemu_my_eshche_zhivy",
        "Почему мы еще живы",
        "https://feeds.transistor.fm/e096750c-c57f-489d-8aee-e55a1e835d6e",
    ),
)


def build_sources() -> list:
    sources = [
        OpenAINewsSource(),
        OpenAIBlogSource(),
        AnthropicNewsSource(),
        ClaudeBlogSource(),
        TelegramBotApiSource(),
    ]
    sources.extend(RssFeedSource(key=key, label=label, feed_url=feed_url) for key, label, feed_url in PODCAST_FEEDS)
    return sources
