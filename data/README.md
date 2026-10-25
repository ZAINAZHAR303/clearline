# Data sources

Small, reproducible, and documented. Nothing here contains real personal,
proprietary or confidential data.

```bash
python scripts/fetch_sanctions.py      # curate the watchlist (downloads once, cached)
python scripts/gen_vendor_master.py    # build vendors around it
```

`data/cache/` holds the raw download and is gitignored. Only the curated
samples are committed.

---

## 1. `sample/sanctions_sample.json` — watchlist

**Real data.**

| | |
|---|---|
| Source | US OFAC Specially Designated Nationals (SDN) List, via OpenSanctions |
| Publisher | Office of Foreign Assets Control |
| URL | `https://data.opensanctions.org/datasets/latest/us_ofac_sdn/targets.simple.csv` |
| Full dataset | 72,614 entities / 7.6 MB |
| Committed subset | **321 organisations**, 140 KB |
| Snapshot | recorded in the file under `provenance.snapshot_updated_at` |

Selection: `Organization` and `Company` records that have at least one alias
and a country. The ~7,500 `Person` records are excluded — Clearline screens
corporate counterparties. The remainder is a seeded random sample, so a
re-fetch reproduces the same file.

**Why a subset is honest here.** Clearline screens one vendor at a time against
ranked candidates. Its behaviour depends on the *structure* of a designation —
aliases, jurisdiction, programme — not on list size. Raise `SAMPLE_SIZE` in
`scripts/fetch_sanctions.py` and re-run to work against more of it.

Licensing: the underlying OFAC list is a US government publication; the
`provenance` block records what the dataset index reports. Confirm
OpenSanctions' own terms before any use beyond this prototype.

### Anchors

Six entities are pinned into the sample because the vendor master is built
around them. Pinning is deterministic, so the demo cases survive a refresh.

---

## 2. `sample/vendor_master.json` — internal vendor master

**Synthetic**, generated with `SEED = 42`. 200 vendors.

This stands in for an ERP vendor extract — the internal data an organisation
runs on, which is what Zetaris exists to serve. It is synthetic because a real
vendor master is confidential.

> The vendors are fictional. Several are **deliberately named after real
> aliases of real OFAC-listed entities**, because that is what a true positive
> looks like. No claim is made about any real company beyond the public
> designation already recorded in the source dataset.

### Demo cases

`_demo_cases` in the JSON maps each vendor to its expected outcome and why.
Nothing in `clearline/` reads that key, so the system cannot pass by looking up
answers — `tests/test_demo_cases.py` asserts against it.

| Vendor | Case | Expected |
|---|---|---|
| `V0001` Metaalkunde BV | Exact alias of a listed Belgian engineering firm. **The name gives nothing away** — this is the case name-only screening misses | **BLOCK** |
| `V0002` South Wealth Resources Ltd. | Exact alias, same jurisdiction | **BLOCK** |
| `V0003` Southwealth Resources Pty Ltd | Same anchor as V0002, but fuzzy overlap only and a different jurisdiction | **CLEAR** |
| `V0004` Nordvik Components GmbH | Clean on its own name; ultimate parent is listed. Bank country disagrees with registered country | ESCALATE, then BLOCK once the chain is walked |
| `V0005` Global Trading Ltd | Generic name, no identifier | ESCALATE |
| `V0006` International Services LLC | Generic name, no identifier | ESCALATE |
| `V0007` / `V0008` Copperline Industries | Same real entity, two IDs, two spellings, one missing tax ID | CLEAR (and deduplicate) |

**V0002 and V0003 are the pair that matters.** Same anchor, near-identical
names, opposite outcomes — and the system has to say why. A false negative is a
sanctions violation; a false positive freezes a real supplier and stops a
production line.

Across the filler rows: suffix variation (`Ltd` / `Limited` / `LLC` / `GmbH` /
`B.V.` / `Pte Ltd`) and **~16% missing `tax_id`**, which is what makes the
data-quality branch real rather than theatrical. The agent reads that null rate
at runtime and raises its evidence bar because of it.

---

## 3. Planned — GLEIF and EDGAR

| Source | Access | Notes |
|---|---|---|
| **GLEIF LEI** `api.gleif.org/api/v1` | Open, no key | `/lei-records/{lei}/direct-parent`, `/ultimate-parent`, `/direct-children` — the control chain. Rate-limited, so cache |
| **SEC EDGAR** `data.sec.gov` | Open | **403s without a descriptive `User-Agent`** — set it in the REST table's `HEADER()` block |

### An accuracy limit, stated plainly

GLEIF reports **control and accounting-consolidation relationships, not
ownership percentages**. Clearline therefore never asserts a percentage. OFAC's
50% rule needs ownership data these sources do not provide, so any indirect
finding is surfaced as a control relationship and flagged for human
confirmation.

---

## Shape, and how Zetaris reaches these files

Each file is a JSON **object** with records under one key (`vendors`,
`entities`), never a bare array — that is the shape Zetaris REST tables handle,
with arrays flattened via `LATERAL VIEW explode()`. See `sql/02_rest_tables.sql`.

Zetaris cannot read your host filesystem. `scripts/sidecar.sh` serves this
directory from a container on the Zetaris Docker network, so the files resolve
at `http://clearline-data/<file>` from inside the platform. No S3 account, no
edits to the Zetaris bundle, and it works offline.
