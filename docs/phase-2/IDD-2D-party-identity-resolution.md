# IDD 2D — Party & Identity Resolution

**Status:** Design · No implementation · 2026-08-03
**Depends on:** IDD-2A Semantic Registry · IDD-2B Core Business Objects · IDD-2C Knowledge Assertions (all frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · One word in the objective must be challenged

> *"guarantee that every real-world person or organization is represented **exactly once**"*

**This guarantee cannot be delivered, and a design that claims it will fail silently.**

Identity resolution is judgement under uncertainty with incomplete evidence. Two records may be the same firm under different trade names, or two genuinely different firms sharing a director and an office phone. No algorithm — and no human — can be certain from the evidence we hold.

What a serious system can promise instead:

| Achievable | Not achievable |
|---|---|
| **Never silently merge two real entities** | Certainty that two records are the same |
| **Detect and queue probable duplicates** | Zero duplicates |
| **Make every merge reversible** | Perfect first-time resolution |
| **Converge toward one representation over time** | "Exactly once", guaranteed |
| **Measure the duplicate rate and drive it down** | — |

**The design target is therefore: converge toward one representation, with every step reversible, and never merge on weak evidence.** That is a promise the architecture can actually keep for ten years.

### The asymmetry that governs every rule below

| Error | Visibility | Cost | Recovery |
|---|---|---|---|
| **False split** — one party stored as two | **Obvious** — someone notices the duplicate | Annoying | Cheap: merge them |
| **False merge** — two parties stored as one | **Near-silent** | **Catastrophic** | Expensive, sometimes impossible |

A false merge blends two firms' credit histories, payment records and conversations. Every downstream figure becomes wrong, and by the time anyone notices, the corrupted numbers have been quoted to customers.

> **Therefore: bias heavily toward splitting. When in doubt, do not merge.**

Every threshold in §3 follows from this single asymmetry.

---

## 1 · Party Architecture

### 1.1 What a Party is

A **Party** is anything that can act in the business and be held responsible for it: a person, a company, a government body, a team, or a system acting on someone's behalf.

It is **not** a customer record, a contact, or a CRM row. Those are *views* of a Party through a role.

### 1.2 Why Party is the canonical identity

Every other object in 2B joins to a Party: Leads have one, Invoices are raised on one, Interactions have participants, Commitments are owed to one, Employees are one.

**If Party is wrong, every number in the business is wrong** — and wrong in a way that is invisible, because each individual record looks fine. A duplicated customer produces two correct-looking revenue figures that sum to a lie.

Three properties make it canonical:

| Property | Consequence |
|---|---|
| **Meaningless identifier** | `knowledge_id` never changes. Companies rename, people marry, GSTINs are reissued — identity survives all of it |
| **One per real-world entity** (converged, not guaranteed) | Net position, total exposure and full history are single queries |
| **Kind is frozen; roles are not** | The thing it *is* never changes; what it *does* changes constantly |

### 1.3 Why Person and Organization are immutable kinds

A Party's **kind** is assigned once at creation and can never change.

**A Person cannot become an Organization.** Not "should not" — *cannot*, because they are different things in the world, not different states of one thing.

The practical test: a sole proprietor who incorporates has not transformed. **A new Organization comes into existence**, related to the Person by `owns` and `represents`. Both parties exist; both have history; the proprietorship's invoices stay with the proprietorship.

If kind were mutable, that event would rewrite history — the pre-incorporation invoices would silently reattribute to a legal entity that did not exist when they were raised. That is a tax and audit problem, not a modelling preference.

### 1.4 Why Customer, Supplier, Employee and Partner are roles

Established in 2B §0. Restated because it is the decision everything here depends on:

| | Kind | Role |
|---|---|---|
| Answers | What it **is** | What it **does** |
| Changes? | Never | Constantly |
| How many? | Exactly one | Zero or many, concurrent |
| Ends? | Never | **Yes, and must be recorded** |

**The test: if it can end, it is not a subtype.**

The failure that makes this concrete: a firm that buys marketing from you *and* supplies you printing is simultaneously Customer and Supplier. As subtypes that needs multiple inheritance, or two records — and with two records, *"what do we owe them net?"* has no answer.

---

## 2 · Party–Role Model

### 2.1 Structure

```
┌────────────────────────────────────────────────┐
│  PARTY                                         │
│  knowledge_id      immutable, meaningless      │
│  kind              PERSON | ORGANIZATION       │
│                    ── FROZEN AT CREATION ──    │
│  resolution_state  UNRESOLVED → PROVISIONAL    │
│                    → RESOLVED | DISPUTED       │
│                    | MERGED                    │
└───────────────────────┬────────────────────────┘
                        │ plays 0..N
┌───────────────────────▼────────────────────────┐
│  PARTYROLE                                     │
│  party             → Party                     │
│  role_type         customer | supplier |       │
│                    employee | partner |        │
│                    referrer | competitor       │
│  valid_from        required                    │
│  valid_until       null = still held           │
│  owner             accountable AGENT           │
│  terms             role-specific claims        │
└────────────────────────────────────────────────┘
```

### 2.2 Role lifecycle

```
prospective ──► active ──► suspended ──► active
                   │            │
                   └────────────┴──► ended   (TERMINAL)
```

| State | Meaning |
|---|---|
| **prospective** | Identified but not yet transacting — a lead's party before first order |
| **active** | Currently held |
| **suspended** | Temporarily halted; credit hold, leave of absence, blacklist pending |
| **ended** | Terminal. `valid_until` set. **Never deleted** |

`suspended` and `ended` are deliberately distinct. A supplier on credit hold is not a former supplier, and conflating them loses the reason.

### 2.3 Role history

Every role is a bitemporal claim (2C §7). Ending a role sets `valid_until` — it does not remove anything.

```
ORG-31 (Acme Pvt Ltd)
  ├── customer   2021-06-01 → 2024-03-31   ended (contract lapsed)
  ├── supplier   2023-08-15 → null          active
  └── customer   2025-01-10 → null          active   ← returned
```

Three roles, two of them the same type at different periods. *"Were they a customer in FY23?"* is answerable. *"How long were they dormant?"* is answerable. Neither would be under a subtype model.

### 2.4 Concurrent roles

**Concurrency is normal, not exceptional.** The same Organization may hold customer, supplier and referrer roles simultaneously. The same Person may be an employee and a customer.

Consequences:

- Net position across roles is a **single query** on one Party
- Role-specific facts attach to the **role**, not the Party — a customer credit limit is not a supplier payment term
- Party-level facts (`legal_name`, `gstin`) are asserted **once** and read by every role view
- Correcting a name corrects it everywhere, because there is one assertion

### 2.5 Role ownership

**Every active role has an accountable owner — an AGENT, never null.**

| Role | Typical owner |
|---|---|
| customer | Account manager |
| supplier | Procurement owner |
| employee | Reporting manager |
| partner | Relationship owner |

Ownership is itself time-bounded and moves without touching the role. *"Who owned this account in March?"* is answerable, which matters when something went wrong in March.

### 2.6 Why this avoids duplication

**The proof:** a firm that is both customer and supplier has

- **one** `knowledge_id`
- **one** `legal_name` claim
- **one** `gstin` claim
- **two** PartyRole records

Under a subtype model it would be two Party records, two `legal_name` claims that can diverge, and no way to compute a net position. The role pattern removes the duplication at its source rather than reconciling it afterwards.

---

## 3 · Identity Resolution

### 3.1 "Deterministic" means reproducible, not certain

The procedure is deterministic: **given the same evidence, it always reaches the same outcome** — including the outcome *"I cannot decide, escalate."*

It is not certain, because the evidence is not. Anyone promising certainty here is promising something the world does not supply.

### 3.2 Identifier classification — the core design decision

**Not all identifiers are equal, and treating them equally is the single most common cause of false merges.**

| Class | Definition | Uniqueness | Recycled? | Shared? | Auto-merge? |
|---|---|---|---|---|---|
| **SOVEREIGN** | Issued by a state authority, verifiable | Global | No | No | ✅ **Yes**, alone |
| **CONTROLLED** | Unique within one issuing system | Scoped | No | No | ⚠️ **Within that system only** |
| **CONTACT** | A channel to reach someone | **None** | **Yes** | **Yes** | ❌ **Never alone** |
| **NOMINAL** | Names, trade names, aliases | None | n/a | Yes | ❌ **Never, ever** |

### 3.3 The identifiers, classified

| Identifier | Class | Notes |
|---|---|---|
| **GSTIN** | SOVEREIGN | Unique per org per state. **One org may hold several** — one per state of registration |
| **PAN** | SOVEREIGN | Person or Org. Very stable. Strongest single identifier available |
| **CIN** | SOVEREIGN | Companies only. Survives renames — **stronger than legal_name** |
| **Aadhaar** | SOVEREIGN | ⚠️ Store **last 4 only**. Legal constraints on retention |
| **Employee ID** | CONTROLLED | Unique within the employer only. **Reused after departure at many firms** |
| **Customer ID** | CONTROLLED | Unique within the issuing system. Two systems' customer IDs are unrelated |
| **Supplier ID** | CONTROLLED | Same |
| **Phone (E.164)** | **CONTACT** | See §3.4 — the most-used and least-reliable identifier we have |
| **Email** | CONTACT | Shared inboxes (`info@`, `sales@`) are common. Personal ones are moderately stable |
| **Alias / trade name** | NOMINAL | Evidence only. Never resolves alone |

### 3.4 Phone numbers — the honest problem

**We identify almost everyone by phone, and phone is the worst identifier in the list.** In the Indian market specifically:

| Property | Consequence |
|---|---|
| **Recycled** after disconnection | Today's owner is not last year's. A merge on phone can bind two unrelated people |
| **Shared** — office and reception lines | One number, many humans |
| **Multiple per person** | Personal, work, WhatsApp Business |
| **WhatsApp Business numbers represent an ORG** | The sender may be a company, not a person — and the transport cannot tell us |

Consequences, stated as rules:

> **R1 — A phone number never auto-merges two parties, at any confidence.**
> **R2 — A party created from a phone number alone starts `PROVISIONAL`, never `RESOLVED`.**
> **R3 — A phone-number claim carries `valid_from`/`valid_until` like any other claim.** Numbers change hands; a phone binding must be able to expire.

R2 has a direct effect on the bot: **every unknown WhatsApp sender creates a PROVISIONAL party.** That is correct. Promotion to `RESOLVED` requires corroboration — a GSTIN, a PAN, or a human confirmation.

### 3.5 The resolution procedure

```
INCOMING IDENTITY EVIDENCE
   │
 ① NORMALISE      phone → E.164 · email lower/trim · GSTIN checksum
   │              names → NOT normalised for matching (§3.7)
   │
 ② EXACT MATCH on SOVEREIGN identifiers
   │   ├── exactly one party  ─────────────────────► RESOLVED
   │   ├── two or more parties ────────────────────► DISPUTED  (§3.8)
   │   └── none ──► continue
   │
 ③ EXACT MATCH on CONTROLLED identifiers (system-scoped)
   │   └── one party, same system ─────────────────► RESOLVED
   │
 ④ CONTACT + corroboration
   │   phone/email match AND ≥1 corroborating signal
   │   (shared sovereign id, confirmed name, known relationship)
   │       └──────────────────────────────────────► PROVISIONAL → queue
   │
 ⑤ CONTACT alone
   │   └──────────────────────────────────────────► PROVISIONAL, no merge
   │
 ⑥ NOTHING MATCHES
       └──────────────────────────────────────────► NEW PARTY, PROVISIONAL
```

**The procedure never merges below step ②.** Steps ④–⑥ create or link provisionally and queue for human confirmation.

### 3.6 Auto-merge conditions — deliberately narrow

Auto-merge fires **only** when *all* hold:

1. Both parties carry the **same SOVEREIGN identifier**
2. That identifier is asserted at **provenance tier ≤ 1** on both sides
3. **No contradicting sovereign identifier** exists (different PANs ⇒ different parties, full stop)
4. Both are the **same kind** (never merge a Person with an Organization)
5. Neither is currently `DISPUTED`

**Everything else queues.** This will feel conservative and produce visible duplicates. That is the intended trade: a visible duplicate costs someone five minutes; a silent false merge costs a year of corrupted figures.

### 3.7 Why names are never normalised for matching

It is tempting to strip "Pvt Ltd", lowercase, and fuzzy-match. **Do not.**

- *Sharma Traders* and *Sharma Trading Co* may be two unrelated firms in the same market
- Transliteration variance across Kannada, Hindi and English is enormous
- Fuzzy name matching produces false merges at exactly the rate that makes them hard to detect — frequent enough to matter, rare enough to go unnoticed

Names are **corroborating evidence** at step ④, never a matching key. They raise confidence in a candidate found by other means; they never find one.

### 3.8 Ambiguity and confidence

| Outcome | Meaning | Action |
|---|---|---|
| **RESOLVED** | Sovereign or system-scoped match | Use directly |
| **PROVISIONAL** | Probable, uncorroborated | **Usable, marked provisional.** Facts attach; merge deferred |
| **DISPUTED** | Contradicting evidence | **Surfaced, never auto-resolved.** Blocks tier ≥ 3 actions |
| **UNRESOLVED** | No evidence yet | New provisional party |

Resolution confidence follows 2C: **capped by the provenance tier of the identifying claim.** A GSTIN from the GST portal is tier 0; a GSTIN typed into WhatsApp by a customer is tier 5 and caps at 0.50 — nowhere near an auto-merge.

**`DISPUTED` is a first-class state that must be surfaced**, not an error to be cleared. A disputed party is a real signal — usually that two firms share a director, an address, or a phone.

---

## 4 · Party Relationships

Classified per 2A's six frozen semantic classes.

| Relationship | Class | Direction | Cardinality | Time-bounded | Inverse |
|---|---|---|---|---|---|
| `employs` | Participation | ORG → PERSON | 1:N | **yes** | `employed_by` |
| `owns` | Transactional | PARTY → PARTY/RESOURCE | 1:N | **yes** | `owned_by` |
| `reports_to` | Participation | PERSON → PERSON | N:1 | **yes** | `has_report` |
| `represents` | Participation | PERSON → ORG | N:M | **yes** | `represented_by` |
| `referred_by` | Participation | PARTY → PARTY | N:1 | no† | `referred` |
| `member_of` | Structural | PARTY → ORG | N:M | **yes** | `has_member` |
| `partner_of` | Participation | PARTY ↔ PARTY | N:M | **yes** | *symmetric* |
| `succeeded_by` | Temporal | PARTY → PARTY | 1:1 | no† | `succeeds` |

† Historical facts. They happened at a moment and do not expire.

### 4.1 `contacts` is not a relationship — challenge

The brief lists `contacts`. **"X contacts Y" is an event, not a persistent edge.** It has a time, a channel, a duration and content — it is an **Interaction** (2B, OCCURRENCE), participants attached by `Participation`.

Modelling it as an edge would either collapse thousands of contacts into one meaningless link, or create thousands of edges that are really events with a worse shape. **Recommend removing it** and using Interaction, which the timeline (§5) already depends on.

### 4.2 `partner_of` is symmetric — handle explicitly

Most relationships have a distinct inverse. `partner_of` does not: if A partners B, B partners A, with the same meaning.

Per 2A §4.4, storing both directions creates a consistency failure with no detector. For symmetric relations the rule is: **store once with a canonical ordering** (lower `knowledge_id` first) and resolve in either direction on read.

### 4.3 `referred_by` — two facts, not one

*"Acme referred Beta"* is a durable social fact between parties. *"This lead came via Acme"* is an attribution on a specific Lead.

Both are real and both are needed. The Party-level edge answers *"who are our best referrers?"*; the Lead-level attribution answers *"what did this particular deal come from?"* Collapsing them loses one of those questions — usually the first, which is the commercially valuable one.

### 4.4 Lifecycle and history

Every relationship is a bitemporal LinkClaim (2C §2.1):

- Ending sets `valid_until`; nothing is deleted
- *"Who reported to whom in 2024?"* is a point-in-time traversal
- Re-establishing creates a **new** claim, preserving the gap
- `succeeded_by` is never time-bounded — succession is a historical event, not a state

---

## 5 · Party Timeline

### 5.1 The timeline is a query, not a stored object

**Nothing is written to a "timeline" table.** It is derived by gathering everything where the Party is subject or participant, ordered by time.

Storing it would create a second source of truth that drifts from the claims it summarises — the failure 2C §1.3 exists to prevent.

### 5.2 What it gathers

| Source | Via | Contributes |
|---|---|---|
| Interactions | `Participation` | meetings, WhatsApp, calls, email, visits |
| Leads | role → lead | created, qualified, won/lost |
| Quotations | via lead | issued, revised, accepted, expired |
| Orders | role → order | confirmed, delivered |
| Invoices | role → invoice | raised, part-paid, settled, overdue |
| Payments | via invoice | cleared, failed, reversed |
| Projects | `assigned_to` / customer role | started, held, delivered |
| Commitments | role → commitment | made, met, **missed** |
| Documents | `references` | contracts, POs, certificates |
| Role changes | PartyRole | became customer, ended employment |
| Merges | merge record | **"this party absorbed another on 3 Aug"** |

### 5.3 Three properties that make it useful

**It spans roles.** A party that was a customer, became dormant, then returned as a supplier has **one** continuous timeline. This is only possible because of the Party–Role model — under subtypes it would be two timelines with no join.

**It spans channels.** WhatsApp, email, meeting and site visit interleave in one sequence. *"When did we last touch them?"* has one answer, which is the entire reason Meeting and Communication were merged into `Interaction` in 2B.

**It is bitemporally honest.** The timeline can be rendered *as we knew it at time T*, not just as we know it now. That is what makes *"what did we know when we approved that discount?"* answerable.

### 5.4 Merge and split appear on the timeline

A merge is a business event and belongs in the history. *"Why did this customer's revenue jump in August?"* — because two parties were merged on 3 August. Without that entry, the jump looks like growth.

---

## 6 · Identity Rules

### 6.1 Merge

**Preconditions:** §3.6 auto-merge conditions, or explicit human approval with recorded evidence.

**Procedure**
1. Choose a **survivor** — the party with the strongest sovereign evidence, not the older record
2. Write a **merge record**: survivor, absorbed, evidence, approver, timestamp, reason
3. Absorbed party is marked `MERGED` with a `merged_into` pointer — **never deleted**
4. Claims and links are **not rewritten**. Queries follow `merged_into`
5. Both `knowledge_id`s remain valid forever; the absorbed one resolves to the survivor

**Point 4 is what makes reversal possible.** Rewriting claims to point at the survivor would destroy the information needed to undo the merge.

### 6.2 Unmerge

**Reversal is mandatory and must be tested, not assumed** (2B acceptance criterion).

1. Delete the merge record
2. Both parties return to `RESOLVED` (or `DISPUTED`)
3. Original claims resolve to their original parties automatically — nothing was rewritten

**The hard case, stated honestly:** claims recorded *after* the merge were asserted against the survivor and carry no memory of which real entity they concerned.

> **Rule: post-merge claims stay with the survivor unless explicitly reassigned during the unmerge, and the unmerge must present them for reassignment.**

There is no automatic answer here. Pretending otherwise would silently misattribute facts — the exact failure the unmerge exists to correct. The design's honest contribution is to **surface the ambiguity** rather than resolve it wrongly.

### 6.3 Split

Distinct from unmerge: a single record that **always** represented two entities and was never merged — usually created from a shared office phone.

1. Create a new Party for the second entity
2. **Human partitions the claims** — no algorithm can do this
3. Record a **split record**: origin, resulting parties, evidence, approver, per-claim assignment
4. Both parties reference the split; the timeline shows it

**Split is always human-driven.** It is rarer than merge and considerably more dangerous, because it distributes existing facts rather than combining them.

### 6.4 Alias

An alias is a **NOMINAL claim**, never an identity.

- Trade names, former names, transliterations, informal names
- Bitemporal — *"trading as Acme Digital, 2021–2024"*
- Used for **search and corroboration**; never for matching (§3.7)

### 6.5 Rename

**Identity does not change.** A rename is a new `legal_name` claim with `valid_from`, and `valid_until` on the previous one. Both readable forever.

*"What were they called when we raised invoice INV-441?"* is answerable by querying `legal_name` as of the invoice date. Overwriting the name would make historical documents unreconcilable with current records.

### 6.6 Legal change — the cases that are genuinely different

| Event | Same Party? | Model |
|---|---|---|
| **Rename** | ✅ Yes | New `legal_name` claim |
| **Proprietorship → Pvt Ltd** | ❌ **No** | **New Organization.** Person `owns` and `represents` it. Old party's history stays with the old party |
| **Pvt Ltd → Ltd** (conversion) | ✅ Yes | Same CIN, so same party. New `legal_form` claim |
| **Merger** (Acme into Beta) | ❌ No | Acme `succeeded_by` Beta. Acme's roles end; Acme is **not deleted** |
| **Demerger** (Acme → Acme + Gamma) | ❌ No | New party for Gamma; `succeeds` from Acme. **A split with legal semantics** |
| **GSTIN reissued** | ✅ Yes | Old GSTIN claim gets `valid_until`; new one asserted |

**CIN is the strongest continuity signal for Indian companies** — it survives renames and legal-form conversions, which `legal_name` does not.

### 6.7 The invariant across all six

> **History is never lost. Nothing is deleted, overwritten, or rewritten. Every operation is additive, recorded with evidence and an approver, and — where it combines entities — reversible.**

---

## 7 · Future Extension

Party is **never modified** by a vertical. Every industry adds roles, identifiers and relationships as registry rows.

| Industry | New roles | New identifiers | Party changes |
|---|---|---|---|
| **Manufacturing** | `vendor`, `subcontractor`, `inspector` | vendor code, BIS licence | **none** |
| **Hospital** | `patient`, `clinician`, `payer`, `next_of_kin` | UHID, ABHA, insurer member no. | **none** |
| **Retail** | `member`, `franchisee` | loyalty ID | **none** |
| **Government** | `beneficiary`, `applicant`, `official`, `contractor` | scheme ID, ration card, voter ID | **none** |
| **Construction** | `contractor`, `consultant`, `approver` | licence no., PWD registration | **none** |
| **Education** | `student`, `guardian`, `faculty` | enrolment no. | **none** |
| **Legal** | `client`, `counsel`, `opposing_party` | bar council no. | **none** |

### 7.1 Why `beneficiary` as a role matters

A citizen may be a beneficiary of three schemes, a grievance raiser, a contractor's employee, and a voter in one constituency — **one Party, five roles**. A `Beneficiary` *type* would need five records and could never answer *"has this person already benefited from a similar scheme?"* — which is the question the government actually cares about.

### 7.2 New identifiers extend, never replace

Each vertical identifier declares its **class** (§3.2) and inherits the merge rules:

- `UHID` → CONTROLLED (unique within one hospital only)
- `ABHA` → SOVEREIGN (national health ID)
- `voter_id` → SOVEREIGN
- `loyalty_id` → CONTROLLED

**A vertical cannot invent a new identifier class.** The four are frozen; adding one would mean the merge rules do not cover it.

---

## 8 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Party defined with frozen `kind` and a `resolution_state` machine |
| 2 | PartyRole defined with lifecycle, bitemporal validity and a non-null owner |
| 3 | Four identifier classes defined, with per-class merge rules |
| 4 | Every listed identifier assigned a class |
| 5 | Relationships classified per 2A's six classes, with direction, cardinality, time-bounding and inverse |
| 6 | `contacts` removed in favour of Interaction |
| 7 | `partner_of` handled as symmetric with canonical ordering |
| 8 | Timeline specified as a **query**, never a stored object |

### Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 9 | Same firm as customer and supplier | **One** party, **two** roles, net position in one query |
| 10 | Attempt to change a Party's kind | **REJECTED** |
| 11 | Two parties share a phone number only | **NO auto-merge.** Both PROVISIONAL, queued |
| 12 | Two parties share a tier-0 GSTIN | **Auto-merge** |
| 13 | Two parties share a GSTIN asserted at tier 5 | **NO auto-merge** — confidence capped at 0.50 |
| 14 | Two parties share a GSTIN but have different PANs | **DISPUTED**, never merged |
| 15 | Attempt to merge a Person with an Organization | **REJECTED** |
| 16 | Fuzzy name match on "Sharma Traders" / "Sharma Trading Co" | **NO merge** — names never match |
| 17 | Perform a merge, then unmerge | Both parties restored; original claims resolve correctly |
| 18 | Unmerge with post-merge claims present | Ambiguous claims **surfaced for reassignment**, not silently kept |
| 19 | Split a conflated party | Human partition recorded; both parties independently queryable |
| 20 | Company renames | Identity unchanged; historical name queryable as of an old invoice date |
| 21 | Proprietorship incorporates | **Two** parties; pre-incorporation invoices stay with the proprietorship |
| 22 | Company merger | `succeeded_by` recorded; absorbed party **not deleted**; roles ended |
| 23 | Employee changes company | Both roles retained; phone claim unaffected (2C §7.3) |
| 24 | End a role | `valid_until` set; party and history intact |
| 25 | Unknown WhatsApp sender | Creates a **PROVISIONAL** party, not RESOLVED |
| 26 | Query the timeline as of a past date | Returns belief at that date, not current belief |
| 27 | Timeline spans a customer→supplier transition | **One** continuous timeline |
| 28 | Merge appears on the timeline | Present, so revenue jumps are explicable |

### Extensibility

| # | Test | Expected |
|---|---|---|
| 29 | Add hospital roles and identifiers (UHID, ABHA) | Registry rows only; **zero Party changes** |
| 30 | Add government roles (beneficiary, applicant) | Registry rows only; zero Party changes |
| 31 | Model a citizen with five concurrent roles | One party, five roles |
| 32 | Count Party changes across 29–31 | **Exactly zero** |

### Quality — the criteria that matter most

| # | Criterion | Target |
|---|---|---|
| 33 | **False-merge rate**, measured by sampled audit | **Zero tolerated.** Any occurrence triggers a threshold review |
| 34 | Duplicate rate, measured and trending | Declining |
| 35 | Resolution queue depth and age | Bounded; ageing items escalate |
| 36 | Every merge reversible — **demonstrated in production, not asserted** | 100% |

### Non-regression

| # | Criterion |
|---|---|
| 37 | Zero application code touched |
| 38 | Phase 1C suite green (226 tests) |
| 39 | Compatible with 2A/2B/2C — no frozen concept modified |
| 40 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 33 is the acceptance test for this slice.** Everything else proves the model is coherent. Only 33 proves it is *safe* — and a single false merge in production is grounds to tighten thresholds immediately, not to explain it away.

---

## 9 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | **False merge** — silent, corrupts every downstream figure | **Existential** | Sovereign-only auto-merge; reversible; sampled audit; zero tolerance |
| **R2** | Phone-based resolution over-merges | **High** | R1–R3 in §3.4. Phone never merges alone |
| **R3** | Resolution queue grows unmanageable | Medium | Measure depth and age; escalate. If unworkable, thresholds are wrong — **not the rule** |
| **R4** | Duplicates erode trust before convergence | Medium | Visible duplicates are the **intended trade**. Communicate this to users |
| **R5** | Post-merge claim ambiguity on unmerge | **High** | §6.2 — surfaced, never auto-assigned |
| **R6** | Someone adds fuzzy name matching "to reduce duplicates" | **High** | §3.7 recorded as a decision, with the reasoning, so it is re-argued rather than quietly added |

---

## 10 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **"Exactly once" is a convergence target, not a guarantee** (§0) — the design promises reversibility and no silent merges instead
2. **Four identifier classes**, with auto-merge restricted to SOVEREIGN
3. **Phone never auto-merges**, at any confidence (§3.4)
4. **Names are never a matching key** — corroboration only (§3.7)
5. **Unknown WhatsApp senders create PROVISIONAL parties**, not resolved ones
6. **`contacts` removed** in favour of Interaction (§4.1)
7. **Post-merge claim ambiguity is surfaced, not auto-resolved** (§6.2)
8. **Proprietorship → Pvt Ltd creates a new Party**, preserving pre-incorporation history (§6.6)
9. **Timeline is a query**, never stored (§5.1)
10. **Zero tolerance for false merges** — any occurrence triggers a threshold review (§8.33)

**Items 1, 3 and 4 will make the system feel worse before it feels better** — more visible duplicates, more queued confirmations. That is the deliberate trade, and it is worth stating plainly now so it is not reversed in six months under pressure to "clean up the duplicates."

A false merge is not a duplicate. It is a corrupted business record that nobody notices.
