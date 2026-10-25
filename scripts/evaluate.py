"""Measure accuracy against the labelled set, instead of asserting it.

    python scripts/evaluate.py --fake      # offline, deterministic
    python scripts/evaluate.py             # live model

Eight demo cases passing proves very little -- a reader is entitled to wonder
whether eight cases were chosen because they pass. This runs every labelled
case in data/sample/vendor_master.json and reports what it got wrong.

The two error types are NOT symmetric, so they are never averaged into a single
"accuracy" number:

  MISS          a genuinely exposed vendor was CLEARED. This is the legal
                violation -- the one the product exists to prevent.
  FALSE BLOCK   a clean vendor was BLOCKED. This freezes a real supplier and
                stops a production line.
  ESCALATION    neither failure. It is review workload, and for an exposed
                vendor it is a SAFE outcome: a human looks at it.

A tool that escalates everything has no misses and is useless, so escalation
rate is reported alongside, not hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"
LOGS = ROOT / "logs"

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def labelled() -> dict[str, dict]:
    """Demo cases and evaluation cases, in one labelled set.

    Demo cases carry an expected decision; evaluation cases carry exposure
    truth plus the decisions that would be acceptable. Both are normalised to
    the same shape here.
    """
    book = json.loads((SAMPLE / "vendor_master.json").read_text(encoding="utf-8"))
    out: dict[str, dict] = {}

    for vid, case in book.get("_eval_cases", {}).items():
        out[vid] = {
            "category": case["category"],
            "exposed": case["exposed"],
            "acceptable": case["acceptable"],
            "why": case["why"],
        }
    for vid, case in book.get("_demo_cases", {}).items():
        expect = case["expect"]
        out[vid] = {
            "category": "demo",
            "exposed": expect == "BLOCK",
            "acceptable": [expect] if expect != "BLOCK" else ["BLOCK", "ESCALATE"],
            "why": case["why"],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if args.fake:
        os.environ["CLEARLINE_FAKE_LLM"] = "1"

    from clearline.orchestrator import screen

    cases = labelled()
    book = json.loads((SAMPLE / "vendor_master.json").read_text(encoding="utf-8"))["vendors"]
    names = {v["vendor_id"]: v["legal_name"] for v in book}

    started = time.time()
    rows = []
    for vid, case in cases.items():
        decision, _ = screen(vid)
        got = decision.decision if decision else "ERROR"
        if case["exposed"]:
            outcome = "MISS" if got == "CLEAR" else ("caught" if got == "BLOCK" else "escalated")
        else:
            outcome = "FALSE BLOCK" if got == "BLOCK" else ("correct" if got == "CLEAR" else "escalated")
        rows.append({**case, "vendor_id": vid, "legal_name": names.get(vid, vid),
                     "decision": got, "outcome": outcome,
                     "acceptable_hit": got in case["acceptable"]})
    elapsed = time.time() - started

    exposed = [r for r in rows if r["exposed"]]
    clean = [r for r in rows if not r["exposed"]]
    misses = [r for r in exposed if r["outcome"] == "MISS"]
    false_blocks = [r for r in clean if r["outcome"] == "FALSE BLOCK"]
    escalated = [r for r in rows if r["decision"] == "ESCALATE"]

    print()
    print(f"  LABELLED SET   {len(rows)} cases · {len(exposed)} exposed · {len(clean)} clean"
          f"   [{'fixture' if args.fake else 'live model'}, {elapsed:.0f}s]")
    print()
    caught = len(exposed) - len(misses)
    mcol = GREEN if not misses else RED
    fcol = GREEN if not false_blocks else RED
    print(f"  {mcol}MISSES          {len(misses)}/{len(exposed)}{RESET}   exposed vendor cleared "
          f"— the legal failure                recall {caught}/{len(exposed)}")
    print(f"  {fcol}FALSE BLOCKS    {len(false_blocks)}/{len(clean)}{RESET}   clean vendor blocked "
          f"— freezes a real supplier")
    print(f"  {DIM}ESCALATIONS     {len(escalated)}/{len(rows)}{RESET}   neither failure; review workload")

    by_cat: dict[str, list] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)

    print(f"\n  {'category':<28}{'n':>3}  {'exposed':>8}  result")
    print(f"  {'-' * 68}")
    for cat in sorted(by_cat):
        group = by_cat[cat]
        bad = [r for r in group if r["outcome"] in ("MISS", "FALSE BLOCK")]
        esc = sum(1 for r in group if r["decision"] == "ESCALATE")
        mark = f"{RED}{len(bad)} wrong{RESET}" if bad else f"{GREEN}all correct{RESET}"
        extra = f"  ({esc} escalated)" if esc else ""
        print(f"  {cat:<28}{len(group):>3}  {str(group[0]['exposed']):>8}  {mark}{extra}")

    if misses or false_blocks:
        print(f"\n  {RED}FAILURES{RESET}")
        for r in misses + false_blocks:
            print(f"    {r['outcome']:<12} {r['vendor_id']}  {r['legal_name'][:40]:<40} "
                  f"-> {r['decision']}")
            print(f"    {DIM}{r['why'][:96]}{RESET}")

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "fixture" if args.fake else "live model",
        "cases": len(rows), "exposed": len(exposed), "clean": len(clean),
        "misses": len(misses), "false_blocks": len(false_blocks),
        "escalations": len(escalated),
        "recall_on_exposure": round(caught / len(exposed), 4) if exposed else None,
        "false_block_rate": round(len(false_blocks) / len(clean), 4) if clean else None,
        "seconds": round(elapsed, 1),
        "rows": rows,
    }
    LOGS.mkdir(exist_ok=True)
    out = LOGS / f"evaluation-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n  report: {out}\n")

    # A miss is a failing result. A false block is not ideal but is survivable.
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
