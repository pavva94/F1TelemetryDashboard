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


def race_summary(year: int, event: str, cache_dir: str | None = None) -> dict[str, Any]:
    session = load_fastf1_session(year, event, "Race", cache_dir)
    laps = session.laps
    results = getattr(session, "results", None)
    standings = _race_standings(results, laps)
    fastest_lap = _fastest_lap_summary(laps)
    position_history = _position_history(laps)
    race_insights = _race_insights(laps)
    winner = standings[0] if standings else None
    event_info = getattr(session, "event", None)

    return {
        "year": year,
        "event": event,
        "round": _jsonable(_value(event_info, "RoundNumber")) if event_info is not None else None,
        "country": _jsonable(_value(event_info, "Country")) if event_info is not None else None,
        "location": _jsonable(_value(event_info, "Location")) if event_info is not None else None,
        "date": _jsonable(_value(event_info, "EventDate")) if event_info is not None else None,
        "winner": winner,
        "raceTime": winner.get("time") if winner else None,
        "fastestLap": fastest_lap,
        "lapCount": int(laps["LapNumber"].max()) if laps is not None and not laps.empty and "LapNumber" in laps.columns else None,
        "classifiedDrivers": len([item for item in standings if item.get("classified")]),
        "standings": standings,
        "positionHistory": position_history,
        "raceInsights": race_insights,
    }


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


def select_best_lap_from_session(session: Any, driver: str) -> LapData:
    laps = _ranked_driver_laps(session, driver)
    if laps.empty:
        raise ValueError(f"No comparable timed laps found for {driver}.")
    return _lapdata_from_lap(laps.iloc[0], driver)


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


def _race_standings(results: pd.DataFrame | None, laps: pd.DataFrame | None) -> list[dict[str, Any]]:
    if results is not None and not results.empty:
        output: list[dict[str, Any]] = []
        for _, row in results.sort_values("Position").iterrows():
            position = _value(row, "Position")
            driver = _none_if_nan(_value(row, "Abbreviation")) or _none_if_nan(_value(row, "DriverId")) or _none_if_nan(_value(row, "BroadcastName"))
            output.append(
                {
                    "position": int(position) if pd.notna(position) else None,
                    "driver": str(driver) if driver else None,
                    "fullName": _none_if_nan(_value(row, "FullName")),
                    "team": _none_if_nan(_value(row, "TeamName")),
                    "grid": _int_or_none(_value(row, "GridPosition")),
                    "status": _none_if_nan(_value(row, "Status")),
                    "points": _float_or_none(_value(row, "Points")),
                    "time": _time_or_gap(_value(row, "Time")),
                    "classified": str(_none_if_nan(_value(row, "Status")) or "").lower() not in {"retired", "accident", "collision", "gearbox", "engine"},
                }
            )
        return output

    if laps is None or laps.empty:
        return []

    output = []
    for driver, group in laps.dropna(subset=["LapNumber"]).groupby("Driver"):
        final_lap = group.sort_values("LapNumber").iloc[-1]
        position = _int_or_none(_value(final_lap, "Position"))
        output.append(
            {
                "position": position,
                "driver": str(driver),
                "fullName": None,
                "team": _none_if_nan(_value(final_lap, "Team")),
                "grid": None,
                "status": None,
                "points": None,
                "time": None,
                "classified": True,
            }
        )
    return sorted(output, key=lambda item: item["position"] or 999)


def _fastest_lap_summary(laps: pd.DataFrame | None) -> dict[str, Any] | None:
    if laps is None or laps.empty or "LapTime" not in laps.columns:
        return None
    timed = laps.dropna(subset=["LapTime"])
    if timed.empty:
        return None
    row = timed.sort_values("LapTime").iloc[0]
    return {
        "driver": _none_if_nan(_value(row, "Driver")),
        "team": _none_if_nan(_value(row, "Team")),
        "lap": _int_or_none(_value(row, "LapNumber")),
        "time": _seconds(_value(row, "LapTime")),
        "compound": _none_if_nan(_value(row, "Compound")),
        "tyreLife": _float_or_none(_value(row, "TyreLife")),
    }


def _position_history(laps: pd.DataFrame | None) -> list[dict[str, Any]]:
    if laps is None or laps.empty or "Position" not in laps.columns:
        return []
    output: list[dict[str, Any]] = []
    for driver, group in laps.dropna(subset=["LapNumber", "Position"]).groupby("Driver"):
        group = group.sort_values("LapNumber")
        team = _none_if_nan(group["Team"].dropna().iloc[0]) if "Team" in group.columns and not group["Team"].dropna().empty else None
        output.append(
            {
                "driver": str(driver),
                "team": team,
                "laps": [
                    {"lap": int(_value(row, "LapNumber")), "position": int(_value(row, "Position"))}
                    for _, row in group.iterrows()
                    if pd.notna(_value(row, "LapNumber")) and pd.notna(_value(row, "Position"))
                ],
            }
        )
    return sorted(output, key=lambda item: item["driver"])


def _race_insights(laps: pd.DataFrame | None) -> dict[str, Any]:
    if laps is None or laps.empty:
        return _empty_race_insights()

    timed = laps.dropna(subset=["LapTime"]).copy() if "LapTime" in laps.columns else pd.DataFrame()
    pace_laps = _representative_race_laps(timed)
    return {
        "driverPace": _driver_pace_distribution(pace_laps),
        "fastestSectors": _fastest_sector_rankings(timed),
        "teamPace": _team_pace_summary(pace_laps),
        "tyreCompounds": _tyre_compound_summary(pace_laps),
        "driverStints": _driver_stint_summary(pace_laps),
        "pitStops": _pit_stop_summary(laps),
        "lapTimeTrend": _lap_time_trend(pace_laps),
        "fuelPaceProxy": _fuel_pace_proxy(pace_laps),
        "notes": [
            "Average pace excludes pit-in and pit-out laps where that timing is available.",
            "Fuel load is not exposed by FastF1; the fuel pace view is a clean-lap trend proxy over race distance.",
            "Pit lane time is estimated from PitInTime to the following PitOutTime when both timestamps are available.",
        ],
    }


def _empty_race_insights() -> dict[str, Any]:
    return {
        "driverPace": [],
        "fastestSectors": {"sector1": [], "sector2": [], "sector3": []},
        "teamPace": [],
        "tyreCompounds": [],
        "driverStints": [],
        "pitStops": [],
        "lapTimeTrend": [],
        "fuelPaceProxy": [],
        "notes": [],
    }


def _representative_race_laps(laps: pd.DataFrame) -> pd.DataFrame:
    if laps.empty:
        return laps
    clean = laps.copy()
    if "Deleted" in clean.columns:
        clean = clean[clean["Deleted"] != True]  # noqa: E712
    if "IsAccurate" in clean.columns:
        clean = clean[clean["IsAccurate"] != False]  # noqa: E712
    if "PitInTime" in clean.columns:
        clean = clean[clean["PitInTime"].isna()]
    if "PitOutTime" in clean.columns:
        clean = clean[clean["PitOutTime"].isna()]
    return clean


def _driver_pace_distribution(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty:
        return []
    output: list[dict[str, Any]] = []
    for driver, group in laps.groupby("Driver"):
        times = [_seconds(value) for value in group["LapTime"].dropna()]
        times = [value for value in times if value is not None]
        if not times:
            continue
        group = group.sort_values("LapNumber")
        output.append(
            {
                "driver": str(driver),
                "team": _first_present(group, "Team"),
                "averagePace": float(pd.Series(times).mean()),
                "medianPace": float(pd.Series(times).median()),
                "bestLapTime": min(times),
                "worstLapTime": max(times),
                "stdDev": float(pd.Series(times).std()) if len(times) > 1 else 0.0,
                "lapCount": len(times),
                "laps": [
                    {
                        "lap": _int_or_none(_value(row, "LapNumber")),
                        "time": _seconds(_value(row, "LapTime")),
                        "compound": _none_if_nan(_value(row, "Compound")),
                        "tyreLife": _float_or_none(_value(row, "TyreLife")),
                        "stint": _int_or_none(_value(row, "Stint")),
                    }
                    for _, row in group.iterrows()
                    if _seconds(_value(row, "LapTime")) is not None
                ],
            }
        )
    return sorted(output, key=lambda item: item["averagePace"])


def _fastest_sector_rankings(laps: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    rankings: dict[str, list[dict[str, Any]]] = {}
    for number, column in ((1, "Sector1Time"), (2, "Sector2Time"), (3, "Sector3Time")):
        if laps.empty or column not in laps.columns:
            rankings[f"sector{number}"] = []
            continue
        best: list[dict[str, Any]] = []
        for driver, group in laps.dropna(subset=[column]).groupby("Driver"):
            row = group.sort_values(column).iloc[0]
            best.append(
                {
                    "driver": str(driver),
                    "team": _none_if_nan(_value(row, "Team")),
                    "lap": _int_or_none(_value(row, "LapNumber")),
                    "time": _seconds(_value(row, column)),
                    "compound": _none_if_nan(_value(row, "Compound")),
                    "tyreLife": _float_or_none(_value(row, "TyreLife")),
                }
            )
        rankings[f"sector{number}"] = sorted(best, key=lambda item: item["time"] if item["time"] is not None else 9999)
    return rankings


def _team_pace_summary(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty or "Team" not in laps.columns:
        return []
    output = []
    for team, group in laps.dropna(subset=["Team"]).groupby("Team"):
        times = [_seconds(value) for value in group["LapTime"].dropna()]
        times = [value for value in times if value is not None]
        if not times:
            continue
        output.append(
            {
                "team": str(team),
                "averagePace": float(pd.Series(times).mean()),
                "medianPace": float(pd.Series(times).median()),
                "bestLapTime": min(times),
                "lapCount": len(times),
                "drivers": sorted(str(driver) for driver in group["Driver"].dropna().unique()),
            }
        )
    return sorted(output, key=lambda item: item["averagePace"])


def _tyre_compound_summary(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty or "Compound" not in laps.columns:
        return []
    output = []
    for compound, group in laps.dropna(subset=["Compound"]).groupby("Compound"):
        times = [_seconds(value) for value in group["LapTime"].dropna()]
        times = [value for value in times if value is not None]
        if not times:
            continue
        output.append(
            {
                "compound": str(compound),
                "lapCount": len(times),
                "averagePace": float(pd.Series(times).mean()),
                "medianPace": float(pd.Series(times).median()),
                "bestLapTime": min(times),
                "drivers": int(group["Driver"].nunique()) if "Driver" in group.columns else None,
            }
        )
    return sorted(output, key=lambda item: item["averagePace"])


def _driver_stint_summary(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty or "Stint" not in laps.columns:
        return []
    output = []
    for (driver, stint), group in laps.dropna(subset=["Stint"]).groupby(["Driver", "Stint"]):
        times = [_seconds(value) for value in group["LapTime"].dropna()]
        times = [value for value in times if value is not None]
        if not times:
            continue
        output.append(
            {
                "driver": str(driver),
                "team": _first_present(group, "Team"),
                "stint": int(stint),
                "compound": _first_present(group, "Compound"),
                "startLap": _int_or_none(group["LapNumber"].min()) if "LapNumber" in group.columns else None,
                "endLap": _int_or_none(group["LapNumber"].max()) if "LapNumber" in group.columns else None,
                "laps": len(times),
                "averagePace": float(pd.Series(times).mean()),
                "bestLapTime": min(times),
            }
        )
    return sorted(output, key=lambda item: (item["driver"], item["stint"]))


def _pit_stop_summary(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty or "PitInTime" not in laps.columns or "PitOutTime" not in laps.columns:
        return []
    output = []
    for driver, group in laps.dropna(subset=["LapNumber"]).groupby("Driver"):
        group = group.sort_values("LapNumber").reset_index(drop=True)
        for index, row in group[group["PitInTime"].notna()].iterrows():
            next_rows = group[(group["LapNumber"] > _value(row, "LapNumber")) & group["PitOutTime"].notna()]
            next_row = next_rows.iloc[0] if not next_rows.empty else None
            duration = None
            if next_row is not None:
                duration = _duration_seconds(_value(next_row, "PitOutTime"), _value(row, "PitInTime"))
            output.append(
                {
                    "driver": str(driver),
                    "team": _none_if_nan(_value(row, "Team")),
                    "lap": _int_or_none(_value(row, "LapNumber")),
                    "stint": _int_or_none(_value(row, "Stint")),
                    "compoundBefore": _none_if_nan(_value(row, "Compound")),
                    "compoundAfter": _none_if_nan(_value(next_row, "Compound")) if next_row is not None else None,
                    "pitLaneTime": duration,
                    "pitOutLap": _int_or_none(_value(next_row, "LapNumber")) if next_row is not None else None,
                }
            )
    return sorted(output, key=lambda item: (item["lap"] or 999, item["driver"]))


def _lap_time_trend(laps: pd.DataFrame) -> list[dict[str, Any]]:
    if laps.empty or "LapNumber" not in laps.columns:
        return []
    output = []
    for lap_number, group in laps.dropna(subset=["LapNumber"]).groupby("LapNumber"):
        times = [_seconds(value) for value in group["LapTime"].dropna()]
        times = [value for value in times if value is not None]
        if not times:
            continue
        output.append(
            {
                "lap": int(lap_number),
                "averageTime": float(pd.Series(times).mean()),
                "medianTime": float(pd.Series(times).median()),
                "bestTime": min(times),
                "lapCount": len(times),
            }
        )
    return sorted(output, key=lambda item: item["lap"])


def _fuel_pace_proxy(laps: pd.DataFrame) -> list[dict[str, Any]]:
    output = []
    if laps.empty or "LapNumber" not in laps.columns:
        return output
    for driver, group in laps.dropna(subset=["LapNumber"]).groupby("Driver"):
        group = group.sort_values("LapNumber")
        points = [
            {
                "lap": _int_or_none(_value(row, "LapNumber")),
                "time": _seconds(_value(row, "LapTime")),
                "compound": _none_if_nan(_value(row, "Compound")),
                "stint": _int_or_none(_value(row, "Stint")),
            }
            for _, row in group.iterrows()
            if _seconds(_value(row, "LapTime")) is not None
        ]
        if len(points) < 3:
            continue
        first = pd.Series([point["time"] for point in points[: max(1, len(points) // 3)]])
        last = pd.Series([point["time"] for point in points[-max(1, len(points) // 3) :]])
        output.append(
            {
                "driver": str(driver),
                "team": _first_present(group, "Team"),
                "earlyMedian": float(first.median()),
                "lateMedian": float(last.median()),
                "medianDelta": float(last.median() - first.median()),
                "points": points,
            }
        )
    return sorted(output, key=lambda item: item["medianDelta"])


def _time_or_gap(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "total_seconds"):
        return _clock(float(value.total_seconds()))
    return str(value)


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


def _int_or_none(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _duration_seconds(end: Any, start: Any) -> float | None:
    if end is None or start is None or pd.isna(end) or pd.isna(start):
        return None
    try:
        delta = end - start
        return float(delta.total_seconds()) if hasattr(delta, "total_seconds") else float(delta)
    except (TypeError, ValueError):
        return None


def _first_present(group: pd.DataFrame, column: str) -> Any:
    if column not in group.columns:
        return None
    values = group[column].dropna()
    if values.empty:
        return None
    return _none_if_nan(values.iloc[0])


def _clock(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds - hours * 3600) // 60)
    remainder = seconds - hours * 3600 - minutes * 60
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:06.3f}"
    return f"{minutes}:{remainder:06.3f}"


def _bool_or_none(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def _none_if_nan(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    return value


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    if pd.isna(value):
        return None
    return value
