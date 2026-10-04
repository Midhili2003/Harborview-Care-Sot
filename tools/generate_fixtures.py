"""Generate practice data in the same formats as the judging files.

fixtures/messy/  - realistic problems injected (listed in EXPECTED_ISSUES.md)
fixtures/clean/  - the same company with no problems (to test for false alarms)

Run:  python tools/generate_fixtures.py
"""
from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent / "fixtures"
DAYS = ["Mon 09/14", "Tue 09/15", "Wed 09/16", "Thu 09/17", "Fri 09/18", "Sat 09/19", "Sun 09/20"]
P_START, P_END = "2026-09-14", "2026-09-20"

# Clean truth: id, first, last, title, code, facility, fac_code, phone, license, exp, hire, schedule
PEOPLE = [
    ("E201", "Sofia", "Reyes", "Registered Nurse", "RN", "Harborview Bayside", "BYS", "718-555-0201",
     "RN-551203", "2027-05-31", "2020-03-02", ["7a-3p", "7a-3p", "OFF", "7a-7p", "OFF", "7a-3p", "OFF"]),
    ("E202", "Marcus", "Bell", "Certified Nursing Assistant", "CNA", "Harborview Riverdale", "RVD", "347-555-0202",
     "CNA-771045", "2026-12-31", "2022-09-12", ["3p-11p", "OFF", "3p-11p", "3p-11p", "3p-11p", "3p-11p", "OFF"]),
    ("E203", "Priya", "Natarajan", "Licensed Practical Nurse", "LPN", "Harborview Bayside", "BYS", "718-555-0203",
     "LPN-430918", "2027-06-30", "2021-01-18", ["OFF", "3p-11p", "3p-11p", "3p-11p", "3p-11p", "OFF", "3p-11p"]),
    ("E204", "James", "Okafor", "Registered Nurse", "RN", "Harborview Riverdale", "RVD", "347-555-0204",
     "RN-662781", "2027-09-16", "2019-06-03", ["7a-3p", "7a-3p", "OFF", "7a-3p", "7a-3p", "OFF", "OFF"]),
    ("E205", "Linda", "Chen", "Certified Nursing Assistant", "CNA", "Harborview Bayside", "BYS", "718-555-0205",
     "CNA-880231", "2027-10-10", "2023-02-27", ["11p-7a", "11p-7a", "11p-7a", "OFF", "OFF", "11p-7a", "11p-7a"]),
    ("E206", "Daniel", "Brooks", "Registered Nurse", "RN", "Harborview Bayside", "BYS", "718-555-0206",
     "RN-553871", "2028-02-29", "2018-11-05", ["OFF", "7a-7p", "OFF", "7a-7p", "OFF", "7a-7p", "OFF"]),
    ("E207", "Angela", "Torres", "Licensed Practical Nurse", "LPN", "Harborview Riverdale", "RVD", "347-555-0207",
     "LPN-551877", "2027-04-30", "2022-04-11", ["7a-3p", "7a-3p", "7a-3p", "OFF", "OFF", "7a-3p", "7a-3p"]),
    ("E208", "Kevin", "Walsh", "Certified Nursing Assistant", "CNA", "Harborview Riverdale", "RVD", "347-555-0208",
     "CNA-772210", "2027-01-31", "2024-08-19", ["11p-7a", "OFF", "11p-7a", "11p-7a", "11p-7a", "11p-7a", "OFF"]),
    ("E209", "Grace", "Kim", "Registered Nurse", "RN", "Harborview Riverdale", "RVD", "347-555-0209",
     "RN-664120", "2027-11-30", "2025-01-06", ["3p-11p", "3p-11p", "OFF", "OFF", "3p-11p", "3p-11p", "3p-11p"]),
    ("E210", "Thomas", "Wright", "Certified Nursing Assistant", "CNA", "Harborview Bayside", "BYS", "718-555-0210",
     "CNA-881907", "2027-07-31", "2026-09-14", ["7a-3p", "7a-3p", "7a-3p", "7a-3p", "7a-3p", "OFF", "OFF"]),
]
HOURS = {"7a-3p": 8, "3p-11p": 8, "11p-7a": 8, "7a-7p": 12}
NOTE = "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."


def hours(sched):
    return sum(HOURS.get(s, 0) for s in sched)


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_schedule_pdf(path, pages):
    """pages: [(facility_title, [(name, role, [7 cells])])]"""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(letter), topMargin=36, bottomMargin=36)
    story = []
    for n, (title, rows) in enumerate(pages):
        story += [Paragraph(title, styles["Title"]),
                  Paragraph("Weekly Staff Schedule, week of Mon 09/14", styles["Normal"]), Spacer(1, 14)]
        data = [["Staff", "Role"] + DAYS] + [[nm, rl] + cells for nm, rl, cells in rows]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                               ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        story += [t, Spacer(1, 16), Paragraph(NOTE, styles["Italic"])]
        if n < len(pages) - 1:
            story.append(PageBreak())
    doc.build(story)


def build(variant: str):
    out = ROOT / variant
    messy = variant == "messy"
    people = [list(p) for p in PEOPLE]

    # ---------------- HR ----------------
    hr_header = ["employee_id", "first_name", "last_name", "job_title", "facility", "phone",
                 "license_number", "license_expiration", "hire_date"]
    hr = []
    for p in people:
        pid, first, last, title, code, fac, fcode, phone, lic, exp, hire, _ = p
        row = [pid, first, last, title, fac, phone, lic, exp, hire]
        if messy:
            if pid == "E204":
                row[7] = "2026-09-16"                       # expired license (agrees with license service)
            if pid == "E205":
                row[7] = "2026-10-10"                       # expiring within 30 days
            if pid == "E207":
                row[3] = "Registered Nurse"                 # HR says RN, license is LPN
            if pid == "E209":
                row[4] = ""                                 # missing facility
                row[8] = "2026-11-02"                       # hire date in the future
            if pid == "E210":
                row[8] = "09/14/2026"                       # non-ISO date
            if pid == "E203":
                row[5] = "(718) 555-0203"                   # different phone formatting (harmless)
        hr.append(row)
    if messy:
        hr_header.append("emergency_contact")              # unexpected extra column
        hr = [r + [""] for r in hr]
        hr.insert(1, hr[0][:])                              # duplicate E201 row (double export)
        hr.insert(6, [""] * len(hr_header))                 # blank row
    write_csv(out / "hr_roster.csv", hr_header, hr)

    # ---------------- Payroll ----------------
    pay_header = ["payroll_id", "employee_name", "job_code", "facility_code", "period_start", "period_end", "hours_paid"]
    pay = []
    n = 3001
    for p in people:
        pid, first, last, title, code, fac, fcode, *_ , sched = p
        name = f"{last.upper()}, {first.upper()}"
        h = hours(sched)
        if messy:
            if pid == "E210":
                continue                                    # new hire missing from payroll
            if pid == "E204":
                name = "OKAFOR, J"                          # ambiguous name -> needs human confirmation
            if pid == "E206":
                h = 44                                      # scheduled 36, paid 44 (+ overtime)
            if pid == "E208":
                fcode = "BYS"                               # HR and schedule say Riverdale
            if pid == "E204":
                pass
        pay.append([f"P-{n}", name, code, fcode, P_START, P_END, h])
        n += 1
    if messy:
        pay.append([f"P-{n}", "DIAZ, ROBERTO", "CNA", "RVD", P_START, P_END, 24])  # not in HR
        pay_header[3] = "Site"                              # renamed column
    write_csv(out / "payroll.csv", pay_header, pay)

    # ---------------- Licenses ----------------
    lic_header = ["license_number", "name_on_license", "license_type", "expiration_date", "last_verified"]
    lic = []
    for p in people:
        pid, first, last, title, code, fac, fcode, phone, number, exp, *_ = p
        name, verified = f"{last.upper()}, {first.upper()}", "2026-09-01"
        if messy:
            if pid == "E203":
                exp = "2027-01-31"                          # HR says 2027-06-30
            if pid == "E204":
                exp = "2026-09-16"                          # expired
            if pid == "E205":
                exp = "2026-10-10"
            if pid == "E206":
                verified = "2026-06-15"                     # stale verification
            if pid == "E207":
                name = "TORRES-RUIZ, ANGELA"                # name differs from HR
            if pid == "E208":
                number = "CNA-772201"                       # transposed digits vs HR
        lic.append([number, name, code, exp, verified])
    write_csv(out / "licenses.csv", lic_header, lic)

    # ---------------- Schedule PDF ----------------
    pages = {"BYS": ("Harborview Bayside", []), "RVD": ("Harborview Riverdale", [])}
    for p in people:
        pid, first, last, title, code, fac, fcode, *_, sched = p
        sched = list(sched)
        display = f"{first} {last}"
        if messy:
            if pid == "E202":
                display = "Marc Bell"                       # nickname
            if pid == "E205":
                sched[5] = "ORIENT"                         # unknown schedule code
            if pid == "E210":
                pages["RVD"][1].append(("Tom Wright", "CNA", ["OFF", "OFF", "OFF", "OFF", "7a-3p", "OFF", "OFF"]))
                # double-booked Friday at both sites
        pages[fcode][1].append((display, code, sched))
    write_schedule_pdf(out / "staff_schedule.pdf", list(pages.values()))
    print(f"wrote {out}")


EXPECTED = """# Problems injected into fixtures/messy

Use `--as-of 2026-09-21` when ingesting so the time-based checks are reproducible.

| # | Problem | Who | Expected rule |
|---|---|---|---|
| 1 | Duplicate HR row (double export) | E201 Sofia Reyes | duplicate_key |
| 2 | Blank row in HR file | (file) | ignored silently |
| 3 | Unexpected extra column `emergency_contact` | (file) | unknown_column |
| 4 | Payroll column renamed `facility_code` -> `Site` | (file) | renamed_column (still mapped) |
| 5 | Nickname on schedule: "Marc Bell" vs "Marcus Bell" | E202 | matched automatically, no issue |
| 6 | HR and license service disagree on expiration | E203 Priya Natarajan | field_conflict (License expiration) |
| 7 | Phone written as (718) 555-0203 | E203 | normalised, no issue |
| 8 | License expired 2026-09-16 | E204 James Okafor | expiry (critical) |
| 9 | Scheduled after license expired (09/17, 09/18) | E204 | activity_after_expiry (critical) |
| 10 | Payroll name "OKAFOR, J" is ambiguous | E204 | possible_match -> needs confirmation |
| 11 | License expires 2026-10-10 | E205 Linda Chen | expiry (warning, within 30 days) |
| 12 | Unknown schedule code "ORIENT" | E205 | invalid_value |
| 13 | Scheduled hours vs paid hours differ (36 vs 44) | E206 Daniel Brooks | hours_reconcile |
| 14 | Paid 44 hours | E206 | overtime (info) |
| 15 | License verification is 98 days old | E206 | stale |
| 16 | HR says RN, license says LPN | E207 Angela Torres | field_conflict (Role) |
| 17 | Name on license "TORRES-RUIZ, ANGELA" | E207 | field_conflict (Name, info) |
| 18 | License number typo CNA-772210 vs CNA-772201 | E208 Kevin Walsh | field_conflict (License number) |
| 19 | Payroll facility BYS, HR + schedule say Riverdale | E208 | field_conflict (Facility) |
| 20 | Missing facility in HR | E209 Grace Kim | required |
| 21 | Hire date in the future | E209 | future_date |
| 22 | Hire date written 09/14/2026 | E210 Thomas Wright | invalid_value (info: non-standard date) |
| 23 | New hire not in payroll | E210 | missing_from (payroll) |
| 24 | Scheduled at both sites at the same time Friday | E210 | overlap |
| 25 | "DIAZ, ROBERTO" paid but not in HR | (payroll only) | not_in_anchor (critical) |
"""

if __name__ == "__main__":
    build("messy")
    build("clean")
    (ROOT / "EXPECTED_ISSUES.md").write_text(EXPECTED, encoding="utf-8")
