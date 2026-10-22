"""Structured JSONL tracing.

Every agent turn, tool call, verdict and branch is an event. The judging
criteria ask for evidence of how the system reached its output in five separate
places, so this is written from the first line of code rather than bolted on.

The event stream is also what the Day-4 trace viewer renders, and it is the
raw material for the World Model event log.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class Trace:
    def __init__(self, subject: str) -> None:
        self.run_id = str(uuid.uuid4())[:8]
        self.subject = subject
        self.started = time.time()
        LOG_DIR.mkdir(exist_ok=True)
        self.path = LOG_DIR / f"run-{time.strftime('%Y%m%dT%H%M%S')}-{self.run_id}.jsonl"
        self._fh = self.path.open("w", encoding="utf-8")
        self.event("run.start", subject=subject)

    def event(self, kind: str, **fields: Any) -> None:
        record = {
            "t": round(time.time() - self.started, 3),
            "run_id": self.run_id,
            "kind": kind,
            **fields,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    @contextmanager
    def agent(self, name: str, **fields: Any):
        """Wrap one agent turn. Records start, end and duration, and never
        swallows an exception -- a failed turn must be visible in the trace."""
        start = time.time()
        self.event("agent.start", agent=name, **fields)
        try:
            yield self
        except Exception as error:
            self.event("agent.error", agent=name, error=repr(error))
            raise
        finally:
            self.event("agent.end", agent=name, ms=int((time.time() - start) * 1000))

    def close(self, **fields: Any) -> None:
        self.event("run.end", **fields)
        self._fh.close()

    # Convenience wrappers so call sites read like the architecture diagram.

    def tool(self, name: str, **fields: Any) -> None:
        self.event("tool.call", tool=name, **fields)

    def verdict(self, agent: str, verdict: str, **fields: Any) -> None:
        self.event("verdict", agent=agent, verdict=verdict, **fields)

    def branch(self, reason: str, taken: str, **fields: Any) -> None:
        """A decision point. These are what prove this is an agent system and
        not a pipeline, so they are a first-class event type."""
        self.event("branch", reason=reason, taken=taken, **fields)
