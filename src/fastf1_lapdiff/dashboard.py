from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from .align import align_laps
from .detectors import analyze_laps
from .models import LapData
from .sections import make_sections


def build_dashboard_payload(reference: LapData, compared: LapData, weather_context: dict[str, Any] | None = None) -> dict[str, Any]:
    aligned = align_laps(reference.telemetry, compared.telemetry)
    report = analyze_laps(reference, compared, weather_context)
    sections = make_sections(aligned)

    return {
        "report": dataclasses.asdict(report),
        "sections": [dataclasses.asdict(section) for section in sections],
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

