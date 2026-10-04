"""Golden record (field-level survivorship) and time-based events."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from .config import Config


def _field_in(field: str) -> str:
    return "_display" if field == "display_name" else field


def build_golden(cfg: Config, entity) -> dict:
    """{field: {value, source, conflicts: [{source, value}]}} using the config's authority order."""
    out = {}
    for field, order in cfg.golden.items():
        f = _field_in(field)
        by_source: dict[str, Counter] = {}
        for r in entity.records:
            v = r["norm"].get(f)
            if v not in (None, ""):
                by_source.setdefault(r["source"], Counter())[v] += 1
        chosen, src = None, None
        for s in order:
            if s in by_source:
                chosen, src = by_source[s].most_common(1)[0][0], s
                break
        others = [{"source": s, "value": v} for s, c in by_source.items() for v in c if v != chosen]
        out[field] = {"value": chosen, "source": src, "conflicts": others}
    return out


def build_events(cfg: Config, entities: dict) -> list[dict]:
    events = []
    specs = {e["source"]: e for e in cfg.events}
    for e in entities.values():
        for r in e.records:
            spec = specs.get(r["source"])
            if not spec:
                continue
            n = r["norm"]
            base = {"entity_key": e.key, "kind": spec["kind"], "source": r["source"],
                    "record_key": r["record_key"], "facility": n.get("facility"), "role": n.get("role")}
            if "_shifts" in n:
                for s in n["_shifts"]:
                    if s.get("status") != "work":
                        continue
                    d = date.fromisoformat(s["date"])
                    st = datetime.combine(d, datetime.min.time()) + timedelta(hours=s["start"])
                    events.append({**base, "start_date": s["date"], "end_date": s["date"],
                                   "start_ts": st.isoformat(),
                                   "end_ts": (st + timedelta(hours=((s["end"] - s["start"]) % 24) or 24)).isoformat(),
                                   "hours": float(s["hours"]), "code": s["code"]})
            elif spec.get("start") and n.get(spec["start"]):
                events.append({**base, "start_date": n.get(spec["start"]),
                               "end_date": n.get(spec.get("end")) or n.get(spec["start"]),
                               "start_ts": None, "end_ts": None,
                               "hours": float(n.get(spec.get("hours")) or 0), "code": None})
    return events
