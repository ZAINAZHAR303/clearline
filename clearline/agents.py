"""The five agents, as typed contracts rather than prompts.

Day 1 implements four of them. The Ownership Walker is Day 4, when it moves
onto the Meterless Markovian engine -- the stub here returns an empty chain and
says so in the trace, which is honest and keeps the end-to-end run whole.

Every output is validated. A model that returns the wrong shape gets the
validation error fed back (see llm.complete_json), it does not crash the run.
"""

from __future__ import annotations

from typing import Literal, get_origin

from pydantic import BaseModel, Field, ValidationError, model_validator

from .llm import Tier, budget_for, complete_json
from .matching import is_generic


class Contract(BaseModel):
    """Base for every agent contract.

    Language models emit `null` for optional fields rather than omitting them,
    which defeats Python defaults: `ambiguity_reason: str = ""` rejects None.
    Dropping nulls before validation lets the declared default apply, so one
    rule covers every field instead of a validator per field.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data):
        if not isinstance(data, dict):
            return data
        out = {}
        for key, value in data.items():
            if value is None:
                continue  # let the declared default apply
            field = cls.model_fields.get(key)
            if field is not None:
                wants_list = get_origin(field.annotation) is list
                if wants_list and not isinstance(value, list):
                    # A single caveat arrives as a bare string rather than a
                    # one-element list. Wrap it instead of failing the turn.
                    value = [] if value == "" else [value]
                elif not wants_list and field.annotation is str and isinstance(value, list):
                    # And the inverse: a rationale arrives as a list of points
                    # where prose is declared. Join rather than discard -- the
                    # content is right, only the shape is wrong.
                    value = " ".join(str(v).strip() for v in value if v)
            out[key] = value
        return out


# --- contracts ---------------------------------------------------------------

class RouterOut(Contract):
    entities: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: str = ""
    risk_tier: Literal["LOW", "MED", "HIGH"] = "MED"
    evidence_bar: float = 0.7


class Candidate(Contract):
    source: str
    source_id: str
    matched_name: str
    score: float
    features_used: list[str] = Field(default_factory=list)


class ResolverOut(Contract):
    candidates: list[Candidate] = Field(default_factory=list)
    hypothesis: str
    confidence: float


class CriticOut(Contract):
    verdict: Literal["ACCEPT", "REJECT", "DEMAND_EVIDENCE", "REROUTE"]
    reasons: list[str] = Field(default_factory=list)
    missing_field: str = ""
    caveats: list[str] = Field(default_factory=list)


class Evidence(Contract):
    claim: str
    source: str
    row_ref: str = ""


class Decision(Contract):
    decision: Literal["CLEAR", "BLOCK", "ESCALATE"]
    confidence: float
    rationale: str
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    human_question: str = ""


def _parse(model: type[BaseModel], payload: dict, agent: str):
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise RuntimeError(f"{agent} returned an invalid shape: {error}") from error


# --- agents ------------------------------------------------------------------

ROUTER_SYSTEM = """You are the intake and risk router for a vendor sanctions-screening system.
Extract the entity names worth searching, note risk signals, and set a risk tier.

is_ambiguous has a NARROW meaning. Set it true ONLY when the name is made up
entirely of generic business words -- Global, International, National, Trading,
Services, Holdings, Group, Solutions, Enterprises -- with no distinctive token
left after removing legal suffixes (Ltd, Limited, LLC, GmbH, Pte, Inc, SA, BV).

  "Global Trading Ltd"        -> ambiguous: nothing distinctive remains
  "International Services LLC"-> ambiguous
  "Zarechny Trading Ltd"      -> NOT ambiguous: "Zarechny" is distinctive
  "Harbourgate Components"    -> NOT ambiguous

An unusual, foreign or transliterated proper noun is DISTINCTIVE, not generic.
Rare spelling is exactly what watchlist matching exists to catch, so never call
a name ambiguous merely because it is unfamiliar or hard to transliterate.
Never set is_ambiguous true when the vendor has a tax_id: a unique identifier
makes the entity resolvable regardless of how common its name is.

A bank country that disagrees with the registered country is a risk signal.
JSON keys: entities, signals, is_ambiguous, ambiguity_reason, risk_tier (LOW|MED|HIGH), evidence_bar (0-1)."""


def router(vendor: dict, trace) -> RouterOut:
    with trace.agent("router", vendor_id=vendor["vendor_id"]):
        # Deterministic signals handed to the model as evidence. The refusal
        # path is too consequential to rest on model judgement alone -- a
        # wrongly-flagged name never reaches the resolver at all.
        precomputed = {
            "deterministic_generic_name": is_generic(vendor["legal_name"]),
            "has_unique_identifier": bool(vendor.get("tax_id")),
            "bank_country_mismatch": vendor.get("bank_country") != vendor.get("country"),
        }
        fake = {
            "entities": [vendor["legal_name"], vendor.get("trading_name") or ""],
            "signals": (["bank_country != country"]
                        if precomputed["bank_country_mismatch"] else []),
            "is_ambiguous": precomputed["deterministic_generic_name"],
            "ambiguity_reason": "generic trading name" if precomputed["deterministic_generic_name"] else "",
            "risk_tier": "HIGH" if vendor.get("annual_spend_usd", 0) > 500_000 else "MED",
            "evidence_bar": 0.7,
        }
        out = _parse(RouterOut, complete_json(
            tier=Tier.NANO, system=ROUTER_SYSTEM,
            user=_as_json({"vendor": vendor, "precomputed_signals": precomputed}),
            budget=1, trace=trace, agent="router", fake=fake,
        ), "router")

        # Guard: a vendor with a unique identifier is resolvable by definition.
        # Honour the model's refusal only when the deterministic check agrees.
        if out.is_ambiguous and precomputed["has_unique_identifier"]:
            trace.event("router.override", reason="model flagged ambiguity but vendor has a tax_id",
                        model_reason=out.ambiguity_reason)
            out = out.model_copy(update={"is_ambiguous": False, "ambiguity_reason": ""})

        if not 0.6 <= out.evidence_bar <= 0.85:
            trace.event("router.bar_clamped", model_said=out.evidence_bar,
                        clamped_to=min(0.85, max(0.6, out.evidence_bar)))
            out = out.model_copy(update={"evidence_bar": min(0.85, max(0.6, out.evidence_bar))})
        trace.event("router.out", risk_tier=out.risk_tier,
                    ambiguous=out.is_ambiguous, signals=out.signals)
        return out


RESOLVER_SYSTEM = """You assess watchlist candidates for a vendor.

The evidence is ALREADY COMPUTED and given to you under `_features` for each
candidate: exact_alias, country_agreement, token_overlap and a score. Do not
recompute them and do not invent new scores -- they are reproducible facts a
reviewer can check, and yours would not be.

Your job is judgement, not arithmetic: state the hypothesis, carry the computed
score through as confidence, and say in one line what the evidence supports.
If the critic has demanded a specific missing field, address that field.

JSON keys: candidates[{source,source_id,matched_name,score,features_used}], hypothesis, confidence."""


def resolver(vendor: dict, hits: list[dict], trace, critic_feedback: dict | None = None) -> ResolverOut:
    with trace.agent("resolver", n_candidates=len(hits), revision=bool(critic_feedback)):
        scored = []
        for hit in hits:
            feats = hit.get("_features") or {}
            score = feats.get("score", 0.0)
            # A revision round means the critic demanded a field and the
            # resolver went and looked: new evidence, not a nudge.
            if critic_feedback and vendor.get("tax_id"):
                score = round(min(1.0, score + 0.08), 2)
            scored.append({
                "source": hit.get("dataset", "opensanctions"),
                "source_id": hit["id"],
                "matched_name": hit.get("caption", ""),
                "score": score,
                "features_used": feats.get("features", []),
            })
        scored.sort(key=lambda c: c["score"], reverse=True)
        best = scored[0]["score"] if scored else 0.0
        fake = {
            "candidates": scored,
            "hypothesis": (f"{vendor['legal_name']} may correspond to "
                           f"{scored[0]['matched_name']}" if scored else "no candidate found"),
            "confidence": best,
        }
        out = _parse(ResolverOut, complete_json(
            tier=Tier.NANO, system=RESOLVER_SYSTEM,
            user=_as_json({"vendor": vendor, "candidates": hits,
                           "critic_feedback": critic_feedback}),
            budget=1, trace=trace, agent="resolver", fake=fake,
        ), "resolver")
        computed = max((h.get("_features", {}).get("score", 0.0) for h in hits), default=0.0)
        if abs(out.confidence - computed) > 0.01:
            trace.event("resolver.confidence_override", model_said=out.confidence,
                        computed=computed,
                        reason="confidence is the deterministic score, not a model opinion")
            out = out.model_copy(update={"confidence": computed})
        trace.event("resolver.out", confidence=out.confidence, n=len(out.candidates))
        return out


AVAILABLE_FIELDS = [
    "vendor.legal_name", "vendor.trading_name", "vendor.tax_id", "vendor.country",
    "vendor.bank_country", "vendor.onboarded_date", "vendor.annual_spend_usd",
    "candidate.caption", "candidate.aliases", "candidate.country",
    "candidate.dataset", "candidate.programme", "control_chain",
]

CRITIC_SYSTEM = """You are an adversarial critic in a vendor SANCTIONS SCREENING system.

What the task is. A candidate is a watchlist entry that may BE this vendor,
trading under a different name. You are judging identity: is the vendor the
listed entity? You are NOT merging two companies, and the vendor record never
carries a sanctions flag -- establishing that is the whole point, so its
absence is not evidence either way.

Two things that are not contradictions:
  - OFAC designates entities WORLDWIDE. A Belgian, Emirati or Iraqi entity on a
    US list is ordinary. The dataset names the list an entity appears on, never
    where it is registered.
  - A listed entity's caption routinely differs from the name a vendor trades
    under. That is what the alias list is for. An exact match against an alias
    IS the identification.

An exact_alias match with country_agreement is strong evidence FOR the match
and should be ACCEPTed unless you can name a concrete defect in it.

Now: try to BREAK the proposed match.
candidates_detail carries each candidate's full record: its aliases, country,
dataset and the deterministically computed features. A listed entity's CAPTION
routinely differs from the alias a vendor trades under -- that is normal, and
an exact_alias match against the alias list is strong evidence, not a
contradiction. The dataset is the list the entity appears ON, never a claim
about where it is registered; compare candidate.country, not the dataset name.

Test specifically for: generic-name collisions, jurisdiction contradiction,
date incompatibility, single-source assertions, and any column the data-quality
report has flagged unreliable. Do not rubber-stamp.
Return DEMAND_EVIDENCE only when a field listed in available_fields would
settle it, and set missing_field to that exact field name. Fields outside that
list cannot be fetched, so demanding one wastes a round -- if what you need is
not available, say so in reasons and return REJECT or REROUTE instead.
Choose the verdict by what the evidence DID:
  ACCEPT  the candidate is the vendor, and you cannot name a concrete defect.
  REJECT  the evidence rules the candidate OUT -- different jurisdiction with
          no exact alias means these are not the same entity. This is a
          finding, not a failure, and it is how a vendor gets cleared.
  REROUTE only when the name evidence is genuinely INCONCLUSIVE, or no
          candidate matched the name at all, so that indirect exposure through
          the control chain is the remaining open question. Do not REROUTE a
          candidate you have just ruled out.
JSON keys: verdict (ACCEPT|REJECT|DEMAND_EVIDENCE|REROUTE), reasons, missing_field, caveats."""


def critic(vendor: dict, proposal: ResolverOut, dq: dict, trace, round_no: int,
           hits: list[dict] | None = None,
           already_demanded: list[str] | None = None) -> CriticOut:
    with trace.agent("critic", round=round_no):
        unreliable = [c for c, s in dq.get("columns", {}).items()
                      if isinstance(s, dict) and s.get("null_rate", 0) > 0.1]
        caveats = [f"{c} is unreliable in this source" for c in unreliable]
        top = proposal.candidates[0] if proposal.candidates else None
        features = set(top.features_used) if top else set()

        if top is None:
            # Nothing to match on this vendor's own name. That is not a clean
            # bill of health -- it is why the control chain exists.
            fake = {"verdict": "REROUTE",
                    "reasons": ["no watchlist candidate on the vendor's own name"],
                    "missing_field": "", "caveats": caveats}
        elif round_no == 1 and proposal.confidence < 0.8:
            fake = {"verdict": "DEMAND_EVIDENCE",
                    "reasons": ["single-source assertion", "token overlap alone is weak"],
                    "missing_field": "vendor.tax_id", "caveats": caveats}
        elif "exact_alias" in features and "country_agreement" in features:
            fake = {"verdict": "ACCEPT",
                    "reasons": ["exact alias of a listed entity", "jurisdiction agrees"],
                    "missing_field": "", "caveats": caveats}
        elif "exact_alias" not in features and "country_disagreement" in features:
            # The near-miss killer. A false positive freezes a real supplier,
            # so fuzzy name overlap across jurisdictions is not enough.
            fake = {"verdict": "REJECT",
                    "reasons": ["no exact alias match",
                                "registered jurisdiction disagrees with the listed entity",
                                "token overlap alone cannot carry a block"],
                    "missing_field": "", "caveats": caveats}
        else:
            fake = {"verdict": "REROUTE",
                    "reasons": ["name evidence is inconclusive; the control chain should decide"],
                    "missing_field": "", "caveats": caveats}
        out = _parse(CriticOut, complete_json(
            tier=Tier.SUPER, system=CRITIC_SYSTEM,
            user=_as_json({"vendor": vendor, "proposal": proposal.model_dump(),
                           "data_quality": dq, "available_fields": AVAILABLE_FIELDS,
                           "already_demanded": already_demanded or [],
                           # The candidate records themselves. Without the
                           # alias list the critic cannot see why an unrelated
                           # caption is a valid match, and correctly rejects it.
                           "candidates_detail": [{
                               "id": h["id"], "caption": h.get("caption"),
                               "aliases": h.get("aliases", []),
                               "country": h.get("country"),
                               "dataset": h.get("dataset"),
                               "programme": h.get("programme"),
                               "computed": h.get("_features", {}),
                           } for h in (hits or [])]}),
            budget=3, trace=trace, agent="critic", fake=fake,
        ), "critic")
        trace.verdict("critic", out.verdict, reasons=out.reasons, round=round_no)
        return out


ADJUDICATOR_SYSTEM = """You produce the final recommendation.

`chain` is the control chain walked upward from the vendor. A hop whose
sanctions_hit is set means the vendor is clean on its own name but CONTROLLED
by a listed entity -- indirect exposure, and a BLOCK. Report it as a control
relationship and never as an ownership percentage: the source publishes
consolidation relationships, not percentages.
EVERY claim in rationale must map to an entry in evidence. Anything unsupported
goes in unresolved_conflicts, never into the rationale.
This is decision SUPPORT: you RECOMMEND, and a human confirms. Express that
confirmation in human_question -- never by escalating a case you can decide.

  BLOCK     the critic ACCEPTed a match. Recommend it even though a human will
            confirm; that is what human_question is for.
  CLEAR     the critic REJECTed the candidate. Ruling one out is a result, and
            clearing is the correct recommendation. Record why in the evidence.
  ESCALATE  only when the evidence is genuinely insufficient to recommend
            either way -- an unresolvable name, or an open control-chain
            question on a vendor carrying a risk signal. Escalating everything
            is alert fatigue and makes the system useless.
Never assert an ownership percentage -- the sources provide control and
consolidation relationships, not measured ownership.
JSON keys: decision (CLEAR|BLOCK|ESCALATE), confidence, rationale, evidence[{claim,source,row_ref}],
unresolved_conflicts, caveats, human_question."""


def adjudicator(vendor: dict, proposal: ResolverOut, critic_out: CriticOut,
                chain: list[dict], dq: dict, trace, risk_tier: str,
                rejections: int) -> Decision:
    contested = risk_tier == "HIGH" or rejections >= 2
    tier = Tier.ULTRA if contested else Tier.SUPER
    # Its output is long by design (evidence list, conflicts, caveats), so it
    # needs content headroom regardless of how uncontested the case is.
    budget = max(3, budget_for(risk_tier, rejections))
    with trace.agent("adjudicator", tier=tier.value, budget=budget, contested=contested):
        top = proposal.candidates[0] if proposal.candidates else None
        base_caveats = list(critic_out.caveats) + [_watchlist_provenance()]
        if not chain:
            # "No indirect exposure found" and "the chain was never walked" are
            # different claims, and a reviewer must be able to tell them apart.
            base_caveats.append("control chain not walked for this vendor")

        chain_hits = [h for h in (chain or []) if h.get("sanctions_hit")]
        if chain_hits:
            hop = chain_hits[0]
            hit = hop["sanctions_hit"]
            fake = {
                "decision": "BLOCK",
                "confidence": 0.9,
                "rationale": (
                    f"{vendor['legal_name']} is clean on its own name, but its control "
                    f"chain reaches {hit['caption']}, a listed entity, at depth {hop['depth']} "
                    f"via {hop['relation'].replace('_', ' ').lower()}."),
                "evidence": [
                    {"claim": f"control chain hop {h['depth']}: {h['name']} ({h['relation']})",
                     "source": "control_graph", "row_ref": str(h.get("lei"))}
                    for h in (chain or [])
                ] + [{"claim": f"{hit['caption']} is listed", "source": hit.get("dataset", "watchlist"),
                      "row_ref": hit.get("entity_id", "")}],
                "unresolved_conflicts": [],
                "caveats": base_caveats + [
                    "control relationship, NOT a measured ownership percentage: the source "
                    "publishes consolidation relationships, and OFAC's 50% rule needs ownership "
                    "data it does not provide"],
                "human_question": ("Confirm the control relationship with the registry before "
                                   "freezing payments."),
            }
        elif critic_out.verdict == "ACCEPT" and top:
            fake = {
                "decision": "BLOCK",
                "confidence": round(proposal.confidence, 2),
                "rationale": (f"{vendor['legal_name']} is an exact alias of listed entity "
                              f"{top.matched_name}, in the same jurisdiction."),
                "evidence": [{"claim": f"exact alias match to {top.matched_name}",
                              "source": top.source, "row_ref": top.source_id},
                             {"claim": f"jurisdiction agrees ({vendor.get('country')})",
                              "source": top.source, "row_ref": top.source_id}],
                "unresolved_conflicts": [],
                "caveats": base_caveats,
                "human_question": "Confirm the alias match before freezing payments.",
            }
        elif critic_out.verdict == "REJECT":
            # The critic killed the candidate. Clearing is the right call: a
            # false positive stops a real supplier, and every fuzzy overlap
            # escalated is alert fatigue. The rejection reason is the audit trail.
            fake = {
                "decision": "CLEAR", "confidence": 0.85,
                "rationale": ("A watchlist candidate was considered and rejected: "
                              + "; ".join(critic_out.reasons) + "."),
                "evidence": ([{"claim": f"candidate {top.matched_name} rejected",
                               "source": top.source, "row_ref": top.source_id}] if top else []),
                "unresolved_conflicts": [], "caveats": base_caveats, "human_question": "",
            }
        elif critic_out.verdict == "REROUTE" and not chain:
            fake = {
                "decision": "ESCALATE", "confidence": 0.45,
                "rationale": ("No match on the vendor's own name. Indirect exposure "
                              "cannot be ruled out until the control chain is walked."),
                "evidence": [], "unresolved_conflicts": critic_out.reasons,
                "caveats": base_caveats,
                "human_question": "Walk the ownership chain for this vendor before approving.",
            }
        else:
            fake = {
                "decision": "ESCALATE", "confidence": 0.5,
                "rationale": "Evidence is inconclusive at the required bar.",
                "evidence": [], "unresolved_conflicts": critic_out.reasons,
                "caveats": base_caveats,
                "human_question": "Can you supply a tax ID or registry number for this vendor?",
            }
        out = _parse(Decision, complete_json(
            tier=tier, system=ADJUDICATOR_SYSTEM,
            user=_as_json({"vendor": vendor, "proposal": proposal.model_dump(),
                           "critic": critic_out.model_dump(), "chain": chain,
                           "data_quality": dq}),
            budget=budget, trace=trace, agent="adjudicator", fake=fake,
        ), "adjudicator")
        trace.event("adjudicator.out", decision=out.decision,
                    confidence=out.confidence, budget_spent=budget, tier=tier.value)
        return out


def _watchlist_provenance() -> str:
    """State which watchlist snapshot a decision rests on. A screening result
    without a snapshot date is not auditable -- designations change weekly."""
    try:
        import json
        from pathlib import Path as _P
        data = json.loads((_P(__file__).resolve().parent.parent / "data" / "sample"
                           / "sanctions_sample.json").read_text(encoding="utf-8"))
        prov = data.get("provenance", {})
        return (f"watchlist: {prov.get('dataset')} snapshot "
                f"{(prov.get('snapshot_updated_at') or '?')[:10]}, curated subset "
                f"of {prov.get('entity_count_full_dataset')} entities")
    except Exception:
        return "watchlist provenance unavailable"


# --- helpers -----------------------------------------------------------------

def _as_json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str, indent=2)
