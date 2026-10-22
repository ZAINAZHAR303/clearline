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

## Fix 2 — the reasoning toggle, found by measurement

The nano tier kept exhausting its budget even at a 900-token ceiling, because a
`/no_think` system directive only *reduces* deliberation. Four mechanisms were
tested against `nemotron-3.5-lightning-30b-a3b` on a small JSON extraction:

| mechanism | reasoning tokens | content |
|---|---|---|
| plain | 900 (entire budget) | **empty** |
| `/no_think` system directive | 429 | ok |
| **`extra_body={"chat_template_kwargs": {"thinking": false}}`** | **0** | ok |
| `extra_body={"reasoning": {"effort": "none"}}` | 0 | ok |

The chat-template flag turns deliberation off outright. It must travel in
`extra_body`; the OpenAI client rejects it as a top-level argument.

## Fix 3 — active parameters, not total

| tier | model | active params |
|---|---|---|
| nano | `nemotron-3.5-lightning-30b-a3b` | 3B, deliberation off |
| super | `nemotron-3.5-lightning-30b-a3b` | 3B |
| ultra | `nemotron-3-ultra-550b-a55b` | 55B, contested cases only |

### Result — vendor `V0001`, trace `run-20261022T211434-c5c78628`

| agent | tier | calls | seconds | reasoning | completion | share |
|---|---|---|---|---|---|---|
| critic | super | 4 | 209.7 | 11906 | 12591 | 95% |
| resolver | super | 3 | 145.7 | 9660 | 10043 | 96% |
| adjudicator | super | 2 | 58.3 | 1802 | 3117 | 58% |
| router | nano | 1 | **2.9** | **0** | 59 | 0% |
| **total** | | **10** | **416.6** | **23368** | | |

| | baseline | now | change |
|---|---|---|---|
| router | 102.8 s | 2.9 s | **35× faster** |
| whole run | 1236.3 s | 416.6 s | **3.0× faster** |
| produced a decision | no | yes | |

Four branches fired in that run: the DQ-driven bar raise, a critic revision
round, a reroute to the control chain, and a confidence escalation.

---

## Day 2 — correctness and cost together

All five demo cases now produce the right decision against the live model.

| vendor | | decision | seconds | reasoning |
|---|---|---|---|---|
| V0001 | Metaalkunde BV | **BLOCK** | 132.0 | 9795 |
| V0002 | South Wealth Resources Ltd. | **BLOCK** | 136.3 | 11032 |
| V0003 | Southwealth Resources Pty Ltd | **CLEAR** | 105.5 | 5727 |
| V0004 | Nordvik Components GmbH | ESCALATE | 181.1 | 13284 |
| V0005 | Global Trading Ltd | ESCALATE | **2.4** | **0** |

V0005 is the shape of the whole argument: an unresolvable name is settled by
the router in 2.4 seconds with zero reasoning tokens, and never reaches the
expensive agents at all.

### V0001, per agent

| agent | tier | calls | seconds | reasoning | share |
|---|---|---|---|---|---|
| adjudicator | super | 3 | 107.4 | 8400 | 94% |
| critic | super | 1 | 21.5 | 1395 | 95% |
| resolver | nano | 1 | 1.6 | 0 | 0% |
| router | nano | 1 | 1.6 | 0 | 0% |
| **total** | | **6** | **132.0** | **9795** | |

| | baseline | Day 2 | change |
|---|---|---|---|
| one vendor, end to end | 1236.3 s | 132.0 s | **9.4× faster** |
| LLM calls | 10 | 6 | |
| correct decision | no | yes | |

The critic fell from 5 calls to 1 once it could see the candidate's alias list
and understood the task. Most of what looked like a cost problem was a
correctness problem: an agent that cannot resolve a question keeps asking.

### What remains

The adjudicator is now the whole cost — 107 of 132 seconds, three calls, 94%
reasoning. Two of those calls are budget escalations before it degrades to a
direct answer. Giving it a realistic starting budget for a long structured
output, rather than discovering the need twice per run, is the next change.

### Earlier: still over budget

6.9 minutes for one vendor, against 5–10 minutes for an entire demo. Where the
remaining time goes:

1. **Repair calls.** 10 LLM calls for what should be 6. Each schema violation
   or truncation re-runs full reasoning. Null and scalar-for-list coercion now
   happens in the `Contract` base, which should remove most of them.
2. **The resolver re-derives what is already computed.** `match_features()`
   produces exact-alias, country-agreement and score deterministically, yet the
   resolver spends 9660 reasoning tokens arriving at them again. Feeding the
   precomputed features in — as the router already does — should cut it
   sharply. This is the next change.
3. **Critic rounds.** Capped at 3; 2 is likely enough once the resolver stops
   proposing weak candidates.

---

## How to regenerate

```bash
python scripts/trace_summary.py --all          # every run, one line each
python scripts/trace_summary.py                # most recent, in detail
```
