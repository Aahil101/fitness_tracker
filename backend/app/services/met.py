"""MET (Metabolic Equivalent of Task) table and burn estimation.

Values follow the Compendium of Physical Activities. kcal/min = MET × 3.5 × kg / 200,
which simplifies to ``kcal = MET × kg × hours``.

Caveat worth knowing: MET values describe *gross* expenditure, so they include
the resting calories the body would have burned anyway. If a user's activity
multiplier is above sedentary, logged workouts overlap with it. The goals service
warns about this; here we just report the standard gross figure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INTENSITY_MODIFIERS: dict[str, float] = {
    "light": 0.8,
    "moderate": 1.0,
    "vigorous": 1.25,
}


@dataclass(frozen=True)
class Activity:
    key: str
    label: str
    met: float
    category: str


# Ordered so the most commonly logged activities surface first in the UI.
ACTIVITIES: tuple[Activity, ...] = (
    # Cardio
    Activity("walking", "Walking (moderate, 5 km/h)", 3.5, "Cardio"),
    Activity("walking_brisk", "Walking (brisk, 6.5 km/h)", 5.0, "Cardio"),
    Activity("running", "Running (9.7 km/h)", 9.8, "Cardio"),
    Activity("running_fast", "Running (12 km/h)", 11.8, "Cardio"),
    Activity("treadmill", "Treadmill (mixed pace)", 6.0, "Cardio"),
    Activity("cycling", "Cycling (moderate, 19-22 km/h)", 8.0, "Cardio"),
    Activity("cycling_light", "Cycling (leisurely, <16 km/h)", 4.0, "Cardio"),
    Activity("spinning", "Indoor cycling / spin class", 8.5, "Cardio"),
    Activity("elliptical", "Elliptical trainer", 5.0, "Cardio"),
    Activity("rowing", "Rowing machine (moderate)", 7.0, "Cardio"),
    Activity("stair_climber", "Stair climber", 9.0, "Cardio"),
    Activity("jump_rope", "Jump rope", 12.3, "Cardio"),
    Activity("swimming", "Swimming (laps, moderate)", 8.3, "Cardio"),
    Activity("swimming_leisure", "Swimming (leisurely)", 6.0, "Cardio"),
    Activity("hiking", "Hiking", 6.0, "Cardio"),
    Activity("stairs", "Stair walking", 8.0, "Cardio"),
    # Strength & conditioning
    Activity("weights", "Weight training (general)", 5.0, "Strength"),
    Activity("weights_heavy", "Weight training (heavy, powerlifting)", 6.0, "Strength"),
    Activity("calisthenics", "Calisthenics (vigorous)", 8.0, "Strength"),
    Activity("hiit", "HIIT / circuit training", 8.0, "Strength"),
    Activity("crossfit", "CrossFit style workout", 7.5, "Strength"),
    Activity("core", "Core / abs work", 3.8, "Strength"),
    # Mind & body
    Activity("yoga", "Yoga (hatha)", 2.5, "Mind & body"),
    Activity("yoga_power", "Yoga (power / vinyasa)", 4.0, "Mind & body"),
    Activity("pilates", "Pilates", 3.0, "Mind & body"),
    Activity("stretching", "Stretching / mobility", 2.3, "Mind & body"),
    # Sports
    Activity("cricket", "Cricket", 4.8, "Sports"),
    Activity("badminton", "Badminton (social)", 5.5, "Sports"),
    Activity("football", "Football / soccer (casual)", 7.0, "Sports"),
    Activity("basketball", "Basketball (game)", 8.0, "Sports"),
    Activity("tennis", "Tennis (singles)", 7.3, "Sports"),
    Activity("table_tennis", "Table tennis", 4.0, "Sports"),
    Activity("volleyball", "Volleyball", 4.0, "Sports"),
    Activity("pickleball", "Pickleball", 5.5, "Sports"),
    Activity("boxing", "Boxing (bag work)", 7.8, "Sports"),
    Activity("martial_arts", "Martial arts", 10.3, "Sports"),
    Activity("climbing", "Rock climbing", 8.0, "Sports"),
    Activity("dancing", "Dancing", 5.0, "Sports"),
    Activity("skating", "Skating / rollerblading", 7.0, "Sports"),
    # Daily life
    Activity("housework", "Housework / cleaning", 3.0, "Daily life"),
    Activity("gardening", "Gardening", 3.8, "Daily life"),
    Activity("shopping", "Walking with groceries", 3.5, "Daily life"),
    Activity("other", "Other activity", 4.0, "Daily life"),
)

BY_KEY: dict[str, Activity] = {a.key: a for a in ACTIVITIES}
# Also allow matching by human label, lowercased, so free-text survives.
BY_LABEL: dict[str, Activity] = {a.label.lower(): a for a in ACTIVITIES}

DEFAULT_MET = 4.0

# Words too generic to identify an activity on their own.
_STOPWORDS = frozenset(
    {
        "and", "the", "a", "my", "of", "with", "for", "session", "sessions", "workout",
        "training", "trainer", "machine", "class", "work", "general", "style", "other",
        "min", "mins", "minute", "minutes", "hour", "morning", "evening", "afternoon",
        "night", "quick", "easy", "hard", "light", "moderate", "vigorous", "intense",
    }
)


def _terms(activity: Activity) -> tuple[str, ...]:
    """Identifying words for an activity: its key plus the label before any '('."""
    head = activity.label.split("(")[0]
    raw = re.findall(r"[a-z]+", f"{activity.key} {head}".lower())
    return tuple(w for w in dict.fromkeys(raw) if w not in _STOPWORDS and len(w) >= 3)


_SEARCH_TERMS: tuple[tuple[Activity, tuple[str, ...]], ...] = tuple(
    (a, _terms(a)) for a in ACTIVITIES
)


def resolve_met(activity_type: str) -> float:
    """Best-effort MET lookup for a key, label, or arbitrary free text."""
    if not activity_type:
        return DEFAULT_MET

    needle = activity_type.strip().lower()
    if needle in BY_KEY:
        return BY_KEY[needle].met
    if needle in BY_LABEL:
        return BY_LABEL[needle].met

    normalised = needle.replace(" ", "_").replace("-", "_")
    if normalised in BY_KEY:
        return BY_KEY[normalised].met

    # Word-level prefix match: "morning run" -> running, "spin class" -> spinning.
    words = [w for w in re.findall(r"[a-z]+", needle) if len(w) >= 3 and w not in _STOPWORDS]
    for activity, terms in _SEARCH_TERMS:
        for word in words:
            for term in terms:
                if term.startswith(word) or word.startswith(term):
                    return activity.met
    return DEFAULT_MET


def estimate_calories_burned(
    activity_type: str,
    duration_min: float,
    weight_kg: float,
    intensity: str | None = None,
) -> float:
    """kcal = MET × body mass (kg) × duration (hours), scaled by intensity."""
    met = resolve_met(activity_type)
    modifier = INTENSITY_MODIFIERS.get((intensity or "moderate").lower(), 1.0)
    hours = max(0.0, duration_min) / 60.0
    return round(met * modifier * max(20.0, weight_kg) * hours, 1)


def activity_catalog() -> list[dict[str, object]]:
    return [
        {"key": a.key, "label": a.label, "met": a.met, "category": a.category}
        for a in ACTIVITIES
    ]
