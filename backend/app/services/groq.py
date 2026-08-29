"""Groq fallback for the text-only AI paths.

Gemini's free tier allows 20 generate_content calls a day, which the coach,
insights and food logging all share — so it runs dry quickly and text logging
stops working. Groq serves an OpenAI-compatible endpoint with far higher free
limits and answers a meal parse in about two seconds, so it stands in whenever
Gemini is unavailable.

Text only, deliberately: Groq currently publishes no vision models, so photo
recognition has no fallback and stays on Gemini.

The prompts are imported from :mod:`gemini` rather than copied. Two divergent
copies of the parsing rules would drift, and the rules are the valuable part.
The only addition is an explicit JSON shape, because Gemini enforces structure
with responseSchema while Groq needs it stated in the prompt.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import settings
from ..errors import ConfigurationError, UpstreamError
from ..http import get_http_client
from . import keypool
from .gemini import ASSISTANT_SYSTEM_PROMPT, MEAL_TEXT_PROMPT
from .keypool import get_pool

log = logging.getLogger(__name__)

# Groq sits behind Cloudflare, which rejects requests with a default library
# User-Agent (error 1010). The shared client already sends a real one.
JSON_SHAPE = """
Return JSON only, no prose, shaped exactly:
{"items":[{"food_name":string,"usda_query":string,"estimated_grams":number,
"confidence":number,"preparation":string,"quantity_text":string,
"fallback_calories_per_100g":number,"fallback_protein_per_100g":number,
"fallback_carbs_per_100g":number,"fallback_fat_per_100g":number}],
"meal_type":string,"notes":string}
"""


async def _chat_completion(
    messages: list[dict[str, str]],
    *,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
) -> str:
    if not settings.groq_configured:
        raise ConfigurationError("GROQ_API_KEY is not set.")

    pool = get_pool("groq", settings.groq_key_list)
    last_error: Exception | None = None
    for key in pool.healthy():
        try:
            content = await _chat_with_key(
                messages,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=key.value,
            )
        except UpstreamError as exc:
            verdict = keypool.classify(getattr(exc, "status_code", None), str(exc))
            if verdict is None:
                raise
            pool.bench(key, verdict[0], verdict[1])
            last_error = exc
            continue
        pool.note_success(key)
        return content

    if last_error is not None:
        raise last_error
    raise UpstreamError("No Groq key is currently usable.")


def _upstream(status_code: int, message: str) -> UpstreamError:
    error = UpstreamError(message)
    error.status_code = status_code  # type: ignore[attr-defined]
    return error


async def _chat_with_key(
    messages: list[dict[str, str]],
    *,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
    api_key: str,
) -> str:
    body: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    client = get_http_client()
    try:
        resp = await client.post(
            f"{settings.groq_api_base}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                # Groq sits behind Cloudflare, which answers a request with no
                # User-Agent with a 403 and Cloudflare error 1010 — nothing to do
                # with the key, but indistinguishable from a rejected one.
                "User-Agent": "PulseFitness/1.0",
            },
            timeout=settings.gemini_timeout_s,
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Could not reach Groq: {str(exc) or type(exc).__name__}") from exc

    if resp.status_code >= 400:
        detail = resp.text[:300]
        log.error("Groq %s error: %s", resp.status_code, detail)
        if resp.status_code == 429:
            raise _upstream(resp.status_code, "Groq rate limit reached. Try again in a moment.")
        if resp.status_code in (401, 403):
            raise _upstream(resp.status_code, "Groq rejected the API key.")
        if resp.status_code == 404:
            # The model is not enabled for this key; another key may have it.
            raise _upstream(resp.status_code, f"Groq model unavailable: {detail[:150]}")
        raise _upstream(resp.status_code, f"Groq error {resp.status_code}.")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise UpstreamError("Groq returned an unreadable response.") from exc

    if not (content or "").strip():
        raise UpstreamError("Groq returned an empty response.")
    return content


async def parse_meal_text(text: str) -> dict[str, Any]:
    """Same contract as :func:`gemini.parse_meal_text`, so callers are unchanged."""
    cleaned = text.strip()
    if not cleaned:
        raise UpstreamError("Describe what you ate first.")

    content = await _chat_completion(
        [
            {"role": "system", "content": MEAL_TEXT_PROMPT + JSON_SHAPE},
            {"role": "user", "content": cleaned[:1000]},
        ],
        json_mode=True,
        temperature=0.2,
        max_tokens=1200,
    )

    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise UpstreamError("Groq returned malformed JSON.") from exc
    if not isinstance(parsed, dict):
        raise UpstreamError("Groq returned an unexpected JSON shape.")
    return parsed


async def chat(
    history: list[dict[str, str]],
    *,
    context_json: str,
    temperature: float = 0.6,
    max_output_tokens: int = 900,
) -> str:
    """Same contract as :func:`gemini.chat`."""
    turns = [
        {"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"]}
        for m in history
        if m.get("content")
    ]
    if not turns:
        raise UpstreamError("No message to send.")

    return (
        await _chat_completion(
            [
                {"role": "system", "content": f"{ASSISTANT_SYSTEM_PROMPT}\n\nUser data:\n{context_json}"},
                *turns,
            ],
            json_mode=False,
            temperature=temperature,
            max_tokens=max_output_tokens,
        )
    ).strip()
