"""Make synthetic test WAVs so the checker can be tried before real recordings exist.

The "dialogue" is band-limited noise shaped into syllables: it isn't speech,
but it has the right level, peaks and gaps for the delivery checks.

Session layout (matches the demo specs): each file starts at the reel's
session start (R1 01:00:00:00, R2 02:00:00:00, ...), with a 1-frame 1 kHz pip
6 s in and the first line 8 s in (FFOA).

Everything here is made up: titles, producers and problems.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pyloudnorm
import soundfile as sf
from scipy import signal

SR = 48000
FPS = 24
PIP_S = 6.0
LINES = [(8.0, 2.4), (11.2, 2.0), (14.0, 2.8), (17.6, 1.8), (20.4, 2.6),
         (23.8, 2.2), (26.8, 2.5), (30.0, 2.0), (32.8, 2.4), (35.9, 1.9)]
LENGTH_S = 39.0


def _line(duration: float, rng: np.random.Generator) -> np.ndarray:
    n = int(duration * SR)
    t = np.arange(n) / SR
    sos = signal.butter(4, [150, 3500], btype="bandpass", fs=SR, output="sos")
    noise = signal.sosfilt(sos, rng.standard_normal(n))
    syllables = (0.5 - 0.5 * np.cos(2 * np.pi * rng.uniform(3.5, 5.5) * t)) ** 1.5
    phrase = 0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(0.3, 0.7) * t + rng.uniform(0, 6))
    fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.03)
    return noise * syllables * phrase * fade


def _music(n: int, rng: np.random.Generator) -> np.ndarray:
    """A slow chord bed: notes change every 2 s and swell gently, so the level never pulses at speech rate."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    roots = rng.choice([110.0, 130.8, 146.8, 164.8, 196.0], size=int(n / SR / 2) + 1)
    chord_env = 0.75 + 0.25 * np.sin(2 * np.pi * 0.25 * t)
    for k, root in enumerate(roots):
        a, b = int(k * 2 * SR), min(n, int((k + 1) * 2 * SR))
        if a >= n:
            break
        seg_t = t[a:b] - t[a]
        fade = np.minimum(1, np.minimum(seg_t, seg_t[::-1]) / 0.25)
        for ratio, amp in ((1, 1.0), (1.25, 0.6), (1.5, 0.5), (2, 0.3), (3, 0.15)):
            out[a:b] += amp * fade * np.sin(2 * np.pi * root * ratio * seg_t)
    return out * chord_env


def _effects(n: int, rng: np.random.Generator) -> np.ndarray:
    """Steady low ambience plus an occasional impact (door, footstep)."""
    sos = signal.butter(2, 800, btype="lowpass", fs=SR, output="sos")
    out = 0.3 * signal.sosfilt(sos, rng.standard_normal(n))
    t = 0.0
    while t < n / SR:
        t += rng.uniform(2.0, 3.5)
        i = int(t * SR)
        m = min(int(0.4 * SR), n - i)
        if m <= 0:
            break
        decay = np.exp(-np.arange(m) / (0.06 * SR))
        out[i:i + m] += 0.7 * decay * signal.sosfilt(sos, rng.standard_normal(m))
    return out


def make_dialogue(seed: int = 1, pip_offset_frames: int = 0, clip_line: int | None = None,
                  include_pip: bool = True, n_lines: int | None = None, gain_db: float = 0.0,
                  blip_at_s: float | None = None, kind: str = "DX", drop_line: int | None = None,
                  walla: tuple[float, float] | None = None) -> np.ndarray:
    """Return a mono float array at 48 kHz.

    pip_offset_frames: move the pip this many frames late (negative = early)
    clip_line:        1-based line number pushed hard into clipping
    n_lines:          only use the first n lines (shorter file)
    gain_db:          level change after normalising to -23 LUFS
    blip_at_s:        a short click at this position (e.g. before FFOA)
    kind:             DX (dialogue), MX (music) or FX (effects)
    drop_line:        1-based line number left out (a line that never made it into the mix)
    walla:            (start_s, end_s) of background voices mixed in (e.g. walla left in a music or effects stem)
    """
    rng = np.random.default_rng(seed)
    lines = LINES[:n_lines] if n_lines else LINES
    length = LENGTH_S if not n_lines else lines[-1][0] + lines[-1][1] + 2.0
    out = np.zeros(int(length * SR))
    if kind == "DX":
        for k, (start, dur) in enumerate(lines, 1):
            seg = _line(dur, rng)
            if k == drop_line:
                continue
            i = int(start * SR)
            out[i:i + len(seg)] += seg
    else:
        ffoa = int(8.0 * SR)
        bed = _music(len(out) - ffoa, rng) if kind == "MX" else _effects(len(out) - ffoa, rng)
        out[ffoa:] += bed
    if walla:
        a, b = walla
        for _ in range(3):                                           # a few overlapping voices
            seg = 0.5 * _line(b - a, rng)
            i = int(a * SR)
            out[i:i + len(seg)] += seg * (1 if kind == "DX" else 1.5)
    out += rng.standard_normal(len(out)) * 10 ** (-75 / 20)         # room tone, about -75 dBFS
    meter = pyloudnorm.Meter(SR)
    out = pyloudnorm.normalize.loudness(out, meter.integrated_loudness(out), -23.0)
    out *= 10 ** (gain_db / 20)

    if clip_line is not None:
        start, dur = lines[clip_line - 1]
        a, b = int(start * SR), int((start + dur) * SR)
        out[a:b] *= 12

    if blip_at_s is not None:
        i = int(blip_at_s * SR)
        out[i:i + 480] += 0.3 * np.hanning(480) * np.sin(2 * np.pi * 300 * np.arange(480) / SR)

    if include_pip:
        n = SR // FPS                                                # exactly one frame
        i = int(round((PIP_S + pip_offset_frames / FPS) * SR))
        out[i:i + n] += 10 ** (-20 / 20) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)

    full_scale = 1 - 2 ** -23
    return np.clip(out, -full_scale, full_scale)


def write_demo_set(folder: str | Path) -> list[Path]:
    """Three single-reel files: clean, errors, misnamed."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = [
        ("TEST_SPC_R1_DX_PMX_v01.wav", make_dialogue(), "PCM_24"),
        ("TEST_SPC_R1_DX_PMX_v02.wav", make_dialogue(pip_offset_frames=3, clip_line=8), "PCM_24"),
        ("Test_Spanish_R1_DX_final.wav", make_dialogue(), "PCM_16"),
    ]
    paths = []
    for name, audio, subtype in files:
        path = folder / name
        sf.write(path, audio, SR, subtype=subtype)
        paths.append(path)
    return paths


# ---------------------------------------------------------------- multi-territory batch

TITLE = "TEST"

# (filename, producer, make_dialogue options, subtype). Planted ops problems:
#   SPC R3 DX never arrives                                  -> Missing
#   FRA R2 FX arrives twice as v02 (PMX and PMR)             -> Duplicate, no clear latest
#   GER R4 DX (no reel 4 on this show) + a badly named file  -> Unexpected
#   SPC R1 DX v01 rejected (pip +3, clipping); v02 fixes the pip,
#     still clips, and adds a click before FFOA              -> Redelivery: fixed / still present / new
#   GER producer: 3 of 4 rejects are sync pip                -> Scorecard flags sync training
#   SPC R2 FX exported 16-bit                                -> Format reject
#   SPC R3 FX has walla left in it                           -> voice marker for the load
#   GER R3 DX dropped line 3, which an editor note covers    -> Noted content missing
def _plan() -> list[tuple[str, str, dict, str]]:
    plan = []

    def add(terr, reel, stem, producer, version=1, stage="PMX", subtype="PCM_24", **opts):
        name = f"{TITLE}_{terr}_R{reel}_{stem}_{stage}_v{version:02d}.wav"
        opts.setdefault("kind", stem if stem in ("MX", "FX") else "DX")
        plan.append((name, producer, opts, subtype))

    # Spain: Ana does dialogue, Sam does music and effects
    add("SPC", 1, "DX", "Ana Ortega", 1, pip_offset_frames=3, clip_line=3)
    add("SPC", 1, "DX", "Ana Ortega", 2, clip_line=3, blip_at_s=7.0)
    add("SPC", 2, "DX", "Ana Ortega")
    for reel in (1, 2, 3):
        add("SPC", reel, "MX", "Sam Patel")
        add("SPC", reel, "FX", "Sam Patel", subtype="PCM_16" if reel == 2 else "PCM_24",
            **({"walla": (12.0, 15.0)} if reel == 3 else {}))
    # France: Lucie, all clean, but R2 FX sent twice as v02
    for reel in (1, 2, 3):
        for stem in ("DX", "MX"):
            add("FRA", reel, stem, "Lucie Martin")
        add("FRA", reel, "FX", "Lucie Martin", version=2 if reel == 2 else 1)
    add("FRA", 2, "FX", "Lucie Martin", version=2, stage="PMR")
    # Germany: Jonas, mostly sync problems
    issues = {(1, "DX"): {"pip_offset_frames": 2}, (2, "DX"): {"pip_offset_frames": -1},
              (3, "MX"): {"pip_offset_frames": 4}, (2, "FX"): {"gain_db": 2.0},
              (3, "DX"): {"drop_line": 3}}
    for reel in (1, 2, 3):
        for stem in ("DX", "MX", "FX"):
            add("GER", reel, stem, "Jonas Weber", **issues.get((reel, stem), {}))
    add("GER", 4, "DX", "Jonas Weber")
    plan.append(("GER_R2_DX_final_mix.wav", "", {"seed": 77}, "PCM_24"))
    return plan


BATCH_PLAN = _plan()


# Editor notes for the demo batch. Line timings: line 2 runs 11.2-13.2 s, line 3 14.0-16.8 s,
# line 4 17.6-19.4 s into each reel.
DEMO_NOTES = [
    ("reel", "timecode", "type", "note", "stem", "territory"),
    ("1", "01:00:11:12", "off-screen line", "Guard calls out from behind the door", "DX", ""),
    ("2", "02:00:17:18", "breath", "Breath before the reply must stay", "DX", ""),
    ("3", "03:00:14:12", "off-screen line", "Radio voice under the music: easy to miss", "DX", ""),
]


def write_demo_batch(folder: str | Path, n_lines: int = 4) -> tuple[list[Path], Path]:
    """Write the batch WAVs plus producers.csv and editor_notes.csv into `folder`.
    Returns (wav paths, producers csv path)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (name, _producer, opts, subtype) in enumerate(BATCH_PLAN):
        opts = {"seed": i + 100, **opts, "n_lines": n_lines}
        path = folder / name
        sf.write(path, make_dialogue(**opts), SR, subtype=subtype)
        paths.append(path)
    csv_path = folder / "producers.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "producer"])
        for name, producer, _, _ in BATCH_PLAN:
            if producer:
                w.writerow([name, producer])
    with open(folder / "editor_notes.csv", "w", newline="") as fh:
        csv.writer(fh).writerows(DEMO_NOTES)
    return paths, csv_path
