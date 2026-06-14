from __future__ import annotations

import argparse
from pathlib import Path

from .detectors import analyze_laps
from .dashboard import build_dashboard_payload
from .fastf1_loader import load_fastf1_session, select_lap, weather_context_for_lap
from .report import render_json, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fastf1-lapdiff")
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare = subparsers.add_parser("compare", help="Compare two FastF1 laps")
    compare.add_argument("--year", type=int, required=True)
    compare.add_argument("--event", required=True)
    compare.add_argument("--session", required=True)
    compare.add_argument("--driver", required=True, help="Compared driver. Also used for reference unless --reference-driver is set.")
    compare.add_argument("--lap", type=int, required=True, help="Compared lap number.")
    compare.add_argument("--reference-driver", help="Reference driver. Defaults to --driver.")
    compare.add_argument("--reference-lap", type=int, help="Reference lap number. Defaults to reference driver's fastest lap.")
    compare.add_argument("--cache-dir", default=".fastf1-cache")
    compare.add_argument("--format", choices=["markdown", "json", "dashboard-json"], default="markdown")
    compare.add_argument("--output", help="Optional output file.")

    args = parser.parse_args(argv)
    if args.command == "compare":
        return _compare(args)
    return 1


def _compare(args: argparse.Namespace) -> int:
    session = load_fastf1_session(args.year, args.event, args.session, args.cache_dir)
    reference_driver = args.reference_driver or args.driver
    reference = select_lap(session, reference_driver, lap_number=args.reference_lap, fastest=args.reference_lap is None)
    compared = select_lap(session, args.driver, lap_number=args.lap)
    weather = weather_context_for_lap(session, args.lap)

    if args.format == "dashboard-json":
        import json

        rendered = json.dumps(build_dashboard_payload(reference, compared, weather), indent=2, default=str)
    else:
        report = analyze_laps(reference, compared, weather)
        rendered = render_json(report) if args.format == "json" else render_markdown(report)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
