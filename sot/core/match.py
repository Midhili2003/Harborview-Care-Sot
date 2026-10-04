"""Entity resolution: decide which records from different systems are the same subject.

Order: saved human decisions -> anchor key -> strong keys -> fuzzy name with
supporting evidence. Low-confidence matches are never merged silently.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .config import Config


def record_fingerprint(r: dict) -> str:
    """Stable identity of a record for remembering human decisions across ingests."""
    n = r["norm"]
    return f"{r['source']}|{n.get('_name_key', '')}|{n.get('facility') or ''}|{n.get('role') or ''}"


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    af, _, al = a.partition(" ")
    bf, _, bl = b.partition(" ")
    if al and al == bl and af and bf and (af.startswith(bf) or bf.startswith(af)) and min(len(af), len(bf)) >= 3:
        return 0.93
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) / 100.0


class Entity:
    def __init__(self, key: str, origin: str):
        self.key = key
        self.origin = origin
        self.records: list[dict] = []
        self.names: set[str] = set()
        self.support: dict[str, set] = {}

    def attach(self, r: dict, support_fields):
        self.records.append(r)
        if r["norm"].get("_name_key"):
            self.names.add(r["norm"]["_name_key"])
        for f in support_fields:
            v = r["norm"].get(f)
            if v:
                self.support.setdefault(f, set()).add(v)

    def sources(self) -> set:
        return {r["source"] for r in self.records}


def resolve(cfg: Config, records: list[dict], match_decisions: dict | None = None):
    """Returns (entities: dict key->Entity, links: list, issues: list)."""
    match_decisions = match_decisions or {}
    ent_cfg = cfg.entity
    anchor = cfg.anchor
    anchor_key = ent_cfg.get("anchor_key")
    support = ent_cfg.get("support_fields", [])
    th = ent_cfg.get("thresholds", {})
    auto, review = th.get("auto", 0.9), th.get("review", 0.75)
    entities: dict[str, Entity] = {}
    links, issues = [], []

    def link(r, e: Entity, method, conf):
        e.attach(r, support)
        r["entity_key"] = e.key
        links.append({"record_key": r["record_key"], "entity_key": e.key, "method": method,
                      "confidence": round(conf, 3)})

    # 1. anchor records define entities
    for r in [r for r in records if r["source"] == anchor]:
        kv = r["norm"].get(anchor_key)
        key = f"{anchor}:{kv}" if kv else f"{anchor}:name:{r['norm'].get('_name_key') or r['record_key']}"
        e = entities.setdefault(key, Entity(key, anchor))
        link(r, e, "anchor_key" if kv else "anchor_name", 1.0)

    # 2. strong key indexes built from anchor records
    key_index: dict[tuple, str] = {}
    for spec in ent_cfg.get("strong_keys", []):
        f = spec["field"]
        for e in entities.values():
            for r in e.records:
                v = r["norm"].get(f)
                if v:
                    key_index.setdefault((f, v), e.key)

    def score(r, e: Entity) -> float:
        nk = r["norm"].get("_name_key", "")
        s = max((name_similarity(nk, n) for n in e.names), default=0.0)
        if s == 0:
            return 0.0
        for f in support:
            v = r["norm"].get(f)
            if v and e.support.get(f):
                s += 0.03 if v in e.support[f] else -0.05
        return max(0.0, min(1.0, s))

    others = [s for s in cfg.sources if s != anchor]
    for source in others:
        keyed_fields = [sp["field"] for sp in ent_cfg.get("strong_keys", []) if source in sp.get("sources", [])]
        for r in [r for r in records if r["source"] == source]:
            fp = record_fingerprint(r)
            # a. a human already decided
            if fp in match_decisions:
                target = match_decisions[fp]
                if target and target in entities:
                    link(r, entities[target], "human_decision", 1.0)
                    continue
                if target is None:
                    key = f"{source}:{r['norm'].get('_name_key') or r['record_key']}"
                    link(r, entities.setdefault(key, Entity(key, source)), "human_kept_separate", 1.0)
                    continue
            # b. strong key
            hit = next((key_index[(f, r["norm"].get(f))] for f in keyed_fields
                        if r["norm"].get(f) and (f, r["norm"].get(f)) in key_index), None)
            if hit:
                link(r, entities[hit], "strong_key", 1.0)
                continue
            # c. fuzzy name
            scored = sorted(((score(r, e), e) for e in entities.values()), key=lambda t: -t[0])
            best_s, best_e = scored[0] if scored else (0.0, None)
            runner = scored[1][0] if len(scored) > 1 else 0.0
            ambiguous = best_s >= review and runner >= review and best_s - runner < 0.03 \
                and scored[1][1].key != best_e.key
            if best_e is not None and best_s >= auto and not ambiguous:
                link(r, best_e, "fuzzy_name", best_s)
                continue
            key = f"{source}:{r['norm'].get('_name_key') or r['record_key']}"
            orphan = entities.setdefault(key, Entity(key, source))
            link(r, orphan, "unmatched", 0.0)
            if best_e is not None and best_s >= review:
                cand = [e for s_, e in scored if s_ >= review][:3]
                issues.append({
                    "rule_id": "possible_match", "severity": "warning",
                    "title": "Possible match needs confirmation",
                    "explanation": (f"{cfg.source_label(source)} record '{r['raw'].get('name') or r['norm'].get('_display')}' "
                                    f"looks like an existing {cfg.business.get('entity_label', 'record').lower()} "
                                    f"({best_s:.0%} similar){' but several are close' if ambiguous else ''}. "
                                    f"It is kept separate until someone confirms."),
                    "entity_key": key, "field": None, "record_keys": [r["record_key"]],
                    "detail": fp,
                    "values": {"fingerprint": fp, "candidates": [c.key for c in cand], "score": round(best_s, 3)},
                })
    return entities, links, issues
