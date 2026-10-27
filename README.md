# Clearline

**Sanctions exposure screening for companies that have no compliance desk.**

Clearline decides whether to onboard, block or escalate a vendor — resolving it
across an internal vendor book and the real OFAC sanctions list, walking its
corporate control chain for indirect exposure, and producing a decision with a
complete evidence trail and explicitly named unresolved conflicts.

Open Agent Hackathon 2026 · **Track 1 — Solving Fragmented Intelligence**
Every answer traces to a source row, so it speaks to Track 2 as well.

```bash
git clone https://github.com/ZAINAZHAR303/clearline && cd clearline
python -m clearline.run --vendor V0001 --fake      # no API key needed
```

---

## Contents

| | |
|---|---|
| [The problem](#the-problem) | Why name-only screening fails, and what it costs |
| [What Clearline does](#what-clearline-does) | Three decisions, never a bare verdict |
| [Quickstart](#quickstart) | Running it in two minutes with no API key |
| [What you'll see](#what-youll-see) | Ten planted cases and what each proves |
| [How it works](#how-it-works) | Five agents, seven branches, and the split that matters |
| [Screening a whole book](#screening-a-whole-book) | 200 vendors, two stages |
| [The correction loop](#the-correction-loop) | A reviewer disagrees, and the next run changes |
| [Accuracy](#accuracy) | Measured against a labelled set, not asserted |
| [Cost](#cost) | Reasoning spent in proportion to risk |
| [Sponsor technology](#sponsor-technology) | Load-bearing, not mentioned |
| [Autonomy](#autonomy) | L2 for resolution, L1 for the decision |
| [Tests](#tests) | 24 offline assertions, two conformance suites |
| [Limitations](#limitations) | Stated plainly |
| [Layout](#repository-layout) | Where everything lives |

> **New to this domain?** [`docs/DOMAIN.md`](docs/DOMAIN.md) explains vendors,
> sanctions screening and OFAC's 50 Percent Rule from zero, with sources —
> including the October 2026 enforcement action this project mirrors.

---

## The problem

A company with 200–2,000 staff has no sanctions-screening desk and no
$50,000/yr Refinitiv subscription. So it either doesn't screen vendors at all,
or screens on legal name only. Name-only screening misses the two things that
matter.

**1. Aliases.** The listed entity is recorded under a name your vendor book has
never seen. `Metaalkunde BV` reads as an ordinary Belgian engineering supplier.
It is an exact alias of a sanctioned entity.

**2. Indirect exposure.** The vendor is clean; its ultimate parent is not. Under
OFAC's **50 Percent Rule**, a company owned 50% or more by a sanctioned party is
blocked too — **and it is never added to the list**. The entity that creates
your legal exposure is, by design, one you cannot find by searching.

It is strict liability. Not knowing is not a defence.

> On **9 October 2026**, a freight forwarder called Pegasus Worldwide Logistics
> paid **$175,015** to settle a sanctions violation. A supplier they already used
> was designated, changed its name, and carried on trading. Pegasus screened the
> new name. It came back clean. Same entity, clean screen, violation anyway.

A false negative is a legal violation. A false positive freezes a legitimate
supplier and stops a production line. Today that call is made by a human with
twelve browser tabs in about forty minutes.

---

## What Clearline does

Five agents, a deterministic matching layer, and two Meterless engines produce
one of three decisions:

| | |
|---|---|
| **BLOCK** | Exposure found, and the evidence names it: which entity, which alias, which hop of which ownership chain. |
| **CLEAR** | Checked and nothing found — with a record of *what* was checked, so "nothing matched" stays distinguishable from "we never looked". |
| **ESCALATE** | Cannot be settled from the available data, carrying one specific question for the human who can settle it. |

Every claim in a rationale maps to an entry in the evidence list. Anything
unsupported goes to `unresolved_conflicts` instead of being asserted — and a
test fails the build if a BLOCK cites nothing.

Here is a real decision, from [`data/sample_runs/V0009.out.txt`](data/sample_runs/V0009.out.txt):

```
  BLOCK  confidence 0.90
  Xing Ao Energy Pte. Ltd. is clean on its own name, but its control chain
  reaches Hebei Xinhai Chemical Group Co., Ltd., a listed entity, at depth 1
  via ultimate parent.

  evidence
    - control chain hop 1: Hebei Xinhai Chemical Group Co., Ltd. (ULTIMATE_PARENT)
      [control_graph L:655600I0RTPZ3DFASH49]
    - Hebei Xinhai Chemical Group Co., Ltd. is listed
      [us_ofac_sdn NK-HkGpeehSFsNLXBJ9tywZCf]

  caveats
    ~ tax_id is unreliable in this source
    ~ watchlist: us_ofac_sdn snapshot 2026-10-22, curated subset of 72614 entities
    ~ control relationship, NOT a measured ownership percentage

  ask the reviewer: Confirm the control relationship with the registry
                    before freezing payments.
```

Both halves of that are public record: a real Singapore company with a real
LEI, and a real OFAC-designated parent, joined by real GLEIF data.

---

## Quickstart

### Dependencies

| | |
|---|---|
| Python | 3.12+ |
| Node | 20+ (the Meterless engines are TypeScript) |
| Docker | only for Zetaris; Clearline runs without it |
| A Nemotron route | NVIDIA's free API, or Meterless/Nightshift — **optional** |

### Run it in two minutes, with no API key at all

```bash
git clone https://github.com/ZAINAZHAR303/clearline.git
cd clearline
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
#    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt # macOS/Linux

python scripts/fetch_sanctions.py      # curates 321 OFAC records (one download, cached)
python scripts/gen_vendor_master.py    # builds the vendor book around them
python scripts/fetch_gleif_chains.py   # REAL ownership chains from GLEIF
python scripts/gen_control_graph.py    # builds the control graph

cd engines/markovian && npm install && cd ../..
cd engines/hmem && npm install && cd ../..

python -m clearline.run --vendor V0001 --fake
```

`--fake` substitutes deterministic model responses, so the whole agent system —
every branch, the revision loop, the chain walk, the memory — runs offline in
about a second. Use it to inspect behaviour without burning tokens.

**Already-committed outputs** for five vendors, covering all three decisions,
are in [`data/sample_runs/`](data/sample_runs/) with their full traces.

### Run it against a live model

Copy `.env.example` to `.env` and fill in your route. All three `MODEL_*`
values must come from the **same** provider.

```bash
python smoke_test.py                   # 4 checks: Zetaris, SQL, sample data, Nemotron
python -m clearline.run --vendor V0001 # ~130s
```

### With Zetaris (full data layer)

```bash
bash scripts/sidecar.sh                # serves data/sample on the Zetaris network
python scripts/apply_sql.py sql/01_databases.sql sql/02_rest_tables.sql sql/03_usl_counterparty.sql
```

Clearline falls back to local files whenever Zetaris is unreachable, recording
which path ran — so a judge without the platform still gets a working system.

---

## What you'll see

Ten planted cases, each exercising a specific behaviour. Expected outcomes live
in `data/sample/vendor_master.json` under `_demo_cases`; nothing in
`clearline/` reads that key, so the system cannot pass by looking up answers.

| Vendor | Case | Result |
|---|---|---|
| `V0001` Metaalkunde BV | Exact alias of a listed Belgian firm. **The name gives nothing away** | **BLOCK** |
| `V0002` South Wealth Resources Ltd. | Exact alias, same jurisdiction | **BLOCK** |
| `V0003` Southwealth Resources Pty Ltd | Same anchor as V0002 — fuzzy overlap, different jurisdiction | **CLEAR** |
| `V0004` Nordvik Components GmbH | Clean on its own name; the **control chain** reaches a listed entity | **BLOCK** |
| `V0005` / `V0006` | Generic names, no identifier | **ESCALATE** |
| `V0007` / `V0008` Copperline | Same entity, two IDs, two spellings | **CLEAR** |
| **`V0009` Xing Ao Energy Pte. Ltd.** | **Real** Singapore company. GLEIF reports its ultimate parent as a **real OFAC-designated** Chinese group | **BLOCK** |
| **`V0010` Rayblue International Corp.** | **Real** BVI company, **real** sanctioned ultimate parent | **BLOCK** |

**V0002 and V0003 are the pair worth watching.** Same watchlist entity,
near-identical names, opposite outcomes — and the system has to say why.

---

## How it works

```
  INTAKE & RISK ROUTER ──▶ RESOLVER ◀──┐  critic demands a specific field
   ambiguity gate            │         │
   refuses to guess          ▼         │
                        CONFLICT CRITIC ┘  tries to BREAK the match
                             │
                   ACCEPT / REJECT / REROUTE
                             │
                     OWNERSHIP WALKER        ← Meterless Markovian
                   control chain, bounded      one hop per chunk
                             │
                        ADJUDICATOR          ← Nemotron, tiered by stakes
                             │
        reviewer override ──▶ H-MEM ──▶ changes the NEXT decision
```

### The branches that make it an agent

Each writes a `branch` event into the trace, so every one is visible after the
fact in [`data/sample_runs/`](data/sample_runs/):

| # | Branch | What it does |
|---|---|---|
| 1 | **Ambiguity gate** | Refuses to guess when a name is too generic to resolve |
| 2 | **DQ-driven replan** | Reads Zetaris data quality at runtime and raises its own evidence bar |
| 3 | **Resolver ↔ critic** | Bounded revision loop; the critic demands *one named field* |
| 4 | **Reroute to chain walk** | Name evidence cannot settle it, so walk ownership |
| 5 | **Confidence escalation** | Hands back to a human with a specific question |
| 6 | **Memory override** | A reviewer's correction drops a candidate before evidence is weighed |
| 7 | **Safety floors** | An exact alias is never CLEARED without review |

### The split that matters

> **Deterministic code decides what *is* true. The model decides what it *means*.**

| Code, not the model | The model, not code |
|---|---|
| Alias and name scoring | Is this the same company? |
| Jurisdiction agreement | Is this ownership hop material? |
| Reachability in the control graph | What must a reviewer be told? |
| Thresholds and the evidence bar | Which question would settle it? |
| The safety floors | What cannot be supported? |

This is not a style preference. The live model once returned **BLOCK with
confidence 0.18** on an exact alias match — a narrative number, inconsistent
with its own decision. Control flow therefore tests the deterministic score,
never the model's certainty about itself. Evidence strength is a fact; the
model's self-report is not.

---

## Screening a whole book

```bash
python -m clearline.batch --fake
```

```
VENDOR BOOK   200 vendors · $120,630,000 annual spend
TRIAGE        25 need review, 175 cleared without it (12.5% reviewed) in 3.6s
DECISIONS     13 BLOCK   7 ESCALATE   5 CLEAR
EXPOSURE      $7,528,000 of spend needs action, of $12,781,000 reviewed
```

Nobody screens one vendor; they have hundreds, and running five agents over all
of them would be absurd — the deliberation cost is what stops a tool like this
ever being run.

So screening is **two stages**, and the split is the same thesis as the
reasoning budget: spend effort in proportion to risk. **Triage** is
deterministic and runs over every vendor, applying four cheap tests — a
watchlist candidate above the noise floor, a name too generic to resolve,
banking in a country it is not registered in, or a control chain that reaches a
listed entity. Only those vendors get the **full agent system**. The other 175
are cleared with a recorded reason.

---

## The correction loop

```bash
python -m clearline.run --vendor V0001 --fake          # BLOCK
python -c "from clearline.memory import override; \
           override('V0001','NK-24kqBFxEsFzjqBYhaNHkC9','wrong','alice')"
python -m clearline.run --vendor V0001 --fake          # now CLEAR
```

A reviewer marks the match wrong. H-MEM drops its confidence by exactly 0.20,
tags it for review, and writes both states to an append-only trust ledger. The
next run reaches a different decision and says which correction did it.

The correction **persists** — that is the point — so V0001 stays CLEAR until you
clear the memory:

```bash
cd engines/hmem && npx tsx src/cli.ts forget-all && cd ../..
```

---

## Accuracy

```bash
python scripts/evaluate.py --fake
```

Eight passing demos prove little — a reader is entitled to wonder whether eight
cases were chosen because they pass. So there is a labelled set: **33 cases, 16
with genuine exposure and 17 clean**, across eight categories including
deliberate near-misses in both directions.

| | result |
|---|---|
| **Misses** (exposed vendor CLEARED) | **0 / 16** — recall 16/16 |
| **False blocks** (clean vendor BLOCKED) | **0 / 17** |
| Escalations | 7 / 33 — review workload, not failure |

The two error types are **never averaged into one accuracy number**, because
they are not symmetric: clearing an exposed vendor is the legal violation,
blocking a clean one freezes a real supplier. Escalations are reported beside
them, because a tool that escalated everything would score zero on both and be
useless.

**The harness found four real bugs on its first run** — including jurisdiction
mismatch being treated as evidence *against* identity, which is precisely the
Pegasus pattern. Details in [`docs/measurements.md`](docs/measurements.md).

---

## Cost

Measured from the provider's own usage accounting, not estimated.

| | baseline | tiered | change |
|---|---|---|---|
| One vendor, end to end | 1236.3 s | **132.0 s** | **9.4× faster** |
| Router | 102.8 s | **2.9 s** | **35× faster** |
| Produced a decision | no | **yes** | |

The baseline used one model on every tier and did not even produce a decision:
the adjudicator spent 100% of its token budget on reasoning and emitted nothing.

Three findings behind the fix:

- **Reasoning tokens are billed against `max_tokens`.** Nemotron returns chain
  of thought in a separate field, so content comes back empty — which presents
  as a JSON parse failure and is not one.
- **A `/no_think` directive only halves deliberation** (429 tokens). The
  `chat_template_kwargs: {thinking: false}` flag zeroes it. Found by A/B test.
- **Most of what looked like a cost problem was a correctness problem.** The
  critic fell from 5 calls to 1 once it could see the candidate's alias list.
  An agent that cannot resolve a question keeps asking.

An unresolvable name costs **2.4 seconds and zero reasoning tokens** — the
router settles it and the expensive agents never run.

Full tables: [`docs/measurements.md`](docs/measurements.md).

---

## Sponsor technology

Full detail in [`SPONSOR_TECH.md`](SPONSOR_TECH.md).

### Zetaris — the provenance layer, not a database

A Unified Semantic Layer ([`sql/03_usl_counterparty.sql`](sql/03_usl_counterparty.sql))
models `counterparty`, `watchlist_entity` and `watchlist_alias` with declared
foreign keys, so one semantic query spans the internal book and the OFAC list.

**The load-bearing part:** `RUN DQ TABLE` checks the constraints the semantic
layer declares, and **the agent reads that result at runtime and raises its own
evidence bar because of it** — data quality changes the plan, not just the data.

### Meterless — two engines, both doing real work

| Engine | Implementation | What it does here |
|---|---|---|
| **Markovian** | `engines/markovian/src/index.ts` | Bounds the control-chain walk — one hop per chunk carrying a compressed state summary, with termination via markers, cycle detection and a depth cap. **86% fewer tokens** on a 20-hop walk (246,000 → 34,000) |
| **H-MEM** | `engines/hmem/src/index.ts` | Holds reviewer corrections. A wrong match loses exactly 0.20 confidence, gains a review tag, and both states go to an append-only trust ledger that changes the next decision |

```bash
bash scripts/conformance.sh
#   Markovian   8/8    H-MEM   13/13
```

Delete either engine and a demo case fails.

### NVIDIA Nemotron — tiered by stakes

Lightning (3B active) for extraction with deliberation off, Super for the critic
loop, Ultra (55B active) for contested adjudication only — with the reasoning
budget driven by risk tier and critic pushback.

**Built with** Claude Code.

---

## Autonomy

Stated per capability, because the two halves sit at different levels
deliberately (see `metadata.json`):

- **L2 — resolution and the chain walk.** The agent runs its own loop with no
  human in it: the critic may demand one specific missing field, the walker
  decides for itself when name evidence is exhausted, and it must pass its own
  checks to proceed.
- **L1 — the block/clear decision.** The adjudicator recommends; a person
  approves. Every output names what a human must confirm.

Clearing an exposed vendor is a sanctions violation and blocking a clean one
freezes a real supplier. The agent can recover from neither, so the final call
stays with a person.

---

## Tests

```bash
pytest -q                  # 24 tests, offline, deterministic, ~75s
bash scripts/conformance.sh
```

The suite runs the whole agent system against every planted case with fake model
responses, verifying orchestration — branching, the revision loop, the
data-quality replan, escalation, the override loop — plus the trust ledger's
invariants. It cannot verify that a prompt conveys the task; that needs live
runs, and those are recorded in [`docs/measurements.md`](docs/measurements.md).

---

## Limitations

Stated plainly, because a screening tool that overclaims is worse than none.

- **The vendor book is synthetic.** Real vendor masters are confidential. Several
  vendors are deliberately named after real OFAC aliases, because that is what a
  true positive looks like. No claim is made about any real company beyond the
  public designation already in the source data.
- **The control graph is part real, part synthetic.** 47 chains are **real**,
  retrieved from the GLEIF Level 2 API and joined to OFAC SDN entries that
  publish an LEI. `V0009` and `V0010` are real companies with real LEIs whose
  real ultimate parents are really designated. The remaining chains are
  synthetic, because the fictional vendors they belong to have no LEI. The file
  records which is which.
- **No ownership percentages, ever.** GLEIF publishes control and consolidation
  relationships, not percentages. OFAC's 50% rule needs ownership data these
  sources do not provide, so indirect findings are reported as control
  relationships and flagged for human confirmation. A test enforces it.
- **The watchlist is a 321-record curated subset** of 72,614, snapshot
  2026-10-22, recorded in the file. OFAC only — no EU, UN or UK list, and no PEP
  or adverse-media screening. Raise `SAMPLE_SIZE` and re-fetch for more.
- **Decision support, not decision authority.** Every output names what a human
  must confirm.

### Prior art

This problem is solved at the top of the market. **Refinitiv World-Check**,
**LexisNexis Firco** and **Kharon** all do ownership-aware screening, with
research teams and licensed data Clearline has no access to. They are also
priced and shaped for institutions that already have a compliance function. The
company with 200 staff and no screening desk is not a smaller version of that
customer — it is an unserved one.

---

## Repository layout

```
clearline/          agents, orchestrator, matching, memory, walker, Zetaris client, trace
engines/
  markovian/        bounded chain walk, implemented from the Meterless spec
  hmem/             reviewer corrections and the trust ledger
sql/                Lightning SQL: databases, REST tables, the USL Counterparty model
scripts/            data generation, SQL application, conformance, evaluation, trace summaries
tests/              24 offline assertions: the planted cases, and the ledger's invariants
viewer/             trace viewer and review queue
data/
  sample/           committed source data, with provenance — see data/README.md
  sample_runs/      five vendors end to end: the decision and the full trace behind it
docs/
  DOMAIN.md         the problem domain from zero, with sources
  measurements.md   measured before/after numbers
metadata.json       sponsor usage, autonomy levels, declared pre-existing components
```

---

## License

[MIT](LICENSE).
