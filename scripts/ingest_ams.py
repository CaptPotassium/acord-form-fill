#!/usr/bin/env python3
"""
Agency management system CSV export -> canonical account record.

Design note
-----------
This file calls no language model, and that is the point.

A CSV already has named columns. Turning "LimitEachOccurrence" into
general_liability.limits.each_occurrence needs a lookup table, not judgement.
Using a model here would add cost, latency and a failure mode in exchange for
nothing, and it would make the result unreproducible -- the same export could
yield different account records on different runs.

So the rule is:

    structured input   (CSV from the AMS)      -> deterministic column mapping
    unstructured input (declarations page PDF) -> the model reads it

Both write the same canonical account record, so downstream form filling does
not care which path a value came from. Provenance records which one it was.

Usage:
    python scripts/ingest_ams.py \
        --export-dir samples/ams \
        --mapping assets/ams/applied_epic.yaml \
        --out samples/account_from_ams.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Column transforms: raw CSV text -> canonical typed value
# ---------------------------------------------------------------------------

def x_number(s: str) -> float | int | None:
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    n = float(cleaned)
    return int(n) if n == int(n) else n


def x_int(s: str) -> int | None:
    n = x_number(s)
    return int(n) if n is not None else None


def x_date(s: str) -> str | None:
    s = s.strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%d-%b-%Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    # Unparseable but non-empty: hand it through unchanged. fill_form.py's
    # validators will reject it and leave the form field blank, which is the
    # behaviour we want -- a bad value should surface, not be quietly dropped.
    return s


def x_listify(s: str) -> list[str] | None:
    parts = [p.strip() for p in re.split(r"[;,|]", s) if p.strip()]
    return parts or None


def x_open_closed(s: str) -> bool | None:
    v = s.strip().lower()
    if v in {"open", "o", "reopened"}:
        return True
    if v in {"closed", "c"}:
        return False
    return None


def x_yesno_bool(s: str) -> bool | None:
    v = s.strip().lower()
    if v in {"y", "yes", "true", "1"}:
        return True
    if v in {"n", "no", "false", "0"}:
        return False
    return None  # blank means "the export does not say", not "no"


TRANSFORMS = {
    "number": x_number, "int": x_int, "date": x_date, "listify": x_listify,
    "open_closed": x_open_closed, "yesno_bool": x_yesno_bool,
    "upper": lambda s: s.strip().upper() or None,
    "str": lambda s: s.strip() or None,
}

# ---------------------------------------------------------------------------
# Canonical record assembly
# ---------------------------------------------------------------------------

def assign(target: dict, path: str, value: Any) -> None:
    """Write a value at a dotted path, creating intermediate dicts."""
    parts = path.split(".")
    cur = target
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def matches(row: dict[str, str], where: dict[str, str]) -> bool:
    return all(str(row.get(k, "")).strip().lower() == str(v).strip().lower()
               for k, v in where.items())


def select_rows(rows: list[dict], spec: dict) -> tuple[list[dict], str | None]:
    """Apply a spec's row filter. Returns the rows and any note to record."""
    sel = spec.get("select") or {}
    where = sel.get("where")
    if not where:
        return rows, None
    hits = [r for r in rows if matches(r, where)]
    if hits:
        return hits, (sel.get("note") or "").strip() or None
    if sel.get("on_no_match") == "first_row" and rows:
        return rows[:1], (f"no row matched {where}; used the first row instead")
    return [], f"no row matched {where}"


def apply_columns(row: dict[str, str], columns: dict, out: dict, prov: dict,
                  prov_prefix: str, source_file: str) -> None:
    for col, rule in columns.items():
        raw = row.get(col)
        if raw is None or str(raw).strip() == "":
            continue
        fn = TRANSFORMS.get(rule.get("transform", "str"), TRANSFORMS["str"])
        value = fn(str(raw))
        if value is None or value == "":
            continue
        assign(out, rule["path"], value)
        prov[f"{prov_prefix}{rule['path']}"] = {
            "source": source_file,
            "page": None,
            "confidence": rule.get("confidence", "high"),
            "note": f"column {col}",
        }


def ingest(export_dir: str, mapping: dict) -> tuple[dict, dict, list, list]:
    account: dict = {}
    prov: dict = {}
    conflicts: list = []
    notes: list[str] = []

    for key, spec in (mapping.get("files") or {}).items():
        filename = spec.get("file", key.split("#")[0])
        full = os.path.join(export_dir, filename)
        if not os.path.exists(full):
            notes.append(f"{filename}: not present in the export directory, skipped")
            continue
        rows = read_csv(full)
        rows, note = select_rows(rows, spec)
        if note:
            notes.append(f"{filename}: {note}")
        if not rows:
            continue

        if spec.get("mode") == "array":
            target = spec["target"]
            items: list[dict] = []
            for i, row in enumerate(rows):
                item: dict = {}
                apply_columns(row, spec["columns"], item, prov,
                              f"{target}.{i}.", filename)
                if item:
                    items.append(item)
            if items:
                assign(account, target, items)
        else:
            apply_columns(rows[0], spec["columns"], account, prov, "", filename)

    _derive(account, prov, mapping, export_dir, notes)
    _flag_renewal_term_conflict(account, export_dir, mapping, conflicts)
    return account, prov, conflicts, notes


def _resolve(obj: Any, path: str) -> Any:
    """Resolve a dotted path. A numeric segment indexes into a list."""
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return None
    return cur


def _derive(account: dict, prov: dict, mapping: dict, export_dir: str,
            notes: list[str]) -> None:
    for path, spec in (mapping.get("derive") or {}).items():
        conf = spec.get("confidence", "high")
        note = spec.get("note", "derived")

        if "constant" in spec:
            assign(account, path, spec["constant"])
            prov[path] = {"source": "derived", "page": None, "confidence": conf, "note": note}

        elif "sum_over" in spec:
            arr = _resolve(account, spec["sum_over"]) or []
            total = sum(float(item.get(f) or 0) for item in arr for f in spec["of"])
            assign(account, path, int(total) if total == int(total) else total)
            prov[path] = {"source": "derived", "page": None, "confidence": conf, "note": note}

        elif "first_of" in spec:
            full = os.path.join(export_dir, spec["first_of"])
            if not os.path.exists(full):
                continue
            rows = read_csv(full)
            if not rows:
                continue
            raw = str(rows[0].get(spec["column"], "")).strip()
            if not raw:
                continue
            fn = TRANSFORMS.get(spec.get("transform", "str"), TRANSFORMS["str"])
            assign(account, path, fn(raw))
            prov[path] = {"source": spec["first_of"], "page": None,
                          "confidence": conf, "note": note}

        elif "copy_from" in spec:
            val = _resolve(account, spec["copy_from"])
            if val not in (None, ""):
                fn = TRANSFORMS.get(spec.get("transform", "str"), TRANSFORMS["str"])
                assign(account, path, fn(str(val)) if spec.get("transform") else val)
                prov[path] = {"source": "derived", "page": None, "confidence": conf, "note": note}

        elif "span_years" in spec:
            # How many years of loss history the run covers. Underwriters ask
            # for five; saying "3" honestly is better than leaving it blank and
            # letting them assume the run is complete.
            cfg = spec["span_years"]
            arr = _resolve(account, cfg["array"]) or []
            years = set()
            for item in arr:
                d = str(item.get(cfg["field"], ""))
                m = re.search(r"/(\d{4})$", d)
                if m:
                    years.add(int(m.group(1)))
            if years:
                assign(account, path, max(years) - min(years) + 1)
                prov[path] = {"source": "derived", "page": None, "confidence": conf,
                              "note": f"{note} (claims span {min(years)}-{max(years)})"}

        elif "prefix_lookup" in spec:
            # Industry classification from the NAICS code. NAICS is a published
            # standard, so the first few digits map to an industry type
            # deterministically -- no judgement, no model.
            cfg = spec["prefix_lookup"]
            code = str(_resolve(account, cfg["from"]) or "")
            for prefix, value in cfg["table"].items():
                if code.startswith(str(prefix)):
                    assign(account, path, value)
                    prov[path] = {"source": "derived", "page": None, "confidence": conf,
                                  "note": f"{note} (NAICS {code} matched prefix {prefix})"}
                    break

        elif "year_of" in spec:
            base, _, leaf = path.partition("[].")
            arr = _resolve(account, base) or []
            for i, item in enumerate(arr):
                m = re.search(r"/(\d{4})$", str(item.get(spec["year_of"], "")))
                if m:
                    item[leaf] = m.group(1)
                    prov[f"{base}.{i}.{leaf}"] = {"source": "derived", "page": None,
                                                  "confidence": conf, "note": note}

        elif "letter_from" in spec:
            # e.g. general_liability.classifications[].premium_basis_code
            base, _, leaf = path.partition("[].")
            arr = _resolve(account, base) or []
            table = {k.lower(): v for k, v in spec["lookup"].items()}
            for i, item in enumerate(arr):
                word = str(item.get(spec["letter_from"], "")).strip().lower()
                if word in table:
                    item[leaf] = table[word]
                    prov[f"{base}.{i}.{leaf}"] = {"source": "derived", "page": None,
                                                  "confidence": conf, "note": note}

    for path in mapping.get("never_in_export") or []:
        notes.append(f"{path}: not available from this export by design; requires a person")


def _flag_renewal_term_conflict(account: dict, export_dir: str, mapping: dict,
                                conflicts: list) -> None:
    """Record that the export held two terms and which one was used.

    The expiring and renewal rows both carry dates. We pick the renewal row,
    but a reviewer should be able to see that a choice was made rather than
    discovering it from a policy period in the past.
    """
    full = os.path.join(export_dir, "epic_policy.csv")
    if not os.path.exists(full):
        return
    rows = read_csv(full)
    terms = {str(r.get("PolicyStatus", "")).strip(): str(r.get("EffectiveDate", "")).strip()
             for r in rows}
    if len(terms) < 2:
        return
    used = _resolve(account, "policy.effective_date")
    conflicts.append({
        "path": "policy.effective_date",
        "detail": ("the export carried more than one term: "
                   + "; ".join(f"{k or 'unlabelled'} beginning {v}" for k, v in terms.items())
                   + f". Used {used}, the row marked Renewal Requested. "
                     "Confirm the requested term with the account manager."),
        "values": [{"value": v, "source": f"epic_policy.csv ({k or 'unlabelled'} row)"}
                   for k, v in terms.items()],
    })


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-dir", required=True, help="directory holding the AMS CSV export")
    ap.add_argument("--mapping", required=True, help="column mapping YAML for this AMS")
    ap.add_argument("--out", required=True, help="canonical account JSON to write")
    ap.add_argument("--completion-date", default=None,
                    help="date to stamp on the form (default: today)")
    args = ap.parse_args()

    mapping = yaml.safe_load(open(args.mapping, encoding="utf-8"))
    account, prov, conflicts, notes = ingest(args.export_dir, mapping)

    completed = args.completion_date or dt.date.today().strftime("%m/%d/%Y")
    assign(account, "form_meta.completion_date", completed)
    prov["form_meta.completion_date"] = {
        "source": "assumed_default", "page": None, "confidence": "low",
        "note": "date this record was built, not a value from the export",
    }

    doc = {"account": account, "provenance": prov, "conflicts": conflicts}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    label = (mapping.get("source") or {}).get("label", args.mapping)
    print(f"{label}")
    print(f"  export dir .......... {args.export_dir}")
    print(f"  values extracted .... {len(prov)}")
    print(f"  conflicts recorded .. {len(conflicts)}")
    print(f"  -> {args.out}")
    if notes:
        print("\n  notes:")
        for n in notes:
            print(f"    - {n}")


if __name__ == "__main__":
    main()
