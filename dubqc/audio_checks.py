"""Audio checks: format, loudness, true peak, clipping, noise floor and sync pip.

Every function takes the audio as a numpy array shaped (samples, channels),
float values in -1..1, plus the sample rate and the spec.
"""

from __future__ import annotations

import numpy as np
import pyloudnorm
import soundfile as sf
from scipy import signal

from .models import CRITICAL, INFO, WARNING, Issue
from .timecode import file_seconds_to_tc, tc_to_file_seconds

SUBTYPE_BITS = {"PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32,
                "FLOAT": 32, "DOUBLE": 64}


def db(x: float) -> float:
    return 20 * np.log10(x) if x > 0 else float("-inf")


def _tc(seconds: float, spec: dict) -> str:
    reel = spec["reel"]
    return file_seconds_to_tc(seconds, reel["fps"], reel["session_start"])


# ---------------------------------------------------------------- format

def check_format(path: str, spec: dict) -> tuple[list[Issue], dict]:
    info = sf.info(path)
    want = spec["format"]
    bits = SUBTYPE_BITS.get(info.subtype)
    is_float = info.subtype in ("FLOAT", "DOUBLE")
    metrics = {
        "container": info.format,
        "sample_rate": info.samplerate,
        "bit_depth": bits,
        "sample_type": "float" if is_float else "integer",
        "channels": info.channels,
        "duration_s": round(info.duration, 3),
    }
    found = f"{info.samplerate / 1000:g} kHz / {bits}-bit{' float' if is_float else ''} / {info.channels} ch"
    expected = f"{want['sample_rate'] / 1000:g} kHz / {want['bit_depth']}-bit / {want['channels']} ch"
    problems = []
    if info.format not in ("WAV", "WAVEX", "RF64"):
        problems.append(f"file is {info.format}, not WAV")
    if info.samplerate != want["sample_rate"]:
        problems.append(f"sample rate is {info.samplerate} Hz, spec says {want['sample_rate']} Hz")
    if bits != want["bit_depth"] or is_float:
        problems.append(f"bit depth is {bits}-bit{' float' if is_float else ''}, spec says {want['bit_depth']}-bit")
    if info.channels != want["channels"]:
        problems.append(f"{info.channels} channel(s), spec says {want['channels']}")
    issues = []
    if problems:
        issues.append(Issue(
            check="Format", code="WRONG FORMAT", severity=CRITICAL,
            message="File format doesn't match the spec: " + "; ".join(problems) + ".",
            expected=expected, found=found,
            fix="Re-export from the session at the spec format. Check the session's own sample rate "
                "rather than converting the file, or the sync and pitch can shift.",
        ))
    return issues, metrics


# ---------------------------------------------------------------- loudness & true peak

def true_peak(data: np.ndarray, sr: int) -> tuple[float, float]:
    """Return (true peak dBTP, position in seconds). 4x oversampled, done in blocks to save memory."""
    block = sr * 10
    pad = 64
    best, best_pos = 0.0, 0.0
    for start in range(0, len(data), block):
        lo = max(0, start - pad)
        chunk = data[lo:start + block + pad].astype(np.float64)
        up = signal.resample_poly(chunk, 4, 1, axis=0)
        mag = np.abs(up).max(axis=1)
        # ignore the overlap so we don't count a sample twice
        keep_from = (start - lo) * 4
        keep_to = keep_from + min(block, len(data) - start) * 4
        mag = mag[keep_from:keep_to]
        if mag.size and mag.max() > best:
            best = float(mag.max())
            best_pos = (start + mag.argmax() / 4) / sr
    return db(best), best_pos


def check_loudness(data: np.ndarray, sr: int, spec: dict) -> tuple[list[Issue], dict]:
    want = spec["loudness"]
    target, tol, ceiling = want["integrated_lufs"], want["tolerance_lu"], want["true_peak_dbtp"]
    issues = []

    meter = pyloudnorm.Meter(sr)
    lufs = float(meter.integrated_loudness(data)) if len(data) > sr * 0.4 else float("-inf")
    tp, tp_pos = true_peak(data, sr)
    metrics = {"integrated_lufs": round(lufs, 1), "true_peak_dbtp": round(tp, 1),
               "true_peak_at": _tc(tp_pos, spec)}

    if not np.isfinite(lufs):
        issues.append(Issue(
            check="Loudness", code="SILENT", severity=CRITICAL,
            message="File is silent (or too short to measure loudness).",
            expected=f"{target} LUFS", found="silence",
            fix="Check the right stem was exported and the tracks weren't muted.",
        ))
    elif abs(lufs - target) > tol:
        diff = target - lufs
        issues.append(Issue(
            check="Loudness", code="LOUDNESS", severity=CRITICAL,
            message=f"Integrated loudness is {lufs:.1f} LUFS, {abs(diff):.1f} LU "
                    f"{'below' if diff > 0 else 'above'} target.",
            expected=f"{target} LUFS ±{tol}", found=f"{lufs:.1f} LUFS",
            fix=f"Overall level needs about {diff:+.1f} dB. Check it against the original version's "
                "dialogue level before just applying gain: a big difference usually means a mix problem.",
        ))
    if tp > ceiling:
        issues.append(Issue(
            check="True peak", code="TRUE PEAK", severity=CRITICAL,
            seconds=tp_pos, timecode=_tc(tp_pos, spec),
            message=f"True peak {tp:+.1f} dBTP is over the {ceiling} dBTP ceiling.",
            expected=f"≤ {ceiling} dBTP", found=f"{tp:+.1f} dBTP",
            fix=f"Pull down the line at {_tc(tp_pos, spec)} or use a true-peak limiter set to {ceiling} dBTP.",
        ))
    return issues, metrics


# ---------------------------------------------------------------- clipping

def find_clips(data: np.ndarray, sr: int, threshold: float, min_run: int,
               merge_gap_s: float = 0.25) -> list[dict]:
    """Find runs of `min_run`+ consecutive samples at full scale. Nearby runs are merged into one event."""
    hot = (np.abs(data) >= threshold).any(axis=1).astype(np.int8)
    edges = np.diff(np.concatenate(([0], hot, [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    runs = [(s, e) for s, e in zip(starts, ends) if e - s >= min_run]
    events: list[dict] = []
    for s, e in runs:
        if events and s - events[-1]["end"] <= merge_gap_s * sr:
            events[-1]["end"] = e
            events[-1]["clipped_samples"] += e - s
            events[-1]["runs"] += 1
        else:
            events.append({"start": s, "end": e, "clipped_samples": e - s, "runs": 1})
    for ev in events:
        ev["start_s"] = ev["start"] / sr
        ev["duration_s"] = (ev["end"] - ev["start"]) / sr
    return events


def check_clipping(data: np.ndarray, sr: int, spec: dict, max_listed: int = 50) -> tuple[list[Issue], dict]:
    cfg = spec["clipping"]
    events = find_clips(data, sr, cfg["threshold"], cfg["min_consecutive"])
    issues = []
    for ev in events[:max_listed]:
        tc = _tc(ev["start_s"], spec)
        issues.append(Issue(
            check="Clipping", code="CLIPPING", severity=CRITICAL,
            seconds=ev["start_s"], timecode=tc,
            message=f"Clipping: {ev['clipped_samples']} full-scale samples in {ev['runs']} run(s) "
                    f"over {ev['duration_s'] * 1000:.0f} ms.",
            expected=f"no runs of {cfg['min_consecutive']}+ full-scale samples",
            found=f"{ev['clipped_samples']} clipped samples",
            fix="Clipping is baked in: turning it down won't fix it. Ask for the line to be re-exported "
                "from an unclipped source or re-recorded.",
        ))
    if len(events) > max_listed:
        issues.append(Issue(
            check="Clipping", code="CLIPPING", severity=CRITICAL,
            message=f"…and {len(events) - max_listed} more clipping events not listed.",
        ))
    return issues, {"clip_events": len(events),
                    "clip_timecodes": [_tc(e["start_s"], spec) for e in events]}


# ---------------------------------------------------------------- noise floor

def window_rms_db(mono: np.ndarray, sr: int, win_s: float = 0.05) -> np.ndarray:
    n = int(sr * win_s)
    usable = len(mono) // n * n
    if usable == 0:
        return np.array([])
    frames = mono[:usable].reshape(-1, n).astype(np.float64)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    with np.errstate(divide="ignore"):
        return 20 * np.log10(rms)


def check_noise(data: np.ndarray, sr: int, spec: dict) -> tuple[list[Issue], dict]:
    reel = spec["reel"]
    ffoa_s = max(0.0, tc_to_file_seconds(reel["ffoa"], reel["fps"], reel["session_start"]))
    levels = window_rms_db(data.mean(axis=1)[int(ffoa_s * sr):], sr)
    if levels.size == 0:
        return [], {"noise_floor_dbfs": None}
    finite = levels[np.isfinite(levels)]
    digital_silence = levels.size - finite.size
    floor = float(np.percentile(finite, 5)) if finite.size else float("-inf")
    metrics = {"noise_floor_dbfs": round(floor, 1) if np.isfinite(floor) else None,
               "digital_silence_s": round(digital_silence * 0.05, 2)}
    issues = []
    limit = spec["noise"]["max_floor_dbfs"]
    if np.isfinite(floor) and floor > limit:
        issues.append(Issue(
            check="Noise", code="NOISE FLOOR", severity=WARNING,
            message=f"Noise floor is around {floor:.0f} dBFS (the quietest parts after FFOA).",
            expected=f"≤ {limit} dBFS", found=f"{floor:.0f} dBFS",
            fix="Listen to the gaps between lines: hum, hiss or room noise. Ask the territory for a cleaner "
                "pass or treat it with noise reduction before premix.",
        ))
    return issues, metrics


# ---------------------------------------------------------------- sync pip

def _bandpass(mono: np.ndarray, sr: int, centre: float) -> np.ndarray:
    sos = signal.butter(4, [centre * 0.7, centre * 1.4], btype="bandpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, mono)


def find_pip(mono: np.ndarray, sr: int, expected_s: float, window_s: float,
             freq: float, min_level_dbfs: float, stop_before_s: float | None = None) -> dict | None:
    """Look for a short tone burst near `expected_s`. Returns onset/length/level or None."""
    lo = max(0, int((expected_s - window_s) * sr))
    hi = min(len(mono), int((expected_s + window_s) * sr))
    if stop_before_s is not None:
        hi = min(hi, int(stop_before_s * sr))
    if hi - lo < sr * 0.01:
        return None
    seg = _bandpass(mono[lo:hi].astype(np.float64), sr, freq)
    env = np.abs(signal.hilbert(seg))
    peak = env.max()
    if db(peak) < min_level_dbfs:
        return None
    above = np.flatnonzero(env >= peak * 0.5)       # -6 dB points
    # the first contiguous block above -6 dB is the pip
    gaps = np.flatnonzero(np.diff(above) > sr * 0.005)
    first_block = above[: gaps[0] + 1] if gaps.size else above
    onset = (lo + first_block[0]) / sr
    length = (first_block[-1] - first_block[0]) / sr
    return {"onset_s": onset, "length_s": length, "level_dbfs": db(peak)}


def _check_one_pip(mono, sr, spec, label, expected_tc, stop_before_s=None) -> tuple[list[Issue], dict]:
    reel, cfg = spec["reel"], spec["pip"]
    fps = reel["fps"]
    expected_s = tc_to_file_seconds(expected_tc, fps, reel["session_start"])
    pip = find_pip(mono, sr, expected_s, cfg["search_window_s"], cfg["frequency_hz"],
                   cfg["min_level_dbfs"], stop_before_s)
    issues = []
    if pip is None:
        issues.append(Issue(
            check="Pip", code="PIP MISSING", severity=CRITICAL,
            seconds=expected_s, timecode=expected_tc,
            message=f"No {label} sync pip found within ±{cfg['search_window_s']} s of {expected_tc}.",
            expected=f"1-frame {cfg['frequency_hz']} Hz pip at {expected_tc}", found="nothing",
            fix=f"Ask for the file to be re-exported with the sync pip at {expected_tc}. "
                "Without it there's no way to confirm sync on load-in.",
        ))
        return issues, {f"{label}_pip": None}

    offset_frames = (pip["onset_s"] - expected_s) * fps
    whole = int(round(offset_frames))
    found_tc = _tc(pip["onset_s"], spec)
    metrics = {f"{label}_pip": found_tc, f"{label}_pip_offset_frames": round(offset_frames, 2)}
    if abs(whole) > cfg["tolerance_frames"]:
        direction = "late" if whole > 0 else "early"
        issues.append(Issue(
            check="Pip", code="PIP OFFSET", severity=CRITICAL,
            seconds=pip["onset_s"], timecode=found_tc,
            message=f"{label.capitalize()} pip is {abs(whole)} frame(s) {direction} "
                    f"({offset_frames:+.2f} fr). Everything after it is probably out of sync too.",
            expected=expected_tc, found=f"{found_tc} ({whole:+d} fr)",
            fix=f"Slip the whole track {abs(whole)} frame(s) {'earlier' if whole > 0 else 'later'} so the pip "
                f"lands on {expected_tc}, then spot-check sync against picture.",
        ))
    frame_s = 1 / fps
    if not (0.5 * frame_s <= pip["length_s"] <= 2 * frame_s):
        issues.append(Issue(
            check="Pip", code="PIP LENGTH", severity=WARNING,
            seconds=pip["onset_s"], timecode=found_tc,
            message=f"{label.capitalize()} pip is {pip['length_s'] * fps:.1f} frames long; should be 1 frame.",
            expected="1 frame", found=f"{pip['length_s'] * fps:.1f} frames",
            fix="Check it's actually the pip and not dialogue or a tone in the wrong place.",
        ))
    return issues, metrics


def check_pips(data: np.ndarray, sr: int, spec: dict) -> tuple[list[Issue], dict]:
    reel = spec["reel"]
    mono = data.mean(axis=1)
    ffoa_s = tc_to_file_seconds(reel["ffoa"], reel["fps"], reel["session_start"])
    issues, metrics = _check_one_pip(mono, sr, spec, "head", reel["pip"], stop_before_s=ffoa_s)

    if reel.get("lfoa"):
        from .timecode import frames_to_tc, tc_to_frames
        tail_tc = frames_to_tc(tc_to_frames(reel["lfoa"], reel["fps"]) + 2 * int(round(reel["fps"])), reel["fps"])
        more_issues, more_metrics = _check_one_pip(mono, sr, spec, "tail", tail_tc)
        issues += more_issues
        metrics.update(more_metrics)

    # Anything other than the pip before FFOA?
    pip_s = metrics.get("head_pip_offset_frames")
    expected_pip_s = tc_to_file_seconds(reel["pip"], reel["fps"], reel["session_start"])
    pip_at = expected_pip_s + (pip_s or 0) / reel["fps"]
    win = 0.05
    levels = window_rms_db(mono[: int(max(0, ffoa_s) * sr)], sr, win)
    for i, level in enumerate(levels):
        t = i * win
        near_pip = pip_at - 0.1 <= t <= pip_at + 1 / reel["fps"] + 0.1
        if level > -50 and not near_pip:
            issues.append(Issue(
                check="Pip", code="AUDIO BEFORE FFOA", severity=WARNING,
                seconds=t, timecode=_tc(t, spec),
                message=f"Audio at {level:.0f} dBFS before first frame of action ({reel['ffoa']}), "
                        "other than the pip.",
                expected=f"silence before {reel['ffoa']} apart from the pip", found=f"{level:.0f} dBFS",
                fix="Check whether a line has slipped early, or clear the pre-roll.",
            ))
            break
    return issues, metrics


# ---------------------------------------------------------------- waveform for the report

def waveform_peaks(data: np.ndarray, bins: int = 1200) -> list[float]:
    mag = np.abs(data).max(axis=1)
    if len(mag) < bins:
        return mag.round(4).tolist()
    usable = len(mag) // bins * bins
    return mag[:usable].reshape(bins, -1).max(axis=1).round(4).tolist()
