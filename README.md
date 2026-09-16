# acord-form-fill

A Claude Skill that ingests account artifacts — declarations pages, loss runs,
AMS exports — and produces a filled ACORD submission packet with a field-level
review report.

Built as a Sales Engineer take-home for Cooper AI.

```bash
pip install -r requirements.txt
./run_demo.sh
```

---

## What it does

```
dec page ─┐                              ┌─ ACORD 125  →┐
AMS CSV  ─┼─► canonical account JSON ─►──┼─ ACORD 126  →┼─► filled packet
loss run ─┘   (extract once)             └─ next form  →┘   + review report
```

Current run against the real ACORD 125/126/140 packet (2016 editions):

| Section | Mapped | Auto-filled | Fill rate | Blockers | Review |
|---|---|---|---|---|---|
| ACORD 125 | 148 | 80 | 54% | 5 | 18 |
| ACORD 126 | 53 | 31 | 58% | 0 | 3 |

**Two numbers matter, not one.** *Coverage* is 201 of the packet's 924 fields —
the sections sourceable from account documents. The other 723 are carrier and
underwriter blocks, additional interests, contact grids, state fraud notices,
signatures and office-use fields that no extraction should touch. *Fill rate* is
how much of what we mapped actually got filled. A single blended percentage
would understate the tool badly.

The 5 blockers on ACORD 125 are the general information questions — prior
cancellation, bankruptcy, judgements, foreign operations, safety program. No
declarations page or AMS export answers those, ever. Flagging them is the tool
telling a CSR to make a phone call.

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
├── scripts/
│   ├── dump_fields.py            # PDF → mapping stub (new-form onboarding)
│   ├── fill_form.py              # canonical + mappings → packet + review reports
│   └── make_sample_forms.py      # generates the sample input documents
├── references/
│   ├── canonical-schema.md       # the schema extraction targets
│   ├── extraction-guide.md       # confidence rubric, source precedence
│   └── adding-a-form.md          # how to onboard form N+1
├── assets/
│   ├── forms/acord_submission_packet.pdf
│   └── mappings/{acord_125,acord_126}.yaml
└── samples/                      # dec page, loss run, AMS CSV, account.json
```

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

**Built:** canonical schema, extraction contract with provenance and confidence,
field dumper with three repeat-pattern shapes, mapping-driven fill engine with
transforms and validators, composite fields, repeating sections with overflow
detection, conflict surfacing, field-level review reports with metrics, two
complete form mappings against the real blank.

| Cut | Why | Cost to add |
|---|---|---|
| ACORD 140 (property) | In the packet and mappable, but needs construction, protection and valuation modelling to be worth anything | Schema extension + mapping, ~1 day |
| ACORD 130 (workers comp) | Class codes, multi-state payroll, experience mod — real domain modelling | ~1 day |
| Carrier supplementals | Same pattern, different YAML. Breadth would not prove anything the second ACORD section didn't | ~30 min each once the schema covers the line |
| OCR for scanned inputs | Different engineering problem; assumed digital-native PDFs | Meaningful — needs an OCR stage and confidence recalibration |
| Live AMS integration | CSV export stands in; the adapter is config, not code | Days, mostly vendor API work |
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
- **Not used:** the fill engine, transforms and validators are hand-written.
  That code is the audit boundary and has to be inspectable line by line.

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
5. **Ingestion from Outlook and SharePoint**, where dec pages actually live.

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
