from __future__ import annotations

import math

import pandas as pd

from fastf1_lapdiff.season_analytics import (
    aggregate_records,
    backtest_predictions,
    classify_reliability,
    clean_race_laps,
    detect_change_point,
    development_regression,
    early_recent,
    expected_points,
    fit_degradation,
    percentage_deficit,
    points_conversion,
    prediction_snapshot,
    reject_outliers,
    rolling_median,
)
from fastf1_lapdiff.web import create_app


def test_percentage_deficit_and_zero_reference() -> None:
    assert math.isclose(percentage_deficit(91.0, 90.0), 1.1111111111111112)
    assert percentage_deficit(90.0, 0) is None
    assert percentage_deficit(None, 90.0) is None


def test_rolling_median_uses_only_available_values() -> None:
    assert rolling_median([3.0, None, 1.0, 8.0], 3) == [3.0, 3.0, 2.0, 4.5]
    assert rolling_median([3.0, 2.0], 1) == [3.0, 2.0]


def test_mad_outlier_rejection() -> None:
    values, excluded = reject_outliers([90.0, 90.1, 89.9, 90.05, 130.0])
    assert excluded == 1
    assert 130.0 not in values


def test_clean_race_laps_excludes_invalid_pit_and_neutralised_laps() -> None:
    laps = pd.DataFrame(
        [
            {"LapTime": pd.to_timedelta(90, unit="s"), "Deleted": False, "IsAccurate": True, "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "TrackStatus": "1"},
            {"LapTime": pd.to_timedelta(91, unit="s"), "Deleted": True, "IsAccurate": True, "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "TrackStatus": "1"},
            {"LapTime": pd.to_timedelta(92, unit="s"), "Deleted": False, "IsAccurate": True, "PitInTime": pd.to_timedelta(10, unit="s"), "PitOutTime": pd.NaT, "TrackStatus": "1"},
            {"LapTime": pd.to_timedelta(93, unit="s"), "Deleted": False, "IsAccurate": True, "PitInTime": pd.NaT, "PitOutTime": pd.NaT, "TrackStatus": "4"},
        ]
    )
    clean, exclusions = clean_race_laps(laps)
    assert len(clean) == 1
    assert exclusions["deleted"] == 1
    assert exclusions["pit"] == 1
    assert exclusions["neutralised"] == 1


def test_development_early_recent_and_change_point() -> None:
    improving = [{"round": round_number, "deficit": 1.2 - round_number * 0.1} for round_number in range(1, 11)]
    model = development_regression(improving)
    comparison = early_recent(improving)
    assert math.isclose(model["rate"], -0.1, abs_tol=1e-9)
    assert model["r2"] > 0.99
    assert comparison["change"] < 0

    stepped = [{"round": round_number, "deficit": 1.0 if round_number < 6 else 0.3} for round_number in range(1, 11)]
    change = detect_change_point(stepped)
    assert change is not None
    assert change["round"] == 6
    assert change["direction"] == "improvement"


def test_reliability_and_points_conversion_are_transparent() -> None:
    assert classify_reliability("Engine") == "mechanical"
    assert classify_reliability("Collision") == "incident"
    assert classify_reliability("Disqualified") == "dsq"
    assert classify_reliability("+1 Lap") == "classified"
    assert expected_points(2, 0.5) == 9.0
    assert points_conversion(18, 9) == 2.0
    assert points_conversion(0, 0) is None


def test_degradation_model_recovers_tyre_age_effect() -> None:
    laps = pd.DataFrame(
        [
            {
                "LapNumber": lap,
                "TyreLife": lap,
                "LapTime": pd.to_timedelta(90 + 0.08 * lap + 0.02 * lap, unit="s"),
                "Deleted": False,
                "IsAccurate": True,
                "PitInTime": pd.NaT,
                "PitOutTime": pd.NaT,
                "TrackStatus": "1",
            }
            for lap in range(1, 15)
        ]
    )
    model = fit_degradation(laps)
    assert model["rate"] is not None
    assert model["laps"] == 14
    assert model["kind"] == "adjusted estimate"


def test_historical_predictions_never_use_target_or_future_rounds() -> None:
    series = {
        "Alpha": [{"round": round_number, "deficit": 0.2 + round_number * 0.01} for round_number in range(1, 8)],
        "Beta": [{"round": round_number, "deficit": 0.5 - round_number * 0.01} for round_number in range(1, 8)],
    }
    prediction = prediction_snapshot(series, 6)
    assert all(max(team["roundsUsed"]) < 6 for team in prediction["teams"])

    backtest = backtest_predictions(series)
    assert backtest["cases"]
    assert all(max(case["roundsUsed"]) < case["round"] for case in backtest["cases"])
    assert backtest["meanAbsoluteRankError"] is not None


def test_multi_event_aggregation_builds_all_major_sections() -> None:
    events = [
        {"round": 1, "name": "Bahrain Grand Prix", "status": "completed", "weather": "dry"},
        {"round": 2, "name": "Saudi Arabian Grand Prix", "status": "completed", "weather": "dry"},
        {"round": 3, "name": "Australian Grand Prix", "status": "completed", "weather": "wet"},
    ]
    records = []
    for round_number in range(1, 4):
        for driver, team, offset in (("AAA", "Alpha", 0.0), ("AAB", "Alpha", 0.1), ("BBB", "Beta", 0.5), ("BBC", "Beta", 0.6)):
            records.append(
                {
                    "round": round_number,
                    "event": events[round_number - 1]["name"],
                    "driver": driver,
                    "team": team,
                    "points": 25 if driver == "AAA" else 10 if driver == "BBB" else 0,
                    "sprintPoints": 0,
                    "finish": 1 if driver == "AAA" else 4,
                    "status": "Finished",
                    "reliability": "classified",
                    "qualifyingDeficit": offset,
                    "racePaceDeficit": offset + 0.05,
                    "adjustedRacePaceDeficit": offset + 0.03,
                    "cleanLaps": 20,
                    "excludedLaps": 2,
                    "quality": {"confidence": "high"},
                    "stints": [],
                    "pitStops": [],
                    "degradation": None,
                }
            )

    payload = aggregate_records(2024, records, events)

    assert payload["championship"]["drivers"]
    assert payload["performance"]["teamQualifying"]["Alpha"]
    assert payload["reliability"]["teams"]
    assert payload["conversion"]["teams"]
    assert payload["momentum"]
    assert payload["trackAnalysis"]["metadataCoverage"] == 3
    assert payload["methodology"]["prediction"]


def test_season_api_and_direct_page_routes_are_registered() -> None:
    paths = {route.path for route in create_app().routes}
    assert "/api/season-analysis" in paths
    assert "/season" in paths
    assert "/race" in paths
