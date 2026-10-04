"""SQLite persistence. Raw records keep full lineage; derived tables are rebuilt on every build."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, as_of TEXT,
    config TEXT, files TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS records (record_key TEXT PRIMARY KEY, source TEXT, file TEXT, row_ref TEXT,
    raw TEXT, norm TEXT, errors TEXT, entity_key TEXT, method TEXT, confidence REAL);
CREATE TABLE IF NOT EXISTS file_issues (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT);
CREATE TABLE IF NOT EXISTS entities (entity_key TEXT PRIMARY KEY, origin TEXT, display_name TEXT,
    sources TEXT, golden TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_key TEXT, kind TEXT,
    source TEXT, record_key TEXT, start_date TEXT, end_date TEXT, start_ts TEXT, end_ts TEXT,
    hours REAL, facility TEXT, role TEXT, code TEXT);
CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT, rule_id TEXT,
    severity TEXT, title TEXT, explanation TEXT, entity_key TEXT, field TEXT, record_keys TEXT,
    file TEXT, vals TEXT, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, key TEXT,
    value TEXT, note TEXT, created_at TEXT);
"""

DERIVED = ["entities", "events", "issues"]


class Store:
    def __init__(self, path: str | Path = "sot.db"):
        self.path = str(path)
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    # ---- snapshot (raw) ----
    def replace_snapshot(self, records, file_issues, summary, as_of, config_path):
        cur = self.con.cursor()
        for t in ["records", "file_issues"] + DERIVED:
            cur.execute(f"DELETE FROM {t}")
        cur.executemany(
            "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r["record_key"], r["source"], r["file"], r["row_ref"], json.dumps(r["raw"]),
              json.dumps(r["norm"]), json.dumps(r["errors"]), None, None, None) for r in records])
        cur.executemany("INSERT INTO file_issues (data) VALUES (?)", [(json.dumps(i),) for i in file_issues])
        cur.execute("INSERT INTO runs (started_at, as_of, config, files, summary) VALUES (?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), as_of.isoformat() if as_of else None,
                     str(config_path), json.dumps(summary), "{}"))
        self.con.commit()

    def load_records(self):
        rows = self.con.execute("SELECT * FROM records ORDER BY rowid").fetchall()
        return [{"record_key": r["record_key"], "source": r["source"], "file": r["file"], "row_ref": r["row_ref"],
                 "raw": json.loads(r["raw"]), "norm": json.loads(r["norm"]),
                 "errors": [tuple(e) for e in json.loads(r["errors"])]} for r in rows]

    def load_file_issues(self):
        return [json.loads(r["data"]) for r in self.con.execute("SELECT data FROM file_issues")]

    def last_run(self):
        r = self.con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    # ---- derived ----
    def save_derived(self, links, entities, golden, events, issues, summary):
        cur = self.con.cursor()
        for t in DERIVED:
            cur.execute(f"DELETE FROM {t}")
        cur.executemany("UPDATE records SET entity_key=?, method=?, confidence=? WHERE record_key=?",
                        [(l["entity_key"], l["method"], l["confidence"], l["record_key"]) for l in links])
        cur.executemany("INSERT INTO entities VALUES (?,?,?,?,?)",
                        [(k, e.origin, (golden[k].get("display_name") or {}).get("value") or k,
                          json.dumps(sorted(e.sources())), json.dumps(golden[k])) for k, e in entities.items()])
        cur.executemany(
            "INSERT INTO events (entity_key, kind, source, record_key, start_date, end_date, start_ts, end_ts, "
            "hours, facility, role, code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(e["entity_key"], e["kind"], e["source"], e["record_key"], e["start_date"], e["end_date"],
              e["start_ts"], e["end_ts"], e["hours"], e["facility"], e["role"], e["code"]) for e in events])
        cur.executemany(
            "INSERT INTO issues (fingerprint, rule_id, severity, title, explanation, entity_key, field, "
            "record_keys, file, vals, status, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(i["fingerprint"], i["rule_id"], i["severity"], i["title"], i["explanation"], i.get("entity_key"),
              i.get("field"), json.dumps(i.get("record_keys", [])), i.get("file"), json.dumps(i.get("values", {})),
              i["status"], i.get("note")) for i in issues])
        cur.execute("UPDATE runs SET summary=? WHERE id=(SELECT MAX(id) FROM runs)", (json.dumps(summary),))
        self.con.commit()

    # ---- decisions ----
    def add_decision(self, kind, key, value=None, note=""):
        self.con.execute("DELETE FROM decisions WHERE kind=? AND key=?", (kind, key))
        self.con.execute("INSERT INTO decisions (kind, key, value, note, created_at) VALUES (?,?,?,?,?)",
                         (kind, key, json.dumps(value), note, datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def remove_decision(self, kind, key):
        self.con.execute("DELETE FROM decisions WHERE kind=? AND key=?", (kind, key))
        self.con.commit()

    def decisions(self, kind):
        return {r["key"]: {"value": json.loads(r["value"]), "note": r["note"]}
                for r in self.con.execute("SELECT * FROM decisions WHERE kind=?", (kind,))}

    def reset(self, keep_decisions=False):
        for t in ["runs", "records", "file_issues"] + DERIVED + ([] if keep_decisions else ["decisions"]):
            self.con.execute(f"DELETE FROM {t}")
        self.con.commit()

    def query(self, sql, params=()):
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]
