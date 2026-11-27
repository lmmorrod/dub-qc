"""Delivery manifest: compare what arrived with what the spec says should arrive.

The spec lists the expected deliverables:

    manifest:
      territories: [SPC, FRA, GER]
      reels: [1, 2, 3]
      stems: [DX, MX, FX]

Every combination is a "slot" (e.g. SPC R3 DX). Each slot should be filled by
one file; later versions (v02, v03...) replace earlier ones.
"""

from __future__ import annotations

from collections import defaultdict

from .naming import parse_valid, slot_key, slot_label

MISSING = "Missing"
DUPLICATE = "Duplicate"
DELIVERED = "Delivered"


def latest_versions(filenames: list[str]) -> tuple[set[str], set[str]]:
    """Split files into (latest, superseded). A file is superseded when a higher version of the
    same slot is in the batch. Unparseable names count as latest (nothing replaces them)."""
    by_slot: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
    latest, superseded = set(), set()
    for name in filenames:
        key = slot_key(name)
        if key is None:
            latest.add(name)
        else:
            by_slot[key].append((parse_valid(name)["VERSION_NUM"], name))
    for files in by_slot.values():
        top = max(v for v, _ in files)
        for v, name in files:
            (latest if v == top else superseded).add(name)
    return latest, superseded


def check_manifest(filenames: list[str], spec: dict) -> dict | None:
    """Return the manifest comparison, or None if the spec has no manifest."""
    m = spec.get("manifest")
    if not m:
        return None
    territories = [str(t) for t in m.get("territories", [])]
    reels = [0 if str(r).upper() == "CONT" else int(str(r).upper().removeprefix("R")) for r in m.get("reels", [])]
    stems = [str(s) for s in m.get("stems", [])]
    # Optional delivery versions, e.g. [R128, IMAX]; without them, files carry no version code.
    versions = [str(v) for v in (m.get("versions") or [""])]
    expected = {(t, r, s, v) for t in territories for r in reels for s in stems for v in versions}

    arrived: dict[tuple, list[str]] = defaultdict(list)
    unexpected: dict[str, list[dict]] = defaultdict(list)     # territory -> files
    for name in filenames:
        parts = parse_valid(name)
        if parts is None:
            unexpected["Unrecognised"].append({"file": name, "reason": "filename can't be parsed"})
            continue
        key = (parts["TERR"], parts["REEL_NUM"], parts["STEM"], parts["FORMAT"])
        if key in expected:
            arrived[key].append(name)
            continue
        if parts["TERR"] not in territories:
            reason = f"territory {parts['TERR']} isn't on this delivery"
        elif parts["REEL_NUM"] not in reels:
            reason = f"reel {parts['REEL']} isn't on this delivery"
        elif parts["STEM"] not in stems:
            reason = f"stem {parts['STEM']} isn't on this delivery"
        else:
            reason = (f"version {parts['FORMAT']} isn't on this delivery" if parts["FORMAT"]
                      else "no delivery version in the filename")
        unexpected[parts["TERR"]].append({"file": name, "reason": reason})

    report = {"territories": [], "unexpected_other": []}
    for terr in territories:
        slots, missing, duplicates = [], [], []
        for reel in reels:
            for version in versions:
                for stem in stems:
                    key = (terr, reel, stem, version)
                    files = sorted(arrived.get(key, []))
                    status, latest = _slot_status(files)
                    slots.append({"reel": reel, "stem": stem, "version": version, "label": slot_label(key),
                                  "status": status, "files": files, "latest": latest})
                    if status == MISSING:
                        missing.append(slot_label(key))
                    elif status == DUPLICATE:
                        duplicates.append({"slot": slot_label(key), "files": files})
        n_expected = len(reels) * len(stems) * len(versions)
        delivered = sum(s["status"] != MISSING for s in slots)
        extra = unexpected.pop(terr, [])
        report["territories"].append({
            "territory": terr,
            "name": spec.get("territories", {}).get(terr, terr),
            "expected": n_expected,
            "delivered": delivered,
            "missing": missing,
            "duplicates": duplicates,
            "unexpected": extra,
            "slots": slots,
            "summary": _summary(terr, delivered, n_expected, missing, duplicates, extra),
        })
    for terr, files in unexpected.items():
        for f in files:
            report["unexpected_other"].append({**f, "territory": terr})

    report["expected"] = sum(t["expected"] for t in report["territories"])
    report["delivered"] = sum(t["delivered"] for t in report["territories"])
    report["complete"] = (report["expected"] == report["delivered"]
                          and not any(t["duplicates"] for t in report["territories"]))
    return report


def _slot_status(files: list[str]) -> tuple[str, str | None]:
    if not files:
        return MISSING, None
    versions = [(parse_valid(f)["VERSION_NUM"], f) for f in files]
    top = max(v for v, _ in versions)
    at_top = [f for v, f in versions if v == top]
    if len(at_top) > 1:
        return DUPLICATE, None
    return DELIVERED, at_top[0]


def _summary(terr, delivered, expected, missing, duplicates, unexpected) -> str:
    notes = []
    if missing:
        notes.append(", ".join(missing) + " missing")
    for d in duplicates:
        notes.append(f"{d['slot']} duplicate ({len(d['files'])} files, no clear latest)")
    if unexpected:
        notes.append(f"{len(unexpected)} unexpected file{'s' if len(unexpected) > 1 else ''}")
    line = f"{terr}: {delivered}/{expected} delivered"
    return line + (", " + "; ".join(notes) if notes else ", complete")
