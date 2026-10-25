"""Screen the whole vendor book and produce a reviewer's worklist.

    python -m clearline.batch --fake            # all vendors
    python -m clearline.batch --fake --limit 40

A compliance officer does not screen one vendor at a time from a command
line. They open a queue on Monday morning. This produces that queue:
everything that needs a human, and a count of everything that does not.

The design point the output rests on: **a tool that makes someone look at all
200 vendors has failed.** Of 200, four need attention. The other 196 are a
number, not a list.

Memory is NOT written during a batch
------------------------------------
`screen()` normally remembers its decision so a later correction has something
to attach to. A sweep skips that, for two reasons. A sweep produces
recommendations, while memory is meant to record adjudications -- what a human
decided. And eight workers writing one memory file is a race that would corrupt
the ledger the product's credibility rests on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .orchestrator import screen

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "queue"
MASTER = ROOT / "data" / "sample" / "vendor_master.json"

NEEDS_HUMAN = {"BLOCK", "ESCALATE"}


def _headline(decision) -> str:
    """One line a reviewer can triage on without opening the case."""
    if decision.evidence:
        return decision.evidence[0].claim
    if decision.unresolved_conflicts:
        return decision.unresolved_conflicts[0]
    return decision.rationale.split(".")[0]


def screen_one(vendor: dict) -> dict[str, Any]:
    started = time.time()
    try:
        decision, trace = screen(vendor["vendor_id"], remember_decision=False)
        if decision is None:
            return {"vendor_id": vendor["vendor_id"], "error": "not found"}
        return {
            "vendor_id": vendor["vendor_id"],
            "legal_name": vendor["legal_name"],
            "country": vendor.get("country"),
            "annual_spend_usd": vendor.get("annual_spend_usd"),
            "category": vendor.get("category"),
            "decision": decision.decision,
            "confidence": round(decision.confidence, 2),
            "headline": _headline(decision),
            "rationale": decision.rationale,
            "evidence": [e.model_dump() for e in decision.evidence],
            "unresolved": decision.unresolved_conflicts,
            "caveats": decision.caveats,
            "question": decision.human_question,
            "trace": trace.path.name,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as error:  # noqa: BLE001 -- one bad vendor must not stop the sweep
        return {"vendor_id": vendor["vendor_id"],
                "legal_name": vendor.get("legal_name"),
                "error": str(error)[:200]}


def run(limit: int | None = None, workers: int = 8) -> dict[str, Any]:
    vendors = json.loads(MASTER.read_text(encoding="utf-8"))["vendors"]
    if limit:
        vendors = vendors[:limit]

    started = time.time()
    results: list[dict] = []
    # Subprocess-bound (the engines are separate processes), so threads help.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(screen_one, v): v for v in vendors}
        for done, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if done % 25 == 0:
                print(f"  {done}/{len(vendors)}", flush=True)

    results.sort(key=lambda r: r["vendor_id"])
    errors = [r for r in results if r.get("error")]
    ok = [r for r in results if not r.get("error")]

    needs = [r for r in ok if r["decision"] in NEEDS_HUMAN]
    # Highest exposure first: a blocked vendor you already pay is more urgent
    # than a blocked vendor you have not onboarded.
    needs.sort(key=lambda r: (r["decision"] != "BLOCK", -(r.get("annual_spend_usd") or 0)))
    cleared = [r for r in ok if r["decision"] == "CLEAR"]

    counts: dict[str, int] = {}
    for r in ok:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_screened": len(ok),
        "elapsed_seconds": round(time.time() - started, 1),
        "counts": counts,
        "needs_attention": needs,
        "cleared": [{k: r[k] for k in ("vendor_id", "legal_name", "country",
                                       "decision", "annual_spend_usd")} for r in cleared],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="clearline.batch")
    parser.add_argument("--fake", action="store_true",
                        help="deterministic responses; no API key needed")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.fake:
        os.environ["CLEARLINE_FAKE_LLM"] = "1"

    QUEUE.mkdir(parents=True, exist_ok=True)
    report = run(limit=args.limit, workers=args.workers)
    (QUEUE / "latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    counts = report["counts"]
    print(f"\n  screened {report['total_screened']} vendors in {report['elapsed_seconds']}s")
    print(f"  {' · '.join(f'{k} {v}' for k, v in sorted(counts.items()))}")
    print(f"\n  NEEDS A HUMAN: {len(report['needs_attention'])}")
    for case in report["needs_attention"][:10]:
        spend = case.get("annual_spend_usd") or 0
        print(f"    {case['decision']:<9} {case['legal_name'][:38]:<38} "
              f"${spend:>9,}  {case['headline'][:46]}")
    if report["errors"]:
        print(f"\n  errors: {len(report['errors'])}")
    print(f"\n  queue written to data/queue/latest.json -> open the viewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
