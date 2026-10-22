"""Ownership Walker — the control-chain traversal, bounded by Markovian.

Python owns data access and judgement; the Markovian engine owns the traversal
and its bounding. The two meet over a subprocess rather than an HTTP service:
nothing to start, nothing to leave running, and a clean checkout can execute it
after one `npm install`.

Why the engine is load-bearing here rather than decorative. A chain walk is the
one unbounded thing Clearline does: each hop adds a company, its jurisdiction
and its relationships, and appending that to a transcript makes cost grow with
depth until a deep chain stops being demoable. Markovian makes each hop one
chunk carrying a bounded state summary, so cost per hop is flat. It also owns
termination — a listed entity or a root emits [TASK_COMPLETE], a revisited node
ends the walk as a cycle, and maxChunks caps depth — and reports the accounting
the trace records.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engines" / "markovian"
WALK = ENGINE / "src" / "walk.ts"


class WalkerUnavailable(RuntimeError):
    pass


def _tsx() -> Path:
    for candidate in (ENGINE / "node_modules" / ".bin" / "tsx.cmd",
                      ENGINE / "node_modules" / ".bin" / "tsx"):
        if candidate.exists():
            return candidate
    raise WalkerUnavailable(
        f"tsx not found in {ENGINE / 'node_modules'}. Run: cd engines/markovian && npm install"
    )


def walk(vendor_id: str, max_depth: int = 5, carryover_tokens: int = 640,
         timeout: int = 60) -> dict[str, Any]:
    """Walk the control chain upward from a vendor.

    Returns the engine's own record: the chain, why it stopped, any listed
    entity found, and the efficiency accounting.
    """
    if not WALK.exists():
        raise WalkerUnavailable(f"{WALK} missing")
    if shutil.which("node") is None:
        raise WalkerUnavailable("node is not on PATH; the Markovian engine needs it")

    result = subprocess.run(
        [str(_tsx()), str(WALK), "--vendor", vendor_id,
         "--max-depth", str(max_depth), "--carryover", str(carryover_tokens)],
        cwd=str(ENGINE), capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise WalkerUnavailable(
            f"walk exited {result.returncode}: {(result.stderr or '').strip()[:300]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WalkerUnavailable(f"walk returned non-JSON: {error}") from error


def ownership_walker(vendor: dict, trace, max_depth: int = 5) -> tuple[list[dict], bool]:
    """Agent 4. Degrades to an empty chain rather than failing the screening.

    Returns (chain, walked). The flag exists because "no indirect exposure
    found" and "the chain was never walked" are different claims and an empty
    list cannot distinguish them -- a reviewer reading a clean result has to
    know which one it is.
    """
    vendor_id = vendor["vendor_id"]
    with trace.agent("ownership_walker", vendor_id=vendor_id, max_depth=max_depth):
        try:
            record = walk(vendor_id, max_depth=max_depth)
        except (WalkerUnavailable, subprocess.TimeoutExpired) as error:
            trace.event("walker.unavailable", error=str(error)[:200],
                        consequence="indirect exposure not assessed")
            return [], False

        engine = record.get("engine", {})
        trace.tool(
            "markovian.walk",
            engine=engine.get("name"),
            implementation=engine.get("implementation"),
            chunks=engine.get("chunks"),
            carryover_tokens=(engine.get("chunkConfig") or {}).get("carryoverTokens"),
            token_label=engine.get("tokenLabel"),
            standard_cost=engine.get("standardCost"),
            markovian_cost=engine.get("markovianCost"),
            terminated_because=record.get("terminated_because"),
        )

        chain = record.get("chain", [])
        for hop in chain:
            trace.event("walker.hop", depth=hop.get("depth"), name=hop.get("name"),
                        country=hop.get("country"), relation=hop.get("relation"),
                        sanctions_hit=bool(hop.get("sanctions_hit")))

        hits = [h for h in chain if h.get("sanctions_hit")]
        if hits:
            trace.branch(
                f"control chain reaches listed entity "
                f"{hits[0]['sanctions_hit']['caption']!r} at depth {hits[0]['depth']}",
                "INDIRECT_EXPOSURE_FOUND",
            )
        else:
            trace.event("walker.clean", terminated_because=record.get("terminated_because"),
                        hops=len(chain))
        return chain, True
