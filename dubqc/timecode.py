"""Timecode helpers (non-drop-frame, HH:MM:SS:FF)."""

from __future__ import annotations


def _base(fps: float) -> int:
    """Frame labels per second, e.g. 23.976 -> 24."""
    return int(round(fps))


def tc_to_frames(tc: str, fps: float) -> int:
    h, m, s, f = (int(p) for p in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * _base(fps) + f


def frames_to_tc(frames: int, fps: float) -> str:
    base = _base(fps)
    sign = "-" if frames < 0 else ""
    frames = abs(frames)
    f = frames % base
    s = frames // base
    return f"{sign}{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def tc_to_seconds(tc: str, fps: float) -> float:
    return tc_to_frames(tc, fps) / fps


def file_seconds_to_tc(seconds: float, fps: float, session_start: str) -> str:
    """Convert a position in the file (seconds from the top) to session timecode."""
    return frames_to_tc(tc_to_frames(session_start, fps) + int(round(seconds * fps)), fps)


def tc_to_file_seconds(tc: str, fps: float, session_start: str) -> float:
    """Convert session timecode to a position in the file (seconds from the top)."""
    return (tc_to_frames(tc, fps) - tc_to_frames(session_start, fps)) / fps
