#!/usr/bin/env python3
"""
Fill any AcroForm PDF from a canonical account JSON plus a form mapping YAML.

Design note
-----------
Nothing in this file calls a language model. Extraction (messy documents ->
canonical JSON) is the model's job because it requires judgement. Writing values
into a form is deterministic and auditable, so it lives here. Every value that
lands in the PDF is traceable to a mapping rule and a source document, and every
value that did NOT land is reported rather than silently dropped. That split is
what makes the output defensible to a producer who has to sign the application.

Usage:
    python scripts/fill_form.py \
        --account samples/account.json \
        --mapping assets/mappings/acord_125.yaml \
        --forms-dir assets/forms \
        --outdir output
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Any

import yaml
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject, TextStringObject

# ---------------------------------------------------------------------------
# Transforms: canonical value -> string as the carrier expects it on the form
# ---------------------------------------------------------------------------

def _digits(v: Any) -> str:
    return re.sub(r"\D", "", str(v))


def t_fein(v: Any) -> str:
    d = _digits(v)
    return f"{d[:2]}-{d[2:]}" if len(d) == 9 else str(v)


def t_phone(v: Any) -> str:
    d = _digits(v)
    if len(d) == 10:
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    if len(d) == 11 and d[0] == "1":
        return f"({d[1:4]}) {d[4:7]}-{d[7:]}"
    return str(v)


def t_date(v: Any) -> str:
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%d %b %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return s


def t_currency(v: Any) -> str:
    try:
        n = float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return str(v)
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def t_number(v: Any) -> str:
    try:
        n = float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return str(v)
    return str(int(n)) if n == int(n) else str(n)


def t_percent(v: Any) -> str:
    s = t_number(v)
    return f"{s}%" if s and not s.endswith("%") else s


TRANSFORMS = {
    "fein": t_fein, "phone": t_phone, "date": t_date, "currency": t_currency,
    "number": t_number, "percent": t_percent,
    "upper": lambda v: str(v).upper(), "title": lambda v: str(v).title(),
    "zip": lambda v: _digits(v)[:5] if len(_digits(v)) >= 5 else str(v),
    "yesno": lambda v: "Yes" if bool(v) else "No",
    "str": lambda v: str(v),
}

# ---------------------------------------------------------------------------
# Validators: catch the errors that cause carrier kickbacks
# ---------------------------------------------------------------------------

VALIDATORS = {
    "fein": (lambda s: bool(re.fullmatch(r"\d{2}-\d{7}", s)), "expected FEIN format 12-3456789"),
    "date": (lambda s: bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", s)), "expected date format MM/DD/YYYY"),
    "zip": (lambda s: bool(re.fullmatch(r"\d{5}(-\d{4})?", s)), "expected 5 or 9 digit ZIP"),
    "state": (lambda s: bool(re.fullmatch(r"[A-Z]{2}", s)), "expected 2-letter state code"),
    "naics": (lambda s: bool(re.fullmatch(r"\d{2,6}", s)), "expected 2-6 digit NAICS code"),
    "email": (lambda s: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", s)), "expected an email address"),
    "phone": (lambda s: bool(re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", s)), "expected phone format (203) 555-0100"),
    "currency": (lambda s: bool(re.fullmatch(r"\$[\d,]+(\.\d{2})?", s)), "expected a currency amount"),
    "nonempty": (lambda s: bool(s.strip()), "value is blank"),
}

# ---------------------------------------------------------------------------
# Canonical account access
# ---------------------------------------------------------------------------

MISSING = object()


def resolve(obj: Any, path: str) -> Any:
    """Resolve a dotted path. Supports numeric segments for list indexing."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return MISSING
        if isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                return MISSING
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                return MISSING
            cur = cur[part]
        else:
            return MISSING
    return MISSING if cur is None or cur == "" else cur


def evaluate_when(value: Any, when: dict) -> bool | None:
    """Decide whether a checkbox should be ticked. None = unknown, leave blank."""
    if value is MISSING:
        return None
    if "equals" in when:
        return str(value).strip().lower() == str(when["equals"]).strip().lower()
    if "contains" in when:
        target = str(when["contains"]).strip().lower()
        seq = value if isinstance(value, list) else [value]
        return any(target == str(x).strip().lower() for x in seq)
    if "is_true" in when:
        return bool(value) is bool(when["is_true"])
    if "is_false" in when:
        return bool(value) is not bool(when["is_false"])
    if "in" in when:
        return str(value).strip().lower() in [str(x).strip().lower() for x in when["in"]]
    return None

# ---------------------------------------------------------------------------
# PDF form introspection
# ---------------------------------------------------------------------------

MULTILINE_FLAG = 1 << 12


def field_types_and_states(reader: PdfReader) -> tuple[dict[str, str], dict[str, str], set[str]]:
    fields = reader.get_fields() or {}
    types = {k: str(v.get("/FT", "/Tx")) for k, v in fields.items()}
    # A single-line text field silently shows only the first line of a
    # multi-line value. Knowing which fields are multiline lets us flatten
    # instead of losing data -- and say so in the review report.
    multiline = {k for k, v in fields.items()
                 if int(v.get("/Ff", 0) or 0) & MULTILINE_FLAG}
    states: dict[str, str] = {}
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            try:
                obj = annot.get_object()
            except Exception:
                continue
            t = obj.get("/T")
            ap = obj.get("/AP")
            if t is None or not ap or "/N" not in ap:
                continue
            try:
                keys = [str(k) for k in ap["/N"].get_object().keys()]
            except Exception:
                continue
            on = [k for k in keys if k != "/Off"]
            if on:
                states[str(t)] = on[0]
    return types, states, multiline

# ---------------------------------------------------------------------------
# Fill planning
# ---------------------------------------------------------------------------

class Plan:
    def __init__(self) -> None:
        self.text: dict[str, str] = {}
        self.checks: dict[str, bool] = {}
        self.filled: list[dict] = []
        self.review: list[dict] = []

    def flag(self, severity: str, field: str, path: str | None, reason: str, detail: str = "") -> None:
        self.review.append({"severity": severity, "field": field, "path": path,
                            "reason": reason, "detail": detail})


TEMPLATE_PATH = re.compile(r"\{([a-zA-Z0-9_.]+)\}")

CONF_RANK = {"high": 0, "medium": 1, "low": 2, "unknown": 3}


def render_template(account: dict, prov: dict, tpl: str) -> tuple[str, dict, list[str]]:
    """Render a composite field like '{a.b}\\n{a.c}, {a.d}'.

    Real forms often collapse several canonical values into one box -- ACORD 125
    puts the named insured's name and full mailing address in a single field.
    Returns the rendered text, merged provenance (worst confidence wins, since a
    composite is only as trustworthy as its weakest part) and any missing paths.
    """
    missing: list[str] = []
    sources: list[str] = []
    worst = "high"

    def sub(m: re.Match) -> str:
        path = m.group(1)
        val = resolve(account, path)
        if val is MISSING:
            missing.append(path)
            return ""
        meta = prov.get(path, {})
        if (src := meta.get("source")) and src not in sources:
            sources.append(src)
        nonlocal worst
        conf = str(meta.get("confidence", "unknown")).lower()
        if CONF_RANK.get(conf, 3) > CONF_RANK.get(worst, 3):
            worst = conf
        return str(val)

    text = TEMPLATE_PATH.sub(sub, tpl)
    # Collapse blank lines and stray separators left by missing parts.
    lines = [ln.strip(" ,") for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln).strip()
    return text, {"source": ", ".join(sources) or None, "page": None, "confidence": worst}, missing


def apply_rule(plan: Plan, account: dict, prov: dict, field: str, rule: dict,
               ftype: str, path_override: str | None = None,
               multiline: bool = False) -> None:
    # Composite fields resolve several paths into one box.
    if rule.get("template") and ftype != "/Btn":
        value, meta, missing = render_template(account, prov, rule["template"])
        if "\n" in value and not multiline:
            value = ", ".join(ln for ln in value.split("\n") if ln)
            plan.flag("info", field, None, "flattened_composite",
                      "field is single-line, so the composite was joined with commas")
        if not value:
            sev = "blocker" if rule.get("required") else "info"
            plan.flag(sev, field, None, "missing_required" if rule.get("required") else "missing_optional",
                      f"none of the source paths resolved: {', '.join(missing)}")
            return
        if missing and rule.get("required"):
            plan.flag("review", field, None, "partial_composite",
                      f"rendered without: {', '.join(missing)}")
        plan.text[field] = value
        plan.filled.append({"field": field, "path": "(composite)", "value": value.replace("\n", " / "),
                            "source": meta["source"], "page": None,
                            "confidence": meta["confidence"]})
        if meta["confidence"] == "low":
            plan.flag("review", field, None, "low_confidence",
                      "composite includes a low-confidence value")
        return

    path = path_override or rule.get("path")
    if not path or path == "TODO":
        plan.flag("info", field, path, "unmapped_field",
                  "no canonical path assigned; value must be entered by hand")
        return

    raw = resolve(account, path)
    meta = prov.get(path, {})
    confidence = str(meta.get("confidence", "unknown")).lower()

    # --- checkbox -------------------------------------------------------
    if ftype == "/Btn":
        when = rule.get("when")
        if when is None:
            decision = bool(raw) if raw is not MISSING else None
        else:
            decision = evaluate_when(raw, when)
        if decision is None:
            if rule.get("required"):
                plan.flag("blocker", field, path, "missing_required",
                          "required checkbox could not be determined from the source documents")
            else:
                plan.flag("review", field, path, "undetermined_checkbox",
                          "left unticked because the source documents did not answer it")
            return
        plan.checks[field] = decision
        if decision:
            plan.filled.append({"field": field, "path": path, "value": "[X]",
                                "source": meta.get("source"), "page": meta.get("page"),
                                "confidence": confidence})
            if confidence == "low":
                plan.flag("review", field, path, "low_confidence",
                          f"ticked from a low-confidence value ({meta.get('source', 'unknown source')})")
        return

    # --- text -----------------------------------------------------------
    if raw is MISSING:
        if rule.get("required"):
            plan.flag("blocker", field, path, "missing_required",
                      "required by the carrier; submission will likely be returned without it")
        else:
            plan.flag("info", field, path, "missing_optional", "not found in the source documents")
        return

    fn = TRANSFORMS.get(rule.get("transform", "str"), TRANSFORMS["str"])
    try:
        value = fn(raw)
    except Exception as exc:  # transform should never take down a run
        value = str(raw)
        plan.flag("review", field, path, "transform_failed", f"{exc}; wrote the raw value")

    if (maxlen := rule.get("max_length")) and len(value) > maxlen:
        plan.flag("review", field, path, "truncated",
                  f"value was {len(value)} chars, form field holds {maxlen}")
        value = value[:maxlen]

    failed = False
    for name in ([rule["validate"]] if isinstance(rule.get("validate"), str) else rule.get("validate", [])):
        check, msg = VALIDATORS.get(name, (lambda s: True, ""))
        if not check(value):
            failed = True
            plan.flag("blocker" if rule.get("required") else "review", field, path,
                      "validation_failed", f"{msg}; got {value!r}")

    # A malformed value in a required field is more dangerous than a blank one:
    # a blank reads as obviously incomplete, while "sometime in July" in a date
    # field reads as data and can survive a hurried review all the way to the
    # carrier. Leave required fields blank when validation fails; keep optional
    # ones so the reviewer can see and correct what was found.
    if failed and rule.get("required"):
        plan.flag("info", field, path, "suppressed",
                  "left blank because the extracted value failed validation")
        return

    plan.text[field] = value
    plan.filled.append({"field": field, "path": path, "value": value,
                        "source": meta.get("source"), "page": meta.get("page"),
                        "confidence": confidence})
    if confidence == "low":
        plan.flag("review", field, path, "low_confidence",
                  f"extracted with low confidence from {meta.get('source', 'unknown source')}")


def build_plan(account: dict, prov: dict, conflicts: list, mapping: dict,
               types: dict[str, str], multiline: set[str] | None = None) -> Plan:
    multiline = multiline or set()
    plan = Plan()

    for field, rule in (mapping.get("fields") or {}).items():
        rule = rule or {}
        if field not in types:
            plan.flag("review", field, rule.get("path"), "field_not_in_pdf",
                      "mapping references a field that does not exist in this PDF edition")
            continue
        apply_rule(plan, account, prov, field, rule, types[field],
                   multiline=field in multiline)

    for group, spec in (mapping.get("repeaters") or {}).items():
        arr = resolve(account, spec.get("path", ""))
        arr = arr if isinstance(arr, list) else []
        indices = spec.get("indices") or list(range(1, len(arr) + 1))
        if len(arr) > len(indices):
            plan.flag("review", group, spec.get("path"), "overflow",
                      f"{len(arr)} items but the form holds {len(indices)}; "
                      f"{len(arr) - len(indices)} must go on an attached schedule")
        for slot, idx in enumerate(indices):
            if slot >= len(arr):
                break
            for template, sub in (spec.get("fields") or {}).items():
                field = template.replace("{i}", str(idx))
                if field not in types:
                    plan.flag("review", field, None, "field_not_in_pdf",
                              "repeater target missing from this PDF edition")
                    continue
                full_path = f"{spec['path']}.{slot}.{sub['item_path']}"
                apply_rule(plan, account, prov, field, sub, types[field],
                           path_override=full_path, multiline=field in multiline)

    for c in conflicts or []:
        plan.flag("review", c.get("path", "?"), c.get("path"), "source_conflict",
                  c.get("detail", "sources disagree on this value"))

    mapped = set((mapping.get("fields") or {}).keys())
    for group, spec in (mapping.get("repeaters") or {}).items():
        for template in (spec.get("fields") or {}):
            for idx in spec.get("indices") or []:
                mapped.add(template.replace("{i}", str(idx)))
    for field in types:
        if field not in mapped:
            plan.flag("info", field, None, "unmapped_field",
                      "present on the form but not mapped to the canonical schema")
    return plan

def count_metrics(plan: Plan, account: dict, mapping: dict, form_field_count: int) -> dict:
    """Count what the tool did, separating three things people conflate.

    MAPPED is every field this mapping knows how to fill.

    APPLICABLE is mapped minus rows that cannot apply to this account. The form
    holds four premises rows; an account with two locations has 28 fields in
    rows three and four with nothing to put in them. Counting those as misses
    penalises the tool for the account being smaller than the form.

    RESOLVED is values written PLUS checkboxes deliberately left unticked. An
    applicant is one entity type, so ticking "Corporation" means correctly
    leaving LLC, Partnership, S-Corp and four others blank. Those are decisions,
    not gaps -- but only the tick lands in plan.filled, so a naive count treats
    seven correct answers as seven failures.

    CAVEAT, and it is a real one: "applicable" is a judgement about what should
    count, and a vendor choosing its own denominator is how benchmarks get
    gamed. Both numbers are reported so a customer can pick, and the review
    report says the definition needs confirming. See metrics_caveat().
    """
    mapped = len(mapping.get("fields") or {}) + sum(
        len(sp.get("fields") or {}) * len(sp.get("indices") or [])
        for sp in (mapping.get("repeaters") or {}).values())

    # Rows the form offers that this account has no data for.
    inapplicable = 0
    row_detail = []
    for group, spec in (mapping.get("repeaters") or {}).items():
        arr = resolve(account, spec.get("path", ""))
        have = len(arr) if isinstance(arr, list) else 0
        slots = len(spec.get("indices") or [])
        per_row = len(spec.get("fields") or {})
        unused = max(0, slots - have) * per_row
        if unused:
            inapplicable += unused
            row_detail.append({"group": group, "form_rows": slots,
                               "account_rows": have, "fields_per_row": per_row,
                               "inapplicable_fields": unused})

    applicable = max(0, mapped - inapplicable)
    written = len(plan.filled)
    decided_blank = sum(1 for v in plan.checks.values() if not v)
    resolved = written + decided_blank

    return {
        "form_fields": form_field_count,
        "mapped_fields": mapped,
        "inapplicable_fields": inapplicable,
        "inapplicable_detail": row_detail,
        "applicable_fields": applicable,
        "written": written,
        "decided_blank": decided_blank,
        "resolved": resolved,
        # The conservative headline: values written / every mapped field.
        "filled": written,
        "fill_rate": round(100 * written / mapped, 1) if mapped else 0.0,
        # The one that reflects what the tool actually settled.
        "resolution_rate": round(100 * resolved / applicable, 1) if applicable else 0.0,
        "blockers": sum(1 for r in plan.review if r["severity"] == "blocker"),
        "reviews": sum(1 for r in plan.review if r["severity"] == "review"),
    }


def metrics_caveat(m: dict) -> str:
    """The sentence a customer has to agree with before the number means anything."""
    return (
        f"Two rates are reported because the denominator is a business decision, "
        f"not a technical one.\n\n"
        f"- **Fill rate {m['fill_rate']}%** ({m['written']} of {m['mapped_fields']} mapped "
        f"fields) is the conservative reading. It counts every field this mapping "
        f"knows about, including {m['inapplicable_fields']} in repeating rows this "
        f"account cannot use and every checkbox correctly left unticked.\n"
        f"- **Resolution rate {m['resolution_rate']}%** ({m['resolved']} of "
        f"{m['applicable_fields']} applicable fields) counts what the tool actually "
        f"settled: {m['written']} values written plus {m['decided_blank']} checkboxes "
        f"deliberately left blank, measured against only the fields that can apply.\n\n"
        f"ACTION REQUIRED: confirm with the customer which definition they want to "
        f"be measured on before either number goes in a pilot report. A vendor "
        f"picking its own denominator is how these numbers stop meaning anything. "
        f"If they have an existing benchmark, match its definition instead of both "
        f"of these."
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_pdf(src: str, dest: str, plan: Plan, states: dict[str, str]) -> None:
    reader = PdfReader(src)
    writer = PdfWriter()
    writer.append(reader)

    # NeedAppearances tells the viewer to render field values it did not generate
    # appearance streams for. Without it, filled values are present in the file
    # but invisible in most viewers -- a classic silent failure.
    root = writer._root_object
    if "/AcroForm" not in root:
        root[NameObject("/AcroForm")] = writer._add_object({})
    root["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    values: dict[str, Any] = dict(plan.text)
    for field, on in plan.checks.items():
        values[field] = states.get(field, "/Yes") if on else "/Off"

    for page in writer.pages:
        try:
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
        except Exception:
            continue

    # Belt and braces: stamp text values directly onto widget /V, and drop the
    # appearance stream pypdf generated for them. Two reasons. First, those
    # streams escape literal parentheses, so "(203) 555-0900" renders as
    # "\(203\) 555-0900". Second, they bake in a fixed font size and overflow
    # narrow boxes. The form's own default appearance is "/Helv 0 Tf", where 0
    # means auto-size, so letting the viewer regenerate from NeedAppearances
    # produces correctly fitted text. Checkbox appearances are left alone --
    # those carry the actual tick glyph and must survive.
    for page in writer.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            t = obj.get("/T")
            if t is not None and str(t) in plan.text:
                obj[NameObject("/V")] = TextStringObject(plan.text[str(t)])
                obj.pop(NameObject("/AP"), None)

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as fh:
        writer.write(fh)


SEV_ORDER = {"blocker": 0, "review": 1, "info": 2}
SEV_LABEL = {"blocker": "BLOCKER", "review": "REVIEW", "info": "INFO"}


def review_markdown(plan: Plan, mapping: dict, account: dict, metrics: dict) -> str:
    name = resolve(account, "applicant.named_insured")
    name = name if name is not MISSING else "(named insured not found)"
    form = mapping.get("form", {})
    out = [
        f"# Review report — {form.get('title', form.get('id', 'form'))}",
        "",
        f"**Account:** {name}  ",
        f"**Form:** {form.get('id')} ({form.get('edition', 'edition unknown')})  ",
        f"**Generated:** {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Fillable fields on form | {metrics['form_fields']} |",
        f"| Mapped to canonical schema | {metrics['mapped_fields']} |",
        f"| Not applicable to this account | {metrics['inapplicable_fields']} |",
        f"| Applicable fields | {metrics['applicable_fields']} |",
        f"| Values written | {metrics['written']} |",
        f"| Checkboxes correctly left blank | {metrics['decided_blank']} |",
        f"| Resolved (written + decided) | {metrics['resolved']} |",
        f"| **Fill rate** (written / mapped) | **{metrics['fill_rate']}%** |",
        f"| **Resolution rate** (resolved / applicable) | **{metrics['resolution_rate']}%** |",
        f"| Blockers | {metrics['blockers']} |",
        f"| Needs review | {metrics['reviews']} |",
        "",
    ]
    if metrics.get("inapplicable_detail"):
        out += ["Rows the form offers that this account cannot use:", ""]
        out += ["| Section | Form rows | This account | Fields excluded |",
                "|---|---|---|---|"]
        out += [f"| {d['group']} | {d['form_rows']} | {d['account_rows']} | "
                f"{d['inapplicable_fields']} |" for d in metrics["inapplicable_detail"]]
        out += [""]
    out += ["### Which number to report", "", metrics_caveat(metrics), ""]
    blockers = [r for r in plan.review if r["severity"] == "blocker"]
    reviews = [r for r in plan.review if r["severity"] == "review"]

    out += ["## Must fix before submission", ""]
    if blockers:
        out += ["| Field | Canonical path | Problem |", "|---|---|---|"]
        out += [f"| `{r['field']}` | `{r['path']}` | {r['reason']}: {r['detail']} |" for r in blockers]
    else:
        out.append("None. Every required field was filled and passed validation.")
    out.append("")

    out += ["## Confirm with the insured", ""]
    if reviews:
        out += ["| Field | Canonical path | Why flagged |", "|---|---|---|"]
        out += [f"| `{r['field']}` | `{r['path']}` | {r['reason']}: {r['detail']} |" for r in reviews]
    else:
        out.append("Nothing flagged.")
    out.append("")

    out += ["## Provenance of filled values", "",
            "| Field | Value | Source | Page | Confidence |", "|---|---|---|---|---|"]
    for f in plan.filled:
        out.append(f"| `{f['field']}` | {f['value']} | {f.get('source') or '—'} | "
                   f"{f.get('page') or '—'} | {f['confidence']} |")
    out.append("")
    out.append("_Every value above is traceable to a source document. Values that could "
               "not be traced were left blank and listed as blockers rather than guessed._")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", required=True)
    ap.add_argument("--mapping", required=True, action="append",
                    help="form mapping YAML; repeat to fill several sections of one packet")
    ap.add_argument("--forms-dir", default="assets/forms")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--pdf", help="override the blank PDF named in the mapping")
    ap.add_argument("--out-name", default="submission_packet_filled.pdf",
                    help="filename for the filled packet inside --outdir")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if any blocker exists")
    a = ap.parse_args()

    with open(a.account, encoding="utf-8") as fh:
        doc = json.load(fh)
    account = doc.get("account", doc)
    prov = doc.get("provenance", {})
    conflicts = doc.get("conflicts", [])

    mappings = []
    for path in a.mapping:
        with open(path, encoding="utf-8") as fh:
            mappings.append(yaml.safe_load(fh))

    # Several form sections often live in one PDF packet -- a broker submits
    # ACORD 125 + 126 stapled together. Each mapping owns its own fields, so
    # they fill into one shared document and each gets its own review report.
    blanks = {m["form"]["pdf"] for m in mappings}
    if a.pdf:
        blank = a.pdf
    elif len(blanks) == 1:
        blank = os.path.join(a.forms_dir, blanks.pop())
    else:
        sys.exit(f"Mappings reference different PDFs ({sorted(blanks)}); "
                 "run them separately or pass --pdf.")
    if not os.path.exists(blank):
        sys.exit(f"Blank form not found: {blank}\n"
                 "Run scripts/make_sample_forms.py, or drop the licensed ACORD PDF in place.")

    reader = PdfReader(blank)
    types, states, multiline = field_types_and_states(reader)
    os.makedirs(a.outdir, exist_ok=True)

    combined = Plan()
    any_blockers = False
    for mapping in mappings:
        plan = build_plan(account, prov, conflicts, mapping, types, multiline)
        metrics = count_metrics(plan, account, mapping, len(types))
        mapped = metrics["mapped_fields"]
        any_blockers = any_blockers or bool(metrics["blockers"])

        form_id = mapping["form"]["id"]
        plan.review.sort(key=lambda r: (SEV_ORDER.get(r["severity"], 9), r["field"]))
        with open(os.path.join(a.outdir, f"{form_id}_review.json"), "w", encoding="utf-8") as fh:
            json.dump({"form": mapping["form"], "metrics": metrics,
                       "filled": plan.filled, "review_queue": plan.review}, fh, indent=2)
        with open(os.path.join(a.outdir, f"{form_id}_review.md"), "w", encoding="utf-8") as fh:
            fh.write(review_markdown(plan, mapping, account, metrics))

        combined.text.update(plan.text)
        combined.checks.update(plan.checks)
        combined.filled.extend(plan.filled)

        print(f"{form_id}:")
        print(f"  fill rate ........ {metrics['written']}/{metrics['mapped_fields']} "
              f"mapped fields ({metrics['fill_rate']}%)")
        print(f"  resolution rate .. {metrics['resolved']}/{metrics['applicable_fields']} "
              f"applicable fields ({metrics['resolution_rate']}%)"
              f"   [{metrics['written']} written + {metrics['decided_blank']} "
              f"correctly left blank]")
        if metrics["inapplicable_fields"]:
            bits = ", ".join(f"{d['group']} {d['account_rows']}/{d['form_rows']} rows"
                             for d in metrics["inapplicable_detail"])
            print(f"  excluded ......... {metrics['inapplicable_fields']} fields in "
                  f"unusable repeating rows ({bits})")
        print(f"  blockers={metrics['blockers']}  review={metrics['reviews']}")
        print(f"  -> {os.path.join(a.outdir, form_id + '_review.md')}")
        print(f"  ! confirm which rate the customer wants to be measured on "
              f"(see {form_id}_review.md)")

    pdf_out = os.path.join(a.outdir, a.out_name)
    write_pdf(blank, pdf_out, combined, states)
    print(f"packet: {len(combined.filled)} fields written -> {pdf_out}")
    if a.strict and any_blockers:
        sys.exit(1)


if __name__ == "__main__":
    main()
