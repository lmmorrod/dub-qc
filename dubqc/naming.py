"""File naming check: <TITLE>_<TERR>_<REEL>_<STEM>_<STAGE>[_<VERSION>]_v<NN>.wav

REEL is R1, R2... for reeled (theatrical) work or CONT for continuous (streaming).
The optional delivery version (e.g. R128, IMAX) sits between the stage and the version number.
"""

from __future__ import annotations

import re

from .models import CRITICAL, INFO, WARNING, Issue

# The required pieces of a name, in order, with what each one should look like.
PARTS = [
    ("TITLE", r"[A-Z0-9]+", "upper-case letters/numbers, no spaces"),
    ("TERR", r"[A-Z]{3}", "3-letter territory code, e.g. SPC"),
    ("REEL", r"R\d+|CONT", "R + reel number (e.g. R1), or CONT for continuous"),
    ("STEM", r"DX|MX|FX|ME|VOX", "DX, MX, FX, ME or VOX"),
    ("STAGE", r"RAW|PMX|PMR|FSS", "RAW, PMX, PMR or FSS"),
    ("VERSION", r"v\d{2}", "v + two digits, e.g. v01"),
]
FORMAT_PART = ("FORMAT", r"[A-Z0-9]{2,8}", "a delivery version code, e.g. R128 or IMAX")
EXAMPLE = "TEST_SPC_R1_DX_PMX_v01.wav (or TEST_SPC_R1_DX_PMR_R128_v01.wav)"


def _parts_for(n_bits: int) -> list[tuple]:
    """6 parts = no delivery version; 7 parts = version code before vNN."""
    return PARTS if n_bits == 6 else PARTS[:5] + [FORMAT_PART] + PARTS[5:]


def parse_name(filename: str) -> dict | None:
    """Split a name into its parts (without validating them), or return None."""
    stem, dot, ext = filename.rpartition(".")
    bits = stem.split("_")
    if len(bits) not in (6, 7):
        return None
    out = {name: bit for (name, _, _), bit in zip(_parts_for(len(bits)), bits)}
    out.setdefault("FORMAT", "")
    out["EXT"] = ext
    return out


def parse_valid(filename: str) -> dict | None:
    """Like parse_name, but only if every part is well formed. Adds REEL_NUM (0 = continuous)
    and VERSION_NUM."""
    parts = parse_name(filename)
    if not parts or parts["EXT"] != "wav":
        return None
    spec_parts = _parts_for(7 if parts["FORMAT"] else 6)
    if not all(re.fullmatch(pattern, parts[name]) for name, pattern, _ in spec_parts):
        return None
    parts["REEL_NUM"] = 0 if parts["REEL"] == "CONT" else int(parts["REEL"][1:])
    parts["VERSION_NUM"] = int(parts["VERSION"][1:])
    return parts


def slot_key(filename: str) -> tuple | None:
    """The deliverable a file fills: (territory, reel, stem, delivery version).
    Numbered versions (v01, v02...) of the same deliverable share a slot."""
    parts = parse_valid(filename)
    return (parts["TERR"], parts["REEL_NUM"], parts["STEM"], parts["FORMAT"]) if parts else None


def reel_label(reel_num: int) -> str:
    return "CONT" if reel_num == 0 else f"R{reel_num}"


def slot_label(slot: tuple) -> str:
    fmt = slot[3] if len(slot) > 3 else ""
    return f"{reel_label(slot[1])} {slot[2]}" + (f" {fmt}" if fmt else "")


def _diagnose(filename: str) -> list[str]:
    """Explain in plain words what's wrong with a name."""
    hints = []
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        return ["no file extension (should end in .wav)"]
    if ext != "wav":
        hints.append(f"extension is '.{ext}', should be lower-case '.wav'")
    if " " in stem:
        hints.append("contains spaces")
    bits = stem.split("_")
    if len(bits) not in (6, 7):
        hints.append(f"has {len(bits)} underscore-separated parts, expected 6 "
                     "(TITLE_TERR_REEL_STEM_STAGE_vNN) or 7 (with a delivery version before vNN)")
        return hints
    for (name, pattern, help_text), bit in zip(_parts_for(len(bits)), bits):
        if not re.fullmatch(pattern, bit):
            hints.append(f"{name} '{bit}' should be {help_text}")
    return hints


def check_naming(filename: str, spec: dict) -> list[Issue]:
    issues: list[Issue] = []
    pattern = spec["naming"]["pattern"]
    if not re.match(pattern, filename):
        hints = _diagnose(filename) or ["doesn't match the spec's naming pattern"]
        issues.append(Issue(
            check="Naming", code="MISNAMED", severity=CRITICAL, file=filename,
            message="Filename doesn't follow the delivery naming convention: " + "; ".join(hints) + ".",
            expected=f"TITLE_TERR_R#_STEM_STAGE_vNN.wav (e.g. {EXAMPLE})",
            found=filename,
            fix="Rename the file to the delivery convention before it goes out. "
                "If it's a territory delivery, ask them to re-send with the correct name.",
        ))
        return issues

    parts = parse_valid(filename)
    if parts is None:
        return issues  # custom pattern that doesn't use the standard parts; regex passed, that's enough

    reel_in_name = parts["REEL_NUM"]
    reel_in_spec = spec["reel"].get("number")
    known_reels = {int(k) for k in (spec.get("reels") or {})}
    if (reel_in_name != 0 and reel_in_name not in known_reels and reel_in_spec is not None
            and reel_in_name != int(reel_in_spec)):
        issues.append(Issue(
            check="Naming", code="REEL MISMATCH", severity=WARNING, file=filename,
            message=f"Filename says reel {reel_in_name} but the spec is for reel {reel_in_spec}.",
            expected=f"R{reel_in_spec}", found=parts["REEL"],
            fix="Check you've loaded the right reel's spec (pip/FFOA timecodes are per reel).",
        ))
    versions = spec.get("versions") or {}
    if parts["FORMAT"] and parts["FORMAT"] not in versions:
        issues.append(Issue(
            check="Naming", code="UNKNOWN VERSION", severity=WARNING, file=filename,
            message=f"Delivery version '{parts['FORMAT']}' isn't defined in the spec, so the default "
                    "loudness and format limits were used.",
            expected=", ".join(versions) or "a version listed under `versions:`", found=parts["FORMAT"],
            fix="Add this version to `versions:` in the spec, or correct the filename.",
        ))
    if parts["TERR"] not in spec.get("territories", {}):
        issues.append(Issue(
            check="Naming", code="UNKNOWN TERRITORY", severity=INFO, file=filename,
            message=f"Territory code '{parts['TERR']}' isn't in the spec's territory list.",
            found=parts["TERR"],
            fix="Add it to `territories:` in the spec if it's valid.",
        ))
    return issues


def describe(filename: str, spec: dict) -> str:
    """Human description, e.g. 'Castilian Spanish (SPC), reel 1, dialogue premix, v01'."""
    from .spec import entry_name
    parts = parse_name(filename)
    if not parts:
        return filename
    terr = spec.get("territories", {}).get(parts["TERR"], parts["TERR"])
    stem = entry_name(spec, "stems", parts["STEM"])
    stage = entry_name(spec, "stages", parts["STAGE"])
    reel = "continuous" if parts["REEL"] == "CONT" else f"reel {parts['REEL'][1:]}"
    version = ""
    if parts["FORMAT"]:
        version = f" ({entry_name(spec, 'versions', parts['FORMAT'])})"
    return f"{terr} ({parts['TERR']}), {reel}, {stem} {stage}{version}, {parts['VERSION']}"
