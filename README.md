# Clearline

**Clearline helps a procurement officer at a mid-size company decide whether to onboard, block, or escalate a vendor — by resolving that vendor across an internal vendor book and the real OFAC sanctions list, walking its corporate control chain for indirect exposure, and producing a decision with a complete evidence trail and explicitly named unresolved conflicts.**

Open Agent Hackathon 2026 · **Track 1 — Solving Fragmented Intelligence**
(Every answer is traceable to a source row, so it speaks to Track 2 as well.)

---

> New to this domain? [`docs/DOMAIN.md`](docs/DOMAIN.md) explains vendors,
> sanctions screening and OFAC's 50 Percent Rule from zero, with sources —
> including the October 2026 enforcement action this project mirrors.

## The problem

A company with 200–2,000 staff has no sanctions-screening desk and no $50k/yr
Refinitiv subscription. So it either doesn't screen vendors at all, or screens
on legal name only. Name-only screening misses the two things that matter:

1. **Aliases.** The listed entity is recorded under a name your vendor book has
   never seen. `Metaalkunde BV` reads as an ordinary Belgian engineering
   supplier. It is an exact alias of a sanctioned entity.
2. **Indirect exposure.** The vendor is clean; its ultimate parent is not.
   Walking a corporate chain by hand is infeasible, so nobody does it.

A false negative is a legal violation. A false positive freezes a legitimate
supplier and stops a production line. Today that call is made by a human with
twelve browser tabs in about forty minutes.

## What Clearline does

Five agents, a deterministic matching layer, and two Meterless engines.
Decisions are **CLEAR**, **BLOCK** or **ESCALATE**, and every claim in a
rationale maps to an entry in the evidence list — anything unsupported goes in
`unresolved_conflicts` instead.

```
  INTAKE & RISK ROUTER ──▶ RESOLVER ◀──┐  critic demands a specific field
   Scout-Intent-style         │        │
   ambiguity gate             ▼        │
                        CONFLICT CRITIC ┘  tries to BREAK the match
                             │
                   ACCEPT / REJECT / REROUTE
                             │
                     OWNERSHIP WALKER        ← Meterless Markovian
                   control chain, bounded      one hop per chunk
                             │
                        ADJUDICATOR          ← Nemotron, tiered
                             │
        reviewer override ──▶ H-MEM ──▶ changes the NEXT decision
```

---

## Quickstart

### Dependencies

| | |
|---|---|
| Python | 3.12+ |
| Node | 20+ (the Meterless engines are TypeScript) |
| Docker | only for Zetaris; Clearline runs without it |
| A Nemotron route | NVIDIA's free API, or Meterless/Nightshift |

### Run it in two minutes, with no API key at all

```bash
git clone https://github.com/ZAINAZHAR303/clearline.git
cd clearline
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
#    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt # macOS/Linux

python scripts/fetch_sanctions.py      # curates 300 OFAC records (one download, cached)
python scripts/gen_vendor_master.py    # builds the vendor book around them
python scripts/gen_control_graph.py    # builds the control graph

cd engines/markovian && npm install && cd ../..
cd engines/hmem && npm install && cd ../..

python -m clearline.run --vendor V0001 --fake
```

`--fake` substitutes deterministic model responses, so the whole agent system —
every branch, the revision loop, the chain walk, the memory — runs offline in
about a second. Use it to inspect behaviour without burning tokens.

### Run it against a live model

Copy `.env.example` to `.env` and fill in your route. All three `MODEL_*`
values must come from the **same** provider.

```bash
python smoke_test.py                   # 4 checks: Zetaris, SQL, sample data, Nemotron
python -m clearline.run --vendor V0001 # ~110s
```

### With Zetaris (full data layer)

```bash
bash scripts/sidecar.sh                        # serves data/sample on the Zetaris network
python scripts/apply_sql.py sql/01_databases.sql sql/02_rest_tables.sql sql/03_usl_counterparty.sql
```

Clearline falls back to local files whenever Zetaris is unreachable, recording
which path ran — so a judge without the platform still gets a working system.

---

## What you'll see

Eight planted cases, each exercising a specific behaviour. Expected outcomes
live in `data/sample/vendor_master.json` under `_demo_cases`; nothing in
`clearline/` reads that key, so the system cannot pass by looking up answers.

| Vendor | Case | Result |
|---|---|---|
| `V0001` Metaalkunde BV | Exact alias of a listed Belgian firm. **The name gives nothing away** | **BLOCK** |
| `V0002` South Wealth Resources Ltd. | Exact alias, same jurisdiction | **BLOCK** |
| `V0003` Southwealth Resources Pty Ltd | Same anchor as V0002 — fuzzy overlap, different jurisdiction | **CLEAR** |
| `V0004` Nordvik Components GmbH | Clean on its own name; the **control chain** reaches a listed entity | **BLOCK** |
| `V0005` / `V0006` | Generic names, no identifier | ESCALATE |
| `V0007` / `V0008` Copperline | Same entity, two IDs, two spellings | CLEAR |

**V0002 and V0003 are the pair worth watching.** Same watchlist entity,
near-identical names, opposite outcomes — and the system has to say why.

### Screen the whole book

```bash
python -m clearline.batch --fake
```

```
VENDOR BOOK   200 vendors · $128,438,000 annual spend
TRIAGE        9 need review, 191 cleared without it (4.5% reviewed) in 3.9s
DECISIONS     4 BLOCK   2 ESCALATE   3 CLEAR
EXPOSURE      $386,000 of spend needs action, of $3,491,000 reviewed
```

Screening is two stages, and the split is the same thesis as the reasoning
budget — spend effort in proportion to risk. **Triage** is deterministic and
runs over every vendor: a watchlist candidate above the noise floor, a name too
generic to resolve, banking in a country it is not registered in, or a control
chain that reaches a listed entity. Only those vendors get the **full agent
system**. The other 191 are cleared with a recorded reason, because "nothing
matched" and "we never looked" have to stay distinguishable.

### The correction loop

```bash
python -m clearline.run --vendor V0001 --fake          # BLOCK
python -c "from clearline.memory import override; \
           override('V0001','NK-24kqBFxEsFzjqBYhaNHkC9','wrong','alice')"
python -m clearline.run --vendor V0001 --fake          # now CLEAR
```

A reviewer marks the match wrong. H-MEM drops its confidence by exactly 0.20,
tags it for review, and writes both states to an append-only trust ledger. The
next run reaches a different decision and says which correction did it.

The correction **persists** — that is the point — so V0001 stays CLEAR until
you clear the memory. To return to a clean slate:

```bash
cd engines/hmem && npx tsx src/cli.ts forget-all && cd ../..
```

---

## Sponsor technology

Full detail in [`SPONSOR_TECH.md`](SPONSOR_TECH.md); measured numbers in
[`docs/measurements.md`](docs/measurements.md).

**Zetaris** is the provenance layer, not a database. A Unified Semantic Layer
(`sql/03_usl_counterparty.sql`) models `counterparty`, `watchlist_entity` and
`watchlist_alias` with declared foreign keys, so one semantic query spans the
internal book and the OFAC list. `RUN DQ TABLE` checks the constraints the
semantic layer declares, and **the agent reads that result at runtime and
raises its evidence bar because of it**.

**Meterless** — two engines implemented from the specs, passing the upstream
conformance suites, and load-bearing rather than mentioned:

| Engine | Implementation | Used by | What it does here |
|---|---|---|---|
| **Markovian** | `engines/markovian/src/index.ts` | `engines/markovian/src/walk.ts`, `clearline/walker.py` | Bounds the control-chain walk — one hop per chunk carrying a compressed state summary, and termination via markers, cycle detection and a depth cap |
| **H-MEM** | `engines/hmem/src/index.ts` | `engines/hmem/src/cli.ts`, `clearline/memory.py` | Holds reviewer corrections. A wrong match loses exactly 0.20 confidence, gains a review tag, and both states go to an append-only trust ledger that changes the next decision |

```bash
bash scripts/conformance.sh
#   Markovian   8/8    H-MEM   13/13
```

**NVIDIA Nemotron** is tiered by stakes — Lightning (3B active) for extraction
with deliberation off, Super for the critic loop, Ultra for contested
adjudication — with the reasoning budget driven by risk tier and critic
pushback. Measured: one vendor went from 1236s with a single model on every
tier to ~110s, and the router from 102.8s to 2.9s.

**Built with** Claude Code (Cursor became optional on 22 October).

---

## Tests

```bash
pytest -q                  # 17 tests, offline, deterministic, ~15s
bash scripts/conformance.sh
```

The suite runs the whole agent system against every planted case with fake
model responses. It verifies orchestration — branching, the revision loop, the
data-quality replan, escalation, the override loop. It cannot verify that a
prompt conveys the task; that needs live runs, and those are recorded in
`docs/measurements.md`.

## Limitations

Stated plainly, because a screening tool that overclaims is worse than none.

- **The vendor book is synthetic.** Real vendor masters are confidential.
  Several vendors are deliberately named after real OFAC aliases, because that
  is what a true positive looks like. No claim is made about any real company
  beyond the public designation already in the source data.
- **The control graph is synthetic.** Modelled on GLEIF Level 2 relationships.
  Fictional vendors have no LEI, and inventing one would be worse than saying
  so. Real LEIs would resolve against the live GLEIF API.
- **No ownership percentages, ever.** GLEIF publishes control and
  consolidation relationships, not percentages. OFAC's 50% rule needs ownership
  data these sources do not provide, so indirect findings are reported as
  control relationships and flagged for human confirmation. A test enforces it.
- **The watchlist is a 300-record curated subset** of ~72,600, with the
  snapshot date recorded in the file. Raise `SAMPLE_SIZE` and re-fetch for more.
- **Decision support, not decision authority.** Every output names what a human
  must confirm.

## Layout

```
clearline/      agents, orchestrator, matching, memory, walker, Zetaris client, trace
engines/        Markovian and H-MEM, implemented from the Meterless specs
sql/            Lightning SQL: databases, REST tables, the USL Counterparty model
scripts/        data generation, SQL application, conformance, trace summaries
tests/          17 offline assertions over the planted cases
docs/           measured before/after numbers
data/sample/    committed samples, with provenance — see data/README.md
```
