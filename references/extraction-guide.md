# Extraction guide

How to turn account artifacts into the canonical record without introducing
errors the reviewer cannot see.

## Read every artifact before writing anything

Fields corroborate across documents. The FEIN on a declarations page confirms
the one in the AMS export; a loss run confirms the carrier and policy number.
Extracting document by document produces contradictions you then have to
untangle. Read everything, then write once.

## Source precedence

Default order, highest first:

1. **Current declarations page** — carrier-issued and current
2. **Prior policy or binder** — carrier-issued but potentially stale
3. **AMS export** — structured and convenient, but drifts from reality
4. **Prior application** — reflects what was claimed, not what was issued

This default exists because carrier-issued documents are authoritative and AMS
records go stale. Some agencies keep the opposite discipline. When precedence
decides a value, say so in the provenance note so the reviewer can disagree.

One deliberate exception: on a **renewal**, term dates come from the AMS or the
submission request, not from the declarations page, because the dec page shows
the expiring term. Getting this backwards puts a policy period in the past,
which is the single most common extraction error on renewals.

## Confidence rubric

Three levels. Be strict — inflated confidence is worse than no confidence,
because it suppresses review of exactly the fields that need it.

**high** — the value appeared in a labelled field, verbatim, and needed no
interpretation. "Federal Employer ID: 06-1583427" → `06-1583427`.

**medium** — the value is correct but required interpretation: normalising to an
enum, parsing a combined line, inferring from context. "Stamford, CT 06902
(Fairfield County)" → `county: "Fairfield"` is medium, because the label was
positional rather than explicit.

**low** — the value is a reasonable inference that a human should confirm.
Condensed prose, a defaulted value, an assumption from standing agency practice.
Anything sourced `assumed_default` is low by definition.

Absent beats low. If you would have to invent the value, leave it out and let it
surface as a gap.

## What never comes from documents

Some fields cannot be extracted at all, and pretending otherwise wastes the
reviewer's attention. These always come from the insured:

- General information questions (prior cancellation, bankruptcy, safety program,
  foreign operations, subsidiaries)
- Subcontractor percentages and certificate requirements
- Operations narrative in the insured's own words
- Anything about intent: requested limits, desired effective date, new locations

When these come back as blockers, that is the tool working correctly. Say so
when reporting, so the user reads it as expected rather than as a miss.

Once a person answers them, record the answer with `source: "insured_confirmed"`
or `source: "csr_confirmed"` — never backfilled onto a document that does not
contain it. `samples/account.json` and `samples/account_reviewed.json` are the
same account before and after this step, and the difference between them is the
honest measure of what still needs a human.

## Conflicts

Record a conflict when two sources give different values for the same path.
Do not average, do not silently prefer. Write both values, both sources, the
one you used, and why.

```json
{
  "path": "policy.effective_date",
  "detail": "dec page shows the expiring term beginning 07/01/2025; AMS shows the renewal term beginning 07/01/2026. Used the AMS value on the assumption this is a renewal. Confirm with the account manager.",
  "values": [
    {"value": "07/01/2025", "source": "dec_page.pdf"},
    {"value": "07/01/2026", "source": "ams_export.csv"}
  ]
}
```

A near-miss is still a conflict. "Brightwater Mechanical Contractors, Inc." and
"Brightwater Mechanical Contractors Inc" differ, and on a named insured that
difference can matter to a carrier. Flag it, pick the version from the
higher-precedence source, and note it.

## Common traps

**Dec page limits are the expiring program, not the request.** They are the
right starting point for a renewal and the wrong answer if the insured asked for
different limits. Mark them `medium` and note the assumption.

**Classification schedules rarely state which location a class applies to.**
Defaulting to location 1 is reasonable; doing it silently is not. Mark `low`.

**Loss runs are valued as of a date.** Capture that date. A loss run valued eight
months ago understates development and underwriters notice.

**The named insured on a dec page may be one entity of several.** If you see
"et al", additional named insureds, or a schedule of entities, flag it rather
than dropping the others.

**Multi-state payroll and class codes are workers comp territory.** This schema
does not model them. If asked for ACORD 130, say the schema needs extending
rather than forcing values into GL paths.
