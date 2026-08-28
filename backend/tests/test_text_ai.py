"""Provider fallback for the text AI paths.

Gemini's free tier is 20 generate_content calls a day, shared across the coach,
insights and food logging, so it runs dry mid-day and those features stop. Groq
takes over — but only for failures that are the provider's fault. A malformed
request would fail identically on both, and retrying it would just double the
latency before showing the same error.
"""

import pytest

from app.config import settings
from app.errors import AppError, ConfigurationError, UpstreamError
from app.services import gemini, groq, text_ai

QUOTA = UpstreamError("Gemini free-tier quota reached. Try again in a minute.")
OVERLOADED = UpstreamError("Gemini is overloaded right now. Wait a few seconds and try again.")
UNREACHABLE = UpstreamError("Could not reach Gemini: ReadTimeout")
BAD_REQUEST = UpstreamError("Gemini blocked the request (SAFETY).")
NO_KEY = ConfigurationError("GEMINI_API_KEY is not set.")

PARSED = {"items": [{"food_name": "tea", "usda_query": "tea", "estimated_grams": 120,
                     "confidence": 0.8, "fallback_calories_per_100g": 34}]}


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch):
    """Script both providers and record which was called."""
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")

    def install(gemini_error: Exception | None):
        calls: list[str] = []

        async def fake_gemini_parse(text: str):
            calls.append("gemini")
            if gemini_error:
                raise gemini_error
            return PARSED

        async def fake_groq_parse(text: str):
            calls.append("groq")
            return PARSED

        async def fake_gemini_chat(history, *, context_json):
            calls.append("gemini")
            if gemini_error:
                raise gemini_error
            return "from gemini"

        async def fake_groq_chat(history, *, context_json, **kw):
            calls.append("groq")
            return "from groq"

        monkeypatch.setattr(gemini, "parse_meal_text", fake_gemini_parse)
        monkeypatch.setattr(groq, "parse_meal_text", fake_groq_parse)
        monkeypatch.setattr(gemini, "chat", fake_gemini_chat)
        monkeypatch.setattr(groq, "chat", fake_groq_chat)
        return calls

    return install


async def test_gemini_answers_when_it_can(providers):
    calls = providers(None)
    parsed, provider = await text_ai.parse_meal_text("half cup of tea")
    assert parsed == PARSED
    assert calls == ["gemini"], "Groq must not be called when Gemini works"
    assert provider == settings.gemini_model


@pytest.mark.parametrize("failure", [QUOTA, OVERLOADED, UNREACHABLE, NO_KEY],
                         ids=["quota", "overloaded", "unreachable", "no-key"])
async def test_provider_failures_fall_through_to_groq(providers, failure):
    calls = providers(failure)
    parsed, provider = await text_ai.parse_meal_text("half cup of tea")
    assert parsed == PARSED
    assert calls == ["gemini", "groq"]
    assert provider == settings.groq_model


async def test_a_bad_request_is_not_retried_on_the_other_provider(providers):
    """Rejected content fails the same way twice; retrying only adds delay."""
    calls = providers(BAD_REQUEST)
    with pytest.raises(UpstreamError, match="blocked the request"):
        await text_ai.parse_meal_text("half cup of tea")
    assert calls == ["gemini"]


async def test_without_a_groq_key_the_gemini_error_surfaces(providers, monkeypatch):
    calls = providers(QUOTA)
    monkeypatch.setattr(settings, "groq_api_key", "")
    with pytest.raises(UpstreamError, match="quota"):
        await text_ai.parse_meal_text("half cup of tea")
    assert calls == ["gemini"], "nothing to fall back to"


async def test_the_coach_falls_back_too(providers):
    calls = providers(QUOTA)
    reply, provider = await text_ai.chat(
        [{"role": "user", "content": "how am I doing?"}], context_json="{}"
    )
    assert reply == "from groq"
    assert calls == ["gemini", "groq"]
    assert provider == settings.groq_model


async def test_errors_stay_app_errors_so_callers_can_still_degrade(providers, monkeypatch):
    """chat.py catches AppError to fall back to its offline reply."""
    calls = providers(QUOTA)

    async def groq_also_fails(history, *, context_json, **kw):
        calls.append("groq")
        raise UpstreamError("Groq rate limit reached. Try again in a moment.")

    monkeypatch.setattr(groq, "chat", groq_also_fails)
    with pytest.raises(AppError):
        await text_ai.chat([{"role": "user", "content": "hi"}], context_json="{}")
    assert calls == ["gemini", "groq"]
