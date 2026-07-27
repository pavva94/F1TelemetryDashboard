"""Explicit administrator command for preparing shared season caches."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .fastf1_loader import available_seasons
from .season_cache import SeasonCacheManager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute persistent season-analysis data.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--season", type=int, help="Season to prepare.")
    target.add_argument("--all", action="store_true", help="Prepare every configured season.")
    parser.add_argument("--force", action="store_true", help="Rebuild even when a valid cache exists.")
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("FASTF1_CACHE_DIR", str(Path.cwd() / ".fastf1-cache")),
        help="FastF1 source cache directory.",
    )
    parser.add_argument(
        "--season-cache-dir",
        default=os.environ.get("SEASON_ANALYSIS_CACHE_DIR"),
        help="Prepared season cache directory (defaults to <cache-dir>/seasons).",
    )
    args = parser.parse_args(argv)

    season_cache_dir = args.season_cache_dir or str(Path(args.cache_dir) / "seasons")
    manager = SeasonCacheManager(season_cache_dir, args.cache_dir)
    seasons = available_seasons() if args.all else [args.season]
    for season in seasons:
        print(f"Preparing {season} season analysis…", flush=True)
        manifest = manager.generate_now(season, force=args.force)
        print(
            f"Ready: {season}, through Round {manifest['lastCompletedRound']} "
            f"in {manifest['generationDurationSeconds']}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
