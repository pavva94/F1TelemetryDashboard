from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

import numpy as np
import pandas as pd

from .models import PerformanceProfile, Section, SectionMetrics


STRAIGHT_TYPES = {"Straight", "DRS straight"}
BRAKING_TYPES = {"Heavy braking zone", "Medium braking zone"}
CORNER_TYPES = {"Low-speed corner", "Medium-speed corner", "High-speed corner"}


def build_section_metrics(aligned: pd.DataFrame, sections: list[Section], reference_label: str = "Reference", compared_label: str = "Compared") -> list[SectionMetrics]:
    metrics: list[SectionMetrics] = []
    for section in sections:
        part = _slice(aligned, section)
        if part.empty:
            continue
        metrics.append(_section_metrics(part, section, reference_label, compared_label))
    return metrics


def build_performance_profile(section_metrics: list[SectionMetrics]) -> PerformanceProfile:
    straight = _sum_delta(section_metrics, STRAIGHT_TYPES)
    braking = _sum_delta(section_metrics, BRAKING_TYPES)
    low = _sum_delta(section_metrics, {"Low-speed corner"})
    medium = _sum_delta(section_metrics, {"Medium-speed corner"})
    high = _sum_delta(section_metrics, {"High-speed corner"})
    drs = _sum_delta(section_metrics, {"DRS straight"})
    corner_exit = _average([m.exit_speed_delta_kmh for m in section_metrics if m.section_type in CORNER_TYPES])
    full_throttle_delta = _average([m.full_throttle_delta_m for m in section_metrics if m.section_type in CORNER_TYPES])
    drs_distance_delta = _average([m.drs_active_distance_delta_m for m in section_metrics if m.section_type == "DRS straight"]) or 0.0

    profile = PerformanceProfile(
        straight_time_delta_seconds=straight,
        braking_time_delta_seconds=braking,
        low_speed_corner_delta_seconds=low,
        medium_speed_corner_delta_seconds=medium,
        high_speed_corner_delta_seconds=high,
        drs_time_delta_seconds=drs,
        average_corner_exit_speed_delta_kmh=corner_exit,
        average_full_throttle_delta_m=full_throttle_delta,
        average_drs_distance_delta_m=drs_distance_delta,
    )
    profile.stronger_indicators = _indicators(section_metrics, gains=True)
    profile.weaker_indicators = _indicators(section_metrics, gains=False)
    profile.inference_notes = _inference_notes(profile, section_metrics)
    return profile


def _section_metrics(part: pd.DataFrame, section: Section, reference_label: str, compared_label: str) -> SectionMetrics:
    ref_start_speed = _window_mean(part, 0.06, "ref_Speed")
    cmp_start_speed = _window_mean(part, 0.06, "cmp_Speed")
    ref_end_speed = _window_mean(part, 0.94, "ref_Speed")
    cmp_end_speed = _window_mean(part, 0.94, "cmp_Speed")
    ref_speed_gain = ref_end_speed - ref_start_speed
    cmp_speed_gain = cmp_end_speed - cmp_start_speed
    brake_delta = _active_distance(part, "cmp_Brake", 0.5) - _active_distance(part, "ref_Brake", 0.5)
    drs_delta = _active_distance(part, "cmp_DRS", 0.5) - _active_distance(part, "ref_DRS", 0.5)
    time_delta = _local_delta(part)
    data_kind = "computed"
    confidence = _confidence(part, abs(time_delta), section)

    return SectionMetrics(
        label=section.label,
        section_type=section.section_type,
        start_distance=section.start_distance,
        end_distance=section.end_distance,
        length=section.length,
        time_delta_seconds=time_delta,
        average_speed_delta_kmh=_mean(part, "speed_diff"),
        minimum_speed_delta_kmh=float(part["cmp_Speed"].min() - part["ref_Speed"].min()),
        maximum_speed_delta_kmh=float(part["cmp_Speed"].max() - part["ref_Speed"].max()),
        entry_speed_delta_kmh=cmp_start_speed - ref_start_speed,
        exit_speed_delta_kmh=cmp_end_speed - ref_end_speed,
        reference_speed_gain_kmh=ref_speed_gain,
        compared_speed_gain_kmh=cmp_speed_gain,
        speed_gain_delta_kmh=cmp_speed_gain - ref_speed_gain,
        average_acceleration_delta_ms2=_mean(part, "accel_diff"),
        average_throttle_delta_pct=_mean(part, "throttle_diff"),
        full_throttle_delta_m=_full_throttle_delta(part),
        brake_active_distance_delta_m=brake_delta,
        drs_active_distance_delta_m=drs_delta,
        reference_gear_mode=_gear_mode(part, "ref_nGear"),
        compared_gear_mode=_gear_mode(part, "cmp_nGear"),
        average_rpm_delta=_mean(part, "rpm_diff"),
        average_line_deviation_m=_optional_mean(part, "line_deviation"),
        data_kind=data_kind,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        note=_section_note(section, time_delta, cmp_end_speed - ref_end_speed, drs_delta, brake_delta, reference_label, compared_label),
    )


def _slice(aligned: pd.DataFrame, section: Section) -> pd.DataFrame:
    return aligned[(aligned["Distance"] >= section.start_distance) & (aligned["Distance"] <= section.end_distance)]


def _local_delta(part: pd.DataFrame) -> float:
    return float(part["delta_time"].iloc[-1] - part["delta_time"].iloc[0])


def _condition_distance(part: pd.DataFrame, mask: pd.Series) -> float:
    if not bool(mask.any()):
        return 0.0
    distances = part["Distance"].to_numpy()
    step = float(np.nanmedian(np.diff(distances))) if len(distances) > 1 else 0.0
    return float(mask.sum() * step)


def _active_distance(part: pd.DataFrame, channel: str, threshold: float) -> float:
    return _condition_distance(part, part[channel] > threshold)


def _mean(part: pd.DataFrame, channel: str) -> float:
    value = float(pd.to_numeric(part[channel], errors="coerce").mean())
    return 0.0 if not math.isfinite(value) else value


def _optional_mean(part: pd.DataFrame, channel: str) -> float | None:
    if channel not in part.columns:
        return None
    value = _mean(part, channel)
    return value if math.isfinite(value) else None


def _window_mean(part: pd.DataFrame, fraction: float, channel: str) -> float:
    start = float(part["Distance"].iloc[0])
    end = float(part["Distance"].iloc[-1])
    center = start + (end - start) * fraction
    width = max(8.0, (end - start) * 0.06)
    window = part[(part["Distance"] >= center - width) & (part["Distance"] <= center + width)]
    return _mean(window if not window.empty else part, channel)


def _gear_mode(part: pd.DataFrame, channel: str) -> int | None:
    values = pd.to_numeric(part[channel], errors="coerce").dropna()
    if values.empty:
        return None
    rounded = np.rint(values.to_numpy()).astype(int)
    return int(Counter(rounded).most_common(1)[0][0])


def _confidence(part: pd.DataFrame, magnitude: float, section: Section) -> str:
    if len(part) < 25:
        return "Low"
    if section.length < 40:
        return "Low"
    if magnitude > 0.12:
        return "High"
    if magnitude > 0.045:
        return "Medium"
    return "Low"


def _section_note(section: Section, time_delta: float, exit_speed_delta: float, drs_delta: float, brake_delta: float, reference_label: str, compared_label: str) -> str:
    if time_delta > 0:
        loser = compared_label
        gainer = reference_label
    else:
        loser = reference_label
        gainer = compared_label

    if abs(time_delta) < 0.025:
        return f"Near-neutral time impact between {reference_label} and {compared_label}; use channel deltas as supporting context."
    outcome = f"{gainer} gains {abs(time_delta):.3f} s over {loser}"
    if section.section_type in STRAIGHT_TYPES:
        if abs(drs_delta) > 20:
            return f"{outcome} on a straight-like section with different DRS active distance."
        return f"{outcome} on a straight-like section; exit speed, DRS, tow, and deployment context can all contribute."
    if section.section_type in BRAKING_TYPES:
        if abs(brake_delta) > 12:
            return f"{outcome} in a braking zone with different brake-on distance."
        return f"{outcome} in a braking zone; FastF1 brake data is boolean only."
    if section.section_type in CORNER_TYPES:
        if abs(exit_speed_delta) > 4:
            return f"{outcome} in a corner section with a meaningful exit-speed delta."
        return f"{outcome} in a corner section; speed and throttle describe behavior, not steering balance."
    return f"{outcome} in this section."


def _sum_delta(metrics: Iterable[SectionMetrics], section_types: set[str]) -> float:
    return float(sum(item.time_delta_seconds for item in metrics if item.section_type in section_types))


def _average(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return None
    return float(sum(clean) / len(clean))


def _full_throttle_delta(part: pd.DataFrame) -> float | None:
    ref = _first_after_min_speed(part, "ref_Throttle", 90)
    cmp = _first_after_min_speed(part, "cmp_Throttle", 90)
    if ref is None or cmp is None:
        return None
    return cmp - ref


def _first_after_min_speed(part: pd.DataFrame, channel: str, threshold: float) -> float | None:
    min_index = int(np.nanargmin(np.minimum(part["ref_Speed"].to_numpy(), part["cmp_Speed"].to_numpy())))
    tail = part.iloc[min_index:]
    mask = tail[channel] >= threshold
    if not bool(mask.any()):
        return None
    return float(tail.loc[mask, "Distance"].iloc[0])


def _indicators(metrics: list[SectionMetrics], gains: bool) -> list[str]:
    ranked = sorted(metrics, key=lambda item: item.time_delta_seconds)
    selected = ranked[:4] if gains else list(reversed(ranked[-4:]))
    output: list[str] = []
    for item in selected:
        if gains and item.time_delta_seconds >= -0.03:
            continue
        if not gains and item.time_delta_seconds <= 0.03:
            continue
        direction = "gain" if item.time_delta_seconds < 0 else "loss"
        output.append(f"{item.section_type}: {direction} {item.time_delta_seconds:+.3f} s, exit {item.exit_speed_delta_kmh:+.1f} km/h")
    return output


def _inference_notes(profile: PerformanceProfile, metrics: list[SectionMetrics]) -> list[str]:
    notes = [
        "All profile items are derived from FastF1 speed, throttle, brake, gear, RPM, DRS, position, distance, and timing data.",
        "Straight-line indicators cannot isolate drag, power-unit deployment, wind, or tow without external data.",
        "Corner and traction-style indicators are heuristics because FastF1 does not provide steering, wheel speed, tyre state, or real G-force.",
    ]
    if profile.average_corner_exit_speed_delta_kmh is not None and abs(profile.average_corner_exit_speed_delta_kmh) > 3:
        notes.append(f"Average corner-exit speed delta is {profile.average_corner_exit_speed_delta_kmh:+.1f} km/h across detected corner sections.")
    if any(abs(item.drs_active_distance_delta_m) > 20 for item in metrics):
        notes.append("At least one DRS section has different active distance, so straight comparisons need DRS context.")
    return notes
