# Discovery Doc — Mid-Market Commercial Brokerage Pilot

**Context:** I did not get the 30-minute discovery call, so this documents the call I would have run, the answers I needed, and the specific assumption I substituted for each in order to ship an MVP. Every assumption below is baked into the skill I built. Where an assumption is wrong, I've noted what breaks and how expensive the fix is.

**On the numbers in section 1:** the volume, timing and hourly-rate figures are
*illustrative*. I had no call, so I picked plausible mid-market values to make the
ROI arithmetic concrete rather than hand-waving at it. They are the first thing
I would replace with real figures, and the model is built so that replacing them
changes the business case without changing a line of code. Everywhere else in
this document, an assumption is either grounded in the sample data or has since
been measured -- and where it has been measured, the result is recorded.

---

## How I'd run the 30 minutes

| Time | Segment | Goal |
|---|---|---|
| 0–3 min | Frame + confirm who's in the room | Get a producer *and* a CSR on the call. They describe the same workflow differently, and the CSR is the one who actually does the re-keying. |
| 3–15 min | Walk one real submission end to end | Screen-share a live account. Not "describe your process" — "open the last submission you sent and show me every window you touched." |
| 15–22 min | Forms, volume, and data sources | Narrow to the highest-volume forms and confirm where the data actually lives. |
| 22–27 min | Trust, review, and delivery | Who signs, what error rate is tolerable, where the filled form goes next. |
| 27–30 min | Success criteria + next step | Agree on the number that makes this pilot a yes, and book the follow-up. |

The single most valuable question is the screen-share. Self-reported workflows omit the workarounds, and the workarounds are the product.

---

## 1. Current workflow and pain quantification

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| Walk me through the last submission you sent. Every window, every copy-paste. | Reveals the actual re-keying path and the shadow steps (the spreadsheet on someone's desktop, the Word template). | Assumed the sequence is: pull declarations page + prior policy from email or the AMS → open blank ACORD 125 PDF in Adobe → type applicant/premises data → open ACORD 126 → retype the applicant block → attach to email. | If they already use a partial autofill in their AMS, my baseline time savings is inflated and the pilot ROI story needs rebasing. Low build impact, high sales impact. |
| How long does a full new-business submission take, start to finish? | Anchors the savings claim in their number, not mine. | Assumed 45–90 minutes per commercial submission across 125 + 126 + one supplemental, of which 25–40 min is pure data entry. | Savings math in the pilot summary changes. No code impact. |
| Who does the re-keying — producers, CSRs, or an offshore team? | Determines the loaded hourly rate for ROI and who the actual end user is. | Assumed CSRs/account managers do ~80% of it at a fully loaded ~$40/hr; producers do the rest. | Changes ROI framing and UI expectations (a CSR tolerates a review queue; a producer wants it done). No code impact. |
| How many submissions per week, and what's the new-business vs. renewal split? | Renewals are the easier, higher-volume win — prior-year data makes fill accuracy much higher. | Assumed ~40 submissions/week, roughly 70% renewal / 30% new business. | If it's mostly new business, prior-policy extraction is less useful and I'd weight AMS + declarations page extraction more heavily. Moderate impact on extraction priorities. |
| What percentage of a form can you fill from what you already have, versus needing to go back to the client? | Sets the ceiling on automation. If 40% of fields always require a client call, "fully automated" was never the goal. | Assumed ~70% of ACORD 125/126 fields are derivable from the declarations page + AMS export; the remainder (loss history detail, operations narrative, subcontractor spend) needs client input. | This is the assumption I'm least comfortable with. If the real number is 45%, the product is a *review-and-complete* tool, not a fill tool — and the demo narrative changes more than the code does. **Since measured, and the discomfort was justified.** On the Applied Epic export path: 74.3% of *applicable* fields resolved, but only 43.0% of *mapped* fields written. Both of the scenarios I described above are true at once, depending on the denominator — which is why the tool now reports both rates and asks the customer to pick which one the pilot is measured on. |

## 2. Data sources and systems

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| Which AMS, which version, and who administers it? | Determines integration path and whether an API exists. | Originally assumed **AMS360 (Vertafore)**. **Revised during the build:** I targeted **Applied Epic** instead, and the reason mattered more than the choice. Epic's export is driven by a mapping file each agency configures, so there is no fixed schema to code against. That turned the column layout into configuration rather than code — see `assets/ams/applied_epic.yaml`. | Either way it is now a config file, not an adapter. Supporting AMS360 as well means copying that YAML and renaming the columns against one real export. The original estimate of half a day per AMS was wrong in the right direction. |
| Can you export an account to CSV today, and what columns come out? | The AMS export is the highest-quality structured input available. I need the real column names. | Originally assumed one flat 14-column export. **Revised:** built against five related files — client, policy, locations, claims and classifications — joined on a client lookup code, because that is the shape an agency-management system actually exports (one file per area, not one flat table). See `samples/ams/`. | Column names and filenames almost certainly differ per agency. Mitigated by design: both live in `assets/ams/applied_epic.yaml`, so a new customer is a config edit. The synthetic CSVs are modelled on the shape of an Epic export; the exact column names are invented and would be replaced by one real export. |
| Is the AMS record trustworthy, or is the declarations page the source of truth? | Brokerages routinely have stale AMS data. This decides my conflict-resolution rule. | Assumed a source precedence of: **current declarations page > prior policy > AMS export**, on the theory that the carrier-issued document is authoritative and the AMS drifts. Conflicts are surfaced, not silently resolved. | If the AMS is actually cleanest, I flip the precedence order — one line in the config. |
| Where do declarations pages and policies actually live — Outlook, SharePoint, the AMS, a shared drive? | Determines ingestion surface for a real deployment. | Assumed for the MVP that a user uploads files manually. Assumed for production that Outlook attachments + a SharePoint folder are the two real sources. | No MVP impact. Significant deployment impact — worth a dedicated question on call two. |
| Are your incoming documents digital PDFs or scans? | OCR is a different engineering problem and I deliberately didn't build it. | Assumed digitally generated, text-extractable PDFs. Carrier declarations pages usually are; broker-forwarded faxes often aren't. | If a meaningful share are scans, I need an OCR stage before extraction. This is a known, explicitly scoped gap. |

## 3. Forms, lines, and carriers

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| Which five forms consume the most hours? | Sequences the roadmap by pain, not by what's easy to build. | Assumed **ACORD 125 and ACORD 126** are the highest-volume pair, since 125 is common to every commercial submission and GL is the most-written line in a mid-market book. | If they're a trucking or contractor shop, 130 / RT Specialty Trucking / Hartford Contractors' Supplemental would outrank them. The architecture handles this — each new form is a mapping file, not new code — but the demo would lead with a different form. |
| What lines dominate the book — GL, property, WC, auto, umbrella? | Line mix determines which supplements matter and which fields the canonical schema must cover. | Assumed a general commercial book weighted to GL and property, with WC secondary. Built the canonical schema to cover applicant, premises, GL coverage, and prior-carrier blocks. | Schema gaps for lines I didn't model (e.g. WC class codes and state-by-state payroll). Additive fix — the schema is extensible by design. |
| Which carriers and wholesalers do you submit to most? | Carrier supplements are where the real time sinks are; ACORDs are only the common denominator. | Assumed a long tail of carriers with no single dominant market, so I built the common ACORD layer first and left supplements as a documented extension point with a stub mapping. | If 60% of volume goes to two carriers, I'd have built one of their supplements instead of ACORD 126 — higher demonstrated value, same effort. |
| Do you use ACORD forms as-is, or a modified agency version? | Custom forms break field-name assumptions. | Assumed standard, current-edition ACORD fillable PDFs with unmodified AcroForm field names. | Custom forms need a re-dump of field names and a new mapping file. ~20 minutes per form, which is exactly the scaling claim I'm making. |

## 4. Data quality and edge cases

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| How often is an account multi-entity, multi-location, or multi-state? | Repeating sections are the hardest part of ACORD fill and the most common source of silent errors. | Assumed single named insured with a handful of premises; built premises as an array and mapped the **four** location rows ACORD 125 actually prints, plus three prior-carrier rows and three loss rows. Overflow beyond those is flagged for an attached schedule rather than dropped. | Accounts with 20 locations need an SOV attachment path and overflow handling. Known limitation, documented. |
| What do you do today when a field is missing? | Reveals whether they guess, leave blank, or call the client — which sets the bar for my review queue. | Assumed they leave it blank and circle back, so my review report mirrors that habit: list what's missing rather than inventing a value. | If they have standard defaults ("assume $1M/$2M unless told otherwise"), I'd encode those defaults and cut the review queue significantly. |
| Do you ever have conflicting data across documents? | Determines whether conflict surfacing is a feature or noise. | Assumed yes and treated it as a first-class output — a conflict on FEIN or effective date appears in the review report with both values and their sources. | If conflicts are rare, this is over-engineering. I'd keep it anyway; the cost is low and the trust payoff is high. |

## 5. Trust, review, and E&O

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| Who signs the completed application, and what's their tolerance for an error? | An ACORD application carries E&O exposure. This determines whether the product is auto-fill or assisted-fill. | Assumed a licensed producer signs and will not accept a black-box fill. Built every extracted value to carry `{value, source_file, page, confidence}` so any field can be traced to its origin. | This is the assumption I'd bet the most on being right. If wrong, the provenance layer is wasted effort — but it's the thing that makes the product deployable, so I'd keep it. |
| Would a CSR review every field, or only flagged ones? | Determines whether we're saving 80% of the time or 95%. | Assumed field-level review of flagged items only, with spot-checks on the rest, once trust is established. Assumed full review during the pilot. | Changes the savings claim, not the build. |
| What error rate would kill this internally? | Gets a hard number for the accuracy conversation instead of hand-waving. | Assumed that a wrong value written silently is far worse than a blank field, so the system biases toward flagging over guessing. | If they'd rather have a fast best-guess, I'd loosen the confidence threshold — a config value. |
| Any restrictions on sending client data to a third-party model? | Real blocker in insurance; better surfaced on call one than at procurement. | Assumed no hard blocker for a pilot, and that PII/FEIN handling gets a security review before production. | Could require on-prem or a BAA-equivalent arrangement. Doesn't change the MVP; changes the deployment plan. |

## 6. Delivery and handoff

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| Where does the filled form go next — email to an underwriter, a wholesaler, or a carrier portal? | The form is an intermediate artifact. The end state is a submitted application. | Assumed the MVP output is a filled PDF on disk that the user attaches to an existing email workflow. | Portal entry is the bigger prize and the natural phase two. No MVP impact. |
| Does the completed form or extracted data need to write back to the AMS? | Write-back doubles the value and doubles the integration work. | Assumed no write-back in the pilot. | Out of MVP scope regardless. |
| Who would be the first 3–5 trial users, and are they willing? | A pilot with unwilling users fails regardless of product quality. | Assumed 3 CSRs and 1 producer on a named book of business, with an internal champion in ops. | Deployment plan changes, not the build. |

## 7. Pilot success criteria

| Question | Why I'd ask | Assumption I made to build | What breaks if I'm wrong |
|---|---|---|---|
| What number makes this a yes at the end of the pilot? | Without a pre-agreed metric the pilot ends in opinion. | Assumed the metric is **minutes per submission**, measured before and after, with a target of 50%+ reduction on ACORD 125/126. | If the real metric is submission volume or hit ratio, I'd instrument differently — measuring forms-per-week rather than minutes-per-form. |
| How do you measure that today? | Most brokerages don't, which means I need to establish the baseline myself in week one. | Assumed no existing time tracking, so the pilot plan includes a manual baseline: 10 timed submissions before rollout. | Adds a week to the pilot if I'm wrong about their instrumentation. |
| Who signs the expansion contract, and what do they care about? | Identifies the economic buyer early. | Assumed the COO or Director of Operations owns the decision and cares about headcount leverage — handling more submissions without adding CSRs. | Standard qualification risk. |

---

## If I only had 10 minutes

1. Screen-share the last submission you sent.
2. Which five forms eat the most hours?
3. What percentage of a form can you fill from documents you already have?
4. Who signs it, and what happens if a field is wrong?
5. What number makes this a yes in 90 days?

---

## Consolidated assumption ledger

| # | Assumption | Confidence | Cost if wrong |
|---|---|---|---|
| A1 | Applied Epic, exporting related CSVs per area (client/policy/locations/claims/classifications) | Medium — the shape is right, the exact column names are invented | Low — column names and filenames are both config in `assets/ams/applied_epic.yaml` |
| A2 | ACORD 125 + 126 are the highest-volume forms | Medium | Low — new mapping file, ~20 min per form |
| A3 | Standard, current-edition ACORD fillable PDFs | High | Low — re-dump field names |
| A4 | Digital, text-extractable PDFs (no scans) | Medium | **High** — requires an OCR stage |
| A5 | ~70% of fields derivable from available documents | **Measured** (Applied Epic export path): 74.3% of applicable fields resolved, 43.0% of mapped fields written | **Resolved into a reporting decision, not a risk** — the tool reports both rates and asks the customer which one the pilot is measured on |
| A6 | Dec page outranks AMS as source of truth | Medium | Low — reorder precedence config |
| A7 | Producer signs and requires traceability | High | Low — provenance layer already built |
| A8 | Single named insured, ≤4 premises (the number of rows the form prints) | Medium | Medium — more than four needs an attached schedule; overflow is already flagged |
| A9 | Success measured in minutes per submission | Medium | Low — instrumentation change |

A5 has since been measured, and the answer was *both* — which is why the metric now ships with a question attached rather than a single number. That leaves **A4** as the assumption I would validate first: if a meaningful share of their incoming documents are scans rather than digital PDFs, an OCR stage has to come before anything else works. The AMS export path is unaffected by it, which is a further argument for leading a pilot with the export rather than with documents.

---

## Questions I deliberately deferred to call two

Data retention, SSO, audit logging, multi-tenant permissions, and the security review. All of them matter for production and none of them change what I would have built for a pilot. Asking them in the first 30 minutes would have cost me the screen-share, which was the most valuable thing on the agenda.
