"""CLI entry point.

    python -m clearline.run --vendor V0001
    python -m clearline.run --vendor V0004 --fake      # no model needed
"""

from __future__ import annotations

import argparse
import os
import sys

from .orchestrator import screen

BOX = {"BLOCK": "\033[91m", "CLEAR": "\033[92m", "ESCALATE": "\033[93m"}
RESET = "\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser(prog="clearline")
    parser.add_argument("--vendor", required=True, help="vendor_id, e.g. V0001")
    parser.add_argument("--fake", action="store_true",
                        help="deterministic canned model responses; no API key needed")
    args = parser.parse_args()

    if args.fake:
        os.environ["CLEARLINE_FAKE_LLM"] = "1"

    decision, trace = screen(args.vendor)
    if decision is None:
        print(f"vendor {args.vendor} not found", file=sys.stderr)
        return 1

    colour = BOX.get(decision.decision, "")
    print()
    print(f"  {colour}{decision.decision}{RESET}  confidence {decision.confidence:.2f}")
    print(f"  {decision.rationale}")
    if decision.evidence:
        print("\n  evidence")
        for item in decision.evidence:
            print(f"    - {item.claim}  [{item.source} {item.row_ref}]")
    if decision.unresolved_conflicts:
        print("\n  unresolved")
        for conflict in decision.unresolved_conflicts:
            print(f"    ! {conflict}")
    if decision.caveats:
        print("\n  caveats")
        for caveat in decision.caveats:
            print(f"    ~ {caveat}")
    if decision.human_question:
        print(f"\n  ask the reviewer: {decision.human_question}")
    print(f"\n  trace: {trace.path}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
