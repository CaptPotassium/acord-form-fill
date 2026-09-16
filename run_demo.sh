#!/usr/bin/env bash
# End-to-end demo: fill the ACORD 125 and 126 sections of a real submission
# packet from one canonical account, then print the review queue.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Regenerating sample input documents"
python3 scripts/make_sample_forms.py --samples samples >/dev/null
echo "    samples/dec_page.pdf, samples/loss_runs.pdf, samples/ams_export.csv"

echo
echo "==> Filling ACORD 125 + 126 from one canonical account"
python3 scripts/fill_form.py \
  --account samples/account.json \
  --mapping assets/mappings/acord_125.yaml \
  --mapping assets/mappings/acord_126.yaml \
  --forms-dir assets/forms --outdir output 2>/dev/null

echo
echo "==> Review queue"
python3 - <<'PY'
import json
for form in ("acord_125", "acord_126"):
    d = json.load(open(f"output/{form}_review.json"))
    m = d["metrics"]
    print(f"  {form}: {m['filled']}/{m['mapped_fields']} mapped fields filled "
          f"({m['fill_rate']}%), {m['mapped_fields']}/{m['form_fields']} of the "
          f"packet mapped")
    for sev, title in (("blocker", "must fix"), ("review", "confirm with insured")):
        rows = [r for r in d["review_queue"] if r["severity"] == sev]
        if not rows:
            continue
        print(f"    {title} ({len(rows)}):")
        for r in rows[:6]:
            print(f"      - {r['field']}  [{r['reason']}]")
        if len(rows) > 6:
            print(f"      ... and {len(rows) - 6} more")
PY

echo
echo "==> Output"
ls -1 output/
echo
echo "Open output/submission_packet_filled.pdf next to output/acord_125_review.md."
