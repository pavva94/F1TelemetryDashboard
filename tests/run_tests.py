from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    failures = 0
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        module = importlib.import_module(path.stem)
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            try:
                fn()
                print(f"PASS {path.name}::{name}")
            except Exception as exc:
                failures += 1
                print(f"FAIL {path.name}::{name}: {exc!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

