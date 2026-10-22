"""Generate the synthetic vendor master and a Day-1 placeholder sanctions list.

Seeded, so the output is reproducible and the repo stays light. Run:

    python scripts/gen_vendor_master.py

Writes JSON as a top-level OBJECT with the records under one key, because that
is the shape Zetaris's proven REST-table recipe handles (object at the root,
arrays exploded with LATERAL VIEW). A top-level array is not the proven path.

The planted cases are the point of this file. They are documented in
data/README.md and each one exercises a specific agent behaviour.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 42
N_VENDORS = 200
OUT = Path(__file__).resolve().parent.parent / "data" / "sample"

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

# --- planted cases ----------------------------------------------------------
# Each entry: (legal_name, trading_name, why it is here)
# Day 1 keeps these synthetic so the skeleton runs offline. Day 2 swaps the
# sanctions side for the real OpenSanctions bulk extract.

# Countries here are FIXED, not random. The discrimination between the true
# positive and the near-miss depends on jurisdiction, so leaving it to the RNG
# produced a fixture where the correct answer was unreachable.
#   (legal, trading, country, bank_country, why)
EXPOSED = [
    # True positive. Exact alias of SYN-001 AND same jurisdiction -> BLOCK.
    ("Zarechny Trading Ltd", "Zarechny", "AE", None,
     "exact alias of a listed entity, same jurisdiction -> BLOCK"),
    # Indirect. Clean on its own name; ultimate parent (SYN-002) is listed.
    # Bank country disagrees with registered country -- a real risk signal.
    ("Harbourgate Components GmbH", "Harbourgate", "DE", "AE",
     "clean itself; ultimate parent is listed -> BLOCK via the Day-4 chain walk"),
    # Near-miss. Fuzzy token overlap only, different jurisdiction, different
    # business line. Must be CLEARED: a false positive freezes a real supplier.
    ("Zarechnyy Logistics Pte Ltd", "Zarechnyy Log", "SG", None,
     "near-miss: no exact alias, different jurisdiction -> must be CLEARED"),
]

GENERIC_TRAPS = [
    ("Global Trading Ltd", "Global Trading", "generic name; must be ESCALATED as unresolvable"),
    ("International Services LLC", "Intl Services", "generic name; must be ESCALATED as unresolvable"),
]

# Same real entity, two vendor_ids, different spellings and one missing tax id.
DUPLICATE_PAIR = [
    ("Copperline Industries Limited", "Copperline", "GB", "GB418872301"),
    ("Copperline Industries Ltd.", "Copperline Inds", "GB", None),
]


def _tax_id(country: str, rng: random.Random) -> str:
    return f"{country}{rng.randint(100_000_000, 999_999_999)}"


def _address(country: str, rng: random.Random) -> str:
    return f"{rng.randint(1, 240)} {rng.choice(['High', 'Mill', 'Station', 'Harbour', 'Market'])} St, {country}"


def build() -> dict:
    rng = random.Random(SEED)
    vendors: list[dict] = []
    notes: dict[str, str] = {}
    n = 0

    def add(legal, trading, country, tax_id, note=None, bank_country=None):
        nonlocal n
        n += 1
        vid = f"V{n:04d}"
        vendors.append({
            "vendor_id": vid,
            "legal_name": legal,
            "trading_name": trading,
            "tax_id": tax_id,
            "country": country,
            "address": _address(country, rng),
            "bank_country": bank_country or country,
            "onboarded_date": f"20{rng.randint(18, 25)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
            "annual_spend_usd": rng.choice([12_000, 48_000, 115_000, 340_000, 890_000, 2_100_000]),
            "category": rng.choice(CATEGORIES),
        })
        if note:
            notes[vid] = note
        return vid

    # 1. The planted exposure cases.
    for legal, trading, country, bank, why in EXPOSED:
        add(legal, trading, country, _tax_id(country, rng), why, bank_country=bank)

    # 2. The generic-name traps.
    for legal, trading, why in GENERIC_TRAPS:
        c = rng.choice(COUNTRIES)
        add(legal, trading, c, None, why)

    # 3. The duplicate entity, two rows.
    for legal, trading, country, tax in DUPLICATE_PAIR:
        add(legal, trading, country, tax, "same real entity as its pair; tests dedupe")

    # 4. Filler, with realistic mess: suffix variation and ~15% missing tax ids.
    while n < N_VENDORS:
        stem = rng.choice(STEMS)
        suffix = rng.choice(SUFFIXES)
        country = rng.choice(COUNTRIES)
        legal = f"{stem} {rng.choice(['Industries', 'Trading', 'Logistics', 'Supply Co', 'Partners'])} {suffix}"
        tax = None if rng.random() < 0.15 else _tax_id(country, rng)
        add(legal, stem, country, tax)

    return {"vendors": vendors, "_planted_cases": notes}


def sanctions_placeholder() -> dict:
    """Day-1 stand-in ONLY. Day 2 replaces this with the OpenSanctions bulk
    extract (see data/README.md). Clearly synthetic so it can never be mistaken
    for a real designation."""
    return {
        "entities": [
            {
                "id": "SYN-001",
                "caption": "Zarechnyi Trading Company",
                "aliases": ["Zarechny Trading Ltd", "Zarechnyi Trd Co", "Zarechny"],
                "country": "AE",
                "topics": ["sanction"],
                "dataset": "SYNTHETIC_DAY1_PLACEHOLDER",
            },
            {
                "id": "SYN-002",
                "caption": "Ostrava Holdings PLC",
                "aliases": ["Ostrava Hldgs", "Ostrava Holding"],
                "country": "GB",
                "topics": ["sanction"],
                "dataset": "SYNTHETIC_DAY1_PLACEHOLDER",
                "_note": "ultimate parent of Harbourgate Components GmbH",
            },
            {
                "id": "SYN-003",
                "caption": "Marisol Petrochemicals SA",
                "aliases": ["Marisol Petro"],
                "country": "FR",
                "topics": ["pep"],
                "dataset": "SYNTHETIC_DAY1_PLACEHOLDER",
            },
        ]
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = build()
    (OUT / "vendor_master.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT / "sanctions_sample.json").write_text(
        json.dumps(sanctions_placeholder(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    missing = sum(1 for v in data["vendors"] if v["tax_id"] is None)
    print(f"vendor_master.json   {len(data['vendors'])} vendors")
    print(f"  missing tax_id     {missing} ({missing / len(data['vendors']):.0%})")
    print(f"  planted cases      {len(data['_planted_cases'])}")
    print(f"sanctions_sample.json {len(sanctions_placeholder()['entities'])} entities (SYNTHETIC placeholder)")


if __name__ == "__main__":
    main()
