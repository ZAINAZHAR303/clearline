"""The demo cases, as assertions.

    pytest -q

Runs the whole agent system against every planted case with CLEARLINE_FAKE_LLM
set, so the suite is deterministic, offline and takes under a second. What it
exercises is the orchestration -- branching, the revision loop, the data-quality
replan, escalation -- not the model's wording.

The expected outcome for each case lives in data/sample/vendor_master.json
under `_demo_cases`, written by scripts/gen_vendor_master.py. Nothing in
clearline/ reads that key, so the system cannot pass by looking up answers.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ["CLEARLINE_FAKE_LLM"] = "1"
os.environ.setdefault("SAMPLE_MODE", "true")
# Isolated memory. The suite must not read state a demo left behind, nor leave
# state behind for one -- the override loop mutates exactly what it asserts on.
_MEM = Path(tempfile.gettempdir()) / "clearline-test-memory" / "hmem.json"
_MEM.parent.mkdir(parents=True, exist_ok=True)
if _MEM.exists():
    _MEM.unlink()
os.environ["CLEARLINE_MEMORY_PATH"] = str(_MEM)

ROOT = Path(__file__).resolve().parent.parent
MASTER = json.loads((ROOT / "data" / "sample" / "vendor_master.json").read_text(encoding="utf-8"))
CASES = MASTER["_demo_cases"]

from clearline.matching import is_generic, match_features, rank  # noqa: E402
from clearline.orchestrator import screen  # noqa: E402


def _vendor(vendor_id: str) -> dict:
    return next(v for v in MASTER["vendors"] if v["vendor_id"] == vendor_id)


@pytest.mark.parametrize("vendor_id", list(CASES))
def test_demo_case_outcome(vendor_id):
    expected = CASES[vendor_id]["expect"]
    decision, trace = screen(vendor_id)
    assert decision is not None, f"{vendor_id} produced no decision"

    assert decision.decision == expected, (
        f"{vendor_id} {_vendor(vendor_id)['legal_name']!r}: "
        f"expected {expected}, got {decision.decision}. "
        f"Case: {CASES[vendor_id]['why']}")


def test_every_claim_is_evidenced():
    """A BLOCK that cites nothing is the failure mode this product exists to
    avoid, so it is an assertion rather than a convention."""
    for vendor_id, case in CASES.items():
        if case["expect"] != "BLOCK":
            continue
        decision, _ = screen(vendor_id)
        assert decision.evidence, f"{vendor_id} blocked with no evidence"
        for item in decision.evidence:
            assert item.source and item.row_ref, f"{vendor_id}: evidence without a source row"


def test_decisions_carry_watchlist_provenance():
    """Designations change weekly; a decision without a snapshot is unauditable."""
    decision, _ = screen("V0001")
    assert any("snapshot" in c for c in decision.caveats), decision.caveats


def test_near_miss_is_not_blocked():
    """The expensive mistake. A false positive freezes a real supplier, and
    fuzzy name overlap across jurisdictions must not carry a block."""
    decision, _ = screen("V0003")
    assert decision.decision == "CLEAR"
    assert any("juris" in r.lower() or "alias" in r.lower()
               for r in [decision.rationale, *decision.unresolved_conflicts]), decision.rationale


def test_indirect_exposure_is_found_by_the_chain_walk():
    """V0004 is clean on its own name. Only the Markovian-bounded control-chain
    walk reaches the listed entity, so this is the assertion that the engine is
    load-bearing rather than merely conformant."""
    decision, _ = screen("V0004")
    assert decision.decision == "BLOCK", decision.rationale
    assert any("chain" in e.claim.lower() for e in decision.evidence),         "a block on indirect exposure must cite the hops that found it"
    assert any("ownership percentage" in c for c in decision.caveats),         "control relationships must never be reported as ownership percentages"


def test_generic_names_are_refused_not_guessed():
    decision, _ = screen("V0005")
    assert decision.decision == "ESCALATE"
    assert decision.human_question, "an escalation must say what the human should supply"


# --- the deterministic layer -------------------------------------------------

def test_is_generic():
    assert is_generic("Global Trading Ltd")
    assert is_generic("International Services LLC")
    assert not is_generic("Metaalkunde BV"), "a distinctive token must survive"
    assert not is_generic("Zarechny Trading Ltd"), "transliterations are distinctive, not generic"


def test_exact_alias_beats_fuzzy_overlap():
    entity = {"id": "X", "caption": "TAWU Mechanical Engineering and Trading Company",
              "aliases": ["Metaalkunde BV", "TAWU"], "country": "BE"}
    hit = match_features({"legal_name": "Metaalkunde BV", "country": "BE"}, entity)
    miss = match_features({"legal_name": "Metaalkunde Holdings Pty", "country": "AU"}, entity)
    assert hit["exact_alias"] and hit["country_agreement"]
    assert not miss["exact_alias"] and not miss["country_agreement"]
    assert hit["score"] > miss["score"]


def test_rank_caps_candidates():
    entities = [{"id": str(i), "caption": f"South Wealth Resources {i}",
                 "aliases": [], "country": "IQ"} for i in range(50)]
    assert len(rank({"legal_name": "South Wealth Resources Ltd.", "country": "IQ"},
                    entities, top_n=5)) <= 5


# --- the correction loop -----------------------------------------------------

def test_reviewer_override_changes_the_next_decision():
    """The loop the product rests on.

    A screening tool that cannot be corrected is worse than useless: every
    false positive costs a supplier relationship and nobody can stop it
    recurring. So a reviewer marks a match wrong, H-MEM drops its confidence by
    the spec's exact delta and tags it for review, and the NEXT run must reach
    a different decision and say which correction did it.
    """
    from clearline.memory import ledger, override, recall

    first, _ = screen("V0001")
    assert first.decision == "BLOCK", "precondition: V0001 blocks on an exact alias"

    entity_id = first.evidence[0].row_ref
    assert entity_id, "a block must cite the entity it matched"

    result = override("V0001", entity_id, "wrong", reviewer="pytest")
    assert result["confidence_after"] == round(result["confidence_before"] - 0.20, 10), \
        "the spec fixes the 'wrong' delta at exactly -0.20"
    assert "review" in result["tags"]

    second, _ = screen("V0001")
    assert second.decision != "BLOCK", (
        f"a reviewer said this match was wrong; the system must not keep asserting it "
        f"(got {second.decision})")
    assert any("reviewer correction" in c for c in second.caveats), second.caveats

    # The correction is auditable, not just applied.
    actions = [e["action"] for e in ledger("V0001")]
    assert "create" in actions and "feedback" in actions, actions
    assert any(m["overridden"] for m in recall("V0001"))
