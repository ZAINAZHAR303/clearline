"""Memory — reviewer corrections that outlive the run, via the H-MEM engine.

Same subprocess bridge as the walker: Python owns judgement, the TypeScript
engine owns memory semantics, and nothing has to be left running.

What this buys the product. A screening tool that cannot be corrected is worse
than useless, because every false positive it produces costs a supplier
relationship and nobody can stop it recurring. Here a reviewer marks a match
wrong, H-MEM drops its confidence by a known amount, tags it for review and
writes both states to an append-only ledger -- and the next run sees that and
decides differently, citing the correction and who made it.

Degrades to no memory rather than failing a screening: an unavailable engine
should cost recall, not the decision.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engines" / "hmem"
CLI = ENGINE / "src" / "cli.ts"
STATE = ROOT / "data" / "memory" / "hmem.json"


class MemoryUnavailable(RuntimeError):
    pass


def _tsx() -> Path:
    for candidate in (ENGINE / "node_modules" / ".bin" / "tsx.cmd",
                      ENGINE / "node_modules" / ".bin" / "tsx"):
        if candidate.exists():
            return candidate
    raise MemoryUnavailable(
        f"tsx not found in {ENGINE / 'node_modules'}. Run: cd engines/hmem && npm install"
    )


def _run(args: list[str], timeout: int = 45) -> dict[str, Any]:
    if not CLI.exists():
        raise MemoryUnavailable(f"{CLI} missing")
    # Pass the state path through so an isolated memory can be selected per
    # process (tests, demo resets) without touching the default.
    env = {**os.environ}
    if os.environ.get("CLEARLINE_MEMORY_PATH"):
        env["CLEARLINE_MEMORY_PATH"] = os.environ["CLEARLINE_MEMORY_PATH"]
    result = subprocess.run(
        [str(_tsx()), str(CLI), *args],
        cwd=str(ENGINE), capture_output=True, text=True, timeout=timeout, env=env,
    )
    if result.returncode != 0:
        raise MemoryUnavailable((result.stderr or "").strip()[:200] or f"exit {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MemoryUnavailable(f"non-JSON from memory engine: {error}") from error


def recall(vendor_id: str) -> list[dict[str, Any]]:
    try:
        return _run(["recall", "--vendor", vendor_id]).get("memories", [])
    except (MemoryUnavailable, subprocess.TimeoutExpired):
        return []


def remember(vendor_id: str, entity_id: str, decision: str, confidence: float) -> dict[str, Any] | None:
    try:
        return _run(["remember", "--vendor", vendor_id, "--entity", entity_id,
                     "--decision", decision, "--confidence", f"{confidence:.2f}"])
    except (MemoryUnavailable, subprocess.TimeoutExpired):
        return None


def override(vendor_id: str, entity_id: str, verdict: str = "wrong",
             reviewer: str = "reviewer") -> dict[str, Any]:
    """Record a reviewer's correction. Raises, because an override the system
    silently failed to store is the one failure a reviewer must never have."""
    return _run(["override", "--vendor", vendor_id, "--entity", entity_id,
                 "--verdict", verdict, "--reviewer", reviewer])


def ledger(vendor_id: str | None = None) -> list[dict[str, Any]]:
    try:
        args = ["ledger"] + (["--vendor", vendor_id] if vendor_id else [])
        return _run(args).get("entries", [])
    except (MemoryUnavailable, subprocess.TimeoutExpired):
        return []


def overridden_entities(memories: list[dict[str, Any]], vendor_id: str) -> dict[str, dict]:
    """Watchlist entities a reviewer has marked wrong for this vendor.

    Keyed by entity id so the orchestrator can drop the candidate and say which
    correction did it.
    """
    out: dict[str, dict] = {}
    for memory in memories:
        if not memory.get("overridden"):
            continue
        for entity in memory.get("entities", []):
            if entity != vendor_id:
                out[entity] = memory
    return out
