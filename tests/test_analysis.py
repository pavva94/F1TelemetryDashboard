from __future__ import annotations

import os
from unittest.mock import patch

import numpy as np
import pandas as pd

from fastf1_lapdiff import LapData, LapMetadata, align_laps, analyze_laps
from fastf1_lapdiff.dashboard import build_dashboard_payload
from fastf1_lapdiff.fastf1_loader import _race_insights, _session_entries_from_laps, order_event_sessions, session_summary
from fastf1_lapdiff.web import _allowed_origins, create_app


def _lap(delay_exit: bool = False, drs: int = 1, lap_time: float = 90.0) -> pd.DataFrame:
    distance = np.linspace(0, 1000, 240)
    speed = 285 - 140 * np.exp(-((distance - 500) / 90) ** 2)
    throttle = np.where(distance < 430, 100, np.where(distance < 610, 0, 100))
    brake = (distance > 420) & (distance < 520)
    gear = np.where(distance < 480, 7, np.where(distance < 620, 3, 6))
    rpm = 8500 + speed * 25
    x = distance
    y = 80 * np.sin(distance / 180)
    if delay_exit:
        speed = speed - np.where((distance > 500) & (distance < 760), 9, 0)
        throttle = np.where((distance > 610) & (distance < 660), 35, throttle)
        throttle = np.where((distance >= 660) & (distance < 700), 0, throttle)
        throttle = np.where((distance >= 700) & (distance < 760), 60, throttle)
        y = y + np.where((distance > 500) & (distance < 650), 4, 0)
        time_seconds = distance / 72 + np.where(distance > 610, 0.16, 0)
    else:
        time_seconds = distance / 72
    return pd.DataFrame(
        {
            "Distance": distance,
            "Time": pd.to_timedelta(time_seconds, unit="s"),
            "Speed": speed,
            "Throttle": throttle,
            "Brake": brake,
            "nGear": gear,
            "RPM": rpm,
            "DRS": drs,
            "X": x,
            "Y": y,
            "Z": 0,
        }
    )


def _data(delay_exit: bool = False, drs: int = 1, lap_time: float = 90.0) -> LapData:
    return LapData(
        metadata=LapMetadata(
            driver="VER",
            lap_number=12 if delay_exit else 10,
            lap_time_seconds=lap_time,
            sector_times_seconds=(30.0, 30.0 if not delay_exit else 30.2, 30.0),
            compound="SOFT",
            tyre_life=3 if not delay_exit else 7,
            track_status="1",
            is_accurate=True,
            deleted=False,
        ),
        telemetry=_lap(delay_exit=delay_exit, drs=drs, lap_time=lap_time),
    )


def test_align_laps_computes_delta_and_differences() -> None:
    aligned = align_laps(_lap(), _lap(delay_exit=True), samples=200)

    assert {"delta_time", "speed_diff", "throttle_diff", "line_deviation", "accel_diff"}.issubset(aligned.columns)
    assert aligned["delta_time"].iloc[-1] > aligned["delta_time"].iloc[0]
    assert aligned["speed_diff"].min() < -5


def test_analyze_laps_detects_exit_loss_and_heuristic_limits() -> None:
    report = analyze_laps(_data(), _data(delay_exit=True, lap_time=90.18), {"TrackTemp": 34.0})
    types = {d.difference_type for d in report.detections}

    assert report.total_delta_seconds is not None
    assert abs(report.total_delta_seconds - 0.18) < 1e-9
    assert "Delayed full throttle" in types or "Throttle hesitation" in types
    assert "Lower exit speed" in types
    assert any(d.evidence_kind == "heuristic" for d in report.detections)
    assert "Tyre wear percentage" in " ".join(report.tyre_context)


def test_analyze_laps_flags_drs_difference() -> None:
    report = analyze_laps(_data(drs=1), _data(drs=0, lap_time=90.05))
    assert any(d.difference_type == "DRS difference" for d in report.detections)


def test_dashboard_payload_contains_report_sections_and_traces() -> None:
    payload = build_dashboard_payload(_data(), _data(delay_exit=True, lap_time=90.18), {"TrackTemp": 34.0})

    assert payload["report"]["total_delta_seconds"] is not None
    assert payload["sections"]
    assert payload["section_metrics"]
    assert any("VER L12 gains" in metric["note"] or "VER L10 and VER L12" in metric["note"] for metric in payload["section_metrics"])
    assert "straight_time_delta_seconds" in payload["performance_profile"]
    assert payload["performance_profile"]["inference_notes"]
    assert "direct" in payload["data_scope"]
    assert "heuristic" in payload["data_scope"]
    assert payload["telemetry"]["Distance"]
    assert payload["telemetry"]["delta_time"]
    assert len(payload["telemetry"]["Distance"]) == len(payload["telemetry"]["delta_time"])


def test_race_insights_summarize_pace_sectors_tyres_and_pits() -> None:
    laps = pd.DataFrame(
        [
            {
                "Driver": "VER",
                "Team": "Red Bull Racing",
                "LapNumber": 1,
                "LapTime": pd.to_timedelta(90.0, unit="s"),
                "Sector1Time": pd.to_timedelta(28.0, unit="s"),
                "Sector2Time": pd.to_timedelta(31.0, unit="s"),
                "Sector3Time": pd.to_timedelta(31.0, unit="s"),
                "Compound": "MEDIUM",
                "TyreLife": 1,
                "Stint": 1,
                "PitInTime": pd.NaT,
                "PitOutTime": pd.NaT,
                "IsAccurate": True,
            },
            {
                "Driver": "VER",
                "Team": "Red Bull Racing",
                "LapNumber": 2,
                "LapTime": pd.to_timedelta(91.0, unit="s"),
                "Sector1Time": pd.to_timedelta(28.5, unit="s"),
                "Sector2Time": pd.to_timedelta(31.5, unit="s"),
                "Sector3Time": pd.to_timedelta(31.0, unit="s"),
                "Compound": "MEDIUM",
                "TyreLife": 2,
                "Stint": 1,
                "PitInTime": pd.to_timedelta(180.0, unit="s"),
                "PitOutTime": pd.NaT,
                "IsAccurate": True,
            },
            {
                "Driver": "VER",
                "Team": "Red Bull Racing",
                "LapNumber": 3,
                "LapTime": pd.to_timedelta(89.8, unit="s"),
                "Sector1Time": pd.to_timedelta(27.9, unit="s"),
                "Sector2Time": pd.to_timedelta(30.9, unit="s"),
                "Sector3Time": pd.to_timedelta(31.0, unit="s"),
                "Compound": "SOFT",
                "TyreLife": 1,
                "Stint": 2,
                "PitInTime": pd.NaT,
                "PitOutTime": pd.to_timedelta(204.0, unit="s"),
                "IsAccurate": True,
            },
            {
                "Driver": "LEC",
                "Team": "Ferrari",
                "LapNumber": 1,
                "LapTime": pd.to_timedelta(90.5, unit="s"),
                "Sector1Time": pd.to_timedelta(28.2, unit="s"),
                "Sector2Time": pd.to_timedelta(30.7, unit="s"),
                "Sector3Time": pd.to_timedelta(31.6, unit="s"),
                "Compound": "MEDIUM",
                "TyreLife": 1,
                "Stint": 1,
                "PitInTime": pd.NaT,
                "PitOutTime": pd.NaT,
                "IsAccurate": True,
            },
        ]
    )

    insights = _race_insights(laps)

    assert insights["driverPace"][0]["driver"] == "VER"
    assert insights["fastestSectors"]["sector2"][0]["driver"] == "LEC"
    assert insights["teamPace"][0]["team"] == "Red Bull Racing"
    assert {item["compound"] for item in insights["tyreCompounds"]} == {"MEDIUM"}
    assert insights["pitStops"][0]["driver"] == "VER"
    assert insights["pitStops"][0]["pitLaneTime"] == 24.0
    assert insights["notes"]


def test_session_order_supports_standard_sprint_and_legacy_names() -> None:
    standard = [{"name": name} for name in ["Practice 2", "Race", "Practice 1", "Qualifying", "Practice 3"]]
    assert [item["name"] for item in order_event_sessions(standard)] == ["Race", "Qualifying", "Practice 3", "Practice 2", "Practice 1"]

    sprint = [{"name": name} for name in ["Sprint Shootout", "Practice 1", "Sprint", "Qualifying", "Race"]]
    assert [item["name"] for item in order_event_sessions(sprint)] == ["Race", "Qualifying", "Sprint", "Sprint Shootout", "Practice 1"]


def test_session_summary_marks_empty_loaded_session_as_no_data() -> None:
    class EmptySession:
        laps = pd.DataFrame()
        results = pd.DataFrame()
        event = None

    with patch("fastf1_lapdiff.fastf1_loader.load_fastf1_session", lambda *args: EmptySession()):
        summary = session_summary(2026, "Example Grand Prix", "Race")

    assert summary["status"] == "no_data_yet"
    assert summary["session"] == "Race"
    assert summary["standings"] == []
    assert summary["raceInsights"]["driverPace"] == []
    assert summary["drivers"] == []


def test_session_summary_entries_can_reuse_loaded_laps() -> None:
    laps = pd.DataFrame(
        [
            {"Driver": "VER", "Team": "Red Bull Racing", "LapNumber": 10, "LapTime": pd.to_timedelta(90.0, unit="s"), "IsAccurate": True},
            {"Driver": "LEC", "Team": "Ferrari", "LapNumber": 11, "LapTime": pd.to_timedelta(90.2, unit="s"), "IsAccurate": True},
        ]
    )

    entries = _session_entries_from_laps(laps)

    assert [driver["code"] for driver in entries["drivers"]] == ["LEC", "VER"]
    assert entries["teams"] == ["Ferrari", "Red Bull Racing"]


def test_allowed_origins_parses_split_frontend_hosts() -> None:
    previous = os.environ.get("FASTF1_ALLOWED_ORIGINS")
    try:
        os.environ["FASTF1_ALLOWED_ORIGINS"] = "https://dashboard.example.com/, https://preview.example.com"
        assert _allowed_origins() == [
            "https://dashboard.example.com",
            "https://preview.example.com",
        ]
    finally:
        if previous is None:
            os.environ.pop("FASTF1_ALLOWED_ORIGINS", None)
        else:
            os.environ["FASTF1_ALLOWED_ORIGINS"] = previous


def test_public_api_allows_split_frontend_origins() -> None:
    with patch.dict(os.environ, {"FASTF1_ALLOWED_ORIGINS": "*"}):
        app = create_app()

    cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == ["*"]
    assert cors.kwargs["allow_methods"] == ["GET"]
