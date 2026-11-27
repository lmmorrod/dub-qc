"""Producer scorecard: how each freelance producer's deliveries are doing.

Producers come from a simple mapping file, CSV:

    file,producer
    TEST_SPC_R1_DX_PMX_v01.wav,Ana Ortega

or YAML:

    TEST_SPC_R1_DX_PMX_v01.wav: Ana Ortega
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .models import CRITICAL, INFO, FileResult
from .naming import parse_valid, slot_key

UNASSIGNED = "Unassigned"

# Which area each check belongs to, and what to suggest when it's the main reason for rejects.
AREAS = {
    "Loudness": "loudness", "True peak": "loudness", "Pip": "sync pip", "Clipping": "clipping",
    "Format": "export format", "Naming": "file naming", "Noise": "noise",
    "Editor notes": "missing lines", "Music & effects": "voice in music and effects",
}
ACTIONS = {
    "sync pip": "sync training needed",
    "loudness": "a metering refresher would help",
    "clipping": "gain staging needs a look",
    "export format": "share the export settings checklist",
    "file naming": "resend the naming convention",
    "noise": "check the recording environment",
    "missing lines": "check the script and editor notes before printing",
    "voice in music and effects": "review the voice markers",
}
STRENGTH_ORDER = ["loudness", "sync pip", "clipping", "noise", "export format", "file naming"]
# When two areas account for the same number of rejects, blame the likely root cause first:
# a clipped line also fails loudness and true peak, so clipping wins over loudness.
ROOT_CAUSE_ORDER = ["clipping", "sync pip", "missing lines", "export format", "file naming", "loudness", "noise"]


def load_producers(source: str | Path | None) -> dict[str, str]:
    """Read a file -> producer mapping from a CSV or YAML path (or CSV/YAML text)."""
    if not source:
        return {}
    # Text with a line break is the mapping itself (e.g. an uploaded file); anything else is a path.
    is_text = isinstance(source, str) and ("\n" in source or "\r" in source)
    text = str(source) if is_text else Path(source).read_text()
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    if "," in first:
        rows = csv.DictReader(io.StringIO(text))
        return {r["file"].strip(): r["producer"].strip() for r in rows if r.get("file") and r.get("producer")}
    data = yaml.safe_load(text) or {}
    return {str(k).strip(): str(v).strip() for k, v in data.items()}


def build_scorecard(results: list[FileResult]) -> list[dict]:
    by_producer: dict[str, list[FileResult]] = defaultdict(list)
    for r in results:
        by_producer[r.producer or UNASSIGNED].append(r)

    rows = []
    for producer, files in sorted(by_producer.items(), key=lambda kv: (kv[0] == UNASSIGNED, kv[0])):
        ratings = Counter(r.rating for r in files)

        # First-time pass: for each deliverable, did the earliest version we have pass?
        first_versions: dict = {}
        for r in files:
            key = slot_key(r.file) or r.file
            version = (parse_valid(r.file) or {}).get("VERSION_NUM", 0)
            if key not in first_versions or version < first_versions[key][0]:
                first_versions[key] = (version, r)
        firsts = [r for _, r in first_versions.values()]
        first_pass = sum(r.passed for r in firsts) / len(firsts) if firsts else 0.0

        problems = Counter(i.code for r in files for i in r.issues if i.severity != INFO)
        offsets = [abs(r.metrics["head_pip_offset_frames"]) for r in files
                   if r.metrics.get("head_pip_offset_frames") is not None]

        rows.append({
            "producer": producer,
            "files": len(files),
            "deliverables": len(firsts),
            "first_time_pass_rate": round(first_pass, 3),
            "good": ratings.get("Good", 0),
            "acceptable": ratings.get("Acceptable with notes", 0),
            "reject": ratings.get("Reject", 0),
            "top_issues": [f"{code} ×{n}" for code, n in problems.most_common(3)],
            "avg_sync_offset_frames": round(sum(offsets) / len(offsets), 2) if offsets else None,
            "note": (f"{len(files)} file(s) with no producer in the mapping: add them to the producers file."
                     if producer == UNASSIGNED else producer_note(files)),
        })
    return rows


def producer_note(files: list[FileResult]) -> str:
    """One line an ops lead could act on, e.g.
    'Strong on loudness and clipping; 3 of 4 rejects are sync pip, so sync training needed.'"""
    areas_with_problems = {AREAS.get(i.check) for r in files for i in r.issues if i.severity != INFO}
    strengths = [a for a in STRENGTH_ORDER if a not in areas_with_problems][:2]
    strong = f"Strong on {' and '.join(strengths)}" if strengths else ""

    rejects = [r for r in files if not r.passed]
    if rejects:
        reject_areas = Counter()
        for r in rejects:
            for area in {AREAS.get(i.check) for i in r.issues if i.severity == CRITICAL}:
                reject_areas[area] += 1
        area, n = min(reject_areas.items(),
                      key=lambda kv: (-kv[1], ROOT_CAUSE_ORDER.index(kv[0]) if kv[0] in ROOT_CAUSE_ORDER else 99))
        if n == len(rejects) == 1:
            action = f"1 reject ({area}): {ACTIONS.get(area, 'follow up')}"
        else:
            action = f"{n} of {len(rejects)} rejects are {area}, so {ACTIONS.get(area, 'follow up')}"
        return f"{strong}; {action}." if strong else f"{action[0].upper()}{action[1:]}."

    warned = [r for r in files if r.issues and any(i.severity != INFO for i in r.issues)]
    if warned:
        return f"{strong}; no rejects, {len(warned)} file(s) with notes." if strong else \
            f"No rejects; {len(warned)} file(s) with notes."
    return "Clean deliveries; no action needed."
