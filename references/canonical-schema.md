# Canonical account schema

One record per account. Every form mapping points into these paths. Extend it by
adding paths — never by renaming existing ones, since mappings reference them by
name and a rename silently breaks every form at once.

Omit any field you cannot source. Absent is a valid state and is reported
honestly; a guess is not.

## Contents

- [Structure](#structure)
- [Field reference](#field-reference)
- [Enumerated values](#enumerated-values)
- [Provenance block](#provenance-block)

## Structure

```json
{
  "account": {
    "form_meta":  { "completion_date": "06/02/2026" },
    "producer":   { "agency_name": "...", "producer_code": "...", "agency_customer_id": "...",
                    "contact_name": "...", "phone": "...", "email": "..." },
    "applicant":  { "named_insured": "...", "dba": "...", "fein": "...",
                    "entity_type": "Corporation", "website": "...", "business_phone": "...",
                    "mailing_address": { "street": "...", "city": "...", "state": "CT",
                                         "zip": "06902", "county": "..." } },
    "business":   { "naics": "238220", "sic": "1711", "years_in_business": 18,
                    "date_business_started": "04/12/2008",
                    "nature_of_business": ["Contractor", "Service"],
                    "annual_revenue": 14750000, "full_time_employees": 62,
                    "part_time_employees": 8, "operations_description": "..." },
    "policy":     { "effective_date": "07/01/2026", "expiration_date": "07/01/2027",
                    "transaction_type": "Renew", "policy_number": "...",
                    "lines_requested": ["General Liability"],
                    "billing_plan": "Agency Bill", "payment_plan": "Annual" },
    "premises":   [ { "location_number": 1,
                      "address": { "street": "...", "city": "...", "state": "CT",
                                   "zip": "...", "county": "..." },
                      "interest": "Tenant", "total_building_area": 12000,
                      "occupied_area": 12000, "annual_revenue": null,
                      "full_time_employees": 24, "part_time_employees": 3,
                      "description_of_operations": "..." } ],
    "prior_carriers": [ { "year": "2025", "carrier_name": "...", "policy_number": "...",
                          "annual_premium": 47850, "effective_date": "...",
                          "expiration_date": "...", "line": "General Liability" } ],
    "general_liability": {
      "commercial_general_liability": true,
      "coverage_trigger": "Occurrence",
      "aggregate_applies_per": "Project",
      "limits": { "each_occurrence": 1000000, "damage_to_rented_premises": 100000,
                  "medical_expense": 10000, "personal_and_advertising_injury": 1000000,
                  "general_aggregate": 2000000,
                  "products_completed_operations_aggregate": 2000000,
                  "employee_benefits": null },
      "deductible": { "applies_to_property_damage": true, "property_damage_amount": 5000,
                      "applies_to_bodily_injury": true, "bodily_injury_amount": 5000,
                      "basis": "Per Occurrence" },
      "premiums": { "premises_operations": null, "products": null, "total": null },
      "classifications": [ { "location_number": 1, "description": "...", "class_code": "98482",
                             "premium_basis": "Payroll", "premium_basis_code": "P",
                             "territory": null, "exposure": 2850000 } ],
      "contractors": { "subcontracted_work_percent": 25,
                       "subcontractor_annual_cost": 900000,
                       "work_subcontracted_description": "..." },
      "employee_benefits": { "employee_count": 70 }
    },
    "losses": [ { "date_of_occurrence": "03/14/2024", "date_of_claim": "03/20/2024",
                  "claim_number": "...", "line": "GL", "description": "...",
                  "amount_paid": 18400, "amount_reserved": 0,
                  "claim_open": false, "subrogation": false } ],
    "loss_summary": { "years_covered": 3, "total_incurred": 74050 },
    "general_information": { "prior_cancellation": false, "bankruptcy": false,
                             "judgement_or_lien": false, "safety_program": true,
                             "foreign_operations": false, "is_subsidiary": false,
                             "flammables_exposure": false, "operates_drones": false }
  },
  "provenance": { "applicant.fein": { "source": "dec_page.pdf", "page": 1, "confidence": "high" } },
  "conflicts":  [ { "path": "policy.effective_date", "detail": "...", "values": [] } ]
}
```

## Field reference

Store numbers as numbers and dates as `MM/DD/YYYY` strings. Formatting for the
form is the mapping's job via `transform:` — do not pre-format currency or
phone numbers during extraction, or transforms will double-apply.

| Path | Type | Notes |
|---|---|---|
| `applicant.named_insured` | string | Full legal name including the entity suffix. Not the DBA. |
| `applicant.fein` | string | Digits or `12-3456789`; the `fein` transform normalises it. |
| `applicant.entity_type` | enum | See below. Drives the legal-entity checkboxes. |
| `business.naics` | string | Keep as a string — leading zeros matter. |
| `business.annual_revenue` | number | Whole dollars, unformatted. |
| `policy.lines_requested` | array | Drives the line-of-business checkboxes. |
| `premises[].interest` | enum | `Owner` or `Tenant`. |
| `general_liability.limits.*` | number | Whole dollars, unformatted. |
| `general_liability.classifications[]` | array | One row per class code. |
| `losses[]` | array | Newest first is conventional but not required. |
| `general_information.*` | boolean | True/false only. Absent means unanswered, which is the honest default — no document answers these. |
| `losses[].claim_open` | boolean | Rendered as Yes/No by the `yesno` transform. |
| `general_liability.classifications[].premium_basis_code` | string | The form's single-letter code: P payroll, S sales, A area, C cost, U unit, M admissions. |

## Enumerated values

Use these spellings exactly — mappings match on them.

- **entity_type**: `Corporation`, `LLC`, `Partnership`, `Individual`, `S-Corp`,
  `Joint Venture`, `Non-Profit`
- **premises interest**: `Owner`, `Tenant`
- **coverage_trigger**: `Occurrence`, `Claims Made`
- **aggregate_applies_per**: `Policy`, `Project`, `Location`
- **premium_basis**: `Payroll`, `Sales`, `Area`, `Units`, `Admissions`, `Cost`
  (forms usually want the single-letter code; keep both, store the word in
  `premium_basis` and the letter in `premium_basis_code`)
- **transaction_type**: `Quote`, `Issue Policy`, `Renew`, `Change`, `Cancel`
- **nature_of_business**: `Contractor`, `Service`, `Manufacturing`, `Retail`,
  `Wholesale`, `Office`, `Restaurant`, `Apartments`, `Condominiums`,
  `Institutional` (an array — a plumbing contractor is both Contractor and Service)
- **lines_requested**: `General Liability`, `Property`, `Business Auto`,
  `Workers Compensation`, `Umbrella`, `Crime`, `Inland Marine`

If a source uses different wording ("Corp.", "an S corporation"), normalise to
the enum and lower the confidence to `medium` with a note recording the original
wording.

## Provenance block

Keyed by the same dotted path as the value, including array indices
(`premises.0.address.street`).

```json
"applicant.mailing_address.county": {
  "source": "dec_page.pdf",
  "page": 1,
  "confidence": "medium",
  "note": "appeared in parentheses after the city line rather than a labelled field"
}
```

`source` is the filename, or `assumed_default` when a value came from a standing
assumption rather than a document. Any `assumed_default` value should carry
`confidence: "low"` so it surfaces for review.
