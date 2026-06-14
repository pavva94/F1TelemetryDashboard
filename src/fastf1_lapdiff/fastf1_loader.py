from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .models import LapData, LapMetadata


def load_fastf1_session(year: int, event: str, session_name: str, cache_dir: str | None = None) -> Any:
    try:
        import fastf1
    except ImportError as exc:
        raise RuntimeError("fastf1 is required for live session loading. Install with `python -m pip install -e .`.") from exc

    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(cache_dir)
    session = fastf1.get_session(year, event, session_name)
    session.load(laps=True, telemetry=True, weather=True, messages=True)
    return session


def available_seasons(start_year: int = 2018, end_year: int | None = None) -> list[int]:
    if end_year is None:
        from datetime import datetime

        end_year = datetime.now().year
    return list(range(end_year, start_year - 1, -1))


def list_events(year: int) -> list[dict[str, Any]]:
    try:
        import fastf1
    except ImportError as exc:
        raise RuntimeError("fastf1 is required for event discovery.") from exc

    schedule = fastf1.get_event_schedule(year, include_testing=False)
    events: list[dict[str, Any]] = []
    for _, row in schedule.iterrows():
        name = _none_if_nan(_value(row, "EventName")) or _none_if_nan(_value(row, "OfficialEventName"))
        if not name:
            continue
        events.append(
            {
                "round": int(_value(row, "RoundNumber", 0) or 0),
                "name": str(name),
                "country": _none_if_nan(_value(row, "Country")),
                "location": _none_if_nan(_value(row, "Location")),
                "date": _jsonable(_value(row, "EventDate")),
                "sessions": _sessions_from_event_row(row),
            }
        )
    return events


def list_session_entries(year: int, event: str, session_name: str, cache_dir: str | None = None) -> dict[str, Any]:
    session = load_fastf1_session(year, event, session_name, cache_dir)
    laps = session.laps
    drivers: list[dict[str, Any]] = []
    if laps is None or laps.empty:
        return {"drivers": [], "teams": []}

    for driver, group in laps.groupby("Driver"):
        team = _none_if_nan(group["Team"].dropna().iloc[0]) if "Team" in group.columns and not group["Team"].dropna().empty else None
        clean = _clean_laps(group)
        fastest = clean.sort_values("LapTime").iloc[0] if not clean.empty else group.dropna(subset=["LapTime"]).sort_values("LapTime").iloc[0]
        drivers.append(
            {
                "code": str(driver),
                "team": team,
                "fastestLap": int(_value(fastest, "LapNumber", 0) or 0),
                "fastestLapTime": _seconds(_value(fastest, "LapTime")),
                "cleanLapCount": int(len(clean)),
                "totalLapCount": int(len(group)),
            }
        )
    drivers.sort(key=lambda item: (item["team"] or "", item["code"]))
    teams = sorted({item["team"] for item in drivers if item["team"]})
    return {"drivers": drivers, "teams": teams}


def select_lap(session: Any, driver: str, lap_number: int | None = None, fastest: bool = False) -> LapData:
    laps = session.laps.pick_driver(driver)
    if laps.empty:
        raise ValueError(f"No laps found for driver {driver}.")

    if fastest:
        lap = laps.pick_fastest()
    elif lap_number is not None:
        selected = laps[laps["LapNumber"] == lap_number]
        if selected.empty:
            raise ValueError(f"No lap {lap_number} found for driver {driver}.")
        lap = selected.iloc[0]
    else:
        raise ValueError("Either lap_number or fastest=True is required.")

    telemetry = lap.get_car_data().add_distance()
    try:
        position = lap.get_pos_data()
        telemetry = pd.merge_asof(
            telemetry.sort_values("Time"),
            position[["Time", "X", "Y", "Z"]].sort_values("Time"),
            on="Time",
            direction="nearest",
        )
    except Exception:
        pass

    return LapData(metadata=_metadata_from_lap(lap, driver), telemetry=telemetry)


def select_best_comparison_laps(session: Any, driver_a: str, driver_b: str | None = None) -> tuple[LapData, LapData]:
    if not driver_b or driver_a == driver_b:
        laps = _ranked_driver_laps(session, driver_a)
        if len(laps) < 2:
            raise ValueError(f"Need at least two comparable timed laps for {driver_a}.")
        return _lapdata_from_lap(laps.iloc[0], driver_a), _lapdata_from_lap(laps.iloc[1], driver_a)

    ref_laps = _ranked_driver_laps(session, driver_a)
    cmp_laps = _ranked_driver_laps(session, driver_b)
    if ref_laps.empty:
        raise ValueError(f"No comparable timed laps found for {driver_a}.")
    if cmp_laps.empty:
        raise ValueError(f"No comparable timed laps found for {driver_b}.")
    return _lapdata_from_lap(ref_laps.iloc[0], driver_a), _lapdata_from_lap(cmp_laps.iloc[0], driver_b)


def weather_context_for_lap(session: Any, lap_number: int | None) -> dict[str, Any]:
    if lap_number is None or not hasattr(session, "weather_data"):
        return {}
    weather = session.weather_data
    if weather is None or weather.empty:
        return {}
    laps = session.laps
    row = laps[laps["LapNumber"] == lap_number]
    if row.empty or "Time" not in row.columns:
        return {}
    target_time = row.iloc[0]["Time"]
    weather = weather.copy()
    weather["__delta"] = (weather["Time"] - target_time).abs()
    nearest = weather.sort_values("__delta").iloc[0].drop(labels=["__delta"], errors="ignore")
    return {key: _jsonable(value) for key, value in nearest.to_dict().items()}


def _ranked_driver_laps(session: Any, driver: str) -> pd.DataFrame:
    laps = session.laps.pick_driver(driver)
    if laps.empty:
        raise ValueError(f"No laps found for driver {driver}.")
    clean = _clean_laps(laps)
    ranked = clean if not clean.empty else laps.dropna(subset=["LapTime"])
    if ranked.empty:
        return ranked
    return ranked.sort_values("LapTime")


def _clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    ranked = laps.dropna(subset=["LapTime"]).copy()
    if "Deleted" in ranked.columns:
        ranked = ranked[ranked["Deleted"] != True]  # noqa: E712
    if "IsAccurate" in ranked.columns:
        ranked = ranked[ranked["IsAccurate"] != False]  # noqa: E712
    if "PitInTime" in ranked.columns:
        ranked = ranked[ranked["PitInTime"].isna()]
    if "PitOutTime" in ranked.columns:
        ranked = ranked[ranked["PitOutTime"].isna()]
    return ranked


def _lapdata_from_lap(lap: pd.Series, driver: str) -> LapData:
    telemetry = lap.get_car_data().add_distance()
    try:
        position = lap.get_pos_data()
        telemetry = pd.merge_asof(
            telemetry.sort_values("Time"),
            position[["Time", "X", "Y", "Z"]].sort_values("Time"),
            on="Time",
            direction="nearest",
        )
    except Exception:
        pass
    return LapData(metadata=_metadata_from_lap(lap, driver), telemetry=telemetry)


def _sessions_from_event_row(row: pd.Series) -> list[dict[str, str]]:
    sessions: list[dict[str, str]] = []
    for index in range(1, 6):
        session_name = _none_if_nan(_value(row, f"Session{index}"))
        session_date = _none_if_nan(_value(row, f"Session{index}Date"))
        if session_name:
            sessions.append({"name": str(session_name), "date": _jsonable(session_date)})
    return sessions


def _metadata_from_lap(lap: pd.Series, driver: str) -> LapMetadata:
    return LapMetadata(
        driver=driver,
        lap_number=int(_value(lap, "LapNumber", 0) or 0),
        lap_time_seconds=_seconds(_value(lap, "LapTime")),
        sector_times_seconds=(
            _seconds(_value(lap, "Sector1Time")),
            _seconds(_value(lap, "Sector2Time")),
            _seconds(_value(lap, "Sector3Time")),
        ),
        compound=_none_if_nan(_value(lap, "Compound")),
        tyre_life=_float_or_none(_value(lap, "TyreLife")),
        fresh_tyre=_bool_or_none(_value(lap, "FreshTyre")),
        stint=int(_value(lap, "Stint")) if pd.notna(_value(lap, "Stint")) else None,
        track_status=str(_value(lap, "TrackStatus")) if pd.notna(_value(lap, "TrackStatus")) else None,
        is_accurate=_bool_or_none(_value(lap, "IsAccurate")),
        deleted=_bool_or_none(_value(lap, "Deleted")),
        pit_in=pd.notna(_value(lap, "PitInTime")),
        pit_out=pd.notna(_value(lap, "PitOutTime")),
    )


def _value(row: pd.Series, key: str, default: Any = None) -> Any:
    return row[key] if key in row.index else default


def _seconds(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return float(value)


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _bool_or_none(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def _none_if_nan(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    return value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    if pd.isna(value):
        return None
    return value
