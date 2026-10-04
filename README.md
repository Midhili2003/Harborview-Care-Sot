# Harborview source of truth

A reusable single source of truth for the Pulse Foundry hackathon. It ingests the HR roster, payroll, license verification and schedule PDF for Harborview Care Group, links every record to one person, builds a trusted "golden" record, and flags everything that is wrong, inconsistent or needs a human.

The engine (`sot/core`) knows nothing about nursing homes. Everything specific to Harborview lives in [`config/harborview.yaml`](config/harborview.yaml). See [DECISIONS.md](DECISIONS.md) for why it is built this way.

## Quickstart

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python -m sot.cli ingest fixtures/messy --as-of 2026-09-21    # practice data with 25 planted problems
streamlit run app.py                                         # dashboard at http://localhost:8501
```

## On judging day

```bash
python -m sot.cli reset                       # start empty (also clears saved decisions)
python -m sot.cli ingest path/to/real_files/  # file types are detected from their columns
python -m sot.cli issues --severity critical
python -m sot.cli report credentials
python -m sot.cli report staffing --quarter 2026Q3 --csv staffing_daily.csv
```

Or use the dashboard: **Load data → upload all four files → Ingest files**. Then walk through Issues, People, Licenses and Staffing report.

Useful extras:

| Command | What it does |
|---|---|
| `python -m sot.cli issues` | Every open issue, with its id |
| `python -m sot.cli decide <id> confirm` | Confirm a possible match (remembered on future ingests) |
| `python -m sot.cli decide <id> separate` | Keep records separate and stop asking |
| `python -m sot.cli decide <id> resolve --note "removed from shifts"` | Someone dealt with the issue |
| `python -m sot.cli decide <id> accept --note "float aide, works both sites"` | The data is correct as it is |
| `python -m sot.cli decide <id> reopen` | Put a closed issue back on the open list |

Critical issues can only be closed with a note, so there is always a reason on record.
| `python -m sot.cli rebuild --as-of 2026-10-01` | Re-run checks against a different date |

## What it flags

**Within one file:** missing columns or values, unreadable dates/numbers/phones, unknown facility or role spellings, malformed license numbers, duplicate IDs, future hire dates, implausible hours, unknown shift codes, unexpected or renamed columns.

**Across systems:** people paid but not in HR, people in HR missing from payroll, the schedule or the license service, possible matches that need a human, and disagreements on license expiration, license number, role vs license type, facility and name.

**Over time:** expired licenses, licenses expiring within 30/90 days, anyone scheduled or paid after their license expired, stale license verification, scheduled vs paid hours mismatches, overtime, and double-booked shifts.

Every issue has a plain-English explanation and links to the exact source rows behind it.

## Project layout

```
config/harborview.yaml   business config: sources, mappings, nicknames, authority, rules
sot/core/                generic engine
  ingest.py              CSV/Excel loader with fuzzy header mapping; PDF schedule grid loader
  normalize.py           dates, names, phones, codes, identifiers
  match.py               entity resolution (anchor key > strong keys > fuzzy name + evidence)
  golden.py              field-level survivorship and time-based events
  rules.py               generic rule types, instantiated from config
  pipeline.py            ingest -> match -> golden -> rules; human decisions
  store.py               SQLite with full lineage
sot/apps/reports.py      staffing (PBJ-style) and credential reports built on the SOT
sot/cli.py               command line
app.py                   Streamlit dashboard
tools/generate_fixtures.py  practice data in the judging formats
fixtures/                messy + clean practice data, EXPECTED_ISSUES.md
tests/                   23 tests incl. robustness (BOM, semicolons, shuffled/renamed/missing columns, Excel, unruled PDF)
```

## Run the tests

```bash
pytest -q
```

## Deploy the dashboard

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, choose **Create app**, pick this repo, branch `main`, main file `app.py`, and deploy.

The hosted app starts empty; upload files, or open **Use sample data** at the bottom of the Load data tab. Its database resets when the app restarts.
