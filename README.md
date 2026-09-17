# acord-form-fill

A Claude Skill that ingests account artifacts — declarations pages, loss runs,
AMS exports — and produces a filled ACORD submission packet with a field-level
review report.

Built as a Sales Engineer take-home for Cooper AI.

```bash
pip install -r requirements.txt
./run_demo.sh            # documents-only run, then the same account after review
./run_demo.sh --sparse    # guardrail run: malformed and missing data
```

---

## What it does

```
declarations page ─┐                      ┌─ ACORD 125  →┐
AMS CSV  ─┼─► canonical account JSON ─►──┼─ ACORD 126  →┼─► filled packet
loss run ─┘   (extract once)             └─ next form  →┘   + review report
```

Current run against the real ACORD 125/126/140 packet (2016 editions, 924
fillable fields). Two runs, because the honest answer is two numbers:

Three runs, because the input and the amount of human help both change the
answer. Every figure below is printed by `run_demo.sh` — none are estimates.

**Run 1 — documents only.** Unattended, from a declarations page, a loss run and
a flat AMS export:

| Section | Mapped | Written | Fill rate | Applicable | Resolved | Resolution rate | Blockers |
|---|---|---|---|---|---|---|---|
| ACORD 125 | 149 | 61 | 40.9% | 109 | 77 | 70.6% | 5 |
| ACORD 126 | 53 | 31 | 58.5% | 47 | 35 | 74.5% | 0 |

**Run 2 — after a CSR works the review queue.** The same account once a person
has answered the five general information questions and supplied the per-location
detail no document carries:

| Section | Mapped | Written | Fill rate | Applicable | Resolved | Resolution rate | Blockers |
|---|---|---|---|---|---|---|---|
| ACORD 125 | 149 | 81 | 54.4% | 109 | 105 | 96.3% | **0** |
| ACORD 126 | 53 | 31 | 58.5% | 47 | 35 | 74.5% | 0 |

**Run 3 — from an Applied Epic CSV export instead of documents.** The realistic
pilot input, and it beats the document path with roughly half the review burden,
because structured data does not need interpreting:

| Section | Mapped | Written | Fill rate | Applicable | Resolved | Resolution rate | Blockers |
|---|---|---|---|---|---|---|---|
| ACORD 125 | 149 | 64 | 43.0% | 109 | 81 | 74.3% | 5 |
| ACORD 126 | 53 | 32 | 60.4% | 47 | 36 | 76.6% | 0 |

*Reproduce run 3 with:*
```bash
python3 scripts/ingest_ams.py --export-dir samples/ams --mapping assets/ams/applied_epic.yaml --out samples/account_from_ams.json
python3 scripts/fill_form.py --account samples/account_from_ams.json --mapping assets/mappings/acord_125.yaml --mapping assets/mappings/acord_126.yaml --forms-dir assets/forms --outdir output_ams
```

The unattended rate is the number that matters for a pilot, because it is the work that
happens without anybody's attention. The gap to the post-review rate is the human-in-the-loop
cost, and it is small and bounded — five phone-call questions and a premises
breakdown, not a re-key of the whole application. `samples/account.json` is the
run-1 state and is extracted from the sample documents; `samples/account_reviewed.json`
is the run-2 state, where every value a person supplied is sourced
`csr_confirmed` or `insured_confirmed` rather than to a document.

**Two numbers matter, not one.** *Coverage* is 202 of the packet's 924 fields —
the sections sourceable from account documents. The other 722 are carrier and
underwriter blocks, additional interests, contact grids, state fraud notices,
signatures and office-use fields that no extraction should touch. *Fill rate* is
how much of what we mapped actually got filled. A single blended percentage
would understate the tool badly.

The 5 run-1 blockers on ACORD 125 are the general information questions — prior
cancellation, bankruptcy, judgements, foreign operations, safety program. No
declarations page or AMS export answers those, ever. Flagging them is the tool
telling a CSR to make a phone call.

## Discovery questions and assumptions

I did not get the 30-minute discovery call, so this is the call I would have run.
Each question below changed something specific in the build — the right-hand
column says what. `DISCOVERY.md` holds the full version: seven sections, a
timed agenda, and a consolidated assumption ledger with a cost-if-wrong estimate
against each item.

The questions are ordered by how much the answer would change the code.

| # | Question I'd ask | Assumption I built on | What it touches in the code |
|---|---|---|---|
| 1 | **Which agency management system do you use?** | Applied Epic. | `assets/ams/applied_epic.yaml` is the whole answer. A different system is a copy of that file, not new code. |
| 2 | **Can you send me two or three real exports, so I can see what you keep and how?** | Five related CSVs — client, policy, locations, claims, classifications — joined on a client lookup code. | Every column name in `assets/ams/applied_epic.yaml`. **This is the highest-value question on the call.** Epic's export is driven by a mapping file each agency configures, so there is no standard schema to assume. One real export replaces a day of guessing. |
| 3 | **Which fields must be exactly right, which just need a look, and which don't matter?** | FEIN, policy dates and state codes must be exact; contact details and descriptions need a glance; office-use fields don't matter. | The `validate:` and `required:` keys in the form mappings. Three levels: no `validate` writes silently; `validate` alone writes it and flags it for review; `validate` plus `required` leaves the box empty and blocks the submission. That choice is per field, set by what a wrong value costs. |
| 4 | **Which one or two forms eat the most hours?** | ACORD 125 and 126 — 125 is common to every commercial submission, and general liability is the most-written line in a mid-market book. | Which mappings exist in `assets/mappings/`. One YAML per form, so a different answer reorders the roadmap without changing the engine. |
| 5 | **When your system holds both the expiring policy and the renewal, which term should the application show?** | The renewal. The expiring term is recorded as prior-carrier history instead. | `select: where: {PolicyStatus: Renewal Requested}` in the Epic mapping. Getting this backwards puts a policy period in the past, which is the most common error on a renewal submission — so the choice is recorded as a conflict with both values, not made silently. |
| 6 | **When your system and a carrier document disagree, which one wins?** | The carrier document, on the theory that it is issued and the system record drifts — with one exception: on a renewal, term dates come from the system, because the declarations page shows the term about to expire. | Source precedence in `references/extraction-guide.md`, and the `conflicts` block in the account record. If their system is the cleaner record, the precedence flips — that is a documentation change, not a code change. |
| 7 | **What's a typical account — how many locations, how many class codes?** | Two to four locations, two class codes. | The `indices:` lists on each repeating section, and the metric. The form prints four location rows; an account with two leaves 28 fields that cannot apply, and counting those as misses would penalise the tool for the account being smaller than the form. This question is why the report separates *applicable* fields from *mapped* fields. |
| 8 | **Are your incoming documents digital, or scanned and faxed?** | Digital and text-extractable. | Nothing — and that is the risk. No OCR stage exists. If a meaningful share are scans, that has to be built before the document path works at all. The AMS export path is unaffected, which is an argument for leading a pilot with the export. |
| 9 | **What do you do today when a field is missing — leave it blank, or apply a house default?** | Leave it blank and circle back. | The review report lists what is missing rather than inventing a value. If they have standing defaults ("$1M/$2M unless told otherwise"), those become config and the review queue shrinks. |
| 10 | **Who signs the finished application, and what happens if a field is wrong?** | A licensed producer signs it and carries errors-and-omissions exposure, so they will not accept a fill they cannot audit. | The provenance layer. Every value carries source file, page and confidence, and the review report can trace any field back to the column or document it came from. |
| 11 | **Which fill-rate definition do you want the pilot measured on?** | None — I deliberately did not decide this. | `count_metrics()` reports both a fill rate and a resolution rate, and every review report carries an `ACTION REQUIRED` asking for this confirmation. A vendor picking its own denominator is how these numbers stop meaning anything; if they already have a benchmark, its definition wins over both of mine. |

**The one I would not trade.** Question 2. Everything else can be answered
approximately and corrected later. Without one real export I am guessing at
column names, and every guess is a field that silently fails to fill.

**The numbers in `DISCOVERY.md` section 1 are illustrative.** Volume,
minutes-per-submission and loaded hourly rate are plausible mid-market figures
chosen to make the ROI arithmetic concrete, not researched benchmarks. They are
the first thing I would replace, and replacing them changes the business case
without changing any code.

**One assumption has since been measured.** I guessed that ~70% of ACORD 125/126
fields would be derivable from available data, and flagged that if the real
number were nearer 45% this would be a review-and-complete tool rather than a
fill tool. Measured on the Applied Epic export path: 74.3% of applicable fields
resolved, 43.0% of mapped fields written. Both scenarios turned out to be true at once, depending on the
denominator — which is exactly why question 11 exists and why the metric ships
with a question attached instead of a single number.

## Architecture

**One canonical account record in the middle.** Mapping documents to forms
directly costs one integration per document-type × form-type pair. Routing
through a canonical schema makes it additive: one extractor per input type, one
YAML mapping per form. ACORD 126's header reads the same canonical paths as
ACORD 125, so the second section cost about fifteen minutes.

**Claude extracts, Python fills.** Reading a declarations page and deciding that
"Form of Business: Corporation" means `applicant.entity_type = "Corporation"`
needs judgement. Writing that into a PDF field does not. The model never touches
the PDF, so every value traces to a mapping rule and a source document. Errors
are attributable to the extraction (visible in `account.json`) or the mapping
(visible in the YAML) — never to an opaque generation step.

**Field names get dumped, never guessed.** `dump_fields.py` enumerates any
AcroForm PDF and emits a mapping stub. Onboarding a new form becomes filling in
paths — 20–40 minutes of work a non-engineer can do, with no Python changes.

**Provenance on every field.** Each value carries source file, page and
confidence. The review report lists what was filled and from where, what failed
validation, what conflicted across sources, and what needs the insured. A
producer signs this application and carries E&O exposure on it, so a silent fill
is not deployable.

```
acord-form-fill/
├── SKILL.md                      # workflow Claude follows
├── DISCOVERY.md                  # discovery questions + assumption ledger
├── run_demo.sh                   # two-state demo; --sparse for the guardrail run
├── scripts/
│   ├── ingest_ams.py             # AMS CSV export → canonical record (no model)
│   ├── dump_fields.py            # PDF → mapping stub (new-form onboarding)
│   ├── fill_form.py              # canonical + mappings → packet + review reports
│   └── make_sample_forms.py      # generates the sample input documents
├── references/
│   ├── canonical-schema.md       # the schema extraction targets
│   ├── extraction-guide.md       # confidence rubric, source precedence
│   ├── adding-a-form.md          # how to onboard form N+1
│   └── packet-field-inventory.txt # all 924 packet fields by page, type, checkbox state
├── assets/
│   ├── forms/acord_submission_packet.pdf
│   ├── mappings/{acord_125,acord_126}.yaml      # one per FORM   (output side)
│   └── ams/applied_epic.yaml                    # one per AMS    (input side)
└── samples/
    ├── ams/                      # five related CSVs: client, policy,
    │                             #   locations, claims, classifications
    ├── declarations_page.pdf, loss_runs.pdf, ams_export.csv
    ├── account.json              # documents only  (run 1)
    ├── account_reviewed.json     # after CSR review (run 2)
    ├── account_from_ams.json     # built from the Epic CSV export
    └── account_sparse.json       # malformed + missing data, for the guardrail run
```

Two mapping layers, both configuration: `assets/ams/` absorbs a customer's
column names, `assets/mappings/` absorbs a form's field names. The Python
between them never changes for either.

## What the real form taught the code

I built first against generated stand-in forms, then swapped in the real
licensed blank. It broke three things a synthetic form never would have, and all
three are the silent-failure class — wrong output that still looks like output.

**Repeater detection was too narrow.** I handled trailing digits
(`Premises_Street_1`). The real packet also uses infix digits
(`ACORD_Location1_Street`) and trailing letters
(`GeneralLiability_Hazard_ClassCode_A`). The letter case is ambiguous because
ACORD also suffixes `_A` onto ordinary single-instance fields, so a template now
only counts as repeating when two or more indices actually exist.

**The two sections use different naming conventions in the same PDF.** Pages 1–4
use vendor naming (`ACORD_*`), pages 5–8 use ACORD's own
`Subject_Attribute_Suffix` scheme. Checkbox on-states differ too: `On` in one
section, `1` in the other. This is the argument for mappings being data rather
than logic.

**Appearance streams corrupted output.** pypdf generates its own appearance
streams, which escaped literal parentheses — `(203) 555-0900` rendered as
`\(203\) 555-0900` — and baked in a font size that clipped text mid-word. The
form's own default appearance is `/Helv 0 Tf`, where 0 means auto-size, so the
fix is deleting those streams for text fields and letting `NeedAppearances` do
the work. Found by rasterizing the output, not by counting fields.

**A composite address silently lost a line.** ACORD 125 collapses name and full
mailing address into one box, so it needed a new `template:` mapping type. That
field turns out not to be multiline, so the newline dropped the city/state/zip
silently. The engine now reads the multiline flag, joins with commas when it
must, and says so in the report.

## What I built vs. cut

**Built:** canonical schema; extraction contract with provenance and confidence;
a deterministic AMS-export reader driven by a per-customer column mapping; field
dumper with three repeat-pattern shapes; mapping-driven fill engine with
transforms and validators; composite fields; repeating sections with overflow
detection; conflict surfacing; field-level review reports carrying both a fill
rate and a resolution rate plus an explicit request to confirm which one a
pilot is measured on; two complete form mappings against the real blank.

| Cut | Why | Cost to add |
|---|---|---|
| ACORD 140 (property) | In the packet and mappable, but needs construction, protection and valuation modelling to be worth anything | Schema extension + mapping, ~1 day |
| ACORD 130 (workers comp) | Class codes, multi-state payroll, experience mod — real domain modelling | ~1 day |
| Carrier supplementals | Same pattern, different YAML. Breadth would not prove anything the second ACORD section didn't | ~30 min each once the schema covers the line |
| OCR for scanned inputs | Different engineering problem; assumed digital-native PDFs | Meaningful — needs an OCR stage and confidence recalibration |
| Live AMS API integration | The CSV export path is built and is the realistic pilot input anyway; a live API removes the manual export step, not the mapping work | Days, mostly vendor API work |
| AMS write-back, portal submission | The real phase-two prize, out of MVP scope | Weeks |
| Web UI | Functional beats pretty; CLI plus review report demos the same thing | — |

## Where I used AI

- **Mapping generation.** Dumped the 924 field names, had Claude draft path
  assignments from names and tooltips, then reviewed each by hand. This is the
  workflow that makes new-form onboarding fast, and the same one a deployment
  engineer would use at a customer.
- **Synthetic test data.** The declarations page, loss run and AMS export are
  generated — a consistent contractor account with plausible GL class codes and
  a loss history matching the operations.
- **Extraction itself.** This is the product, not a build shortcut.
  `references/extraction-guide.md` is the prompt contract.
- **Not used, in the fill engine.** Transforms and validators are hand-written.
  That code is the audit boundary and has to be inspectable line by line.
- **Not used, on the AMS export path, and that was the more interesting call.**
  A CSV already has named columns, so turning `LimitEachOccurrence` into
  `general_liability.limits.each_occurrence` needs a lookup table, not
  judgement. A model there would add cost and latency for nothing, and would
  make the result unreproducible — the same export could yield different records
  on different runs. The rule: **structured input gets a column mapping,
  unstructured input gets the model.** Both write the same canonical record, and
  provenance says which path a value came from.

## What I'd build next

1. **Accuracy instrumentation.** Every reviewer correction is a labelled error.
   Log them and the review queue becomes a measurement instrument. The number
   that matters is the *silent error rate* — wrong and not flagged — because a
   flagged error costs thirty seconds and an unflagged one costs a claim. Fill
   rate is the sales metric, silent error rate is the engineering metric, and
   they trade against each other through the confidence threshold. That dial
   should belong to the customer.
2. **ACORD 140**, since it is already in this packet and property is the second
   most common line in a mid-market book.
3. **One carrier supplemental**, to prove extensibility against a non-ACORD form.
4. **OCR stage**, gated on how many real inputs turn out to be scans.
5. **Ingestion from Outlook and SharePoint**, where declarations pages actually live.

## Notes

Blank ACORD forms are copyrighted by ACORD and licensed to member agencies and
vendors. The blank in `assets/forms/` was provided for this exercise. In a real
deployment, forms live in the customer's own licensed forms directory rather
than the vendor's repo — `references/adding-a-form.md` covers pointing the
mappings at them.

The skill makes no network calls. Extraction runs on documents that arrive from
carriers and third parties, which is exactly the input class where prompt
injection matters, so a no-egress sandbox is a deliberate property rather than
an accident.

## Requirements

Python 3.10+, `pypdf`, `reportlab`, `pyyaml`. Optional: `poppler-utils` for
`pdftoppm`, to rasterize and visually verify output.
