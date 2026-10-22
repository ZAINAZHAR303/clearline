"""Deterministic entity matching: blocking, features and scoring.

This exists because the resolver was spending 9,660 reasoning tokens per run
re-deriving facts Python can establish exactly -- whether a name is an exact
alias, whether jurisdictions agree -- at 96% reasoning share and 145 seconds.

The division of labour that follows is also the honest one:

  deterministic here   what IS true: exact alias, token overlap, jurisdiction
  the model            what it MEANS: is this evidence enough to act on

A score the model invented cannot be audited. A score computed here can be
recomputed by a judge, which is what "every claim traces to a source row"
requires.
"""

from __future__ import annotations

LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "lllc", "inc", "incorporated", "gmbh", "sa", "sas",
    "plc", "pte", "bv", "bvba", "nv", "co", "company", "corp", "corporation",
    "ag", "as", "oy", "ab", "spa", "srl", "pty", "kk", "fz", "fze", "llp",
}

# Words that carry no identifying power on their own.
GENERIC_TOKENS = {
    "global", "international", "national", "trading", "services", "service",
    "holdings", "holding", "group", "solutions", "enterprises", "enterprise",
    "general", "the", "and", "of",
}


def tokens(name: str) -> set[str]:
    raw = (name or "").lower().replace(",", " ").replace(".", " ").replace("-", " ")
    return {t for t in raw.split() if t}


def distinctive(name: str) -> set[str]:
    """Tokens that actually identify an entity."""
    return tokens(name) - LEGAL_SUFFIXES - GENERIC_TOKENS


def is_generic(name: str) -> bool:
    """Generic only when nothing distinctive survives.

    'Global Trading Ltd' -> {} -> generic.
    'Metaalkunde BV'     -> {metaalkunde} -> not generic.
    """
    return len(distinctive(name)) == 0


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard over distinctive tokens, with prefix matching so that
    'southwealth' reaches 'south wealth' and transliteration drift such as
    'shustari' / 'shushtari' is not discarded outright."""
    if not a or not b:
        return 0.0
    hits = 0
    for left in a:
        for right in b:
            if left == right or (
                len(left) > 4 and len(right) > 4
                and (left.startswith(right[:5]) or right.startswith(left[:5]))
            ):
                hits += 1
                break
    return hits / max(len(a), len(b))


def match_features(vendor: dict, entity: dict) -> dict:
    """Everything deterministic about one vendor/entity pair.

    Returned verbatim to the model as evidence, and recorded in the trace so a
    reviewer can recompute it.
    """
    legal = (vendor.get("legal_name") or "").strip().lower()
    trading = (vendor.get("trading_name") or "").strip().lower()
    names = {a.strip().lower() for a in entity.get("aliases", [])}
    names.add((entity.get("caption") or "").strip().lower())

    exact_alias = legal in names or (bool(trading) and trading in names)
    country_agreement = bool(entity.get("country")) and entity["country"] == vendor.get("country")
    overlap = max(
        _overlap(distinctive(vendor.get("legal_name", "")), distinctive(name))
        for name in names
    ) if names else 0.0

    features: list[str] = []
    score = 0.30
    if exact_alias:
        features.append("exact_alias")
        score += 0.50
    elif overlap >= 0.5:
        features.append(f"token_overlap_{overlap:.2f}")
        score += 0.10
    else:
        features.append(f"weak_overlap_{overlap:.2f}")
        score -= 0.10

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
        "token_overlap": round(overlap, 2),
        "features": features,
        "score": round(max(0.0, min(1.0, score)), 2),
    }


def rank(vendor: dict, entities: list[dict], top_n: int = 5) -> list[dict]:
    """Blocking plus ranking. Generating a few extra candidates is fine -- the
    Conflict Critic exists to kill them -- but handing the model 300 entities
    is both slow and a way to make it hallucinate a match."""
    scored = []
    for entity in entities:
        feats = match_features(vendor, entity)
        if feats["exact_alias"] or feats["token_overlap"] >= 0.34:
            scored.append({**entity, "_features": feats})
    scored.sort(key=lambda e: e["_features"]["score"], reverse=True)
    return scored[:top_n]
