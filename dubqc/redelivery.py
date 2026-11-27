"""Redelivery check: when v02 arrives, did it fix what was wrong with v01?

Each v01 issue is marked Fixed or Still present, and anything only in v02 is a New issue.
The previous version can be in the same batch, or in an earlier run's JSON report (--baseline).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .models import SEVERITY_ORDER, FileResult, Issue
from .naming import parse_valid, slot_key

FIXED = "Fixed"
STILL_PRESENT = "Still present"
NEW = "New issue"

# These problems are tied to a place in the file, so v01 and v02 must match by position too.
# Everything else (loudness, pip offset, format...) happens once per file and matches by type.
POSITIONAL = {"CLIPPING", "AUDIO BEFORE FFOA", "VOICE IN MUSIC/EFFECTS", "NOTED CONTENT MISSING"}


def load_baseline(path: str | Path) -> list[FileResult]:
    """Read the files and issues back out of an earlier JSON report."""
    data = json.loads(Path(path).read_text())
    out = []
    for f in data.get("files", []):
        issues = [Issue(**i) for i in f.get("issues", [])]
        out.append(FileResult(file=f["file"], path=f.get("path", ""), metrics=f.get("metrics", {}),
                              issues=issues, rating=f.get("rating", ""), producer=f.get("producer", "")))
    return out


def compare(old: FileResult, new: FileResult, tolerance_s: float = 1.0) -> dict:
    """Match v01's issues against v02's."""
    unmatched_new = list(new.issues)
    rows = []
    for o in old.issues:
        match = None
        for n in unmatched_new:
            if n.code != o.code:
                continue
            if o.code in POSITIONAL and o.seconds is not None and n.seconds is not None \
                    and abs(o.seconds - n.seconds) > tolerance_s:
                continue
            match = n
            break
        if match:
            unmatched_new.remove(match)
        rows.append(_row(STILL_PRESENT if match else FIXED, o, match))
    rows += [_row(NEW, None, n) for n in unmatched_new]
    rows.sort(key=lambda r: ({NEW: 0, STILL_PRESENT: 1, FIXED: 2}[r["status"]], SEVERITY_ORDER[r["severity"]]))

    counts = {s: sum(r["status"] == s for r in rows) for s in (FIXED, STILL_PRESENT, NEW)}
    if not old.issues and not new.issues:
        verdict = "Both versions clean"
    elif new.passed and not counts[NEW]:
        verdict = "All fixed" if not counts[STILL_PRESENT] else "Passes now, with notes"
    elif new.passed:
        verdict = "Passes now, but has new notes"
    else:
        verdict = "Still failing"
    return {"old_file": old.file, "new_file": new.file, "old_rating": old.rating, "new_rating": new.rating,
            "verdict": verdict, "counts": counts, "rows": rows}


def _row(status: str, old: Issue | None, new: Issue | None) -> dict:
    ref = new or old
    return {
        "status": status,
        "code": ref.code,
        "severity": ref.severity,
        "old_timecode": old.timecode if old else "",
        "new_timecode": new.timecode if new else "",
        "old_found": old.found if old else "",
        "new_found": new.found if new else "",
        "message": ref.message,
    }


def find_redeliveries(results: list[FileResult], baseline: list[FileResult] | None = None,
                      tolerance_s: float = 1.0) -> list[dict]:
    """Pair each new version with the version just before it (from this batch or the baseline)."""
    pool: dict[tuple, dict[int, list[FileResult]]] = defaultdict(lambda: defaultdict(list))
    in_batch = {id(r) for r in results}
    for r in list(baseline or []) + list(results):
        key = slot_key(r.file)
        if key is not None:
            pool[key][parse_valid(r.file)["VERSION_NUM"]].append(r)

    out = []
    for key, versions in sorted(pool.items()):
        ordered = sorted(versions)
        for prev_v, this_v in zip(ordered, ordered[1:]):
            prev, this = versions[prev_v], versions[this_v]
            # Skip when either version is ambiguous (duplicates are reported by the manifest).
            news = [r for r in this if id(r) in in_batch]
            if len(prev) != 1 or len(news) != 1:
                continue
            out.append(compare(prev[0], news[0], tolerance_s))
    return out
