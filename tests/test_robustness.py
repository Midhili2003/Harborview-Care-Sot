"""Judging-day insurance: the pipeline must survive messy file layouts."""
import csv
import shutil

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from conftest import ROOT, issues


def _copy(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(ROOT / "fixtures/messy", d)
    return d


def test_shuffled_columns_bom_semicolons_blank_rows(run, tmp_path):
    d = _copy(tmp_path)
    df = pd.read_csv(d / "hr_roster.csv", dtype=str, keep_default_na=False)
    df = df[list(reversed(df.columns))]
    df.columns = [c.replace("_", " ").title() for c in df.columns]   # "License Expiration"
    text = df.to_csv(index=False, sep=";")
    (d / "hr_roster.csv").write_text("\ufeff" + text + ";;;;;;;;;\n\n", encoding="utf-8")
    store, s = run(d)
    assert s["records_by_source"]["hr"] == 11
    assert {i["rule_id"] for i in issues(store)} >= {"expiry", "activity_after_expiry", "duplicate_key"}


def test_missing_required_column_is_flagged_not_crashing(run, tmp_path):
    d = _copy(tmp_path)
    df = pd.read_csv(d / "payroll.csv", dtype=str)
    df.drop(columns=["hours_paid"]).to_csv(d / "payroll.csv", index=False)
    store, _ = run(d)
    assert [i for i in issues(store) if i["rule_id"] == "missing_column" and i["field"] == "hours"]


def test_excel_and_unrecognised_files(run, tmp_path):
    d = _copy(tmp_path)
    pd.read_csv(d / "licenses.csv", dtype=str).to_excel(d / "licenses.xlsx", index=False)
    (d / "licenses.csv").unlink()
    (d / "notes.csv").write_text("foo,bar\n1,2\n")
    store, s = run(d)
    assert s["records_by_source"]["licenses"] == 10
    assert [i for i in issues(store) if i["rule_id"] == "unrecognised_file"]


def test_weird_values(run, tmp_path):
    d = _copy(tmp_path)
    rows = list(csv.reader(open(d / "payroll.csv")))
    rows[1][6] = "thirty"
    rows[2][4] = "2026-02-30"
    rows[3][6] = "-5"
    csv.writer(open(d / "payroll.csv", "w", newline="")).writerows(rows)
    store, _ = run(d)
    rules = [i["rule_id"] for i in issues(store)]
    assert rules.count("invalid_value") >= 3
    assert "numeric_range" in rules


def test_pdf_without_table_lines(run, tmp_path):
    """A schedule printed as plain text (no ruled table) still parses."""
    d = _copy(tmp_path)
    c = canvas.Canvas(str(d / "staff_schedule.pdf"), pagesize=letter)
    y = 740
    for line in ["Harborview Bayside", "Weekly Staff Schedule 2026",
                 "Staff Role Mon 09/14 Tue 09/15 Wed 09/16 Thu 09/17 Fri 09/18 Sat 09/19 Sun 09/20",
                 "Sofia Reyes RN 7a-3p 7a-3p OFF 7a-7p OFF 7a-3p OFF",
                 "Daniel Brooks RN OFF 7a-7p OFF 7a-7p OFF 7a-7p OFF",
                 "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."]:
        c.drawString(40, y, line)
        y -= 22
    c.save()
    store, s = run(d)
    assert s["records_by_source"]["schedule"] == 2
    ev = store.query("SELECT SUM(hours) h FROM events WHERE kind='scheduled' AND entity_key='hr:E201'")
    assert ev[0]["h"] == 36


def test_empty_folder(run, tmp_path):
    (tmp_path / "empty").mkdir()
    store, s = run(tmp_path / "empty")
    assert s["entities"] == 0
