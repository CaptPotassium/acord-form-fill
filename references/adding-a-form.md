# Adding a form

Supporting a new form is a mapping exercise, not an engineering one. No Python
changes. Budget 20–40 minutes for a typical ACORD section or carrier
supplemental.

## 1. Get the blank PDF

It must be a fillable AcroForm. Licensed ACORD blanks come from ACORD or the
agency management system; carrier supplementals come from the carrier's agent
portal. Drop it in `assets/forms/`.

Real ACORD forms are copyrighted and licensed. Do not commit them to a shared
repo — keep them in the deployment's own forms directory.

## 2. Dump the fields

```bash
python scripts/dump_fields.py assets/forms/<form>.pdf \
  --form-id <form_id> --out assets/mappings/<form_id>.stub.yaml
```

This lists every field with its type, page, tooltip label, and checkbox on-states,
and groups indexed fields into repeater candidates.

If it reports no fields, the PDF is flattened or scanned. Stop — that form needs
a different fill strategy and should be scoped separately.

## 3. Fill in the paths

Rename the stub to `<form_id>.yaml` and replace every `path: TODO` with a dotted
path from `canonical-schema.md`.

```yaml
NamedInsured_FEINOrSocSecNumber_A:
  path: applicant.fein
  transform: fein
  validate: fein
  required: true
```

Delete fields you are not mapping. Anything left unmapped is reported as a gap
rather than silently ignored, which is the behaviour you want — but a form with
forty unmapped signature and office-use fields produces a noisy report.

**Checkboxes** need a `when:` condition:

```yaml
NamedInsured_LegalEntity_Corporation_A:
  path: applicant.entity_type
  when: {equals: Corporation}
```

Supported conditions: `equals`, `in`, `contains` (for arrays), `is_true`,
`is_false`. Without `when:`, the box ticks on any truthy value.

**Repeating sections** consolidate the stub's candidates into one group per array:

```yaml
repeaters:
  premises:
    path: premises
    indices: [1, 2, 3]
    fields:
      'Premises_MailingAddress_LineOne_{i}': {item_path: address.street}
      'Premises_MailingAddress_CityName_{i}': {item_path: address.city}
```

`indices` are whatever actually appears in the field names -- digits (`1, 2, 3`)
or letters (`A, B, C`). Real packets mix both: the ACORD 125 pages here use
infix digits (`ACORD_Location1_Street`) while the ACORD 126 pages use ACORD's
own trailing letters (`GeneralLiability_Hazard_ClassCode_A`). `dump_fields.py`
detects all three shapes and only treats a template as repeating when two or
more indices exist, so ordinary single-instance fields ending in `_A` are not
mistaken for a group. Overflow is flagged automatically.

**Composite fields** collapse several canonical values into one box, which real
forms do constantly -- ACORD 125 puts the named insured's name and full mailing
address in a single field. Use `template:` instead of `path:`:

```yaml
ACORD_Policy_Insured1_MailingAddress:
  required: true
  template: "{applicant.mailing_address.street}\n{applicant.mailing_address.city}, {applicant.mailing_address.state} {applicant.mailing_address.zip}"
```

If the target field is not multiline, the newline is replaced with a comma and
the substitution is noted in the review report. Confidence for a composite is
the worst confidence among its parts, since it is only as trustworthy as its
weakest component.

## 4. Mark required fields honestly

`required: true` promotes a missing value to a blocker. Reserve it for fields
that genuinely cause a carrier to return the submission. Over-marking trains
reviewers to ignore the blocker list, which is worse than not having one.

Marking a field required that no document can supply is correct when the field
genuinely is required — the general information questions on ACORD 125 are the
canonical example. The blocker is telling the user to make a phone call.

`required: true` also changes failure behaviour. If a required field's value
fails validation, it is left blank rather than written, because a blank required
field reads as obviously incomplete while a malformed one reads as data and can
survive a hurried review. Optional fields keep the value so the reviewer can see
what was found and correct it.

## 5. Available transforms and validators

| Transform | Effect |
|---|---|
| `fein` | `061583427` → `06-1583427` |
| `phone` | `2035550148` → `(203) 555-0148` |
| `date` | Parses common formats → `MM/DD/YYYY` |
| `currency` | `14750000` → `$14,750,000` |
| `number` | Strips formatting, drops trailing `.0` |
| `percent` | `25` → `25%` |
| `zip`, `upper`, `title`, `yesno`, `str` | As named |

| Validator | Checks |
|---|---|
| `fein`, `date`, `zip`, `state`, `naics`, `email`, `phone`, `currency`, `nonempty` | Format after transform |

A failed validator on a `required` field is a blocker; otherwise a review item.
Add new transforms in the `TRANSFORMS` dict in `fill_form.py` — that is the only
situation where a new form touches Python.

## 6. Test it

```bash
python scripts/fill_form.py --account samples/account.json \
  --mapping assets/mappings/<form_id>.yaml --outdir output
```

Then actually open the PDF. A field can be populated in the file and invisible on
screen if the field name is wrong, so confirm visually before calling it done:

```bash
pdftoppm -png -r 90 output/<form_id>_filled.pdf /tmp/check
```

Check the review report too. A suspiciously clean report usually means fields are
unmapped rather than correct.

## Carrier supplementals

Same process. They are typically shorter than ACORD sections and reuse the
applicant block, so most of the mapping is paths you have already written. Where
a supplemental asks for something the schema does not model — liquor receipts,
vehicle schedules, hotel room counts — add the paths to the canonical schema
first, then map to them. Extending the schema is additive and does not affect
existing forms.
