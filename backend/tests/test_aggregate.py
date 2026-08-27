from datetime import date

from app.services import aggregate


def test_day_bounds_are_computed_in_the_users_timezone():
    tz = aggregate.resolve_tz("Asia/Kolkata")  # UTC+5:30
    start, end = aggregate.day_bounds_utc(date(2026, 8, 27), tz)
    assert start.startswith("2026-08-26T18:30")
    assert end.startswith("2026-08-27T18:30")


def test_unknown_timezone_falls_back_to_utc_instead_of_crashing():
    tz = aggregate.resolve_tz("Mars/Olympus_Mons")
    assert str(tz) == "UTC"


def test_late_evening_entry_belongs_to_the_local_day():
    tz = aggregate.resolve_tz("Asia/Kolkata")
    # 20:00 UTC on the 26th is 01:30 on the 27th in Kolkata.
    row = {"logged_at": "2026-08-26T20:00:00+00:00"}
    assert aggregate.local_day_of(row, tz) == date(2026, 8, 27)


def test_timestamp_parsing_handles_zulu_and_long_fractions():
    assert aggregate.parse_ts("2026-08-27T10:15:30Z") is not None
    assert aggregate.parse_ts("2026-08-27T10:15:30.123456789+00:00") is not None
    assert aggregate.parse_ts("not a date") is None
    assert aggregate.parse_ts(None) is None


def test_timestamp_parsing_handles_every_fractional_precision():
    """Postgres trims trailing zeros, so 3-5 fractional digits are routine.

    Regression: an earlier normalisation scraped digits out of the string and ate
    part of the UTC offset, so these lengths failed to parse. Callers then fell
    back to the UTC date and mis-bucketed entries by up to a day — the AI coach
    reported 0 kcal for a day that had food logged.
    """
    for digits in range(0, 10):
        fraction = ("." + "1" * digits) if digits else ""
        for offset in ("+00:00", "Z", "+05:30", "-07:00", ""):
            raw = f"2026-08-27T19:32:32{fraction}{offset}"
            assert aggregate.parse_ts(raw) is not None, raw


def test_five_digit_fraction_buckets_into_the_correct_local_day():
    # 19:32 UTC is 01:02 the next day in Asia/Kolkata — the exact case that broke.
    tz = aggregate.resolve_tz("Asia/Kolkata")
    row = {"logged_at": "2026-08-27T19:32:32.11579+00:00"}
    assert aggregate.local_day_of(row, tz) == date(2026, 8, 28)

    # And it must still land on the UTC day when the profile is on UTC.
    assert aggregate.local_day_of(row, aggregate.resolve_tz("UTC")) == date(2026, 8, 27)


def test_odd_precision_entries_reach_the_daily_series():
    """daily_series feeds the forecast, so mis-parsing here skews projections."""
    tz = aggregate.resolve_tz("Asia/Kolkata")
    series = aggregate.daily_series(
        food_rows=[
            {"logged_at": "2026-08-27T19:32:32.11579+00:00", "calories": 263},
            {"logged_at": "2026-08-27T05:10:00.123+00:00", "calories": 400},
        ],
        workout_rows=[],
        tz=tz,
        start=date(2026, 8, 27),
        end=date(2026, 8, 28),
    )
    by_day = {d.day.isoformat(): d for d in series}
    assert by_day["2026-08-28"].calories_in == 263  # 01:02 IST on the 28th
    assert by_day["2026-08-27"].calories_in == 400  # 10:40 IST on the 27th
    assert all(d.logged for d in series)


def test_daily_series_zero_fills_missing_days():
    tz = aggregate.resolve_tz("UTC")
    series = aggregate.daily_series(
        food_rows=[{"logged_at": "2026-08-27T12:00:00Z", "calories": 500}],
        workout_rows=[{"logged_at": "2026-08-25T12:00:00Z", "calories_burned": 200}],
        tz=tz,
        start=date(2026, 8, 25),
        end=date(2026, 8, 27),
    )
    assert [d.day.isoformat() for d in series] == ["2026-08-25", "2026-08-26", "2026-08-27"]
    assert series[0].calories_out == 200
    assert series[0].logged is False
    assert series[2].calories_in == 500
    assert series[2].logged is True


def test_totals_sum_calories_and_macros_ignoring_nulls():
    rows = [
        {"calories": 300, "protein_g": 20, "carbs_g": None, "fat_g": 10, "fiber_g": 2},
        {"calories": 200.5, "protein_g": None, "carbs_g": 30, "fat_g": 5, "fiber_g": None},
    ]
    totals = aggregate.totals(rows)
    assert totals["calories"] == 500.5
    assert totals["protein_g"] == 20
    assert totals["carbs_g"] == 30


def test_workouts_group_by_hour_day_and_week():
    tz = aggregate.resolve_tz("UTC")
    rows = [
        {"logged_at": "2026-08-27T06:30:00Z", "calories_burned": 200, "duration_min": 30},
        {"logged_at": "2026-08-27T06:45:00Z", "calories_burned": 100, "duration_min": 15},
        {"logged_at": "2026-08-20T18:00:00Z", "calories_burned": 400, "duration_min": 60},
    ]

    hourly = aggregate.group_workouts(workout_rows=rows, tz=tz, bucket="hour")
    assert {"bucket": "2026-08-27T06:00", "calories_burned": 300.0, "duration_min": 45, "sessions": 2} in hourly

    daily = aggregate.group_workouts(workout_rows=rows, tz=tz, bucket="day")
    assert len(daily) == 2

    weekly = aggregate.group_workouts(workout_rows=rows, tz=tz, bucket="week")
    assert [g["bucket"] for g in weekly] == ["2026-W34", "2026-W35"]


def test_weight_points_are_sorted_and_reject_bad_rows():
    points = aggregate.weight_points(
        [
            {"logged_at": "2026-08-27", "weight_kg": 80},
            {"logged_at": "2026-08-25", "weight_kg": 81},
            {"logged_at": "2026-08-26", "weight_kg": None},
            {"logged_at": None, "weight_kg": 79},
        ]
    )
    assert [(p.day.isoformat(), p.weight_kg) for p in points] == [
        ("2026-08-25", 81.0),
        ("2026-08-27", 80.0),
    ]
