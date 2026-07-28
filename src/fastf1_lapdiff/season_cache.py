"""Persistent, cross-process cache for prepared season analysis datasets."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .fastf1_loader import list_events
from .season_analytics import build_season_analysis


SCHEMA_VERSION = 1
CALCULATION_VERSION = "season-analysis-v3"
DEFAULT_STALE_LOCK_SECONDS = 60 * 60 * 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


class SeasonCacheManager:
    """Own season generations, locks, validation, and background refreshes."""

    def __init__(
        self,
        cache_root: str | Path,
        fastf1_cache_dir: str | Path | None = None,
        *,
        seed_root: str | Path | None = None,
        builder: Callable[..., dict[str, Any]] = build_season_analysis,
        schedule_loader: Callable[[int], list[dict[str, Any]]] = list_events,
        stale_lock_seconds: int = DEFAULT_STALE_LOCK_SECONDS,
    ) -> None:
        self.root = Path(cache_root)
        self.fastf1_cache_dir = str(fastf1_cache_dir) if fastf1_cache_dir else None
        self.seed_root = Path(seed_root) if seed_root else None
        self.builder = builder
        self.schedule_loader = schedule_loader
        self.stale_lock_seconds = stale_lock_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self.hydrate_from_seed()
        self.recover_abandoned_state()

    def hydrate_from_seed(self) -> None:
        """Copy bundled prepared seasons into an empty runtime cache."""
        if not self.seed_root or not self.seed_root.is_dir():
            return
        try:
            seed_seasons = list(self.seed_root.iterdir())
        except OSError:
            return
        for seed_season in seed_seasons:
            if not seed_season.is_dir() or not seed_season.name.isdigit():
                continue
            target = self.root / seed_season.name
            if target.exists():
                continue
            staging = self.root / f".{seed_season.name}.seed-{uuid.uuid4().hex}.tmp"
            try:
                shutil.copytree(seed_season, staging)
                os.replace(staging, target)
            except (FileExistsError, OSError):
                # Another worker may have hydrated or started this season.
                continue
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def recover_abandoned_state(self) -> None:
        """Remove abandoned staging directories and expired generation locks."""
        for season_dir in self.root.iterdir():
            if not season_dir.is_dir():
                continue
            staging = season_dir / "staging"
            if staging.exists():
                for child in staging.iterdir():
                    if self._age_seconds(child) > self.stale_lock_seconds:
                        shutil.rmtree(child, ignore_errors=True)
            lock = season_dir / "generation.lock"
            if lock.exists() and self._lock_is_stale(lock):
                lock.unlink(missing_ok=True)

    def status(self, year: int, *, check_source: bool = True) -> dict[str, Any]:
        loaded = self.load(year)
        lock = self._read_lock(year)
        failure = self._read_json(self._season_dir(year) / "last-failure.json")
        if loaded:
            _payload, manifest = loaded
            refreshing = bool(lock)
            source_stale = check_source and not refreshing and self._source_has_new_round(year, manifest)
            stale = source_stale or refreshing
            result = {
                **manifest,
                "status": "generating" if refreshing else "ready",
                "stale": stale,
                "revalidating": refreshing,
                "servingLastPrepared": refreshing,
                "progress": lock.get("progress") if lock else None,
                "stage": lock.get("stage") if lock else None,
            }
            if source_stale:
                result["latestAvailableRound"] = self._latest_completed_round(year)
            return result
        if lock:
            return {**lock, "status": "generating", "stale": False, "servingLastPrepared": False}
        if failure:
            return {**failure, "status": "failed", "stale": False, "servingLastPrepared": False}
        return {
            "season": year,
            "status": "missing",
            "schemaVersion": SCHEMA_VERSION,
            "calculationVersion": CALCULATION_VERSION,
            "stale": False,
            "servingLastPrepared": False,
        }

    def request(self, year: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return prepared data when possible and ensure one generation is running."""
        loaded = self.load(year)
        if loaded:
            payload, manifest = loaded
            stale = self._source_has_new_round(year, manifest)
            if stale and not self._recent_failure(year):
                self.start_generation(year, force=True)
            state = self.status(year, check_source=False)
            state["stale"] = stale
            state["revalidating"] = stale and state["status"] == "generating"
            state["servingLastPrepared"] = stale
            if stale:
                state["latestAvailableRound"] = self._latest_completed_round(year)
            payload.setdefault("meta", {}).update(
                {
                    "cache": state,
                    "stale": stale,
                    "revalidating": state["revalidating"],
                }
            )
            return payload, state
        if not self._recent_failure(year):
            self.start_generation(year)
        return None, self.status(year, check_source=False)

    def start_generation(self, year: int, *, force: bool = False) -> bool:
        """Atomically elect one worker, then generate without blocking the request."""
        if not force and self.load(year):
            return False
        if not self._acquire_lock(year):
            return False
        thread = threading.Thread(
            target=self._generate_with_lock,
            args=(year,),
            name=f"season-cache-{year}",
            daemon=True,
        )
        thread.start()
        return True

    def generate_now(self, year: int, *, force: bool = False) -> dict[str, Any]:
        """Blocking entry point for deployment scripts and administrators."""
        if not force:
            loaded = self.load(year)
            if loaded and not self._source_has_new_round(year, loaded[1]):
                return loaded[1]
        if not self._acquire_lock(year):
            raise RuntimeError(f"Season {year} is already being generated.")
        self._generate_with_lock(year)
        loaded = self.load(year)
        if not loaded:
            failure = self._read_json(self._season_dir(year) / "last-failure.json")
            raise RuntimeError((failure or {}).get("error", f"Season {year} generation failed."))
        return loaded[1]

    def load(self, year: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
        season_dir = self._season_dir(year)
        current = self._read_text(season_dir / "CURRENT")
        if not current or "/" in current or current.startswith("."):
            return None
        generation_dir = season_dir / "generations" / current
        manifest = self._read_json(generation_dir / "manifest.json")
        data_file = generation_dir / "analysis.json.gz"
        if not self._valid_manifest(year, manifest) or not data_file.is_file():
            return None
        try:
            compressed = data_file.read_bytes()
            if hashlib.sha256(compressed).hexdigest() != manifest.get("dataSha256"):
                return None
            payload = json.loads(gzip.decompress(compressed))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if payload.get("meta", {}).get("season") != year:
            return None
        return payload, manifest

    def _generate_with_lock(self, year: int) -> None:
        started = time.monotonic()
        available_rounds: list[int] = []
        failed_rounds: list[int] = []
        warnings: list[str] = []
        try:
            self._update_lock(year, "loading event schedule", 3)
            schedule = self.schedule_loader(year)
            latest_round = self._latest_completed_round(year, schedule)
            if latest_round < 1:
                raise RuntimeError("No completed championship rounds are available yet.")

            def progress(stage: str, percent: int, details: dict[str, Any] | None = None) -> None:
                self._update_lock(year, stage, percent, details)

            payload = self.builder(
                year,
                self.fastf1_cache_dir,
                1,
                latest_round,
                True,
                progress_callback=progress,
            )
            available_rounds = list(payload.get("meta", {}).get("completedRounds") or [])
            failed_rounds = sorted(
                {int(row["round"]) for row in payload.get("errors", []) if row.get("round") is not None}
            )
            warnings = [str(row.get("message")) for row in payload.get("errors", []) if row.get("message")]
            if not available_rounds:
                raise RuntimeError(payload.get("message") or "No race data could be prepared.")
            self._update_lock(year, "validating cache", 94)
            generated_at = _iso_now()
            payload.setdefault("meta", {}).update(
                {
                    "generatedAt": generated_at,
                    "dataFreshness": "Shared persistent season cache generated from FastF1 timing data",
                }
            )
            generation_id = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
            staging = self._season_dir(year) / "staging" / generation_id
            staging.mkdir(parents=True, exist_ok=False)
            raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
            compressed = gzip.compress(raw, compresslevel=6, mtime=0)
            (staging / "analysis.json.gz").write_bytes(compressed)
            manifest = {
                "season": year,
                "status": "ready",
                "schemaVersion": SCHEMA_VERSION,
                "calculationVersion": CALCULATION_VERSION,
                "generationId": generation_id,
                "generatedAt": generated_at,
                "lastCompletedRound": max(available_rounds),
                "sourceLastUpdatedAt": self._source_timestamp(schedule, latest_round),
                "generationDurationSeconds": round(time.monotonic() - started, 3),
                "availableRounds": available_rounds,
                "failedRounds": failed_rounds,
                "skippedRounds": [
                    number for number in range(1, latest_round + 1) if number not in available_rounds
                ],
                "warnings": warnings,
                "complete": not failed_rounds and max(available_rounds) >= latest_round,
                "partial": bool(failed_rounds),
                "dataSha256": hashlib.sha256(compressed).hexdigest(),
                "dataBytes": len(compressed),
            }
            self._write_json(staging / "manifest.json", manifest)
            final_dir = self._season_dir(year) / "generations" / generation_id
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final_dir)
            self._atomic_write_text(self._season_dir(year) / "CURRENT", generation_id)
            (self._season_dir(year) / "last-failure.json").unlink(missing_ok=True)
            self._update_lock(year, "complete", 100)
            self._prune_generations(year, keep=2)
        except Exception as exc:
            self._write_json(
                self._season_dir(year) / "last-failure.json",
                {
                    "season": year,
                    "failedAt": _iso_now(),
                    "error": str(exc),
                    "availableRounds": available_rounds,
                    "failedRounds": failed_rounds,
                    "warnings": warnings,
                },
            )
        finally:
            (self._season_dir(year) / "generation.lock").unlink(missing_ok=True)

    def _acquire_lock(self, year: int) -> bool:
        season_dir = self._season_dir(year)
        season_dir.mkdir(parents=True, exist_ok=True)
        lock = season_dir / "generation.lock"
        if lock.exists() and self._lock_is_stale(lock):
            lock.unlink(missing_ok=True)
        record = {
            "season": year,
            "status": "generating",
            "startedAt": _iso_now(),
            "updatedAt": _iso_now(),
            "pid": os.getpid(),
            "stage": "waiting to start",
            "progress": 0,
        }
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def _update_lock(
        self, year: int, stage: str, progress: int, details: dict[str, Any] | None = None
    ) -> None:
        lock = self._read_lock(year) or {"season": year, "status": "generating", "startedAt": _iso_now()}
        lock.update(
            {
                "stage": stage,
                "progress": max(0, min(100, int(progress))),
                "updatedAt": _iso_now(),
                "details": details or {},
            }
        )
        self._atomic_write_json(self._season_dir(year) / "generation.lock", lock)

    def _read_lock(self, year: int) -> dict[str, Any] | None:
        lock = self._season_dir(year) / "generation.lock"
        if not lock.exists():
            return None
        if self._lock_is_stale(lock):
            lock.unlink(missing_ok=True)
            return None
        return self._read_json(lock)

    def _lock_is_stale(self, path: Path) -> bool:
        record = self._read_json(path) or {}
        timestamp = record.get("updatedAt") or record.get("startedAt")
        if timestamp:
            try:
                updated = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                return (_utc_now() - updated.astimezone(timezone.utc)).total_seconds() > self.stale_lock_seconds
            except ValueError:
                pass
        return self._age_seconds(path) > self.stale_lock_seconds

    def _source_has_new_round(self, year: int, manifest: dict[str, Any]) -> bool:
        if year != _utc_now().year:
            return False
        try:
            return self._latest_completed_round(year) > int(manifest.get("lastCompletedRound") or 0)
        except Exception:
            # Revalidation must never prevent a valid prepared dataset from
            # being served when the schedule provider is temporarily offline.
            return False

    def _recent_failure(self, year: int, retry_after_seconds: int = 300) -> bool:
        failure = self._season_dir(year) / "last-failure.json"
        return failure.exists() and self._age_seconds(failure) < retry_after_seconds

    def _latest_completed_round(self, year: int, schedule: list[dict[str, Any]] | None = None) -> int:
        events = schedule if schedule is not None else self.schedule_loader(year)
        today = _utc_now().date()
        completed = [
            int(event["round"])
            for event in events
            if int(event.get("round") or 0) > 0 and self._event_date(event) < today
        ]
        return max(completed, default=0)

    @staticmethod
    def _event_date(event: dict[str, Any]) -> date:
        value = event.get("date")
        if not value:
            return date.max
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return date.max

    def _source_timestamp(self, schedule: list[dict[str, Any]], round_number: int) -> str | None:
        event = next((row for row in schedule if int(row.get("round") or 0) == round_number), None)
        return str(event.get("date")) if event and event.get("date") else None

    def _valid_manifest(self, year: int, manifest: dict[str, Any] | None) -> bool:
        return bool(
            manifest
            and manifest.get("season") == year
            and manifest.get("status") == "ready"
            and manifest.get("schemaVersion") == SCHEMA_VERSION
            and manifest.get("calculationVersion") == CALCULATION_VERSION
            and manifest.get("generationId")
            and manifest.get("dataSha256")
        )

    def _season_dir(self, year: int) -> Path:
        return self.root / str(year)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, separators=(",", ":"), default=str), encoding="utf-8")

    def _atomic_write_json(self, path: Path, value: dict[str, Any]) -> None:
        self._atomic_write_text(path, json.dumps(value, separators=(",", ":"), default=str))

    @staticmethod
    def _atomic_write_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _age_seconds(path: Path) -> float:
        try:
            return max(0.0, time.time() - path.stat().st_mtime)
        except OSError:
            return 0.0

    def _prune_generations(self, year: int, keep: int) -> None:
        generations = self._season_dir(year) / "generations"
        if not generations.exists():
            return
        entries = sorted(
            (entry for entry in generations.iterdir() if entry.is_dir()),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        for old in entries[keep:]:
            shutil.rmtree(old, ignore_errors=True)
