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


def _as_of(store, as_of=None):
    run = store.last_run()
    return as_of or (date.fromisoformat(run["as_of"]) if run and run.get("as_of") else date.today())


def agreement_grid(cfg: Config, store: Store) -> dict:
    """For each person and each source system: does that system agree with the others?

    'missing' - the system has no record of the person
    'differs' - the system disagrees with the others on a checked field (warning/critical rules)
    'agrees'  - present and consistent
    """
    sources = list(cfg.sources)
    ents = _entities(store)
    recs = defaultdict(list)
    for r in store.query("SELECT entity_key, source, norm FROM records WHERE entity_key IS NOT NULL"):
        recs[r["entity_key"]].append({"source": r["source"], "norm": json.loads(r["norm"])})
    groups = {}
    for grp in cfg.raw.get("role_equivalents", []):
        for v in grp:
            groups[v] = grp[-1]
    checks = [r for r in cfg.rules if r.get("type") == "field_conflict" and r.get("severity") != "info"]
    hour_rules = {r.get("id") or r["type"] for r in cfg.rules if r.get("type") == "hours_reconcile"}
    hours_off = {i["entity_key"] for i in store.query("SELECT rule_id, entity_key FROM issues WHERE status='open'")
                 if i["rule_id"] in hour_rules}
    paid_source = next((e["source"] for e in cfg.events if e.get("hours")), None)
    rows = []
    for k, e in sorted(ents.items(), key=lambda kv: kv[1]["display_name"]):
        present = {r["source"] for r in recs[k]}
        status = {s: ("agrees" if s in present else "missing") for s in sources}
        why = defaultdict(list)
        for p in checks:
            vals = defaultdict(set)
            for r in recs[k]:
                f = p["fields"].get(r["source"])
                v = r["norm"].get(f) if f else None
                if v not in (None, ""):
                    vals[r["source"]].add(groups.get(v, v))
            distinct = {v for vs in vals.values() for v in vs}
            if len(distinct) < 2:
                continue
            count = defaultdict(int)
            for vs in vals.values():
                for v in vs:
                    count[v] += 1
            top = max(count.values())
            winners = [v for v, c in count.items() if c == top]
            majority = winners[0] if len(winners) == 1 else None
            for s, vs in vals.items():
                if majority is None or vs != {majority}:
                    status[s] = "differs"
                    why[s].append(p["label"].lower())
        if k in hours_off and paid_source and status.get(paid_source) != "missing":
            status[paid_source] = "differs"
            why[paid_source].append("hours vs schedule")
        rows.append({"entity_key": k, "name": e["display_name"], "in_anchor": e["origin"] == cfg.anchor,
                     "status": status, "why": {s: ", ".join(dict.fromkeys(w)) for s, w in why.items()}})
    return {"sources": [(s, cfg.source_label(s)) for s in sources], "rows": rows}


def overview(cfg: Config, store: Store) -> dict:
    """One answer per problem in the brief."""
    as_of = _as_of(store)
    staffing = staffing_report(cfg, store)
    creds = credentials_report(cfg, store, as_of)
    ents = _entities(store)
    exp_field = _expiry_field(cfg) or "license_expiration"
    id_field = next((r.get("id_field") for r in cfg.rules if r.get("type") == "expiry"), None)

    # who is working this period with a valid credential, by facility and role
    events = store.query("SELECT entity_key, facility, role, start_date FROM events WHERE kind='scheduled'")
    capacity = defaultdict(lambda: defaultdict(set))
    not_counted = set()
    for ev in events:
        g = ents.get(ev["entity_key"], {}).get("golden", {})
        exp = (g.get(exp_field) or {}).get("value")
        has_cred = bool((g.get(id_field) or {}).get("value")) if id_field else True
        valid = has_cred and exp and exp >= ev["start_date"]
        fac = cfg.label_value("code:facility", ev["facility"] or (g.get("facility") or {}).get("value")) or "Unknown"
        role = ev["role"] or (g.get("role") or {}).get("value") or "Unknown"
        if valid and ents.get(ev["entity_key"], {}).get("origin") == cfg.anchor:
            capacity[fac][role].add(ev["entity_key"])
        else:
            not_counted.add(ents.get(ev["entity_key"], {}).get("display_name", ev["entity_key"]))
    dates = sorted(ev["start_date"] for ev in events)
    return {
        "as_of": as_of.isoformat(),
        "staffing": {
            "ready": not staffing["blocking_issues"],
            "blocking": staffing["blocking_issues"],
            "paid": round(sum(r["paid_hours"] for r in staffing["summary"]), 1),
            "scheduled": round(sum(r["scheduled_hours"] for r in staffing["summary"]), 1),
            "excluded": round(sum(r["hours"] for r in staffing["excluded"]), 1),
        },
        "licenses": {
            "expired": [r for r in creds if r["status"] == "EXPIRED"],
            "soon": [r for r in creds if r["status"] == "<30 days"],
            "later": [r for r in creds if r["status"] == "<90 days"],
            "worked_after": [r for r in creds if r["shifts_after_expiry"]],
            "total": len(creds),
        },
        "capacity": {fac: {role: len(p) for role, p in sorted(roles.items())} for fac, roles in sorted(capacity.items())},
        "capacity_period": f"{dates[0]} to {dates[-1]}" if dates else None,
        "not_counted": sorted(not_counted),
    }
