"""Load a delivery spec (YAML) and fill in sensible defaults for anything it leaves out."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULT_SPEC: dict = {
    "name": "Default broadcast delivery (EBU R128)",
    "loudness": {"integrated_lufs": -23.0, "tolerance_lu": 1.0, "true_peak_dbtp": -1.0},
    "format": {"sample_rate": 48000, "bit_depth": 24, "channels": 1},
    "naming": {"pattern": r"^[A-Z0-9]+_[A-Z]{3}_R\d+_(DX|MX|FX|ME|VOX)_(PMX|PMR|FSS)_v\d{2}\.wav$"},
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
    "stems": {"DX": "dialogue", "MX": "music", "FX": "effects", "ME": "M&E", "VOX": "vocal"},
    "stages": {"PMX": "premix", "PMR": "printmaster", "FSS": "FSS"},
    # Optional per-reel timecodes, e.g. {2: {session_start: '02:00:00:00', pip: ..., ffoa: ...}}
    "reels": {},
    # Optional expected deliverables: {territories: [...], reels: [...], stems: [...]}
    "manifest": None,
    # How close (seconds) a clip in v02 must be to one in v01 to count as the same problem
    "redelivery": {"match_tolerance_s": 1.0},
    "script": {"match_threshold": 0.85},
    "sync": {"start_offset_s": 0.5, "duration_tolerance_pct": 20},
}


def spec_for_reel(spec: dict, reel_number: int | None) -> dict:
    """The spec with that reel's own timecodes (from `reels:`) laid over the default `reel:`."""
    reels = {int(k): v for k, v in (spec.get("reels") or {}).items()}
    if reel_number is None or reel_number not in reels:
        return spec
    out = copy.deepcopy(spec)
    out["reel"] = _merge(spec["reel"], reels[reel_number])
    out["reel"]["number"] = reel_number
    return out


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
