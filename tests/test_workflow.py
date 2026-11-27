"""Tests for the workflow features: delivery versions, stage-aware checks, M&E marker pass, editor notes."""

import csv
from pathlib import Path

import pytest
import soundfile as sf

from dubqc.batch import run_batch
from dubqc.delivery import check_file
from dubqc.demo import DEMO_NOTES, SR, make_dialogue
from dubqc.manifest import check_manifest
from dubqc.me_markers import find_voice
from dubqc.naming import check_naming, parse_valid, slot_key, slot_label
from dubqc.notes import PRESENT, SILENT, load_notes, notes_for
from dubqc.report import to_html
from dubqc.spec import checklist_for, checks_for, load_spec, spec_for_file

SAMPLES = Path(__file__).parent.parent / "samples" / "demo_batch"

SPEC = load_spec({
    "versions": {
        "TH": {"name": "Theatrical", "loudness": {"integrated_lufs": None, "true_peak_dbtp": -1}},
        "R128": {"name": "Broadcast (EBU R128)", "loudness": {"integrated_lufs": -23, "tolerance_lu": 1}},
        "NF": {"name": "Nearfield", "loudness": {"integrated_lufs": -27, "tolerance_lu": 2}},
    },
    # the demo audio has its pip 6 s in, so lay continuous files out the same way
    "continuous": {"session_start": "00:59:54:00", "pip": "01:00:00:00", "ffoa": "01:00:02:00"},
})


def write(tmp_path, name, **opts):
    path = tmp_path / name
    sf.write(path, make_dialogue(n_lines=4, **opts), SR, subtype="PCM_24")
    return path


def codes(result):
    return {i.code for i in result.issues}


# ---------------------------------------------------------------- naming with versions, CONT and RAW

def test_names_with_version_cont_and_raw():
    p = parse_valid("TEST_SPC_R1_DX_PMR_R128_v02.wav")
    assert (p["FORMAT"], p["STAGE"], p["VERSION_NUM"]) == ("R128", "PMR", 2)
    assert slot_key("TEST_SPC_R1_DX_PMR_R128_v02.wav") == ("SPC", 1, "DX", "R128")
    c = parse_valid("TEST_SPC_CONT_MX_RAW_v01.wav")
    assert c["REEL_NUM"] == 0 and c["STAGE"] == "RAW" and c["FORMAT"] == ""
    assert slot_label(("SPC", 0, "DX", "NF")) == "CONT DX NF"
    assert check_naming("TEST_SPC_R1_DX_PMR_R128_v01.wav", SPEC) == []
    assert check_naming("TEST_SPC_R1_DX_PMR_r128_v01.wav", SPEC)[0].code == "MISNAMED"
    assert check_naming("TEST_SPC_R1_DX_PMR_IMAX_v01.wav", SPEC)[0].code == "UNKNOWN VERSION"


# ---------------------------------------------------------------- delivery versions

def test_version_limits_come_from_the_filename():
    spec, version = spec_for_file(SPEC, parse_valid("TEST_SPC_R1_DX_PMR_NF_v01.wav"))
    assert version == "NF" and spec["loudness"]["integrated_lufs"] == -27
    assert spec["loudness"]["true_peak_dbtp"] == -1          # untouched values keep the default
    spec, version = spec_for_file(SPEC, parse_valid("TEST_SPC_R1_DX_PMR_v01.wav"))
    assert version == "" and spec["loudness"]["integrated_lufs"] == -23


def test_default_version_applies_to_plain_names():
    spec, version = spec_for_file(load_spec({**SPEC, "default_version": "NF"}), parse_valid("TEST_SPC_R1_DX_PMR_v01.wav"))
    assert version == "NF" and spec["loudness"]["integrated_lufs"] == -27


def test_same_audio_passes_one_version_and_fails_another(tmp_path):
    loud = {"gain_db": 3.0}                                  # -20 LUFS
    th = check_file(write(tmp_path, "TEST_SPC_R1_DX_PMR_TH_v01.wav", **loud), SPEC)
    r128 = check_file(write(tmp_path, "TEST_SPC_R1_DX_PMR_R128_v01.wav", **loud), SPEC)
    assert th.version == "TH" and "LOUDNESS" not in codes(th)    # theatrical: no LUFS target
    assert "LOUDNESS" in codes(r128)
    assert "no target for this version" in th.load_report


def test_continuous_file_uses_continuous_timecodes(tmp_path):
    r = check_file(write(tmp_path, "TEST_SPC_CONT_DX_PMR_R128_v01.wav"), SPEC)
    assert r.metrics["head_pip"] == "01:00:00:00" and r.passed


def test_manifest_counts_each_version_as_a_deliverable():
    spec = load_spec({**SPEC, "manifest": {"territories": ["SPC"], "reels": [1, "CONT"], "stems": ["DX"],
                                           "versions": ["R128", "NF"]}})
    files = ["TEST_SPC_R1_DX_PMR_R128_v01.wav", "TEST_SPC_R1_DX_PMR_NF_v01.wav",
             "TEST_SPC_CONT_DX_PMR_R128_v01.wav", "TEST_SPC_R1_DX_PMR_v01.wav"]
    m = check_manifest(files, spec)
    (spc,) = m["territories"]
    assert spc["expected"] == 4 and spc["delivered"] == 3
    assert spc["missing"] == ["CONT DX NF"]
    assert spc["unexpected"][0]["reason"] == "no delivery version in the filename"


# ---------------------------------------------------------------- stage- and stem-aware checks

def test_checks_depend_on_stage_and_stem():
    assert "loudness" not in checks_for(SPEC, "RAW", "DX")        # raw dialogue isn't mixed yet
    assert "noise" in checks_for(SPEC, "RAW", "DX")
    me = checks_for(SPEC, "PMX", "FX")
    assert "voice_in_me" in me and "noise" not in me
    assert "voice_in_me" not in checks_for(SPEC, "PMX", "DX")
    # a spec that names stems without listing checks still gets sensible defaults
    plain = load_spec({"stems": {"DX": "dialogue", "FX": "effects"}})
    assert "voice_in_me" not in checks_for(plain, "PMX", "DX") and "voice_in_me" in checks_for(plain, "PMX", "FX")


def test_raw_dialogue_skips_loudness(tmp_path):
    r = check_file(write(tmp_path, "TEST_SPC_R1_DX_RAW_v01.wav", gain_db=6.0), SPEC)
    assert "LOUDNESS" not in codes(r) and "loudness" not in r.checks_run


def test_checklists_by_stage_and_stem():
    dx = checklist_for(SPEC, "PMX", "DX")
    assert any("in sync with picture" in i for i in dx) and any("off-screen" in i for i in dx)
    fx = checklist_for(SPEC, "PMX", "FX")
    assert any(i.startswith("Marker pass") for i in fx)
    assert not any("dialogue present" in i for i in fx)          # dialogue items stay off M&E stems


# ---------------------------------------------------------------- M&E marker pass

@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_music_and_effects_are_not_flagged(seed):
    for kind in ("MX", "FX"):
        assert find_voice(make_dialogue(seed=seed, kind=kind, n_lines=4)[:, None], SR, SPEC) == []


def test_walla_in_effects_is_marked(tmp_path):
    r = check_file(write(tmp_path, "TEST_SPC_R1_FX_PMX_v01.wav", kind="FX", walla=(12.0, 15.0)), SPEC)
    (voice,) = [i for i in r.issues if i.code == "VOICE IN M&E"]
    assert voice.severity == "Info" and 11.0 <= voice.seconds <= 13.0
    assert r.passed                                               # a marker, not a fault


# ---------------------------------------------------------------- editor notes

def test_load_notes_and_match_them_to_files(tmp_path):
    f = tmp_path / "notes.csv"
    f.write_text("reel,timecode,type,note,stem,territory\n"
                 "1,01:00:11:12,off-screen line,Guard calls out,,\n"
                 "R2,02:00:17:18,breath,Keep breath,DX,GER\n"
                 "CONT,01:00:05:00,walla,Crowd,FX,\n")
    notes = load_notes(f)
    assert [n["reel"] for n in notes] == [1, 2, 0] and notes[0]["stem"] == "DX"
    assert len(notes_for(notes, parse_valid("TEST_GER_R2_DX_PMX_v01.wav"))) == 1
    assert notes_for(notes, parse_valid("TEST_SPC_R2_DX_PMX_v01.wav")) == []     # GER only
    assert len(notes_for(notes, parse_valid("TEST_SPC_CONT_FX_PMX_v01.wav"))) == 1


def test_noted_line_present_or_missing(tmp_path):
    notes = load_notes("reel,timecode,type,note\n1,01:00:14:12,off-screen line,Radio voice\n")
    ok = check_file(write(tmp_path, "TEST_SPC_R1_DX_PMX_v01.wav"), SPEC, notes=notes)
    dropped = check_file(write(tmp_path, "TEST_GER_R1_DX_PMX_v01.wav", drop_line=3), SPEC, notes=notes)
    assert ok.notes[0]["status"] == PRESENT and ok.passed
    assert dropped.notes[0]["status"] == SILENT
    assert "NOTED CONTENT MISSING" in codes(dropped) and not dropped.passed
    assert "noted line(s) have no audio" in dropped.load_report


def test_sample_notes_file_matches_demo():
    with open(SAMPLES / "editor_notes.csv") as fh:
        assert [tuple(row) for row in csv.reader(fh)] == list(DEMO_NOTES)


def test_report_shows_checklist_and_notes(tmp_path):
    notes = load_notes(SAMPLES / "editor_notes.csv")
    paths = [write(tmp_path, "TEST_SPC_R1_DX_PMX_v01.wav"), write(tmp_path, "TEST_SPC_R1_FX_PMX_v01.wav", kind="FX")]
    html = to_html(run_batch(paths, SPEC, notes=notes), SPEC, "Test")
    for text in ("What to listen for", "Already checked automatically", "Editor notes",
                 "Guard calls out from behind the door", "Marker pass"):
        assert text in html, text
