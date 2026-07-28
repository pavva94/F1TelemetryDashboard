from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.responses import FileResponse, JSONResponse, Response

from .dashboard import build_dashboard_payload
from .fastf1_loader import (
    available_seasons,
    list_events,
    list_session_entries,
    load_fastf1_session,
    race_summary,
    session_summary,
    select_best_comparison_laps,
    select_best_lap_from_session,
    weather_context_for_lap,
)
from .season_cache import SeasonCacheManager


APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = os.environ.get("FASTF1_CACHE_DIR", str(Path.cwd() / ".fastf1-cache"))
DEFAULT_SEASON_CACHE_DIR = os.environ.get(
    "SEASON_ANALYSIS_CACHE_DIR", str(Path(DEFAULT_CACHE_DIR) / "seasons")
)
DEFAULT_SEASON_CACHE_SEED_DIR = os.environ.get("SEASON_ANALYSIS_SEED_DIR")


def create_app() -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException, Query
        from fastapi.encoders import jsonable_encoder
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.middleware.gzip import GZipMiddleware
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("FastAPI web dependencies are missing. Install with `python -m pip install -e .`.") from exc

    app = FastAPI(
        title="Apex Signal API",
        description="Formula 1 season, race, and lap analysis powered by FastF1 data.",
        version="0.1.0",
    )
    season_cache = SeasonCacheManager(
        DEFAULT_SEASON_CACHE_DIR,
        DEFAULT_CACHE_DIR,
        seed_root=DEFAULT_SEASON_CACHE_SEED_DIR,
    )
    app.state.season_cache = season_cache
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    allowed_origins = _allowed_origins()
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["*"],
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

    @app.get("/api/session-summary")
    def session_summary_route(year: int, event: str, session: str) -> JSONResponse:
        try:
            data = session_summary(year, event, session, DEFAULT_CACHE_DIR)
            return JSONResponse(jsonable_encoder(data))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/season/{year}/status")
    def season_status_route(year: int) -> JSONResponse:
        if year < 2018 or year > 2100:
            raise HTTPException(status_code=422, detail="Season must be between 2018 and 2100.")
        return JSONResponse(jsonable_encoder(season_cache.status(year)))

    @app.get("/api/season/{year}/analysis")
    def prepared_season_analysis_route(
        year: int, if_none_match: str | None = Header(None)
    ) -> Response:
        if year < 2018 or year > 2100:
            raise HTTPException(status_code=422, detail="Season must be between 2018 and 2100.")
        try:
            data, status = season_cache.request(year)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if data is None:
            response_status = 503 if status.get("status") == "failed" else 202
            return JSONResponse(
                {
                    "season": year,
                    "status": status.get("status", "generating"),
                    "cache": status,
                    "detail": status.get("error") if response_status == 503 else None,
                },
                status_code=response_status,
                headers={"Cache-Control": "no-store", "Retry-After": "2"},
            )
        etag_suffix = "-stale" if status.get("stale") else ""
        etag = f'"{status.get("dataSha256", "")}{etag_suffix}"'
        headers = _season_cache_headers(year, status, etag)
        if if_none_match == etag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(jsonable_encoder(data), headers=headers)

    @app.post("/api/season/{year}/refresh")
    def refresh_season_route(
        year: int,
        x_season_refresh_token: str | None = Header(None),
    ) -> JSONResponse:
        if year < 2018 or year > 2100:
            raise HTTPException(status_code=422, detail="Season must be between 2018 and 2100.")
        configured_token = os.environ.get("SEASON_REFRESH_TOKEN")
        if not configured_token:
            raise HTTPException(status_code=503, detail="Administrative season refresh is not configured.")
        import secrets

        if not x_season_refresh_token or not secrets.compare_digest(
            x_season_refresh_token, configured_token
        ):
            raise HTTPException(status_code=403, detail="Invalid season refresh token.")
        started = season_cache.start_generation(year, force=True)
        return JSONResponse(
            {
                "season": year,
                "status": "generating",
                "started": started,
                "cache": season_cache.status(year, check_source=False),
            },
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/season-analysis")
    def season_analysis_route(
        year: int = Query(..., ge=2018, le=2100),
        start_round: int | None = Query(None, ge=1),
        end_round: int | None = Query(None, ge=1),
        include_sprints: bool = True,
        if_none_match: str | None = Header(None),
    ) -> Response:
        """Compatibility route; filtering is presentation-only over the shared dataset."""
        if start_round is not None and end_round is not None and start_round > end_round:
            raise HTTPException(status_code=422, detail="start_round must be less than or equal to end_round")
        return prepared_season_analysis_route(year, if_none_match)

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

        @app.get("/race")
        @app.get("/season")
        def analysis_route() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")

    return app


def _comparison_mode(session_a: str, session_b: str, driver_a: str, driver_b: str) -> str:
    if session_a != session_b:
        return "cross-session-best-laps"
    if driver_a == driver_b:
        return "same-driver-two-best-laps"
    return "driver-vs-driver-best-laps"


def _season_cache_headers(year: int, manifest: dict[str, Any], etag: str) -> dict[str, str]:
    generated = manifest.get("generatedAt")
    try:
        parsed = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
        last_modified = parsed.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    except (TypeError, ValueError):
        last_modified = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    current_year = datetime.now(timezone.utc).year
    cache_control = (
        "public, max-age=60, stale-while-revalidate=86400"
        if year == current_year
        else "public, max-age=86400, stale-while-revalidate=604800"
    )
    return {"ETag": etag, "Last-Modified": last_modified, "Cache-Control": cache_control}


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


def _allowed_origins() -> list[str]:
    """Return optional comma-separated frontend origins for split deployments."""
    configured = os.environ.get("FASTF1_ALLOWED_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
