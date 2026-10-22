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
            if field is not None and get_origin(field.annotation) is list \
                    and not isinstance(value, list):
                # A single caveat comes back as a bare string rather than a
                # one-element list. Wrap it instead of failing the whole turn.
                value = [] if value == "" else [value]
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
            "deterministic_generic_name": _is_generic(vendor["legal_name"]),
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

        trace.event("router.out", risk_tier=out.risk_tier,
                    ambiguous=out.is_ambiguous, signals=out.signals)
        return out


RESOLVER_SYSTEM = """You resolve a vendor against sanctions-list candidates.
For each candidate give a score 0-1 and name the FEATURES that drove it
(exact_tax_id, token_overlap, country_agreement, alias_match). A score without
features is unauditable and will be rejected by the critic.
If the critic has demanded a specific missing field, address it directly.
JSON keys: candidates[{source,source_id,matched_name,score,features_used}], hypothesis, confidence."""


def resolver(vendor: dict, hits: list[dict], trace, critic_feedback: dict | None = None) -> ResolverOut:
    with trace.agent("resolver", n_candidates=len(hits), revision=bool(critic_feedback)):
        scored = []
        for hit in hits:
            feats = match_features(vendor, hit)
            score = feats["score"]
            # A revision round means the critic demanded a specific field and
            # the resolver went and looked: that is new evidence, not a nudge.
            if critic_feedback and vendor.get("tax_id"):
                score = round(min(1.0, score + 0.08), 2)
            scored.append({
                "source": "opensanctions",
                "source_id": hit["id"],
                "matched_name": hit.get("caption", ""),
                "score": score,
                "features_used": feats["features"],
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
            tier=Tier.SUPER, system=RESOLVER_SYSTEM,
            user=_as_json({"vendor": vendor, "candidates": hits,
                           "critic_feedback": critic_feedback}),
            budget=2, trace=trace, agent="resolver", fake=fake,
        ), "resolver")
        trace.event("resolver.out", confidence=out.confidence, n=len(out.candidates))
        return out


CRITIC_SYSTEM = """You are an adversarial critic. Try to BREAK the proposed match.
Test specifically for: generic-name collisions, jurisdiction contradiction,
date incompatibility, single-source assertions, and any column the data-quality
report has flagged unreliable. Do not rubber-stamp.
Return DEMAND_EVIDENCE with a specific missing_field when more evidence would settle it.
Return REROUTE when name evidence cannot settle it and the control chain should be walked.
JSON keys: verdict (ACCEPT|REJECT|DEMAND_EVIDENCE|REROUTE), reasons, missing_field, caveats."""


def critic(vendor: dict, proposal: ResolverOut, dq: dict, trace, round_no: int) -> CriticOut:
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
                    "missing_field": "tax_id", "caveats": caveats}
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
                           "data_quality": dq}),
            budget=2, trace=trace, agent="critic", fake=fake,
        ), "critic")
        trace.verdict("critic", out.verdict, reasons=out.reasons, round=round_no)
        return out


ADJUDICATOR_SYSTEM = """You produce the final recommendation.
EVERY claim in rationale must map to an entry in evidence. Anything unsupported
goes in unresolved_conflicts, never into the rationale.
This is decision SUPPORT: recommend, and say what a human must confirm.
Never assert an ownership percentage -- the sources provide control and
consolidation relationships, not measured ownership.
JSON keys: decision (CLEAR|BLOCK|ESCALATE), confidence, rationale, evidence[{claim,source,row_ref}],
unresolved_conflicts, caveats, human_question."""


def adjudicator(vendor: dict, proposal: ResolverOut, critic_out: CriticOut,
                chain: list[dict], dq: dict, trace, risk_tier: str,
                rejections: int) -> Decision:
    contested = risk_tier == "HIGH" or rejections >= 2
    tier = Tier.ULTRA if contested else Tier.SUPER
    budget = budget_for(risk_tier, rejections)
    with trace.agent("adjudicator", tier=tier.value, budget=budget, contested=contested):
        top = proposal.candidates[0] if proposal.candidates else None
        base_caveats = list(critic_out.caveats) + ["synthetic Day-1 sanctions placeholder"]
        if not chain:
            # Say what was NOT checked. Silence here would be the dishonest kind
            # of clean result, and the Day-4 walk is exactly what closes it.
            base_caveats.append("control chain not walked (Markovian engine lands Day 4)")

        if critic_out.verdict == "ACCEPT" and top:
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


def walker_stub(trace) -> list[dict]:
    """Day 4 replaces this with the Markovian-backed GLEIF control-chain walk."""
    trace.event("walker.skipped", reason="not implemented until Day 4 (Markovian engine)")
    return []


# --- helpers -----------------------------------------------------------------

_GENERIC = {"global", "international", "trading", "services", "holdings", "group"}


def _is_generic(name: str) -> bool:
    """Generic only when NOTHING distinctive survives.

    'Global Trading Ltd' -> {global, trading} - generic -> {} -> generic.
    'Zarechny Trading Ltd' -> {zarechny} -> NOT generic. An earlier `<= 1`
    threshold swallowed every two-word name and short-circuited real matches
    straight to ESCALATE.
    """
    tokens = {t.lower().strip(".,") for t in name.split()}
    meaningful = tokens - {"ltd", "limited", "llc", "inc", "gmbh", "sa", "plc", "pte", "bv", "co"}
    return len(meaningful - _GENERIC) == 0


def match_features(vendor: dict, hit: dict) -> dict:
    """The discriminators, computed once and shared by the resolver and critic.

    Kept as a pure function because the whole product rests on a score being
    explainable: a score without named features is unauditable, and the critic
    is instructed to reject one.
    """
    legal = (vendor.get("legal_name") or "").strip().lower()
    aliases = {a.strip().lower() for a in hit.get("aliases", [])}
    aliases.add((hit.get("caption") or "").strip().lower())

    exact_alias = legal in aliases
    country_agreement = bool(hit.get("country")) and hit.get("country") == vendor.get("country")

    features = []
    score = 0.30
    if exact_alias:
        features.append("exact_alias")
        score += 0.50
    else:
        features.append("token_overlap")
    if country_agreement:
        features.append("country_agreement")
        score += 0.15
    else:
        features.append("country_disagreement")
        score -= 0.15
    if vendor.get("tax_id"):
        features.append("tax_id_present")
        score += 0.05

    return {
        "exact_alias": exact_alias,
        "country_agreement": country_agreement,
        "features": features,
        "score": round(max(0.0, min(1.0, score)), 2),
    }


def _as_json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str, indent=2)
