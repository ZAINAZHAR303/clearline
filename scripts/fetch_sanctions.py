"""Fetch the OFAC SDN list and curate a small, committed sample.

    python scripts/fetch_sanctions.py            # curate from cache, download if needed
    python scripts/fetch_sanctions.py --refresh  # force re-download

The full list is 7.6 MB and ~72,000 entities. Committing that would be the
"data too heavy" mistake, so the download lands in data/cache/ (gitignored) and
only a curated sample goes into data/sample/.

Why a sample is honest here rather than a shortcut: Clearline screens one
vendor at a time against candidate matches. The agent's behaviour depends on
the structure of a watchlist entry -- aliases, jurisdiction, programme -- not on
the size of the list. A reviewer can re-run with --refresh and point at the
full file by raising SAMPLE_SIZE.

Anchors
-------
Some entities are pinned into the sample because the synthetic vendor master is
built around them (see scripts/gen_vendor_master.py). Pinning is deterministic
so the demo cases survive a refresh.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SAMPLE = ROOT / "data" / "sample"

DATASET = "us_ofac_sdn"
BASE = f"https://data.opensanctions.org/datasets/latest/{DATASET}"
CSV_URL = f"{BASE}/targets.simple.csv"
INDEX_URL = f"{BASE}/index.json"

SAMPLE_SIZE = 300
SEED = 42
ANCHOR_COUNT = 6

csv.field_size_limit(10**7)


def _download(url: str, dest: Path, attempts: int = 4) -> None:
    """OpenSanctions sits behind a CDN that returns intermittent 504s on the
    larger files, so retry rather than failing the build."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "clearline-hackathon"})
            with urllib.request.urlopen(request, timeout=240) as response:
                data = response.read()
            if data[:15].lstrip().startswith(b"<"):
                raise RuntimeError("got an HTML error page, not the file")
            dest.write_bytes(data)
            print(f"  downloaded {dest.name}  {len(data) / 1e6:.1f} MB")
            return
        except Exception as error:  # noqa: BLE001 -- retry on anything transient
            last = error
            print(f"  attempt {attempt}/{attempts} failed: {str(error)[:90]}")
    raise SystemExit(f"could not download {url}: {last}")


def provenance() -> dict:
    path = CACHE / "ofac_index.json"
    if not path.exists():
        _download(INDEX_URL, path)
    index = json.loads(path.read_text(encoding="utf-8"))
    publisher = index.get("publisher") or {}
    return {
        "dataset": DATASET,
        "title": index.get("title"),
        "publisher": publisher.get("name"),
        "publisher_url": publisher.get("url"),
        "source_url": CSV_URL,
        "snapshot_updated_at": index.get("updated_at"),
        "entity_count_full_dataset": index.get("entity_count"),
        "license": index.get("license") or publisher.get("url"),
        "note": "Curated subset. Re-fetch with scripts/fetch_sanctions.py --refresh.",
    }


def load_organisations(path: Path) -> list[dict]:
    """Organizations only. Clearline screens corporate counterparties, so the
    ~7,500 Person records are noise for this use case."""
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("schema") not in {"Organization", "Company"}:
                continue
            aliases = [a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()]
            countries = [c.strip() for c in (row.get("countries") or "").split(";") if c.strip()]
            if not aliases or not countries:
                continue
            rows.append({
                "id": row["id"],
                "caption": row["name"],
                "aliases": aliases,
                "country": countries[0].upper(),
                "topics": ["sanction"],
                "programme": (row.get("sanctions") or "").split(";")[0].strip(),
                "dataset": DATASET,
            })
    return rows


def pick_anchors(rows: list[dict]) -> list[dict]:
    """Entities the vendor master is built around. Chosen deterministically:
    at least two aliases (so alias drift is demonstrable), a short enough name
    to read on a slide, and sorted by id so a refresh keeps the same cases."""
    eligible = [
        r for r in rows
        if len(r["aliases"]) >= 2
        and 12 <= len(r["caption"]) <= 48
        and r["caption"].isascii()
        and all(a.isascii() for a in r["aliases"][:3])
    ]
    eligible.sort(key=lambda r: r["id"])
    return eligible[:ANCHOR_COUNT]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="force re-download")
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    SAMPLE.mkdir(parents=True, exist_ok=True)

    raw = CACHE / "ofac_targets.simple.csv"
    if args.refresh or not raw.exists():
        print(f"fetching {CSV_URL}")
        _download(CSV_URL, raw)
    else:
        print(f"using cached {raw.name} ({raw.stat().st_size / 1e6:.1f} MB)")

    rows = load_organisations(raw)
    print(f"  organisations with aliases and a country: {len(rows)}")

    anchors = pick_anchors(rows)
    anchor_ids = {a["id"] for a in anchors}
    rest = [r for r in rows if r["id"] not in anchor_ids]
    random.Random(SEED).shuffle(rest)
    selected = anchors + rest[: max(0, SAMPLE_SIZE - len(anchors))]

    out = {"provenance": provenance(), "anchors": [a["id"] for a in anchors],
           "entities": selected}
    target = SAMPLE / "sanctions_sample.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nwrote {target.relative_to(ROOT)}  {len(selected)} entities, "
          f"{target.stat().st_size / 1024:.0f} KB")
    print(f"snapshot: {out['provenance']['snapshot_updated_at']}")
    print("\nanchors (the vendor master is built around these):")
    for a in anchors:
        print(f"  {a['id']}  {a['caption']}  [{a['country']}]  aliases={len(a['aliases'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
