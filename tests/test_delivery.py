"""Delivery Checker tests, run against synthetic audio generated on the fly."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from dubqc.audio_checks import check_pips, find_clips
from dubqc.delivery import check_file
from dubqc.demo import SR, make_dialogue, write_demo_set
from dubqc.naming import check_naming
from dubqc.report import to_html
from dubqc.spec import load_spec
from dubqc.timecode import file_seconds_to_tc, frames_to_tc, tc_to_frames

SPEC = load_spec(Path(__file__).parent.parent / "samples" / "last_train_to_leith" / "spec.yaml")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    folder = tmp_path_factory.mktemp("demo")
    paths = write_demo_set(folder)
    return {p.name: check_file(p, SPEC) for p in paths}


def codes(result):
    return {i.code for i in result.issues}


def test_clean_file_passes(demo):
    r = demo["LASTTRAIN_SPC_R1_DX_PMX_v01.wav"]
    assert r.passed
    assert r.issues == []
    assert abs(r.metrics["integrated_lufs"] - -23) <= 0.5
    assert r.metrics["head_pip"] == "01:00:06:00"
    assert r.rating == "Good"


def test_errors_file_catches_pip_and_clipping(demo):
    r = demo["LASTTRAIN_SPC_R1_DX_PMX_v02.wav"]
    assert not r.passed
    assert {"PIP OFFSET", "CLIPPING", "TRUE PEAK"} <= codes(r)
    pip = next(i for i in r.issues if i.code == "PIP OFFSET")
    assert "+3 fr" in pip.found
    clip = next(i for i in r.issues if i.code == "CLIPPING")
    assert clip.timecode.startswith("01:00:30:")          # line 8 starts at 01:00:30:00
    assert "REJECT" in r.load_report


def test_misnamed_16bit_file(demo):
    r = demo["LastTrain_Spanish_R1_DX_final.wav"]
    assert {"MISNAMED", "WRONG FORMAT"} <= codes(r)
    assert "PIP OFFSET" not in codes(r)


def test_missing_pip(tmp_path):
    p = tmp_path / "LASTTRAIN_SPC_R1_DX_PMX_v03.wav"
    sf.write(p, make_dialogue(include_pip=False), SR, subtype="PCM_24")
    assert "PIP MISSING" in codes(check_file(p, SPEC))


@pytest.mark.parametrize("offset", [-2, 1, 5])
def test_pip_offset_measured_in_frames(offset):
    audio = make_dialogue(pip_offset_frames=offset)[:, None]
    _, metrics = check_pips(audio, SR, SPEC)
    assert round(metrics["head_pip_offset_frames"]) == offset


def test_naming_rules():
    good = "LASTTRAIN_SPC_R1_DX_PMX_v01.wav"
    assert check_naming(good, SPEC) == []
    for bad in ["LASTTRAIN_SPC_R1_DX_PMX_v1.wav", "LastTrain_SPC_R1_DX_PMX_v01.wav",
                "LASTTRAIN_SPC_R1_DX_PMX_v01.WAV", "LASTTRAIN_SPC_R1_DX_MIX_v01.wav"]:
        assert check_naming(bad, SPEC)[0].code == "MISNAMED", bad
    assert check_naming("LASTTRAIN_SPC_R2_DX_PMX_v01.wav", SPEC)[0].code == "REEL MISMATCH"


def test_clip_runs():
    x = np.zeros((48000, 1), dtype=np.float32)
    x[1000:1002] = 1.0          # 2 samples: below the 3-sample minimum
    x[20000:20010] = -1.0       # 10 samples: a clip
    events = find_clips(x, 48000, 0.999, 3)
    assert len(events) == 1 and events[0]["start"] == 20000


def test_timecode():
    assert tc_to_frames("01:00:06:00", 24) == 86544
    assert frames_to_tc(86547, 24) == "01:00:06:03"
    assert file_seconds_to_tc(8.0, 24, "01:00:00:00") == "01:00:08:00"


def test_html_renders(demo):
    html = to_html(list(demo.values()), SPEC, "Test")
    assert "FAIL" in html and "PIP OFFSET" in html and "<svg" in html
