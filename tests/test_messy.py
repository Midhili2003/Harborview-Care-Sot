"""Every problem listed in fixtures/EXPECTED_ISSUES.md must be detected."""
from conftest import ROOT, issues

EXPECTED = [
    ("duplicate_key", "hr:E201"),
    ("unknown_column", None),
    ("renamed_column", None),
    ("field_conflict", "hr:E203"),        # license expiration
    ("expiry", "hr:E204"),
    ("activity_after_expiry", "hr:E204"),
    ("possible_match", None),
    ("expiry", "hr:E205"),
    ("invalid_value", "hr:E205"),         # ORIENT
    ("hours_reconcile", "hr:E206"),
    ("overtime", "hr:E206"),
    ("stale", "hr:E206"),
    ("field_conflict", "hr:E207"),        # role + name
    ("field_conflict", "hr:E208"),        # license number + facility
    ("required", "hr:E209"),
    ("future_date", "hr:E209"),
    ("missing_from", "hr:E210"),
    ("overlap", "hr:E210"),
    ("not_in_anchor", "payroll:roberto diaz"),
]


def test_all_expected_issues_found(run):
    store, summary = run(ROOT / "fixtures/messy")
    found = {(i["rule_id"], i["entity_key"]) for i in issues(store)}
    rules = {i["rule_id"] for i in issues(store)}
    missing = [(r, e) for r, e in EXPECTED if ((r, e) not in found if e else r not in rules)]
    assert not missing, f"not detected: {missing}"


def test_specific_conflicts(run):
    store, _ = run(ROOT / "fixtures/messy")
    titles = {(i["entity_key"], i["field"]) for i in issues(store) if i["rule_id"] == "field_conflict"}
    assert ("hr:E207", "Role") in titles
    assert ("hr:E208", "License number") in titles
    assert ("hr:E208", "Facility") in titles
    assert ("hr:E203", "License expiration") in titles


def test_nickname_matched_without_issue(run):
    store, _ = run(ROOT / "fixtures/messy")
    rec = store.query("SELECT entity_key, method FROM records WHERE source='schedule' AND raw LIKE '%Marc Bell%'")
    assert rec[0]["entity_key"] == "hr:E202"
    assert not [i for i in issues(store) if i["entity_key"] == "hr:E202"]


def test_golden_record_prefers_license_service(run):
    import json
    store, _ = run(ROOT / "fixtures/messy")
    g = json.loads(store.query("SELECT golden FROM entities WHERE entity_key='hr:E203'")[0]["golden"])
    assert g["license_expiration"]["value"] == "2027-01-31"
    assert g["license_expiration"]["source"] == "licenses"
    assert g["license_expiration"]["conflicts"][0]["value"] == "2027-06-30"


def test_every_issue_has_lineage(run):
    store, _ = run(ROOT / "fixtures/messy")
    import json
    for i in issues(store):
        assert i["explanation"]
        assert json.loads(i["record_keys"]) or i["file"] or i["rule_id"] in {"overlap", "overtime"}


def test_reingest_is_idempotent(run, cfg):
    from sot.core.pipeline import ingest
    from conftest import AS_OF
    store, s1 = run(ROOT / "fixtures/messy")
    s2 = ingest(cfg, store, [ROOT / "fixtures/messy"], AS_OF)
    assert s1["issues_open"] == s2["issues_open"]
    assert s1["entities"] == s2["entities"]
