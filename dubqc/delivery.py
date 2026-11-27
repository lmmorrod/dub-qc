"""Run every delivery check on a file and write the load-report summary."""

from __future__ import annotations

from pathlib import Path

import soundfile as sf

from . import audio_checks as ac
from .me_markers import check_voice_in_me
from .models import CRITICAL, SEVERITY_ORDER, WARNING, FileResult, Issue
from .naming import check_naming, describe, parse_valid
from .notes import check_notes, notes_for
from .spec import checks_for, spec_for_file

# Which issue codes belong to which switchable check
CODE_CHECK = {"LOUDNESS": "loudness", "SILENT": "loudness", "TRUE PEAK": "true_peak"}


def check_file(path: str | Path, spec: dict, display_name: str | None = None,
               producer: str = "", notes: list[dict] | None = None) -> FileResult:
    """Run the checks that apply to this file's stage and stem, against its version's limits."""
    path = Path(path)
    name = display_name or path.name
    result = FileResult(file=name, path=str(path), producer=producer)
    parts = parse_valid(name)
    spec, result.version = spec_for_file(spec, parts)
    result.stage = parts["STAGE"] if parts else ""
    result.stem = parts["STEM"] if parts else ""
    result.reel_timecodes = {k: spec["reel"].get(k) for k in ("fps", "session_start", "pip", "ffoa")}
    checks = checks_for(spec, result.stage or None, result.stem or None)
    result.checks_run = checks

    if "naming" in checks:
        result.issues += check_naming(name, spec)

    try:
        fmt_issues, fmt_metrics = ac.check_format(str(path), spec)
    except Exception as exc:  # unreadable file
        result.issues.append(Issue(check="Format", code="UNREADABLE", severity=CRITICAL,
                                   message=f"Couldn't read the file as audio: {exc}",
                                   fix="Check the file isn't truncated or in an unsupported format."))
        _finish(result, spec)
        return result
    if "format" in checks:
        result.issues += fmt_issues
    result.metrics.update(fmt_metrics)

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    result.duration_s = len(data) / sr

    if "loudness" in checks or "true_peak" in checks:
        issues, metrics = ac.check_loudness(data, sr, spec)
        result.issues += [i for i in issues if CODE_CHECK.get(i.code, "loudness") in checks]
        result.metrics.update(metrics)
    for key, check in (("clipping", ac.check_clipping), ("pip", ac.check_pips),
                       ("noise", ac.check_noise), ("voice_in_me", check_voice_in_me)):
        if key in checks:
            issues, metrics = check(data, sr, spec)
            result.issues += issues
            result.metrics.update(metrics)

    if notes:
        note_issues, result.notes = check_notes(data, sr, spec, notes_for(notes, parts))
        result.issues += note_issues

    result.waveform = ac.waveform_peaks(data)
    _finish(result, spec)
    return result


def check_files(paths, spec: dict, display_names=None) -> list[FileResult]:
    display_names = display_names or [None] * len(paths)
    return [check_file(p, spec, n) for p, n in zip(paths, display_names)]


def _finish(result: FileResult, spec: dict) -> None:
    for issue in result.issues:
        issue.file = result.file
    result.issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity],
                                      i.seconds if i.seconds is not None else -1))
    result.rating, result.load_report = load_report(result, spec)


def load_report(result: FileResult, spec: dict) -> tuple[str, str]:
    """A short, plain-English summary of the file, the kind you'd send back to a territory."""
    m = result.metrics
    codes = {i.code for i in result.issues}
    desc = describe(result.file, spec)
    lines = [f"{result.file}: {desc}." if desc != result.file else f"{result.file}."]

    if "UNREADABLE" in codes:
        return "Reject", lines[0] + " The file couldn't be opened. Please re-send."

    if "WRONG FORMAT" in codes:
        lines.append(f"Format is {m.get('sample_rate', 0) / 1000:g} kHz / {m.get('bit_depth')}-bit / "
                     f"{m.get('channels')} ch, which doesn't match the spec.")
    if "MISNAMED" in codes:
        lines.append("The filename doesn't follow the delivery naming convention.")

    lufs, tp = m.get("integrated_lufs"), m.get("true_peak_dbtp")
    target = spec["loudness"]
    if lufs is not None and target.get("integrated_lufs") is not None:
        verdict = "out of spec" if "LOUDNESS" in codes else "within spec"
        lines.append(f"Loudness {lufs} LUFS integrated (target {target['integrated_lufs']} ±{target['tolerance_lu']}), "
                     f"{verdict}; true peak {tp:+} dBTP"
                     f"{' (over the ' + str(target['true_peak_dbtp']) + ' dBTP ceiling)' if 'TRUE PEAK' in codes else ''}.")
    elif lufs is not None:
        lines.append(f"Loudness {lufs} LUFS integrated (no target for this version); true peak {tp:+} dBTP"
                     f"{' (over the ceiling)' if 'TRUE PEAK' in codes else ''}.")

    clips = m.get("clip_timecodes", [])
    if clips:
        shown = ", ".join(clips[:5]) + ("…" if len(clips) > 5 else "")
        lines.append(f"{len(clips)} clipping event(s) at {shown}. These need re-exporting from a clean source.")
    elif "clip_timecodes" in m:
        lines.append("No clipping.")

    if "PIP MISSING" in codes:
        lines.append("No sync pip found, so sync couldn't be confirmed.")
    elif "head_pip_offset_frames" in m:
        off = int(round(m["head_pip_offset_frames"]))
        if off == 0:
            lines.append("Sync pip is on time.")
        else:
            lines.append(f"Sync pip is {abs(off)} frame(s) {'late' if off > 0 else 'early'}, "
                         "so the track is likely out of sync from the pip onwards.")
    if "AUDIO BEFORE FFOA" in codes:
        lines.append("There's audio before first frame of action.")

    voice = m.get("me_voice_markers", [])
    if voice:
        lines.append(f"{len(voice)} passage(s) of possible voice content in the M&E at {', '.join(voice[:5])}: "
                     "listen and mark for the load.")
    missing_notes = [n for n in result.notes if n["status"] == "Silent"]
    if missing_notes:
        lines.append(f"{len(missing_notes)} noted line(s) have no audio: "
                     + ", ".join(f"{n['timecode']} ({n['type']})" for n in missing_notes) + ".")

    floor = m.get("noise_floor_dbfs")
    if floor is not None:
        lines.append(f"Noise floor around {floor:.0f} dBFS" + (" (noisy)." if "NOISE FLOOR" in codes else "."))

    severities = {i.severity for i in result.issues}
    if CRITICAL in severities:
        rating = "Reject"
        lines.append("Overall: REJECT. Please fix the critical issues and redeliver.")
    elif WARNING in severities:
        rating = "Acceptable with notes"
        lines.append("Overall: ACCEPTABLE WITH NOTES. Usable, but please look at the warnings.")
    else:
        rating = "Good"
        lines.append("Overall: GOOD. No issues found.")
    return rating, " ".join(lines)
