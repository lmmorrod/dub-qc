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


def make_dialogue(seed: int = 1, pip_offset_frames: int = 0, clip_line: int | None = None,
                  include_pip: bool = True, n_lines: int | None = None, gain_db: float = 0.0,
                  blip_at_s: float | None = None) -> np.ndarray:
    """Return a mono float array at 48 kHz.

    pip_offset_frames: move the pip this many frames late (negative = early)
    clip_line:        1-based line number pushed hard into clipping
    n_lines:          only use the first n lines (shorter file)
    gain_db:          level change after normalising to -23 LUFS
    blip_at_s:        a short click at this position (e.g. before FFOA)
    """
    rng = np.random.default_rng(seed)
    lines = LINES[:n_lines] if n_lines else LINES
    length = LENGTH_S if not n_lines else lines[-1][0] + lines[-1][1] + 2.0
    out = np.zeros(int(length * SR))
    for start, dur in lines:
        seg = _line(dur, rng)
        i = int(start * SR)
        out[i:i + len(seg)] += seg
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
def _plan() -> list[tuple[str, str, dict, str]]:
    plan = []

    def add(terr, reel, stem, producer, version=1, stage="PMX", subtype="PCM_24", **opts):
        name = f"{TITLE}_{terr}_R{reel}_{stem}_{stage}_v{version:02d}.wav"
        plan.append((name, producer, opts, subtype))

    # Spain: Ana does dialogue, Sam does music and effects
    add("SPC", 1, "DX", "Ana Ortega", 1, pip_offset_frames=3, clip_line=3)
    add("SPC", 1, "DX", "Ana Ortega", 2, clip_line=3, blip_at_s=7.0)
    add("SPC", 2, "DX", "Ana Ortega")
    for reel in (1, 2, 3):
        add("SPC", reel, "MX", "Sam Patel")
        add("SPC", reel, "FX", "Sam Patel", subtype="PCM_16" if reel == 2 else "PCM_24")
    # France: Lucie, all clean, but R2 FX sent twice as v02
    for reel in (1, 2, 3):
        for stem in ("DX", "MX"):
            add("FRA", reel, stem, "Lucie Martin")
        add("FRA", reel, "FX", "Lucie Martin", version=2 if reel == 2 else 1)
    add("FRA", 2, "FX", "Lucie Martin", version=2, stage="PMR")
    # Germany: Jonas, mostly sync problems
    issues = {(1, "DX"): {"pip_offset_frames": 2}, (2, "DX"): {"pip_offset_frames": -1},
              (3, "MX"): {"pip_offset_frames": 4}, (2, "FX"): {"gain_db": 2.0}}
    for reel in (1, 2, 3):
        for stem in ("DX", "MX", "FX"):
            add("GER", reel, stem, "Jonas Weber", **issues.get((reel, stem), {}))
    add("GER", 4, "DX", "Jonas Weber")
    plan.append(("GER_R2_DX_final_mix.wav", "", {"seed": 77}, "PCM_24"))
    return plan


BATCH_PLAN = _plan()


def write_demo_batch(folder: str | Path, n_lines: int = 4) -> tuple[list[Path], Path]:
    """Write the batch WAVs plus producers.csv into `folder`. Returns (wav paths, csv path)."""
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
    return paths, csv_path
