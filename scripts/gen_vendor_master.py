"""Generate the synthetic vendor master.

    python scripts/fetch_sanctions.py      # first: curate the real watchlist
    python scripts/gen_vendor_master.py    # then: build vendors around it

The vendors are fictional. The watchlist entities they are built around are
REAL, taken from the OFAC SDN list via OpenSanctions, so the demo exercises the
structure of actual designations -- alias drift, transliteration, jurisdiction
-- instead of structure I invented to be easy.

Naming a fictional vendor after a real listed alias is the point: that is what
a true positive looks like. No claim is made about any real company beyond the
public designation already recorded in the source dataset.

Output is a JSON object with records under one key, because that is the shape
Zetaris REST tables handle (object at the root, arrays exploded with
LATERAL VIEW). A bare array is not the proven path.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 42
N_VENDORS = 200
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"

COUNTRIES = ["US", "GB", "DE", "FR", "NL", "SG", "AE", "IN", "PL", "CA", "AU", "JP"]
CATEGORIES = [
    "logistics", "raw materials", "IT services", "facilities", "packaging",
    "contract manufacturing", "professional services", "components",
]
SUFFIXES = ["Ltd", "Limited", "LLC", "L.L.C.", "GmbH", "B.V.", "Pte Ltd", "Inc", "S.A."]
STEMS = [
    "Northwind", "Baltic", "Cedar Point", "Meridian", "Halcyon", "Orchard",
    "Ironside", "Bluewater", "Kestrel", "Sandstone", "Quarry", "Lantern",
    "Fairweather", "Copperline", "Thornhill", "Vantage", "Pinecrest", "Ridgeway",
    "Saltmarsh", "Greyfriars", "Oakhaven", "Stormline", "Fenwick", "Larkspur",
]


def load_anchors() -> dict[str, dict]:
    path = SAMPLE / "sanctions_sample.json"
    if not path.exists():
        raise SystemExit("run scripts/fetch_sanctions.py first")
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in data["entities"]}
    return {i: by_id[i] for i in data["anchors"] if i in by_id}


def find(anchors: dict[str, dict], needle: str) -> dict:
    for entity in anchors.values():
        if needle.lower() in entity["caption"].lower():
            return entity
    raise SystemExit(f"anchor matching {needle!r} not in the sample; re-run fetch_sanctions.py")


def real_cases() -> list[dict]:
    """Demo vendors that are REAL companies with real LEIs.

    Their exposure is not invented: the parent relationship is self-reported
    to GLEIF by the entity, and the parent's designation is published by OFAC.
    Clearline joins two public records and says nothing beyond what they
    already say. Nothing here asserts an ownership percentage.
    """
    path = SAMPLE / "gleif_chains.json"
    if not path.exists():
        return []
    chains = json.loads(path.read_text(encoding="utf-8"))["chains"]

    # Pick readable, ASCII-named children in jurisdictions a Western buyer
    # would onboard without a second thought -- which is the whole point.
    wanted = ["Xing Ao Energy", "Rayblue International"]
    out = []
    for needle in wanted:
        chain = next((c for c in chains if needle.lower() in (c["child"]["name"] or "").lower()), None)
        if not chain:
            continue
        child, parent = chain["child"], chain["parent"]
        out.append({
            "legal_name": child["name"], "trading_name": child["name"].split()[0],
            "country": child.get("country") or "SG", "bank_country": None,
            "lei": child["lei"],
            "expect": "BLOCK",
            "why": (f"REAL company. GLEIF reports its ultimate parent as "
                    f"{parent['name']!r}, which is on the OFAC SDN list. Clean on its "
                    f"own name; only the chain walk finds it."),
            "anchor": None,
        })
    return out


def build_cases(anchors: dict[str, dict]) -> list[dict]:
    """The demo cases, each derived from a real listed entity.

    Every case states the outcome it must produce. These are the assertions the
    offline test checks, and the order they appear in the demo.
    """
    tawu = find(anchors, "TAWU")
    swr = find(anchors, "South Wealth")
    khaverim = find(anchors, "KHAVERIM")

    return [
        {
            # The hero case. "Metaalkunde BV" reads as an ordinary Belgian
            # metalworking supplier and is an exact alias of a listed entity.
            # Name-only screening never finds this.
            "legal_name": "Metaalkunde BV", "trading_name": "Metaalkunde",
            "country": tawu["country"], "bank_country": None,
            "expect": "BLOCK",
            "why": f"exact alias of listed entity {tawu['caption']!r}; name gives nothing away",
            "anchor": tawu["id"],
        },
        {
            # Same anchor as the next case, opposite outcome.
            "legal_name": "South Wealth Resources Ltd.", "trading_name": "South Wealth",
            "country": swr["country"], "bank_country": None,
            "expect": "BLOCK",
            "why": f"exact alias of {swr['caption']!r}, same jurisdiction",
            "anchor": swr["id"],
        },
        {
            # The near-miss. Fuzzy overlap with the case above, different
            # jurisdiction, not an alias. A false positive here freezes a real
            # supplier, so it must CLEAR.
            "legal_name": "Southwealth Resources Pty Ltd", "trading_name": "Southwealth",
            "country": "AU", "bank_country": None,
            "expect": "CLEAR",
            "why": "fuzzy overlap only, different jurisdiction, no exact alias",
            "anchor": None,
        },
        {
            # Indirect exposure. Clean on its own name; the control chain is
            # what finds it, which is the Day-4 Markovian walk.
            "legal_name": "Nordvik Components GmbH", "trading_name": "Nordvik",
            "country": "DE", "bank_country": khaverim["country"],
            "expect": "BLOCK",
            "why": f"clean on its own name; control chain reaches {khaverim['caption']!r}. "
                   "Only the Markovian-bounded walk finds this.",
            "anchor": khaverim["id"],
        },
        {
            "legal_name": "Global Trading Ltd", "trading_name": "Global Trading",
            "country": "FR", "bank_country": None, "no_tax_id": True,
            "expect": "ESCALATE", "why": "generic name, no identifier: unresolvable",
            "anchor": None,
        },
        {
            "legal_name": "International Services LLC", "trading_name": "Intl Services",
            "country": "SG", "bank_country": None, "no_tax_id": True,
            "expect": "ESCALATE", "why": "generic name, no identifier: unresolvable",
            "anchor": None,
        },
        {
            "legal_name": "Copperline Industries Limited", "trading_name": "Copperline",
            "country": "GB", "bank_country": None,
            "expect": "CLEAR", "why": "same real entity as the next row; tests dedupe",
            "anchor": None,
        },
        {
            "legal_name": "Copperline Industries Ltd.", "trading_name": "Copperline Inds",
            "country": "GB", "bank_country": None, "no_tax_id": True,
            "expect": "CLEAR", "why": "same real entity as the previous row; tests dedupe",
            "anchor": None,
        },
    ]


def _variant(name: str, rng: random.Random) -> str:
    """A plausible different company with an overlapping name.

    Near-misses are where false positives come from, so these are generated by
    the mutations that actually occur -- a dropped or swapped word, a joined
    compound, a different legal suffix -- rather than random noise.
    """
    words = [w for w in name.split() if w.lower() not in
             {"ltd", "limited", "llc", "inc", "gmbh", "plc", "sa", "bv", "pte", "co", "company"}]
    suffix = rng.choice(["Pty Ltd", "Holdings Ltd", "Trading GmbH", "Partners LLC", "Group B.V."])
    if len(words) >= 2 and rng.random() < 0.5:
        joined = words[0] + words[1].lower()        # "South Wealth" -> "Southwealth"
        return f"{joined} {' '.join(words[2:])} {suffix}".replace("  ", " ").strip()
    return f"{' '.join(words[:2])} {suffix}"


def build_eval_cases(anchors: dict[str, dict], entities: list[dict],
                     rng: random.Random) -> list[dict]:
    """A labelled set for measuring accuracy, beyond the demo cases.

    Labels record EXPOSURE TRUTH, not an expected output string, because the
    two error types are not symmetric. Escalating a genuinely exposed vendor is
    safe -- a human looks at it. CLEARING one is the legal violation. And
    blocking a clean vendor freezes a real supplier, while escalating it only
    costs review time.

    So each case carries `exposed` plus the decisions that would be acceptable,
    and scripts/evaluate.py measures misses and false blocks separately.
    """
    usable = [e for e in entities
              if e["aliases"] and e["caption"].isascii()
              and all(a.isascii() for a in e["aliases"]) and 10 <= len(e["caption"]) <= 52]
    usable.sort(key=lambda e: e["id"])
    pool = [e for e in usable if e["id"] not in anchors]
    cases: list[dict] = []

    def case(legal, country, category, exposed, acceptable, why,
             anchor=None, bank=None, no_tax=False, chain=None):
        cases.append({
            "legal_name": legal, "trading_name": legal.split()[0],
            "country": country, "bank_country": bank, "no_tax_id": no_tax,
            "category": category, "exposed": exposed, "acceptable": acceptable,
            "why": why, "anchor": anchor, "chain_to": chain,
        })

    # --- genuinely exposed: an exact alias of a listed entity ----------------
    for entity in pool[:5]:
        alias = entity["aliases"][0]
        case(alias, entity["country"], "alias_exact_same_country", True,
             ["BLOCK"], f"exact alias of {entity['caption']!r}, same jurisdiction",
             anchor=entity["id"])

    # Harder: the alias matches but the vendor is registered elsewhere. Real
    # companies operate across borders, so this must not be cleared -- though
    # escalating it is a reasonable answer.
    for entity in pool[5:8]:
        alias = entity["aliases"][0]
        other = "NL" if entity["country"] != "NL" else "IE"
        case(alias, other, "alias_exact_diff_country", True,
             ["BLOCK", "ESCALATE"],
             f"exact alias of {entity['caption']!r} but registered in {other}",
             anchor=entity["id"])

    # --- genuinely exposed: clean name, sanctioned owner ---------------------
    for entity in pool[8:11]:
        case(f"{rng.choice(STEMS)} {rng.choice(['Components', 'Systems', 'Supply'])} GmbH",
             "DE", "chain_indirect", True, ["BLOCK", "ESCALATE"],
             f"clean on its own name; control chain reaches {entity['caption']!r}",
             anchor=entity["id"], bank=entity["country"], chain=entity["id"])

    # --- clean: near-misses, the false-positive trap -------------------------
    for entity in pool[11:16]:
        other = "AU" if entity["country"] != "AU" else "CA"
        case(_variant(entity["caption"], rng), other, "near_miss_diff_country", False,
             ["CLEAR", "ESCALATE"],
             f"name overlaps {entity['caption']!r} but is a different company in {other}")

    # Hardest clean case: overlapping name AND the same jurisdiction, so only
    # the absence of an exact alias separates it from a true positive.
    for entity in pool[16:19]:
        case(_variant(entity["caption"], rng), entity["country"],
             "near_miss_same_country", False, ["CLEAR", "ESCALATE"],
             f"overlaps {entity['caption']!r} in the same jurisdiction, but is not an alias")

    # --- clean: has an ownership chain that terminates without a hit ---------
    for i in range(2):
        case(f"{rng.choice(STEMS)} {rng.choice(['Logistics', 'Industries'])} Ltd",
             rng.choice(["GB", "NL"]), "clean_deep_chain", False, ["CLEAR", "ESCALATE"],
             "ownership chain terminates without reaching a listed entity",
             chain="CLEAN")

    # --- unresolvable --------------------------------------------------------
    for name in ("Global Solutions Group", "International Holdings Ltd"):
        case(name, rng.choice(COUNTRIES), "generic_name", False, ["ESCALATE"],
             "no distinctive token and no identifier: cannot be resolved", no_tax=True)

    return cases


def main() -> None:
    rng = random.Random(SEED)
    anchors = load_anchors()
    vendors: list[dict] = []
    cases: dict[str, dict] = {}

    def add(legal, trading, country, tax_id, bank_country=None, lei=None):
        vid = f"V{len(vendors) + 1:04d}"
        vendors.append({
            "vendor_id": vid,
            "legal_name": legal,
            "trading_name": trading,
            "tax_id": tax_id,
            "country": country,
            "address": f"{rng.randint(1, 240)} "
                       f"{rng.choice(['High', 'Mill', 'Station', 'Harbour', 'Market'])} St, {country}",
            "bank_country": bank_country or country,
            "onboarded_date": f"20{rng.randint(18, 25)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "annual_spend_usd": rng.choice([12_000, 48_000, 115_000, 340_000, 890_000, 2_100_000]),
            "category": rng.choice(CATEGORIES),
            **({"lei": lei} if lei else {}),
        })
        return vid

    for case in build_cases(anchors) + real_cases():
        tax = None if case.get("no_tax_id") else f"{case['country']}{rng.randint(10**8, 10**9 - 1)}"
        vid = add(case["legal_name"], case["trading_name"], case["country"],
                  tax, case["bank_country"], lei=case.get("lei"))
        cases[vid] = {"expect": case["expect"], "why": case["why"], "anchor": case["anchor"]}

    # The labelled evaluation set. Separate from the demo cases above, which
    # stay stable because the README, tests and docs refer to them by id.
    eval_cases: dict[str, dict] = {}
    entities = json.loads((SAMPLE / "sanctions_sample.json").read_text(encoding="utf-8"))["entities"]
    for case in build_eval_cases(anchors, entities, rng):
        tax = None if case.get("no_tax_id") else f"{case['country']}{rng.randint(10**8, 10**9 - 1)}"
        vid = add(case["legal_name"], case["trading_name"], case["country"],
                  tax, case["bank_country"])
        eval_cases[vid] = {k: case[k] for k in
                           ("category", "exposed", "acceptable", "why", "anchor", "chain_to")}

    # Filler with realistic mess: suffix variation and ~15% missing tax ids,
    # which is what makes the data-quality branch real rather than theatrical.
    while len(vendors) < N_VENDORS:
        stem = rng.choice(STEMS)
        country = rng.choice(COUNTRIES)
        legal = (f"{stem} {rng.choice(['Industries', 'Trading', 'Logistics', 'Supply Co', 'Partners'])} "
                 f"{rng.choice(SUFFIXES)}")
        tax = None if rng.random() < 0.15 else f"{country}{rng.randint(10**8, 10**9 - 1)}"
        add(legal, stem, country, tax)

    out = {"vendors": vendors, "_demo_cases": cases, "_eval_cases": eval_cases}
    target = SAMPLE / "vendor_master.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    missing = sum(1 for v in vendors if v["tax_id"] is None)
    print(f"wrote {target.relative_to(ROOT)}  {len(vendors)} vendors, "
          f"{target.stat().st_size / 1024:.0f} KB")
    print(f"  missing tax_id: {missing} ({missing / len(vendors):.0%})")
    print("\ndemo cases:")
    for vid, case in cases.items():
        vendor = next(v for v in vendors if v["vendor_id"] == vid)
        print(f"  {vid}  {vendor['legal_name']:<34} [{vendor['country']}]  -> {case['expect']}")


if __name__ == "__main__":
    main()
