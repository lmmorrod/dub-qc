"""Make synthetic test WAVs so the checker can be tried before real recordings exist.

The "dialogue" is band-limited noise shaped into syllables: it isn't speech,
but it has the right level, peaks and gaps for the delivery checks.

Session layout (matches the demo spec): file starts at 01:00:00:00,
1-frame 1 kHz pip at 01:00:06:00, first line at 01:00:08:00.
"""

from __future__ import annotations

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
                  include_pip: bool = True) -> np.ndarray:
    """Return a mono float array at 48 kHz."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(LENGTH_S * SR))
    for start, dur in LINES:
        seg = _line(dur, rng)
        i = int(start * SR)
        out[i:i + len(seg)] += seg
    out += rng.standard_normal(len(out)) * 10 ** (-75 / 20)         # room tone, about -75 dBFS
    meter = pyloudnorm.Meter(SR)
    out = pyloudnorm.normalize.loudness(out, meter.integrated_loudness(out), -23.0)

    if clip_line is not None:   # 1-based line number, pushed hard into clipping
        start, dur = LINES[clip_line - 1]
        a, b = int(start * SR), int((start + dur) * SR)
        out[a:b] *= 12

    if include_pip:
        n = SR // FPS                                                # exactly one frame
        i = int(round((PIP_S + pip_offset_frames / FPS) * SR))
        out[i:i + n] += 10 ** (-20 / 20) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)

    full_scale = 1 - 2 ** -23
    return np.clip(out, -full_scale, full_scale)


def write_demo_set(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = [
        # clean delivery: should pass
        ("LASTTRAIN_SPC_R1_DX_PMX_v01.wav", make_dialogue(), "PCM_24"),
        # pip 3 frames late, line 8 clipped
        ("LASTTRAIN_SPC_R1_DX_PMX_v02.wav", make_dialogue(pip_offset_frames=3, clip_line=8), "PCM_24"),
        # misnamed, and 16-bit
        ("LastTrain_Spanish_R1_DX_final.wav", make_dialogue(), "PCM_16"),
    ]
    paths = []
    for name, audio, subtype in files:
        path = folder / name
        sf.write(path, audio, SR, subtype=subtype)
        paths.append(path)
    return paths
