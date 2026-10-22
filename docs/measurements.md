# Measurements

Real numbers from `scripts/trace_summary.py`, taken from the provider's own
usage accounting. Nothing here is estimated. This is the evidence behind two
claims the submission makes: that reasoning is spent in proportion to risk, and
that a run stays inside a predictable budget.

Reproduce any row with:

```bash
python scripts/trace_summary.py logs/<run>.jsonl
```

---

## Baseline — one model for every tier

`nvidia/nemotron-3.5-super-vl-120b-a12b` (120B total / 12B active, vision-language)
on nano, super and ultra. Vendor `V0001`, trace `run-20261022T204315-eec44396`.

| agent | tier | calls | seconds | reasoning tokens | completion | reasoning share |
|---|---|---|---|---|---|---|
| adjudicator | super | 1 | 602.2 | 1600 | 1600 | **100%** |
| critic | super | 2 | 449.7 | 4059 | 4584 | 89% |
| router | nano | 1 | 102.8 | 1093 | 1184 | 92% |
| resolver | super | 1 | 81.5 | 829 | 1008 | 82% |
| **total** | | **5** | **1236.3** | **7581** | | |

**20.6 minutes for a single vendor**, against a 5–10 minute target for an entire
run. The run did not even produce a decision: the adjudicator spent 100% of its
1600-token budget on reasoning, emitted no answer, and the budget escalated.

Three things this makes concrete:

1. **Reasoning dominates.** 82–100% of every completion is chain of thought.
   A token budget sized for the answer is consumed before the answer starts.
2. **Reasoning tokens are billed against `max_tokens`.** Nemotron returns its
   chain of thought in a separate `reasoning_content` field, so the *content*
   comes back empty — which presents as a JSON parse failure and is not one.
3. **Tiering is not a nicety.** The router spent 103 seconds and 1093 reasoning
   tokens establishing that "Zarechny" is not a generic word.

---

## Fix 1 — per-tier token ceilings

nano capped at 900 tokens, with deliberation suppressed on that tier.

| | before | after | change |
|---|---|---|---|
| router latency | 102.8 s | 16.6 s | **6.2× faster** |
| router reasoning tokens | 1093 | 900 (at ceiling) | bounded |

The ceiling alone recovers most of the router cost, and it bounds the worst
case rather than just improving the average — which is what matters for a demo
that has to run on someone else's machine.

---

## Fix 2 — active parameters, not total

Pending. The ladder being measured:

| tier | model | active params |
|---|---|---|
| nano | `nemotron-3.5-lightning-30b-a3b` | 3B |
| super | `nemotron-3.5-lightning-30b-a3b` | 3B |
| ultra | `nemotron-3-ultra-550b-a55b` | 55B, contested cases only |

Active parameters drive throughput, not total size. Dropping the main loop from
12B to 3B active should move the critic furthest, since it is the most-called
agent and the one that truncated — and a faster critic buys more revision
rounds inside the same wall-clock budget, which is what the rubric rewards.

Ultra fires only when the risk tier is HIGH or the critic has rejected twice, so
its cost is bounded to roughly one call per contested run.

---

## How to regenerate

```bash
python scripts/trace_summary.py --all          # every run, one line each
python scripts/trace_summary.py                # most recent, in detail
```
