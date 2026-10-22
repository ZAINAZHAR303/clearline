"""Summarise a run trace: per-agent latency, reasoning spend, and branches.

    python scripts/trace_summary.py                 # most recent run
    python scripts/trace_summary.py logs/run-*.jsonl
    python scripts/trace_summary.py --all           # every run, one line each

This is the measurement behind two claims the submission makes:

  1. "We spend reasoning in proportion to risk" -- reasoning_tokens per call,
     taken from the provider's own usage accounting, not estimated.
  2. "The system runs inside a predictable budget" -- wall-clock per agent.

It is also the source of the demo's budget histogram, so it stays a script
rather than something retyped into a terminal.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / "logs"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarise(path: Path, verbose: bool = True) -> dict:
    events = load(path)
    if not events:
        return {}

    subject = next((e.get("subject") for e in events if e["kind"] == "run.start"), "?")
    end = next((e for e in events if e["kind"] == "run.end"), {})

    per_agent: dict[str, dict] = defaultdict(lambda: {"ms": 0, "calls": 0, "reasoning": 0, "completion": 0})
    for event in events:
        if event["kind"] == "agent.end":
            per_agent[event["agent"]]["ms"] += event.get("ms", 0)
        elif event["kind"] == "llm.result":
            agent = per_agent[event["agent"]]
            agent["calls"] += 1
            agent["reasoning"] += event.get("reasoning_tokens") or 0
            agent["completion"] += event.get("completion_tokens") or 0
            agent["tier"] = event.get("tier")

    total_ms = sum(a["ms"] for a in per_agent.values())
    total_reasoning = sum(a["reasoning"] for a in per_agent.values())

    if not verbose:
        return {"file": path.name, "subject": subject, "outcome": end.get("outcome"),
                "seconds": round(total_ms / 1000, 1), "reasoning": total_reasoning}

    print(f"\n{path.name}   subject={subject}   outcome={end.get('outcome')}   "
          f"confidence={end.get('confidence')}")
    print(f"{'agent':<14}{'tier':<8}{'calls':>6}{'seconds':>9}{'reasoning':>11}{'completion':>12}"
          f"{'  reasoning share':>18}")
    print("-" * 80)
    for name, a in sorted(per_agent.items(), key=lambda kv: -kv[1]["ms"]):
        share = f"{a['reasoning'] / a['completion']:.0%}" if a["completion"] else "-"
        print(f"{name:<14}{a.get('tier') or '-':<8}{a['calls']:>6}{a['ms'] / 1000:>9.1f}"
              f"{a['reasoning']:>11}{a['completion']:>12}{share:>18}")
    print("-" * 80)
    print(f"{'TOTAL':<14}{'':<8}{sum(a['calls'] for a in per_agent.values()):>6}"
          f"{total_ms / 1000:>9.1f}{total_reasoning:>11}")

    branches = [e for e in events if e["kind"] == "branch"]
    if branches:
        print("\nbranches taken")
        for b in branches:
            print(f"  {b['taken']:<28} <- {b['reason'][:60]}")

    verdicts = [e for e in events if e["kind"] == "verdict"]
    if verdicts:
        print("\ncritic verdicts")
        for v in verdicts:
            print(f"  round {v.get('round')}: {v['verdict']}")

    exhausted = [e for e in events if e["kind"] == "llm.budget_exhausted"]
    for e in exhausted:
        print(f"\n  ! {e['agent']} exhausted {e['max_tokens']} tokens on reasoning "
              f"-> escalated to {e['next_max_tokens']}")

    return {}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        rows = [summarise(p, verbose=False) for p in sorted(LOGS.glob("run-*.jsonl"))]
        print(f"{'file':<42}{'subject':<9}{'outcome':<11}{'secs':>7}{'reasoning':>11}")
        for r in rows:
            if r:
                print(f"{r['file']:<42}{r['subject']:<9}{str(r['outcome']):<11}"
                      f"{r['seconds']:>7}{r['reasoning']:>11}")
        return 0

    paths = [Path(a) for a in args] or sorted(LOGS.glob("run-*.jsonl"))[-1:]
    if not paths:
        print("no traces in logs/ -- run: python -m clearline.run --vendor V0001 --fake")
        return 1
    for path in paths:
        summarise(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
