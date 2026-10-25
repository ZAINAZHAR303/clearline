"""The trust ledger's invariants.

    pytest -q tests/test_memory_ledger.py

These are assertions rather than conventions because the ledger IS the
product's evidence: the submission claims a reviewer correction is recorded
with both states, in an append-only log, that a later decision can cite. Two
defects broke exactly that claim, and neither was visible to the conformance
suite (which exercises the in-memory engine, not persistence across processes):

  1. `save` wrote `[...previousLedger, ...hmem.ledger.all()]` while `load` had
     already rehydrated previousLedger into that same array, so every CLI
     invocation persisted the whole history twice over -- 1, 3, 7, 15, ... 255
     entries after eight calls. Past a few dozen calls `JSON.stringify`
     exceeded V8's maximum string length and the memory file could no longer be
     read or written at all: `RangeError: Invalid string length`.
  2. The ledger's id counter lives in the process and was never restored, so
     the first entry written by each new process was `led-1` again. All 255
     copies above shared one id -- an audit entry nothing can cite.

Both are only observable ACROSS processes, which is why these tests drive the
real subprocess bridge rather than the engine directly.
"""

from __future__ import annotations

import pytest

from clearline.memory import ledger, remember

WRITES = 4  # each one spawns tsx; enough to catch doubling (would give 15)


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    """A memory file of this test's own. The ledger is cumulative by design, so
    asserting on counts requires starting from nothing."""
    monkeypatch.setenv("CLEARLINE_MEMORY_PATH", str(tmp_path / "hmem.json"))
    return tmp_path


def test_ledger_is_append_only_not_self_duplicating(isolated_memory):
    for i in range(WRITES):
        assert remember("V9001", f"TEST-ENTITY-{i}", "BLOCK", 0.9) is not None

    entries = ledger(limit=0)
    assert len(entries) == WRITES, (
        f"{WRITES} writes produced {len(entries)} ledger entries. "
        f"{2 ** WRITES - 1} means the ledger is duplicating itself on save.")


def test_ledger_entry_ids_survive_a_new_process(isolated_memory):
    """Each write is a separate subprocess, so this is the cross-process case:
    ids must keep counting rather than restart at led-1."""
    for i in range(WRITES):
        remember("V9002", f"TEST-ENTITY-{i}", "BLOCK", 0.9)

    ids = [entry["id"] for entry in ledger(limit=0)]
    assert len(set(ids)) == len(ids), f"repeated ledger ids: {ids}"


def test_ledger_reader_is_bounded(isolated_memory):
    for i in range(WRITES):
        remember("V9003", f"TEST-ENTITY-{i}", "BLOCK", 0.9)

    assert len(ledger(limit=2)) == 2
    assert len(ledger(limit=0)) == WRITES
