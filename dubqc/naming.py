"""File naming check: <TITLE>_<TERR>_<REEL>_<STEM>_<STAGE>_v<NN>.wav"""

from __future__ import annotations

import re

from .models import CRITICAL, INFO, WARNING, Issue

# The pieces of a name, in order, with what each one should look like.
PARTS = [
    ("TITLE", r"[A-Z0-9]+", "upper-case letters/numbers, no spaces"),
    ("TERR", r"[A-Z]{3}", "3-letter territory code, e.g. SPC"),
    ("REEL", r"R\d+", "R + reel number, e.g. R1"),
    ("STEM", r"DX|ME|VOX", "DX, ME or VOX"),
    ("STAGE", r"PMX|PMR|FSS", "PMX, PMR or FSS"),
    ("VERSION", r"v\d{2}", "v + two digits, e.g. v01"),
]


def parse_name(filename: str) -> dict | None:
    """Split a well-formed name into its parts, or return None."""
    stem, dot, ext = filename.rpartition(".")
    bits = stem.split("_")
    if len(bits) != len(PARTS):
        return None
    out = {name: bit for (name, _, _), bit in zip(PARTS, bits)}
    out["EXT"] = ext
    return out


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
    if len(bits) != len(PARTS):
        hints.append(f"has {len(bits)} underscore-separated parts, expected {len(PARTS)} "
                     "(TITLE_TERR_REEL_STEM_STAGE_vNN)")
        return hints
    for (name, pattern, help_text), bit in zip(PARTS, bits):
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
            expected="TITLE_TERR_R#_STEM_STAGE_vNN.wav (e.g. TEST_SPC_R1_DX_PMX_v01.wav)",
            found=filename,
            fix="Rename the file to the delivery convention before it goes out. "
                "If it's a territory delivery, ask them to re-send with the correct name.",
        ))
        return issues

    parts = parse_name(filename)
    if parts is None:
        return issues  # custom pattern that doesn't use the standard parts; regex passed, that's enough

    reel_in_name = int(parts["REEL"][1:])
    reel_in_spec = spec["reel"].get("number")
    if reel_in_spec is not None and reel_in_name != int(reel_in_spec):
        issues.append(Issue(
            check="Naming", code="REEL MISMATCH", severity=WARNING, file=filename,
            message=f"Filename says reel {reel_in_name} but the spec is for reel {reel_in_spec}.",
            expected=f"R{reel_in_spec}", found=parts["REEL"],
            fix="Check you've loaded the right reel's spec (pip/FFOA timecodes are per reel).",
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
    parts = parse_name(filename)
    if not parts:
        return filename
    terr = spec.get("territories", {}).get(parts["TERR"], parts["TERR"])
    stem = spec.get("stems", {}).get(parts["STEM"], parts["STEM"])
    stage = spec.get("stages", {}).get(parts["STAGE"], parts["STAGE"])
    return f"{terr} ({parts['TERR']}), reel {parts['REEL'][1:]}, {stem} {stage}, {parts['VERSION']}"
