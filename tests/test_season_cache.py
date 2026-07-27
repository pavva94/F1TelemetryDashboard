from __future__ import annotations

import json
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastf1_lapdiff.season_cache import CALCULATION_VERSION, SeasonCacheManager


def _schedule(rounds: int) -> list[dict[str, object]]:
    return [
        {
            "round": round_number,
            "name": f"Event {round_number}",
            "date": "2020-01-01T12:00:00+00:00",
            "sessions": [],
        }
        for round_number in range(1, rounds + 1)
    ]


def _payload(year: int, last_round: int) -> dict[str, object]:
    return {
        "meta": {
            "season": year,
            "completedRounds": list(range(1, last_round + 1)),
            "availableRound": last_round,
            "isComplete": True,
            "partial": False,
        },
        "events": _schedule(last_round),
        "records": [{"round": last_round, "driver": "AAA", "team": "Alpha"}],
        "entities": {"drivers": ["AAA"], "teams": ["Alpha"]},
        "errors": [],
    }


def _wait_until_ready(manager: SeasonCacheManager, year: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if manager.load(year):
            return
        time.sleep(0.01)
    raise AssertionError("season cache did not become ready")


def test_concurrent_requests_generate_once_and_persist_across_managers() -> None:
    with tempfile.TemporaryDirectory() as directory:
        calls = 0
        calls_lock = threading.Lock()

        def builder(year, cache_dir, start, end, sprints, progress_callback=None):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.08)
            return _payload(year, end)

        manager = SeasonCacheManager(directory, builder=builder, schedule_loader=lambda year: _schedule(2))
        workers = [threading.Thread(target=manager.request, args=(2024,)) for _ in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        _wait_until_ready(manager, 2024)

        assert calls == 1
        loaded = manager.load(2024)
        assert loaded is not None
        assert loaded[1]["calculationVersion"] == CALCULATION_VERSION

        restarted = SeasonCacheManager(directory, builder=builder, schedule_loader=lambda year: _schedule(2))
        payload, status = restarted.request(2024)
        assert payload is not None
        assert status["status"] == "ready"
        assert calls == 1


def test_calculation_version_mismatch_invalidates_generation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        calls = 0

        def builder(year, cache_dir, start, end, sprints, progress_callback=None):
            nonlocal calls
            calls += 1
            return _payload(year, end)

        manager = SeasonCacheManager(directory, builder=builder, schedule_loader=lambda year: _schedule(1))
        manager.generate_now(2024)
        current = (Path(directory) / "2024" / "CURRENT").read_text().strip()
        manifest_path = Path(directory) / "2024" / "generations" / current / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["calculationVersion"] = "obsolete"
        manifest_path.write_text(json.dumps(manifest))

        assert manager.load(2024) is None
        payload, status = manager.request(2024)
        assert payload is None
        assert status["status"] == "generating"
        _wait_until_ready(manager, 2024)
        assert calls == 2


def test_stale_lock_is_recovered() -> None:
    with tempfile.TemporaryDirectory() as directory:
        season_dir = Path(directory) / "2024"
        season_dir.mkdir(parents=True)
        (season_dir / "generation.lock").write_text(
            json.dumps(
                {
                    "season": 2024,
                    "status": "generating",
                    "startedAt": "2020-01-01T00:00:00+00:00",
                    "updatedAt": "2020-01-01T00:00:00+00:00",
                }
            )
        )
        manager = SeasonCacheManager(
            directory,
            builder=lambda year, cache, start, end, sprints, progress_callback=None: _payload(year, end),
            schedule_loader=lambda year: _schedule(1),
            stale_lock_seconds=1,
        )
        assert not (season_dir / "generation.lock").exists()
        assert manager.start_generation(2024)
        _wait_until_ready(manager, 2024)


def test_current_season_serves_old_generation_while_new_round_builds() -> None:
    with tempfile.TemporaryDirectory() as directory:
        year = datetime.now(timezone.utc).year
        round_count = 1
        refresh_started = threading.Event()
        allow_refresh = threading.Event()
        calls = 0

        def schedule_loader(requested_year):
            return _schedule(round_count)

        def builder(requested_year, cache_dir, start, end, sprints, progress_callback=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                refresh_started.set()
                allow_refresh.wait(timeout=3)
            return _payload(requested_year, end)

        manager = SeasonCacheManager(directory, builder=builder, schedule_loader=schedule_loader)
        manager.generate_now(year)
        round_count = 2

        payload, status = manager.request(year)
        assert payload is not None
        assert payload["meta"]["availableRound"] == 1
        assert status["stale"] is True
        assert refresh_started.wait(timeout=2)
        still_old = manager.load(year)
        assert still_old is not None
        assert still_old[0]["meta"]["availableRound"] == 1

        allow_refresh.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            loaded = manager.load(year)
            if loaded and loaded[0]["meta"]["availableRound"] == 2:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("refreshed generation was not atomically promoted")
