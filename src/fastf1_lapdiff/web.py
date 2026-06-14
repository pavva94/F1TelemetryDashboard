from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .dashboard import build_dashboard_payload
from .fastf1_loader import (
    available_seasons,
    list_events,
    list_session_entries,
    load_fastf1_session,
    race_summary,
    select_best_comparison_laps,
    select_best_lap_from_session,
    weather_context_for_lap,
)


APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = os.environ.get("FASTF1_CACHE_DIR", str(Path.cwd() / ".fastf1-cache"))


def create_app() -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.encoders import jsonable_encoder
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("FastAPI web dependencies are missing. Install with `python -m pip install -e .`.") from exc

    app = FastAPI(
        title="FastF1 Lap Difference Dashboard",
        description="No-login telemetry comparison dashboard backed by FastF1 data.",
        version="0.1.0",
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/seasons")
    def seasons() -> dict[str, list[int]]:
        return {"seasons": available_seasons()}

    @app.get("/api/events")
    def events(year: int = Query(..., ge=2018, le=2100)) -> JSONResponse:
        try:
            return JSONResponse(jsonable_encoder({"events": list_events(year)}))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/session-entries")
    def session_entries(year: int, event: str, session: str) -> JSONResponse:
        try:
            data = list_session_entries(year, event, session, DEFAULT_CACHE_DIR)
            return JSONResponse(jsonable_encoder(data))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/race-summary")
    def race_summary_route(year: int, event: str) -> JSONResponse:
        try:
            data = race_summary(year, event, DEFAULT_CACHE_DIR)
            return JSONResponse(jsonable_encoder(data))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/compare-best-laps")
    def compare_best_laps(
        year: int,
        event: str,
        session: str | None = None,
        driver_a: str = Query(...),
        driver_b: str | None = None,
        session_a: str | None = None,
        session_b: str | None = None,
    ) -> JSONResponse:
        try:
            reference_session_name = session_a or session
            compared_session_name = session_b or session_a or session
            if not reference_session_name or not compared_session_name:
                raise ValueError("Both reference and compared sessions are required.")

            reference_session = load_fastf1_session(year, event, reference_session_name, DEFAULT_CACHE_DIR)
            compared_session = reference_session if compared_session_name == reference_session_name else load_fastf1_session(year, event, compared_session_name, DEFAULT_CACHE_DIR)
            compared_driver = driver_b or driver_a

            if reference_session_name == compared_session_name:
                reference, compared = select_best_comparison_laps(reference_session, driver_a, compared_driver)
            else:
                reference = select_best_lap_from_session(reference_session, driver_a)
                compared = select_best_lap_from_session(compared_session, compared_driver)

            weather = weather_context_for_lap(compared_session, compared.metadata.lap_number)
            payload = build_dashboard_payload(reference, compared, weather)
            payload["selection"] = {
                "year": year,
                "event": event,
                "session": reference_session_name if reference_session_name == compared_session_name else f"{reference_session_name} vs {compared_session_name}",
                "sessionA": reference_session_name,
                "sessionB": compared_session_name,
                "driverA": driver_a,
                "driverB": compared_driver,
                "mode": _comparison_mode(reference_session_name, compared_session_name, driver_a, compared_driver),
            }
            return JSONResponse(jsonable_encoder(payload))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    frontend_dir = _frontend_dir()
    if frontend_dir.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dir), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    return app


def _comparison_mode(session_a: str, session_b: str, driver_a: str, driver_b: str) -> str:
    if session_a != session_b:
        return "cross-session-best-laps"
    if driver_a == driver_b:
        return "same-driver-two-best-laps"
    return "driver-vs-driver-best-laps"


def main() -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn is missing. Install with `python -m pip install -e .`.") from exc

    uvicorn.run("fastf1_lapdiff.web:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)
    return 0


def _frontend_dir() -> Path:
    configured = os.environ.get("FASTF1_FRONTEND_DIR")
    if configured:
        return Path(configured)
    cwd_frontend = Path.cwd() / "frontend"
    if cwd_frontend.exists():
        return cwd_frontend
    return APP_DIR / "frontend"


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
