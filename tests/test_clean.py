from conftest import ROOT, issues


def test_clean_data_has_no_false_alarms(run):
    store, summary = run(ROOT / "fixtures/clean")
    bad = [i for i in issues(store) if i["severity"] in ("critical", "warning")]
    assert not bad, [i["explanation"] for i in bad]
    assert summary["entities"] == 10
    assert summary["match_methods"].get("unmatched", 0) == 0
