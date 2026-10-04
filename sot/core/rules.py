"""Generic rule types. Instances (which source, which field, what severity) come from config.

Each rule takes (ctx, params) and returns a list of issue dicts. To add a rule
type, write a function and decorate it with @rule("name").
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

RULES = {}


def rule(name):
    def deco(fn):
        RULES[name] = fn
        return fn
    return deco


class Context:
    def __init__(self, cfg, records, entities, golden, events, as_of: date, missing_columns: set):
        self.cfg = cfg
        self.records = records
        self.entities = entities
        self.golden = golden
        self.events = events
        self.as_of = as_of
        self.missing_columns = missing_columns
        self.present = {r["source"] for r in records}

    def name(self, ek) -> str:
        if not ek:
            return "Unknown"
        g = self.golden.get(ek, {})
        n = (g.get("display_name") or {}).get("value") or ek
        aid = (g.get(self.cfg.entity.get("anchor_key", ""), {}) or {}).get("value")
        return f"{n} ({aid})" if aid else n

    def label(self, source, field, value):
        if field == "_name_key":
            return value
        return self.cfg.label_value(self.cfg.field_type(source, field), value)

    def where(self, r) -> str:
        return f"{self.cfg.source_label(r['source'])}, {r['file']} {r['row_ref']}"


def issue(p, severity_default, title, explanation, entity_key=None, field=None, records=(), detail="", values=None):
    return {"rule_id": p.get("id") or p["type"], "severity": p.get("severity", severity_default), "title": title,
            "explanation": explanation, "entity_key": entity_key, "field": field,
            "record_keys": [r["record_key"] for r in records], "detail": detail, "values": values or {}}


def _d(v):
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _gv(ctx, ek, field):
    return (ctx.golden.get(ek, {}).get(field) or {}).get("value")


# ------------------------------------------------------------- single-source rules

@rule("required")
def required(ctx, p):
    out = []
    for r in ctx.records:
        spec = ctx.cfg.sources[r["source"]]["fields"]
        errs = {f for f, _ in r["errors"]}
        for f, fs in spec.items():
            if fs.get("required") and r["norm"].get(f) in (None, "") and f not in errs \
                    and (r["file"], f) not in ctx.missing_columns:
                out.append(issue(p, "warning", f"Missing {f.replace('_', ' ')}",
                                 f"{ctx.where(r)} has no value for {f.replace('_', ' ')}.",
                                 r.get("entity_key"), f, [r], r["record_key"]))
    return out


@rule("invalid_value")
def invalid_value(ctx, p):
    out = []
    reformatted = defaultdict(list)
    for r in ctx.records:
        for f, msg in r["errors"]:
            title = "Unrecognised schedule entry" if f == "shift" else f"Unreadable {f.replace('_', ' ')}"
            out.append(issue(p, "warning", title, f"{ctx.where(r)}: {msg}.", r.get("entity_key"), f, [r],
                             f"{r['record_key']}|{msg}"))
        for f in r["norm"].get("_reformatted", []):
            reformatted[(r["file"], f)].append(r)
    for (file, f), rs in reformatted.items():
        out.append({**issue(p, "info", "Dates in a non-standard format",
                            f"{len(rs)} {f.replace('_', ' ')} value(s) in {file} were not written as YYYY-MM-DD "
                            f"and were converted ({ctx.cfg.date_order.upper()} order assumed). Check they were read correctly.",
                            rs[0].get("entity_key") if len(rs) == 1 else None, f, rs, f"{file}|{f}"),
                    "severity": "info"})
    return out


@rule("duplicate_key")
def duplicate_key(ctx, p):
    groups = defaultdict(list)
    for r in ctx.records:
        if r["source"] == p["source"] and r["norm"].get(p["field"]):
            groups[r["norm"][p["field"]]].append(r)
    out = []
    for v, rs in groups.items():
        if len(rs) > 1:
            same = all({k: x for k, x in r["norm"].items() if not k.startswith("_")} ==
                       {k: x for k, x in rs[0]["norm"].items() if not k.startswith("_")} for r in rs)
            out.append(issue(p, "warning", f"Duplicate {p['field'].replace('_', ' ')}",
                             f"{v} appears {len(rs)} times in {ctx.cfg.source_label(p['source'])} "
                             f"({', '.join(r['row_ref'] for r in rs)}). "
                             + ("The rows are identical, so this is likely a double export."
                                if same else "The rows disagree, so someone needs to pick the right one."),
                             rs[0].get("entity_key"), p["field"], rs, v))
    return out


@rule("future_date")
def future_date(ctx, p):
    out = []
    for r in ctx.records:
        d = _d(r["norm"].get(p["field"])) if r["source"] == p["source"] else None
        if d and d > ctx.as_of:
            out.append(issue(p, "warning", f"{p['field'].replace('_', ' ').capitalize()} is in the future",
                             f"{ctx.where(r)} has {p['field'].replace('_', ' ')} {d}, after today ({ctx.as_of}).",
                             r.get("entity_key"), p["field"], [r], r["record_key"]))
    return out


@rule("numeric_range")
def numeric_range(ctx, p):
    out = []
    for r in ctx.records:
        v = r["norm"].get(p["field"]) if r["source"] == p["source"] else None
        if v is not None and not (p.get("min", float("-inf")) <= v <= p.get("max", float("inf"))):
            out.append(issue(p, "warning", f"Implausible {p['field'].replace('_', ' ')}",
                             f"{ctx.where(r)} has {p['field']} = {v:g}, outside the expected range "
                             f"{p.get('min')}–{p.get('max')}.", r.get("entity_key"), p["field"], [r], r["record_key"]))
    return out


@rule("date_order")
def date_order(ctx, p):
    out = []
    for r in ctx.records:
        if r["source"] != p["source"]:
            continue
        s, e = _d(r["norm"].get(p["start"])), _d(r["norm"].get(p["end"]))
        if s and e and e < s:
            out.append(issue(p, "warning", "End date before start date",
                             f"{ctx.where(r)}: {p['end']} {e} is before {p['start']} {s}.",
                             r.get("entity_key"), p["end"], [r], r["record_key"]))
    return out


# ------------------------------------------------------------- cross-source rules

@rule("not_in_anchor")
def not_in_anchor(ctx, p):
    out = []
    anchor = ctx.cfg.anchor
    for ek, e in ctx.entities.items():
        if anchor in e.sources():
            continue
        rs = [r for r in e.records if r["source"] == p["source"]]
        if not rs or e.origin != p["source"]:
            continue
        out.append(issue(p, "warning", f"In {ctx.cfg.source_label(p['source'])} but not in {ctx.cfg.source_label(anchor)}",
                         f"{rs[0]['norm'].get('_display') or ek} appears in {ctx.cfg.source_label(p['source'])} "
                         f"({len(rs)} record(s)) with no matching {ctx.cfg.source_label(anchor)} record. {p.get('why', '')}",
                         ek, None, rs, p["source"]))
    return out


@rule("missing_from")
def missing_from(ctx, p):
    if p["source"] not in ctx.present:
        return []
    out = []
    anchor = ctx.cfg.anchor
    for ek, e in ctx.entities.items():
        if e.origin != anchor or p["source"] in e.sources():
            continue
        if p.get("when_field") and not any(r["norm"].get(p["when_field"]) for r in e.records):
            continue
        out.append(issue(p, "warning", f"Not found in {ctx.cfg.source_label(p['source'])}",
                         f"{ctx.name(ek)}: {p.get('why', '')}", ek, p.get("when_field"),
                         [r for r in e.records if r["source"] == anchor], p["source"]))
    return out


@rule("missing_value")
def missing_value(ctx, p):
    out = []
    for ek, e in ctx.entities.items():
        role = _gv(ctx, ek, p.get("role_field", "role"))
        if e.origin == ctx.cfg.anchor and role in p.get("roles", []) and not _gv(ctx, ek, p["field"]):
            out.append(issue(p, "warning", f"No {p['field'].replace('_', ' ')} on file",
                             f"{ctx.name(ek)}: {p.get('why', '')}", ek, p["field"], e.records, p["field"]))
    return out


@rule("field_conflict")
def field_conflict(ctx, p):
    groups = {}
    eq_name = p.get("equivalents")
    for grp in (ctx.cfg.raw.get(eq_name, []) if eq_name else []):
        for v in grp:
            groups[v] = grp[-1]
    out = []
    for ek, e in ctx.entities.items():
        seen = defaultdict(set)  # canonical value -> {(source, shown value)}
        recs = []
        for r in e.records:
            f = p["fields"].get(r["source"])
            v = r["norm"].get(f) if f else None
            if v in (None, ""):
                continue
            shown = r["norm"].get("_display") if f == "_name_key" else ctx.label(r["source"], f, v)
            seen[groups.get(v, v)].add((r["source"], shown))
            recs.append(r)
        if len(seen) > 1:
            by_value = defaultdict(list)
            for canon, pairs in seen.items():
                for s, shown in sorted(pairs):
                    if ctx.cfg.source_label(s) not in by_value[shown]:
                        by_value[shown].append(ctx.cfg.source_label(s))
            parts = []
            for shown, srcs in sorted(by_value.items(), key=lambda kv: -len(kv[1])):
                who = srcs[0] if len(srcs) == 1 else ", ".join(srcs[:-1]) + " and " + srcs[-1]
                parts.append(f"{who} {'says' if len(srcs) == 1 else 'say'} {shown}")
            out.append(issue(p, "warning", f"{p['label']} does not agree across systems",
                             f"{ctx.name(ek)}: " + "; ".join(parts) + ".", ek, p["label"], recs, p["label"],
                             {"values": sorted({sh for ps in seen.values() for _, sh in ps})}))
    return out


# ------------------------------------------------------------- time-based rules

@rule("expiry")
def expiry(ctx, p):
    out = []
    windows = sorted(p.get("windows", []))
    for ek, e in ctx.entities.items():
        g = ctx.golden.get(ek, {}).get(p["field"]) or {}
        d = _d(g.get("value"))
        if not d:
            continue
        days = (d - ctx.as_of).days
        label = p["field"].replace("_", " ")
        if days < 0:
            cl = ctx.cfg.business.get("credential_label", label)
            sev, title = p.get("severity", "critical"), f"{cl} expired"
            text = f"expired on {d} ({-days} days ago)"
        else:
            hit = next(((w, s) for w, s in windows if days <= w), None)
            if not hit:
                continue
            sev, title = hit[1], f"{ctx.cfg.business.get('credential_label', label)} expires within {hit[0]} days"
            text = f"expires on {d} (in {days} days)"
        out.append({**issue(p, sev, title,
                            f"{ctx.name(ek)}: {ctx.cfg.business.get('credential_label', 'credential')} "
                            f"{_gv(ctx, ek, p.get('id_field', '')) or ''} {text}, per "
                            f"{ctx.cfg.source_label(g.get('source'))}.".replace("  ", " "),
                            ek, p["field"], [r for r in e.records if r["norm"].get(p["field"])], title,
                            {"days": days, "date": d.isoformat()}), "severity": sev})
    return out


@rule("activity_after_expiry")
def activity_after_expiry(ctx, p):
    out = []
    by_ent = defaultdict(list)
    for ev in ctx.events:
        if ev["kind"] in p.get("kinds", []):
            by_ent[ev["entity_key"]].append(ev)
    for ek, evs in by_ent.items():
        d = _d(_gv(ctx, ek, p["field"]))
        if not d:
            continue
        bad = [ev for ev in evs if _d(ev["end_date"]) and _d(ev["end_date"]) > d and ev["hours"] > 0]
        if bad:
            parts = []
            for kind in sorted({ev["kind"] for ev in bad}):
                evs_k = [ev for ev in bad if ev["kind"] == kind]
                when = sorted({ev["start_date"] if ev["start_date"] == ev["end_date"]
                               else f"{ev['start_date']} to {ev['end_date']}" for ev in evs_k})
                parts.append(f"{kind} {sum(ev['hours'] for ev in evs_k):g} hours ({', '.join(when)})")
            recs = [r for r in ctx.entities[ek].records if r["record_key"] in {ev["record_key"] for ev in bad}]
            out.append(issue(p, "critical", "Working on an expired license",
                             f"{ctx.name(ek)}'s license expired on {d}, but they are " + " and ".join(parts)
                             + " after that date. This is a compliance risk, and these hours should not be "
                             "reported as licensed staffing.", ek, p["field"], recs, "after_expiry"))
    return out


@rule("stale")
def stale(ctx, p):
    out = []
    for r in ctx.records:
        d = _d(r["norm"].get(p["field"])) if r["source"] == p["source"] else None
        if d and (ctx.as_of - d).days > p.get("max_age_days", 90):
            out.append(issue(p, "warning", "Verification is out of date",
                             f"{ctx.name(r.get('entity_key'))}: last verified {d}, "
                             f"{(ctx.as_of - d).days} days ago (limit {p.get('max_age_days')}).",
                             r.get("entity_key"), p["field"], [r], r["record_key"]))
    return out


@rule("hours_reconcile")
def hours_reconcile(ctx, p):
    tol = p.get("tolerance", 0.5)
    sched, paid = defaultdict(list), defaultdict(list)
    for ev in ctx.events:
        if ev["kind"] == p["scheduled"]:
            sched[ev["entity_key"]].append(ev)
        elif ev["kind"] == p["paid"]:
            paid[ev["entity_key"]].append(ev)
    if not sched or not paid:
        return []
    out = []
    for ek in set(sched) & set(paid):
        covered = set()
        for pe in paid[ek]:
            s, e = _d(pe["start_date"]), _d(pe["end_date"])
            if not s or not e:
                continue
            within = [ev for ev in sched[ek] if s <= _d(ev["start_date"]) <= e]
            covered |= {id(ev) for ev in within}
            sh = sum(ev["hours"] for ev in within)
            if abs(sh - pe["hours"]) > tol:
                recs = [r for r in ctx.entities[ek].records
                        if r["record_key"] in {pe["record_key"]} | {ev["record_key"] for ev in within}]
                out.append(issue(p, "warning", "Scheduled hours do not match paid hours",
                                 f"{ctx.name(ek)}, {s} to {e}: scheduled {sh:g} hours, paid {pe['hours']:g} hours "
                                 f"(difference {pe['hours'] - sh:+g}).", ek, "hours", recs, f"{s}",
                                 {"scheduled": sh, "paid": pe["hours"]}))
        loose = [ev for ev in sched[ek] if id(ev) not in covered]
        if loose:
            out.append(issue(p, "warning", "Scheduled shifts with no pay period",
                             f"{ctx.name(ek)} is scheduled on {', '.join(sorted({ev['start_date'] for ev in loose}))} "
                             f"but no payroll period covers those dates.", ek, "hours",
                             [r for r in ctx.entities[ek].records if r["source"] == loose[0]["source"]], "uncovered"))
    return out


@rule("overtime")
def overtime(ctx, p):
    out = []
    for ev in ctx.events:
        if ev["kind"] != p["kind"]:
            continue
        s, e = _d(ev["start_date"]), _d(ev["end_date"])
        weeks = max(1.0, ((e - s).days + 1) / 7) if s and e else 1.0
        limit = p.get("max_hours", 40) * weeks
        if ev["hours"] > limit:
            out.append(issue(p, "info", "Overtime",
                             f"{ctx.name(ev['entity_key'])} was paid {ev['hours']:g} hours for {s} to {e}, "
                             f"over the {limit:g}-hour threshold.", ev["entity_key"], "hours", [], ev["record_key"]))
    return out


@rule("overlap")
def overlap(ctx, p):
    out = []
    by_ent = defaultdict(list)
    for ev in ctx.events:
        if ev["kind"] == p["kind"] and ev["start_ts"]:
            by_ent[ev["entity_key"]].append(ev)
    for ek, evs in by_ent.items():
        evs.sort(key=lambda x: x["start_ts"])
        for a, b in zip(evs, evs[1:]):
            if b["start_ts"] < a["end_ts"]:
                out.append(issue(p, "warning", "Double-booked shifts",
                                 f"{ctx.name(ek)} has overlapping shifts on {a['start_date']}: "
                                 f"{a['code']} at {ctx.label(a['source'], 'facility', a['facility'])} and "
                                 f"{b['code']} at {ctx.label(b['source'], 'facility', b['facility'])}.",
                                 ek, "shift", [], f"{a['start_ts']}|{b['start_ts']}"))
    return out


def run_rules(ctx) -> list[dict]:
    out = []
    for p in ctx.cfg.rules:
        fn = RULES.get(p.get("type"))
        if fn is None:
            out.append({"rule_id": "config", "severity": "warning", "title": "Unknown rule type in config",
                        "explanation": f"Rule type '{p.get('type')}' is not implemented.", "entity_key": None,
                        "field": None, "record_keys": [], "detail": str(p), "values": {}})
            continue
        try:
            out += fn(ctx, p)
        except Exception as e:  # noqa: BLE001 - one broken rule must not stop the others
            out.append({"rule_id": p.get("type"), "severity": "warning", "title": "Rule failed to run",
                        "explanation": f"{p.get('type')}: {e}", "entity_key": None, "field": None,
                        "record_keys": [], "detail": str(p), "values": {}})
    return out
