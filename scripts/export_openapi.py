"""Write the OpenAPI definition to a file.

    python scripts/export_openapi.py

The definition is what APIMatic turns into SDKs, a documentation portal and
a Context Plugin, so it is committed rather than left to be fetched from a
running server. A reader of the repository, or a tool, gets the contract
without having to start anything.

Exits non-zero if the committed copy is out of date, so it can be used as a
check rather than only as a generator:

    python scripts/export_openapi.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from leash.api import app  # noqa: E402

DEFAULT = ROOT / "api" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT))
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the file on disk does not match the live definition",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    current = render()

    if args.check:
        if not out.exists():
            print(f"{out} does not exist. Run this without --check.")
            return 1
        if out.read_text(encoding="utf-8") != current:
            print(f"{out} is out of date. Run scripts/export_openapi.py.")
            return 1
        print(f"{out} matches the API.")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(current, encoding="utf-8")

    spec = json.loads(current)
    endpoints = sum(len(ops) for ops in spec["paths"].values())
    print(f"wrote {out}")
    print(f"  {endpoints} endpoints, {len(spec['components']['schemas'])} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
