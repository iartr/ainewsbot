from __future__ import annotations

import logging

import httpx

LOGGER = logging.getLogger(__name__)

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
CLASSIFIER_MAX_TOKENS = 16
SYSTEM_PROMPT = (
    "You classify AI news headlines. Reply with a single word: 'yes' or 'no'. "
    "Answer 'yes' only when the headline announces the release or public launch of a "
    "NEW AI model or a major new version of a model by an AI lab (for example a new "
    "GPT, Claude, Gemini, Llama, or Kimi model). Answer 'no' for features, product "
    "updates, pricing, partnerships, research papers, benchmarks, safety posts, "
    "hiring, or minor point updates."
)


def _is_affirmative(answer: str | None) -> bool:
    if not answer:
        return False
    return answer.strip().lower().startswith("yes")


class ModelReleaseClassifier:
    """Decides whether a news headline announces a brand-new model release.

    Backed by a cheap OpenAI chat model. Designed to fail safe: if the feature is
    disabled (no API key) or the call errors in any way, it returns ``False`` so the
    item flows into the daily digest instead of being sent immediately.
    """

    def __init__(self, *, api_key: str | None, model: str, client: httpx.AsyncClient):
        self._api_key = api_key or None
        self._model = model
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._api_key is not None

    async def is_model_release(self, *, title: str, source_label: str) -> bool:
        if self._api_key is None:
            return False

        user_prompt = (
            f"Source: {source_label}\n"
            f"Headline: {title}\n"
            "Does this announce a new AI model release?"
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": CLASSIFIER_MAX_TOKENS,
        }

        try:
            response = await self._client.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"]
        except Exception as exc:
            LOGGER.warning("Model-release classification failed for %r: %s", title, exc)
            return False

        is_release = _is_affirmative(answer)
        LOGGER.info("Classified %r as model_release=%s", title, is_release)
        return is_release
