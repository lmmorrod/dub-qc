"""Editor notes: timecoded reminders that carry from one QC pass to the next.

Notes live in a simple CSV that editors add to as they work:

    reel,timecode,type,note,stem,territory
    1,01:00:11:12,off-screen line,Guard calls out from behind the door,DX,
    3,03:00:14:12,breath,Breath before the line must stay,DX,GER

- reel: 1, 2, ... or CONT
- stem: which stem the note is about (default DX)
- territory: blank = every territory
- duration_s (optional): how long the noted content lasts (default from the spec)

Every run, each note is matched to the files it applies to and checked: is there audio at that
timecode? A noted line that has gone quiet in a later print is flagged.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

from .models import CRITICAL, Issue
from .timecode import tc_to_file_seconds

PRESENT = "Present"
SILENT = "Silent"
OUTSIDE = "Outside file"


def load_notes(source: str | Path | None) -> list[dict]:
    """Read notes from a CSV path, or from CSV text (e.g. an uploaded file)."""
    if not source:
        return []
    is_text = isinstance(source, str) and ("\n" in source or "\r" in source)
    text = str(source) if is_text else Path(source).read_text()
    notes = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("timecode") or not row.get("reel"):
            continue
        reel = row["reel"].upper().removeprefix("R")
        notes.append({
            "reel": 0 if reel == "CONT" else int(reel),
            "timecode": row["timecode"],
            "type": row.get("type") or "note",
            "note": row.get("note", ""),
            "stem": (row.get("stem") or "DX").upper(),
            "territory": (row.get("territory") or "").upper(),
            "duration_s": float(row["duration_s"]) if row.get("duration_s") else None,
        })
    return notes


def notes_for(notes: list[dict], parts: dict | None) -> list[dict]:
    """The notes that apply to a file, given its parsed name."""
    if not parts:
        return []
    return [n for n in notes if n["reel"] == parts["REEL_NUM"] and n["stem"] == parts["STEM"]
            and n["territory"] in ("", parts["TERR"])]


def check_notes(data: np.ndarray, sr: int, spec: dict, notes: list[dict]) -> tuple[list[Issue], list[dict]]:
    """Check each note against the audio. Returns (issues, note results)."""
    cfg = spec["notes"]
    reel = spec["reel"]
    mono = data.mean(axis=1)
    issues, results = [], []
    for n in notes:
        start = tc_to_file_seconds(n["timecode"], reel["fps"], reel["session_start"])
        dur = n["duration_s"] or cfg["default_duration_s"]
        a, b = int(start * sr), int((start + dur) * sr)
        if a < 0 or b > len(mono):
            status, level = OUTSIDE, None
        else:
            rms = float(np.sqrt((mono[a:b].astype(np.float64) ** 2).mean()))
            level = 20 * np.log10(rms) if rms > 0 else float("-inf")
            status = PRESENT if level >= cfg["min_level_dbfs"] else SILENT
        results.append({**n, "status": status, "level_dbfs": None if level is None else round(level, 1),
                        "seconds": start})
        if status == SILENT:
            issues.append(Issue(
                check="Editor notes", code="NOTED CONTENT MISSING", severity=CRITICAL,
                seconds=start, timecode=n["timecode"],
                message=f"Editor note ({n['type']}): \"{n['note']}\". There's no audio here.",
                expected=f"{n['type']} at {n['timecode']}", found=f"silence ({level:.0f} dBFS)",
                fix="Check whether the line was dropped in the mix or never recorded. "
                    "If never recorded, add it to the pickup request.",
            ))
    return issues, results
