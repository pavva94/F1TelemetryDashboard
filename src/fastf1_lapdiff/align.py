from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_CHANNELS = ["Speed", "Throttle", "Brake", "nGear", "RPM", "DRS", "Distance"]
OPTIONAL_CHANNELS = ["X", "Y", "Z"]


def _time_seconds(series: pd.Series) -> np.ndarray:
    if np.issubdtype(series.dtype, np.timedelta64):
        return series.dt.total_seconds().to_numpy(dtype=float)
    if np.issubdtype(series.dtype, np.datetime64):
        base = series.iloc[0]
        return (series - base).dt.total_seconds().to_numpy(dtype=float)
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)


def _prepare_telemetry(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "Distance" not in data.columns:
        raise ValueError("Telemetry is missing FastF1 Distance. Call add_distance() before comparison.")
    if "Time" not in data.columns:
        raise ValueError("Telemetry is missing Time.")

    data = data.sort_values("Distance")
    data = data.dropna(subset=["Distance", "Time"])
    data = data.drop_duplicates(subset=["Distance"], keep="first")
    data["time_seconds"] = _time_seconds(data["Time"])

    missing = [channel for channel in REQUIRED_CHANNELS if channel not in data.columns]
    if missing:
        raise ValueError(f"Telemetry is missing required channel(s): {', '.join(missing)}")
    return data


def _interp(source: pd.DataFrame, distance_axis: np.ndarray, channel: str) -> np.ndarray:
    if channel not in source.columns:
        return np.full_like(distance_axis, np.nan, dtype=float)

    values = source[channel]
    if values.dtype == bool:
        values = values.astype(int)
    values = pd.to_numeric(values, errors="coerce")
    return np.interp(distance_axis, source["Distance"].to_numpy(), values.to_numpy())


def align_laps(reference: pd.DataFrame, compared: pd.DataFrame, samples: int = 1200) -> pd.DataFrame:
    """Align two laps on a common distance axis and compute channel differences."""

    ref = _prepare_telemetry(reference)
    cmp = _prepare_telemetry(compared)

    start = max(float(ref["Distance"].min()), float(cmp["Distance"].min()))
    end = min(float(ref["Distance"].max()), float(cmp["Distance"].max()))
    if end <= start:
        raise ValueError("Laps do not share a usable distance range.")

    distance = np.linspace(start, end, samples)
    aligned = pd.DataFrame({"Distance": distance})

    channels = ["time_seconds", *REQUIRED_CHANNELS, *OPTIONAL_CHANNELS]
    for channel in channels:
        aligned[f"ref_{channel}"] = _interp(ref, distance, channel)
        aligned[f"cmp_{channel}"] = _interp(cmp, distance, channel)

    aligned["delta_time"] = aligned["cmp_time_seconds"] - aligned["ref_time_seconds"]
    aligned["speed_diff"] = aligned["cmp_Speed"] - aligned["ref_Speed"]
    aligned["throttle_diff"] = aligned["cmp_Throttle"] - aligned["ref_Throttle"]
    aligned["gear_diff"] = aligned["cmp_nGear"] - aligned["ref_nGear"]
    aligned["rpm_diff"] = aligned["cmp_RPM"] - aligned["ref_RPM"]
    aligned["drs_diff"] = aligned["cmp_DRS"] - aligned["ref_DRS"]
    aligned["line_deviation"] = np.hypot(aligned["cmp_X"] - aligned["ref_X"], aligned["cmp_Y"] - aligned["ref_Y"])

    ref_speed_ms = aligned["ref_Speed"] / 3.6
    cmp_speed_ms = aligned["cmp_Speed"] / 3.6
    aligned["ref_accel_estimate"] = np.gradient(ref_speed_ms, aligned["ref_time_seconds"])
    aligned["cmp_accel_estimate"] = np.gradient(cmp_speed_ms, aligned["cmp_time_seconds"])
    aligned["accel_diff"] = aligned["cmp_accel_estimate"] - aligned["ref_accel_estimate"]

    return aligned.replace([np.inf, -np.inf], np.nan)

