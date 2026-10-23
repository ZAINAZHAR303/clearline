# Sponsor technology

How Zetaris, Meterless and NVIDIA are used in Clearline, where that code lives,
and what was unique about each. Machine-readable equivalent:
[`metadata.json`](metadata.json). Measured figures: [`docs/measurements.md`](docs/measurements.md).

Everything below is reproducible:

```bash
bash scripts/conformance.sh                      # Meterless: 8/8 and 13/13
python scripts/trace_summary.py --all            # NVIDIA: per-agent reasoning spend
python scripts/apply_sql.py sql/*.sql            # Zetaris: the data layer
python -m clearline.run --vendor V0004 --fake    # all of it, offline
```

---

## Zetaris — the provenance layer, not a database

| Where | What |
|---|---|
| `sql/01_databases.sql` | Lightning database and schemastore container |
| `sql/02_rest_tables.sql` | REST tables over the internal vendor book and the OFAC extract; aliases flattened with `LATERAL VIEW explode()` |
| `sql/03_usl_counterparty.sql` | Unified Semantic Layer: `counterparty`, `watchlist_entity`, `watchlist_alias`, related by foreign key |
| `clearline/zetaris.py` | REST client, `run_sql()`, `dq_report()` |
| `scripts/sidecar.sh` | Serves `data/sample` on the Zetaris Docker network |
| `scripts/apply_sql.py` | Applies Lightning SQL one statement at a time |

### What it does

Two sources that share no key and disagree about names — an internal vendor
book and the real OFAC SDN list — become one governed model. A single semantic
query spans both:

```sql
SELECT c.vendor_id, c.legal_name, e.caption, e.dataset
FROM   counterparty_usl.counterparty c
JOIN   counterparty_usl.watchlist_alias  a ON lower(trim(c.legal_name)) = lower(trim(a.alias))
JOIN   counterparty_usl.watchlist_entity e ON e.entity_id = a.entity_id
```

Exactly two exact-alias hits out of 200 vendors — the two the demo expects.

### What was unique

**Data quality steers the agent at runtime.** `RUN DQ TABLE` checks the
constraints the semantic layer *declares*, so keys are verified by the platform
rather than asserted by us. The result is not filed alongside the answer — the
agent reads it *before* weighing any evidence and raises its bar because of it:

```
TOOL    dq_report   constraints=[{"column":"vendor_id","check":"Primary Key Constraint",
                                  "invalid":0,"passed":true}]  tax_id null_rate 0.16
BRANCH  RAISE_EVIDENCE_BAR   tax_id unreliable in this source (tax_id 16% null)
```

An agent reasoning about the *quality* of its data, not just its content, and
it is visible in every trace.

**Aliases are a first-class table.** `watchlist_alias` has its own primary key
and a foreign key to the entity, because the alias — not the caption — is what
identifies a counterparty. `Metaalkunde BV` is an alias of an entity whose
caption looks nothing like it, and modelling aliases as rows is what lets one
join find that.

**Three syntax findings**, documented in the SQL for whoever reads it next:
`DESCRIBE BY` rejects a colon and every dependent `CREATE` then fails with a
misleading *"Lightning Database doesn't exist"*; `COMPILE USL … DDL` wraps
several `CREATE TABLE` blocks so a file needs its own statement delimiter;
`NOT NULL` columns must be fed by provably non-null expressions, so `ACTIVATE`
needs `COALESCE`.

---

## Meterless — two engines, both load-bearing

The requirement is an engine implemented in a *working feature*, demonstrated
by a passing test. Mentioning one, or adding an unused dependency, does not
count. Both of ours drive behaviour the product would lose without them.

| Engine | Implementation | Called from | Conformance |
|---|---|---|---|
| **Markovian** | `engines/markovian/src/index.ts` | `src/walk.ts`, `clearline/walker.py` | **8/8** |
| **H-MEM** | `engines/hmem/src/index.ts` | `src/cli.ts`, `clearline/memory.py` | **13/13** |

Both written from the `AGENTS.md` specs, not copied from the reference, and
both passed on the first run. `scripts/conformance.sh` fetches the upstream
specs into a gitignored directory rather than vendoring them, so the check
always runs against the current spec.

### Markovian — bounds the control-chain walk

Each hop is one chunk. Every hop makes a real model call judging how **material**
the control relationship is, carrying the chain accumulated so far as a
compressed summary rather than the whole traversal — so prompt cost per hop is
flat with depth. Termination belongs to the engine: `[TASK_COMPLETE]` on a
listed entity or a root, cycle detection on a revisited node, `maxChunks` as
the depth cap.

```
V0004  Baltic Holdings Oy (MEDIUM) -> KHAVERIM (HIGH)   SANCTIONS_HIT, 2 hops
V0007  4-hop chain, all MEDIUM                          ROOT, clean
V0008  Saaremaa <-> Lahti                               CYCLE, terminated
```

**What was unique: we refuse to let the model end the search.** On its first
outing it judged hop 1 immaterial and returned `continue_walk: false`, which
would have stopped one hop short of a listed ultimate parent. That field is now
advisory and deliberately ignored — materiality shapes the *report*, while only
a hit, a cycle, a root or the depth cap stops the *walk*. A missed listed
parent costs far more than one extra hop.

### H-MEM — holds reviewer corrections

```
run 1   BLOCK   Metaalkunde BV is an exact alias of a listed entity
review          alice marks the match wrong -> confidence 1.0 -> 0.8,
                "review" tag, both states in the append-only ledger
run 2   CLEAR   citing the correction and pointing at the ledger
```

Recall happens *before* evidence is weighed, not afterwards as an apology: an
overridden candidate never reaches the resolver, and the trace records which
memory dropped it and who made the call.

**What was unique: the spec gave a better design than we would have
improvised.** Three rules we would likely have got wrong in a compliance
product — *supersede, never delete*, so a contradiction once believed stays in
the record; *provenance required at construction*, so a memory with no source
is rejected rather than stored unauditable; and *preview before execute*, with
guardrails re-checked at execution rather than trusted from the plan.

### Honest accounting

At depth 2–4 the carried state still costs more than re-sending history —
crossover is around depth 6 with a 256-token carryover. Markovian's value at
our depths is bounded state and guaranteed termination, not token economics.
We would rather say that than overclaim a saving.

### Not used

The Meterless runtime (Nightshift). Local inference does not fit alongside
Zetaris on a 15.8 GB machine, so Nemotron is reached through NVIDIA's API. The
sponsor overview scopes Meterless to the agent engines, which is how it is used
here.

---

## NVIDIA Nemotron — reasoning spent in proportion to risk

`clearline/llm.py` holds the tier router, the budget policy and the usage
accounting.

| Tier | Model | Where |
|---|---|---|
| nano | `nemotron-3.5-lightning-30b-a3b`, deliberation off | router, resolver, per-hop materiality |
| super | `nemotron-3.5-lightning-30b-a3b` | the resolver/critic loop |
| ultra | `nemotron-3-ultra-550b-a55b` | contested adjudication only |

```python
budget = BASE[risk_tier]                  # LOW 1x · MED 2x · HIGH 4x
budget *= 1 + 0.5 * critic_rejections     # escalate when the critic pushes back
budget = min(budget, CEILING)             # bounded: runtime discipline
```

### What was unique

**The reasoning toggle was found by measurement, not documentation.** The nano
tier kept exhausting its budget even at a 900-token ceiling. Four mechanisms,
A/B tested:

| mechanism | reasoning tokens | content |
|---|---|---|
| plain | 900 (entire budget) | **empty** |
| `/no_think` system directive | 429 | ok |
| **`chat_template_kwargs: {thinking: false}`** | **0** | ok |

A `/no_think` directive only *halves* deliberation. The chat-template flag
turns it off. It travels in `extra_body` in Python — and **inline in Node**,
whose client has no such parameter and returned `400 Unsupported parameter(s):
extra_body` when wrapped.

**Reasoning tokens come from the provider's own usage accounting**, so "spend
reasoning in proportion to risk" is measured rather than asserted.

### Measured

| | baseline | now |
|---|---|---|
| One vendor, end to end | 1236.3 s, **no decision** | ~110–132 s, correct |
| Router | 102.8 s, 1093 reasoning tokens | **2.9 s, 0** |
| An unresolvable vendor | full pipeline | **2.4 s, 0 tokens** — settled by the router |

The baseline failed because reasoning consumed the entire token budget and the
content came back *empty* — which presents as a JSON parse failure and is not
one. Nemotron returns its chain of thought in a separate `reasoning_content`
field, but those tokens are still billed against `max_tokens`.

---

## Cursor

Not used. Cursor became optional in the 22 October announcement, which
explicitly permits other AI coding tools. Built with **Claude Code**.
