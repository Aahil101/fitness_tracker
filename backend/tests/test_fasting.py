"""Fasting stages: the personalisation maths, and the timeline it produces."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services import fasting

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

BASE = {"weight_kg": 80.0, "maintenance_kcal": 2200.0}


def session(*, started_hours_ago: float, target: float = 16.0, ended_hours_ago: float | None = None):
    row = {
        "id": "sess-1",
        "started_at": (NOW - timedelta(hours=started_hours_ago)).isoformat(),
        "target_hours": target,
    }
    if ended_hours_ago is not None:
        row["ended_at"] = (NOW - timedelta(hours=ended_hours_ago)).isoformat()
    return row


def state(**kwargs):
    params = {
        "session": None,
        "now": NOW,
        "weight_kg": 80.0,
        "maintenance_kcal": 2200.0,
        "recent_carbs_g": 300.0,
        "exercise_kcal": 0.0,
    }
    params.update(kwargs)
    return fasting.evaluate(**params)


class TestPersonalisation:
    def test_a_normal_carb_day_lands_near_the_textbook_timeline(self):
        """A full liver on an average build should not move the chart much."""
        result = fasting.personalise(**BASE, recent_carbs_g=300.0)
        assert result.fill_fraction == pytest.approx(1.0)
        # ~88 g at 4.5 g/h is a shade under 20 hours, against a baseline of 18.
        assert result.estimated_depletion_hours == pytest.approx(19.6, abs=0.3)
        assert abs(result.shift_hours) < 2.5

    def test_a_low_carb_day_brings_ketosis_forward(self):
        result = fasting.personalise(**BASE, recent_carbs_g=40.0)
        assert result.shift_hours < 0
        assert result.fill_fraction == pytest.approx(fasting.MIN_FILL_FRACTION)

    def test_training_before_the_fast_brings_ketosis_forward(self):
        rested = fasting.personalise(**BASE, recent_carbs_g=300.0)
        trained = fasting.personalise(**BASE, recent_carbs_g=300.0, exercise_kcal=800.0)
        assert trained.shift_hours < rested.shift_hours
        # Only the liver's share of the carbohydrate cost counts: muscle glycogen
        # cannot refill the bloodstream, so it does not govern ketosis onset.
        assert trained.exercise_glycogen_g == pytest.approx(25.0, abs=0.5)

    def test_a_bigger_person_holds_more_but_also_burns_more(self):
        """Size should mostly cancel — timing is not wildly weight-dependent."""
        small = fasting.personalise(weight_kg=55.0, maintenance_kcal=1600.0, recent_carbs_g=300.0)
        large = fasting.personalise(weight_kg=110.0, maintenance_kcal=3000.0, recent_carbs_g=500.0)
        assert abs(small.estimated_depletion_hours - large.estimated_depletion_hours) < 6

    def test_shift_is_clamped_so_a_sparse_log_cannot_invent_a_timeline(self):
        absurd = fasting.personalise(weight_kg=50.0, maintenance_kcal=4000.0, recent_carbs_g=0.0)
        assert absurd.shift_hours == pytest.approx(-fasting.MAX_SHIFT_HOURS)
        assert any("capped" in note for note in absurd.notes)

    def test_no_weight_on_file_falls_back_to_the_standard_timeline(self):
        result = fasting.personalise(
            weight_kg=None, maintenance_kcal=2200.0, recent_carbs_g=300.0
        )
        assert result.shift_hours == 0.0
        assert any("weigh-in" in note for note in result.notes)

    def test_no_food_logged_assumes_a_normal_day_rather_than_an_empty_tank(self):
        """Missing evidence is not evidence of zero carbs.

        Treating an empty log as a zero-carb day would promise ketosis hours
        early to anyone who simply had not logged.
        """
        result = fasting.personalise(**BASE, recent_carbs_g=None)
        assert result.fill_fraction == pytest.approx(1.0)
        assert any("No food logged" in note for note in result.notes)

    def test_explanation_names_its_inputs(self):
        result = fasting.personalise(**BASE, recent_carbs_g=120.0, exercise_kcal=400.0)
        assert result.how_calculated
        assert "your weight" in result.inputs_used
        assert "the carbs in your last meals" in result.inputs_used
        assert "your recent training" in result.inputs_used


class TestStages:
    def test_the_timeline_is_ordered_and_named(self):
        stages = fasting.build_stages(elapsed_hours=0.0, shift_hours=0.0, started_at=None)
        keys = [s.spec.key for s in stages]
        assert keys == ["fed", "glycogen", "fat_burning", "ketosis", "deep_ketosis", "deep_repair", "extended"]
        for stage in stages:
            assert stage.spec.label and stage.spec.summary and stage.spec.detail

    def test_the_fed_window_never_shrinks_with_glycogen(self):
        """Regression: a low-carb day once produced a 30-minute "Fed" stage.

        How long digestion takes is a property of the meal, not of how full the
        liver is. Only the fuel-driven boundaries may move.
        """
        for shift in (-6.0, -3.0, 0.0, 3.0, 6.0):
            stages = fasting.build_stages(elapsed_hours=0.0, shift_hours=shift, started_at=None)
            fed = stages[0]
            assert fed.end_hours == pytest.approx(4.0), f"fed window moved at shift {shift}"

    def test_a_depleted_day_still_leaves_a_credible_timeline(self):
        """Regression: the fill floor was applied before training was subtracted.

        Both reductions then compounded, and a low-carb day with one hard
        session estimated under two hours of fuel — which would have put ketosis
        before the user had finished digesting.
        """
        result = fasting.personalise(
            weight_kg=83.0, maintenance_kcal=2518.0, recent_carbs_g=46.0, exercise_kcal=436.0
        )
        assert result.estimated_depletion_hours >= 4.0
        assert result.fill_fraction >= fasting.MIN_FILL_FRACTION
        stages = fasting.build_stages(
            elapsed_hours=0.0, shift_hours=result.shift_hours, started_at=None
        )
        # Whatever the inputs, fat burning cannot precede the end of digestion.
        fat_burning = next(s for s in stages if s.spec.key == "fat_burning")
        assert fat_burning.start_hours >= 4.0

    def test_eating_more_carbs_than_the_liver_holds_buys_nothing(self):
        """The tank cannot overfill, so 600 g should not beat 300 g."""
        normal = fasting.personalise(**BASE, recent_carbs_g=300.0)
        huge = fasting.personalise(**BASE, recent_carbs_g=600.0)
        assert huge.estimated_depletion_hours == pytest.approx(
            normal.estimated_depletion_hours, abs=0.01
        )

    def test_boundaries_stay_monotonic_under_an_extreme_shift(self):
        """A large negative shift must not produce a stage of negative width."""
        stages = fasting.build_stages(elapsed_hours=0.0, shift_hours=-6.0, started_at=None)
        starts = [s.start_hours for s in stages]
        assert starts == sorted(starts)
        for stage in stages:
            if stage.end_hours is not None:
                assert stage.end_hours > stage.start_hours

    def test_only_one_stage_is_active(self):
        stages = fasting.build_stages(elapsed_hours=14.0, shift_hours=0.0, started_at=None)
        active = [s for s in stages if s.status == "active"]
        assert len(active) == 1
        assert active[0].spec.key == "fat_burning"

    def test_earlier_stages_are_done_and_later_ones_upcoming(self):
        stages = {
            s.spec.key: s.status
            for s in fasting.build_stages(elapsed_hours=20.0, shift_hours=0.0, started_at=None)
        }
        assert stages["fed"] == "done"
        assert stages["glycogen"] == "done"
        assert stages["fat_burning"] == "done"
        assert stages["ketosis"] == "active"
        assert stages["deep_ketosis"] == "upcoming"

    def test_progress_within_the_active_stage(self):
        # ketosis spans 16-24h unshifted; 20h is halfway.
        stages = fasting.build_stages(elapsed_hours=20.0, shift_hours=0.0, started_at=None)
        ketosis = next(s for s in stages if s.spec.key == "ketosis")
        assert ketosis.progress == pytest.approx(0.5, abs=0.01)

    def test_the_open_ended_final_stage_has_no_denominator(self):
        stages = fasting.build_stages(elapsed_hours=100.0, shift_hours=0.0, started_at=None)
        last = stages[-1]
        assert last.end_hours is None
        assert last.status == "active"
        assert last.progress == 1.0

    def test_a_low_carb_day_actually_moves_ketosis_earlier(self):
        """The point of the whole exercise, asserted end to end."""
        fed = state(recent_carbs_g=300.0)
        depleted = state(recent_carbs_g=30.0)
        fed_ketosis = next(s for s in fed.stages if s.spec.key == "ketosis").start_hours
        low_ketosis = next(s for s in depleted.stages if s.spec.key == "ketosis").start_hours
        assert low_ketosis < fed_ketosis - 2

    def test_reached_at_is_a_real_timestamp_once_passed(self):
        result = state(session=session(started_hours_ago=20.0))
        ketosis = next(s for s in result.stages if s.spec.key == "ketosis")
        assert ketosis.reached_at is not None
        upcoming = next(s for s in result.stages if s.status == "upcoming")
        assert upcoming.reached_at is None


class TestEvaluate:
    def test_no_session_still_returns_the_timeline_that_would_apply(self):
        """So the page can show what a fast would look like before committing."""
        result = state(session=None)
        assert result.active is False
        assert result.elapsed_hours == 0.0
        assert result.stages
        assert result.personalisation is not None
        assert all(s.status == "upcoming" for s in result.stages)

    def test_an_open_fast_measures_from_the_start(self):
        result = state(session=session(started_hours_ago=10.0, target=16.0))
        assert result.active is True
        assert result.elapsed_hours == pytest.approx(10.0, abs=0.01)
        assert result.remaining_hours == pytest.approx(6.0, abs=0.01)
        assert result.progress == pytest.approx(10 / 16, abs=0.01)
        assert result.target_reached is False

    def test_a_closed_fast_freezes_at_its_end(self):
        """Elapsed must stop growing once the fast is over."""
        result = state(session=session(started_hours_ago=20.0, ended_hours_ago=4.0))
        assert result.active is False
        assert result.elapsed_hours == pytest.approx(16.0, abs=0.01)

    def test_passing_the_target_caps_progress_and_reports_it(self):
        result = state(session=session(started_hours_ago=19.0, target=16.0))
        assert result.target_reached is True
        assert result.progress == 1.0
        assert result.remaining_hours == 0.0

    def test_next_stage_and_time_until_it(self):
        result = state(session=session(started_hours_ago=10.0), recent_carbs_g=300.0)
        assert result.next_stage_key is not None
        assert result.hours_to_next_stage is not None
        assert result.hours_to_next_stage >= 0

    def test_a_long_fast_carries_a_safety_note(self):
        short = state(session=session(started_hours_ago=10.0, target=16.0))
        assert short.caution is None
        long = state(session=session(started_hours_ago=30.0, target=36.0))
        assert long.caution is not None
        assert "doctor" in long.caution

    def test_an_ambitious_target_warns_before_it_is_reached(self):
        result = state(session=session(started_hours_ago=1.0, target=48.0))
        assert result.caution is not None

    def test_serialises_for_the_api(self):
        payload = state(session=session(started_hours_ago=5.0)).to_dict()
        assert set(payload) == {
            "active",
            "session_id",
            "started_at",
            "ended_at",
            "target_hours",
            "elapsed_hours",
            "remaining_hours",
            "progress",
            "target_reached",
            "current_stage_key",
            "next_stage_key",
            "hours_to_next_stage",
            "stages",
            "personalisation",
            "caution",
        }
        assert payload["stages"][0].keys() == {
            "key",
            "label",
            "summary",
            "detail",
            "start_hours",
            "end_hours",
            "status",
            "progress",
            "reached_at",
        }
        assert payload["personalisation"]["how_calculated"]

    def test_naive_and_zulu_timestamps_are_both_accepted(self):
        zulu = {"id": "z", "started_at": "2026-08-29T02:00:00Z", "target_hours": 16}
        naive = {"id": "n", "started_at": "2026-08-29T02:00:00", "target_hours": 16}
        for row in (zulu, naive):
            result = state(session=row)
            assert result.elapsed_hours == pytest.approx(10.0, abs=0.01)


class TestHistorySummary:
    def test_open_fasts_are_excluded(self):
        """An open fast has no duration, and counting it would drag the average."""
        rows = [
            session(started_hours_ago=40, ended_hours_ago=24, target=16),  # 16h
            session(started_hours_ago=5),  # still running
        ]
        summary = fasting.summarise_history(rows)
        assert summary["sessions"] == 1
        assert summary["average_hours"] == pytest.approx(16.0, abs=0.01)

    def test_longest_average_and_total(self):
        rows = [
            session(started_hours_ago=100, ended_hours_ago=88, target=12),  # 12h
            session(started_hours_ago=60, ended_hours_ago=40, target=16),  # 20h
        ]
        summary = fasting.summarise_history(rows)
        assert summary["sessions"] == 2
        assert summary["longest_hours"] == pytest.approx(20.0, abs=0.01)
        assert summary["average_hours"] == pytest.approx(16.0, abs=0.01)
        assert summary["total_hours"] == pytest.approx(32.0, abs=0.01)

    def test_counts_only_fasts_that_reached_their_target(self):
        rows = [
            session(started_hours_ago=100, ended_hours_ago=84, target=16),  # 16h, met
            session(started_hours_ago=60, ended_hours_ago=50, target=16),  # 10h, missed
        ]
        summary = fasting.summarise_history(rows)
        assert summary["completed_on_target"] == 1

    def test_no_history_degrades_rather_than_dividing_by_zero(self):
        summary = fasting.summarise_history([])
        assert summary["sessions"] == 0
        assert summary["longest_hours"] is None
        assert summary["average_hours"] is None
        assert summary["total_hours"] == 0.0



# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
class TestFastingEndpoints:
    """Wired-up behaviour. The fake database returns no fasting rows, so the
    "already running" and "stop" paths are driven by patching the lookup."""

    def test_current_with_no_fast_returns_the_prospective_timeline(self, client):
        body = client.get("/api/fasting/current").json()
        assert body["active"] is False
        assert body["session_id"] is None
        assert len(body["stages"]) == 7
        assert body["personalisation"]["how_calculated"]
        # The fixture logs carbs, so the estimate should be using them.
        assert body["personalisation"]["recent_carbs_g"] is not None

    def test_start_opens_a_session_and_returns_its_state(self, client):
        body = client.post("/api/fasting/start", json={"target_hours": 18}).json()
        assert body["session"]["target_hours"] == 18
        assert body["session"]["user_id"]
        assert body["state"]["active"] is True
        assert body["state"]["target_hours"] == 18

    def test_target_is_rounded_to_a_sensible_granularity(self, client):
        body = client.post("/api/fasting/start", json={"target_hours": 16.37}).json()
        assert body["session"]["target_hours"] == 16.25

    def test_target_hours_is_bounded(self, client):
        assert client.post("/api/fasting/start", json={"target_hours": 0}).status_code == 422
        assert client.post("/api/fasting/start", json={"target_hours": 400}).status_code == 422

    def test_a_backdated_start_is_accepted(self, client):
        """The common case: last ate at 8pm, opened the app in the morning."""
        from datetime import UTC, datetime, timedelta

        earlier = (datetime.now(UTC) - timedelta(hours=11)).isoformat()
        body = client.post(
            "/api/fasting/start", json={"target_hours": 16, "started_at": earlier}
        ).json()
        assert body["state"]["elapsed_hours"] == pytest.approx(11.0, abs=0.1)

    def test_a_start_in_the_future_is_clamped_to_now(self, client):
        """Otherwise elapsed time would be negative and the ring would run backwards."""
        from datetime import UTC, datetime, timedelta

        later = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
        body = client.post(
            "/api/fasting/start", json={"target_hours": 16, "started_at": later}
        ).json()
        assert body["state"]["elapsed_hours"] == pytest.approx(0.0, abs=0.05)

    def test_a_start_more_than_a_week_ago_is_rejected(self, client):
        from datetime import UTC, datetime, timedelta

        ancient = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        response = client.post(
            "/api/fasting/start", json={"target_hours": 16, "started_at": ancient}
        )
        assert response.status_code == 400

    def test_starting_a_second_fast_is_refused(self, client, monkeypatch):
        from app.routers import fasting as router_module

        async def already_open(ctx):
            return session(started_hours_ago=3.0)

        monkeypatch.setattr(router_module, "_open_session", already_open)
        response = client.post("/api/fasting/start", json={"target_hours": 16})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "already_fasting"

    def test_stopping_when_nothing_is_running_is_refused(self, client):
        response = client.post("/api/fasting/stop", json={})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "not_fasting"

    def test_stop_reports_the_duration_actually_achieved(self, client, monkeypatch):
        from app.routers import fasting as router_module

        async def already_open(ctx):
            return session(started_hours_ago=17.0, target=16.0)

        monkeypatch.setattr(router_module, "_open_session", already_open)
        body = client.post("/api/fasting/stop", json={}).json()
        # The fixture session started 17h before the frozen NOW, but "now" at
        # request time is real, so only assert the shape and the ordering.
        assert body["hours"] > 0
        assert "met_target" in body
        assert body["state"]["active"] is False

    def test_history_returns_sessions_and_a_summary(self, client):
        body = client.get("/api/fasting/history").json()
        assert "sessions" in body
        assert set(body["summary"]) == {
            "sessions",
            "completed_on_target",
            "longest_hours",
            "average_hours",
            "total_hours",
        }

    def test_every_fasting_read_is_scoped_to_the_user(self, client, queries):
        """RLS is the backstop, not the only guard."""
        client.get("/api/fasting/current")
        fasting_reads = [pairs for table, pairs in queries if table == "fasting_sessions"]
        assert fasting_reads, "expected the handler to look for an open session"
        for pairs in fasting_reads:
            assert any(k == "user_id" for k, _ in pairs)
