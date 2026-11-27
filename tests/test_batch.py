"""Tests for the ops-at-scale features: manifest, producer scorecard, redelivery check."""

from pathlib import Path

import pytest

from dubqc.batch import analyse, run_batch
from dubqc.demo import BATCH_PLAN, write_demo_batch
from dubqc.manifest import check_manifest, latest_versions
from dubqc.notes import load_notes
from dubqc.models import CRITICAL, WARNING, FileResult, Issue
from dubqc.redelivery import FIXED, NEW, STILL_PRESENT, compare, find_redeliveries, load_baseline
from dubqc.report import to_html, to_json, write_reports
from dubqc.scorecard import build_scorecard, load_producers
from dubqc.spec import load_spec, spec_for_reel

SAMPLES = Path(__file__).parent.parent / "samples" / "demo_batch"
SPEC = load_spec(SAMPLES / "spec.yaml")


def name(terr, reel, stem, v=1, stage="PMX"):
    return f"TEST_{terr}_R{reel}_{stem}_{stage}_v{v:02d}.wav"


def full_set():
    return [name(t, r, s) for t in ("SPC", "FRA", "GER") for r in (1, 2, 3) for s in ("DX", "MX", "FX")]


def result(file, *issues, producer="", rating=None, metrics=None):
    r = FileResult(file=file, path=file, issues=list(issues), producer=producer, metrics=metrics or {})
    r.rating = rating or ("Reject" if not r.passed else "Acceptable with notes" if r.issues else "Good")
    return r


def issue(code, check, severity=CRITICAL, seconds=None, tc=""):
    return Issue(check=check, code=code, severity=severity, message=code, seconds=seconds, timecode=tc)


# ---------------------------------------------------------------- manifest

def test_manifest_complete():
    m = check_manifest(full_set(), SPEC)
    assert m["complete"] and m["delivered"] == m["expected"] == 27
    assert all(t["summary"].endswith("9/9 delivered, complete") for t in m["territories"])


def test_manifest_missing_duplicate_unexpected():
    files = full_set()
    files.remove(name("SPC", 3, "DX"))
    files.remove(name("FRA", 2, "FX"))
    files += [name("FRA", 2, "FX", 2, "PMX"), name("FRA", 2, "FX", 2, "PMR"),   # two v02s: no clear latest
              name("GER", 4, "DX"), name("ITA", 1, "DX"), "random_mix.wav"]
    m = check_manifest(files, SPEC)
    terr = {t["territory"]: t for t in m["territories"]}
    assert terr["SPC"]["summary"] == "SPC: 8/9 delivered, R3 DX missing"
    assert terr["FRA"]["duplicates"][0]["slot"] == "R2 FX"
    assert terr["GER"]["unexpected"][0]["file"] == name("GER", 4, "DX")
    other = {u["file"]: u["territory"] for u in m["unexpected_other"]}
    assert other == {name("ITA", 1, "DX"): "ITA", "random_mix.wav": "Unrecognised"}
    assert not m["complete"]


def test_later_version_replaces_earlier():
    files = full_set() + [name("SPC", 1, "DX", 2)]
    m = check_manifest(files, SPEC)
    assert m["complete"]                                   # v01 + v02 is not a duplicate
    latest, superseded = latest_versions(files)
    assert superseded == {name("SPC", 1, "DX", 1)}


def test_no_manifest_in_spec():
    assert check_manifest(full_set(), load_spec(None)) is None


def test_reel_timecodes():
    r2 = spec_for_reel(SPEC, 2)
    assert r2["reel"]["pip"] == "02:00:06:00" and r2["reel"]["fps"] == 24
    assert spec_for_reel(SPEC, 9)["reel"]["pip"] == "01:00:06:00"        # unknown reel: defaults


# ---------------------------------------------------------------- scorecard

def test_scorecard_numbers_and_note():
    pip = lambda: issue("PIP OFFSET", "Pip")
    files = [
        result(name("GER", 1, "DX"), pip(), producer="P", metrics={"head_pip_offset_frames": 2.0}),
        result(name("GER", 2, "DX"), pip(), producer="P", metrics={"head_pip_offset_frames": -1.0}),
        result(name("GER", 3, "DX"), pip(), producer="P", metrics={"head_pip_offset_frames": 3.0}),
        result(name("GER", 1, "FX"), issue("LOUDNESS", "Loudness"), producer="P"),
        result(name("GER", 2, "FX"), producer="P", metrics={"head_pip_offset_frames": 0.0}),
        result(name("GER", 3, "FX"), issue("NOISE FLOOR", "Noise", WARNING), producer="P"),
    ]
    row = build_scorecard(files)[0]
    assert row["files"] == 6 and row["reject"] == 4 and row["good"] == 1 and row["acceptable"] == 1
    assert row["first_time_pass_rate"] == pytest.approx(2 / 6, abs=0.001)
    assert row["top_issues"][0] == "PIP OFFSET ×3"
    assert row["avg_sync_offset_frames"] == 1.5
    assert "3 of 4 rejects are sync pip, so sync training needed" in row["note"]
    assert row["note"].startswith("Strong on clipping")


def test_first_time_pass_uses_earliest_version():
    files = [result(name("SPC", 1, "DX", 1), issue("CLIPPING", "Clipping"), producer="A"),
             result(name("SPC", 1, "DX", 2), producer="A")]
    row = build_scorecard(files)[0]
    assert row["deliverables"] == 1 and row["first_time_pass_rate"] == 0.0


def test_clipping_blamed_over_loudness():
    files = [result(name("SPC", 1, "DX"), issue("CLIPPING", "Clipping"), issue("LOUDNESS", "Loudness"), producer="A")]
    assert "clipping" in build_scorecard(files)[0]["note"]


def test_load_producers_csv_and_yaml(tmp_path):
    csv_file = tmp_path / "p.csv"
    csv_file.write_text("file,producer,notes\na.wav,Ana,x\nb.wav, Jonas ,\n")
    assert load_producers(csv_file) == {"a.wav": "Ana", "b.wav": "Jonas"}
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text("a.wav: Ana\n")
    assert load_producers(yaml_file) == {"a.wav": "Ana"}
    # uploaded text (as the web app passes it), long enough to break if treated as a path
    long_csv = "file,producer\r\n" + "".join(f"{'X' * 40}_{i}.wav,Ana\r\n" for i in range(40))
    assert len(load_producers(long_csv)) == 40
    assert load_producers("a.wav: Ana\nb.wav: Jonas\n") == {"a.wav": "Ana", "b.wav": "Jonas"}


# ---------------------------------------------------------------- redelivery

def test_compare_fixed_still_new():
    v1 = result(name("SPC", 1, "DX", 1), issue("PIP OFFSET", "Pip", seconds=6.1, tc="01:00:06:03"),
                issue("CLIPPING", "Clipping", seconds=14.0, tc="01:00:14:00"),
                issue("CLIPPING", "Clipping", seconds=20.0, tc="01:00:20:00"))
    v2 = result(name("SPC", 1, "DX", 2), issue("CLIPPING", "Clipping", seconds=14.2, tc="01:00:14:05"),
                issue("AUDIO BEFORE FFOA", "Pip", WARNING, seconds=7.0, tc="01:00:07:00"))
    c = compare(v1, v2)
    status = {(r["code"], r["old_timecode"] or r["new_timecode"]): r["status"] for r in c["rows"]}
    assert status[("PIP OFFSET", "01:00:06:03")] == FIXED
    assert status[("CLIPPING", "01:00:14:00")] == STILL_PRESENT
    assert status[("CLIPPING", "01:00:20:00")] == FIXED
    assert status[("AUDIO BEFORE FFOA", "01:00:07:00")] == NEW
    assert c["counts"] == {FIXED: 2, STILL_PRESENT: 1, NEW: 1}
    assert c["verdict"] == "Still failing"


def test_all_fixed_verdict():
    v1 = result(name("SPC", 1, "DX", 1), issue("LOUDNESS", "Loudness"))
    v2 = result(name("SPC", 1, "DX", 2))
    assert compare(v1, v2)["verdict"] == "All fixed"


def test_redelivery_against_baseline_report(tmp_path):
    v1 = result(name("SPC", 1, "DX", 1), issue("PIP OFFSET", "Pip", tc="01:00:06:03"))
    old_run = analyse([v1], SPEC)
    paths = write_reports(old_run, SPEC, tmp_path, "old")
    baseline = load_baseline(paths["json"])
    v2 = result(name("SPC", 1, "DX", 2))
    found = find_redeliveries([v2], baseline)
    assert len(found) == 1 and found[0]["rows"][0]["status"] == FIXED


# ---------------------------------------------------------------- whole demo batch, real audio

@pytest.fixture(scope="module")
def demo_batch(tmp_path_factory):
    folder = tmp_path_factory.mktemp("batch")
    paths, csv_path = write_demo_batch(folder)
    return run_batch(paths, SPEC, producers=load_producers(csv_path),
                     notes=load_notes(folder / "editor_notes.csv"))


def test_sample_producers_file_matches_demo():
    assert load_producers(SAMPLES / "producers.csv") == {n: p for n, p, _, _ in BATCH_PLAN if p}


def test_demo_batch_end_to_end(demo_batch):
    b = demo_batch
    summaries = [t["summary"] for t in b.manifest["territories"]]
    assert summaries[0] == "SPC: 8/9 delivered, R3 DX missing"
    assert "R2 FX duplicate" in summaries[1]
    assert "1 unexpected file" in summaries[2]

    cards = {row["producer"]: row for row in b.scorecard}
    assert "sync training needed" in cards["Jonas Weber"]["note"]
    assert cards["Lucie Martin"]["reject"] == 0
    assert cards["Ana Ortega"]["first_time_pass_rate"] == 0.5

    (rd,) = b.redeliveries
    statuses = {r["code"]: r["status"] for r in rd["rows"]}
    assert statuses["PIP OFFSET"] == FIXED
    assert statuses["CLIPPING"] == STILL_PRESENT
    assert statuses["AUDIO BEFORE FFOA"] == NEW

    # GER R2 pip is checked against reel 2's own timecode
    ger_r2 = next(f for f in b.files if f.file == name("GER", 2, "DX"))
    assert next(i for i in ger_r2.issues if i.code == "PIP OFFSET").timecode == "02:00:05:23"
    assert not b.passed

    # M&E marker pass finds the walla left in SPC R3 FX, and only there
    voice = [(f.file, i.timecode) for f in b.files for i in f.issues if i.code == "VOICE IN M&E"]
    assert voice and all(f == name("SPC", 3, "FX") for f, _ in voice)
    # the note on R3's off-screen line catches the line GER dropped
    ger_r3 = next(f for f in b.files if f.file == name("GER", 3, "DX"))
    assert "NOTED CONTENT MISSING" in {i.code for i in ger_r3.issues}
    assert all(n["status"] == "Present" for f in b.files if f.file != ger_r3.file for n in f.notes)


def test_report_has_new_sections(demo_batch):
    html = to_html(demo_batch, SPEC, "Demo")
    for text in ("Delivery manifest", "Producer scorecard", "Redelivery check", "R3 DX missing",
                 "Delivery QC for dubbed dialogue"):
        assert text in html, text
    data = to_json(demo_batch, SPEC, "Demo")
    assert data["manifest"] and data["scorecard"] and data["redeliveries"]
