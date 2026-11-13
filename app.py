"""Streamlit page for the Delivery Checker.  Run with:  uv run streamlit run app.py"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from dubqc.delivery import check_files
from dubqc.report import overall_pass, to_html, to_json, write_reports
from dubqc.spec import load_spec

DEFAULT_SPEC = Path(__file__).parent / "samples" / "single_reel" / "spec.yaml"

st.set_page_config(page_title="Dub QC: Delivery Checker", page_icon="🎧", layout="wide")
st.title("Dub QC: Delivery Checker")
st.caption("Drop in dialogue WAVs and check naming, format, loudness, clipping and the sync pip against a delivery spec.")

with st.sidebar:
    st.header("Delivery spec")
    project = st.text_input("Project name", "Test")
    spec_upload = st.file_uploader("Load a spec (YAML)", type=["yaml", "yml"])
    spec_text = spec_upload.read().decode() if spec_upload else DEFAULT_SPEC.read_text()
    spec_text = st.text_area("Edit spec", spec_text, height=480)

uploads = st.file_uploader("Dialogue WAVs", type=["wav"], accept_multiple_files=True)

if st.button("Run QC", type="primary", disabled=not uploads):
    try:
        spec = load_spec(spec_text)
    except Exception as exc:
        st.error(f"Couldn't read the spec: {exc}")
        st.stop()

    with st.spinner("Checking…"), tempfile.TemporaryDirectory() as tmp:
        paths, names = [], []
        for up in uploads:
            p = Path(tmp) / up.name
            p.write_bytes(up.getbuffer())
            paths.append(p)
            names.append(up.name)
        results = check_files(paths, spec, names)
        saved = write_reports(results, spec, "reports", project)

    passed = overall_pass(results)
    issues = [i for r in results for i in r.issues]
    cols = st.columns(4)
    cols[0].metric("Overall", "PASS" if passed else "FAIL")
    for col, sev in zip(cols[1:], ["Critical", "Warning", "Info"]):
        col.metric(sev, sum(i.severity == sev for i in issues))

    (st.success if passed else st.error)(
        "All files pass." if passed else "One or more files have critical issues. See the report below.")

    html = to_html(results, spec, project)
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download HTML report", html, file_name=saved["html"].name, mime="text/html")
    d2.download_button("Download JSON", json.dumps(to_json(results, spec, project), indent=2, default=str),
                       file_name=saved["json"].name, mime="application/json")
    d3.download_button("Download marker list", saved["markers"].read_text(), file_name=saved["markers"].name)
    st.caption(f"Also saved to {saved['html'].parent}/")

    components.html(html, height=1400, scrolling=True)
