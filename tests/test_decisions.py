import json

from conftest import AS_OF, ROOT, issues
from sot.core.pipeline import accept_match, dismiss, ingest, reject_match


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


def test_dismiss_persists(run, cfg):
    store, _ = run(ROOT / "fixtures/messy")
    target = [i for i in issues(store) if i["rule_id"] == "overtime"][0]
    dismiss(cfg, store, target["id"], note="approved overtime")
    ingest(cfg, store, [ROOT / "fixtures/messy"], AS_OF)
    d = issues(store, "dismissed")
    assert [i for i in d if i["rule_id"] == "overtime" and i["note"] == "approved overtime"]
