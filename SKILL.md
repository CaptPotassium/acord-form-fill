---
name: acord-form-fill
description: Fill ACORD forms and carrier applications from account documents. Use this skill whenever the user uploads or mentions insurance account artifacts — declarations pages, dec pages, policies, quotes, loss runs, binders, AMS or agency-management-system exports — and wants a form, application, or submission produced. Trigger on any mention of ACORD, ACORD 125, ACORD 126, ACORD 130, commercial insurance applications, carrier supplementals, submission prep, or re-keying account data into forms, even if the user does not name a specific form number. Also use when asked to extract structured account data from insurance documents, or to check which fields on an application can be auto-filled and which still need the insured.
---

# ACORD form fill

Turn messy account artifacts into a filled, reviewable insurance application.

## The core idea

Do not map documents to forms directly. That approach costs one integration per
document-type × form-type pair and collapses the moment a new carrier supplemental
arrives. Instead route everything through one canonical account record:

```
dec page ─┐                              ┌─ ACORD 125
AMS CSV  ─┼─► canonical account JSON ─►──┼─ ACORD 126
loss run ─┘   (extract once)             └─ carrier supplemental
```

Adding an input type costs one extractor. Adding a form costs one YAML mapping
file and no code. The applicant block on ACORD 126 draws from the same canonical
paths as ACORD 125, so the second form is nearly free.

## Division of labour

**You extract. The script fills.** Reading a declarations page and deciding that
"Form of Business: Corporation" means `applicant.entity_type = "Corporation"`
requires judgement, so that is your job. Writing a value into a PDF field is
deterministic and auditable, so `scripts/fill_form.py` does it.

Never write values into the PDF yourself and never edit the filled PDF by hand.
A producer signs this application and carries E&O exposure on it. Every value in
the output must be traceable to a mapping rule and a source document, and that
guarantee only holds if the fill path stays deterministic.

## Workflow

### 1. Inventory the inputs

List what was provided and what each artifact is (declarations page, loss run,
AMS export, prior application, SOV). If the user has not said which form they
want, ask — but note that ACORD 125 is the common applicant section behind nearly
every commercial submission and is usually the right default.

Check `assets/mappings/` for available forms. Each `.yaml` there is a supported
form. If the user wants a form that has no mapping yet, read
`references/adding-a-form.md`.

### 2. Extract into the canonical account

Read `references/canonical-schema.md` for the field paths and
`references/extraction-guide.md` for the provenance and confidence rules.

Write `account.json` with three top-level keys:

- `account` — the values themselves
- `provenance` — keyed by the same dotted paths, recording source, page, and confidence
- `conflicts` — where sources disagree, with both values and which one you used

Record provenance for **every** value you extract. A value with no provenance
entry is reported as untraceable, which defeats the purpose of the tool.

Leave a field out entirely rather than guessing. A blank field costs a phone
call; a confidently wrong field costs a denied claim. This is the single most
important rule in the skill.

### 3. Fill each requested form

```bash
python scripts/fill_form.py \
  --account account.json \
  --mapping assets/mappings/acord_125.yaml \
  --mapping assets/mappings/acord_126.yaml \
  --forms-dir assets/forms \
  --outdir output
```

Pass `--mapping` once per form section. Sections that live in one PDF packet --
ACORD 125 and 126 are stapled together in a real submission -- fill into a
single document. The script writes one filled packet plus `<form_id>_review.md`
and `<form_id>_review.json` per section.

### 4. Report back

Lead with what needs human attention, not with what worked. Use this shape:

```
Filled ACORD 125 — 61 of 148 mapped fields (41%); 148 of 924 packet fields mapped

Must fix before submission (3):
  • <field> — <why>

Confirm with the insured (7):
  • <field> — <why>

Filled PDF: output/acord_125_filled.pdf
Review report: output/acord_125_review.md
```

Report two numbers, not one. **Coverage** is how much of the form was mapped at
all; **fill rate** is how much of what was mapped got filled. A packet has
hundreds of carrier, underwriter, signature and office-use fields that no
extraction can or should touch, so a single blended percentage understates the
tool badly. Say which sections were deliberately left unmapped.

Then state where the gaps concentrate. If the general
information questions came back as blockers, say plainly that no declarations
page or AMS export answers those — they always require the insured — so the user
knows this is expected behaviour rather than a failure.

## Setup

The repo ships with generated stand-in forms and sample inputs. To regenerate:

```bash
python scripts/make_sample_forms.py --outdir assets/forms --samples samples
```

`assets/forms/acord_submission_packet.pdf` is the real ACORD 125/126/140 packet
(2016 editions, 924 fillable fields), supplied by Cooper for this exercise so the
demo runs out of the box.

Note for a real deployment: ACORD blank forms are copyrighted and licensed to
member agencies and vendors. They belong in the customer's own forms directory,
not in a vendor's repo — `--forms-dir` exists so the customer points at theirs.
To add another form, drop the blank in `assets/forms/` and follow
`references/adding-a-form.md`.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/make_sample_forms.py` | Generate ACORD-style stand-in forms and sample inputs |
| `scripts/dump_fields.py` | Enumerate a PDF's fillable fields and emit a mapping stub |
| `scripts/fill_form.py` | Canonical account + mapping → filled PDF + review report |

## References

| File | Read it when |
|---|---|
| `references/canonical-schema.md` | Extracting — gives every field path and its expected type |
| `references/extraction-guide.md` | Extracting — provenance, confidence rubric, source precedence |
| `references/adding-a-form.md` | Supporting a form that has no mapping yet |

## Things that go wrong

**A PDF has no fillable fields.** It is flattened or scanned. `dump_fields.py`
will say so. Field-name filling cannot work; the form needs coordinate-based
overlay or OCR first. Tell the user rather than producing an empty form.

**Values are in the file but invisible, garbled, or clipped.** The writer sets
`NeedAppearances`, stamps widget values directly, and deletes the appearance
streams for text fields so the viewer regenerates them. Skipping that last step
produces two silent corruptions: literal parentheses render escaped
(`\(203\) 555-0900`) and text overflows narrow boxes at a baked-in font size.
If a viewer still shows blanks, check the field names against `dump_fields.py`.

**A value shows only its first line.** The field is single-line. Composite
`template:` values are flattened with commas automatically and noted in the
report, but a long description in a single-line field will still clip.

**Sources disagree.** Do not silently pick one. Record both in `conflicts` with
the reason for your choice. Default precedence is the current declarations page
over a prior policy over the AMS export, on the theory that carrier-issued
documents are authoritative and AMS records drift — but say so explicitly, since
some agencies keep a cleaner AMS than their document trail.

**More items than the form holds.** Three premises rows, twenty locations. The
script flags overflow and fills what fits. Tell the user the remainder needs an
attached schedule.
