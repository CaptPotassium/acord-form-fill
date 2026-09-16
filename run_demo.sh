#!/usr/bin/env bash
# End-to-end demo: fill the ACORD 125 and 126 sections of a real submission
# packet from one canonical account, then print the review queue.
#
# Two runs, deliberately. The first uses only what the three source documents
# actually contain. The second uses the same account after a CSR has answered
# the review queue. The gap between them is the human-in-the-loop cost.
set -euo pipefail
cd "$(dirname "$0")"

# pypdf warns about the packet's /F2 font resource on every text field it
# restyles. It is benign and noisy; everything else on stderr should be seen.
filter_noise() { grep -v 'Font dictionary for /F2 not found' >&2 || true; }

report() {
  python3 - "$1" <<'PY'
import json, sys
outdir = sys.argv[1]
for form in ("acord_125", "acord_126"):
    d = json.load(open(f"{outdir}/{form}_review.json"))
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
}

fill() {
  python3 scripts/fill_form.py \
    --account "$1" \
    --mapping assets/mappings/acord_125.yaml \
    --mapping assets/mappings/acord_126.yaml \
    --forms-dir assets/forms --outdir "$2" 2> >(filter_noise)
}

if [[ "${1:-}" == "--sparse" ]]; then
  echo "==> Guardrail demo — deliberately malformed and incomplete account"
  echo "    samples/account_sparse.json: bad date, missing FEIN and NAICS,"
  echo "    partial composite address, more premises than the form holds."
  echo
  fill samples/account_sparse.json output_sparse
  echo
  report output_sparse
  echo
  echo "A required field whose value fails validation is left BLANK, not written."
  echo "A blank reads as incomplete; \"sometime in July\" in a date field reads as"
  echo "data and can survive a hurried review all the way to the carrier."
  echo
  echo "Output: output_sparse/"
  exit 0
fi

echo "==> Regenerating sample input documents"
python3 scripts/make_sample_forms.py --samples samples >/dev/null
echo "    samples/dec_page.pdf, samples/loss_runs.pdf, samples/ams_export.csv"

echo
echo "=============================================================="
echo " RUN 1 — documents only (unattended extraction)"
echo "=============================================================="
fill samples/account.json output
echo
report output

echo
echo "=============================================================="
echo " RUN 2 — same account after a CSR answers the review queue"
echo "=============================================================="
fill samples/account_reviewed.json output_reviewed
echo
report output_reviewed

echo
echo "==> Output"
echo "  output/            documents only"
echo "  output_reviewed/   after CSR review"
echo
echo "Open output/submission_packet_filled.pdf next to output/acord_125_review.md."
echo "Run ./run_demo.sh --sparse for the guardrail demo (malformed and missing data)."
