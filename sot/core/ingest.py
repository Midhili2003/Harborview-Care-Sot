"""Turn files into normalized records.

Two generic loaders:
  * table     - CSV / TSV / Excel with fuzzy header mapping
  * pdf_grid  - a printed roster/schedule: one row per person, one column per day
Nothing here raises on bad data. Problems become issues.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .config import Config
from .normalize import (clean, header_key, is_non_iso_date, parse_date, parse_identifier,
                        parse_number, parse_phone, simplify)

TABLE_EXT = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}


def file_issue(rule_id, severity, title, explanation, file, field=None):
    return {"rule_id": rule_id, "severity": severity, "title": title, "explanation": explanation,
            "file": file, "field": field, "entity_key": None, "record_keys": [], "detail": file}


# ---------------------------------------------------------------- normalizing

def normalize_fields(cfg: Config, source: str, raw: dict) -> tuple[dict, list]:
    """raw: canonical field -> raw string. Returns normalized dict and [(field, message)]."""
    spec = cfg.sources[source]["fields"]
    norm, errors = {}, []
    first = last = full = None
    for field, fs in spec.items():
        value = raw.get(field, "")
        ftype = fs.get("type", "string")
        out, err = None, None
        if ftype == "date":
            d, err = parse_date(value, cfg.date_order)
            out = d.isoformat() if d else None
            if d and is_non_iso_date(value):
                norm.setdefault("_reformatted", []).append(field)
        elif ftype == "number":
            out, err = parse_number(value)
        elif ftype == "phone":
            out, err = parse_phone(value)
        elif ftype.startswith("identifier"):
            ident = cfg.identifiers.get(ftype.split(":", 1)[1], {}) if ":" in ftype else {}
            out, err = parse_identifier(value, ident.get("pattern"), ident.get("dash", False))
        elif ftype.startswith("code:"):
            cm = cfg.code_maps.get(ftype.split(":", 1)[1])
            out, err = cm.parse(value) if cm else (clean(value) or None, None)
        elif ftype == "first_name":
            first = clean(value)
            out = first or None
        elif ftype == "last_name":
            last = clean(value)
            out = last or None
        elif ftype == "person_name":
            full = clean(value)
            out = full or None
        else:
            out = clean(value) or None
        norm[field] = out
        if err:
            errors.append((field, err))
    if full is not None:
        f, l = cfg.names.split(full)
        norm.update(cfg.names.build(f, l))
    elif first is not None or last is not None:
        norm.update(cfg.names.build(first or "", last or ""))
    return norm, errors


# ---------------------------------------------------------------- detection

def _alias_keys(fs: dict, field: str) -> set:
    return {header_key(a) for a in [field] + list(fs.get("aliases", []))}


def map_headers(cfg: Config, source: str, headers: list[str]):
    """Return {canonical_field: original_header}, unknown headers."""
    spec = cfg.sources[source]["fields"]
    mapping, used = {}, set()
    keys = {h: header_key(h) for h in headers}
    for field, fs in spec.items():
        aliases = _alias_keys(fs, field)
        for h in headers:  # exact alias first
            if h not in used and keys[h] in aliases:
                mapping[field] = h
                used.add(h)
                break
    for field, fs in spec.items():  # then loose contains-match for leftovers
        if field in mapping:
            continue
        aliases = [a for a in _alias_keys(fs, field) if len(a) > 4]
        for h in headers:
            if h not in used and keys[h] and any(a in keys[h] or keys[h] in a for a in aliases):
                mapping[field] = h
                used.add(h)
                break
    unknown = [h for h in headers if h not in used and clean(h)]
    return mapping, unknown


def detect_table_source(cfg: Config, headers: list[str]):
    best, best_score = None, 0.0
    for source, sc in cfg.sources.items():
        if sc.get("loader") != "table":
            continue
        mapping, _ = map_headers(cfg, source, headers)
        fields = sc["fields"]
        req = [f for f, fs in fields.items() if fs.get("required")]
        score = len(mapping) / len(fields)
        if req:
            score = 0.5 * score + 0.5 * (sum(f in mapping for f in req) / len(req))
        if score > best_score:
            best, best_score = source, score
    return (best, best_score) if best_score >= 0.45 else (None, best_score)


# ---------------------------------------------------------------- table loader

def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False,
                       skip_blank_lines=True, on_bad_lines="warn", engine="python")


def load_table(cfg: Config, path: Path, source: str | None = None):
    issues, records = [], []
    try:
        df = read_table(path)
    except Exception as e:  # noqa: BLE001
        return None, [], [file_issue("unreadable_file", "critical", "File could not be read",
                                     f"{path.name} could not be opened: {e}", path.name)]
    headers = [str(c) for c in df.columns]
    if source is None:
        source, score = detect_table_source(cfg, headers)
        if source is None:
            return None, [], [file_issue("unrecognised_file", "warning", "File type not recognised",
                                         f"{path.name} does not match any configured source "
                                         f"(best match {score:.0%}). It was not ingested.", path.name)]
    mapping, unknown = map_headers(cfg, source, headers)
    spec = cfg.sources[source]["fields"]
    for f, fs in spec.items():
        if fs.get("required") and f not in mapping:
            issues.append(file_issue("missing_column", "critical", f"Missing column: {f}",
                                     f"{path.name} has no column for '{f}'. Every record from this file "
                                     f"will be missing it.", path.name, f))
    renamed = [f"'{h}' read as '{f}'" for f, h in mapping.items() if header_key(h) != header_key(f)
               and header_key(h) not in {header_key(a) for a in spec[f].get("aliases", [])[:1]}]
    if renamed:
        issues.append(file_issue("renamed_column", "info", "Columns matched by a different name",
                                 f"In {path.name}: " + "; ".join(renamed) + ".", path.name))
    for h in unknown:
        issues.append(file_issue("unknown_column", "info", f"Unexpected column: {h}",
                                 f"{path.name} has a column '{h}' that is not part of the configured layout. "
                                 f"It is kept with the raw data but not used.", path.name, h))
    for i, row in df.iterrows():
        values = {h: clean(row[h]) for h in df.columns}
        if not any(values.values()):
            continue
        raw = {f: values.get(h, "") for f, h in mapping.items()}
        norm, errors = normalize_fields(cfg, source, raw)
        records.append({"source": source, "file": path.name, "row_ref": f"row {i + 2}",
                        "raw": {str(k): v for k, v in values.items()}, "norm": norm, "errors": errors})
    return source, records, issues


# ---------------------------------------------------------------- pdf grid loader

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m?\.?"
SHIFT_RE = re.compile(rf"^{_TIME}\s*(?:-|–|—|to)\s*{_TIME}$", re.I)
SHIFT24_RE = re.compile(r"^(\d{1,2}):?(\d{2})\s*(?:-|–|—|to)\s*(\d{1,2}):?(\d{2})$")
DAY_RE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?")


def shift_key(code: str) -> str:
    return re.sub(r"\s+", "", code.lower()).replace("–", "-").replace("—", "-")


def parse_shift(code: str):
    """'7a-3p' -> (start_hour_float, end_hour_float)."""
    s = clean(code)
    m = SHIFT_RE.match(s)
    if m:
        def h(hh, mm, ap):
            v = int(hh) % 12 + (12 if ap.lower() == "p" else 0)
            return v + (int(mm) / 60 if mm else 0)
        return h(*m.group(1, 2, 3)), h(*m.group(4, 5, 6))
    m = SHIFT24_RE.match(s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60, int(m.group(3)) + int(m.group(4)) / 60
    return None


def parse_legend(text: str) -> dict:
    """'Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours.' -> {code: hours}."""
    legend = {}
    token = re.compile(rf"{_TIME}\s*(?:-|–|—|to)\s*{_TIME}", re.I)
    for sentence in re.split(r"(?<=[a-z])\.\s+|\n|;", text, flags=re.I):
        hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours|hrs|hr|h)\b", sentence, re.I)
        if not hm:
            continue
        for t in token.finditer(sentence):
            legend[shift_key(t.group(0))] = float(hm.group(1))
    return legend


def _find_facility(cfg: Config, text: str):
    for line in text.splitlines()[:6]:
        cm = cfg.code_maps.get("facility")
        if cm and clean(line):
            code, err = cm.parse(line)
            if not err:
                return code, clean(line)
    return None, None


def _with_day_header(table):
    """Trim a table so it starts at the row holding the day columns; None if there is none."""
    for i, row in enumerate(table[:5]):
        if sum(1 for c in row if c and DAY_RE.search(str(c))) >= 3:
            return table[i:] if len(table) - i >= 2 else None
    return None


def _pdf_tables(page):
    for settings in (None, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
        tables = page.extract_tables(settings) if settings else page.extract_tables()
        good = [t2 for t in tables if t and (t2 := _with_day_header(t))]
        if good:
            return good
    return []


def _text_grid(text: str):
    """Fallback when no table is detected: rebuild rows from text lines."""
    lines = [l for l in text.splitlines() if clean(l)]
    header_idx = next((i for i, l in enumerate(lines) if len(DAY_RE.findall(l)) >= 3), None)
    if header_idx is None:
        return None
    header_line = lines[header_idx]
    days = re.findall(r"[A-Za-z]{3}\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?", header_line)
    n = len(days)
    rows = [["Staff", "Role"] + days]
    for l in lines[header_idx + 1:]:
        toks = l.split()
        if len(toks) < n + 2:
            continue
        cells = toks[-n:]
        if not all(parse_shift(c) or c.lower() in {"off", "-", "x"} or c.isalpha() for c in cells):
            continue
        rows.append([" ".join(toks[:-n - 1]), toks[-n - 1]] + cells)
    return rows if len(rows) > 1 else None


def load_pdf_grid(cfg: Config, path: Path, source: str, year_hint: int):
    import pdfplumber

    sc = cfg.sources[source]
    off = {simplify(v) for v in sc.get("off_values", ["off"])}
    leave = {simplify(v) for v in sc.get("leave_values", [])}
    records, issues = [], []
    try:
        pdf = pdfplumber.open(path)
    except Exception as e:  # noqa: BLE001
        return [], [file_issue("unreadable_file", "critical", "File could not be read",
                               f"{path.name} could not be opened as a PDF: {e}", path.name)]
    with pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            facility, title = _find_facility(cfg, text)
            legend = parse_legend(text)
            years = re.findall(r"\b(20\d{2})\b", text)
            year = int(years[0]) if years else year_hint
            if facility is None:
                issues.append(file_issue("unknown_facility", "warning", "Schedule page without a known facility",
                                         f"Page {pno} of {path.name} does not name a recognised facility, "
                                         f"so its shifts cannot be attributed to a site.", path.name))
            if not legend:
                issues.append(file_issue("no_shift_legend", "info", "No shift-length note found",
                                         f"Page {pno} of {path.name} has no shift-length note; hours are "
                                         f"computed from shift start and end times.", path.name))
            grids = _pdf_tables(page) or ([g] if (g := _text_grid(text)) else [])
            if not grids:
                issues.append(file_issue("no_table", "critical", "No schedule table found",
                                         f"Page {pno} of {path.name} has no readable table.", path.name))
                continue
            for grid in grids:
                header = [clean(c) for c in grid[0]]
                name_col = role_col = None
                for i, h in enumerate(header):
                    hk = header_key(h)
                    if name_col is None and hk in _alias_keys(sc["fields"]["name"], "name"):
                        name_col = i
                    elif role_col is None and "role" in sc["fields"] and hk in _alias_keys(sc["fields"]["role"], "role"):
                        role_col = i
                day_cols = {}
                for i, h in enumerate(header):
                    m = DAY_RE.search(h)
                    if m:
                        y = m.group(3)
                        yy = (int(y) + 2000 if len(y) == 2 else int(y)) if y else year
                        try:
                            day_cols[i] = date(yy, int(m.group(1)), int(m.group(2)))
                        except ValueError:
                            pass
                if name_col is None or not day_cols:
                    continue
                for r, row in enumerate(grid[1:], start=2):
                    cells = [clean(c) for c in row] + [""] * (len(header) - len(row))
                    if not cells[name_col] or header_key(cells[name_col]) in _alias_keys(sc["fields"]["name"], "name"):
                        continue
                    raw = {"name": cells[name_col], "role": cells[role_col] if role_col is not None else ""}
                    norm, errors = normalize_fields(cfg, source, raw)
                    norm["facility"] = facility or norm.get("facility")
                    shifts = []
                    for ci, d in day_cols.items():
                        code = cells[ci] if ci < len(cells) else ""
                        k = simplify(code)
                        if k in off:
                            continue
                        if k in leave:
                            shifts.append({"date": d.isoformat(), "code": code, "status": "leave", "hours": 0})
                            continue
                        span = parse_shift(code)
                        if span is None:
                            errors.append(("shift", f"unrecognised schedule entry '{code}' on {d.isoformat()}"))
                            shifts.append({"date": d.isoformat(), "code": code, "status": "unknown", "hours": 0})
                            continue
                        start, end = span
                        computed = (end - start) % 24 or 24
                        hours = legend.get(shift_key(code), computed)
                        shifts.append({"date": d.isoformat(), "code": code, "status": "work",
                                       "start": start, "end": end, "hours": hours})
                    norm["_shifts"] = shifts
                    cell_raw = {header[i] or f"col{i}": cells[i] for i in range(min(len(header), len(cells)))}
                    cell_raw["_page_title"] = title or ""
                    records.append({"source": source, "file": path.name, "row_ref": f"page {pno} row {r}",
                                    "raw": cell_raw, "norm": norm, "errors": errors})
    return records, issues


# ---------------------------------------------------------------- entry point

def ingest_files(cfg: Config, paths: list[Path], year_hint: int | None = None):
    """Load every file. Returns (records, file_issues, file_summary)."""
    records, issues, summary = [], [], []
    pdfs = []
    for p in sorted(paths):
        p = Path(p)
        ext = p.suffix.lower()
        if ext == ".pdf":
            pdfs.append(p)
        elif ext in TABLE_EXT:
            source, recs, iss = load_table(cfg, p)
            records += recs
            issues += iss
            summary.append({"file": p.name, "source": source, "records": len(recs)})
        elif not p.name.startswith("."):
            issues.append(file_issue("unrecognised_file", "info", "File skipped",
                                     f"{p.name} is not a supported file type.", p.name))
    # Use years seen in the tabular data to date a schedule that omits the year.
    if year_hint is None:
        date_fields = {e.get("start") for e in cfg.events if e.get("start")}
        years = [int(v[:4]) for r in records for k, v in r["norm"].items()
                 if k in date_fields and isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)]
        year_hint = max(set(years), key=years.count) if years else date.today().year
    pdf_sources = [s for s, sc in cfg.sources.items() if sc.get("loader") == "pdf_grid"]
    for p in pdfs:
        if not pdf_sources:
            issues.append(file_issue("unrecognised_file", "info", "File skipped",
                                     f"{p.name}: no PDF source is configured.", p.name))
            continue
        recs, iss = load_pdf_grid(cfg, p, pdf_sources[0], year_hint)
        records += recs
        issues += iss
        summary.append({"file": p.name, "source": pdf_sources[0] if recs else None, "records": len(recs)})
    for r in records:
        r["record_key"] = f"{r['source']}|{r['file']}|{r['row_ref']}"
    return records, issues, summary
