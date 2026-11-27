"""Run every delivery check on a file and write the load-report summary."""

from __future__ import annotations

from pathlib import Path

import soundfile as sf

from . import audio_checks as ac
from .models import CRITICAL, SEVERITY_ORDER, WARNING, FileResult
from .naming import check_naming, describe, parse_valid
from .spec import spec_for_reel


def check_file(path: str | Path, spec: dict, display_name: str | None = None,
               producer: str = "") -> FileResult:
    path = Path(path)
    name = display_name or path.name
    result = FileResult(file=name, path=str(path), producer=producer)
    parts = parse_valid(name)
    spec = spec_for_reel(spec, parts["REEL_NUM"] if parts else None)
    result.reel_timecodes = {k: spec["reel"].get(k) for k in ("fps", "session_start", "pip", "ffoa")}

    result.issues += check_naming(name, spec)

    try:
        fmt_issues, fmt_metrics = ac.check_format(str(path), spec)
    except Exception as exc:  # unreadable file
        from .models import Issue
        result.issues.append(Issue(check="Format", code="UNREADABLE", severity=CRITICAL,
                                   message=f"Couldn't read the file as audio: {exc}",
                                   fix="Check the file isn't truncated or in an unsupported format."))
        _finish(result, spec)
        return result
    result.issues += fmt_issues
    result.metrics.update(fmt_metrics)

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    result.duration_s = len(data) / sr

    for check in (ac.check_loudness, ac.check_clipping, ac.check_pips, ac.check_noise):
        issues, metrics = check(data, sr, spec)
        result.issues += issues
        result.metrics.update(metrics)

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
    if lufs is not None:
        verdict = "out of spec" if "LOUDNESS" in codes else "within spec"
        lines.append(f"Loudness {lufs} LUFS integrated (target {target['integrated_lufs']} ±{target['tolerance_lu']}), "
                     f"{verdict}; true peak {tp:+} dBTP"
                     f"{' (over the ' + str(target['true_peak_dbtp']) + ' dBTP ceiling)' if 'TRUE PEAK' in codes else ''}.")

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
