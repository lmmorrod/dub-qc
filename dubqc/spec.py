"""Load a delivery spec (YAML) and fill in sensible defaults for anything it leaves out."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

ALL_CHECKS = ["naming", "format", "loudness", "true_peak", "clipping", "pip", "noise", "voice_in_me"]

DEFAULT_SPEC: dict = {
    "name": "Default broadcast delivery (EBU R128)",
    "loudness": {"integrated_lufs": -23.0, "tolerance_lu": 1.0, "true_peak_dbtp": -1.0},
    "format": {"sample_rate": 48000, "bit_depth": 24, "channels": 1},
    "naming": {"pattern": r"^[A-Z0-9]+_[A-Z]{3}_(R\d+|CONT)_(DX|MX|FX|ME|VOX)_(RAW|PMX|PMR|FSS)(_[A-Z0-9]{2,8})?_v\d{2}\.wav$"},
    "reel": {
        "number": 1,
        "fps": 24,
        "session_start": "01:00:00:00",
        "pip": "01:00:06:00",
        "ffoa": "01:00:08:00",
        "lfoa": None,
    },
    "pip": {
        "frequency_hz": 1000,
        "search_window_s": 1.5,
        "tolerance_frames": 0,
        "min_level_dbfs": -40,
    },
    "clipping": {"threshold": 0.999, "min_consecutive": 3},
    "noise": {"max_floor_dbfs": -60},
    "territories": {
        "SPC": "Castilian Spanish",
        "LAS": "Latin American Spanish",
        "FRE": "Parisian French",
        "FRA": "French",
        "CFR": "Canadian French",
        "GER": "German",
        "ITA": "Italian",
        "BPO": "Brazilian Portuguese",
        "POL": "Polish",
        "RUS": "Russian",
        "BUL": "Bulgarian",
        "TUR": "Turkish",
        "JPN": "Japanese",
        "KOR": "Korean",
        "MAN": "Mandarin",
        "CAN": "Cantonese",
        "HIN": "Hindi",
    },
    # Each stem and stage can be just a name, or a name plus which checks run and a
    # "what to listen for" checklist for the person doing the QC pass.
    "stems": {
        "DX": {"name": "dialogue", "checks": [c for c in ALL_CHECKS if c != "voice_in_me"],
               "checklist": [
                   "Dialogue only: no music or effects baked into the stem",
                   "Every line present, including off-screen and background lines",
                   "Lines in sync with lip movement, not just with the pip",
                   "No clicks, pops, distortion, dropouts or mic bumps",
               ]},
        "VOX": {"name": "vocal", "checks": [c for c in ALL_CHECKS if c != "voice_in_me"],
                "checklist": ["All sung content in the vocal stem, none left in dialogue",
                              "Harmonies on the right tracks; timing and tuning match the original"]},
        **{code: {"name": name, "checks": [c for c in ALL_CHECKS if c != "noise"],
                  "stage_checklist": False,          # the stage checklists are about dialogue
                  "checklist": [
                      "Listen for dropouts, clicks, distortion and sync problems",
                      "Mark any voice content (walla, breaths, efforts) so dialogue "
                      "editors don't double it with the dub",
                  ]}
           for code, name in (("MX", "music"), ("FX", "effects"), ("ME", "music and effects"))},
    },
    "stages": {
        "RAW": {"name": "raw dialogue", "checks": ["naming", "format", "clipping", "pip", "noise"],
                "checklist": [
                    "Every scripted line recorded; list anything missing as a pickup request",
                    "Takes on the right character tracks",
                    "Recording quality: room noise, distortion, mic bumps (goes in the load report)",
                ]},
        "PMX": {"name": "premix", "checklist": [
            "All dialogue present and in sync with picture",
            "Treatments (phone, radio, reverb) match the original",
            "No doubling between dub dialogue and voice left in the music and effects",
            "Walla and efforts where the original has them",
        ]},
        "PMR": {"name": "printmaster", "checklist": [
            "Every premix QC note has been fixed",
            "Nothing new introduced since the premix",
            "Dialogue sits clearly over music and effects",
        ]},
        "FSS": {"name": "final QC", "checklist": [
            "Every printmaster QC note has been fixed",
            "Final top-to-tail listen: no dropouts, clicks or missing lines",
            "Pips present and in sync; nothing before first frame of action",
        ]},
    },
    # Delivery versions (theatrical, IMAX, broadcast...). Each can override loudness, format and
    # timecodes. A file picks its version from the filename (..._PMR_R128_v01.wav), or uses
    # `default_version`; with neither, the top-level limits apply.
    "versions": {},
    "default_version": None,
    # Timecode layout for continuous (non-reeled) files, named with CONT instead of R1, R2...
    "continuous": {"session_start": "00:59:50:00", "pip": "00:59:58:00", "ffoa": "01:00:00:00"},
    # Optional per-reel timecodes, e.g. {2: {session_start: '02:00:00:00', pip: ..., ffoa: ...}}
    "reels": {},
    # Voice markers in music and effects: how sure the detector must be that a passage is voice, and how long it must last
    "voice_in_me": {"min_score": 0.72, "min_duration_s": 1.0, "min_level_dbfs": -45},
    # Editor notes: how loud the audio at a noted timecode must be to count as present
    "notes": {"min_level_dbfs": -45, "default_duration_s": 1.0},
    # Optional expected deliverables: {territories: [...], reels: [...], stems: [...]}
    "manifest": None,
    # How close (seconds) a clip in v02 must be to one in v01 to count as the same problem
    "redelivery": {"match_tolerance_s": 1.0},
    "script": {"match_threshold": 0.85},
    "sync": {"start_offset_s": 0.5, "duration_tolerance_pct": 20},
}


def spec_for_reel(spec: dict, reel_number: int | None) -> dict:
    """The spec with that reel's own timecodes laid over the default `reel:`.
    Reel 0 means continuous (uses `continuous:`)."""
    if reel_number == 0:
        out = copy.deepcopy(spec)
        out["reel"] = _merge(spec["reel"], spec.get("continuous") or {})
        out["reel"]["number"] = 0
        return out
    reels = {int(k): v for k, v in (spec.get("reels") or {}).items()}
    if reel_number is None or reel_number not in reels:
        return spec
    out = copy.deepcopy(spec)
    out["reel"] = _merge(spec["reel"], reels[reel_number])
    out["reel"]["number"] = reel_number
    return out


def spec_for_version(spec: dict, version: str | None) -> tuple[dict, str]:
    """The spec with a delivery version's overrides (loudness, format, reel...) laid on top.
    Returns (spec, version code used or '')."""
    versions = spec.get("versions") or {}
    code = version or spec.get("default_version") or ""
    if code not in versions:
        return spec, ""
    override = {k: v for k, v in (versions[code] or {}).items() if k != "name"}
    return _merge(spec, override), code


def spec_for_file(spec: dict, parts: dict | None) -> tuple[dict, str]:
    """Everything that depends on the filename: version limits first, then the reel's timecodes."""
    spec, version = spec_for_version(spec, parts["FORMAT"] if parts else None)
    return spec_for_reel(spec, parts["REEL_NUM"] if parts else None), version


def entry(spec: dict, group: str, code: str) -> dict:
    """A stem/stage/version entry as a dict, whether the spec gives a plain name or a full entry."""
    value = (spec.get(group) or {}).get(code)
    if isinstance(value, dict):
        return {"name": value.get("name", code), **value}
    return {"name": value or code}


def entry_name(spec: dict, group: str, code: str) -> str:
    return entry(spec, group, code)["name"]


def checks_for(spec: dict, stage: str | None, stem: str | None) -> list[str]:
    """Which checks run on a file: the checks allowed for its stage AND for its stem."""
    stage_checks = entry(spec, "stages", stage).get("checks", ALL_CHECKS) if stage else ALL_CHECKS
    # If a spec names a stem without listing its checks, fall back to the built-in set for that
    # stem, so e.g. dialogue is never run through the "voice in music and effects" detector.
    builtin = DEFAULT_SPEC["stems"].get(stem or "DX", DEFAULT_SPEC["stems"]["DX"])
    stem_checks = entry(spec, "stems", stem).get("checks", builtin["checks"]) if stem else builtin["checks"]
    return [c for c in ALL_CHECKS if c in stage_checks and c in stem_checks]


def checklist_for(spec: dict, stage: str | None, stem: str | None) -> list[str]:
    items = []
    builtin = DEFAULT_SPEC["stems"].get(stem or "", {})
    use_stage = entry(spec, "stems", stem).get("stage_checklist", builtin.get("stage_checklist", True)) if stem else True
    if stage and use_stage:
        items += entry(spec, "stages", stage).get("checklist", [])
    if stem:
        items += entry(spec, "stems", stem).get("checklist", [])
    return items


def _merge(base: dict, override: dict) -> dict:
    """Recursively lay `override` on top of `base`."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_spec(source: str | Path | dict | None = None) -> dict:
    """Load a spec from a YAML file path, a YAML string, a dict, or None (defaults only)."""
    if source is None:
        user = {}
    elif isinstance(source, dict):
        user = source
    elif isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and Path(source).exists()):
        user = yaml.safe_load(Path(source).read_text()) or {}
    else:
        user = yaml.safe_load(source) or {}
    return _merge(DEFAULT_SPEC, user)
