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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
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
