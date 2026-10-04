"""Reports that sit on top of the source of truth.

These are examples of applications the SOT makes easy: a quarterly staffing
report (the CMS Payroll-Based Journal problem) and a credential expiry list.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from ..core.config import Config
from ..core.store import Store


def _quarter_bounds(q: str | None):
    if not q:
        return None, None
    y, n = int(q[:4]), int(q[-1])
    start = date(y, 3 * (n - 1) + 1, 1)
    end = date(y + (n == 4), (3 * n) % 12 + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def _expiry_field(cfg: Config):
    return next((r["field"] for r in cfg.rules if r.get("type") == "activity_after_expiry"), None)


def _entities(store):
    return {e["entity_key"]: {**e, "golden": json.loads(e["golden"])} for e in store.query("SELECT * FROM entities")}


def staffing_report(cfg: Config, store: Store, quarter: str | None = None) -> dict:
    qs, qe = _quarter_bounds(quarter)
    ents = _entities(store)
    exp_field = _expiry_field(cfg)
    events = store.query("SELECT * FROM events")
    if qs:
        events = [e for e in events if qs.isoformat() <= e["start_date"] <= qe.isoformat()]
    grid = defaultdict(lambda: {"paid_hours": 0.0, "scheduled_hours": 0.0, "people": set()})
    daily = defaultdict(float)
    excluded = []
    for ev in events:
        g = ents.get(ev["entity_key"], {}).get("golden", {})
        fac = ev["facility"] or (g.get("facility") or {}).get("value")
        role = ev["role"] or (g.get("role") or {}).get("value")
        exp = (g.get(exp_field) or {}).get("value") if exp_field else None
        if exp and ev["end_date"] > exp and ev["hours"]:
            excluded.append({"name": ents[ev["entity_key"]]["display_name"], "hours": ev["hours"],
                             "reason": f"{ev['kind']} {ev['start_date']} after expiry {exp}"})
            continue
        k = (cfg.label_value("code:facility", fac) or "Unknown", role or "Unknown")
        if ev["kind"] == "paid":
            grid[k]["paid_hours"] += ev["hours"]
        elif ev["kind"] == "scheduled":
            grid[k]["scheduled_hours"] += ev["hours"]
            daily[(ev["start_date"], k[0], k[1])] += ev["hours"]
        grid[k]["people"].add(ev["entity_key"])
    summary = [{"facility": f, "role": r, "headcount": len(v["people"]), "paid_hours": round(v["paid_hours"], 2),
                "scheduled_hours": round(v["scheduled_hours"], 2),
                "variance": round(v["paid_hours"] - v["scheduled_hours"], 2)}
               for (f, r), v in sorted(grid.items())]
    involved = {ev["entity_key"] for ev in events}
    blocking = [i for i in store.query("SELECT * FROM issues WHERE status='open' AND severity IN ('critical','warning')")
                if i["entity_key"] in involved]
    period = f"{qs} to {qe}" if qs else "(all periods loaded)"
    if events:
        period += f"; data covers {min(e['start_date'] for e in events)} to {max(e['end_date'] for e in events)}"
    return {"period": period, "summary": summary,
            "daily": [{"date": d, "facility": f, "role": r, "scheduled_hours": h}
                      for (d, f, r), h in sorted(daily.items())],
            "excluded": excluded,
            "blocking_issues": len(blocking),
            "warning": (f"{len(blocking)} open critical/warning issue(s) affect people in this report. "
                        f"Resolve them before submitting." if blocking else "")}


def credentials_report(cfg: Config, store: Store, as_of: date | None = None) -> list[dict]:
    run = store.last_run()
    as_of = as_of or (date.fromisoformat(run["as_of"]) if run and run.get("as_of") else date.today())
    exp_field = _expiry_field(cfg) or "license_expiration"
    id_field = next((r.get("id_field") for r in cfg.rules if r.get("type") == "expiry"), None)
    ents = _entities(store)
    events = store.query("SELECT * FROM events WHERE kind='scheduled'")
    rows = []
    for k, e in ents.items():
        g = e["golden"]
        exp = (g.get(exp_field) or {}).get("value")
        num = (g.get(id_field) or {}).get("value") if id_field else None
        if not exp and not num:
            continue
        days = (date.fromisoformat(exp) - as_of).days if exp else None
        status = ("MISSING DATE" if days is None else "EXPIRED" if days < 0 else "<30 days" if days <= 30
                  else "<90 days" if days <= 90 else "ok")
        after = [ev for ev in events if ev["entity_key"] == k and exp and ev["start_date"] > exp]
        nxt = sorted(ev["start_date"] for ev in events if ev["entity_key"] == k and ev["start_date"] >= as_of.isoformat())
        rows.append({"name": e["display_name"],
                     "facility": cfg.label_value("code:facility", (g.get("facility") or {}).get("value")),
                     "role": (g.get("role") or {}).get("value"), "license_number": num, "expires": exp,
                     "source": (g.get(exp_field) or {}).get("source"), "days_left": days, "status": status,
                     "last_verified": (g.get("last_verified") or {}).get("value"),
                     "shifts_after_expiry": len(after), "next_shift": nxt[0] if nxt else None})
    return sorted(rows, key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0))
