"""Run every red-team campaign against the demo mandate.

    python scripts/redteam.py

Offline and deterministic by default. With LEASH_GROQ_API_KEY set it also runs
the LLM adversary, which is the one that finds techniques nobody listed.

The output is the artifact: how many ways were tried, which rule stopped each
one, and whether the mandate held.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leash.adversary import LLMAdversary, StrategyAdversary  # noqa: E402
from leash.config import settings  # noqa: E402
from leash.llm import build_brain  # noqa: E402
from leash.redteam import (  # noqa: E402
    ALL_OBJECTIVES,
    Suite,
    run_campaign,
    world_from,
)
from leash.store import build_demo_store, demo_mandate  # noqa: E402


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Attack the demo mandate.")
    parser.add_argument("--attempts", type=int, default=120)
    parser.add_argument("--out", default="artifacts/redteam.json")
    parser.add_argument("--llm", action="store_true", help="also run the LLM adversary")
    args = parser.parse_args(argv)

    store = build_demo_store()
    mandate = demo_mandate()
    world = world_from(store, mandate)

    adversaries = [StrategyAdversary()]
    if args.llm:
        brain = build_brain(settings())
        if brain is None:
            print("no LEASH_GROQ_API_KEY set, running the offline adversary only\n")
        else:
            adversaries.append(LLMAdversary(brain))

    reports = []
    for adversary in adversaries:
        for objective_type in ALL_OBJECTIVES:
            reports.append(
                await run_campaign(
                    mandate=demo_mandate(),
                    world=world,
                    objective=objective_type(),
                    adversary=adversary,
                    directory=store.directory,
                    max_attempts=args.attempts,
                )
            )

    suite = Suite(tuple(reports))
    print(suite.table())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    suite.write(str(out))
    print(f"\nfull log written to {out}")

    return 0 if suite.held else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
