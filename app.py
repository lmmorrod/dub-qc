"""Dub QC web page.  Run with:  uv run streamlit run app.py"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from dubqc import brand
from dubqc.batch import run_batch
from dubqc.redelivery import load_baseline
from dubqc.report import to_html, to_json, write_reports
from dubqc.notes import load_notes
from dubqc.scorecard import load_producers
from dubqc.spec import checklist_for, entry_name
from dubqc.spec import load_spec

HERE = Path(__file__).parent
SPECS = {
    "Demo multi-territory delivery (SPC/FRA/GER × R1–R3)": HERE / "samples" / "demo_batch" / "spec.yaml",
    "Single reel (R1 dialogue)": HERE / "samples" / "single_reel" / "spec.yaml",
}

st.set_page_config(page_title="Dub QC", page_icon="🎧", layout="wide")
st.markdown(f"""{brand.FONT_LINK}<style>
html, body, [class*="css"], .stMarkdown, .stButton, .stTextInput, .stDataFrame {{font-family:{brand.FONT_STACK};}}
.block-container {{padding-top:3.8rem}}
.dubqc-head {{background:{brand.SLATE};border-bottom:3px solid {brand.ACCENT};border-radius:10px;
  padding:18px 22px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}}
.dubqc-head .tag {{color:#9fb0c0;font-size:14px;margin-top:4px}}
.dubqc-head .hint {{color:#c9d4de;font-size:13px;max-width:440px}}
</style>
<div class="dubqc-head"><div>{brand.wordmark_html(30)}<div class="tag">{brand.TAGLINE}</div></div>
<div class="hint">Drop in a batch of deliveries to check every file, see what's missing,
score producers and verify redeliveries.</div></div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Setup")
    project = st.text_input("Project name", "Test")
    preset = st.selectbox("Delivery spec", list(SPECS))
    spec_upload = st.file_uploader("…or load your own spec (YAML)", type=["yaml", "yml"])
    spec_text = spec_upload.read().decode() if spec_upload else SPECS[preset].read_text()
    with st.expander("Edit spec"):
        spec_text = st.text_area("Spec YAML", spec_text, height=420, label_visibility="collapsed")
    producers_upload = st.file_uploader("Producers (CSV or YAML: file → producer)", type=["csv", "yaml", "yml"])
    baseline_upload = st.file_uploader("Previous report (JSON), to compare redeliveries", type=["json"])
    notes_upload = st.file_uploader("Editor notes (CSV: reel, timecode, type, note, stem, territory)", type=["csv"])
    st.caption("Try it: `uv run python -m dubqc make-demo-batch` writes 30 demo WAVs and a producers.csv "
               "to samples/synthetic/batch.")

uploads = st.file_uploader("Delivery WAVs", type=["wav"], accept_multiple_files=True)

if st.button("Run QC", type="primary", disabled=not uploads):
    try:
        spec = load_spec(spec_text)
    except Exception as exc:
        st.error(f"Couldn't read the spec: {exc}")
        st.stop()
    producers = load_producers(producers_upload.read().decode()) if producers_upload else {}
    notes = load_notes(notes_upload.read().decode()) if notes_upload else []
    baseline = None
    if baseline_upload:
        with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as fh:
            fh.write(baseline_upload.getbuffer())
        baseline = load_baseline(fh.name)

    with st.spinner(f"Checking {len(uploads)} file(s)…"), tempfile.TemporaryDirectory() as tmp:
        paths, names = [], []
        for up in uploads:
            p = Path(tmp) / up.name
            p.write_bytes(up.getbuffer())
            paths.append(p)
            names.append(up.name)
        batch = run_batch(paths, spec, names, producers, baseline, notes)
        saved = write_reports(batch, spec, "reports", project)
    st.session_state["run"] = {"batch": batch, "spec": spec, "project": project, "saved": saved}

run = st.session_state.get("run")
if run:
    batch, spec, project, saved = run["batch"], run["spec"], run["project"], run["saved"]
    current = batch.current_files
    issues = [i for r in current for i in r.issues]
    html = to_html(batch, spec, project)

    cols = st.columns(5)
    cols[0].metric("Overall", "PASS" if batch.passed else "FAIL")
    if batch.manifest:
        cols[1].metric("Deliverables in", f"{batch.manifest['delivered']}/{batch.manifest['expected']}")
    cols[2].metric("Files passing QC", f"{sum(r.passed for r in current)}/{len(current)}")
    cols[3].metric("Critical", sum(i.severity == "Critical" for i in issues))
    cols[4].metric("Warnings", sum(i.severity == "Warning" for i in issues))

    tabs = st.tabs(["Overview", "What to listen for", "Delivery manifest", "Redelivery check", "Editor notes",
                    "Producer scorecard", "Issues", "Full report"])
    tab_overview, tab_listen, tab_manifest, tab_redelivery, tab_notes, tab_score, tab_issues, tab_report = tabs

    with tab_overview:
        if batch.manifest:
            for t in batch.manifest["territories"]:
                ok = t["delivered"] == t["expected"] and not t["duplicates"] and not t["unexpected"]
                (st.success if ok else st.warning)(f"**{t['summary']}** · {t['name']}")
            for u in batch.manifest["unexpected_other"]:
                st.warning(f"**Not on this delivery:** `{u['file']}` ({u['reason']})")
        (st.success if batch.passed else st.error)(
            "Everything passes." if batch.passed else "Some files or deliverables need attention. See the tabs above.")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Download HTML report", html, file_name=saved["html"].name, mime="text/html")
        d2.download_button("Download JSON (use as next baseline)", json.dumps(to_json(batch, spec, project),
                           indent=2, default=str), file_name=saved["json"].name, mime="application/json")
        d3.download_button("Download marker list", saved["markers"].read_text(), file_name=saved["markers"].name)

    with tab_listen:
        groups = {}
        for r in current:
            groups.setdefault((r.stage, r.stem), []).append(r)
        order = {"RAW": 0, "PMX": 1, "PMR": 2, "FSS": 3}
        for (stage, stem), files in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 9), kv[0][1])):
            items = checklist_for(spec, stage or None, stem or None)
            if not items:
                continue
            title = " · ".join(x for x in (entry_name(spec, "stages", stage) if stage else "",
                                           entry_name(spec, "stems", stem) if stem else "") if x)
            st.subheader(f"{title.capitalize()} ({len(files)} files)")
            for item in items:
                st.checkbox(item, key=f"chk-{stage}-{stem}-{item}")

    with tab_notes:
        noted = [{"file": r.file, "timecode": n["timecode"], "type": n["type"], "note": n["note"],
                  "status": n["status"], "level (dBFS)": n["level_dbfs"]} for r in current for n in r.notes]
        if not noted:
            st.info("Load an editor notes CSV in the sidebar to check noted lines in every file.")
        else:
            st.dataframe(pd.DataFrame(noted), use_container_width=True, hide_index=True)

    with tab_manifest:
        if not batch.manifest:
            st.info("This spec has no `manifest:` section, so there's nothing to compare against.")
        else:
            ratings = {r.file: r.rating for r in batch.files}
            for t in batch.manifest["territories"]:
                st.subheader(f"{t['territory']} · {t['delivered']}/{t['expected']} delivered")
                grid = {}
                for s in t["slots"]:
                    if s["status"] != "Delivered":
                        cell = s["status"]
                    else:
                        cell = f"{ratings.get(s['latest'], '')} ({s['latest'].rsplit('_', 1)[-1][:-4]})"
                    grid.setdefault(f"R{s['reel']}", {})[s["stem"]] = cell
                st.dataframe(pd.DataFrame(grid).T, use_container_width=True)
                for d in t["duplicates"]:
                    st.caption(f"{d['slot']} duplicate: " + ", ".join(d["files"]))
                for u in t["unexpected"]:
                    st.caption(f"Unexpected: {u['file']} ({u['reason']})")

    with tab_redelivery:
        if not batch.redeliveries:
            st.info("No redeliveries in this batch. Add v01 and v02 of the same file, "
                    "or load a previous report as a baseline.")
        for rd in batch.redeliveries:
            c = rd["counts"]
            st.markdown(f"**`{rd['old_file']}` → `{rd['new_file']}`**: {rd['verdict']} · "
                        f"{c['Fixed']} fixed, {c['Still present']} still present, {c['New issue']} new")
            st.dataframe(pd.DataFrame(rd["rows"])[["status", "code", "severity", "old_timecode", "new_timecode",
                                                   "old_found", "new_found"]],
                         use_container_width=True, hide_index=True)

    with tab_score:
        rows = [r for r in batch.scorecard]
        if not any(r["producer"] != "Unassigned" for r in rows):
            st.info("Load a producers file (CSV or YAML) in the sidebar to see the scorecard.")
        else:
            df = pd.DataFrame(rows)
            df["top_issues"] = df["top_issues"].apply(", ".join)
            df["first_time_pass_rate"] = df["first_time_pass_rate"] * 100
            st.dataframe(
                df[["producer", "files", "first_time_pass_rate", "good", "acceptable", "reject", "top_issues",
                    "avg_sync_offset_frames", "note"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "producer": "Producer", "files": "Files", "good": "Good", "acceptable": "Notes",
                    "reject": "Reject", "top_issues": "Top issues", "note": st.column_config.TextColumn("Summary", width="large"),
                    "first_time_pass_rate": st.column_config.ProgressColumn(
                        "First-time pass", format="%.0f%%", min_value=0, max_value=100),
                    "avg_sync_offset_frames": st.column_config.NumberColumn("Avg sync offset (fr)", format="%.1f"),
                })
            st.caption("Click a column header to sort.")

    with tab_issues:
        table = [{"file": r.file, "timecode": i.timecode, "issue": i.code, "severity": i.severity,
                  "problem": i.message, "fix": i.fix, "superseded": r.superseded}
                 for r in batch.files for i in r.issues]
        if table:
            st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
        else:
            st.success("No issues found.")

    with tab_report:
        components.html(html, height=1600, scrolling=True)
        st.caption(f"Also saved to {saved['html'].parent}/")
