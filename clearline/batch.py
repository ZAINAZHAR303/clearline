"""Portfolio screening — the whole vendor book, not one vendor.

    python -m clearline.batch --fake            # offline, deterministic
    python -m clearline.batch                   # live model
    python -m clearline.batch --limit 50

A compliance officer does not screen one supplier; they have hundreds and no
way to know which deserve attention. Running the full agent system over every
vendor would answer that, and would also be absurd: most vendors have nothing
to look at, and deliberating over them is the cost that stops a tool like this
ever being run.

So screening is two stages, and the split is the same thesis as the reasoning
budget -- spend effort in proportion to risk:

  TRIAGE    deterministic, no model, every vendor. Four cheap tests, each of
            which is a reason a human would want a second look.
  REVIEW    the full agent system, only for vendors triage flagged.

On the sample book that is 9 of 200. The other 191 are cleared with a recorded
reason, not silently dropped -- "nothing matched" and "we never looked" have to
stay distinguishable, here as everywhere else in this system.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from .matching import is_generic, rank
from .orchestrator import screen

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"
LOGS = ROOT / "logs"

# A candidate scoring below this is fuzzy name noise. On the sample book the
# distribution is bimodal -- exact aliases at 1.0, a couple at 0.6, then a
# cluster at 0.3 and under -- so the gap is where the threshold belongs.
CANDIDATE_THRESHOLD = 0.4
MAX_CHAIN_DEPTH = 5


def _load(name: str, key: str) -> Any:
    return json.loads((SAMPLE / name).read_text(encoding="utf-8"))[key]


class ControlGraph:
    """Cheap reachability over the control graph.

    Deliberately NOT the Markovian walk: this answers only "is there any listed
    entity above this vendor?" so that the expensive, model-assessed walk is
    reserved for vendors where the answer is yes. A cheap test deciding whether
    to spend an expensive one is the same pattern as the reasoning budget.
    """

    def __init__(self) -> None:
        graph = json.loads((SAMPLE / "control_graph.json").read_text(encoding="utf-8"))
        self.nodes = {n["key"]: n for n in graph["nodes"]}
        self.parents: dict[str, list[str]] = {}
        for edge in graph["edges"]:
            self.parents.setdefault(edge["child"], []).append(edge["parent"])
        self.listed = {e["id"] for e in _load("sanctions_sample.json", "entities")}

    def reaches_listed(self, vendor_id: str, depth: int = MAX_CHAIN_DEPTH) -> bool:
        seen = {vendor_id}
        current = vendor_id
        for _ in range(depth):
            parents = self.parents.get(current)
            if not parents:
                return False
            nxt = parents[0]
            if nxt in seen:  # cycle
                return False
            node = self.nodes.get(nxt)
            if node and node.get("entity_id") in self.listed:
                return True
            seen.add(nxt)
            current = nxt
        return False


def triage(vendors: list[dict]) -> dict[str, list[str]]:
    """Which vendors deserve the full agent system, and why.

    Each reason is one a human reviewer would independently recognise, which is
    what makes a fast clear defensible: we can always say what was checked.
    """
    entities = _load("sanctions_sample.json", "entities")
    graph = ControlGraph()
    flagged: dict[str, list[str]] = {}

    for vendor in vendors:
        reasons: list[str] = []

        candidates = rank(vendor, entities, top_n=1)
        if candidates and candidates[0]["_features"]["score"] >= CANDIDATE_THRESHOLD:
            feats = candidates[0]["_features"]
            reasons.append(
                "exact alias of a listed entity" if feats["exact_alias"]
                else f"watchlist candidate (score {feats['score']})"
            )

        if is_generic(vendor["legal_name"]):
            reasons.append("name too generic to resolve")

        if vendor.get("bank_country") != vendor.get("country"):
            reasons.append("banks in a different country than it is registered")

        if graph.reaches_listed(vendor["vendor_id"]):
            reasons.append("control chain reaches a listed entity")

        if reasons:
            flagged[vendor["vendor_id"]] = reasons

    return flagged


def run(fake: bool = False, limit: int | None = None) -> dict[str, Any]:
    if fake:
        os.environ["CLEARLINE_FAKE_LLM"] = "1"

    vendors = _load("vendor_master.json", "vendors")
    if limit:
        vendors = vendors[:limit]
    by_id = {v["vendor_id"]: v for v in vendors}
    total_spend = sum(v["annual_spend_usd"] for v in vendors)

    started = time.time()
    flagged = triage(vendors)
    triage_seconds = time.time() - started

    results = []
    llm_calls = reasoning_tokens = 0
    for vendor_id, reasons in flagged.items():
        decision, trace = screen(vendor_id)
        events = [json.loads(line) for line in
                  trace.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        calls = [e for e in events if e["kind"] == "llm.result"]
        llm_calls += len(calls)
        reasoning_tokens += sum(e.get("reasoning_tokens") or 0 for e in calls)
        results.append({
            "vendor_id": vendor_id,
            "legal_name": by_id[vendor_id]["legal_name"],
            "country": by_id[vendor_id]["country"],
            "annual_spend_usd": by_id[vendor_id]["annual_spend_usd"],
            "triage_reasons": reasons,
            "decision": decision.decision if decision else "ERROR",
            "confidence": decision.confidence if decision else 0.0,
            "rationale": decision.rationale if decision else "",
            "human_question": decision.human_question if decision else "",
            "trace": trace.path.name,
        })

    elapsed = time.time() - started
    order = {"BLOCK": 0, "ESCALATE": 1, "CLEAR": 2, "ERROR": 3}
    results.sort(key=lambda r: (order.get(r["decision"], 9), -r["annual_spend_usd"]))

    counts = {d: sum(1 for r in results if r["decision"] == d)
              for d in ("BLOCK", "ESCALATE", "CLEAR", "ERROR")}
    action = [r for r in results if r["decision"] in ("BLOCK", "ESCALATE")]

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "fixture" if fake else "live model",
        "book": {
            "vendors": len(vendors),
            "annual_spend_usd": total_spend,
        },
        "triage": {
            "needs_review": len(flagged),
            "cleared_without_review": len(vendors) - len(flagged),
            "share_reviewed": round(len(flagged) / len(vendors), 4) if vendors else 0,
            "seconds": round(triage_seconds, 2),
        },
        "decisions": counts,
        "exposure": {
            "spend_reviewed_usd": sum(r["annual_spend_usd"] for r in results),
            "spend_needing_action_usd": sum(r["annual_spend_usd"] for r in action),
        },
        "cost": {
            "wall_clock_seconds": round(elapsed, 1),
            "llm_calls": llm_calls,
            "reasoning_tokens": reasoning_tokens,
        },
        "results": results,
    }

    LOGS.mkdir(exist_ok=True)
    out = LOGS / f"portfolio-{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(out)
    return report


BOX = {"BLOCK": "\033[91m", "CLEAR": "\033[92m", "ESCALATE": "\033[93m", "ERROR": "\033[95m"}
RESET = "\033[0m"


def render(report: dict[str, Any]) -> None:
    book, tri, cost = report["book"], report["triage"], report["cost"]
    exposure = report["exposure"]

    print()
    print(f"  VENDOR BOOK   {book['vendors']} vendors · ${book['annual_spend_usd']:,} annual spend")
    print(f"  TRIAGE        {tri['needs_review']} need review, "
          f"{tri['cleared_without_review']} cleared without it "
          f"({tri['share_reviewed']:.1%} reviewed) in {tri['seconds']}s")
    counts = report["decisions"]
    print(f"  DECISIONS     "
          + "  ".join(f"{BOX[d]}{counts[d]} {d}{RESET}" for d in ("BLOCK", "ESCALATE", "CLEAR")
                      if counts[d]))
    print(f"  EXPOSURE      ${exposure['spend_needing_action_usd']:,} of spend needs action, "
          f"of ${exposure['spend_reviewed_usd']:,} reviewed")
    print(f"  COST          {cost['wall_clock_seconds']}s · {cost['llm_calls']} model calls · "
          f"{cost['reasoning_tokens']:,} reasoning tokens  [{report['mode']}]")

    action = [r for r in report["results"] if r["decision"] in ("BLOCK", "ESCALATE")]
    if action:
        print(f"\n  NEEDS ATTENTION")
        for r in action:
            print(f"    {BOX[r['decision']]}{r['decision']:<9}{RESET} "
                  f"{r['legal_name'][:38]:<38} [{r['country']}] ${r['annual_spend_usd']:>9,}")
            print(f"              {r['rationale'][:104]}")
            if r["human_question"]:
                print(f"              ask: {r['human_question'][:96]}")

    cleared = [r for r in report["results"] if r["decision"] == "CLEAR"]
    if cleared:
        print(f"\n  REVIEWED AND CLEARED")
        for r in cleared:
            print(f"    {BOX['CLEAR']}CLEAR{RESET}     {r['legal_name'][:38]:<38} "
                  f"[{r['country']}]  {r['triage_reasons'][0][:44]}")

    print(f"\n  report: {report['report_path']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(prog="clearline.batch")
    parser.add_argument("--fake", action="store_true",
                        help="deterministic canned model responses; no API key needed")
    parser.add_argument("--limit", type=int, help="screen only the first N vendors")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    report = run(fake=args.fake, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
