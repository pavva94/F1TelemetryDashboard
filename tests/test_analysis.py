from __future__ import annotations

import numpy as np
import pandas as pd

from fastf1_lapdiff import LapData, LapMetadata, align_laps, analyze_laps
from fastf1_lapdiff.dashboard import build_dashboard_payload


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
    assert "straight_time_delta_seconds" in payload["performance_profile"]
    assert payload["performance_profile"]["inference_notes"]
    assert "direct" in payload["data_scope"]
    assert "heuristic" in payload["data_scope"]
    assert payload["telemetry"]["Distance"]
    assert payload["telemetry"]["delta_time"]
    assert len(payload["telemetry"]["Distance"]) == len(payload["telemetry"]["delta_time"])
