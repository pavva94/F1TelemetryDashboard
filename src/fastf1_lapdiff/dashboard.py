from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from .align import align_laps
from .detectors import analyze_laps
from .metrics import build_performance_profile, build_section_metrics
from .models import LapData
from .sections import make_sections


def build_dashboard_payload(reference: LapData, compared: LapData, weather_context: dict[str, Any] | None = None) -> dict[str, Any]:
    aligned = align_laps(reference.telemetry, compared.telemetry)
    report = analyze_laps(reference, compared, weather_context)
    sections = make_sections(aligned)
    section_metrics = build_section_metrics(aligned, sections)
    performance_profile = build_performance_profile(section_metrics)

    return {
        "report": dataclasses.asdict(report),
        "sections": [dataclasses.asdict(section) for section in sections],
        "section_metrics": [dataclasses.asdict(section) for section in section_metrics],
        "performance_profile": dataclasses.asdict(performance_profile),
        "data_scope": {
            "direct": ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS", "X/Y/Z position", "Time", "Distance"],
            "derived": ["Delta time over distance", "approximate acceleration from speed/time", "active DRS/brake distance", "section speed gain", "line deviation"],
            "heuristic": ["traction-like exit behavior", "straight-line efficiency", "aero/platform indicators", "braking compromise indicators"],
            "excluded": ["steering angle", "brake pressure", "tyre pressure", "tyre temperature", "tyre wear percentage", "fuel level", "wheel speed", "real G-force", "yaw rate", "slip angle"],
        },
        "telemetry": _telemetry_payload(aligned),
    }


def _telemetry_payload(aligned: Any, max_points: int = 420) -> dict[str, list[float | None]]:
    if len(aligned) > max_points:
        indices = np.linspace(0, len(aligned) - 1, max_points).astype(int)
        data = aligned.iloc[indices]
    else:
        data = aligned

    channels = [
        "Distance",
        "delta_time",
        "ref_Speed",
        "cmp_Speed",
        "ref_Throttle",
        "cmp_Throttle",
        "ref_Brake",
        "cmp_Brake",
        "ref_nGear",
        "cmp_nGear",
        "ref_RPM",
        "cmp_RPM",
        "ref_DRS",
        "cmp_DRS",
        "ref_X",
        "ref_Y",
        "cmp_X",
        "cmp_Y",
        "line_deviation",
        "accel_diff",
    ]
    return {channel: [_number(value) for value in data[channel].tolist()] for channel in channels if channel in data.columns}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return round(numeric, 5)
