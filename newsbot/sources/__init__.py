from __future__ import annotations

from newsbot.sources.anthropic import AnthropicNewsSource
from newsbot.sources.apple_podcasts import ApplePodcastSource
from newsbot.sources.claude_blog import ClaudeBlogSource
from newsbot.sources.openai import OpenAINewsSource
from newsbot.sources.openai_blog import OpenAIBlogSource
from newsbot.sources.telegram_api import TelegramBotApiSource

APPLE_PODCASTS = (
    (
        "podcast_zapusk_zavtra",
        "Запуск завтра",
        "https://podcasts.apple.com/ru/podcast/%D0%B7%D0%B0%D0%BF%D1%83%D1%81%D0%BA-%D0%B7%D0%B0%D0%B2%D1%82%D1%80%D0%B0/id1488945593?l=en-GB",
        "1488945593",
        "https://feeds.transistor.fm/5f1e0bb2-458b-4ac4-8d85-f464a505f813",
    ),
    (
        "podcast_konkurenty",
        "Конкуренты",
        "https://podcasts.apple.com/us/podcast/%D0%BA%D0%BE%D0%BD%D0%BA%D1%83%D1%80%D0%B5%D0%BD%D1%82%D1%8B/id1657621781?l=en-GB",
        "1657621781",
        "https://feeds.transistor.fm/f06f5c52-b4c8-48be-8dff-7b8e529c5bdc",
    ),
    (
        "podcast_pochemu_my_eshche_zhivy",
        "Почему мы еще живы",
        "https://podcasts.apple.com/ru/podcast/%D0%BF%D0%BE%D1%87%D0%B5%D0%BC%D1%83-%D0%BC%D1%8B-%D0%B5%D1%89%D0%B5-%D0%B6%D0%B8%D0%B2%D1%8B/id1568720773?l=en-GB",
        "1568720773",
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
    sources.extend(
        ApplePodcastSource(
            key=key,
            label=label,
            page_url=page_url,
            lookup_id=lookup_id,
            feed_url=feed_url,
        )
        for key, label, page_url, lookup_id, feed_url in APPLE_PODCASTS
    )
    return sources
