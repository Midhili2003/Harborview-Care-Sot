# Problems injected into fixtures/messy

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
