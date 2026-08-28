"""Test fixtures: an authenticated client backed by a fake PostgREST layer.

The fake stands in for Supabase so the integration tests can exercise real
dependency wiring, the query strings the handlers build, and the response
contracts the frontend depends on — without credentials or network access.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import deps, security
from app.main import app
from app.security import CurrentUser

USER_ID = "11111111-2222-3333-4444-555555555555"
USER_TZ = "Asia/Kolkata"  # UTC+5:30 — a half-hour offset catches naive maths
TZ = ZoneInfo(USER_TZ)
# "Today" from the profile's point of view, which is what the API buckets by.
TODAY = datetime.now(TZ).date()


def _iso(days_ago: int = 0, hour: int = 12) -> str:
    """UTC timestamp for a given *local* wall-clock hour, N local days back.

    Anchoring on the local day matters: building these from the current UTC date
    instead made the suite time-of-day dependent. With a UTC+5:30 profile, a
    20:00 *UTC* entry falls at 01:30 the next local day, so the fixture spanned
    11 local days instead of 10 whenever the tests ran after 18:30 UTC. Local
    hours 8-20 never cross local midnight, so the span is now always exact.
    """
    local = datetime.combine(
        TODAY - timedelta(days=days_ago), time(hour=hour), tzinfo=TZ
    )
    return local.astimezone(UTC).isoformat()


PROFILE: dict[str, Any] = {
    "id": USER_ID,
    "full_name": "Test Person",
    "sex": "male",
    "birth_date": "1995-04-12",
    "starting_weight_kg": 84.0,
    "goal_weight_kg": 78.0,
    "height_cm": 178,
    "activity_level": "sedentary",
    "unit_preference": "metric",
    "timezone": USER_TZ,
    "onboarded_at": _iso(30),
}

GOAL: dict[str, Any] = {
    "id": "goal-1",
    "user_id": USER_ID,
    "daily_calorie_target": 1900,
    "maintenance_calories": 2450,
    "protein_target_g": 150,
    "carb_target_g": 190,
    "fat_target_g": 53,
    "fiber_target_g": 27,
    "target_weekly_deficit_kcal": -3850,
    "effective_from": (TODAY - timedelta(days=30)).isoformat(),
}

# Three meals a day for the last 10 days: ~1,620 kcal/day against a 1,900 target.
MEALS = (
    {"food_name": "Oats with milk", "calories": 420, "protein_g": 14, "carbs_g": 66, "fat_g": 8, "fiber_g": 9, "meal_type": "breakfast", "hour": 8},
    {"food_name": "Chicken breast", "calories": 680, "protein_g": 62, "carbs_g": 0, "fat_g": 14, "fiber_g": 0, "meal_type": "lunch", "hour": 13},
    {"food_name": "Basmati rice", "calories": 520, "protein_g": 11, "carbs_g": 96, "fat_g": 2, "fiber_g": 2, "meal_type": "dinner", "hour": 20},
)

FOOD_ROWS: list[dict[str, Any]] = [
    {
        "id": f"food-{day}-{index}",
        "user_id": USER_ID,
        "logged_at": _iso(day, meal["hour"]),
        "portion_g": 150,
        "source": "manual",
        "ai_confidence": None,
        "image_url": None,
        "food_item_id": None,
        **{k: v for k, v in meal.items() if k != "hour"},
    }
    for day in range(10)
    for index, meal in enumerate(MEALS)
]

WORKOUT_ROWS: list[dict[str, Any]] = [
    {
        "id": f"workout-{i}",
        "user_id": USER_ID,
        "logged_at": _iso(i * 2, 18),
        "activity_type": "running" if i % 2 else "weights",
        "duration_min": 40,
        "calories_burned": 380 if i % 2 else 210,
        "intensity": "moderate",
        "source": "met_estimated",
        "notes": None,
    }
    for i in range(5)
]

# A steady 0.56 kg/week downward trend over three weeks.
WEIGHT_ROWS: list[dict[str, Any]] = [
    {
        "id": f"weight-{i}",
        "user_id": USER_ID,
        "logged_at": (TODAY - timedelta(days=20 - i)).isoformat(),
        "weight_kg": round(84.0 - i * 0.08, 2),
        "note": None,
    }
    for i in range(21)
]

CHAT_SESSION: dict[str, Any] = {
    "id": "session-1",
    "user_id": USER_ID,
    "title": "Why has my weight stalled?",
    "last_message_at": _iso(0),
    "created_at": _iso(1),
}


def as_pairs(params: Any) -> list[tuple[str, Any]]:
    if params is None:
        return []
    if isinstance(params, dict):
        return list(params.items())
    return list(params)


class FakeREST:
    """Stand-in for SupabaseREST that records the queries it is asked to run."""

    def __init__(self, queries: list[tuple[str, list[tuple[str, Any]]]]) -> None:
        self.queries = queries

    async def select(self, table: str, params: Any) -> list[dict[str, Any]]:
        pairs = as_pairs(params)
        self.queries.append((table, pairs))
        keys = dict(pairs)

        # Defence in depth: handlers must scope every user-owned read.
        if table == "profiles":
            assert keys.get("id") == f"eq.{USER_ID}", f"profiles unscoped: {pairs}"
        elif table != "food_items":
            assert keys.get("user_id") == f"eq.{USER_ID}", f"{table} unscoped: {pairs}"

        return {
            "profiles": [PROFILE],
            "goals": [GOAL],
            "food_logs": FOOD_ROWS,
            "workouts": WORKOUT_ROWS,
            "weight_logs": WEIGHT_ROWS,
            "chat_sessions": [CHAT_SESSION],
        }.get(table, [])

    async def select_one(self, table: str, params: Any) -> dict[str, Any] | None:
        rows = await self.select(table, params)
        return rows[0] if rows else None

    async def insert(self, table: str, rows: Any, returning: str = "representation") -> list[dict[str, Any]]:
        payload = rows if isinstance(rows, list) else [rows]
        return [{**row, "id": f"new-{table}-{i}"} for i, row in enumerate(payload)]

    async def insert_one(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        return (await self.insert(table, row))[0]

    async def upsert(self, table: str, rows: Any, on_conflict: str, returning: str = "representation"):
        return await self.insert(table, rows)

    async def update(self, table: str, patch: dict[str, Any], params: Any) -> list[dict[str, Any]]:
        if table == "profiles":
            return [{**PROFILE, **patch}]
        if table == "chat_sessions":
            return [{**CHAT_SESSION, **patch}]
        return [patch]

    async def update_one(self, table: str, patch: dict[str, Any], params: Any) -> dict[str, Any]:
        return (await self.update(table, patch, params))[0]

    async def delete(self, table: str, params: Any) -> list[dict[str, Any]]:
        return [{"id": "deleted"}]

    async def delete_one(self, table: str, params: Any) -> dict[str, Any]:
        return {"id": "deleted"}

    async def upload_image(self, path: str, content: bytes, content_type: str) -> str | None:
        return None

    async def signed_url(self, object_path: str, expires_in: int = 3600) -> str | None:
        return None


@pytest.fixture
def no_ai_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the AI-unconfigured state for degradation tests.

    Without this the tests inherit whatever is in backend/.env: on a machine
    with a real GEMINI_API_KEY they would assert the wrong branch *and* spend
    live quota on every run. Degradation is a behaviour we choose to test, so
    the configuration is set explicitly rather than inherited.

    Both providers are cleared. Leaving Groq configured would send the request
    down the fallback path instead of degrading, which is the opposite of what
    these tests exist to check.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "groq_api_key", "")


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def queries() -> list[tuple[str, list[tuple[str, Any]]]]:
    return []


@pytest.fixture
def client(queries: list[tuple[str, list[tuple[str, Any]]]]) -> Iterator[TestClient]:
    """Client authenticated as USER_ID with Supabase faked out."""

    async def fake_user() -> CurrentUser:
        return CurrentUser(
            id=USER_ID, email="test@example.com", access_token="fake-token", claims={"sub": USER_ID}
        )

    async def fake_db() -> FakeREST:
        return FakeREST(queries)

    app.dependency_overrides[security.get_current_user] = fake_user
    app.dependency_overrides[deps.get_db] = fake_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
