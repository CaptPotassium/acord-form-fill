#!/usr/bin/env python3
"""
Enumerate every fillable field in a PDF and emit a mapping stub.

This is the onboarding tool for a new form. Point it at any AcroForm PDF --
a licensed ACORD blank, a carrier supplemental, an agency-custom form -- and it
writes a YAML skeleton listing every field with its type, page, and checkbox
on-state. A human then fills in the `path:` values to connect each field to the
canonical account schema. No Python changes are required to support a new form.

Usage:
    python scripts/dump_fields.py assets/forms/acord_125_standin.pdf \
        --form-id acord_125 --out assets/mappings/acord_125.stub.yaml
    python scripts/dump_fields.py <pdf> --json      # machine-readable inventory
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from pypdf import PdfReader

TYPE_NAMES = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}

# Real forms index repeating rows in at least three ways, often within the same
# PDF because sections come from different vendors:
#   trailing digit   Premises_Street_1
#   infix digit      ACORD_Location1_Street, ACORD_LossHistory_2_AmountPaid
#   trailing letter  GeneralLiability_Hazard_ClassCode_A / _B / _C
# The trailing-letter case is ambiguous: ACORD also suffixes _A onto ordinary
# single-instance fields (Form_CompletionDate_A). So a template only counts as a
# repeater when two or more distinct indices actually exist for it.
DIGIT_RUN = re.compile(r"\d+")
TRAILING_ALPHA = re.compile(r"^(?P<base>.+_)(?P<idx>[A-Z])$")


def candidate_templates(name: str) -> list[tuple[str, str]]:
    """Return [(template, index), ...] this field could belong to."""
    out: list[tuple[str, str]] = []
    for m in DIGIT_RUN.finditer(name):
        out.append((name[: m.start()] + "{i}" + name[m.end():], m.group()))
    if (m := TRAILING_ALPHA.match(name)):
        out.append((m.group("base") + "{i}", m.group("idx")))
    return out


def detect_repeaters(names: list[str]) -> dict[str, dict[str, str]]:
    """template -> {index: field_name}, keeping only genuine repeating groups."""
    groups: dict[str, dict[str, str]] = {}
    for name in names:
        for template, idx in candidate_templates(name):
            groups.setdefault(template, {})[idx] = name
    return {t: m for t, m in groups.items() if len(m) >= 2}


def best_template(name: str, kept: dict[str, dict[str, str]]) -> tuple[str, str] | None:
    """Pick the repeating group a field belongs to, preferring the widest one."""
    best = None
    for template, idx in candidate_templates(name):
        if template in kept and kept[template].get(idx) == name:
            if best is None or len(kept[template]) > len(kept[best[0]]):
                best = (template, idx)
    return best


def page_index_map(reader: PdfReader) -> dict[str, int]:
    """Map fully-qualified field name -> 1-based page number."""
    out: dict[str, int] = {}
    for pno, page in enumerate(reader.pages, start=1):
        for annot in page.get("/Annots") or []:
            try:
                obj = annot.get_object()
            except Exception:
                continue
            name, node = None, obj
            parts: list[str] = []
            seen = 0
            while node is not None and seen < 12:
                t = node.get("/T")
                if t:
                    parts.insert(0, str(t))
                node = node.get("/Parent")
                node = node.get_object() if node is not None else None
                seen += 1
            if parts:
                name = ".".join(parts)
            if name and name not in out:
                out[name] = pno
    return out


def checkbox_states(reader: PdfReader, name: str) -> list[str]:
    """Return the 'on' state names for a checkbox (excluding /Off)."""
    states: list[str] = []
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            try:
                obj = annot.get_object()
            except Exception:
                continue
            t = obj.get("/T")
            if t is None or str(t) != name.split(".")[-1]:
                continue
            ap = obj.get("/AP")
            if ap and "/N" in ap:
                try:
                    for k in ap["/N"].get_object().keys():
                        k = str(k)
                        if k != "/Off" and k.lstrip("/") not in states:
                            states.append(k.lstrip("/"))
                except Exception:
                    pass
    return states


def inventory(pdf_path: str) -> list[dict]:
    reader = PdfReader(pdf_path)
    fields = reader.get_fields() or {}
    if not fields:
        sys.exit(
            f"No AcroForm fields found in {pdf_path}.\n"
            "This is usually a flattened or scanned PDF. Flattened forms cannot be\n"
            "filled by field name -- they need coordinate-based overlay instead."
        )
    pages = page_index_map(reader)
    kept = detect_repeaters(list(fields.keys()))
    rows: list[dict] = []
    for name, spec in fields.items():
        ft = str(spec.get("/FT", ""))
        kind = TYPE_NAMES.get(ft, ft or "unknown")
        row: dict = {
            "field": name,
            "type": kind,
            "page": pages.get(name),
            "label": str(spec.get("/TU", "")) or None,
        }
        if kind == "button":
            row["on_states"] = checkbox_states(reader, name) or ["Yes"]
        if (hit := best_template(name, kept)):
            row["repeat_template"], row["repeat_index"] = hit
        rows.append(row)
    return rows


def to_stub(rows: list[dict], form_id: str, pdf_path: str) -> str:
    repeats: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for r in rows:
        if "repeat_template" in r:
            repeats.setdefault(r["repeat_template"], []).append(r)
        else:
            singles.append(r)

    lines = [
        "# Mapping stub generated by dump_fields.py -- fill in every `path:` value.",
        "# `path` is a dotted path into the canonical account schema",
        "# (see references/canonical-schema.md). Delete fields you do not map;",
        "# unmapped fields are reported as gaps rather than silently ignored.",
        "",
        "form:",
        f"  id: {form_id}",
        f"  title: TODO",
        f"  pdf: {os.path.basename(pdf_path)}",
        "  edition: TODO",
        "",
        "fields:",
    ]
    for r in singles:
        lines.append(f"  {r['field']}:")
        lines.append("    path: TODO")
        meta = f"    # type={r['type']} page={r['page']}"
        if r.get("label"):
            meta += f" label={r['label']!r}"
        lines.append(meta)
        if r["type"] == "button":
            lines.append(f"    # on_states={r.get('on_states')}")
            lines.append("    # for checkboxes add:  when: {equals: 'SomeValue'}   or  truthy: true")

    if repeats:
        lines += [
            "",
            "# --- Repeating field templates detected -------------------------------",
            "# Consolidate related templates into named groups, each mapping ONE array",
            "# in the canonical schema onto its indexed fields. Example:",
            "#",
            "# repeaters:",
            "#   premises:",
            "#     path: premises",
            "#     indices: [1, 2, 3]",
            "#     fields:",
            "#       'Premises_MailingAddress_LineOne_{i}': {item_path: address.street}",
            "#",
            "repeater_candidates:",
        ]
        for template, items in sorted(repeats.items()):
            idxs = sorted(str(i["repeat_index"]) for i in items)
            lines.append(f"  - template: '{template}'")
            lines.append(f"    indices: {idxs}")
            lines.append(f"    type: {items[0]['type']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("--form-id", default="new_form")
    ap.add_argument("--out", help="write YAML stub here (default: stdout)")
    ap.add_argument("--json", action="store_true", help="emit raw inventory as JSON")
    a = ap.parse_args()

    rows = inventory(a.pdf)
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    stub = to_stub(rows, a.form_id, a.pdf)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(stub)
        n_rep = len({r["repeat_template"] for r in rows if "repeat_template" in r})
        print(f"{len(rows)} fields ({n_rep} repeating groups) -> {a.out}")
    else:
        print(stub)


if __name__ == "__main__":
    main()
