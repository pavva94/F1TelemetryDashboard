from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Section


def make_sections(aligned: pd.DataFrame, max_sections: int = 18) -> list[Section]:
    """Create approximate sections from braking zones and speed minima."""

    distances = aligned["Distance"].to_numpy()
    lap_length = float(distances[-1] - distances[0])
    window = max(60.0, lap_length / max_sections)
    seeds: list[float] = []

    brake = ((aligned["ref_Brake"] > 0.5) | (aligned["cmp_Brake"] > 0.5)).to_numpy()
    if brake.any():
        starts = np.flatnonzero(brake & ~np.r_[False, brake[:-1]])
        seeds.extend(float(distances[index]) for index in starts)

    speed = np.minimum(aligned["ref_Speed"].to_numpy(), aligned["cmp_Speed"].to_numpy())
    for index in range(2, len(speed) - 2):
        if speed[index] <= speed[index - 1] and speed[index] <= speed[index + 1] and speed[index] < np.nanpercentile(speed, 40):
            seeds.append(float(distances[index]))

    if not seeds:
        step = lap_length / max_sections
        return [
            Section(f"Section {i + 1}", float(distances[0] + i * step), float(min(distances[-1], distances[0] + (i + 1) * step)), "Straight")
            for i in range(max_sections)
        ]

    seeds = sorted(seeds)
    merged: list[float] = []
    for seed in seeds:
        if not merged or seed - merged[-1] > window * 0.75:
            merged.append(seed)

    boundaries = [float(distances[0])]
    for seed in merged:
        boundaries.append(max(float(distances[0]), seed - window * 0.45))
        boundaries.append(min(float(distances[-1]), seed + window * 0.75))
    boundaries.append(float(distances[-1]))
    boundaries = sorted(set(round(value, 3) for value in boundaries))

    sections: list[Section] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end - start < 25:
            continue
        part = aligned[(aligned["Distance"] >= start) & (aligned["Distance"] <= end)]
        if part.empty:
            continue
        brake_ratio = float(((part["ref_Brake"] > 0.5) | (part["cmp_Brake"] > 0.5)).mean())
        throttle_ratio = float(((part["ref_Throttle"] > 90) | (part["cmp_Throttle"] > 90)).mean())
        min_speed = float(min(part["ref_Speed"].min(), part["cmp_Speed"].min()))
        drs_ratio = float(((part["ref_DRS"] > 0) | (part["cmp_DRS"] > 0)).mean())
        section_type = _classify_section(brake_ratio, throttle_ratio, min_speed, drs_ratio)
        sections.append(Section(f"{section_type} {len(sections) + 1}", start, end, section_type))
    return sections[:max_sections]


def _classify_section(brake_ratio: float, throttle_ratio: float, min_speed: float, drs_ratio: float) -> str:
    if drs_ratio > 0.35 and throttle_ratio > 0.6:
        return "DRS straight"
    if brake_ratio > 0.45:
        return "Heavy braking zone"
    if brake_ratio > 0.2:
        return "Medium braking zone"
    if min_speed < 105:
        return "Low-speed corner"
    if min_speed < 175:
        return "Medium-speed corner"
    if throttle_ratio > 0.75:
        return "Straight"
    return "High-speed corner"

