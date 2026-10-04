# Key decisions

## 1. A generic engine plus a business config

The engine in `sot/core` has no healthcare knowledge. It knows how to read tables and printed grids, normalize values, match records to a subject, pick a trusted value per field, and run rule types. Everything about Harborview is in `config/harborview.yaml`: which files exist, every spelling of each column, facility and role codes, nicknames, ID formats, which system wins for each field, and which checks to run with what thresholds.

**Why:** the brief asks for something Pulse Foundry can reuse for a client in a different industry. For a trucking company, the subject becomes a driver, the anchor system is the driver roster, the credential is a CDL with a medical card expiry, the schedule is a dispatch log, and the rules (`expiry`, `activity_after_expiry`, `hours_reconcile`, `overlap`, `field_conflict`) apply unchanged. That client needs a new YAML file, not new code.

## 2. Keep the raw data, with lineage on every record

Every input row is stored exactly as received, with its file and row or page reference. Normalized values sit alongside the raw values, never in place of them. Every issue links to the rows that caused it, and the dashboard shows them.

**Why:** the client said they are "never fully confident" in their numbers. Trust comes from being able to answer "where did this come from?" for any value.

## 3. One system defines who exists

HR is the anchor: an HR record creates a person. Every other system is matched to HR. Anyone found elsewhere but not in HR (for example, someone on payroll) becomes a visible orphan with a critical flag, rather than being quietly merged or dropped.

**Why:** a person on payroll who is not in HR is exactly the kind of thing a business needs to see, and only an anchor makes it detectable.

## 4. Match in order of certainty, and never guess silently

1. Decisions a human already made
2. The anchor key (employee ID)
3. Strong keys (license number links HR to the license service)
4. Fuzzy name similarity, with nicknames ("Marc" = "Marcus") and name order ("REYES, SOFIA") handled, plus facility and role as supporting evidence

At 90% or above the match is automatic. Between 75% and 90% the record is kept separate and a "possible match" issue asks a human. Below that it is unmatched. Each link stores its method and confidence.

**Why:** a wrong merge corrupts the golden record invisibly; a missed merge is visible and cheap to fix. In the practice data, payroll's "OKAFOR, J" scores 86% against James Okafor and is held for confirmation.

## 5. A trusted source per field, with disagreements kept visible

The golden record takes each field from the system that should own it: license expiration and type from the license service, contact details and hire date from HR, hours paid from payroll, hours scheduled from the schedule. Values from other systems that disagree are kept next to the trusted value and raised as a conflict.

**Why:** there is no single "best system", only a best system per fact. Showing the losing values means a reviewer can see the disagreement instead of having it resolved out of sight.

## 6. Rules as small generic types, configured per business

Rule types (`required`, `duplicate_key`, `field_conflict`, `expiry`, `activity_after_expiry`, `hours_reconcile`, `overlap`, and others) are short functions. The config creates instances, such as "compare license expiration between HR and the license service" or "warn 30 days before expiry". Each issue has a severity (critical, warning, info) and a plain-English explanation written for a manager, not a developer. A failing rule produces an issue instead of stopping the run.

## 7. Bad data becomes an issue, never a crash

Headers are matched by synonyms and loose matching, so reordered, renamed or extra columns still load. Encodings with a BOM, semicolon or tab separators, blank rows, Excel files and mixed date formats are handled. A missing required column is one critical issue for the file, not an error per row. The PDF loader tries ruled tables, then text-aligned tables, then rebuilds rows from plain text lines. It reads the facility from the page title and shift lengths from the footer note instead of hardcoding them. Unknown shift codes are flagged. The tests cover these cases.

**Why:** the real files are only revealed live at judging.

## 8. Human decisions are data too

A reviewer can confirm a possible match, keep records separate, mark an issue as **resolved** (someone dealt with it, such as taking a person off the schedule) or **accept it as-is** (the data is correct, such as a float aide who works at both sites). These are different statements, so they are recorded differently. Critical issues cannot be closed without a note saying what was done. Decisions are stored in their own table and re-applied on every ingest. Each ingest rebuilds everything else from the raw files, so the same files always produce the same result.

**Why:** a source of truth that forgets yesterday's fixes is a cleanup script, not a system.

## 9. Checks run "as of" a date

Expiry and staleness are measured from a configurable date (today by default). This makes results reproducible for testing and lets a manager look ahead ("what will have expired by next month?").

## How this addresses the three problems

**Quarterly staffing reports (CMS Payroll-Based Journal).** Payroll hours are linked to a verified person, role and facility, and the schedule gives the daily breakdown PBJ asks for. `report staffing` produces hours by facility and role, warns when open issues touch the people in the report, and leaves out hours worked on an expired license. What took weeks becomes a query, and confidence comes from the issue list being cleared first.

**Licenses and paperwork expiring.** The credential report lists every license by days left, using the license service as the trusted date, and shows shifts already scheduled after the expiry. In the practice data, it catches an RN scheduled two days after their license expired. Vendor paperwork fits the same model: a vendor is another subject with credentials and expiry dates, so it needs config, not new code.

**Slow referral handling.** None of the four files contain referral data, and we did not invent any. What the source of truth provides is the answer intake staff need first: which licensed staff, of which role, are working at which facility on which shift, verified and current. With that answer instant and trusted, a referral can be accepted or declined in minutes. Referrals would be added later as one more configured source, with the patient as a second subject type.

## What I would do next

Hand the review queue to the people who own each system, add more subject types (vendors, patients/referrals), add scheduled ingests from system exports, and track issue history over time to show whether data quality is improving.
