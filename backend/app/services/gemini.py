"""Gemini client (REST, no SDK).

Talking to ``generativelanguage.googleapis.com`` directly keeps the dependency
surface to httpx and avoids SDK churn. Three entry points:

* :func:`recognise_food` — vision + structured JSON output
* :func:`chat` — multi-turn assistant with a system instruction
* :func:`generate_text` — one-shot generation for summaries

Every function raises :class:`UpstreamError` on failure so callers can decide
whether to degrade gracefully (summaries, chat) or surface the error (vision).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from ..config import settings
from ..errors import ConfigurationError, UpstreamError
from ..http import get_http_client

log = logging.getLogger(__name__)

# Google answers 503 when the model is momentarily overloaded and 500/502/504
# when its edge hiccups. All clear on their own, so they are worth one or two
# quick retries; anything else is a real error and retrying only adds latency.
TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_DELAY_S = 0.8

# Structured-output schema for the food photo pipeline. Gemini's REST API expects
# OpenAPI-style uppercase type names.
FOOD_VISION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "food_name": {"type": "STRING"},
                    "usda_query": {"type": "STRING"},
                    "estimated_grams": {"type": "NUMBER"},
                    "confidence": {"type": "NUMBER"},
                    "preparation": {"type": "STRING"},
                },
                "required": ["food_name", "usda_query", "estimated_grams", "confidence"],
            },
        },
        "meal_type": {"type": "STRING"},
        "notes": {"type": "STRING"},
    },
    "required": ["items"],
}

FOOD_VISION_PROMPT = """You are a nutrition assistant identifying food in a photo.

Return every distinct food or drink you can see. For each one:
- food_name: what a person would call it, including preparation (e.g. "grilled chicken thigh")
- usda_query: 2-4 plain words to look this up in the USDA FoodData Central database.
  Use generic ingredient terms, no brands, no adjectives like "delicious".
- estimated_grams: edible weight in grams. Use visual references (plate ~26cm,
  fork ~19cm, standard mug ~350ml) and typical serving sizes. Exclude bones,
  shells, pits and packaging.
- confidence: 0.0-1.0 for how sure you are of the identification AND the portion.
  Be honest: mixed dishes and anything partly hidden should be below 0.6.
- preparation: fried / grilled / boiled / raw / baked / steamed, if visible.

Also set meal_type to one of breakfast, lunch, dinner, snack based on the food.
Put any caveat a human should check (hidden oil, unclear sauce, obscured portion)
in notes.

If the image contains no food at all, return an empty items array and say so in notes."""

ASSISTANT_SYSTEM_PROMPT = """You are the in-app fitness and nutrition coach for a personal tracking app.

How to behave:
- Ground every claim in the user's own numbers, which are provided below as JSON.
  Quote the figures you used ("you averaged 1,840 kcal over the last 7 days").
- Be concrete and specific. Prefer one actionable change over five vague ones.
- Keep answers short: 2-5 sentences, or a tight list of at most 5 bullets.
- If the data does not support an answer, say what is missing and what to log.
- Use the user's unit preference. Weight in kg unless the profile says imperial.
- Never invent logged entries, weights or dates that are not in the context.

Hard limits:
- You are not a doctor. Do not diagnose, do not interpret symptoms, do not give
  medical advice, and do not comment on medication or supplements beyond
  "ask a clinician".
- Never recommend under 1,200 kcal/day or losing more than 1 kg per week.
- If the user describes disordered eating, self-harm, or asks for an extreme
  fast, decline the specifics, respond with care, and suggest professional support.
- Do not moralise about food. No "good"/"bad" foods, no guilt."""


def _endpoint(model: str, method: str = "generateContent") -> str:
    return f"{settings.gemini_api_base}/models/{model}:{method}"


def _generation_config(
    *,
    json_schema: dict[str, Any] | None,
    temperature: float,
    max_output_tokens: int,
    thinking: bool,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
        "topP": 0.95,
    }
    if json_schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = json_schema
    if not thinking:
        # Flash models think by default; for these short, well-specified tasks it
        # only adds latency. Stripped automatically if the model rejects it.
        config["thinkingConfig"] = {"thinkingBudget": 0}
    return config


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            raise UpstreamError(f"Gemini blocked the request ({reason}).")
        raise UpstreamError("Gemini returned no candidates.")

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()

    if not text:
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            raise UpstreamError("Gemini response was cut off before any text was produced.")
        raise UpstreamError(f"Gemini returned an empty response (finishReason={finish}).")
    return text


async def _post(body: dict[str, Any], *, model: str) -> dict[str, Any]:
    if not settings.gemini_configured:
        raise ConfigurationError(
            "GEMINI_API_KEY is not set. Add it to the backend environment to enable AI features."
        )

    client = get_http_client()
    url = _endpoint(model)
    headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}

    last_transient = 0
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = await client.post(
                url, json=body, headers=headers, timeout=settings.gemini_timeout_s
            )
        except httpx.HTTPError as exc:
            # httpx timeout exceptions stringify to '', which logged a blank
            # reason and hid the actual cause; fall back to the class name.
            # Not retried: the attempt already spent the whole timeout budget.
            reason = str(exc) or type(exc).__name__
            raise UpstreamError(f"Could not reach Gemini: {reason}") from exc

        if resp.status_code < 400:
            return resp.json()

        detail = resp.text[:400]
        # Older / non-2.5 models reject thinkingConfig — drop it and retry once.
        if (
            attempt == 0
            and resp.status_code == 400
            and "thinking" in detail.lower()
            and "thinkingConfig" in json.dumps(body.get("generationConfig", {}))
        ):
            body["generationConfig"].pop("thinkingConfig", None)
            continue

        # 503 means Google's side is momentarily overloaded, not that anything is
        # wrong with the request; it usually clears on the next attempt and comes
        # back fast, so the backoff stays well inside the request budget.
        if resp.status_code in TRANSIENT_STATUSES and attempt < MAX_ATTEMPTS - 1:
            last_transient = resp.status_code
            delay = RETRY_DELAY_S * (2**attempt)
            log.info(
                "Gemini %s (overloaded), retrying in %.1fs (attempt %d/%d)",
                resp.status_code, delay, attempt + 1, MAX_ATTEMPTS,
            )
            await asyncio.sleep(delay)
            continue

        log.error("Gemini %s error: %s", resp.status_code, detail)
        if resp.status_code == 429:
            raise UpstreamError("Gemini free-tier quota reached. Try again in a minute.")
        if resp.status_code in (401, 403):
            raise UpstreamError("Gemini rejected the API key.")
        if resp.status_code == 404:
            raise UpstreamError(
                f"Gemini model '{model}' is not available for this key. "
                "Set GEMINI_MODEL to a model your key can access."
            )
        if resp.status_code in TRANSIENT_STATUSES:
            raise UpstreamError(
                "Gemini is overloaded right now. Wait a few seconds and try again — "
                "or enter the food manually."
            )
        raise UpstreamError(f"Gemini error {resp.status_code}: {detail}")

    raise UpstreamError(
        f"Gemini stayed overloaded ({last_transient}) after {MAX_ATTEMPTS} attempts. "
        "Wait a few seconds and try again — or enter the food manually."
        if last_transient
        else "Gemini request failed after retry."
    )


async def recognise_food(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    *,
    hint: str | None = None,
) -> dict[str, Any]:
    """Identify foods in a photo. Returns the parsed structured-output payload."""
    prompt = FOOD_VISION_PROMPT
    if hint:
        prompt += f"\n\nThe user says this is: {hint[:200]}. Use it to disambiguate."

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": _generation_config(
            json_schema=FOOD_VISION_SCHEMA,
            temperature=0.2,
            max_output_tokens=2048,
            thinking=False,
        ),
    }

    payload = await _post(body, model=settings.gemini_model)
    text = _extract_text(payload)
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise UpstreamError("Gemini did not return valid JSON for the photo.") from exc
    if not isinstance(parsed, dict):
        raise UpstreamError("Unexpected JSON shape from Gemini.")
    return parsed


async def chat(
    history: list[dict[str, str]],
    *,
    context_json: str,
    temperature: float = 0.6,
    max_output_tokens: int = 900,
) -> str:
    """Multi-turn reply. ``history`` is [{role: user|assistant, content: str}, ...]."""
    contents = [
        {
            "role": "model" if msg["role"] == "assistant" else "user",
            "parts": [{"text": msg["content"]}],
        }
        for msg in history
        if msg.get("content")
    ]
    if not contents:
        raise UpstreamError("No message to send.")

    body = {
        "systemInstruction": {
            "parts": [
                {"text": ASSISTANT_SYSTEM_PROMPT},
                {"text": f"\n\nThe user's current data:\n{context_json}"},
            ]
        },
        "contents": contents,
        "generationConfig": _generation_config(
            json_schema=None,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking=False,
        ),
    }
    payload = await _post(body, model=settings.gemini_model)
    return _extract_text(payload)


async def generate_json(
    prompt: str,
    schema: dict[str, Any],
    *,
    temperature: float = 0.4,
    max_output_tokens: int = 1200,
) -> dict[str, Any]:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": _generation_config(
            json_schema=schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking=False,
        ),
    }
    payload = await _post(body, model=settings.gemini_model)
    text = _extract_text(payload)
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise UpstreamError("Gemini returned malformed JSON.") from exc
    return parsed if isinstance(parsed, dict) else {"result": parsed}


MEAL_TEXT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "food_name": {"type": "STRING"},
                    "usda_query": {"type": "STRING"},
                    "estimated_grams": {"type": "NUMBER"},
                    "confidence": {"type": "NUMBER"},
                    "preparation": {"type": "STRING"},
                    "quantity_text": {"type": "STRING"},
                },
                "required": ["food_name", "usda_query", "estimated_grams", "confidence"],
            },
        },
        "meal_type": {"type": "STRING"},
        "notes": {"type": "STRING"},
    },
    "required": ["items"],
}

MEAL_TEXT_PROMPT = """You convert a written description of a meal into structured food items.

The user types casually, in any English variety, and often mixes units:
  "half cup of tea with 1 spoon"  ->  tea (120 g) + sugar (4 g)
  "grilled chicken 1 piece with butter 50g"  ->  grilled chicken breast (120 g) + butter (50 g)
  "2 rotis and a bowl of dal"  ->  roti x2 (80 g) + dal (200 g)

Rules:
* Split the description into one entry per distinct food. Never merge two foods.
* Always resolve the portion to grams. Convert household measures using ordinary
  cooking conventions: 1 cup liquid about 240 g, 1 tablespoon about 15 g,
  1 teaspoon about 5 g, "1 spoon" of sugar in a drink about 4 g. Halve for
  "half". Multiply for counts like "2 rotis".
* "1 spoon" alongside tea or coffee means sugar unless another food is named.
* Where the food is implied rather than stated (sugar in tea, oil for frying),
  include it as its own item so the calories are not lost.
* estimated_grams is the total for that entry, counting every unit of it.
* quantity_text echoes the user's own wording for that item, so they can see how
  their phrasing was read.
* usda_query is a plain search phrase for a nutrition database: no counts, no
  units, no brand names. "grilled chicken breast", not "1 piece grilled chicken".
* confidence is 0-1: high when the food and amount are both explicit, low when
  you inferred the portion.
* If nothing edible is described, return an empty items array and say why in notes.
* Set meal_type to breakfast, lunch, dinner or snack only if the text implies it.
"""


async def parse_meal_text(text: str) -> dict[str, Any]:
    """Free-text meal description -> the same item shape vision produces.

    Deliberately mirrors :func:`recognise_food`'s output so both paths feed the
    identical USDA resolution step; nutrition never comes from the model.
    """
    cleaned = text.strip()
    if not cleaned:
        raise UpstreamError("Describe what you ate first.")

    return await generate_json(
        f"{MEAL_TEXT_PROMPT}\nDescription:\n{cleaned[:1000]}",
        MEAL_TEXT_SCHEMA,
        temperature=0.2,
        max_output_tokens=1200,
    )


async def list_models() -> list[str]:
    """Names of models the configured key can actually call (diagnostics)."""
    if not settings.gemini_configured:
        return []
    client = get_http_client()
    try:
        resp = await client.get(
            f"{settings.gemini_api_base}/models",
            headers={"x-goog-api-key": settings.gemini_api_key},
        )
    except httpx.HTTPError:
        return []
    if resp.status_code >= 400:
        return []
    return [
        (m.get("name") or "").removeprefix("models/")
        for m in resp.json().get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
