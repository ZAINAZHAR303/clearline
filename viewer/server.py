"""Trace viewer — what the agents did, and why.

    python -m viewer.server        then open http://localhost:8800

Reads the JSONL traces in logs/ and serves them as a timeline. No build step,
no CDN, no database: a judge runs one command and sees the system reason.

The thing worth showing is not that output appeared. It is the branches — the
revision loop, the data-quality replan, the chain walk, a reviewer's correction
excluding a candidate. Those are what separate an agent system from a pipeline,
and they are invisible in a terminal scroll.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
QUEUE = ROOT / "data" / "queue" / "latest.json"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Clearline trace viewer")


def _events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a run killed mid-write should still be readable
    return out


def _summary(path: Path) -> dict | None:
    events = _events(path)
    if not events:
        return None
    start = next((e for e in events if e["kind"] == "run.start"), {})
    end = next((e for e in events if e["kind"] == "run.end"), {})
    vendor = next((e for e in events if e["kind"] == "vendor.loaded"), {})

    llm = [e for e in events if e["kind"] == "llm.result"]
    return {
        "file": path.name,
        "run_id": start.get("run_id"),
        "subject": start.get("subject"),
        "legal_name": vendor.get("legal_name"),
        "country": vendor.get("country"),
        "outcome": end.get("outcome"),
        "confidence": end.get("confidence"),
        "seconds": round(max((e.get("t", 0) for e in events), default=0), 1),
        "llm_calls": len(llm),
        "reasoning_tokens": sum(e.get("reasoning_tokens") or 0 for e in llm),
        "branches": sum(1 for e in events if e["kind"] == "branch"),
        "mtime": path.stat().st_mtime,
    }


@app.get("/api/runs")
def list_runs(limit: int = 40) -> JSONResponse:
    """Newest first, capped. A week of development leaves hundreds of traces
    and an unbounded sidebar buries the run you just made."""
    paths = sorted(LOGS.glob("run-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = [s for s in (_summary(p) for p in paths[:limit]) if s]
    return JSONResponse(runs)


@app.get("/api/runs/{name}")
def get_run(name: str) -> JSONResponse:
    # Resolve inside LOGS and compare parents: a trace viewer that will open
    # ../../.env on request is not something to ship.
    path = (LOGS / name).resolve()
    if path.parent != LOGS.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="no such run")
    return JSONResponse({"summary": _summary(path), "events": _events(path)})


@app.get("/api/queue")
def queue() -> JSONResponse:
    """The reviewer's worklist: what needs a human, and a count of what does not."""
    if not QUEUE.exists():
        return JSONResponse({"empty": True,
                             "hint": "python -m clearline.batch --fake"})
    return JSONResponse(json.loads(QUEUE.read_text(encoding="utf-8")))


@app.post("/api/decide")
def decide(payload: dict = Body(...)) -> JSONResponse:
    """Approve a recommendation, or override it.

    This is the action the whole product exists to support, so it is deliberate
    about two things. The reviewer's name is recorded, because an audit trail
    with an anonymous actor is not an audit trail. And an override goes through
    H-MEM rather than editing the queue file, so it changes what the system
    decides NEXT TIME instead of just changing what this screen shows.
    """
    vendor_id = payload.get("vendor_id")
    action = payload.get("action")
    reviewer = (payload.get("reviewer") or "").strip() or "unnamed-reviewer"
    entity_id = payload.get("entity_id")
    if not vendor_id or action not in {"approve", "override"}:
        raise HTTPException(status_code=400, detail="vendor_id and action (approve|override) required")

    import sys
    sys.path.insert(0, str(ROOT))
    from clearline.memory import ledger, override, remember

    try:
        if action == "override":
            if not entity_id:
                raise HTTPException(status_code=400,
                                    detail="override needs the entity_id the decision cited")
            result = override(vendor_id, entity_id, "wrong", reviewer)
        else:
            # Approving confirms the match, which is 'helpful' feedback: it
            # should make the same call more confident next time, not less.
            remember(vendor_id, entity_id or "approved", "BLOCK", 0.95)
            result = override(vendor_id, entity_id or "approved", "helpful", reviewer)
        return JSONResponse({"ok": True, "action": action, "reviewer": reviewer,
                             "result": result, "ledger": ledger(vendor_id)})
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(error)[:300]) from error


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def main() -> None:
    import uvicorn

    LOGS.mkdir(exist_ok=True)
    print("Clearline trace viewer -> http://localhost:8800")
    uvicorn.run(app, host="127.0.0.1", port=8800, log_level="warning")


if __name__ == "__main__":
    main()
