import json

from conftest import AS_OF, ROOT, issues
import pytest

from sot.core.pipeline import accept_match, close_issue, ingest, reject_match, reopen


def _possible(store):
    return [i for i in issues(store) if i["rule_id"] == "possible_match"][0]


def test_accept_match_persists_across_ingests(run, cfg):
    store, before = run(ROOT / "fixtures/messy")
    accept_match(cfg, store, _possible(store)["id"], note="confirmed")
    after = ingest(cfg, store, [ROOT / "fixtures/messy"], AS_OF)
    assert after["entities"] == before["entities"] - 1
    assert not [i for i in issues(store) if i["rule_id"] == "possible_match"]
    rec = store.query("SELECT entity_key, method FROM records WHERE source='payroll' AND raw LIKE '%OKAFOR, J%'")[0]
    assert rec == {"entity_key": "hr:E204", "method": "human_decision"}


def test_reject_match_keeps_separate_and_stops_asking(run, cfg):
    store, _ = run(ROOT / "fixtures/messy")
    reject_match(cfg, store, _possible(store)["id"])
    assert not [i for i in issues(store) if i["rule_id"] == "possible_match"]


def test_accept_as_is_persists(run, cfg):
    store, _ = run(ROOT / "fixtures/messy")
    target = [i for i in issues(store) if i["rule_id"] == "overtime"][0]
    close_issue(cfg, store, target["id"], "accepted", note="approved overtime")
    ingest(cfg, store, [ROOT / "fixtures/messy"], AS_OF)
    assert [i for i in issues(store, "accepted") if i["rule_id"] == "overtime" and i["note"] == "approved overtime"]


def test_critical_needs_a_note(run, cfg):
    store, _ = run(ROOT / "fixtures/messy")
    crit = [i for i in issues(store) if i["rule_id"] == "activity_after_expiry"][0]
    with pytest.raises(ValueError):
        close_issue(cfg, store, crit["id"], "resolved", note="  ")
    s = close_issue(cfg, store, crit["id"], "resolved", note="Removed from 09/17 and 09/18 shifts")
    assert s["issues_open"]["critical"] == 3
    assert s["issues_closed"] == {"resolved": 1}


def test_reopen(run, cfg):
    store, _ = run(ROOT / "fixtures/messy")
    target = [i for i in issues(store) if i["rule_id"] == "overlap"][0]
    close_issue(cfg, store, target["id"], "accepted", note="float aide")
    closed = [i for i in issues(store, "accepted")][0]
    reopen(cfg, store, closed["id"])
    assert [i for i in issues(store) if i["rule_id"] == "overlap"]
