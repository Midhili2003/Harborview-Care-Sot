"""Generic value normalizers.

Every normalizer returns (value, error). A non-empty error never stops
processing: the caller records it as an issue and keeps going.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

EMPTY = {"", "nan", "none", "null", "n/a", "na", "-", "--"}


def clean(value) -> str:
    if value is None:
        return ""
    s = str(value).replace("\ufeff", "").replace("\xa0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return "" if s.lower() in EMPTY else s


def simplify(text: str) -> str:
    """Lowercase, strip accents and punctuation. Used for loose comparisons."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def header_key(text: str) -> str:
    return simplify(clean(text)).replace(" ", "_")


# ---------- dates ----------

_FORMATS_MDY = ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%m.%d.%Y"]
_FORMATS_DMY = ["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y"]
_FORMATS_COMMON = ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d-%b-%Y", "%d %b %Y", "%b %d %Y",
                   "%B %d %Y", "%d %B %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]


def parse_date(value, order: str = "mdy"):
    s = clean(value)
    if not s:
        return None, None
    s2 = s.replace(",", "")
    formats = _FORMATS_COMMON + (_FORMATS_MDY if order == "mdy" else _FORMATS_DMY)
    for fmt in formats:
        try:
            d = datetime.strptime(s2, fmt).date()
            if d.year < 1900 or d.year > 2100:
                return None, f"date '{s}' is out of range"
            return d, None
        except ValueError:
            continue
    # Excel serial number
    if re.fullmatch(r"\d{5}(\.0+)?", s):
        n = int(float(s))
        if 20000 < n < 80000:
            return date.fromordinal(date(1899, 12, 30).toordinal() + n), None
    return None, f"could not read '{s}' as a date"


def is_non_iso_date(value) -> bool:
    s = clean(value)
    return bool(s) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)


# ---------- numbers / phones ----------

def parse_number(value):
    s = clean(value)
    if not s:
        return None, None
    s2 = s.replace(",", "")
    try:
        return float(s2), None
    except ValueError:
        return None, f"could not read '{s}' as a number"


def parse_phone(value):
    s = clean(value)
    if not s:
        return None, None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return s, f"phone '{s}' does not have 10 digits"
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}", None


# ---------- identifiers / codes ----------

def parse_identifier(value, pattern: str | None = None, dash: bool = False):
    s = clean(value)
    if not s:
        return None, None
    s2 = re.sub(r"[\s_\u2013\u2014.]+", "-", s.upper())
    s2 = re.sub(r"-+", "-", s2).strip("-")
    m = re.fullmatch(r"([A-Z]+)(\d+)", s2)
    if m and dash:
        s2 = f"{m.group(1)}-{m.group(2)}"
    if pattern and not re.fullmatch(pattern, s2):
        return s2, f"'{s}' does not look like a valid identifier"
    return s2, None


class CodeMap:
    """Maps any known spelling of a value to its canonical code."""

    def __init__(self, spec: dict):
        self.labels = {}
        self.lookup = {}
        for code, info in (spec or {}).items():
            info = info or {}
            self.labels[code] = info.get("label", code)
            for alias in [code, info.get("label", "")] + list(info.get("aliases", [])):
                if alias:
                    self.lookup[simplify(str(alias))] = code

    def parse(self, value):
        s = clean(value)
        if not s:
            return None, None
        key = simplify(s)
        if key in self.lookup:
            return self.lookup[key], None
        # tolerate extra words, e.g. "Harborview Bayside Campus"
        hits = {code for alias, code in self.lookup.items() if len(alias) > 3 and alias in key}
        if len(hits) == 1:
            return hits.pop(), None
        return s, f"'{s}' is not a recognised value"

    def label(self, code):
        return self.labels.get(code, code)


# ---------- people ----------

class NameParser:
    def __init__(self, nicknames: dict):
        self.canon = {}
        for canonical, aliases in (nicknames or {}).items():
            for a in aliases:
                self.canon.setdefault(simplify(a), simplify(canonical))

    def canonical_first(self, first: str) -> str:
        f = simplify(first)
        return self.canon.get(f, f)

    def split(self, full: str):
        """'REYES, SOFIA' / 'Sofia Reyes' / 'Sofia M. Reyes' -> (first, last)."""
        s = clean(full)
        if not s:
            return "", ""
        if "," in s:
            last, first = [p.strip() for p in s.split(",", 1)]
        else:
            parts = s.split(" ")
            if len(parts) == 1:
                return parts[0], ""
            first, last = parts[0], " ".join(parts[1:])
        first = first.split(" ")[0] if first else ""
        last_parts = [p for p in last.split(" ") if not re.fullmatch(r"[A-Za-z]\.?", p)] or last.split(" ")
        return first, " ".join(last_parts)

    def build(self, first: str, last: str) -> dict:
        first, last = clean(first), clean(last)
        display = " ".join(p.title() if p.isupper() or p.islower() else p
                           for p in f"{first} {last}".split())
        key = f"{self.canonical_first(first)} {simplify(last)}".strip()
        return {"_first": first, "_last": last, "_display": display, "_name_key": key}
