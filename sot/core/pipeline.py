"""Orchestration: ingest files -> store raw -> build (match, golden, events, rules)."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from .config import Config
from .golden import build_events, build_golden
from .ingest import ingest_files
from .match import resolve
from .rules import Context, run_rules
from .store import Store

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def fingerprint(i: dict) -> str:
    raw = f"{i['rule_id']}|{i.get('entity_key') or ''}|{i.get('field') or ''}|{i.get('detail') or ''}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def collect_files(paths) -> list[Path]:
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.is_file() and not f.name.startswith(".")
                    and f.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".db"}]
        elif p.is_file():
            out.append(p)
    return out


def ingest(cfg: Config, store: Store, paths, as_of: date | None = None) -> dict:
    files = collect_files(paths)
    records, file_issues, file_summary = ingest_files(cfg, files)
    store.replace_snapshot(records, file_issues, file_summary, as_of or date.today(), cfg.path)
    return build(cfg, store, as_of)


def build(cfg: Config, store: Store, as_of: date | None = None) -> dict:
    run = store.last_run()
    if as_of is None:
        as_of = date.fromisoformat(run["as_of"]) if run and run.get("as_of") else date.today()
    records = store.load_records()
    file_issues = store.load_file_issues()
    match_dec = {k: v["value"] for k, v in store.decisions("match").items()}
    dismissed = store.decisions("dismiss")

    entities, links, match_issues = resolve(cfg, records, match_dec)
    golden = {k: build_golden(cfg, e) for k, e in entities.items()}
    events = build_events(cfg, entities)
    missing_cols = {(i["file"], i["field"]) for i in file_issues if i["rule_id"] == "missing_column"}
    ctx = Context(cfg, records, entities, golden, events, as_of, missing_cols)
    issues = file_issues + match_issues + run_rules(ctx)

    seen = set()
    unique = []
    for i in issues:
        i["fingerprint"] = fingerprint(i)
        if i["fingerprint"] in seen:
            continue
        seen.add(i["fingerprint"])
        d = dismissed.get(i["fingerprint"])
        i["status"] = "dismissed" if d else "open"
        i["note"] = d["note"] if d else None
        unique.append(i)
    unique.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["rule_id"], ctx.name(i.get("entity_key"))))

    methods = Counter(l["method"] for l in links)
    open_issues = [i for i in unique if i["status"] == "open"]
    summary = {
        "as_of": as_of.isoformat(),
        "records_by_source": dict(Counter(r["source"] for r in records)),
        "files": json.loads(run["files"]) if run and run.get("files") else [],
        "entities": len(entities),
        "anchored_entities": sum(1 for e in entities.values() if e.origin == cfg.anchor),
        "match_methods": dict(methods),
        "issues_open": dict(Counter(i["severity"] for i in open_issues)),
        "issues_dismissed": sum(1 for i in unique if i["status"] == "dismissed"),
    }
    store.save_derived(links, entities, golden, events, unique, summary)
    return summary


# ---------------------------------------------------------------- human decisions

def _issue(store: Store, issue_id: int) -> dict:
    rows = store.query("SELECT * FROM issues WHERE id=?", (issue_id,))
    if not rows:
        raise ValueError(f"No issue with id {issue_id}")
    i = rows[0]
    i["vals"] = json.loads(i["vals"] or "{}")
    return i


def accept_match(cfg: Config, store: Store, issue_id: int, target: str | None = None, note: str = "") -> dict:
    """Confirm a possible match. Remembered for every future ingest."""
    i = _issue(store, issue_id)
    fp = i["vals"].get("fingerprint")
    target = target or (i["vals"].get("candidates") or [None])[0]
    if not fp or not target:
        raise ValueError("This issue is not a possible match")
    store.add_decision("match", fp, target, note)
    return build(cfg, store)


def reject_match(cfg: Config, store: Store, issue_id: int, note: str = "") -> dict:
    """Keep the records separate, and stop asking."""
    i = _issue(store, issue_id)
    fp = i["vals"].get("fingerprint")
    if not fp:
        raise ValueError("This issue is not a possible match")
    store.add_decision("match", fp, None, note)
    return build(cfg, store)


def dismiss(cfg: Config, store: Store, issue_id: int, note: str = "") -> dict:
    """Accept an issue as-is (e.g. 'float nurse, works at both sites'). Remembered across ingests."""
    i = _issue(store, issue_id)
    store.add_decision("dismiss", i["fingerprint"], True, note)
    return build(cfg, store)


def reopen(cfg: Config, store: Store, issue_id: int) -> dict:
    i = _issue(store, issue_id)
    store.remove_decision("dismiss", i["fingerprint"])
    return build(cfg, store)
