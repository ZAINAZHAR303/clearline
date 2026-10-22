# CLEARLINE — Build Plan
### Counterparty exposure adjudication for companies that can't afford a screening desk

**Track 1 — Solving Fragmented Intelligence** · Open Agent Hackathon 2026

> **One-liner (use this verbatim on slide 1 and as line 1 of the README):**
> Clearline helps a procurement officer at a mid-size company decide whether to onboard, block, or escalate a vendor — by resolving that vendor across an internal vendor master and three disagreeing public registries, walking its corporate control chain for indirect exposure, and producing a decision with a complete evidence trail and explicitly named unresolved conflicts.

---

## 0. Hard facts

| | |
|---|---|
| Now | **22 Oct 2026, 08:48 UTC** |
| Registration closes | **22 Oct 23:45 UTC — ~15 hours away. HARD GATE.** |
| Submissions close | **27 Oct 23:45 UTC** |
| Time remaining | **~135 hours** |
| Target submit time | **27 Oct 16:00 UTC** (8-hour buffer — non-negotiable) |
| Pre-existing components to declare | **None.** Repo was empty at 22 Oct 08:48 UTC. Keep it that way; it removes an entire eligibility question. |

---

## 0.5 RULE CHANGES — announced 21–22 Oct, supersede the written guides

**① You must create a team on HackOS even if you are building solo.** Confirmed by the organizers in general chat on 22 Oct: *"even if you're building Solo you still need to build a team."* Ticking "happy to build solo" in the registration form is **not** sufficient. This is an eligibility gate — check it before anything else.

**② Cursor is now OPTIONAL.** Any AI coding tool is permitted — Cursor, Claude Code, Windsurf, Copilot. Cursor remains *recommended* and is what the vibe-coding workshop uses, but the Meterless prompts work identically everywhere. Build wherever you are most productive, and describe whichever tool you used in the submission.

**③ There are NO free Cursor credits.** All references were removed from the guide. If you use Cursor it's on your own plan. Treat the event page's "Best use of Cursor-built product" in-kind award as **unreliable** and do not plan around it. The Nemotron / DGX Spark award is unaffected and remains the largest single prize.

**④ The Meterless requirement is now explicit and binding:**

> *"You must still implement at least one Meterless Engine (H-MEM, Markovian, World Model or Scout Intent) in a working feature of your product. Then demonstrate it with a passing test or a live demo. Mentioning an engine or adding an unused dependency won't count."*

This is the single hardest-edged requirement in the whole event, and it is exactly what §5 of this plan already does. **Implementing an engine and passing its conformance runner is the prescribed evidence.** See §5.3 for the corrected commands.

**⑤ A new sponsor appears: Bright Data.** A `Help Bright Data` channel was listed alongside Zetaris/NVIDIA/Meterless/Cursor when the build window opened. No public details exist yet. Worth ten minutes in Resources and that channel — a brand-new sponsor usually means a new prize with very few entrants. For Clearline it could supply adverse-media or company data. Opportunistic only; do not restructure around it.

**⑥ Competitors are framing projects by "autonomy level" (L1 / L2).** Two public pitches use this taxonomy, which almost certainly came from the 21 Oct onboarding call or the updated challenge statements. **Watch the recording: https://youtu.be/48GKYJfwoB8** — it also presented *"additional challenges with new prizes"* that appear in no written guide. If judges use that vocabulary, state Clearline's levels explicitly: **L2 for resolution and chain-walking** (the agent loops and must pass its own checks), **L1 for the block/clear decision** (the agent recommends, a human approves).

**⑦ `metadata.json`.** Sponsor folders reportedly ask you to describe each sponsor's use "in your README and metadata.json", but no official schema was published. A community draft exists (Apache-2.0, by Marcin Marzec). Adding one costs twenty minutes and is cheap insurance against a judging checklist you can't see.

---

### Why this problem wins Impact (30 pts, and the tie-breaker)

A mid-market company (200–2,000 staff) has no sanctions-screening desk and no $50k/yr Refinitiv or Dow Jones subscription. So it either doesn't screen vendors at all, or screens on legal name only. Name-only screening misses the two things that actually matter:

1. **Aliases and transliterations** — the sanctioned entity is listed under a spelling that isn't in your vendor master.
2. **Indirect exposure through the control chain** — the vendor itself is clean, but its ultimate parent is not. Walking a corporate chain by hand is infeasible, so nobody does it.

A false negative is a legal violation. A false positive freezes a legitimate supplier and stops a production line. Both are expensive, and the decision is made today by a human with twelve browser tabs in about forty minutes.

---

## 1. DO THESE FOUR THINGS BEFORE 11:00 UTC TODAY

Everything else in this plan is worthless if #1 fails.

1. **Register on hackathon.genai.works and confirm you appear in HackOS.** Closes 23:45 UTC today. Pick "happy to build solo" if you're solo. Confirm your track as Track 1 in your team workspace.
2. **Request the Zetaris platform bundle + container registry credentials** in the HackOS Help Zetaris channel if you don't already have them. This is the long-lead item; without the registry login `docker compose pull` fails with `unauthorized` and you are dead in the water.
3. **Start the Zetaris install.** It is ~4 GB of images and 30–45 minutes of first start. Begin it now and do everything below while it runs.
4. **Watch the 21 Oct participant onboarding recording on HackOS.** Additional challenges and prizes were announced there that are not in any of the PDF guides.

### Zetaris install, condensed

```bash
unzip zetaris-platform.zip && cd zetaris-platform
docker login zetarishackathon.azurecr.io     # use the organizers' registry credentials
./preflight.sh                               # fix every failure before continuing
```

Before the **first** `docker compose up`, edit `zetaris-platform/.env`:

- `ZETARIS_ADMIN_EMAIL`, `ZETARIS_ADMIN_PASSWORD` (8+ chars, upper + lower + digit + one of `$ @ ! % * ? &` — other punctuation is rejected), `ZETARIS_ADMIN_ORG`
- Confirm: `ZSPARK_DRIVER_MEM=2g`, `ZSPARK_DRIVER_CORES=2`, `ZSPARK_MASTER_URL=local[2]`, `ZETARIS_API_MAX_HEAP=1g`, `UI_PORT=3000`, `ZETARIS_SEED_TPCH=true`, `COMPOSE_PROFILES` empty

**These cannot be changed after first start.** Editing them later does not reset an existing account; the only cure is `docker compose down -v`, which destroys your data and encryption keys.

```bash
chmod 600 .env && docker compose config --quiet
docker compose pull && docker compose up -d
docker compose ps --all     # postgres/driver/api/ui/ai-datasteward Up; init+bootstrap Exited (0)
./verify.sh                 # all 9 checks must pass
```

Windows: every command above runs in a **WSL 2 terminal** with Docker Desktop's WSL integration on. Docker needs 8 GB RAM / 4 CPUs / 15 GB disk allocated in Docker Desktop settings — your laptop's total RAM is irrelevant, only what Docker is *allowed* to use.

### Power layer — set up BOTH routes today

Mixing settings between the two routes is the single most common setup failure. Pick one as primary, have the other configured and tested as a hot fallback.

```
MODEL_BASE_URL=   # Meterless provider address  OR  https://integrate.api.nvidia.com/v1
MODEL_API_KEY=    # Meterless key               OR  nvapi-... from build.nvidia.com
NEMOTRON_MODEL=   # model id from the SAME route
```

Create your NVIDIA key only at **build.nvidia.com**. Check your free-tier rate limit today so a busy demo doesn't surprise you on the 27th.

**Exit gate for today, hour 3:** `./verify.sh` 9/9 green, `SELECT 1 AS one;` returns a row in the SQL Editor at http://localhost:3000, and your Zetaris API key is in your project `.env`.

---

## 2. The six-day plan

Every day has an **exit gate**. If you miss a gate, apply the cut order in §13 immediately — do not carry slippage forward.

### Day 1 — 22 Oct · Skeleton and first closed loop

The goal today is not features. It is **one end-to-end run that touches every layer**, however crudely. Teams that don't get this on Day 1 never recover.

- [ ] Register. (23:45 UTC gate.)
- [ ] Zetaris up, `verify.sh` 9/9.
- [ ] `git init`, first commit — **after 00:00 UTC today**, which has passed, so you're clear.
- [ ] `.gitignore` containing `.env` **before** you ever create `.env`. Add `.env.example` with placeholder values only.
- [ ] Clone `https://github.com/zetaris/getting-started`. Run the PokéAPI recipe end to end (§7). You need a *working* REST table before you attempt a real one — it is your syntax reference, because the published SQL guide is mid-revision.
- [ ] Open the project in **Cursor**. Point Cursor's agent at the getting-started repo's `AGENTS.md` — it already teaches Lightning SQL rules, one-statement-at-a-time execution, and never printing credentials.
- [ ] `smoke_test.py` passing 3/3 (Zetaris web, Zetaris SQL over REST, Nemotron reply).
- [ ] Generate `data/sample/vendor_master.json` — ~200 synthetic vendors (§7.1).
- [ ] Stand up the data sidecar (§7.2) and register `vendor_master` as a Lightning REST table.
- [ ] Hard-coded walking skeleton: one vendor in → `run_sql` against Zetaris → one Nemotron call → a decision string out. Structured JSONL logging from the very first line of code.

**Exit gate:** `python -m clearline.run --vendor V0042` prints a decision and writes `logs/run-*.jsonl`. It can be dumb. It must be whole.

---

### Day 2 — 23 Oct · The data layer, and the USL that makes it one entity

Today is Zetaris day. A Zetaris executive is on the judging panel; this is where the Sponsor Tech points and a disproportionate share of Technical actually live.

- [ ] Register **OpenSanctions** (bulk file via sidecar — see §7.3, do not depend on a metered API).
- [ ] Register **GLEIF** as a REST table. No key. Verify the `/direct-parent`, `/ultimate-parent`, `/direct-children` endpoints return for a known LEI.
- [ ] Register **SEC EDGAR**. **It 403s without a descriptive `User-Agent` header** — set it in the REST table definition. Classic time-sink; you've been warned.
- [ ] `LOAD USL` defining a single **Counterparty** business entity across all four sources, with declared join paths. This is the centrepiece of your "fragmented intelligence" claim: one SQL query that spans your internal master plus three registries.
- [ ] `RUN DQ` on the columns your agent will rely on — `country`, `tax_id`, `legal_name` nulls, jurisdiction code validity, orphaned references. **Capture the results as data your agent can read at runtime.** (§7.5 — this is the move most teams will miss entirely.)
- [ ] Cache every external response to `data/cache/`. Implement `SAMPLE_MODE=true` to run entirely from cache. Do it now, not on the 26th, because it is also your API-outage insurance for the whole week.
- [ ] Bound every external call with a timeout. Cap retries.

**Exit gate:** one SQL query returns a candidate set joining internal vendors to all three registries. `SAMPLE_MODE=true` runs with your network cable unplugged. Three `RUN DQ` results are persisted and readable by code.

---

### Day 3 — 24 Oct · The agent system and the critic loop

Today is the difference between a pipeline and an agent system.

- [ ] Implement the five agents as contracts (§4), not as prompts. Each returns typed, validated structured output; a parse failure is a retry with the error fed back, not a crash.
- [ ] **Resolver ↔ Conflict Critic revision loop**, max 3 rounds. The Critic must be able to return `DEMAND_EVIDENCE` naming a *specific missing field*, and the Resolver must act on it. This loop is the thing judges are explicitly looking for — make it real and make it visible.
- [ ] Wire **Scout Intent** as the intake router: entity extraction, ambiguity flag, risk tier.
- [ ] Wire **H-MEM** as the match decision ledger with its trust ledger recording provenance for every assertion.
- [ ] **The DQ branch:** when a `RUN DQ` result shows a column is unreliable, the plan changes and the log says so in plain language. ("`country` is 18% null in OpenSanctions for this slice, so I will not rely on jurisdiction mismatch to reject — routing to the control-chain check instead.")
- [ ] Mid-build self-check at **24 Oct 16:00 UTC**. Ask: *if the deadline were tomorrow, what would fail?* Fix that, and only that.

**Exit gate:** a run where the Critic rejects a match, the Resolver revises, and the second attempt is accepted — visible in the log. Plus a run where DQ output changes the route.

---

### Day 4 — 25 Oct · The control-chain walk, escalation, and the trace viewer

- [ ] **Ownership Walker** on **Markovian**: bounded-depth traversal of the GLEIF control chain, each hop a bounded chunk with state carryover, O(1) context per hop. Cap depth at 5 and cycle-detect. Screen every node against sanctions as you go.
- [ ] **Escalation branch:** confidence band → `ESCALATE` with the specific question a human needs to answer.
- [ ] **Human override → H-MEM consolidation.** An override is written as an event, consolidates into long-term memory, and changes the next run's decision. *This is your single best demo moment — protect its schedule.*
- [ ] **Trace viewer.** FastAPI + one static HTML page. Timeline of agent turns, tool calls, DQ results, critic verdicts, reasoning budget spent per call, final decision. Every claim expands to the exact SQL and the row it came from. Three hours of work that scores on Technical, Demo **and** Product & UX simultaneously.
- [ ] Nemotron tiering live (§6) with per-call budget logged.
- [ ] Fallback paths: sanctions source down, GLEIF rate-limited, Nemotron 429. Each degrades with a named caveat in the output rather than crashing.
- [ ] Run the **Meterless conformance suites** and screenshot the passes (§5.3).
- [ ] *Stretch, only if everything above is green:* reimplement one engine (Markovian is simplest) to the spec and pass conformance against your own build.

**Exit gate — FEATURE FREEZE at 25 Oct 23:59 UTC.** After this, no new capability. Only hardening, docs and packaging. Breaking this rule is the most common way good hackathon projects lose.

---

### Day 5 — 26 Oct · Harden, document, record

Resist the urge to build. Today is 25 of the 100 points (Demo 15 + Product & UX 10) that most teams throw away by filming a panicked screencast at 23:00 on the 27th.

- [ ] **Clean-setup test.** Fresh clone into a new directory, follow your own README literally, nothing else. Whatever breaks is your Technical score. Repeat until it runs with zero manual steps.
- [ ] 5 sample inputs in `input_examples/`, their outputs in `output_examples/`. Cover: a clean vendor, an alias match, an indirect-exposure block, an escalation, and a graceful source failure. Judges need to see it work on more than one case.
- [ ] README: the one-liner first, then setup, usage, dependencies, data sources with licences, limitations.
- [ ] `SPONSOR_TECH.md` — Zetaris integration, Meterless engines (with conformance screenshots), how Cursor was used during development, where Nemotron contributes, and **what was unique about your use of each**. That last clause is a literal scoring field; answer it explicitly.
- [ ] Deck (§11) and **demo video, 1–4 min** (§10). Record audio separately if your mic is poor; a clear voiceover carries a mediocre screen capture, never the reverse.
- [ ] Secret sweep: `git log -p | grep -iE 'nvapi-|api[_-]?key|bearer|password'`. Check the deck images and the video for an exposed key or a visible `.env`.
- [ ] Repo weight: no raw archives, no checkpoints, no caches beyond what the demo needs.
- [ ] Time a cold run end to end. Target 5–10 minutes. If it's longer, cut sample size, not loops.

**Exit gate:** a stranger could clone, run, and understand it. Video and deck exported and uploaded somewhere stable.

---

### Day 6 — 27 Oct · Submit early

- [ ] 09:00 UTC — final clean-setup run on a different machine or a fresh container if you can.
- [ ] 12:00 UTC — final validation pass against the pre-submission checklist (§12).
- [ ] **16:00 UTC — SUBMIT.** Eight hours of buffer. Submissions close 23:45 UTC and the deadline does not move for time zones.
- [ ] Declare pre-existing components: **none** (verify your first commit timestamp is after 22 Oct 00:00 UTC).
- [ ] After submitting you may keep refining and resubmit up to the deadline — but your team composition locks on first submission, so if you're joining anyone, settle it first.
- [ ] Monitor HackOS announcements through to 6 Nov in case judges request clarification.

---

## 3. System shape

```
                        ┌─────────────────────────────┐
   vendor query  ──────▶│  1. INTAKE & RISK ROUTER    │  Scout Intent
                        │  entities · ambiguity flag  │
                        │  risk tier → budget         │
                        └──────────┬──────────────────┘
                                   │ signed execution contract
                                   ▼
                        ┌─────────────────────────────┐
                        │  2. RESOLVER                │◀──┐  Nemotron Super
                        │  candidates + score +       │   │  + Nano for
                        │  the features that drove it │   │  normalisation
                        └──────────┬──────────────────┘   │
                                   ▼                      │ DEMAND_EVIDENCE
                        ┌─────────────────────────────┐   │ (names the
                        │  3. CONFLICT CRITIC         │───┘  missing field)
                        │  tries to BREAK the match   │      max 3 rounds
                        └──────────┬──────────────────┘
                     ACCEPT        │         reroute: "not more name
                                   ▼          evidence — walk the chain"
                        ┌─────────────────────────────┐
                        │  4. OWNERSHIP WALKER        │  Markovian
                        │  control chain, depth ≤ 5,  │  bounded hops,
                        │  screen every node          │  state carryover
                        └──────────┬──────────────────┘
                                   │ each new node → back to Critic
                                   ▼
                        ┌─────────────────────────────┐
                        │  5. ADJUDICATOR             │  Nemotron Ultra
                        │  CLEAR / BLOCK / ESCALATE   │  (contested only)
                        │  + evidence + open conflicts│
                        └──────────┬──────────────────┘
                                   ▼
              human override ──▶ World Model event ──▶ H-MEM consolidation
                                   └──▶ changes the NEXT run
```

### The loops, stated explicitly (put this slide in the deck)

The organizers' guidance asks for at least three of these. You have seven.

1. Resolver ↔ Critic revision loop, bounded at 3 rounds
2. Critic → Router re-routing (changes *which* evidence is sought, not just more of it)
3. Walker → Critic (every discovered chain node is critiqued before it counts)
4. DQ-driven replan (data-quality result changes the plan at runtime)
5. Confidence-band escalation to a human, with a specific question
6. Human override → memory consolidation → different future decisions
7. Degradation branch when a source or the model provider fails

---

## 4. Agent contracts

Write these as typed schemas (Pydantic) before writing any prompt. Validate every output. A parse failure retries with the validation error appended to the prompt; it never throws.

### 1. Intake & Risk Router — *Scout Intent*
- **In:** `{vendor_id | free_text, requested_action}`
- **Out:** `{entities[], signals[], ambiguity: {is_ambiguous, reason}, risk_tier: LOW|MED|HIGH, evidence_bar: float, reasoning_budget: int, execution_contract: {allowed_tools[], max_rounds, signature}}`
- **Must:** refuse rather than guess when input is insufficient — return `ambiguity.is_ambiguous=true` with the question to ask. Refusing well is worth more than guessing well.
- **Model:** Nano

### 2. Resolver
- **In:** `{entities[], evidence_bar, critic_feedback?: {missing_field, reason}}`
- **Out:** `{candidates: [{source, source_id, matched_name, score, features_used[], provenance: {sql, row_ref}}], hypothesis, confidence}`
- **Must:** name the features that drove the score (exact tax_id, normalised-token overlap, country agreement, LEI corroboration). A score without features is unauditable and the Critic should reject it.
- **Model:** Super, with Nano for bulk alias/country normalisation

### 3. Conflict Critic
- **In:** `{hypothesis, candidates[], dq_report}`
- **Out:** `{verdict: ACCEPT | REJECT | DEMAND_EVIDENCE | REROUTE, reasons[], missing_field?, caveats[]}`
- **Must:** be genuinely adversarial. Specifically test for: generic-name collisions ("Global Trading Ltd" matches hundreds), jurisdiction contradiction, date incompatibility, single-source assertions, and any column the DQ report has flagged unreliable.
- **Model:** Super. Use a different system prompt and a higher temperature than the Resolver — a critic that shares the Resolver's framing rubber-stamps it.

### 4. Ownership Walker — *Markovian*
- **In:** `{accepted_lei, depth_budget: 5, visited[]}`
- **Out:** `{chain: [{lei, name, relation: DIRECT_PARENT|ULTIMATE_PARENT|DIRECT_CHILD, sanctions_hit?}], terminated_because: DEPTH|CYCLE|ROOT|RATE_LIMIT}`
- **Must:** cycle-detect, cap depth, carry only a compact state summary between hops. Report *why* it stopped — "terminated at depth 5, chain may continue" is honest and scores better than silence.
- **Model:** Nano per hop (cheap, high volume), Super for the final chain interpretation

### 5. Adjudicator
- **In:** `{hypothesis, critic_history[], chain, dq_report, memory_hits[]}`
- **Out:** `{decision: CLEAR|BLOCK|ESCALATE, confidence, rationale, evidence: [{claim, source, sql, row_ref}], unresolved_conflicts[], caveats[], human_question?}`
- **Must:** every claim in `rationale` maps to an entry in `evidence`. Anything unsupported goes in `unresolved_conflicts`, never into the rationale. This constraint is the whole product.
- **Model:** Ultra when contested (HIGH risk tier, or ≥2 critic rejections, or confidence in the escalation band); otherwise Super at max reasoning budget

---

## 5. Where each Meterless engine plugs in

This is your Innovation and Sponsor Tech story, and it is the part almost no other team will do properly. The four engines map one-to-one onto the behaviours the rubric calls "strong" — so using them as the substrate is not integration theatre, it *is* the architecture.

### 5.1 Placement

| Engine | Role in Clearline | Why it's load-bearing, not decoration |
|---|---|---|
| **Scout Intent** | Agent 1. Intent and entity extraction, ambiguity flagging *before* the model runs, risk tiering, signed execution contracts gating every state write | Gives you the refuse-rather-than-hallucinate behaviour and the risk signal that drives Nemotron budget allocation |
| **H-MEM** | The match decision ledger. Short-term = this run's hypotheses · working = accepted matches for this vendor · long-term = consolidated adjudications and human overrides, with the **trust ledger** recording who asserted what, from where | This is what makes the human override change future runs. Three-tier memory plus provenance is exactly what the rubric means by "shared memory" |
| **World Model** | Event-sourced counterparty graph. Every resolution, rejection, hop discovered and override is an event; the graph is derived state | Gives you replay and a timeline for free — which *is* the trace viewer. Judges asked for traces in five separate places |
| **Markovian** | Agent 4's chain walk, and the batch screening pass. Bounded chunks with safe carryover, O(1) context per hop | Your runtime-discipline answer. A 40-node chain cannot blow context, and cost per hop is flat |

### 5.2 Integration decision — make it on Day 1 and don't revisit

The engine references are **TypeScript** (`npx tsx`). Your agent should be **Python** (best Zetaris + OpenAI-SDK support).

**Do:** run the TS engine references as a small local **Node sidecar** behind a thin HTTP surface, called from Python. Decided on Day 1, working by Day 1 evening.

**Don't:** start the week by porting four specs to Python. That is a two-day detour that produces no demo.

The Day 4 *stretch* is to reimplement one engine (Markovian) in Python and pass its conformance suite against your own build. Nice if it lands; never a dependency.

### 5.3 Conformance — this is now a REQUIREMENT, not a flourish

Rule change ④ makes implementing one engine mandatory, demonstrated by a passing test or live demo. The conformance runners each take an env var pointing at **your own implementation's `index.ts`** — so the implementation must be a TypeScript module, and `node v24.16` is already installed on your machine.

```bash
HMEM_IMPL=/abs/path/to/your/index.ts         npx tsx conformance/runner.ts
MARKOVIAN_IMPL=/abs/path/to/your/index.ts    npx tsx conformance/runner.ts
WORLD_MODEL_IMPL=/abs/path/to/your/index.ts  npx tsx conformance/runner.ts
cd engines/scout-intent && npm run evals     # 32 examples; injection targets 0.95 precision / 0.90 recall
```

Each engine's spec is its `AGENTS.md`, with a runnable reference beside it in `reference/`.

**Which engine to implement yourself — decide Day 1:**

| Engine | Effort | Verdict |
|---|---|---|
| **Markovian** | Lowest | ✅ **Do this one first.** Bounded chunks with carryover, must resume from its last marker after a crash. It maps straight onto the ownership-chain walk, and `reference/scripts/measured-run.ts` produces a *measurement* of flat per-step context — a ready-made demo artifact |
| **H-MEM** | Highest | Second, if time allows. Working/episodic/semantic tiers as grep-able files, mining, conflict resolution, trust ledger, preview-first sleep cycle. Carries your best demo moment (override → memory → changed decision) |
| **World Model** | Medium | Stable IDs + idempotent ingest, checked by `reference/scripts/idempotency-check.ts --mutate` |
| **Scout Intent** | Medium | Eval-based, not conformance. The injection-resistance targets are a genuine differentiator if you have spare time |

**Minimum to satisfy the rule: Markovian implemented, conformance passing, visibly driving the chain walk.** Use the stock references for the other three — that still reads as deep integration, and the one you implemented is your evidence. Screenshot every passing run into the deck.

---

## 6. Nemotron tiering — this is your DGX Spark pitch

The Nemotron in-kind prize (DGX Spark Founder's Edition, ~$4,699) is the largest single award in the event and is decided on Nemotron use alone. It is a second, independent shot at winning, and a solo builder can take it.

One model call for everything forfeits it. Tier deliberately:

| Tier | Where | Why |
|---|---|---|
| **Nano** | Alias and country-code normalisation, field extraction from EDGAR and sanctions blobs, per-hop chain screening | Hundreds of calls across 200 vendors. Reasoning off for throughput. Nano exists for exactly this |
| **Super** | Resolver and Conflict Critic loop, final chain interpretation | Needs real tool calling (`run_sql`) and multi-step reasoning. Your workhorse |
| **Ultra** | Adjudicator, contested cases only | Reserve the expensive reasoning for decisions that actually carry risk |

### ⚠️ Route decision: use NVIDIA's remote API, not local Nightshift

The Meterless Power route runs **Nightshift locally** — an OpenAI-compatible server on `http://127.0.0.1:8088/v1`, bearer token read from `<stateDir>/proxy-token`, model IDs that are routing modes like `meterless/auto`, and a recommended **180 s timeout** because model loads take minutes. (A 401/403 from `GET /v1/models` means unauthorized, not offline. The placeholder `rt-local` is rejected.)

**On a 15.8 GB laptop already giving 9 GB to WSL for Zetaris, local inference will not fit.** So:

```
MODEL_BASE_URL=https://integrate.api.nvidia.com/v1
MODEL_API_KEY=nvapi-...
NEMOTRON_MODEL=<id copied from the build.nvidia.com model page>
```

This costs you nothing in sponsor scoring: the binding Meterless requirement is to **implement an engine** (§5.3), which is local TypeScript and weighs almost nothing. Power and Meterless are separate obligations — satisfy Meterless through the engine, and Nemotron through NVIDIA's free tier. Check your free-tier rate limit before demo day.

### The thing that wins it: spend reasoning proportional to stakes

The Nemotron 3 family was post-trained for multi-step tool use with **granular reasoning-budget control**. So don't use a fixed budget — drive it from Scout Intent's risk tier and the Critic's rejection count:

```python
budget = BASE[risk_tier]                    # LOW 1x · MED 2x · HIGH 4x
budget *= 1 + 0.5 * critic_rejections       # escalate when the critic pushes back
budget = min(budget, CEILING)               # bounded: runtime discipline
```

Log the budget spent on every call. Then **put the histogram in the demo**: cheap vendors cost almost nothing, the one contested vendor consumed most of the reasoning. That single chart is a Reasoning Architecture argument, a cost argument, and an engineering-maturity argument in one image — and it is the concrete, measurable claim that wins a "best use of Nemotron" award instead of merely qualifying for it.

Also do a one-line ablation: the same case at fixed-low budget gets the decision wrong; at risk-scaled budget it gets it right. Evidence beats assertion.

---

## 7. The Zetaris data layer

### ⚠️ Verify syntax against working examples, not the published guide

The Zetaris knowledge-base SQL guide is explicitly **in revision** and may be incomplete. Confirmed statements: `CREATE LIGHTNING DATABASE`, `CREATE LIGHTNING REST TABLE`, `CREATE LIGHTNING FILESTORE TABLE`, `CREATE SCHEMASTORE CONTAINER`, `CREATE SCHEMASTORE VIEW`, `LOAD USL`, `RUN DQ <column> TABLE <table>`, `REGISTER OR REPLACE JDBC DATASOURCE`, `CREATE NAMESPACE`, `SHOW LIGHTNING DATABASES`.

**Copy exact column and option syntax from these two working files** rather than from any doc — including this one:

- `open_data/rest_apis/sql/non_rate_limited/02_pokeapi_create.sql` — your REST table template
- `open_data/usl/` — the EDGAR+SIC build rebuilt with USL; your USL template

Your own install serves the authoritative API reference at `http://localhost:8888/redoc/index.html`. Run **one statement at a time** and wait for each to finish.

### 7.1 Source 1 — internal vendor master (synthetic, ~200 rows)

This is the "internal data an organisation runs on" that Zetaris exists to serve, and it is why this project beats an all-public-data mashup.

Fields: `vendor_id, legal_name, trading_name, tax_id, country, address, bank_country, onboarded_date, annual_spend_usd, category`

Deliberately plant, and document in `data/README.md`:
- Suffix variation — `Ltd` / `Limited` / `LLC` / `L.L.C.`
- Transliteration and spelling drift in 4–5 names
- Missing `tax_id` on ~15% of rows (this is what makes your DQ story real)
- Two vendor_ids that are the same real entity
- 3–4 vendors with genuine sanctions or control-chain exposure
- 2 generic-name traps — "Global Trading Ltd" — that *should* be rejected as unresolvable

Generate it with a seeded script so it's reproducible, and commit the script alongside the data.

### 7.2 The local-file problem — and the clean fix

**Zetaris cannot read a file sitting on your laptop.** The official guidance is to put it in storage Zetaris can reach, such as S3. You do not need an AWS account for that.

Serve your sample data from a container on the same Docker network and register it as a REST table — reusing the PokéAPI pattern you already proved on Day 1:

```bash
docker network ls | grep zetaris          # find the compose network name
docker run -d --name clearline-data \
  --network <zetaris_network> \
  -v "/d/Github Repos/genai hackathon/data/sample:/usr/share/nginx/html:ro" \
  nginx:alpine
```

Zetaris now reaches your files at `http://clearline-data/vendor_master.json`. No S3, no credentials, no edits to the Zetaris compose file, and it works offline. Serve **JSON**, not CSV, so the REST table path applies.

### 7.3 Source 2 — OpenSanctions

**Use the free bulk dataset, not the hosted API.** The hosted API may require a key; the bulk files at `data.opensanctions.org` do not. Take one small dataset (for example the OFAC SDN list), drop it in `data/sample/`, and serve it through the same sidecar.

This is strictly better for you: no key, no rate limit, no outage risk during judging, and your `SAMPLE_MODE` story comes free. Record the dataset name, snapshot date and licence in `data/README.md`.

Fields that matter: `caption`, `aliases`, `country`, `topics` (sanction / PEP / crime), `datasets`.

### 7.4 Sources 3 and 4 — GLEIF and EDGAR

**GLEIF** (`api.gleif.org/api/v1`) — fully open, no key. The crown jewel:

- `/lei-records?filter[entity.legalName]=...` — name search
- `/lei-records/{lei}/direct-parent`
- `/lei-records/{lei}/ultimate-parent`
- `/lei-records/{lei}/direct-children`

Those three relationship endpoints are the control chain, and walking them is the thing no human reviewer does by hand. Rate limits apply — **cache aggressively** from Day 2.

**SEC EDGAR** — company tickers/CIK, submissions JSON, SIC code. Corroborates legal name, jurisdiction of incorporation and industry. **Set a descriptive `User-Agent` header in the REST table definition or every request 403s.** This gotcha has eaten entire afternoons.

### 7.5 USL and DQ — the two moves that separate you from the field

**`LOAD USL`** defining one **Counterparty** entity across all four sources with declared join paths. Then your agent asks one semantic question and Zetaris federates it. That is literally the Track 1 challenge statement, satisfied by the sponsor's own flagship feature, in the sponsor judge's home territory.

**`RUN DQ`** is the move nearly everyone will miss. Don't run data-quality checks as a setup step and forget them. **Persist the results and let the agent read them at runtime, then change its plan because of them.** Target: `tax_id` null rate, `country` validity, orphaned references, duplicate `legal_name`.

Then the agent can log, in plain language:

> `country` is 18% null in this sanctions slice, so jurisdiction mismatch is not a safe basis for rejection here — routing to the control-chain check instead. Confidence bar raised to 0.82.

An agent reasoning about the *quality* of its data rather than just its content is visible in a trace, impossible to fake, and almost nobody will do it. This single behaviour is worth more to your Technical and Innovation scores than two extra agents.

---

## 8. Two accuracy guardrails — do not skip these

**8.1 GLEIF gives you control and consolidation relationships, NOT ownership percentages.** Do not write "61% indirect ownership" anywhere unless a source actually supplies a percentage. GLEIF Level 2 reports direct and ultimate *accounting-consolidating parent* relationships. Say what you can defend:

> BLOCK — indirect exposure via ultimate parent **Holdco X** (LEI `...`), which appears on the OFAC SDN list under the alias "…". Chain depth 3. Relationship type: ultimate accounting-consolidating parent. **This is a control relationship, not a measured ownership percentage** — OFAC's 50% rule requires ownership data this source does not provide, so this is flagged for human confirmation.

That is more impressive than the overclaim, not less. It shows you know the domain, and a judge who knows sanctions screening will notice immediately. Overclaiming is explicitly on the organizers' list of things judges discount.

**8.2 Frame the product as decision support, not decision authority.** Output is "recommend BLOCK, pending human confirmation," with a named reviewer question. Also on the discount list: "unsupported claims of value."

---

## 9. Repo layout

```
genai hackathon/
├── README.md                  # one-liner FIRST, then setup/usage/deps/limitations
├── SPONSOR_TECH.md            # Zetaris · Meterless (+conformance) · Cursor · NVIDIA
├── BUILD-PLAN.md              # this file
├── .env.example               # placeholders ONLY
├── .gitignore                 # .env, data/cache/, logs/
├── requirements.txt
├── smoke_test.py
├── data/
│   ├── README.md              # every source: URL, licence, snapshot date, subset, limits
│   ├── sample/                # vendor_master.json + sanctions subset (served via sidecar)
│   └── cache/                 # gitignored; SAMPLE_MODE reads here
├── sql/
│   ├── 01_databases.sql
│   ├── 02_rest_tables.sql
│   ├── 03_usl_counterparty.sql
│   └── 04_dq_rules.sql
├── engines/                   # Meterless Node sidecar (degit'd references)
├── clearline/
│   ├── llm.py                 # Nemotron: tier router + reasoning-budget policy
│   ├── zetaris.py             # run_sql() + dq_report()
│   ├── memory.py              # H-MEM + World Model client
│   ├── agents/                # router · resolver · critic · walker · adjudicator
│   ├── orchestrator.py        # the loops, branching, escalation, retries
│   ├── trace.py               # structured JSONL from line one
│   └── run.py                 # CLI entry
├── viewer/                    # FastAPI + one static page
├── input_examples/            # 5 cases
└── output_examples/           # their outputs, committed
```

---

## 10. Demo script — 110 seconds

Structure it so that if a judge watches only the first 30 seconds, they still understand the value. Show the product working before you explain how it works.

| Time | Beat |
|---|---|
| **0:00–0:12** | **The problem, concretely.** "A compliance officer at a 600-person manufacturer screens vendors by name in a spreadsheet. The tools that do this properly cost fifty thousand a year. So indirect exposure through a parent company is never checked — because walking a corporate chain by hand is impossible." |
| **0:12–0:22** | One vendor goes in. "Acme Trading Co, $2.1M annual spend, up for renewal." |
| **0:22–0:40** | **The agents work, on screen, in the trace viewer.** Router tiers it HIGH. Resolver proposes a match. **Critic rejects it** — "single-source, generic name" — and demands the tax ID. Resolver revises. Narrate this: *"the critic just rejected its own system's match."* |
| **0:40–0:52** | **The DQ moment.** Zetaris `RUN DQ` shows `country` 18% null; the agent says so and reroutes to the control chain. *"It's reasoning about the quality of its data, not just the data."* |
| **0:52–1:08** | **The chain walk.** Depth 3 through GLEIF to an ultimate parent that hits the sanctions list under an alias. **BLOCK**, with the evidence table — and one row expanded to show the exact SQL and the source row behind the claim. |
| **1:08–1:22** | **The override.** A human marks one match as wrong. Re-run the same vendor: the decision changes, because the correction consolidated into long-term memory. *"It doesn't just log the correction. It learns it."* |
| **1:22–1:35** | The reasoning-budget histogram. "Cheap vendors cost almost nothing. The contested one got the deep reasoning. We spend Nemotron's reasoning in proportion to risk." |
| **1:35–1:50** | 15 seconds on the stack: Zetaris USL federating four sources, Meterless H-MEM/World Model/Markovian/Scout Intent as the substrate with conformance suites passing, Nemotron tiered Nano→Super→Ultra, built in Cursor. |

Record audio separately if your mic is weak. Hard cut anything that drifts past 2:00 — the ceiling is 4 minutes but a tight 110 seconds reads as confidence and a rambling 3:50 reads as padding.

---

## 11. Deck — 10 slides

1. The one-liner, verbatim
2. The user and the decision (the 40-minutes-and-twelve-tabs status quo)
3. Why it's hard: four sources, no shared key, and they disagree — with one concrete example of the same entity under four different identifiers
4. Architecture diagram (§3)
5. **The loops slide** (§3) — name all seven
6. Zetaris: USL federating four sources + the DQ-driven replan, with real SQL on the slide
7. Meterless: the four engines as substrate + **conformance screenshots**
8. Nemotron: the tiering table + the reasoning-budget histogram + the ablation
9. Evidence and limitations: what it proves, what it doesn't, the control-vs-ownership caveat
10. What's next, and what we'd need for production

---

## 12. Pre-submission checklist

- [ ] Demo video 1–4 min, uploaded and playable from a fresh browser session
- [ ] Deck complete
- [ ] GitHub repo public; README covers setup, usage, dependencies
- [ ] Clean clone → run works with **zero** manual steps
- [ ] `SAMPLE_MODE=true` runs with no network
- [ ] 5 sample inputs + their committed outputs
- [ ] Logs/traces show how the system reached its output
- [ ] Sponsor explanation covers Zetaris, Meterless, Cursor, NVIDIA — **including what was unique about each**
- [ ] Pre-existing components declared: **none**
- [ ] No secrets in code, README, notebooks, logs, deck images or video
- [ ] `.env.example` placeholders only
- [ ] Cold run completes in 5–10 minutes
- [ ] Track confirmed as Track 1 in the team workspace
- [ ] **Team created on HackOS** (required even when solo — see §0.5 ①)
- [ ] **At least one Meterless engine implemented, with its conformance runner passing** (§0.5 ④, §5.3) — screenshot in the deck
- [ ] `metadata.json` at the repo root describing each sponsor's use (§0.5 ⑦)
- [ ] Autonomy levels stated explicitly: L2 resolution/chain-walk, L1 decision (§0.5 ⑥)
- [ ] **Submitted by 27 Oct 16:00 UTC**

---

## 13. Cut order — decide now, not at 22:00 on the 27th

Cut from the top the moment you miss a daily exit gate:

1. Batch 200-vendor screening → single-vendor mode only
2. Ultra tier → Super at maximum reasoning budget
3. EDGAR → three sources instead of four
4. Python engine reimplementation → TS sidecar only (this was always a stretch)
5. Trace viewer polish → structured JSONL plus a static HTML render

### Never cut — these ARE the submission

- The Resolver ↔ Critic revision loop
- The control-chain walk
- The DQ-driven replan
- The human override → memory → changed decision loop
- A clean-setup run with no manual steps
- `SAMPLE_MODE`
- The demo video

---

## 14. Risk register

| Risk | Mitigation | Day |
|---|---|---|
| Zetaris bundle/credentials don't arrive | Ask in Help Zetaris **today**; escalate to `hackathons@genai.works` | 1 |
| Docker can't get 8 GB / 15 GB | AWS VM path, ~$1 per 8-hour session | 1 |
| REST table syntax fights back | Clone the PokéAPI file; one statement at a time; Help Zetaris channel; `redoc` on :8888 | 1–2 |
| EDGAR 403 | Descriptive `User-Agent` in the table definition | 2 |
| GLEIF rate limit mid-demo | Cache everything from Day 2; `SAMPLE_MODE` | 2 |
| Nemotron 429 / credit exhausted | Both routes configured; swap three env vars | 1 |
| TS/Python boundary eats a day | Sidecar decided Day 1; reimplementation is stretch only | 1 |
| Feature creep past the freeze | 25 Oct 23:59 freeze is absolute; cut order above | 4 |
| Submitting late | 16:00 UTC target, 8-hour buffer | 6 |

---

## 15. The one-paragraph pitch to keep rereading

Most submissions this week will be a chatbot over one `SELECT`, with Zetaris as a database, Meterless as a model proxy, and Nemotron as one API call. Clearline inverts all three: **Zetaris is the provenance and governance layer** whose data-quality output changes the agent's plan at runtime; **Meterless's four engines are the actual substrate** — memory with a trust ledger, event-sourced world state, bounded reasoning, intent gating — with conformance suites passing as proof; and **Nemotron's reasoning budget is spent in measured proportion to risk**. The problem is real, the user is specific, every claim traces to a source row, and a human correction changes what the system decides next time. Build that, show it in 110 seconds, and submit eight hours early.
