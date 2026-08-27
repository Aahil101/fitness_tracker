from app.services.met import (
    activity_catalog,
    estimate_calories_burned,
    resolve_met,
)


def test_known_activity_keys_resolve_to_their_met_value():
    assert resolve_met("running") == 9.8
    assert resolve_met("yoga") == 2.5
    assert resolve_met("cricket") == 4.8


def test_labels_and_free_text_still_resolve():
    assert resolve_met("Weight training (general)") == 5.0
    assert resolve_met("morning run") == 9.8
    assert resolve_met("jump rope") == 12.3


def test_unknown_activity_falls_back_to_a_neutral_met():
    assert resolve_met("interpretive dance battle") == 4.0
    assert resolve_met("") == 4.0


def test_burn_formula_is_met_times_weight_times_hours():
    # 9.8 MET * 80 kg * 0.5 h
    assert estimate_calories_burned("running", 30, 80, "moderate") == 392.0


def test_intensity_scales_the_estimate():
    light = estimate_calories_burned("cycling", 60, 70, "light")
    moderate = estimate_calories_burned("cycling", 60, 70, "moderate")
    vigorous = estimate_calories_burned("cycling", 60, 70, "vigorous")
    assert light < moderate < vigorous
    assert moderate == 560.0  # 8.0 * 70 * 1
    assert vigorous == 700.0


def test_zero_duration_burns_nothing():
    assert estimate_calories_burned("running", 0, 80) == 0.0


def test_catalog_is_complete_and_serialisable():
    catalog = activity_catalog()
    assert len(catalog) > 30
    assert all({"key", "label", "met", "category"} <= set(item) for item in catalog)
    assert len({item["key"] for item in catalog}) == len(catalog)
