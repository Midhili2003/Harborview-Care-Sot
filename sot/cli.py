"""Command line interface.

  python -m sot.cli ingest fixtures/messy --as-of 2026-09-21
  python -m sot.cli issues [--severity critical]
  python -m sot.cli report staffing [--quarter 2026Q3] [--csv out.csv]
  python -m sot.cli report credentials
  python -m sot.cli reset
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .core.config import Config
from .core.pipeline import accept_match, build, dismiss, ingest, reject_match, reopen
from .apps.reports import credentials_report, staffing_report
from .core.store import Store

ICON = {"critical": "[CRITICAL]", "warning": "[WARNING] ", "info": "[info]    "}


def print_summary(store: Store, s: dict, top: int = 10):
    print(f"\nIngested as of {s['as_of']}")
    for f in s.get("files") or []:
        print(f"  {f['file']:<28} -> {f['source'] or 'NOT RECOGNISED':<10} {f['records']} records")
    print(f"\nEntities: {s['entities']} ({s['anchored_entities']} in the anchor system)")
    print("Match methods: " + ", ".join(f"{k}={v}" for k, v in s["match_methods"].items()))
    o = s["issues_open"]
    print(f"\nOpen issues: {o.get('critical', 0)} critical, {o.get('warning', 0)} warning, {o.get('info', 0)} info"
          + (f" ({s['issues_dismissed']} dismissed)" if s["issues_dismissed"] else ""))
    rows = store.query("SELECT severity, title, explanation FROM issues WHERE status='open' "
                       "AND severity IN ('critical','warning') LIMIT ?", (top,))
    for r in rows:
        print(f"  {ICON[r['severity']]} {r['title']}\n      {r['explanation']}")
    if rows:
        print("\nSee all issues: python -m sot.cli issues   |   Dashboard: streamlit run app.py")


def table(rows, cols):
    if not rows:
        print("  (none)")
        return
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  " + "  ".join(c.ljust(w[c]) for c in cols))
    for r in rows:
        print("  " + "  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sot", description="Single source of truth")
    ap.add_argument("--config", default="config/harborview.yaml")
    ap.add_argument("--db", default="sot.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="ingest a folder or files")
    p.add_argument("paths", nargs="+")
    p.add_argument("--as-of", help="date the time-based checks are run against (YYYY-MM-DD)")
    p.add_argument("--keep-decisions", action="store_true", default=True)
    p = sub.add_parser("rebuild", help="re-run matching and rules on the last ingest")
    p.add_argument("--as-of")
    p = sub.add_parser("issues", help="list issues")
    p.add_argument("--severity", choices=["critical", "warning", "info"])
    p = sub.add_parser("report")
    p.add_argument("kind", choices=["staffing", "credentials"])
    p.add_argument("--quarter")
    p.add_argument("--csv")
    p = sub.add_parser("decide", help="record a human decision on an issue")
    p.add_argument("issue_id", type=int)
    p.add_argument("action", choices=["accept", "reject", "dismiss", "reopen"])
    p.add_argument("--to", help="entity key to match to (default: best candidate)")
    p.add_argument("--note", default="")
    sub.add_parser("reset", help="delete all data and decisions")
    a = ap.parse_args(argv)

    cfg = Config(a.config)
    store = Store(a.db)
    as_of = date.fromisoformat(a.as_of) if getattr(a, "as_of", None) else None

    if a.cmd == "ingest":
        print_summary(store, ingest(cfg, store, a.paths, as_of))
    elif a.cmd == "rebuild":
        print_summary(store, build(cfg, store, as_of))
    elif a.cmd == "issues":
        q = "SELECT id, severity, rule_id, title, explanation FROM issues WHERE status='open'"
        rows = store.query(q + (" AND severity=?" if a.severity else ""), (a.severity,) if a.severity else ())
        for r in rows:
            print(f"#{r['id']:<3} {ICON[r['severity']]} {r['title']}  ({r['rule_id']})\n     {r['explanation']}")
        print(f"\n{len(rows)} open issue(s)")
    elif a.cmd == "report":
        if a.kind == "staffing":
            rep = staffing_report(cfg, store, a.quarter)
            if rep["warning"]:
                print(f"\n!! {rep['warning']}")
            print(f"\nStaffing hours {rep['period']}")
            table(rep["summary"], ["facility", "role", "headcount", "paid_hours", "scheduled_hours", "variance"])
            if rep["excluded"]:
                print("\nHours excluded (worked on an expired license):")
                table(rep["excluded"], ["name", "hours", "reason"])
            if a.csv:
                import pandas as pd
                pd.DataFrame(rep["daily"]).to_csv(a.csv, index=False)
                print(f"\nDaily detail written to {a.csv}")
        else:
            rows = credentials_report(cfg, store)
            table(rows, ["name", "facility", "role", "license_number", "expires", "days_left", "status",
                         "last_verified", "shifts_after_expiry"])
    elif a.cmd == "decide":
        fn = {"accept": lambda: accept_match(cfg, store, a.issue_id, a.to, a.note),
              "reject": lambda: reject_match(cfg, store, a.issue_id, a.note),
              "dismiss": lambda: dismiss(cfg, store, a.issue_id, a.note),
              "reopen": lambda: reopen(cfg, store, a.issue_id)}[a.action]
        print_summary(store, fn())
    elif a.cmd == "reset":
        store.reset()
        print("All data and decisions deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
