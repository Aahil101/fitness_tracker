"""Text AI with a provider fallback: Gemini first, Groq if it is unavailable.

Gemini's free tier permits 20 generate_content calls a day across the coach,
insights and food logging combined, so in practice it runs dry and the features
that depend on it stop working mid-day. Groq has much higher free limits, so
rather than fail the request it takes over.

Gemini stays first because it is the better model for this task and holds the
photo path, which Groq cannot serve — Groq publishes no vision models. Only
genuine upstream failures fall through: a quota exhaustion, an outage, a
timeout. A bad request would fail identically on both, so it is re-raised.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import settings
from ..errors import ConfigurationError, UpstreamError
from . import gemini, groq

log = logging.getLogger(__name__)


def _should_fall_back(exc: Exception) -> bool:
    """True when the failure is the provider's fault rather than the request's."""
    if not settings.groq_configured:
        return False
    # A missing Gemini key is exactly the case Groq should cover.
    if isinstance(exc, ConfigurationError):
        return True
    if not isinstance(exc, UpstreamError):
        return False
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("quota", "overloaded", "could not reach", "rate limit", "unavailable", "error 5")
    )


async def parse_meal_text(text: str) -> tuple[dict[str, Any], str]:
    """Parse a described meal. Returns the payload and the provider that answered."""
    try:
        return await gemini.parse_meal_text(text), settings.gemini_model
    except (UpstreamError, ConfigurationError) as exc:
        if not _should_fall_back(exc):
            raise
        log.info("Gemini unavailable (%s); parsing with Groq instead", exc)
        return await groq.parse_meal_text(text), settings.groq_model


async def chat(history: list[dict[str, str]], *, context_json: str) -> tuple[str, str]:
    """Coach reply. Returns the text and the provider that answered."""
    try:
        return await gemini.chat(history, context_json=context_json), settings.gemini_model
    except (UpstreamError, ConfigurationError) as exc:
        if not _should_fall_back(exc):
            raise
        log.info("Gemini unavailable (%s); answering with Groq instead", exc)
        return await groq.chat(history, context_json=context_json), settings.groq_model
