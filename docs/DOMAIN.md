# The problem Clearline solves — a primer

Written for someone with no background in procurement or sanctions compliance.
Nothing here assumes prior knowledge. Sources at the end; the claims that rest
on industry marketing rather than regulators are marked as such.

---

## 1. What a vendor is

A **vendor** (also *supplier*, *counterparty*, *third party*) is any company
your company pays for goods or services. A factory buys steel, cleaning,
logistics, IT support, legal advice. Each of those is a vendor.

A mid-size manufacturer typically has **several hundred to a few thousand**
vendors. The list of them lives in the finance or ERP system and is called the
**vendor master** — one row per vendor, with its legal name, tax ID, country,
bank details, and how much you spend with it a year.

`data/sample/vendor_master.json` in this repo is a synthetic version of exactly
that file.

**Onboarding** is the process of checking a new vendor before you start paying
them. **Due diligence** is the checking part: are they a real company, are they
financially sound, and — the part this project is about — *are we legally
allowed to do business with them?*

## 2. What sanctions screening is

Governments publish lists of companies and people that businesses are
prohibited from dealing with. The best-known is the US Treasury's **SDN list**
(Specially Designated Nationals), published by **OFAC** (Office of Foreign
Assets Control).

If a company on that list is your vendor, paying them is a **legal violation**,
not a policy breach. Penalties are per-violation and run into six and seven
figures. Ignorance is not a defence — OFAC operates on *strict liability*, so
"we didn't know" does not help you.

So every vendor has to be checked against those lists. That check is called
**sanctions screening**, and it is not optional for any company doing
international business.

## 3. Why it is harder than looking up a name

This is the part that matters, and it is where Clearline lives.

### Failure mode 1 — the name on the list is not the name you have

Designated entities change names, trade under different names, and appear on
lists under transliterations. Screening the one name in your vendor master
finds nothing.

> **This is not hypothetical.** On 9 October 2026 — two weeks before this
> hackathon — OFAC settled with **Pegasus Worldwide Logistics**, a freight
> forwarder, for **$175,015**.
>
> A sanctioned Chinese supplier had **changed its name after being
> designated**. Pegasus screened only the new name against the SDN list and
> found nothing. The phone number and email address were unchanged throughout
> the shipping documents. OFAC's finding:
>
> *"Screening the other identifiers, including through a basic internet search,
> would have yielded a positive match."*
>
> OFAC cited reckless disregard for screening controls and failure to
> investigate red flags.

That is Clearline's `V0001` case in real life. **Metaalkunde BV** reads as an
ordinary Belgian engineering supplier; it is an exact alias of a sanctioned
entity whose listed name looks nothing like it. Screening on the vendor's own
legal name finds nothing. Screening against the *alias list* finds it.

This is why `watchlist_alias` is a first-class table in our semantic layer
rather than a column: the alias, not the caption, is what identifies a
counterparty.

### Failure mode 2 — the vendor is clean but its owner is not

OFAC's **50 Percent Rule**: an entity that is owned 50% or more, *in aggregate,
directly or indirectly*, by blocked persons is **itself blocked** — even though
its own name appears nowhere on any list.

Two consequences that make this hard:

- **Aggregate.** Two blocked parties owning 30% and 25% add up to 55%. Blocked.
- **Indirect.** Ownership flows down chains. A blocked owner's 50% stake makes
  the intermediate company blocked, and *that* company's stake can block the
  one below it. Law firms call this the "light switch" approach — the full
  holding of a blocked intermediate counts, so exposure propagates downward
  through structures.

So checking the vendor's name is not enough. You have to walk **up its
corporate ownership chain** and check every parent. By hand, across registries,
for a thousand vendors, that is infeasible — which is why in practice it mostly
does not happen.

That is Clearline's `V0004`: *Nordvik Components GmbH* is clean on its own
name. Only walking the chain two hops finds a listed ultimate parent.

> **A 2026 development worth knowing for the deck.** OFAC guidance of 31 March
> 2026 states that the 50% Rule is **"a floor, not a ceiling"** — firms are
> expected to look past formal ownership to the practical and economic reality
> of control. That is precisely why Clearline assesses the *materiality* of
> each control relationship rather than treating the chain as a yes/no lookup.

### Failure mode 3 — crying wolf

The opposite error. Name-matching is fuzzy by necessity, so screening tools
produce enormous numbers of **false positives**: alerts where the vendor merely
resembles a listed entity.

Industry sources commonly cite false-positive rates of **90–95%**, with 30–60
minutes of analyst time per alert. *(Caveat: these figures come from vendors
selling screening software, not regulators or peer-reviewed work. Treat them as
indicative. We have not found an authoritative published figure.)*

The consequence is **alert fatigue** — analysts conditioned to expect that
alerts are noise start dismissing them, and eventually dismiss a real one.

That is Clearline's `V0003`: *Southwealth Resources Pty Ltd* in Australia
fuzzily resembles *South Wealth Resources Company* in Iraq. Different
jurisdiction, no exact alias. It must **CLEAR**, and the system has to say why.

**A false positive is not a harmless error.** Blocking a legitimate supplier
stops a production line and damages a commercial relationship. The two error
types have different costs, and a useful tool has to be judged on both.

## 4. Who actually does this work

At a large bank, a dedicated financial-crime compliance team with a
six-figure-per-year screening platform.

At a **200–2,000 person manufacturer** — Clearline's user — there is no such
team. A procurement or finance person checks vendors as one task among many,
usually by typing names into a free search box. They do not walk ownership
chains, because doing so by hand is impossible.

That gap is the opportunity: the companies most likely to be caught by failure
modes 1 and 2 are precisely the ones with no tooling to catch them.

## 5. Where Clearline sits

| The real problem | What Clearline does |
|---|---|
| The listed name isn't the name you have | Resolves against the full alias list, exact match beats fuzzy |
| Vendor clean, owner isn't | Walks the control chain and checks every parent |
| 90%+ alerts are noise | A critic agent must break the match before it is allowed to stand |
| "Why did you block them?" | Every claim traces to a source row, with the watchlist snapshot date |
| The reviewer was right and the system was wrong | A correction persists and changes the next decision |

### The honest boundary

Clearline is **decision support, not decision authority**. It recommends and
names what a human must confirm. It also **never asserts an ownership
percentage**, because the open sources publish *control and consolidation*
relationships, not percentages — and the 50% Rule needs ownership data they do
not provide. Claiming otherwise would be the kind of overclaim that makes a
compliance tool dangerous.

---

## Sources

**Primary — start here**

- OFAC FAQ 401, the 50 Percent Rule and indirect ownership — <https://ofac.treasury.gov/faqs/401>
- OFAC sanctions programmes and the SDN list — <https://ofac.treasury.gov>
- OpenSanctions, the aggregated dataset this project uses — <https://www.opensanctions.org>

**The enforcement action that mirrors this project**

- Sidley, *OFAC's Pegasus Settlement: Lessons for Logistics Providers on Screening* (15 Oct 2026) — <https://whitecollarwatch.sidley.com/2026/10/15/ofacs-pegasus-settlement-lessons-for-logistics-providers-on-screening-and-subpoena-responses/>
- Export Compliance Daily, *OFAC Fines Forwarder $175,000 for Importing From Sanctioned Chinese Company* — <https://exportcompliancedaily.com/article/2026/10/13/ofac-fines-forwarder-175000-for-importing-from-sanctioned-chinese-company-2610090044>

**The 50 Percent Rule explained by practitioners**

- Cleary Gottlieb, *OFAC Issues New Guidance on Entities Owned by Blocked Persons* — <https://www.clearygottlieb.com/news-and-insights/publication-listing/ofac-issues-new-guidance-on-entities-owned-by-blocked-persons26>
- Covington, *OFAC Issues New Guidance Regarding Entities Owned by Designated Parties* — <https://cov.com/-/media/files/corporate/publications/2014/08/ofac_issues_new_guidance_regarding_entities_owned_by_one_or_more_designated_parties.pdf>
- Mondaq, *Old Rule, New Risk: OFAC's 50% Rule and the Growing Importance of Control* (2026) — <https://www.mondaq.com/unitedstates/export-controls-trade-investment-sanctions/1806304/old-rule-new-risk-ofacs-50-rule-and-the-growing-importance-of-control>

**False positives and alert fatigue** *(vendor-published; indicative only)*

- Dun & Bradstreet, *What Are False Positives in KYC and AML Compliance Screening?* — <https://www.dnb.com/en-us/resources/compliance-risk/what-are-false-positives-in-kyc-and-aml-compliance-screening.html>
- LSEG Risk Intelligence, *False Positives: When Systems Flag It Wrong* — <https://www.lseg.com/en/risk-intelligence/glossary/risk-management/false-positive>
- sanctions.io, *The Problem of False Positives in AML Screening* — <https://www.sanctions.io/blog/the-problem-of-false-positives-in-aml-screening>

**Vendor onboarding and third-party risk basics**

- UpGuard, *Vendor Risk Management Onboarding Process* — <https://upguard.com/blog/vrm-onboarding-process>
- Mitratech, *The Vendor Onboarding Due Diligence Guide* — <https://grc.mitratech.com/vendor-onboarding-guide>

**Corporate ownership data**

- GLEIF — the Legal Entity Identifier system and its Level 2 parent relationships — <https://www.gleif.org>
- SEC EDGAR — US company filings — <https://www.sec.gov/edgar>
