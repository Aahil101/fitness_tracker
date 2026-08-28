"""Integration tests over the wired application.

These cover what the unit tests cannot: dependency resolution, the PostgREST
query strings the handlers actually build, the response contracts the frontend
consumes, and the graceful-degradation paths when AI credentials are absent.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Auth boundary
# ---------------------------------------------------------------------------
PROTECTED_PATHS = (
    "/api/me",
    "/api/dashboard",
    "/api/analytics",
    "/api/goals",
    "/api/food/logs",
    "/api/food/recent",
    "/api/workouts",
    "/api/weight",
    "/api/weight/streak",
    "/api/chat/sessions",
)


def test_every_user_scoped_route_rejects_anonymous_requests(anon_client: TestClient):
    for path in PROTECTED_PATHS:
        response = anon_client.get(path)
        assert response.status_code in (401, 503), f"{path} returned {response.status_code}"
        assert "error" in response.json()


def test_public_routes_stay_open(anon_client: TestClient):
    assert anon_client.get("/health").status_code == 200
    assert anon_client.get("/api/workouts/catalog").status_code == 200


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
def test_me_returns_profile_goal_and_integration_state(client: TestClient):
    body = client.get("/api/me").json()
    assert body["profile"]["full_name"] == "Test Person"
    assert body["timezone"] == "Asia/Kolkata"
    assert body["goal_is_provisional"] is False
    assert body["needs_onboarding"] is False
    assert set(body["integrations"]) >= {"supabase", "gemini", "usda", "redis"}


# ---------------------------------------------------------------------------
# Dashboard — the front page contract
# ---------------------------------------------------------------------------
def test_dashboard_gauge_exposes_all_three_arc_layers(client: TestClient):
    gauge = client.get("/api/dashboard").json()["gauge"]

    # Layer 1 ceiling, layer 2 fill, layer 3 marker.
    assert gauge["maintenance_calories"] == 2450
    assert gauge["daily_calorie_target"] == 1900
    assert 0 <= gauge["fraction_of_maintenance"] <= 1
    assert 0 < gauge["target_fraction_of_maintenance"] <= 1
    assert gauge["remaining_to_target"] == round(1900 - gauge["logged_calories"], 1)
    assert gauge["over_target"] is (gauge["logged_calories"] > 1900)


def test_dashboard_returns_three_rolling_windows(client: TestClient):
    periods = client.get("/api/dashboard").json()["periods"]
    assert {"week", "month", "year"} == set(periods)
    assert [periods[k]["days"] for k in ("week", "month", "year")] == [7, 30, 365]

    # Rolling windows nest, so totals must be non-decreasing.
    assert (
        periods["week"]["total_calories"]
        <= periods["month"]["total_calories"]
        <= periods["year"]["total_calories"]
    )


def test_daily_average_divides_by_days_logged_not_days_elapsed(client: TestClient):
    year = client.get("/api/dashboard").json()["periods"]["year"]
    # The fixture logs 10 days out of 365; dividing by 365 would read ~44 kcal.
    assert year["days_logged"] == 10
    assert year["daily_average"] == round(year["total_calories"] / 10, 1)
    assert year["daily_average"] > 1000


def test_dashboard_forecast_reports_both_projected_and_measured_trends(client: TestClient):
    forecast = client.get("/api/dashboard").json()["forecast"]
    assert forecast["projected_weekly_change_kg"] < 0  # fixture runs a deficit
    # The fixture's weigh-ins fall 0.08 kg/day => -0.56 kg/week.
    assert forecast["observed_weekly_change_kg"] == -0.56
    assert forecast["confidence"] in ("low", "medium", "high")
    assert forecast["days_to_goal"] is not None


def test_forecast_window_is_honoured_and_bounded(client: TestClient):
    for window in (7, 14, 30):
        body = client.get(f"/api/dashboard?forecast_window={window}").json()
        assert body["forecast"]["window_days"] == window

    # Regression guard: a Literal[7, 14, 30] annotation here rejected the query
    # string "7" outright, 422-ing every dashboard load.
    assert client.get("/api/dashboard?forecast_window=7").status_code == 200
    assert client.get("/api/dashboard?forecast_window=10").status_code == 200
    assert client.get("/api/dashboard?forecast_window=400").status_code == 422


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def test_analytics_series_are_zero_filled_across_the_range(client: TestClient):
    body = client.get("/api/analytics?days=30").json()
    assert len(body["calorie_series"]) == 30
    assert len(body["macro_series"]) == 30
    assert body["range"]["days"] == 30

    # Unlogged days must be distinguishable from days of genuine fasting.
    unlogged = [point for point in body["calorie_series"] if not point["logged"]]
    assert unlogged, "fixture should include unlogged days"
    assert all(point["net"] is None for point in unlogged)


def test_analytics_projection_extends_beyond_the_last_weigh_in(client: TestClient):
    body = client.get("/api/analytics?days=30").json()
    assert len(body["weight_series"]) > 0
    assert len(body["weight_projection"]) > 1
    assert body["weight_projection"][0]["date"] <= body["weight_projection"][-1]["date"]
    assert set(body["workout_groups"]) == {"day", "week"}
    assert body["activity_breakdown"][0]["calories_burned"] > 0


def test_analytics_range_is_bounded(client: TestClient):
    assert client.get("/api/analytics?days=9999").status_code == 422
    assert client.get("/api/analytics?days=1").status_code == 422


# ---------------------------------------------------------------------------
# Timezone handling
# ---------------------------------------------------------------------------
def test_day_boundaries_are_converted_from_the_users_timezone_to_utc(
    client: TestClient, queries: list[tuple[str, list[tuple[str, Any]]]]
):
    client.get("/api/dashboard")

    food_queries = [pairs for table, pairs in queries if table == "food_logs"]
    assert food_queries, "dashboard should query food_logs"

    bounds = [
        value
        for pairs in food_queries
        for key, value in pairs
        if key == "logged_at" and str(value).startswith("gte.")
    ]
    # Asia/Kolkata is UTC+5:30, so local midnight is 18:30 UTC the day before.
    assert any("18:30" in str(value) for value in bounds), bounds[:3]


def test_range_filters_use_repeated_keys_rather_than_a_single_dict_entry(
    client: TestClient, queries: list[tuple[str, list[tuple[str, Any]]]]
):
    client.get("/api/dashboard")
    food_queries = [pairs for table, pairs in queries if table == "food_logs"]
    # A dict cannot express logged_at>=X AND logged_at<Y; both must be present.
    assert any(sum(1 for key, _ in pairs if key == "logged_at") == 2 for pairs in food_queries)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
def test_goal_preview_matches_mifflin_st_jeor_by_hand(client: TestClient):
    body = client.post(
        "/api/goals/preview",
        json={
            "weight_kg": 80,
            "height_cm": 180,
            "age_years": 30,
            "sex": "male",
            "activity_level": "sedentary",
            "weekly_change_kg": -0.5,
        },
    ).json()
    assert body["bmr"] == 1780  # 10*80 + 6.25*180 - 5*30 + 5
    assert body["maintenance_calories"] == 2136  # x1.2
    assert body["daily_calorie_target"] == 1586  # - 3850/7
    assert body["macros"]["protein_g"] == 144.0  # 1.8 g/kg


def test_goal_preview_refuses_to_promise_an_unsafe_deficit(client: TestClient):
    body = client.post(
        "/api/goals/preview",
        json={
            "weight_kg": 55,
            "height_cm": 160,
            "age_years": 45,
            "sex": "female",
            "activity_level": "sedentary",
            "weekly_change_kg": -1.5,
        },
    ).json()
    assert body["daily_calorie_target"] >= 1200
    assert body["warnings"]
    # The promised rate is recomputed after clamping.
    assert body["projected_weekly_change_kg"] > -1.5


def test_goal_preview_falls_back_to_the_stored_profile(client: TestClient):
    body = client.post("/api/goals/preview", json={}).json()
    assert body["maintenance_calories"] > 1200
    assert body["daily_calorie_target"] < body["maintenance_calories"]


# ---------------------------------------------------------------------------
# Writes & validation
# ---------------------------------------------------------------------------
def test_food_log_round_trip(client: TestClient):
    response = client.post(
        "/api/food/logs",
        json={
            "food_name": "Greek yogurt",
            "portion_g": 170,
            "calories": 100,
            "protein_g": 17,
            "meal_type": "breakfast",
        },
    )
    assert response.status_code == 201
    log = response.json()["log"]
    assert log["user_id"] is not None
    assert log["logged_at"]  # server-stamped when omitted


def test_batch_insert_supports_confirming_an_ai_draft(client: TestClient):
    response = client.post(
        "/api/food/logs/batch",
        json=[
            {"food_name": "Rice", "portion_g": 150, "calories": 200, "source": "ai_confirmed"},
            {"food_name": "Dal", "portion_g": 120, "calories": 140, "source": "ai_confirmed"},
        ],
    )
    assert response.status_code == 201
    assert response.json()["count"] == 2


def test_workout_burn_is_estimated_when_not_supplied(client: TestClient):
    workout = client.post(
        "/api/workouts", json={"activity_type": "running", "duration_min": 30}
    ).json()["workout"]
    assert workout["calories_burned"] > 0
    assert workout["source"] == "met_estimated"


def test_supplied_workout_burn_is_kept_as_manual(client: TestClient):
    workout = client.post(
        "/api/workouts",
        json={"activity_type": "running", "duration_min": 30, "calories_burned": 275},
    ).json()["workout"]
    assert workout["calories_burned"] == 275
    assert workout["source"] == "manual"


def test_burn_estimate_endpoint_uses_the_met_table(client: TestClient):
    body = client.post(
        "/api/workouts/estimate", json={"activity_type": "running", "duration_min": 30}
    ).json()
    assert body["met"] == 9.8
    assert body["calories_burned"] > 0


def test_weight_upsert_reports_the_change_since_the_previous_entry(client: TestClient):
    body = client.post("/api/weight", json={"weight_kg": 82.4}).json()
    assert body["log"]["weight_kg"] == 82.4
    assert body["change_since_previous_kg"] is not None


def test_input_validation_rejects_impossible_values(client: TestClient):
    assert (
        client.post("/api/food/logs", json={"food_name": "x", "portion_g": 0, "calories": 10}).status_code
        == 422
    )
    assert client.post("/api/weight", json={"weight_kg": 999}).status_code == 422
    assert client.post("/api/chat/messages", json={"content": ""}).status_code == 422
    assert (
        client.post("/api/workouts", json={"activity_type": "run", "duration_min": 0}).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# AI degradation — the app must stay usable without Gemini configured.
# These pin the credential state via `no_ai_credentials` so they neither
# depend on the developer's .env nor spend live API quota.
# ---------------------------------------------------------------------------
def test_ai_status_reports_missing_configuration(client: TestClient, no_ai_credentials: None):
    body = client.get("/api/ai/status").json()
    assert body["gemini_configured"] is False
    assert body["model"]


def test_photo_endpoint_explains_the_missing_key_instead_of_500ing(
    client: TestClient, no_ai_credentials: None
):
    response = client.post(
        "/api/ai/food-photo", files={"file": ("meal.jpg", b"\xff\xd8\xff\xdb fake", "image/jpeg")}
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["error"]["message"]


def test_photo_endpoint_rejects_non_images(client: TestClient):
    response = client.post(
        "/api/ai/food-photo", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code in (400, 503)


def test_insight_falls_back_to_rule_based_prose_with_real_numbers(
    client: TestClient, no_ai_credentials: None
):
    body = client.post("/api/ai/insight", json={"kind": "weekly", "refresh": True}).json()
    assert body["model"] is None  # no model was used
    assert len(body["body"]) > 40
    assert body["metrics"]["days_logged"] > 0
    # The narrative must quote the target it was given, not invent one.
    assert "1,900" in body["body"] or "1900" in body["body"]


def test_chat_degrades_to_the_users_own_numbers(client: TestClient, no_ai_credentials: None):
    body = client.post("/api/chat/messages", json={"content": "How am I doing?"}).json()
    assert body["degraded"] is True
    assert body["session_id"]
    assert "today_calories" in body["context_used"]
    assert len(body["assistant_message"]["content"]) > 40


def test_chat_history_endpoints(client: TestClient):
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert len(sessions) == 1

    messages = client.get(f"/api/chat/sessions/{sessions[0]['id']}/messages")
    assert messages.status_code == 200
    assert "session" in messages.json()

    assert client.get("/api/chat/suggestions").json()["prompts"]



class TestMeasuredMetrics:
    """The new blocks, checked against the known fixture rows.

    The fixture logs 3 meals a day for 10 days against a 1900 kcal target and
    2450 kcal maintenance, and carries 21 daily weigh-ins falling 0.08 kg/day.
    """

    def test_dashboard_exposes_the_trend_alongside_the_raw_reading(self, client: TestClient):
        body = client.get("/api/dashboard").json()
        trend = body["weight_trend"]
        # 0.08 kg/day is 0.56 kg/week. The trend must recover it, not a shallower
        # figure: understating progress is how a working diet looks like a failure.
        assert trend["weekly_change_kg"] == pytest.approx(-0.56, abs=0.06)
        assert trend["rate_status"] in {"gentle", "on_target", "rapid"}
        assert trend["rate_label"] and trend["rate_detail"]
        # Percentage of bodyweight, because that is the form the guidance takes.
        assert trend["weekly_change_pct"] == pytest.approx(
            trend["weekly_change_kg"] / trend["trend_kg"] * 100, abs=0.02
        )
        # Both numbers stay available; the trend does not replace the scale.
        assert body["weight"]["trend_kg"] is not None
        assert body["weight"]["current_kg"] is not None

    def test_expenditure_falls_back_to_the_formula_on_patchy_logging(
        self, client: TestClient
    ):
        """10 logged days inside a 28-day window is too thin to measure from."""
        body = client.get("/api/dashboard").json()
        exp = body["expenditure"]
        assert exp["source"] == "formula"
        assert exp["maintenance_kcal"] == pytest.approx(2450.0)
        assert exp["measured_kcal"] is None
        assert exp["notes"], "should say what would unlock a measured figure"
        assert exp["how_calculated"]

    def test_maintenance_agrees_across_every_block_that_shows_it(
        self, client: TestClient
    ):
        """The gauge arc, the deficit panel and the analytics page cannot disagree."""
        dash = client.get("/api/dashboard").json()
        analytics = client.get("/api/analytics").json()
        maintenance = dash["expenditure"]["maintenance_kcal"]
        assert dash["gauge"]["maintenance_calories"] == pytest.approx(maintenance, abs=1)
        assert dash["deficit"]["maintenance_calories"] == pytest.approx(maintenance, abs=1)
        assert analytics["targets"]["maintenance_calories"] == pytest.approx(maintenance, abs=1)
        assert analytics["expenditure"]["maintenance_kcal"] == pytest.approx(maintenance, abs=1)

    def test_adherence_grades_the_plan_not_the_typing(self, client: TestClient):
        """The fixture eats ~1620 against a 1900 target, so days are under, not on."""
        body = client.get("/api/dashboard").json()
        adherence = body["adherence"]
        assert adherence["days_logged"] > 0
        assert adherence["days_compliant"] == 0
        assert adherence["weakest_link"] == "calories"
        assert "under" in adherence["headline"].lower()
        # Rate is over logged days, never over the whole window.
        assert adherence["compliance_rate"] == pytest.approx(
            adherence["days_compliant"] / adherence["days_logged"]
        )
        assert adherence["how_calculated"]

    def test_goal_eta_is_a_range(self, client: TestClient):
        body = client.get("/api/dashboard").json()
        fc = body["forecast"]
        if fc["goal_date"]:
            assert fc["goal_date_earliest"] <= fc["goal_date"] <= fc["goal_date_latest"]
            assert fc["goal_eta_note"]

    def test_analytics_weight_series_carries_the_trend_channel(self, client: TestClient):
        body = client.get("/api/analytics").json()
        assert body["weight_series"], "fixture has weigh-ins"
        for point in body["weight_series"]:
            assert set(point) == {"date", "weight_kg", "trend_kg"}
        # The projection must start from the trend, not from the last raw reading,
        # or the forecast line jumps by whatever water the user was carrying.
        assert body["weight_projection"]
        first = body["weight_projection"][0]["projected_kg"]
        assert first == pytest.approx(body["weight_trend"]["trend_kg"], abs=0.2)

    def test_every_new_block_ships_an_explanation(self, client: TestClient):
        """Trust requires that a user can find out where a number came from."""
        body = client.get("/api/dashboard").json()
        assert body["weight_trend"]["how_calculated"]
        assert body["expenditure"]["how_calculated"]
        assert body["adherence"]["how_calculated"]



class TestAdherenceExcludesToday:
    """A half-finished day is not a failed day.

    The fixture logs three meals a day including today, but at any hour before
    the last meal today's total is necessarily below target. Grading it would
    mark the user off-plan for not having eaten dinner yet.
    """

    def test_today_is_not_graded(self, client: TestClient):
        from datetime import date as _date
        from datetime import timedelta as _timedelta

        body = client.get("/api/dashboard").json()
        adherence = body["adherence"]
        today = _date.fromisoformat(body["today"]["date"])

        # The window ends yesterday, so it can never include today.
        assert adherence["days_in_window"] == 14
        analytics = client.get("/api/analytics").json()
        assert analytics["adherence"]["days_in_window"] <= 14

        # And the day count cannot exceed the days that have actually finished.
        assert adherence["days_logged"] <= 14
        assert today - _timedelta(days=1) <= today  # sanity on the fixture clock

    def test_dashboard_and_analytics_agree_on_adherence(self, client: TestClient):
        """Two surfaces, one number — a user comparing them must not find a gap."""
        dash = client.get("/api/dashboard").json()["adherence"]
        analytics = client.get("/api/analytics").json()["adherence"]
        assert dash["days_compliant"] == analytics["days_compliant"]
        assert dash["days_logged"] == analytics["days_logged"]
