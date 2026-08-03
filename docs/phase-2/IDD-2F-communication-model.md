# IDD 2F — Communication Model

**Status:** Design · No implementation · 2026-08-03
**Depends on:** 2A · 2B · 2C · 2D · 2E (all frozen)
**Gate:** implementation may not begin until this document is approved

---

## 0 · Reconciling two frozen documents

2A and 2B named the same two concepts differently. Both are frozen, so this is an **alignment, not a redesign**:

| 2A (semantic) | 2B (object) | Category | This document uses |
|---|---|---|---|
| `core.communication@1` — the ACT | **Interaction** | OCCURRENCE | **Interaction** |
| `core.message@1` — the CONTENT | **Document** | ARTIFACT | **Message** *(a kind of Document)* |

**`Interaction` is the object name; `Communication` is the semantic-registry concept it realises.** `Message` is a Document subtype — it inherits content-hash identity, which is what makes "the same PDF forwarded twice" one artifact and two interactions.

No frozen concept changes. Only the vocabulary is unified.

---

## 1 · Communication vs Interaction vs Conversation

### 1.1 The three, sharply separated

| | What it is | Stored? | Bounded by |
|---|---|---|---|
| **Interaction** | One bounded episode of contact | **Yes** — OCCURRENCE | Time and participants |
| **Message** | One unit of content within it | **Yes** — ARTIFACT | The content itself |
| **Conversation** | A continuing exchange with a party | **No — derived** | Nothing objective (§1.3) |

### 1.2 The distinction that carries the weight

**An Interaction is an event. A Message is a thing.** A phone call is an Interaction with no Message. A forwarded PDF is one Message appearing in three Interactions. A meeting is an Interaction that may produce a Message (the minutes).

Collapsing them means either counting one forwarded document as three documents, or losing the fact that it was sent three times. Both matter commercially.

### 1.3 Conversation is derived — challenge

The brief implies Conversation is an object. **It should not be stored**, for the same reason the Party Timeline is not (2D §5.1): its boundaries are not objective.

| Channel | Does a "conversation" have a boundary? |
|---|---|
| Email | Yes — `In-Reply-To` / `References` headers |
| Slack / Teams | Partly — threads inside channels |
| **WhatsApp** | **No.** One continuous stream per number, forever |
| Phone | Each call is separate; the relationship is continuous |
| Meetings | No inherent threading |

Storing a Conversation forces a boundary decision **at write time**, on channels that have no boundary — and that decision will be wrong. Six months later, was the March enquiry the same conversation as the June order? The answer depends on the question being asked, so it must be computed at read time.

> **Conversation is a query over Interactions, scoped by party, time window and optionally thread.**

### 1.4 Thread and Session are not business objects either

**Thread is transport metadata.** Email `Message-ID` / `In-Reply-To`, Slack `thread_ts`, WhatsApp `context.id` for quoted replies. Captured as an **attribute on the Message**, used to reconstruct structure. It is not a business concept — no business rule depends on "the thread".

**Session is a channel policy window.** WhatsApp's 24-hour rule is a *Meta billing and consent policy*, not a business concept. It answers *"may we send freely right now, or does this need an approved template?"*

That belongs in the **channel adapter**, surfaced as a capability — `channel.can_send_freely(party)` — never modelled as a core object. Modelling it would put one vendor's commercial policy into the permanent object model, where it would outlive the policy.

### 1.5 What this leaves

**Two stored objects. Three derived views.**

```
STORED                          DERIVED
├── Interaction  (OCCURRENCE)   ├── Conversation  (query)
└── Message      (ARTIFACT)     ├── Thread        (from transport attrs)
                                └── Session       (channel capability)
```

---

## 2 · The Canonical Interaction

```
INTERACTION  (OCCURRENCE)
├── IDENTITY
│   ├── knowledge_id · tenant_id
│   └── external_ref          channel + provider id (dedup key)
│
├── CHANNEL
│   ├── channel               whatsapp | email | sms | voice | meeting |
│   │                         webchat | telegram | slack | teams | note
│   ├── mode                  synchronous | asynchronous
│   └── provider              which integration produced it
│
├── PARTICIPANTS              Participation edges, NOT a list of strings
│   └── each: party · role (initiator | recipient | cc | observer |
│             organiser | attendee | no_show) · joined/left
│
├── TIME
│   ├── occurred_at           WORLD time — when it happened
│   ├── ended_at              null for instantaneous
│   ├── duration              derived
│   └── received_at           SYSTEM time — when we learned of it
│
├── CONTENT
│   └── messages[]            0..N Messages (a call may have none)
│
├── REFERENCES                Evidential edges to any object
│
├── LIFECYCLE
│   └── state                 §4
│
└── DERIVED  (never stored on the Interaction — §7)
    ├── business_purpose · intent · sentiment
    └── extracted commitments, risks, action items
```

### 2.1 The canonical Message

```
MESSAGE  (ARTIFACT — a Document subtype)
├── content_hash              IDENTITY. Same content = same Message
├── interaction_ref           which episode carried it
├── direction                 INBOUND | OUTBOUND | INTERNAL
├── author                    party
├── body_ref                  pointer to stored content
├── media[]                   §6
├── thread                    provider_message_id · in_reply_to · thread_key
└── delivery                  §4.2 — outbound only
```

### 2.2 Four challenges to the proposed field list

**`direction` belongs on the Message, not the Interaction.** A meeting has no direction — it is not inbound or outbound. An email exchange contains both. Putting direction on the episode forces a wrong answer for every two-way interaction.

**`business_purpose` must not be a stored field.** It is an *interpretation*, produced by a model at tier 4. Storing it on the Interaction records an opinion as though it were an observed property, with no provenance, no confidence and no lineage. It belongs in the knowledge plane as a derived claim (§7).

**`participants` are edges, not a list.** A list of names cannot express *role* (organiser vs attendee vs no-show), cannot be time-bounded (joined late, left early), and cannot resolve to a Party. Participation edges (2A) give all three.

**"Documents" is not a channel.** The brief lists it alongside WhatsApp and Email. A document *arrives via* a channel — it is an ARTIFACT, not a transport. Treating it as a channel would create interactions with no participants and no time.

### 2.3 Internal notes map cleanly

An internal note is an **Interaction with `channel = note` and only internal participants.** No external party, no delivery state.

This is why it belongs in the same model: *"everything we know about this customer, in one timeline"* must include the note where someone wrote *"they mentioned a competitor quote."* A separate notes system puts the most decision-relevant context outside the timeline.

---

## 3 · Conversation, Thread, Session — begin and end

| Concept | Begins | Ends | Stored |
|---|---|---|---|
| **Message** | Content is authored or received | Immediately — a point event | ✅ |
| **Interaction** | First contact in an episode | Explicit end (call hangs up, meeting closes) **or** a channel-specific inactivity gap | ✅ |
| **Thread** | A reply references a prior message | Never — threads are open-ended | attribute |
| **Session** | Per channel policy (WhatsApp: inbound message) | Per channel policy (WhatsApp: +24 h) | capability |
| **Conversation** | **Defined by the query**, not by the data | Same | derived |

### 3.1 Interaction boundaries — the honest part

For synchronous channels (call, meeting) the boundary is objective: it starts and stops.

For asynchronous channels it is **a modelling choice, and must be declared per channel** rather than assumed:

| Channel | Boundary rule |
|---|---|
| WhatsApp | Inactivity gap — configurable, ~4 h default |
| Email | One Interaction per message; threading reconstructs structure |
| SMS | Inactivity gap |
| Web chat | Explicit session from the widget |

**This is a declared parameter, not a truth.** Recorded as such so a future maintainer knows it was a decision rather than a discovery — and can change it per channel without re-deriving what "conversation" means.

---

## 4 · Lifecycle

### 4.1 Interaction lifecycle

```
scheduled ──► in_progress ──► completed
     ├──► cancelled
     └──► no_show          ← DISTINCT from cancelled
```

Instantaneous interactions (a received WhatsApp message) enter directly at `completed`.

`no_show` remains distinct from `cancelled` (2B): *nobody came* and *it was called off* are different facts, and the reliability signal lives in the difference.

### 4.2 Message delivery — outbound only

```
draft ──► queued ──► sent ──► delivered ──► read
                       │
                       └──► failed ──► (retry) ──► queued
```

**Inbound messages have exactly one state: `received`.** We do not control their lifecycle, and modelling one invents states we can never observe.

### 4.3 Three corrections to the proposed lifecycle

**`Replied` is not a state.** A message does not become "replied" — a *reply exists*, which is a relationship (`in_reply_to`) on another Message. As a state it would need mutating an immutable record; as a relationship it is free, and it supports many replies rather than one boolean.

**`Deleted` must not exist.** Communications are business records. Deleting one destroys the answer to *"what did we tell them in March?"*

WhatsApp's "delete for everyone" is itself an **event**: the sender retracted at time T. That is recorded as a retraction (2C §3.3) — the message remains readable, marked retracted, excluded from current views and included in historical replay. **What was said and later retracted is often the most significant thing in a dispute.**

**`Archived` is a storage tier, not a state.** Same reasoning as 2C §3.4 — where the bytes live is not what is true.

### 4.4 Derived states

| State | Derived as |
|---|---|
| **Unanswered** | Inbound message with no outbound in the same party-scope after it |
| **Awaiting reply** | Outbound message with no inbound after it, past a channel-specific expectation window |
| **Stale** | Either of the above beyond an SLA |
| **Replied** | An `in_reply_to` edge exists |

None is stored. All are computed at read time and therefore always current — a stored flag would go stale the moment the next message arrived.

---

## 5 · Relationship Model

| Related to | Edge | Class | Meaning |
|---|---|---|---|
| **Party** | `Participation` | Participation | Who took part, in what role |
| **Lead** | `references` | Evidential | The exchange that advanced it |
| **Project** | `references` | Evidential | Project correspondence |
| **Task** | `references` / `originated` | Evidential | *"Do X"* became a Task |
| **Meeting** | — | — | **A meeting IS an Interaction** (2B merge) |
| **Quotation** | `references` + `evidenced_by` | Evidential | The email that carried it |
| **Invoice** | `references` | Evidential | Payment chasing |
| **Commitment** | **`originated`** | Evidential | *"I'll pay Friday"* created it (§7.3) |
| **Decision** | `evidence_ref` | Evidential | Contributed to a decision packet (2E) |
| **Knowledge Assertions** | **`extracted_from`** | Evidential | Claims derived from content (§7) |
| **OI** | via decision evidence | Evidential | **Never a direct edge** |

### 5.1 Two rules

**Communications reference; they are never owned.** An Interaction is not "part of" a Lead — it *references* it. The same call may reference a Lead, a Project and an Invoice. Ownership would force one, and lose the rest.

**OI never links directly to Interactions.** It references the **evidence packet**, which references the claims, which reference the Interaction they were extracted from. Traversing that chain is what makes *"what did they actually say that made us decide this?"* answerable — and a direct edge would bypass the provenance we need.

---

## 6 · Attachments

### 6.1 Attachments are Documents, not fields

Any file — PDF, image, voice note, video, spreadsheet — is a **Document (ARTIFACT)** with content-hash identity, attached to a Message by an edge.

**The consequence that matters:** the same quotation PDF sent to three customers is **one Document and three attachment edges**. Deduplication is automatic, and *"who else received this?"* becomes answerable.

### 6.2 Media and derived content

```
Voice note (audio, ARTIFACT)
     │ derived, tier 4, capped 0.60
     ▼
Transcript (derived claim)
     │ derived from the transcript
     ▼
Extracted commitments, intents  ← DEPTH 2 — the cap (2C §8.3)
```

**Raw media is retained permanently** (2C §V2). A better transcriber in 2029 can re-derive from the original; it cannot re-derive from a 2026 transcript. Discarding the audio after transcription trades a permanent asset for temporary storage savings.

**Derivation depth is capped at 2.** Audio → transcript → commitment is the limit. Anything further compounds confidence downward until the lineage is unexplainable.

### 6.3 Storage is not modelled here

Where bytes live — object store, Drive, provider CDN — is an adapter concern. The model holds a `content_hash` and a resolvable reference. Media that is only reachable through an expiring provider URL is **fetched and stored**, not linked, or the record decays.

---

## 7 · Business Meaning

### 7.1 The rule

> **Extraction produces derived claims in the knowledge plane. The prompt is never stored, and the interpretation is never written onto the Interaction.**

```
Message content  (retained raw, ARTIFACT)
      │
      │  extraction — ASYNCHRONOUS, off the request path
      ▼
DERIVED CLAIMS (2C)
   predicate · value · tier 4 · confidence ≤ 0.60
   derivation: { model, task_contract, inputs, computed_at }
   extracted_from → Message
      │
      ▼
Read by the Brain like any other fact
```

**What is stored:** the claim, its provenance, its confidence, and a pointer to the message it came from.
**What is not stored:** the prompt, the model's raw output, the reasoning trace.

The claim is reproducible without them — re-run the extraction on the retained raw content. Storing prompts would couple the knowledge plane to a specific model's interface, which is the vendor lock-in the whole architecture exists to prevent.

### 7.2 The speech-act distinction — the subtlety that matters most

> **A statement in a conversation creates TWO facts, not one.**

*"We'll pay by Friday"* produces:

| Fact | Predicate | Tier | Cap | Confidence in |
|---|---|---|---|---|
| **They said it** | `stated_payment_intent` | **2–4** (extraction) | 0.80 / 0.60 | that the words were said |
| **They will pay Friday** | `expected_payment_date` | **5** (self-reported) | **0.50** | that it will happen |

Conflating them means **treating a promise as a fact.** A customer's stated budget of ₹5 lakh is not their budget — it is what they said their budget was, and the difference is the entire skill of sales.

Article II.6 caps customer-sourced claims at 0.50 for exactly this reason. This section is where that cap becomes operational.

### 7.3 What extraction produces

| Extracted | Becomes | Notes |
|---|---|---|
| **Intent** | Derived claim on the Interaction | Enquiry, complaint, follow-up, negotiation |
| **Commitment** | **A Commitment object** (2B) | With party, obligation, due date, owner |
| **Action item** | **A Task object** (2B) | Assigned, with a due date |
| **Deadline** | TEMPORAL claim | On the referenced object |
| **Risk** | Derived claim | Escalation signal |
| **Approval** | Input to a Decision (2E) | **Never the decision itself** |
| **Sentiment** | Derived claim | Low-tier, easily wrong, never decisive |

### 7.4 Two hard rules

**Extraction never acts.** It produces claims and proposes objects. Creating a Commitment from *"I'll pay Friday"* is a proposal that goes through the Decision Engine like any other — because a mis-extracted commitment that silently enters the tracking system is worse than none.

**Extraction is asynchronous.** Never on the request path. A customer waiting for a reply must not wait for entity extraction. This is also why raw retention matters — extraction can be re-run, improved, or back-filled without touching the conversation.

---

## 8 · Communication Retrieval

Every view below is a **query**, never a stored list.

| View | Definition | Notes |
|---|---|---|
| **Latest** | Most recent Interaction by `occurred_at`, party-scoped | |
| **Unanswered** | Inbound with no subsequent outbound in party-scope | Excludes auto-replies and delivery receipts |
| **Awaiting reply** | Outbound with no inbound after it, past the channel's expectation window | |
| **Pending** | Open Commitments and Tasks *originated* from communications | |
| **Customer timeline** | All Interactions where the party participated | **Spans channels and roles** (2D §5.3) |
| **Project timeline** | All Interactions referencing the project | |
| **Decision timeline** | Interactions whose extracted claims entered a decision packet | **Two hops**, per §5.1 |

### 8.1 "Important" must be explainable — challenge

The brief lists *important* as a retrieval mode. **Importance is not a property of a message.** It is a ranking, relative to a purpose, and a stored `is_important` flag would be an unexplainable opinion that goes stale.

Importance is **computed and decomposable**:

| Signal | Contribution |
|---|---|
| Contains an extracted Commitment | High |
| References a high-value object | High |
| Unanswered beyond SLA | High |
| From a party with an open Opportunity | Medium |
| Escalation or risk language extracted | Medium |
| Recency | Decay |

**Every "important" result must be able to say why it ranked.** An unexplainable priority list gets ignored within a month, because the first wrong ranking destroys trust in all of them.

### 8.2 Retrieval never returns raw content by default

Retrieval returns **Interaction metadata and derived claims**. Raw content is fetched explicitly, and that fetch is a capability invocation — policy-gated and audited, because conversation content is the most sensitive data in the system.

This also keeps context packets small: the Brain usually needs *"they committed to Friday"*, not the full transcript.

---

## 9 · Future Expansion

The model is channel-agnostic and domain-agnostic. Verticals add **registry rows and adapters**, never model changes.

| Industry | Channels added | Extracted concepts | Interaction changes |
|---|---|---|---|
| **Manufacturing** | EDI, supplier portal | Spec queries, deviation requests, inspection findings | **none** |
| **Healthcare** | Patient portal, teleconsult, IVR | Symptoms, consent, referrals, follow-up | **none** — ⚠️ consent is a Commitment |
| **Retail** | In-store, social DM, review platforms | Complaints, returns, sentiment | **none** |
| **Construction** | Site app, RFI system | RFIs, site instructions, safety observations | **none** |
| **Government** | Grievance portal, IVR, physical letter | Grievances, applications, appeals | **none** |
| **Legal** | Court filing, secure client portal | Instructions, filings, deadlines | **none** — ⚠️ privilege is per-fact |
| **Education** | Parent app, LMS | Absence, performance, parent concerns | **none** — ⚠️ minors' data |

### 9.1 What a new channel actually adds

An adapter that maps the provider's payload into Interaction + Message + Participation, plus:

- The channel's **boundary rule** (§3.1)
- The channel's **session policy**, if any (§1.4)
- The channel's **delivery states** (some have none)
- **Retention and consent constraints**

All configuration. The core model does not learn what Telegram is.

### 9.2 Three verticals that will stress this

Flagged now rather than discovered during a sale:

- **Legal** — privilege is a *per-fact* visibility rule. A single message may be partly privileged. The frozen `visibility` + `acl_roles` model must be validated against this before signing a legal client.
- **Healthcare** — consent governs whether a communication may be retained at all, and consent is itself a Commitment with a lifecycle.
- **Education** — minors' data carries retention and access constraints that differ per jurisdiction.

None is blocked by this model. Each needs validation on paper first.

---

## 10 · Acceptance Criteria

### Structural

| # | Criterion |
|---|---|
| 1 | Interaction and Message are the only stored objects; Conversation, Thread and Session are derived or adapter-level |
| 2 | `direction` is on Message, not Interaction |
| 3 | `business_purpose` is a derived claim, not a stored field |
| 4 | Participants are Participation edges with roles, not a list |
| 5 | Attachments are Documents with content-hash identity |
| 6 | Message delivery states are outbound-only; inbound has one state |
| 7 | No `Deleted` state exists — retraction is an event |
| 8 | Interaction boundary rules declared **per channel** |
| 9 | Internal notes map to Interaction with `channel = note` |
| 10 | Retrieval views are all queries |

### Behavioural — must be demonstrated

| # | Test | Expected |
|---|---|---|
| 11 | Same PDF sent to three customers | **One** Document, **three** attachment edges |
| 12 | Phone call with no message content | Valid Interaction, zero Messages |
| 13 | Meeting recorded | An Interaction — **not** a separate Meeting object |
| 14 | Attempt to mark a message `Deleted` | **REJECTED** — retraction only; message remains readable |
| 15 | Sender retracts a WhatsApp message | Retraction recorded; original in historical replay, excluded from current |
| 16 | *"We'll pay by Friday"* extracted | **Two claims**: stated-intent (tier 2–4) and expected-date (**tier 5, ≤ 0.50**) |
| 17 | Extraction attempts to create a Commitment directly | **REJECTED** — proposal only, through the Decision Engine |
| 18 | Store a prompt alongside an extracted claim | **REJECTED** |
| 19 | Voice note transcribed | Audio **retained**; transcript is a derived claim at tier 4 |
| 20 | Re-run extraction with a better model | New claims derived from **retained raw**, superseding the old |
| 21 | Derivation depth 3 from a voice note | **REJECTED** — capped at 2 |
| 22 | Customer timeline for a party who was customer then supplier | **One** continuous timeline |
| 23 | *Unanswered* query | Excludes auto-replies and delivery receipts |
| 24 | *Important* result | **Explains why it ranked** |
| 25 | Retrieve raw content | Requires a **policy-gated, audited** capability call |
| 26 | Same message in two channels (forwarded) | One Message, two Interactions |
| 27 | Add Telegram | Adapter + config only; **zero model changes** |
| 28 | Add a channel with no delivery receipts | Supported; delivery states simply absent |

### Extensibility

| # | Test | Expected |
|---|---|---|
| 29 | Model a healthcare teleconsult | Registry + adapter only; zero Interaction changes |
| 30 | Model a government grievance via IVR and letter | Two channels, one timeline; zero model changes |
| 31 | Count core model changes across 27–30 | **Exactly zero** |

### Non-regression

| # | Criterion |
|---|---|
| 32 | Zero application code touched |
| 33 | Phase 1C suite green (226 tests) |
| 34 | Compatible with 2A–2E; no frozen concept modified |
| 35 | **Live production probe:** unsigned → 403; a real message replies |

**Criterion 16 is the acceptance test for this slice.** The rest prove the model is well-formed. Only 16 proves it is *honest* — that the system distinguishes what a customer **said** from what is **true**. A model that cannot make that distinction will confidently report promises as facts, and every forecast built on it will be wrong in the same optimistic direction.

---

## 11 · Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | Extraction treated as fact rather than tier-4 claim | **High** | Provenance caps enforced; §7.2 speech-act split |
| **R2** | Raw content discarded after extraction | **High** | Retention mandatory (2C §V2) — a better model later cannot re-derive from a transcript |
| **R3** | Conversation stored, boundaries wrong | Medium | Derived, never stored (§1.3) |
| **R4** | Extraction on the request path | Medium | Asynchronous by design (§7.4) |
| **R5** | Conversation content leaks via retrieval | **High** | Raw content behind a policy-gated capability (§8.2) |
| **R6** | A vendor's session policy enters the object model | Medium | Session is an adapter capability (§1.4) |
| **R7** | Importance stored as a flag, becomes unexplainable | Medium | Computed and decomposable (§8.1) |

---

## 12 · Approval Gate

Implementation may not begin until these are accepted **or amended**:

1. **Conversation, Thread and Session are not stored objects** — derived, attribute, and adapter capability respectively
2. **`direction` moves to Message**; an Interaction has no direction
3. **`business_purpose` is a derived claim**, never a stored field
4. **No `Deleted` state** — retraction is an event and the record survives
5. **`Replied` is a relationship**, not a state
6. **`Archived` is a storage tier**, not a lifecycle state
7. **Documents are not a channel** — they are artifacts carried by one
8. **Speech acts create two facts** — what was said, and what was claimed
9. **Raw media retained permanently**; extraction is re-runnable
10. **Extraction proposes, never acts**; and never runs on the request path
11. **Importance is computed and explainable**, never a stored flag

Items 4 and 8 are the ones that matter most.

**Item 4** because a deleted communication is a hole in the business record precisely where disputes concentrate. **Item 8** because a system that cannot tell *"they said they'd pay Friday"* from *"they will pay Friday"* will report optimism as forecast — and will do so consistently, in one direction, which is the worst kind of wrong.
