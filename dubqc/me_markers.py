"""M&E marker pass: find voice content (walla, breaths, efforts, stray dialogue) in music & effects stems.

Speech has a tell-tale rhythm: its level in the voice band (roughly 300 Hz to 3.4 kHz) rises
and falls 3 to 8 times a second, once per syllable. Music and effects rarely pulse at exactly
that rate. So for each second of audio we measure how much of the voice band's level movement
sits at syllable rate, and flag passages where that share stays high.

It's a pointer, not a verdict: every marker is something for an editor to listen to and confirm.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .models import INFO, Issue
from .timecode import file_seconds_to_tc, tc_to_file_seconds

ENV_RATE = 100          # envelope samples per second
WINDOW_S = 1.0
HOP_S = 0.25


def voice_scores(mono: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (window start times, syllable-rate score 0..1, voice-band level dBFS) per window."""
    sos = signal.butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    band = signal.sosfilt(sos, mono.astype(np.float64))
    hop = sr // ENV_RATE
    n = len(band) // hop
    if n < ENV_RATE * WINDOW_S:
        return np.array([]), np.array([]), np.array([])
    env = np.sqrt((band[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)

    win = int(WINDOW_S * ENV_RATE)
    step = int(HOP_S * ENV_RATE)
    freqs = np.fft.rfftfreq(win, 1 / ENV_RATE)
    syllable = (freqs >= 3) & (freqs <= 8)
    movement = (freqs >= 0.5) & (freqs <= 20)
    taper = np.hanning(win)
    starts, scores, levels = [], [], []
    for i in range(0, n - win + 1, step):
        seg = env[i:i + win]
        spectrum = np.abs(np.fft.rfft((seg - seg.mean()) * taper)) ** 2
        total = spectrum[movement].sum()
        scores.append(spectrum[syllable].sum() / total if total > 0 else 0.0)
        levels.append(20 * np.log10(np.sqrt((seg ** 2).mean())))
        starts.append(i / ENV_RATE)
    return np.array(starts), np.array(scores), np.array(levels)


def find_voice(data: np.ndarray, sr: int, spec: dict) -> list[dict]:
    """Passages after FFOA that look like voice: [{start_s, end_s, score}]."""
    cfg = spec["voice_in_me"]
    reel = spec["reel"]
    ffoa_s = max(0.0, tc_to_file_seconds(reel["ffoa"], reel["fps"], reel["session_start"]))
    starts, scores, levels = voice_scores(data.mean(axis=1), sr)
    hot = (scores >= cfg["min_score"]) & (levels >= cfg["min_level_dbfs"]) & (starts >= ffoa_s)

    passages: list[dict] = []
    for t, s, flag in zip(starts, scores, hot):
        if not flag:
            continue
        if passages and t <= passages[-1]["end_s"]:
            passages[-1]["end_s"] = t + WINDOW_S
            passages[-1]["score"] = max(passages[-1]["score"], s)
        else:
            passages.append({"start_s": t, "end_s": t + WINDOW_S, "score": s})
    return [p for p in passages if p["end_s"] - p["start_s"] >= cfg["min_duration_s"] + WINDOW_S - HOP_S]


def check_voice_in_me(data: np.ndarray, sr: int, spec: dict) -> tuple[list[Issue], dict]:
    reel = spec["reel"]
    passages = find_voice(data, sr, spec)
    issues = []
    for p in passages:
        tc = file_seconds_to_tc(p["start_s"], reel["fps"], reel["session_start"])
        end_tc = file_seconds_to_tc(p["end_s"], reel["fps"], reel["session_start"])
        issues.append(Issue(
            check="M&E markers", code="VOICE IN M&E", severity=INFO,
            seconds=p["start_s"], timecode=tc,
            message=f"Possible voice content (walla, breath, effort or dialogue) from {tc} to {end_tc}.",
            expected="music and effects only, or voice content marked for the load",
            found=f"{p['end_s'] - p['start_s']:.1f} s, confidence {p['score']:.0%}",
            fix="Listen and confirm. If it's voice, mark it for the load template so the dub "
                "doesn't double it; if it's walla, note whether it's complete.",
        ))
    return issues, {"me_voice_markers": [i.timecode for i in issues]}
