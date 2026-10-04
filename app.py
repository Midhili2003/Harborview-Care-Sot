"""Dashboard for the source of truth.  Run:  streamlit run app.py"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from sot.apps.reports import credentials_report, staffing_report
from sot.core.config import Config
from sot.core.pipeline import accept_match, dismiss, ingest, reject_match, reopen
from sot.core.store import Store

ROOT = Path(__file__).parent
CONFIG = ROOT / "config/harborview.yaml"
DB = ROOT / "sot.db"
SEV_COLOR = {"critical": "#B42318", "warning": "#B54708", "info": "#475467"}
SEV_BG = {"critical": "#FEF3F2", "warning": "#FFFAEB", "info": "#F2F4F7"}

st.set_page_config(page_title="Harborview source of truth", page_icon="🩺", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton button, .stTabs button { font-family: 'Public Sans', sans-serif; }
h1 { font-weight: 700; letter-spacing: -0.01em; color: #0E3B4A; }
.sev { display:inline-block; padding: 1px 8px; border-radius: 3px; font-size: 0.8rem; font-weight: 600; }
.count { font-size: 2rem; font-weight: 700; line-height: 1; }
.countlabel { color: #475467; font-size: 0.9rem; }
.expl { font-size: 1rem; line-height: 1.5; max-width: 75ch; }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_cfg():
    return Config(CONFIG)


cfg = get_cfg()
store = Store(DB)


def sev_badge(sev):
    return f"<span class='sev' style='color:{SEV_COLOR[sev]};background:{SEV_BG[sev]}'>{sev}</span>"


def entity_names():
    return {e["entity_key"]: e["display_name"] for e in store.query("SELECT entity_key, display_name FROM entities")}


def show_records(recs, extra=None):
    """One table per source system, so columns line up."""
    for source in dict.fromkeys(r["source"] for r in recs):
        rows = []
        for r in recs:
            if r["source"] != source:
                continue
            raw = {k.replace("_page_title", "page title"): v for k, v in json.loads(r["raw"]).items()}
            rows.append({"file": r["file"], "where": r["row_ref"], **(extra(r) if extra else {}), **raw})
        st.markdown(f"**{cfg.source_label(source)}**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def records_by_key(keys):
    if not keys:
        return []
    q = f"SELECT * FROM records WHERE record_key IN ({','.join('?' * len(keys))})"
    return store.query(q, tuple(keys))


# --------------------------------------------------------------------------- header
run = store.last_run()
summary = json.loads(run["summary"]) if run and run.get("summary") else {}
st.title(f"{cfg.business.get('name', 'Business')}: one trusted record")
if summary:
    o = summary.get("issues_open", {})
    cols = st.columns(5)
    for c, (label, value, color) in zip(cols, [
        ("people", summary.get("entities", 0), "#0E3B4A"),
        ("records", sum(summary.get("records_by_source", {}).values()), "#0E3B4A"),
        ("critical", o.get("critical", 0), SEV_COLOR["critical"]),
        ("warnings", o.get("warning", 0), SEV_COLOR["warning"]),
        ("info", o.get("info", 0), SEV_COLOR["info"]),
    ]):
        c.markdown(f"<div class='count' style='color:{color}'>{value}</div><div class='countlabel'>{label}</div>",
                   unsafe_allow_html=True)
    st.caption(f"Last ingest {run['started_at']}, checks run as of {summary.get('as_of')}")
else:
    st.info("No data yet. Load files in the first tab.")

tabs = st.tabs(["Load data", "Issues", "People", "Licenses", "Staffing report", "Decisions"])

# --------------------------------------------------------------------------- load
with tabs[0]:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Ingest files")
        st.write("Drop in the HR roster, payroll and license exports (CSV or Excel) and the schedule PDF. "
                 "File types are detected from their columns, so names don't matter.")
        uploads = st.file_uploader("Files", accept_multiple_files=True, type=["csv", "tsv", "txt", "xlsx", "xls", "pdf"])
        as_of = st.date_input("Run time-based checks as of", value=date.today(),
                              help="Expiry and staleness are measured from this date.")
        if st.button("Ingest uploaded files", type="primary", disabled=not uploads):
            with tempfile.TemporaryDirectory() as tmp:
                for u in uploads:
                    (Path(tmp) / u.name).write_bytes(u.getbuffer())
                ingest(cfg, store, [tmp], as_of)
            st.rerun()
    with right:
        st.subheader("Practice data")
        st.write("Generated in the same formats as the real files. The messy set has 25 planted problems; "
                 "the clean set should raise no warnings.")
        variant = st.radio("Dataset", ["messy", "clean"], horizontal=True)
        if st.button("Load practice data"):
            ingest(cfg, store, [ROOT / "fixtures" / variant], date(2026, 9, 21))
            st.rerun()
    if summary.get("files"):
        st.subheader("Last ingest")
        st.dataframe(pd.DataFrame(summary["files"]).rename(columns={"source": "detected as"}),
                     hide_index=True, width="stretch")
        st.write("Matching: " + ", ".join(f"{v} by {k.replace('_', ' ')}" for k, v in summary["match_methods"].items()))

# --------------------------------------------------------------------------- issues
with tabs[1]:
    issues = store.query("SELECT * FROM issues")
    if not issues:
        st.write("Nothing flagged.")
    else:
        names = entity_names()
        f1, f2, f3, f4 = st.columns(4)
        sev = f1.multiselect("Severity", ["critical", "warning", "info"], default=["critical", "warning"])
        status = f2.selectbox("Status", ["open", "dismissed", "all"])
        rule_opts = sorted({i["title"] for i in issues})
        rule_sel = f3.multiselect("Type", rule_opts)
        person = f4.selectbox("Person", ["Everyone"] + sorted({names.get(i["entity_key"], "") for i in issues
                                                                 if i["entity_key"]} - {""}))
        shown = [i for i in issues if i["severity"] in sev and (status == "all" or i["status"] == status)
                 and (not rule_sel or i["title"] in rule_sel)
                 and (person == "Everyone" or names.get(i["entity_key"]) == person)]
        st.caption(f"{len(shown)} of {len(issues)} issues")
        for i in shown:
            who = names.get(i["entity_key"], "")
            label = f"{i['severity'].upper()}  ·  {i['title']}" + (f"  ·  {who}" if who else "")
            with st.expander(label, expanded=i["severity"] == "critical" and i["status"] == "open"):
                st.markdown(f"{sev_badge(i['severity'])} <div class='expl'>{i['explanation']}</div>",
                            unsafe_allow_html=True)
                recs = records_by_key(json.loads(i["record_keys"] or "[]"))
                if recs:
                    st.caption("Source rows behind this issue")
                    show_records(recs)
                vals = json.loads(i["vals"] or "{}")
                note = st.text_input("Note", key=f"note{i['id']}", value=i["note"] or "",
                                     placeholder="Why, for the audit trail")
                b1, b2, b3 = st.columns([2, 1, 1])
                if i["rule_id"] == "possible_match" and i["status"] == "open":
                    cands = vals.get("candidates", [])
                    target = b1.selectbox("Same person as", cands, key=f"t{i['id']}",
                                          format_func=lambda k: f"{names.get(k, k)} ({k})")
                    if b2.button("Confirm match", key=f"a{i['id']}", type="primary"):
                        accept_match(cfg, store, i["id"], target, note)
                        st.rerun()
                    if b3.button("Keep separate", key=f"r{i['id']}"):
                        reject_match(cfg, store, i["id"], note)
                        st.rerun()
                elif i["status"] == "open":
                    if b3.button("Dismiss", key=f"d{i['id']}", help="Accept as-is. Remembered on future ingests."):
                        dismiss(cfg, store, i["id"], note)
                        st.rerun()
                else:
                    if b3.button("Reopen", key=f"o{i['id']}"):
                        reopen(cfg, store, i["id"])
                        st.rerun()

# --------------------------------------------------------------------------- people
with tabs[2]:
    ents = store.query("SELECT * FROM entities ORDER BY display_name")
    if ents:
        opts = {e["entity_key"]: f"{e['display_name']}  ({e['entity_key']})" for e in ents}
        key = st.selectbox("Person", list(opts), format_func=opts.get)
        e = next(x for x in ents if x["entity_key"] == key)
        g = json.loads(e["golden"])
        st.subheader(e["display_name"])
        if e["origin"] != cfg.anchor:
            st.warning(f"Not in {cfg.source_label(cfg.anchor)}. Known only from {cfg.source_label(e['origin'])}.")
        rows = []
        for field, v in g.items():
            ftype = next((cfg.field_type(s, field) for s in cfg.sources if cfg.field_type(s, field)), None)
            rows.append({"field": field.replace("_", " "), "trusted value": cfg.label_value(ftype, v["value"]),
                         "from": cfg.source_label(v["source"]) if v["source"] else "",
                         "other values seen": "; ".join(f"{cfg.label_value(ftype, c['value'])} ({cfg.source_label(c['source'])})"
                                                        for c in v["conflicts"])})
        c1, c2 = st.columns([3, 2])
        c1.caption("Golden record: each field comes from the system trusted for it")
        c1.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        own = store.query("SELECT severity, title, explanation FROM issues WHERE entity_key=? AND status='open'", (key,))
        c2.caption(f"{len(own)} open issue(s)")
        for i in own:
            c2.markdown(f"{sev_badge(i['severity'])} **{i['title']}**  \n{i['explanation']}", unsafe_allow_html=True)
        recs = store.query("SELECT * FROM records WHERE entity_key=?", (key,))
        st.caption("Every source record linked to this person, and how it was matched")
        show_records(recs, lambda r: {"matched by": (r["method"] or "").replace("_", " "),
                                      "confidence": r["confidence"]})
        shifts = store.query("SELECT kind, start_date, end_date, code, hours, facility FROM events "
                             "WHERE entity_key=? ORDER BY start_date", (key,))
        if shifts:
            st.caption("Scheduled and paid time")
            st.dataframe(pd.DataFrame(shifts), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- licenses
with tabs[3]:
    rows = credentials_report(cfg, store) if summary else []
    if rows:
        df = pd.DataFrame(rows)
        st.write("Sorted by days left. Expired or soon-expiring licenses are listed with any shifts already "
                 "scheduled after the expiry date.")

        def color(v):
            return {"EXPIRED": f"color:{SEV_COLOR['critical']};font-weight:600",
                    "<30 days": f"color:{SEV_COLOR['warning']};font-weight:600"}.get(v, "")
        st.dataframe(df.style.map(color, subset=["status"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- staffing
with tabs[4]:
    if summary:
        q = st.text_input("Quarter (e.g. 2026Q3). Leave blank for everything loaded.", "")
        rep = staffing_report(cfg, store, q or None)
        if rep["warning"]:
            st.error(rep["warning"])
        else:
            st.success("No open critical or warning issues affect these numbers.")
        st.caption(f"Period: {rep['period']}")
        st.dataframe(pd.DataFrame(rep["summary"]), hide_index=True, width="stretch")
        if rep["excluded"]:
            st.caption("Hours left out because the license had expired")
            st.dataframe(pd.DataFrame(rep["excluded"]), hide_index=True, width="stretch")
        if rep["daily"]:
            daily = pd.DataFrame(rep["daily"])
            st.caption("Daily scheduled hours by facility and role (the shape a state staffing submission needs)")
            st.dataframe(daily.pivot_table(index=["facility", "role"], columns="date", values="scheduled_hours",
                                           aggfunc="sum", fill_value=0), width="stretch")
            st.download_button("Download daily detail (CSV)", daily.to_csv(index=False), "staffing_daily.csv")

# --------------------------------------------------------------------------- decisions
with tabs[5]:
    st.write("Human decisions are stored separately from the data and re-applied on every ingest, "
             "so nobody has to fix the same thing twice.")
    d = store.query("SELECT kind, key, value, note, created_at FROM decisions ORDER BY id DESC")
    if d:
        st.dataframe(pd.DataFrame(d), hide_index=True, width="stretch")
    else:
        st.caption("No decisions yet.")
    if st.button("Delete all data and decisions"):
        store.reset()
        st.rerun()
