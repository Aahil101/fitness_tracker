"""Generated summaries ("how did my week go?").

The metrics are computed deterministically here; Gemini only turns them into
prose. That split matters: the numbers a user sees are never hallucinated, and
if the model is unavailable or out of quota we fall back to a rule-based
narrative instead of showing an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..errors import AppError
from . import gemini

log = logging.getLogger(__name__)

INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "body": {"type": "STRING"},
        "highlights": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "body", "highlights"],
}

PROMPT_TEMPLATE = """You are writing a {period_label} recap inside a nutrition and fitness app.

Here are the user's real numbers as JSON. Use only these — never invent a figure:
{metrics_json}

Write:
- headline: max 8 words, specific and warm. No emoji, no exclamation marks.
- body: 2-4 sentences. Lead with what actually happened versus the target, then
  the single most useful adjustment. Quote real numbers. Second person ("you").
- highlights: 2-4 short strings, max 9 words each, each anchored to a number.

Tone rules:
- Neutral and practical. Never shame, never hype.
- No "good"/"bad" foods, no moralising about calories.
- If days_logged is low, say the data is thin rather than drawing conclusions.
- No medical advice. No calorie target below 1200. No weight loss above 1kg/week.
"""


def _fmt(value: Any, digits: int = 0, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    formatted = f"{number:,.{digits}f}"
    return f"{formatted}{suffix}"


def fallback_summary(kind: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """Rule-based recap used when Gemini is unavailable."""
    target = metrics.get("daily_calorie_target") or 0
    highlights: list[str] = []

    if kind == "daily":
        eaten = metrics.get("calories_consumed") or 0
        remaining = metrics.get("calories_remaining")
        burned = metrics.get("calories_burned") or 0
        protein = metrics.get("protein_g") or 0
        protein_target = metrics.get("protein_target_g") or 0

        if remaining is not None and remaining >= 0:
            headline = f"{_fmt(remaining)} kcal left today"
            body = (
                f"You've logged {_fmt(eaten)} kcal of your {_fmt(target)} kcal target. "
                f"That leaves {_fmt(remaining)} kcal to work with."
            )
        else:
            over = abs(remaining or 0)
            headline = f"{_fmt(over)} kcal over target"
            body = (
                f"You've logged {_fmt(eaten)} kcal against a {_fmt(target)} kcal target, "
                f"so you're {_fmt(over)} kcal over. One day rarely matters — the weekly average does."
            )

        if burned:
            body += f" You also burned {_fmt(burned)} kcal in training."
        if protein_target:
            highlights.append(f"Protein {_fmt(protein)}g of {_fmt(protein_target)}g")
        if burned:
            highlights.append(f"Exercise burn {_fmt(burned)} kcal")
        highlights.append(f"Entries logged: {metrics.get('entry_count', 0)}")
    else:
        avg = metrics.get("avg_daily_calories") or 0
        days_logged = metrics.get("days_logged") or 0
        window = metrics.get("window_days") or 7
        projected = metrics.get("projected_weekly_change_kg")
        observed = metrics.get("observed_weekly_change_kg")

        headline = f"{_fmt(avg)} kcal daily average"
        body = (
            f"Across {days_logged} of {window} logged days you averaged {_fmt(avg)} kcal "
            f"against a {_fmt(target)} kcal target."
        )
        if projected is not None:
            direction = "losing" if projected < 0 else "gaining"
            body += f" At that pace you're {direction} about {_fmt(abs(projected), 2)} kg per week."
        if observed is not None:
            body += f" The scale moved {_fmt(observed, 2)} kg per week over the same period."
        if days_logged < window * 0.6:
            body += " With this few logged days the estimate is rough — log more to sharpen it."

        highlights.append(f"Avg protein {_fmt(metrics.get('avg_protein_g'))}g/day")
        if metrics.get("workout_sessions"):
            highlights.append(
                f"{metrics['workout_sessions']} sessions, {_fmt(metrics.get('workout_minutes'))} min"
            )
        highlights.append(f"Logged {days_logged}/{window} days")

    return {
        "headline": headline,
        "body": body,
        "highlights": [h for h in highlights if h][:4],
        "model": None,
    }


async def generate_insight(kind: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """Ask Gemini for prose over pre-computed metrics; degrade to rules on failure."""
    period_label = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}.get(kind, "weekly")
    prompt = PROMPT_TEMPLATE.format(
        period_label=period_label,
        metrics_json=json.dumps(metrics, indent=2, default=str),
    )

    try:
        parsed = await gemini.generate_json(prompt, INSIGHT_SCHEMA, temperature=0.5)
    except AppError as exc:
        log.info("Insight generation degraded to rule-based: %s", exc.detail)
        result = fallback_summary(kind, metrics)
        result["degraded_reason"] = exc.detail
        return result

    highlights = parsed.get("highlights") or []
    if not isinstance(highlights, list):
        highlights = []

    headline = str(parsed.get("headline") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if not headline or not body:
        return fallback_summary(kind, metrics)

    from ..config import settings

    return {
        "headline": headline[:120],
        "body": body[:1200],
        "highlights": [str(h)[:80] for h in highlights][:4],
        "model": settings.gemini_model,
    }
