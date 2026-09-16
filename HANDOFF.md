# Handoff — Cooper AI Sales Engineer take-home

Written as a pick-up-where-we-left-off doc: enough state to resume work in a
fresh session, plus the reasoning behind each decision so it can be defended in
the panel rather than just recited.

---

## The assignment

Sales Engineer take-home for Cooper AI, a company building AI agents for
insurance brokerages — their product reads dec pages, loss runs and applications,
fills ACORD forms and carrier supplementals, and flags what's missing for a
broker to confirm.

Build a working MVP that ingests account artifacts and produces a filled form.
Budget 4–6 hours. Deliverables: a skill package or repo, a 2–3 page write-up, and
a working demo. The onsite is 60 minutes with a panel — demo live, walk through
discovery questions and assumptions, explain architecture and how accuracy and
edge cases scale, explain customer deployment.

Evaluated on: sales discovery, Python and AI-assisted coding, scoping under
ambiguity, demo presentation. Three of those four are writing and talking, not
code — worth remembering when allocating remaining time.

An interviewer later confirmed that producing one or two of the listed sample
forms is sufficient, which makes the ACORD 125 + 126 scope exactly right.

## What exists now

A Claude Skill called `acord-form-fill`, delivered as both a `.skill` package
(installs into claude.ai chat) and a `.zip` containing a git repo with two
commits (for GitHub or Claude Code).

Name was left as `acord-form-fill`. A rename to "acorn forms" was requested and
then withdrawn — flagged as a likely typo of ACORD, which an insurance panel
would notice.

### Current numbers

Run against the real ACORD 125/126/140 packet (2016 editions, 924 fillable
fields) that an interviewer provided.

Two runs, because the honest answer is two numbers.

**Run 1 — documents only** (`samples/account.json`, extracted from the dec page,
loss run and AMS export and nothing else):

| Section | Mapped | Auto-filled | Fill rate | Blockers | Review |
|---|---|---|---|---|---|
| ACORD 125 | 148 | 61 | 41% | 5 | 12 |
| ACORD 126 | 53 | 31 | 58% | 0 | 6 |

**Run 2 — after a CSR works the review queue** (`samples/account_reviewed.json`):

| Section | Mapped | Auto-filled | Fill rate | Blockers | Review |
|---|---|---|---|---|---|
| ACORD 125 | 148 | 81 | 55% | 0 | 15 |
| ACORD 126 | 53 | 31 | 58% | 0 | 3 |

201 of 924 packet fields mapped; 92 values written unattended, 111 after review.

**Always report coverage and fill rate separately.** Coverage is 201/924 — the
sections sourceable from account documents. The remaining 723 are carrier and
underwriter blocks, additional interests, contact grids, state fraud notices,
signatures and office-use fields that no extraction should touch. A single
blended number reads as weak rather than honest.

The 5 blockers are the ACORD 125 general information questions — prior
cancellation, bankruptcy, judgements, foreign operations, safety program. No dec
page or AMS export answers those, ever. Flagging them is the tool telling a CSR
to make a phone call, and saying so out loud reframes the whole metric.

### Repository layout

```
acord-form-fill/
├── SKILL.md                      # workflow Claude follows
├── README.md                     # doubles as the assignment write-up
├── DISCOVERY.md                  # discovery questions + assumption ledger
├── run_demo.sh                   # one-command demo
├── scripts/
│   ├── dump_fields.py            # PDF → mapping stub (new-form onboarding)
│   ├── fill_form.py              # canonical + mappings → packet + review reports
│   └── make_sample_forms.py      # generates sample input documents
├── references/
│   ├── canonical-schema.md
│   ├── extraction-guide.md
│   └── adding-a-form.md
├── assets/
│   ├── forms/acord_submission_packet.pdf
│   └── mappings/{acord_125,acord_126}.yaml
└── samples/                      # dec page, loss run, AMS CSV, account.json,
                                  # account_sparse.json (failure-case demo)
```

Sample account is Brightwater Mechanical Contractors, Inc. — a Connecticut
plumbing and HVAC contractor with two locations, two GL class codes and three
losses. All synthetic and internally consistent.

## Architecture, and why

**A canonical account record sits in the middle.** Mapping documents directly to
forms costs one integration per document-type × form-type pair. Routing through
a canonical schema makes it additive: one extractor per input type, one YAML
mapping per form. ACORD 126's header reads the same canonical paths as ACORD
125, so the second section cost about fifteen minutes. This is the answer to
"how does it scale to more forms, lines and carriers."

**Claude extracts, Python fills.** Reading a dec page and deciding that "Form of
Business: Corporation" means `applicant.entity_type = "Corporation"` requires
judgement. Writing it into a PDF field does not. The model never touches the
PDF, so errors are attributable to the extraction (visible in `account.json`) or
the mapping (visible in the YAML) — never to an opaque generation step. This is
the audit boundary, and it's why the fill engine is hand-written rather than
AI-generated.

**Field names get dumped, never guessed.** `dump_fields.py` enumerates any
AcroForm PDF and emits a mapping stub. Onboarding a new form becomes filling in
paths — 20–40 minutes, no Python changes, doable by a non-engineer.

**Provenance on every value.** Each carries source file, page and confidence
(high/medium/low — categorical, because numeric confidence from an LLM is
theatre). The review report separates blockers, review items and gaps. A
producer signs this application and carries E&O exposure on it, so a silent fill
isn't deployable.

## What the real form taught the code

Built first against generated stand-in forms, then swapped in the real blank. It
broke three things — all silent failures, all found by rendering output rather
than counting fields. This is the strongest material for the "how do you handle
accuracy at scale" question.

1. **Repeater detection was too narrow.** Handled trailing digits only. The real
   packet also uses infix digits (`ACORD_Location1_Street`) and trailing letters
   (`GeneralLiability_Hazard_ClassCode_A`). The letter case is ambiguous because
   ACORD also suffixes `_A` onto single-instance fields, so a template now only
   counts as repeating when two or more indices actually exist.
2. **The two sections use different naming conventions in the same PDF.** Pages
   1–4 (ACORD 125) carry a literal `ACORD_` prefix; pages 5–8 (ACORD 126) use
   domain-object naming (`GeneralLiability_*`, `ProductAndCompletedOperations_*`)
   and pages 9–10 (ACORD 140) a third (`CommercialProperty_*`). Checkbox
   on-states differ too — `/On` on pages 1–4, `/1` on 5–10. This is the argument
   for mappings being data rather than logic.
   Verified against the packet; see `references/packet-field-inventory.txt`.
3. **Appearance streams corrupted output.** pypdf generates its own, which
   escaped literal parentheses — `(203) 555-0900` rendered as `\(203\) 555-0900`
   — and baked in a font size that clipped text mid-word. Fix: delete those
   streams for text fields and let `NeedAppearances` regenerate at the form's own
   auto-size default.

A fourth, from adding composite fields: ACORD 125 collapses name and full
mailing address into one box, and that field isn't multiline, so a newline
silently dropped the city/state/zip. The engine now reads the multiline flag,
joins with commas when needed, and reports the substitution.

### One design decision worth calling out

A required field whose value fails validation is now left **blank** rather than
written. A blank required field reads as obviously incomplete; `"sometime in
July"` in a date field reads as data and can survive a hurried review all the way
to the carrier. `samples/account_sparse.json` reproduces this alongside missing
FEIN and NAICS, a partial composite address, and premises overflow.

## Open items

**The extraction half is now verified — and it moved the headline number.**
`samples/account.json` was originally hand-written rather than extracted, and a
blind extraction from the three sample documents fills 61/148 on ACORD 125, not
80/148. The 19-field gap broke down as: 10 values the old fixture had already
flagged `low` with an honest note (per-location allocations of company totals —
defensible), 7 that claimed `confidence: "high"` and cited a document which does
not contain them (`agency_customer_id`, three `date_of_claim`, three
`subrogation` — the loss run has no such columns), and 2 a genuine ambiguity
about whether one sq-ft figure per location is total or occupied area.

The seven false high-confidence citations were the real defect: high confidence
is precisely what suppresses review, so they would have passed audit looking
sourced. They are now attributed `csr_confirmed`. The fixture split into a
documents-only state and a post-review state, so the demo shows the arc and a
panelist running the blind test confirms the write-up instead of contradicting
it.

**Discovery doc contains invented numbers.** The volume and time-per-submission
figures in section 1 are placeholders. Swap in real numbers if available;
otherwise say plainly on the panel that they're synthetic.

**Deliberately cut**, documented with cost-to-add in the README: ACORD 140
(in the packet and mappable, needs construction/protection/valuation modelling),
ACORD 130 (class codes, multi-state payroll, experience mod), carrier
supplementals, OCR for scanned inputs, live AMS integration, AMS write-back and
portal submission, web UI.

**Next build, in order:** accuracy instrumentation, then ACORD 140, then one
carrier supplemental, then OCR, then Outlook/SharePoint ingestion.

The accuracy instrumentation argument, since it's the best "what's next" answer:
every reviewer correction is a labelled error, so the review queue becomes a
measurement instrument. The number that matters is the *silent error rate* —
wrong and not flagged — because a flagged error costs thirty seconds and an
unflagged one costs a claim. Fill rate is the sales metric, silent error rate is
the engineering metric, and they trade against each other through the confidence
threshold. That dial should belong to the customer.

## Context on metrics in this industry

Useful for the ROI conversation. Agencies track financial and relational KPIs —
revenue per employee, retention, hit ratio, organic growth — benchmarked against
the Big "I" Best Practices Study. Almost none track forms processed or form
accuracy. Accuracy surfaces only as E&O claims (badly lagging), policy checking,
carrier rework, or outsourcer SLAs.

That last one is the competitive frame: the alternative to Cooper isn't "a CSR
types it," it's "we send it to Patra or ReSource Pro at ~99% accuracy per
transaction." That's the bar a panelist will implicitly compare against.

Because no baseline exists at the customer, the product has to ship its own
measurement — which is a design implication, not a slide.

## Running it

```bash
cd ~/code/acord-form-fill
pip install -r requirements.txt
./run_demo.sh            # run 1 (documents only) then run 2 (after review)
./run_demo.sh --sparse   # guardrail demo: malformed and missing data
```

Install into Claude Code: copy the folder to `~/.claude/skills/acord-form-fill`
(the folder holding `SKILL.md` must sit directly inside `skills/`), then start a
fresh session. Symlink instead of copy while iterating. For claude.ai chat,
upload the `.skill` file.

Push to GitHub — the repo is already initialized with two commits:

```bash
gh repo create acord-form-fill --private --source=. --push
```

## Demo plan for the onsite

Open with the architecture in one line: extract once into a canonical account,
then fill N forms from it. Show ACORD 125 and 126 filling from a single
extraction — that's the reuse claim made concrete rather than asserted.

Report coverage and fill rate as two numbers. Explain the 5 blockers as correct
behaviour before anyone asks.

Then run the two states back to back. 41% unattended, 0 blockers and 55% once a
CSR answers five phone-call questions. The gap is the human-in-the-loop cost and
it is bounded — five questions and a premises breakdown, not a re-key of the
application. Do not lead with 55%; lead with 41%, because that is the number
that holds up when a panelist runs the extraction themselves.

Then run the sparse account deliberately. Showing the guardrails catch a
malformed date and leave the field blank, rather than writing `sometime in July`
into an application a producer signs, is a stronger moment than any happy path.
Follow it with the three bugs the real form exposed — that's the honest version
of "how do you handle accuracy at scale."

Have a one-liner ready on ACORD licensing: blank forms are copyrighted and
licensed to member agencies and vendors, so in deployment they live in the
customer's own forms directory, not the vendor's repo. Noticing it unprompted
signals commercial awareness.

If asked about security: the extraction sandbox makes no network calls. Documents
arrive from carriers and third parties, which is exactly the input class where
prompt injection matters, so no-egress is a deliberate property.

## Loose ends from the session

- No GitHub connector was reachable from the chat session, so the repo was
  initialized locally and shipped inside the zip instead.
- The sandbox had network egress disabled, which is configurable under
  Settings → Capabilities but was never actually load-bearing — the skill makes
  no network calls and every needed library was already present.
- Stand-in form generation still exists in `make_sample_forms.py` behind
  `--standin-forms`, as a fallback when no licensed blank is available. The
  mappings target the real packet.
