"""Fetch REAL corporate control chains from GLEIF.

    python scripts/fetch_gleif_chains.py           # from cache, fetch if absent
    python scripts/fetch_gleif_chains.py --refresh # re-query GLEIF

This removes the project's weakest claim. The control graph was synthetic
because our demo vendors are fictional and fictional companies have no LEI.
But the OFAC extract carries LEI codes for 187 sanctioned organisations, and
GLEIF publishes their Level 2 parent/child relationships -- so a real
subsidiary whose real ultimate parent is a real designated entity can be
walked end to end from public records alone.

What this is and is not
-----------------------
Both halves are public record: the designation is published by OFAC, and the
parent relationship is self-reported to GLEIF by the entity itself. Joining
them is exactly what sanctions screening is, and states no opinion about any
company beyond what those two sources already say.

GLEIF Level 2 records the ACCOUNTING CONSOLIDATING parent -- the entity that
includes this one in its consolidated financial statements. It is not an
ownership percentage, and none is recorded or inferred here. OFAC's 50% Rule
turns on ownership, so a chain found this way is evidence for review, not a
determination.

No API key. GLEIF rate-limits, so requests are paced and cached.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SAMPLE = ROOT / "data" / "sample"
OFAC_CSV = CACHE / "ofac_targets.simple.csv"

GLEIF = "https://api.gleif.org/api/v1"
LEI_RE = re.compile(r"\b[A-Z0-9]{18}[0-9]{2}\b")
PACE_SECONDS = 0.25
MAX_PARENTS_TO_PROBE = 200

csv.field_size_limit(10**7)


def _get(url: str, attempts: int = 3):
    """GET with pacing and retry. A 404 is a legitimate answer from GLEIF --
    it means 'no such relationship' -- so it returns None rather than raising."""
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/vnd.api+json",
                         "User-Agent": "clearline-hackathon (sanctions screening research)"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:  # rate limited: back off rather than hammer
                time.sleep(2 * attempt)
                continue
            if attempt == attempts:
                return None
        except Exception:
            if attempt == attempts:
                return None
            time.sleep(1.0 * attempt)
    return None


def sanctioned_leis() -> list[dict]:
    """OFAC organisations that publish an LEI."""
    if not OFAC_CSV.exists():
        raise SystemExit("run scripts/fetch_sanctions.py first")
    out = []
    with OFAC_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("schema") not in {"Organization", "Company"}:
                continue
            found = LEI_RE.findall(row.get("identifiers") or "")
            if found:
                out.append({
                    "lei": found[0],
                    "caption": row["name"],
                    "country": (row.get("countries") or "").split(";")[0].upper(),
                    "programme": (row.get("sanctions") or "").split(";")[0].strip(),
                    "ofac_id": row["id"],
                })
    return out


def _entity(record: dict) -> dict:
    attrs = record.get("attributes", {}).get("entity", {})
    return {
        "lei": record.get("id"),
        "name": (attrs.get("legalName") or {}).get("name"),
        "country": (attrs.get("legalAddress") or {}).get("country"),
        "status": attrs.get("status"),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--limit", type=int, default=MAX_PARENTS_TO_PROBE)
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    SAMPLE.mkdir(parents=True, exist_ok=True)
    raw_cache = CACHE / "gleif_children.json"

    parents = sanctioned_leis()
    print(f"OFAC organisations publishing an LEI: {len(parents)}")

    if raw_cache.exists() and not args.refresh:
        probed = json.loads(raw_cache.read_text(encoding="utf-8"))
        print(f"using cached GLEIF responses for {len(probed)} parents")
    else:
        probed = {}
        print(f"querying GLEIF for up to {args.limit} parents (paced, no key needed)...")
        for index, parent in enumerate(parents[: args.limit], 1):
            payload = _get(f"{GLEIF}/lei-records/{parent['lei']}/direct-children")
            probed[parent["lei"]] = [_entity(k) for k in ((payload or {}).get("data") or [])]
            if index % 25 == 0:
                print(f"  {index}/{min(len(parents), args.limit)}")
            time.sleep(PACE_SECONDS)
        raw_cache.write_text(json.dumps(probed, ensure_ascii=False), encoding="utf-8")

    by_lei = {p["lei"]: p for p in parents}
    chains = []
    for lei, children in probed.items():
        for child in children:
            if not child.get("lei") or not child.get("name"):
                continue
            parent = by_lei.get(lei, {})
            chains.append({
                "child": child,
                "parent": {
                    "lei": lei,
                    "name": parent.get("caption"),
                    "country": parent.get("country"),
                    "status": "SANCTIONED",
                },
                "relation": "ULTIMATE_PARENT",
                "ofac_id": parent.get("ofac_id"),
                "programme": parent.get("programme"),
            })

    out = {
        "provenance": {
            "source": "GLEIF Level 2 direct-children, joined to OFAC SDN entries carrying an LEI",
            "gleif_api": f"{GLEIF}/lei-records/{{lei}}/direct-children",
            "relationship_type": "accounting consolidating parent",
            "not_included": "ownership percentages -- GLEIF does not publish them and none is inferred",
            "both_halves_are_public_record": True,
            "retrieved": time.strftime("%Y-%m-%d"),
            "parents_probed": len(probed),
        },
        "chains": chains,
    }
    target = SAMPLE / "gleif_chains.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # Pin the sanctioned parents into the watchlist sample. Without this the
    # walk reaches a real parent and finds nothing to match it against, because
    # the 300-record curated subset need not contain these specific entities.
    sample_path = SAMPLE / "sanctions_sample.json"
    if sample_path.exists():
        watchlist = json.loads(sample_path.read_text(encoding="utf-8"))
        have = {e["id"] for e in watchlist["entities"]}
        aliases_by_id = {}
        with OFAC_CSV.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                aliases_by_id[row["id"]] = [
                    a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()
                ]
        added = 0
        for chain in chains:
            ofac_id = chain.get("ofac_id")
            if not ofac_id or ofac_id in have:
                continue
            watchlist["entities"].append({
                "id": ofac_id,
                "caption": chain["parent"]["name"],
                "aliases": aliases_by_id.get(ofac_id, []),
                "country": chain["parent"]["country"] or "",
                "topics": ["sanction"],
                "programme": chain.get("programme") or "",
                "dataset": "us_ofac_sdn",
            })
            have.add(ofac_id)
            added += 1
        watchlist["gleif_linked"] = sorted({c["ofac_id"] for c in chains if c.get("ofac_id")})
        sample_path.write_text(
            json.dumps(watchlist, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"pinned {added} sanctioned parent(s) into the watchlist sample")

    print(f"\nwrote {target.relative_to(ROOT)}  {len(chains)} real chain(s), "
          f"{target.stat().st_size / 1024:.0f} KB")
    for chain in chains[:8]:
        print(f"  {chain['child']['name'][:44]} [{chain['child']['country']}]")
        print(f"    -> {chain['relation']} -> {chain['parent']['name'][:44]} "
              f"[{chain['parent']['country']}]  SANCTIONED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
